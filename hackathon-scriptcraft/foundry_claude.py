"""Claude-compatible client backed by a Foundry (Azure OpenAI) deployment.

The desktop app calls Anthropic directly for the Idea Generator, briefs,
titles and the explainer video planner. A hackathon sandbox usually has no
Anthropic key and cannot deploy Claude (the marketplace terms need company
details), so container_app.py swaps web_gui._get_anthropic_client for this
shim when ANTHROPIC_API_KEY is empty and a Foundry resource is configured.

It implements the small part of the Anthropic SDK the app uses:
  client.messages.create(**kwargs)          -> Message
  client.messages.stream(**kwargs)          -> context manager (events + get_final_message)
  client.beta.messages.stream(**kwargs)     -> same
Auth is Entra ID (managed identity in Container Apps); no key is read.
Server-side web search is not available on this path, so tools are dropped.

Settings:
  FOUNDRY_CHAT_DEPLOYMENT   deployment to call (default MAF_CLAUDE_MODEL)
  FOUNDRY_OPENAI_ENDPOINT   default https://<MAF_FOUNDRY_RESOURCE>.openai.azure.com/
  FOUNDRY_SHIM_EFFORT       reasoning effort for gpt-5 class models (default low)
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import threading
from types import SimpleNamespace

logger = logging.getLogger("foundry_claude")

_SCOPE = "https://cognitiveservices.azure.com/.default"
_USAGE = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
_USAGE_LOCK = threading.Lock()


def configured() -> bool:
    return bool(_endpoint() and _deployment())


def _endpoint() -> str:
    ep = (os.environ.get("FOUNDRY_OPENAI_ENDPOINT") or "").strip()
    if ep:
        return ep
    res = (os.environ.get("MAF_FOUNDRY_RESOURCE") or "").strip()
    return f"https://{res}.openai.azure.com/" if res else ""


def _deployment() -> str:
    return ((os.environ.get("FOUNDRY_CHAT_DEPLOYMENT") or "").strip()
            or (os.environ.get("MAF_CLAUDE_MODEL") or "").strip())


def usage_totals() -> dict:
    with _USAGE_LOCK:
        return dict(_USAGE)


def _record(inp: int, out: int) -> None:
    with _USAGE_LOCK:
        _USAGE["calls"] += 1
        _USAGE["input_tokens"] += int(inp or 0)
        _USAGE["output_tokens"] += int(out or 0)
        tot = dict(_USAGE)
    logger.info("🧮 Foundry shim usage: in=%s out=%s | totals %s", inp, out, tot)
    print(f"🧮 Foundry shim usage: in={inp} out={out} | totals {tot}", flush=True)


def _pdf_text(data_b64: str) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(base64.b64decode(data_b64)))
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception as e:  # pragma: no cover - best effort
        return f"[PDF could not be read: {e}]"


def _convert_block(b) -> list:
    if isinstance(b, str):
        return [{"type": "text", "text": b}]
    if not isinstance(b, dict):
        b = getattr(b, "model_dump", lambda: {"type": getattr(b, "type", ""), "text": getattr(b, "text", "")})()
    t = b.get("type")
    if t == "text":
        return [{"type": "text", "text": b.get("text", "")}]
    if t == "image":
        src = b.get("source") or {}
        if src.get("type") == "base64":
            return [{"type": "image_url", "image_url": {
                "url": f"data:{src.get('media_type', 'image/png')};base64,{src.get('data', '')}"}}]
        if src.get("type") == "url":
            return [{"type": "image_url", "image_url": {"url": src.get("url")}}]
        return []
    if t == "document":
        src = b.get("source") or {}
        title = b.get("title") or "attached document"
        if src.get("type") == "text":
            body = src.get("data", "")
        elif src.get("type") == "base64" and "pdf" in (src.get("media_type") or ""):
            body = _pdf_text(src.get("data", ""))
        elif src.get("type") == "base64":
            try:
                body = base64.b64decode(src.get("data", "")).decode("utf-8", "replace")
            except Exception:
                body = ""
        elif src.get("type") == "content":
            body = "\n".join(x.get("text", "") for x in src.get("content") or [] if isinstance(x, dict))
        else:
            body = ""
        return [{"type": "text", "text": f"<document title=\"{title}\">\n{body}\n</document>"}]
    # tool_use / tool_result / thinking blocks have no chat-completions form here.
    return []


def _messages(system, messages) -> list:
    out = []
    if system:
        if isinstance(system, str):
            text = system
        else:
            text = "\n\n".join((s.get("text", "") if isinstance(s, dict) else str(s)) for s in system)
        out.append({"role": "system", "content": text})
    for m in messages or []:
        role = m.get("role", "user")
        content = m.get("content")
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue
        parts = []
        for b in content or []:
            parts.extend(_convert_block(b))
        if role == "assistant":
            out.append({"role": "assistant",
                        "content": "".join(p.get("text", "") for p in parts if p["type"] == "text")})
        elif all(p["type"] == "text" for p in parts):
            out.append({"role": role, "content": "\n\n".join(p["text"] for p in parts)})
        else:
            out.append({"role": role, "content": parts})
    return out


def _message(text: str, finish: str, inp: int, out: int):
    stop = {"length": "max_tokens", "content_filter": "refusal"}.get(finish or "", "end_turn")
    return SimpleNamespace(
        id="foundry", type="message", role="assistant", model=_deployment(),
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason=stop, stop_details=None,
        usage=SimpleNamespace(input_tokens=inp, output_tokens=out,
                              cache_creation_input_tokens=0, cache_read_input_tokens=0))


class _Messages:
    def __init__(self, owner: "FoundryAnthropic"):
        self._o = owner

    def _request(self, kwargs: dict) -> dict:
        max_tokens = int(kwargs.get("max_tokens") or 4000)
        req = dict(model=_deployment(),
                   messages=_messages(kwargs.get("system"), kwargs.get("messages")),
                   # Reasoning tokens count against the limit; leave headroom.
                   max_completion_tokens=min(128000, max_tokens + 16000))
        effort = (os.environ.get("FOUNDRY_SHIM_EFFORT") or "low").strip()
        if effort and effort != "none":
            req["reasoning_effort"] = effort
        fmt = (kwargs.get("output_config") or {}).get("format")
        if isinstance(fmt, dict) and fmt.get("type") == "json_schema" and fmt.get("schema"):
            req["response_format"] = {"type": "json_schema", "json_schema": {
                "name": "output", "schema": fmt["schema"], "strict": False}}
        return req

    def _call(self, req: dict, stream: bool):
        import openai
        try:
            return self._o._client().chat.completions.create(stream=stream, **(
                {**req, "stream_options": {"include_usage": True}} if stream else req))
        except openai.BadRequestError as e:
            msg = str(e).lower()
            changed = False
            if "response_format" in req and ("response_format" in msg or "json_schema" in msg or "schema" in msg):
                req.pop("response_format"); changed = True
            if "reasoning_effort" in req and "reasoning" in msg:
                req.pop("reasoning_effort"); changed = True
            if not changed:
                raise
            logger.warning("Foundry shim: retrying without an unsupported option (%s)", str(e)[:160])
            return self._call(req, stream)

    def create(self, **kwargs):
        if kwargs.get("stream"):
            raise NotImplementedError("use messages.stream")
        req = self._request(kwargs)
        resp = self._call(req, stream=False)
        choice = resp.choices[0]
        u = resp.usage
        inp, out = (u.prompt_tokens, u.completion_tokens) if u else (0, 0)
        _record(inp, out)
        return _message(choice.message.content or "", choice.finish_reason, inp, out)

    def stream(self, **kwargs):
        return _Stream(self, self._request(kwargs))

    def count_tokens(self, **kwargs):
        text = json.dumps(_messages(kwargs.get("system"), kwargs.get("messages")))
        return SimpleNamespace(input_tokens=len(text) // 4)


class _Stream:
    def __init__(self, messages: _Messages, req: dict):
        self._m, self._req = messages, req
        self._parts, self._finish, self._usage = [], None, (0, 0)
        self._final = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        resp = self._m._call(dict(self._req), stream=True)
        yield SimpleNamespace(type="message_start")
        for chunk in resp:
            if getattr(chunk, "usage", None):
                self._usage = (chunk.usage.prompt_tokens, chunk.usage.completion_tokens)
            for c in chunk.choices or []:
                piece = getattr(c.delta, "content", None)
                if piece:
                    self._parts.append(piece)
                    yield SimpleNamespace(type="content_block_delta", index=0,
                                          delta=SimpleNamespace(type="text_delta", text=piece))
                if c.finish_reason:
                    self._finish = c.finish_reason
        _record(*self._usage)
        self._final = _message("".join(self._parts), self._finish, *self._usage)
        yield SimpleNamespace(type="message_stop")

    def get_final_message(self):
        if self._final is None:
            for _ in self:
                pass
        return self._final

    @property
    def text_stream(self):
        for ev in self:
            if ev.type == "content_block_delta":
                yield ev.delta.text


class FoundryAnthropic:
    """Duck-typed stand-in for anthropic.Anthropic."""

    _shared = None
    _lock = threading.Lock()

    def __init__(self, timeout: float = 60.0, max_retries: int = 6):
        self.timeout, self.max_retries = timeout, max_retries
        self.messages = _Messages(self)
        self.beta = SimpleNamespace(messages=self.messages)

    def _client(self):
        from openai import AzureOpenAI
        with FoundryAnthropic._lock:
            if FoundryAnthropic._shared is None:
                from azure.identity import DefaultAzureCredential, get_bearer_token_provider
                FoundryAnthropic._shared = get_bearer_token_provider(DefaultAzureCredential(), _SCOPE)
        return AzureOpenAI(azure_endpoint=_endpoint(), api_version="2025-04-01-preview",
                           azure_ad_token_provider=FoundryAnthropic._shared,
                           timeout=max(self.timeout, 120.0), max_retries=self.max_retries)
