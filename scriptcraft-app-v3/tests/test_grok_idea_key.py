"""Idea Generator Grok key: desktop XAI_API_KEY and container GROK_API_KEY.

The desktop app loads XAI_API_KEY from the repo-root .env. The container deploy
stored that credential as GROK_API_KEY and the idea generator only read
XAI_API_KEY, so Grok ideas failed in the cloud. These checks use dummy
credentials and a fake xAI client. They never call the network.
"""
from __future__ import annotations

import importlib.util
import json
import logging
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
LOCAL_APP = HERE.parent
REPO = LOCAL_APP.parent
CONTAINER_APP = REPO / "scriptcraft-app-v3-container"

_TMP = Path(tempfile.mkdtemp(prefix="sc-grok-key-"))
_SETTINGS = _TMP / "settings.json"
_SETTINGS.write_text("{}")
_HISTORY = _TMP / "idea_generator.json"
os.environ["SCRIPTCRAFT_SETTINGS_FILE"] = str(_SETTINGS)
os.environ["SCRIPTCRAFT_IDEAS_HISTORY_FILE"] = str(_HISTORY)
os.environ.pop("APP_AUTH_TOKEN", None)
for _name in ("XAI_API_KEY", "GROK_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
    os.environ.pop(_name, None)

sys.path.insert(0, str(LOCAL_APP))
import web_gui as local_gui  # noqa: E402


def _load_container():
    spec = importlib.util.spec_from_file_location(
        "container_web_gui", CONTAINER_APP / "web_gui.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["container_web_gui"] = module
    spec.loader.exec_module(module)
    return module


container_gui = _load_container()

LOCAL = "xai-test-local-1111"
CONTAINER = "xai-test-container-2222"
SAVED = "xai-test-saved-3333"
FRESH = "xai-test-fresh-4444"
_KEY_ENV = ("XAI_API_KEY", "GROK_API_KEY", "GOOGLE_API_KEY")


def _write_settings(data: dict) -> None:
    _SETTINGS.write_text(json.dumps(data))


@pytest.fixture(params=["local", "container"])
def gui(request):
    """Each case runs against the desktop module and the container copy."""
    module = {"local": local_gui, "container": container_gui}[request.param]
    saved_env = {name: os.environ.get(name) for name in _KEY_ENV}
    _write_settings({})
    for name in _KEY_ENV:
        os.environ.pop(name, None)
    yield module
    _write_settings({})
    for name, value in saved_env.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def _install_fake_xai(monkeypatch, seen: list, content: str = "", boom: str = ""):
    class FakeChat:
        def append(self, *_args, **_kwargs):
            return None

        def sample(self):
            return types.SimpleNamespace(content=content, server_side_tool_usage=None)

    class FakeClient:
        def __init__(self, api_key=None):
            seen.append(api_key)
            if boom:
                raise RuntimeError(boom.format(key=api_key))
            self.chat = types.SimpleNamespace(create=lambda **_kw: FakeChat())

    sdk = types.ModuleType("xai_sdk")
    sdk.Client = FakeClient
    chat = types.ModuleType("xai_sdk.chat")
    chat.system = lambda text: text
    chat.user = lambda text: text
    tools = types.ModuleType("xai_sdk.tools")
    tools.web_search = lambda: "web"
    tools.x_search = lambda **_kw: "x"
    monkeypatch.setitem(sys.modules, "xai_sdk", sdk)
    monkeypatch.setitem(sys.modules, "xai_sdk.chat", chat)
    monkeypatch.setitem(sys.modules, "xai_sdk.tools", tools)


def _capture(module):
    records = []

    class _Handler(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = _Handler()
    module.logger.addHandler(handler)
    return records, handler


def test_desktop_env_name_wins_over_container_name(gui):
    os.environ["XAI_API_KEY"] = LOCAL
    os.environ["GROK_API_KEY"] = CONTAINER
    assert gui._resolve_xai_api_key() == LOCAL


def test_container_env_name_used_when_desktop_name_missing(gui):
    os.environ["GROK_API_KEY"] = CONTAINER
    assert gui._resolve_xai_api_key() == CONTAINER


def test_saved_key_beats_both_env_names(gui):
    _write_settings({"grok_api_key": SAVED})
    os.environ["XAI_API_KEY"] = LOCAL
    os.environ["GROK_API_KEY"] = CONTAINER
    assert gui._resolve_xai_api_key() == SAVED


def test_fresh_key_beats_saved_and_env(gui):
    _write_settings({"grok_api_key": SAVED})
    os.environ["XAI_API_KEY"] = LOCAL
    os.environ["GROK_API_KEY"] = CONTAINER
    assert gui._effective_key(FRESH, "grok_api_key", "XAI_API_KEY") == FRESH


def test_masked_or_blank_browser_value_falls_back(gui):
    _write_settings({"grok_api_key": SAVED})
    masked = gui._mask_key(SAVED)
    assert gui._effective_key(masked, "grok_api_key", "XAI_API_KEY") == SAVED
    assert gui._effective_key("  ", "grok_api_key", "XAI_API_KEY") == SAVED
    _write_settings({"grok_api_key": masked})
    os.environ["GROK_API_KEY"] = CONTAINER
    assert gui._resolve_xai_api_key() == CONTAINER
    assert gui._effective_key(masked, "grok_api_key", "XAI_API_KEY") == CONTAINER


def test_placeholder_and_surrounding_quotes_are_not_sent(gui):
    os.environ["XAI_API_KEY"] = "your-xai-api-key-here"
    os.environ["GROK_API_KEY"] = f'"{CONTAINER}"'
    assert gui._resolve_xai_api_key() == CONTAINER
    os.environ["XAI_API_KEY"] = f"'{LOCAL}'"
    os.environ.pop("GROK_API_KEY", None)
    assert gui._resolve_xai_api_key() == LOCAL


def test_alias_keeps_desktop_key_and_copies_container_key(gui):
    os.environ["XAI_API_KEY"] = LOCAL
    os.environ["GROK_API_KEY"] = CONTAINER
    gui._alias_grok_env_key()
    assert os.environ["XAI_API_KEY"] == LOCAL
    os.environ.pop("XAI_API_KEY", None)
    os.environ["GROK_API_KEY"] = f'"{CONTAINER}"'
    gui._alias_grok_env_key()
    assert os.environ["XAI_API_KEY"] == CONTAINER
    os.environ["XAI_API_KEY"] = f"'{LOCAL}'"
    gui._alias_grok_env_key()
    assert os.environ["XAI_API_KEY"] == LOCAL


def test_missing_key_reports_configuration_not_a_secret(gui):
    with pytest.raises(RuntimeError) as raised:
        gui._grok_complete("system", "user", search_days=0)
    message = str(raised.value)
    assert "not configured" in message
    assert "XAI_API_KEY" in message and "GROK_API_KEY" in message
    assert "xai-test-" not in message


def test_provider_rejection_redacts_the_key(gui, monkeypatch):
    os.environ["GROK_API_KEY"] = CONTAINER
    _install_fake_xai(monkeypatch, [], boom="Incorrect API key provided: {key}")
    with pytest.raises(RuntimeError) as raised:
        gui._grok_complete("system", "user", search_days=0)
    message = str(raised.value)
    assert "Incorrect API key" in message
    assert CONTAINER not in message
    assert CONTAINER[-4:] in message


def _post_ideas(module, monkeypatch, seen, boom=""):
    _install_fake_xai(
        monkeypatch, seen,
        content='[{"title":"Grok Idea","angle":"A hook."}]',
        boom=boom)
    monkeypatch.setattr(module, "_fetch_top_youtube_ai_titles", lambda limit=10: [])
    monkeypatch.setattr(
        module, "_anthropic_complete",
        lambda *_a, **_k: '[{"title":"Claude Idea","angle":"A hook."}]')
    records, handler = _capture(module)
    try:
        response = module.app.test_client().post(
            "/api/ideas/generate",
            json={"request": "offline check", "lane": "auto"})
    finally:
        module.logger.removeHandler(handler)
    body = response.get_data(as_text=True)
    return response, body, records


def test_idea_generate_uses_container_env_key(gui, monkeypatch):
    os.environ["GROK_API_KEY"] = CONTAINER
    seen = []
    response, body, records = _post_ideas(gui, monkeypatch, seen)
    assert response.status_code == 200, body[:400]
    data = response.get_json()
    assert data["success"]
    sources = [idea["source"] for idea in data["ideas"]]
    assert "Grok" in sources
    assert any(source.startswith("Claude") for source in sources)
    assert seen == [CONTAINER]
    assert CONTAINER not in body
    assert CONTAINER not in "\n".join(records)


def test_idea_generate_uses_saved_key_ahead_of_env(gui, monkeypatch):
    _write_settings({"grok_api_key": SAVED})
    os.environ["XAI_API_KEY"] = LOCAL
    os.environ["GROK_API_KEY"] = CONTAINER
    seen = []
    response, body, records = _post_ideas(gui, monkeypatch, seen)
    assert response.status_code == 200, body[:400]
    assert seen == [SAVED]
    joined = body + "\n" + "\n".join(records)
    for secret in (SAVED, LOCAL, CONTAINER):
        assert secret not in joined


def test_idea_generate_ignores_masked_saved_key(gui, monkeypatch):
    _write_settings({"grok_api_key": "\u2022\u2022\u2022\u2022" + CONTAINER[-4:]})
    os.environ["GROK_API_KEY"] = CONTAINER
    seen = []
    response, body, records = _post_ideas(gui, monkeypatch, seen)
    assert response.status_code == 200, body[:400]
    assert seen == [CONTAINER]
    assert CONTAINER not in body
    assert CONTAINER not in "\n".join(records)
    assert "\u2022\u2022\u2022\u2022" not in "".join(seen)


def test_idea_generate_missing_key_keeps_claude_ideas(gui, monkeypatch):
    monkeypatch.setattr(gui, "_fetch_top_youtube_ai_titles", lambda limit=10: [])
    monkeypatch.setattr(
        gui, "_anthropic_complete",
        lambda *_a, **_k: '[{"title":"Claude Idea","angle":"A hook."}]')
    records, handler = _capture(gui)
    try:
        response = gui.app.test_client().post(
            "/api/ideas/generate", json={"request": "offline check"})
    finally:
        gui.logger.removeHandler(handler)
    body = response.get_data(as_text=True)
    data = response.get_json()
    assert data["success"]
    assert any(idea["source"].startswith("Claude") for idea in data["ideas"])
    assert not any(idea["source"] == "Grok" for idea in data["ideas"])
    assert any("not configured" in warning for warning in data["warnings"])
    assert "xai-test-" not in body
    assert "xai-test-" not in "\n".join(records)


def test_idea_generate_invalid_key_redacts_warning(gui, monkeypatch):
    os.environ["XAI_API_KEY"] = LOCAL
    seen = []
    response, body, records = _post_ideas(
        gui, monkeypatch, seen, boom="Incorrect API key provided: {key}")
    data = response.get_json()
    assert data["success"]
    assert any(idea["source"].startswith("Claude") for idea in data["ideas"])
    assert not any(idea["source"] == "Grok" for idea in data["ideas"])
    assert any("Incorrect API key" in warning for warning in data["warnings"])
    joined = body + "\n" + "\n".join(records)
    assert LOCAL not in joined
    assert seen == [LOCAL]


def test_keys_dialog_sees_container_env_without_revealing_it(gui):
    os.environ["GROK_API_KEY"] = CONTAINER
    response = gui.app.test_client().get("/api/keys")
    body = response.get_data(as_text=True)
    data = response.get_json()
    assert data["sources"]["grok_api_key"] == "env"
    assert data["present"]["grok_api_key"] is True
    assert data["keys"]["grok_api_key"].endswith(CONTAINER[-4:])
    assert CONTAINER not in body


def test_index_masks_container_key(gui):
    os.environ["GROK_API_KEY"] = CONTAINER
    html = gui.app.test_client().get("/").get_data(as_text=True)
    masked = gui._mask_key(CONTAINER)
    assert f'id="grokApiKey" value="{masked}"' in html
    assert CONTAINER not in html


def test_desktop_and_container_modules_resolve_the_same_key():
    os.environ.pop("XAI_API_KEY", None)
    os.environ["GROK_API_KEY"] = CONTAINER
    _write_settings({})
    try:
        assert local_gui._resolve_xai_api_key() == CONTAINER
        assert container_gui._resolve_xai_api_key() == CONTAINER
    finally:
        os.environ.pop("GROK_API_KEY", None)


def _resolve_key_function() -> str:
    script = (CONTAINER_APP / "deploy-azure.sh").read_text(encoding="utf-8")
    start = script.index("_resolve_key() {")
    end = script.index("\nX_API_KEY=")
    return script[start:end]


def _bash_resolve(dotenv: str, app_vars: dict | None = None) -> str:
    """Run the deploy script's resolver. az is stubbed and returns one app env."""
    app_vars = app_vars or {}
    cases = "\n".join(
        f"    *{name}*) printf '%s' '{value}' ;;" for name, value in app_vars.items())
    env_dir = _TMP / "deploy-env"
    env_dir.mkdir(exist_ok=True)
    (env_dir / ".env").write_text(dotenv, encoding="utf-8")
    program = f"""
{_resolve_key_function()}
az() {{
  case "$*" in
{cases}
    *) printf '%s' '' ;;
  esac
  return 0
}}
cd '{env_dir}'
XAI_API_KEY=$(_resolve_key XAI_API_KEY)
if [ -z "$XAI_API_KEY" ]; then
  XAI_API_KEY=$(_resolve_key GROK_API_KEY)
fi
printf '%s' "$XAI_API_KEY"
"""
    env = os.environ.copy()
    env.pop("XAI_API_KEY", None)
    env.pop("GROK_API_KEY", None)
    result = subprocess.run(
        ["bash", "-s"], input=program, text=True, capture_output=True, env=env, check=False)
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_deploy_script_reads_desktop_name_quotes_and_container_name():
    script = (CONTAINER_APP / "deploy-azure.sh").read_text(encoding="utf-8")
    assert 'GROK_API_KEY="${GROK_API_KEY:-}"' not in script
    assert 'ENV_VARS_ARGS+=("XAI_API_KEY=$XAI_API_KEY")' in script
    assert 'ENV_VARS_ARGS+=("GROK_API_KEY=$GROK_API_KEY")' in script
    grok_section = script.split("# --- Grok / xAI key", 1)[1].split(
        "# --- Optional extra keys", 1)[0]
    for line in grok_section.splitlines():
        if line.strip().startswith("echo"):
            assert "$XAI_API_KEY" not in line and "$GROK_API_KEY" not in line
    assert _bash_resolve('XAI_API_KEY="xai-test-from-dotenv-1111"\n') == "xai-test-from-dotenv-1111"
    assert _bash_resolve("GROK_API_KEY='xai-test-from-container-2222'\n") == "xai-test-from-container-2222"
    assert _bash_resolve(
        "# no grok key\n", {"GROK_API_KEY": "xai-test-from-app-5555"}) == "xai-test-from-app-5555"
    assert _bash_resolve("# no grok key\n") == ""
