#!/usr/bin/env python3
"""Narration for the hackathon package.

TTS_PROVIDER selects the voice:

  azure       Azure AI Speech neural voice (default). Entra ID or a key.
  piper       Piper, baked into the image, no network.
  elevenlabs  Optional. Used only when ELEVENLABS_API_KEY is set.

Every provider is paced to about TTS_WPM (default 175) and then passed through
explainer_video.normalize_audio (-14 LUFS). Word times come from Azure Speech
word boundaries, or from faster-whisper when the provider does not return them.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import shutil
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path


DEFAULT_VOICE = "en-US-AvaMultilingualNeural"
DEFAULT_WPM = 175
# Ava's default rate is near 150 spoken words per minute. SSML rate is relative.
DEFAULT_BASELINE_WPM = 150


def _setting(name: str, default: str = "") -> str:
    value = (os.environ.get(name) or "").strip()
    return value or default


def provider_name() -> str:
    name = _setting("TTS_PROVIDER", "azure").lower()
    if name not in ("azure", "piper", "elevenlabs"):
        return "azure"
    return name


def target_wpm() -> float:
    try:
        return float(_setting("TTS_WPM", str(DEFAULT_WPM)))
    except ValueError:
        return float(DEFAULT_WPM)


def prosody_rate(target: float | None = None, baseline: float | None = None) -> str:
    """SSML prosody rate that moves a neural voice from its baseline toward target wpm."""
    target = float(DEFAULT_WPM if target is None else target)
    if baseline is None:
        try:
            baseline = float(_setting("TTS_BASELINE_WPM", str(DEFAULT_BASELINE_WPM)))
        except ValueError:
            baseline = float(DEFAULT_BASELINE_WPM)
    baseline = baseline or float(DEFAULT_BASELINE_WPM)
    percent = (target / baseline - 1.0) * 100.0
    return f"{percent:+.0f}%"


def build_ssml(text: str, voice: str, rate: str) -> str:
    safe_voice = html.escape(voice, quote=True)
    body = html.escape(text or "")
    return (
        '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
        'xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="en-US">'
        f'<voice name="{safe_voice}"><prosody rate="{html.escape(rate, quote=True)}">'
        f"{body}</prosody></voice></speak>"
    )


def status() -> dict:
    piper_bin = _setting("PIPER_BIN", "/opt/piper/piper")
    model = _setting("PIPER_MODEL", "/opt/piper/en_US-lessac-medium.onnx")
    return {
        "provider": provider_name(),
        "voice": _setting("TTS_VOICE", DEFAULT_VOICE),
        "wpm": target_wpm(),
        "ssml_rate": prosody_rate(),
        "azure_configured": bool(
            _setting("AZURE_SPEECH_KEY")
            or _setting("AZURE_SPEECH_REGION")
            or _setting("AZURE_SPEECH_ENDPOINT")
        ),
        "elevenlabs_configured": bool(_setting("ELEVENLABS_API_KEY")),
        "piper_ready": Path(piper_bin).is_file() and Path(model).is_file(),
    }


def _duration(path: Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=False,
    )
    try:
        return float((proc.stdout or "").strip())
    except ValueError:
        return 0.0


def _atempo_chain(factor: float) -> str:
    """ffmpeg atempo is limited to 0.5..2.0 per filter."""
    filters = []
    remaining = factor
    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5
    filters.append(f"atempo={remaining:.5f}")
    return ",".join(filters)


def pace_to_wpm(src: Path, dst: Path, text: str, wpm: float) -> float:
    """Speed the clip so it lands near `wpm`. Returns the atempo factor (1.0 if unchanged)."""
    words = max(1, len((text or "").split()))
    target = words / max(wpm, 1.0) * 60.0
    actual = _duration(src)
    if actual <= 0.05 or target <= 0.05:
        shutil.copyfile(src, dst)
        return 1.0
    factor = actual / target
    if 0.97 <= factor <= 1.03:
        shutil.copyfile(src, dst)
        return 1.0
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
         "-af", _atempo_chain(factor), str(dst)],
        check=True,
    )
    return factor


def _scale_words(words: list, factor: float) -> list:
    if not words or abs(factor - 1.0) < 0.001:
        return words
    scaled = []
    for word in words:
        scaled.append({
            "text": word.get("text") or "",
            "start": float(word.get("start") or 0) / factor,
            "end": float(word.get("end") or 0) / factor,
        })
    return scaled


def _boundary_seconds(value) -> float:
    if hasattr(value, "total_seconds"):
        return float(value.total_seconds())
    try:
        return float(value) / 10_000_000.0
    except (TypeError, ValueError):
        return 0.0


def azure_configured() -> bool:
    if _setting("AZURE_SPEECH_KEY") and _setting("AZURE_SPEECH_REGION"):
        return True
    if _setting("AZURE_SPEECH_REGION") or _setting("AZURE_SPEECH_ENDPOINT"):
        # Entra: the same service principal the rest of the app uses.
        from linedrive_azure.agents.base_agent_client import azure_identity_configured
        return azure_identity_configured()
    return False


def _speech_config(voice: str):
    import azure.cognitiveservices.speech as speechsdk
    key = _setting("AZURE_SPEECH_KEY")
    region = _setting("AZURE_SPEECH_REGION")
    endpoint = _setting("AZURE_SPEECH_ENDPOINT")
    if key and region:
        config = speechsdk.SpeechConfig(subscription=key, region=region)
    else:
        from azure.identity import DefaultAzureCredential
        token = DefaultAzureCredential().get_token(
            "https://cognitiveservices.azure.com/.default").token
        resource_id = _setting("AZURE_SPEECH_RESOURCE_ID")
        if resource_id and region:
            # Entra auth for Speech: "aad#<resource id>#<token>" with the region.
            config = speechsdk.SpeechConfig(
                auth_token=f"aad#{resource_id}#{token}", region=region)
            config.speech_synthesis_voice_name = voice
            config.set_speech_synthesis_output_format(
                speechsdk.SpeechSynthesisOutputFormat.Riff48Khz16BitMonoPcm)
            return config
        if not endpoint:
            if not region:
                raise RuntimeError(
                    "Azure Speech needs AZURE_SPEECH_REGION or AZURE_SPEECH_ENDPOINT"
                )
            endpoint = (
                f"wss://{region}.tts.speech.microsoft.com/"
                "cognitiveservices/websocket/v1"
            )
        config = speechsdk.SpeechConfig(endpoint=endpoint)
        config.authorization_token = "aad#" + token
    config.speech_synthesis_voice_name = voice
    config.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Riff48Khz16BitMonoPcm)
    return config


def azure_synthesize(text: str, wav_path: Path, voice: str, rate: str) -> list:
    import azure.cognitiveservices.speech as speechsdk
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    config = _speech_config(voice)
    audio = speechsdk.audio.AudioOutputConfig(filename=str(wav_path))
    synth = speechsdk.SpeechSynthesizer(speech_config=config, audio_config=audio)
    words: list = []

    def on_boundary(evt):
        kind = getattr(evt, "boundary_type", None)
        if kind != speechsdk.SpeechSynthesisBoundaryType.Word:
            return
        start = _boundary_seconds(getattr(evt, "audio_offset", 0))
        # duration is a timedelta in current SDKs and 100ns ticks in older ones.
        dur = getattr(evt, "duration", 0)
        if hasattr(dur, "total_seconds"):
            length = float(dur.total_seconds())
        else:
            length = _boundary_seconds(dur)
        token = (getattr(evt, "text", "") or "").strip()
        if token:
            words.append({"text": token, "start": start, "end": start + max(length, 0.01)})

    synth.synthesis_word_boundary.connect(on_boundary)
    result = synth.speak_ssml_async(build_ssml(text, voice, rate)).get()
    if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
        details = getattr(result, "cancellation_details", None)
        message = getattr(details, "error_details", None) or str(result.reason)
        raise RuntimeError(f"Azure Speech failed: {message}")
    return words


def piper_synthesize(text: str, wav_path: Path) -> None:
    binary = _setting("PIPER_BIN", "/opt/piper/piper")
    model = _setting("PIPER_MODEL", "/opt/piper/en_US-lessac-medium.onnx")
    if not Path(binary).is_file() or not Path(model).is_file():
        raise RuntimeError(
            "Piper is not installed in this image "
            f"(expected {binary} and {model})."
        )
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    lib = str(Path(binary).resolve().parent)
    env["LD_LIBRARY_PATH"] = lib + (
        ":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
    proc = subprocess.run(
        [binary, "--model", model, "--output_file", str(wav_path)],
        input=text.encode("utf-8"),
        capture_output=True, env=env, check=False,
    )
    if proc.returncode != 0 or not wav_path.is_file():
        detail = (proc.stderr or b"").decode("utf-8", "replace")[-400:]
        raise RuntimeError(f"Piper failed ({proc.returncode}): {detail}")


def eleven_synthesize(text: str, out_path: Path, voice_id: str) -> None:
    import requests
    key = _setting("ELEVENLABS_API_KEY")
    if not key:
        raise RuntimeError("ELEVENLABS_API_KEY is not set")
    if not voice_id:
        raise RuntimeError("Set ELEVENLABS_VOICE_ID or pick a voice")
    model = _setting("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")
    response = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
        headers={"xi-api-key": key, "accept": "audio/mpeg"},
        json={"text": text, "model_id": model},
        timeout=180,
    )
    if response.status_code != 200:
        raise RuntimeError(f"ElevenLabs error {response.status_code}: {response.text[:200]}")
    out_path.write_bytes(response.content)


_whisper = None
_whisper_lock = threading.Lock()


def _audio_16k(wav: Path):
    """Mono 16 kHz float32. ffmpeg, not PyAV: newer PyAV dropped metadata_errors."""
    import numpy as np
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(wav), "-ac", "1", "-ar", "16000",
         "-f", "s16le", "-"],
        capture_output=True, check=True,
    )
    if not proc.stdout:
        raise RuntimeError("ffmpeg produced no samples")
    return np.frombuffer(proc.stdout, np.int16).astype(np.float32) / 32768.0


def whisper_words(wav: Path) -> list:
    """Word times from the offline faster-whisper model baked into the image."""
    global _whisper
    from faster_whisper import WhisperModel
    root = _setting("WHISPER_MODEL_DIR", "/opt/whisper")
    with _whisper_lock:
        if _whisper is None:
            _whisper = WhisperModel(
                _setting("WHISPER_MODEL", "tiny.en"),
                device="cpu", compute_type="int8", download_root=root,
            )
        model = _whisper
    segments, _info = model.transcribe(
        _audio_16k(wav), word_timestamps=True, language="en")
    words = []
    for segment in segments:
        for word in (segment.words or []):
            token = (word.word or "").strip()
            if token:
                words.append({
                    "text": token,
                    "start": float(word.start),
                    "end": float(word.end),
                })
    return words


def synthesize(text: str, out_wav: Path, provider: str | None = None,
               voice: str | None = None) -> dict:
    """Write a -14 LUFS WAV (and sidecar .words.json / .m4a) for `text`."""
    text = (text or "").strip()
    if not text:
        raise ValueError("No narration text")
    chosen = (provider or provider_name()).lower()
    if chosen not in ("azure", "piper", "elevenlabs"):
        raise ValueError(f"Unknown TTS provider: {chosen}")
    voice = (voice or "").strip()
    if chosen == "azure":
        voice = voice or _setting("TTS_VOICE", DEFAULT_VOICE)
    elif chosen == "elevenlabs":
        voice = voice or _setting("ELEVENLABS_VOICE_ID")

    tmp = Path(tempfile.mkdtemp(prefix="narration-"))
    try:
        raw = tmp / "raw.wav"
        words = None
        used = chosen
        if chosen == "azure":
            if not azure_configured():
                print("Azure Speech is not configured; using Piper.")
                piper_synthesize(text, raw)
                used = "piper"
            else:
                try:
                    words = azure_synthesize(text, raw, voice, prosody_rate())
                except Exception as exc:
                    print(f"Azure Speech failed ({exc}); using Piper.")
                    piper_synthesize(text, raw)
                    used = "piper"
                    words = None
        elif chosen == "piper":
            piper_synthesize(text, raw)
        else:
            eleven_raw = tmp / "raw.mp3"
            eleven_synthesize(text, eleven_raw, voice)
            raw = eleven_raw

        paced = tmp / "paced.wav"
        factor = pace_to_wpm(raw, paced, text, target_wpm())
        words = _scale_words(words or [], factor)

        out_wav = Path(out_wav)
        out_wav.parent.mkdir(parents=True, exist_ok=True)
        from explainer_video import normalize_audio
        loud = normalize_audio(paced, out_wav, out_wav.with_suffix(".m4a"))
        if not words:
            try:
                words = whisper_words(out_wav)
            except Exception as exc:
                print(f"faster-whisper timing failed ({exc}); estimating {target_wpm():.0f} wpm")
                words = _estimate_words(text, _duration(out_wav))
        out_wav.with_suffix(".words.json").write_text(
            json.dumps(words), encoding="utf-8")
        return {
            "provider": used,
            "input_lufs": float(loud.get("input_lufs") or 0),
            "target_lufs": -14.0,
            "words": len(words),
            "seconds": _duration(out_wav),
            "wav": str(out_wav),
            "wpm": target_wpm(),
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _estimate_words(text: str, duration: float) -> list:
    tokens = (text or "").split()
    if not tokens or duration <= 0:
        return []
    step = duration / len(tokens)
    return [
        {"text": token, "start": i * step, "end": (i + 1) * step}
        for i, token in enumerate(tokens)
    ]


def install(app, web_gui) -> None:
    """Point the existing voiceover button at the selected provider.

    The page still polls /api/elevenlabs/tts/<job>. Azure and Piper do not
    require an ElevenLabs key. A missing optional key returns JSON, it does
    not crash the process.
    """
    original_tts = app.view_functions.get("elevenlabs_tts_start")

    def voices():
        chosen = provider_name()
        if chosen == "elevenlabs":
            if not web_gui._eleven_key():
                return web_gui.jsonify({
                    "success": False, "needs_key": True,
                    "error": ("ElevenLabs is optional. Add ELEVENLABS_API_KEY, "
                              "or set TTS_PROVIDER=azure or TTS_PROVIDER=piper."),
                }), 400
            return app.view_functions_original_voices()
        if chosen == "piper":
            voice, label = "piper-lessac-medium", "Piper lessac (offline)"
        else:
            voice = _setting("TTS_VOICE", DEFAULT_VOICE)
            label = f"{voice} (Azure neural, {prosody_rate()} SSML)"
        return web_gui.jsonify({
            "success": True,
            "provider": chosen,
            "voices": [{
                "voice_id": voice, "name": label, "category": chosen,
                "own": True, "detail": f"about {target_wpm():.0f} words per minute",
                "preview_url": "",
            }],
            "balance": None,
            "models": [{"id": chosen, "label": chosen}],
            "voice_id": voice,
            "model_id": chosen,
            "similarity": 0.75,
            "clone_strength": 0.0,
            "clone_strength_models": [],
        })

    # Keep the original ElevenLabs voice list addressable after we replace the view.
    app.view_functions_original_voices = app.view_functions.get("elevenlabs_voices")

    def tts_start():
        chosen = provider_name()
        data = web_gui.request.get_json(silent=True) or {}
        if chosen == "elevenlabs" and not web_gui._eleven_key():
            return web_gui.jsonify({
                "success": False, "needs_key": True,
                "error": ("ElevenLabs is optional. Add ELEVENLABS_API_KEY, "
                          "or set TTS_PROVIDER=azure or TTS_PROVIDER=piper."),
            }), 400
        try:
            text, source = web_gui._eleven_script_text(data)
        except Exception as exc:
            return web_gui.jsonify({
                "success": False, "error": f"Could not read the script: {exc}",
            }), 500
        if not text:
            return web_gui.jsonify({
                "success": False,
                "error": "No spoken text found. Open a script with Host: lines first.",
            }), 400
        voice = (data.get("voice_id") or "").strip()
        title = (data.get("title") or "Voiceover").strip()
        safe = web_gui._safe_title_for_paths(title) or "Voiceover"
        stamp = web_gui.datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = (web_gui._get_run_output_dir(title) / "voiceover"
                    / f"{safe}_{chosen}_{stamp}.wav")
        job_id = uuid.uuid4().hex
        web_gui._eleven_set(
            job_id, status="running", created=web_gui.time.time(), total=1, done=0,
            chars=len(text), words=len(text.split()), source=source,
            voice=voice or _setting("TTS_VOICE", DEFAULT_VOICE),
            model=chosen, message="Starting narration…",
        )

        def run():
            try:
                web_gui._eleven_set(job_id, message=f"Reading with {chosen}…")
                result = synthesize(text, out_path, provider=chosen, voice=voice)
                web_gui._eleven_set(
                    job_id, status="done", path=result["wav"],
                    audio_seconds=int(result["seconds"]),
                    message=(f"Saved {Path(result['wav']).name} "
                             f"({result['provider']}, {result['words']} words timed)"),
                    provider=result["provider"],
                )
            except Exception as exc:
                web_gui.logger.error(f"Narration failed: {exc}")
                web_gui._eleven_set(job_id, status="error", error=str(exc)[:500])

        threading.Thread(target=run, daemon=True).start()
        return web_gui.jsonify({
            "success": True, "job_id": job_id, "parts": 1,
            "chars": len(text), "source": source, "provider": chosen,
        })

    # ElevenLabs keeps its original route when it is the selected provider and
    # the caller wants the multi-part stitcher. Azure and Piper always use
    # synthesize(), which loudnorm-normalizes. ElevenLabs does too, so every
    # provider hits normalize_audio.
    if original_tts is not None:
        app.view_functions["elevenlabs_tts_start"] = tts_start
    app.view_functions["elevenlabs_voices"] = voices


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthesize narration to a WAV.")
    parser.add_argument("--provider", default="")
    parser.add_argument("--text", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--voice", default="")
    args = parser.parse_args()
    result = synthesize(
        args.text, Path(args.out),
        provider=args.provider or None,
        voice=args.voice or None,
    )
    # Loudness and timing only. Never print credentials.
    print(
        f"provider={result['provider']} seconds={result['seconds']:.2f} "
        f"words={result['words']} input_lufs={result['input_lufs']:.1f} "
        f"target_lufs=-14 wav={result['wav']}"
    )


if __name__ == "__main__":
    main()
