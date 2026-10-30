"""
Container entrypoint for Podcast Generator (ScriptCraft v3, cloud variant).

Wraps the existing `web_gui.py` Flask app for headless container hosting:

  1. Pre-installs stub modules so any `import davinci_resolve_api`,
     `import resolve_inspector`, or `import DaVinciResolveScript` calls
     succeed without actually requiring DaVinci Resolve to be installed.
  2. Restores the 🔑 API Keys dialog's settings from a private blob (the
     container disk is ephemeral) and uploads them again after every save.
  3. Imports `web_gui` to register all routes.
  4. Replaces routes that depend on a local file system, DaVinci Resolve,
     local Whisper transcription, or local video/audio download with a
     503 stub. Local-disk download/save endpoints are also disabled.

The original `web_gui.py` is intentionally NOT modified — this keeps the
container variant a thin overlay so we can resync from `scriptcraft-app-v3/`
(./sync-from-v3.sh) without merge pain.
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


# --- 3. Keep the API Keys dialog's settings across restarts ------------------
# The container's disk is wiped on every restart and deploy, so keys saved in
# the 🔑 API Keys dialog would quietly revert to the deploy-time env vars.
# Restore the settings file from a private blob BEFORE web_gui reads it at
# import, and upload it again after every save. Uses the app's managed
# identity (Storage Blob Data Contributor on the account). Set
# SCRIPTCRAFT_SETTINGS_BLOB_CONTAINER="" to turn this off.

_SETTINGS_BLOB_CONTAINER = os.environ.get(
    "SCRIPTCRAFT_SETTINGS_BLOB_CONTAINER", "app-settings").strip()
_SETTINGS_BLOB_NAME = "web_gui_settings.json"
_SETTINGS_PATH = Path(
    os.environ.get("SCRIPTCRAFT_SETTINGS_FILE")
    or (Path.home() / ".scriptcraft" / "web_gui_settings.json")
).expanduser()


def _settings_blob_service():
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import BlobServiceClient
    account = os.environ.get("FINISHED_VIDEOS_BLOB_ACCOUNT",
                             "linedrivestorage")
    return BlobServiceClient(
        account_url=f"https://{account}.blob.core.windows.net",
        credential=DefaultAzureCredential(),
        connection_timeout=10, read_timeout=30,
    )


def _restore_settings_from_blob() -> None:
    if not _SETTINGS_BLOB_CONTAINER:
        return
    from azure.core.exceptions import ResourceNotFoundError
    try:
        blob = _settings_blob_service().get_blob_client(
            _SETTINGS_BLOB_CONTAINER, _SETTINGS_BLOB_NAME)
        data = blob.download_blob().readall()
    except ResourceNotFoundError:
        print("🔑 No saved settings blob yet; using the deploy-time keys")
        return
    except Exception as e:
        print(f"⚠️ Could not restore saved settings from blob: {e}")
        return
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS_PATH.write_bytes(data)
    _SETTINGS_PATH.chmod(0o600)
    print(f"🔑 Restored saved settings from blob "
          f"{_SETTINGS_BLOB_CONTAINER}/{_SETTINGS_BLOB_NAME}")


def _upload_settings_to_blob() -> bool:
    if not _SETTINGS_BLOB_CONTAINER:
        return True
    from azure.core.exceptions import ResourceNotFoundError
    try:
        container = _settings_blob_service().get_container_client(
            _SETTINGS_BLOB_CONTAINER)
        data = _SETTINGS_PATH.read_bytes()
        try:
            container.upload_blob(_SETTINGS_BLOB_NAME, data, overwrite=True)
        except ResourceNotFoundError:
            # First save: create the container (private: no public access),
            # then retry.
            container.create_container()
            container.upload_blob(_SETTINGS_BLOB_NAME, data, overwrite=True)
        return True
    except Exception as e:
        print(f"❌ Could not upload settings to blob: {e}")
        return False


_restore_settings_from_blob()


# --- 4. Import the unmodified web app ---------------------------------------

import web_gui  # noqa: E402  (must come AFTER stubs/sys.path setup)

app = web_gui.app
app.config["CONTAINER_MODE"] = True

# Every save (API Keys dialog and other settings) also goes to the blob. A
# failed upload reports "Could not save settings" so the dialog never claims a
# key will survive a restart when it won't.
_save_settings_locally = web_gui._save_scriptcraft_settings


def _save_settings_and_upload(settings: dict) -> bool:
    return _save_settings_locally(settings) and _upload_settings_to_blob()


web_gui._save_scriptcraft_settings = _save_settings_and_upload


# --- 5. Disable routes that require local-only resources --------------------

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
    # Render Audio from a finished video: reads a local video path with ffmpeg
    "api_extract_audio_start",
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


# --- 6. Health endpoint for Container Apps probes ---------------------------

@app.route("/healthz")
def _container_healthz():
    return jsonify({"status": "ok", "mode": "container", "version": getattr(web_gui, "VERSION", "unknown")})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
