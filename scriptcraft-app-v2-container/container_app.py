"""
Container entrypoint for ScriptCraft v2 (cloud variant).

Wraps the existing `web_gui.py` Flask app for headless container hosting:

  1. Pre-installs stub modules so any `import davinci_resolve_api`,
     `import resolve_inspector`, or `import DaVinciResolveScript` calls
     succeed without actually requiring DaVinci Resolve to be installed.
  2. Imports `web_gui` to register all routes.
  3. Replaces routes that depend on a local file system, DaVinci Resolve,
     local Whisper transcription, or local video/audio download with a
     503 stub. Local-disk download/save endpoints are also disabled.

The original `web_gui.py` is intentionally NOT modified — this keeps the
container variant a thin overlay so we can resync from `scriptcraft-app-v2/`
without merge pain.
"""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path

# --- 1. Stub out DaVinci/Resolve modules BEFORE web_gui imports them ---------


def _make_stub_module(name: str) -> types.ModuleType:
    mod = types.ModuleType(name)

    def _unavailable(*_args, **_kwargs):
        raise RuntimeError(
            f"{name} is not available in the container build of ScriptCraft. "
            "DaVinci Resolve features are local-only."
        )

    # Common attributes referenced by web_gui
    for attr in (
        "inspect_current_timeline",
        "_apply_wipe_to_v3_clips",
        "probe_fusion_comp",
        "save_comp_preset",
        "create_resolve_project",
        "render_audio_from_timeline",
        "list_timelines",
    ):
        setattr(mod, attr, _unavailable)

    return mod


for _stub_name in ("davinci_resolve_api", "resolve_inspector", "DaVinciResolveScript"):
    if _stub_name not in sys.modules:
        sys.modules[_stub_name] = _make_stub_module(_stub_name)


# --- 2. Ensure the local package is on sys.path -----------------------------

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# Default an output dir that exists inside the container. web_gui defaults
# to ~/Dev/Videos/Edited/Final which won't exist in the image.
os.environ.setdefault("SCRIPTCRAFT_OUTPUT_PARENT", "/tmp/scriptcraft_output")
Path("/tmp/scriptcraft_output").mkdir(parents=True, exist_ok=True)


# --- 3. Import the unmodified web app ---------------------------------------

import web_gui  # noqa: E402  (must come AFTER stubs/sys.path setup)

app = web_gui.app
app.config["CONTAINER_MODE"] = True


# --- 4. Disable routes that require local-only resources --------------------

from flask import jsonify  # noqa: E402

# Endpoint names of routes to disable. Flask derives these from the view
# function name unless the route was registered with an explicit endpoint.
# We map the *view function names* found in web_gui.py.
_DISABLED_VIEWS = {
    # Local Whisper transcription (CLI dependency, local audio file)
    "api_transcribe_audio",
    "api_transcribe_audio_progress",
    # DaVinci Resolve integrations
    "api_resolve_inspect",
    "api_resolve_test_swipe",
    "api_resolve_probe_fusion",
    "api_resolve_save_comp_preset",
    "api_resolve_list_timelines",
    "api_resolve_render_audio_start",
    "api_resolve_render_audio_progress",
    "create_resolve_project",
    "create_resolve_with_videos",
    "check_aroll_videos",
    "setup_project",
    "execute_curl",
    "check_video_status",
    # Local file-system bound: directory browsers / output dir mgmt
    "api_browse_dirs",
    "api_create_dir",
    "api_save_outputs",
    "api_output_dir_get",
    "api_output_dir_save",
    # macOS native file/folder pickers (osascript) + Finder reveal + local media
    # preview — all require the local desktop and are meaningless in the cloud.
    "api_youtube_pick_output_dir",
    "api_youtube_pick_transcript",
    "youtube_pick_video_path",
    "youtube_pick_thumbnail_path",
    "youtube_pick_srt_path",
    "youtube_local_preview",
    "youtube_reveal_path",
    # Local-disk video/audio downloads
    "download_heygen_video",
    "download_media_zip",
    # Word document export to local disk (heavy, not needed in cloud)
    # NOTE: export_word actually streams the .docx in the HTTP response
    # (browser save dialog handles the location), so it's safe in container.
    # "export_word" intentionally NOT disabled.
    "test_word_page",
    # Local debug / capture / SSE test helpers
    "debug_stdout",
    "test_capture_page",
    "test_capture_process",
    "test_create",
    "test_page",
    "test_sse",
    "test_progress",
    "test_progress_stream",
    "test_thumbnails",
    "thumbnail_test",
    "generate_test_thumbnails",
    "test_comparisons",
}

# Display names of disabled routes (best-effort — for UI hints)
_DISABLED_TAGS = sorted(_DISABLED_VIEWS)


def _disabled_response(view_name: str):
    return (
        jsonify(
            {
                "status": "error",
                "error": "feature_disabled_in_container",
                "message": (
                    f"'{view_name}' is disabled in the cloud/container build. "
                    "This feature requires the local desktop app (DaVinci Resolve, "
                    "local file system, or local Whisper)."
                ),
            }
        ),
        503,
    )


_overrides = 0
for endpoint, view_func in list(app.view_functions.items()):
    target_name = getattr(view_func, "__name__", endpoint)
    if endpoint in _DISABLED_VIEWS or target_name in _DISABLED_VIEWS:
        captured = target_name

        def _stub(*_a, _name=captured, **_kw):
            return _disabled_response(_name)

        _stub.__name__ = f"disabled_{captured}"
        app.view_functions[endpoint] = _stub
        _overrides += 1

print(f"🔒 Container mode: disabled {_overrides} local-only view functions")
print(f"🔒 Disabled set ({len(_DISABLED_TAGS)}): {', '.join(_DISABLED_TAGS)}")


# --- 5. Health endpoint for Container Apps probes ---------------------------

@app.route("/healthz")
def _container_healthz():
    return jsonify({"status": "ok", "mode": "container", "version": getattr(web_gui, "VERSION", "unknown")})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
