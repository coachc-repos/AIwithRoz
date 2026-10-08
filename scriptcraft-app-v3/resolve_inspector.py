#!/usr/bin/env python3
"""
DaVinci Resolve Timeline Inspector

Connects to the currently-running DaVinci Resolve, reads the active project's
current timeline, and returns a structured dict describing every clip on every
video and audio track — including B-roll on V2/V3, adjustment clips, and any
plug-in / effect settings that Resolve exposes via the scripting API.

Note: Resolve's Python API does NOT expose a clean "list of OpenFX applied to
this clip" call. The best we can do is:
  - Enumerate Fusion compositions on the clip (Resolve FX + Fusion effects
    that get baked into Fusion comps) via GetFusionCompCount/Names.
  - Dump the full property bag returned by `TimelineItem.GetProperty()`
    (no arg => returns dict of every exposed property: transforms, retiming,
    composite mode, opacity, stabilization, dynamic zoom, etc.).
  - Detect adjustment clips heuristically (no MediaPoolItem or name match).
"""

from __future__ import annotations

import os
import sys
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("resolve_inspector")
if not logger.handlers and not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger.setLevel(logging.INFO)


# --------------------------------------------------------------------------- #
# Resolve connection                                                          #
# --------------------------------------------------------------------------- #

def _connect_resolve():
    """Connect to a running DaVinci Resolve and return the resolve object."""
    resolve_script_api = (
        "/Library/Application Support/Blackmagic Design/"
        "DaVinci Resolve/Developer/Scripting"
    )
    resolve_script_lib = (
        "/Applications/DaVinci Resolve/DaVinci Resolve.app/"
        "Contents/Libraries/Fusion/fusionscript.so"
    )
    os.environ["RESOLVE_SCRIPT_API"] = resolve_script_api
    os.environ["RESOLVE_SCRIPT_LIB"] = resolve_script_lib
    modules_path = os.path.join(resolve_script_api, "Modules")
    if modules_path not in sys.path:
        sys.path.append(modules_path)

    import DaVinciResolveScript as dvr_script  # type: ignore
    return dvr_script.scriptapp("Resolve")


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #

def _safe_call(obj, method_name: str, *args, default=None):
    """Invoke obj.method_name(*args) defensively."""
    try:
        fn = getattr(obj, method_name, None)
        if fn is None:
            return default
        return fn(*args)
    except Exception as e:
        logger.debug(f"{method_name} failed: {e}")
        return default


def _frames_to_tc(frames: Optional[int], fps: float) -> Optional[str]:
    """Convert an integer frame count to HH:MM:SS:FF using the timeline fps."""
    if frames is None or fps <= 0:
        return None
    try:
        f = int(frames)
        ifps = int(round(fps))
        hours = f // (3600 * ifps)
        f -= hours * 3600 * ifps
        minutes = f // (60 * ifps)
        f -= minutes * 60 * ifps
        seconds = f // ifps
        frame_part = f - seconds * ifps
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frame_part:02d}"
    except Exception:
        return None


def _media_pool_item_info(mpi) -> Dict[str, Any]:
    """Pull the useful bits out of a MediaPoolItem."""
    if not mpi:
        return {}
    info: Dict[str, Any] = {
        "name": _safe_call(mpi, "GetName"),
        "clip_property": {},
    }
    # GetClipProperty() with no args returns all properties as a dict.
    props = _safe_call(mpi, "GetClipProperty")
    if isinstance(props, dict):
        # Keep a curated subset to avoid massive payloads.
        keep_keys = (
            "File Path", "File Name", "Resolution", "FPS", "Duration",
            "Type", "Format", "Codec", "Audio Codec", "Audio Ch", "Video Codec",
            "Frames", "Start", "End", "Bit Depth", "Color Space",
        )
        info["clip_property"] = {k: props.get(k) for k in keep_keys if k in props}
    return info


def _is_adjustment_clip(item, mpi_info: Dict[str, Any]) -> bool:
    """Best-effort detection of an adjustment clip."""
    name = (_safe_call(item, "GetName") or "").lower()
    if "adjustment clip" in name or name == "adjustment":
        return True
    # Adjustment clips may still have a generator MediaPoolItem; inspect its type.
    clip_type = (mpi_info.get("clip_property") or {}).get("Type", "")
    if isinstance(clip_type, str) and "adjustment" in clip_type.lower():
        return True
    return False


def _inspect_timeline_item(item, fps: float) -> Dict[str, Any]:
    """Build a dict describing a single TimelineItem."""
    mpi = _safe_call(item, "GetMediaPoolItem")
    mpi_info = _media_pool_item_info(mpi)

    start = _safe_call(item, "GetStart")
    end = _safe_call(item, "GetEnd")
    duration = _safe_call(item, "GetDuration")
    src_start = _safe_call(item, "GetSourceStartFrame")
    src_end = _safe_call(item, "GetSourceEndFrame")
    src_start_tc = _safe_call(item, "GetSourceStartTime")
    src_end_tc = _safe_call(item, "GetSourceEndTime")
    left_offset = _safe_call(item, "GetLeftOffset")
    right_offset = _safe_call(item, "GetRightOffset")

    # Fusion comps (where Resolve FX + Fusion effects live for this clip).
    fusion_comp_count = _safe_call(item, "GetFusionCompCount", default=0) or 0
    fusion_comp_names: List[str] = []
    if fusion_comp_count:
        names = _safe_call(item, "GetFusionCompNameList") or _safe_call(item, "GetFusionCompNames")
        if isinstance(names, list):
            fusion_comp_names = [str(n) for n in names]
        elif isinstance(names, dict):
            fusion_comp_names = [str(v) for v in names.values()]

    # Property bag (transform, composite mode, retime, dynamic zoom, etc.).
    # Calling GetProperty() with no args returns a dict of all known properties.
    property_bag = _safe_call(item, "GetProperty")
    if not isinstance(property_bag, dict):
        property_bag = {}

    # Markers on the clip itself.
    markers = _safe_call(item, "GetMarkers") or {}
    markers_serialized = []
    if isinstance(markers, dict):
        for frame_id, m in markers.items():
            try:
                markers_serialized.append({
                    "frame_id": int(frame_id),
                    "timecode": _frames_to_tc(int(frame_id), fps),
                    "color": m.get("color"),
                    "name": m.get("name"),
                    "note": m.get("note"),
                    "duration": m.get("duration"),
                })
            except Exception:
                continue

    flags = _safe_call(item, "GetFlagList") or []

    item_info: Dict[str, Any] = {
        "name": _safe_call(item, "GetName"),
        "unique_id": _safe_call(item, "GetUniqueId"),
        "is_adjustment_clip": _is_adjustment_clip(item, mpi_info),
        "timeline": {
            "start_frame": start,
            "end_frame": end,
            "duration_frames": duration,
            "start_tc": _frames_to_tc(start, fps),
            "end_tc": _frames_to_tc(end, fps),
            "duration_tc": _frames_to_tc(duration, fps),
        },
        "source": {
            "start_frame": src_start,
            "end_frame": src_end,
            "start_tc": src_start_tc,
            "end_tc": src_end_tc,
            "left_offset": left_offset,
            "right_offset": right_offset,
        },
        "clip_color": _safe_call(item, "GetClipColor"),
        "flags": flags,
        "markers": markers_serialized,
        "fusion_comp_count": fusion_comp_count,
        "fusion_comp_names": fusion_comp_names,
        "media_pool_item": mpi_info,
        "properties": property_bag,
    }
    return item_info


def _inspect_track(timeline, track_type: str, track_index: int, fps: float) -> Dict[str, Any]:
    items = _safe_call(timeline, "GetItemListInTrack", track_type, track_index) or []
    track_name = _safe_call(timeline, "GetTrackName", track_type, track_index)
    enabled = _safe_call(timeline, "GetIsTrackEnabled", track_type, track_index)
    locked = _safe_call(timeline, "GetIsTrackLocked", track_type, track_index)
    return {
        "track_type": track_type,
        "track_index": track_index,
        "track_name": track_name,
        "enabled": enabled,
        "locked": locked,
        "item_count": len(items),
        "items": [_inspect_timeline_item(it, fps) for it in items],
    }


# --------------------------------------------------------------------------- #
# Public entry point                                                          #
# --------------------------------------------------------------------------- #

def inspect_current_timeline() -> Dict[str, Any]:
    """Inspect the currently-loaded timeline in DaVinci Resolve."""
    try:
        resolve = _connect_resolve()
    except Exception as e:
        return {"success": False, "error": f"Failed to load DaVinciResolveScript: {e}"}

    if not resolve:
        return {
            "success": False,
            "error": "DaVinci Resolve is not running. Please start Resolve and open a project.",
        }

    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return {"success": False, "error": "Failed to get Project Manager from Resolve."}

    project = project_manager.GetCurrentProject()
    if not project:
        return {"success": False, "error": "No project is open in DaVinci Resolve."}

    timeline = project.GetCurrentTimeline()
    if not timeline:
        return {"success": False, "error": "No timeline is open in the current project."}

    # Frame rate is needed for timecode conversion.
    fps_str = _safe_call(project, "GetSetting", "timelineFrameRate") or "24"
    try:
        fps = float(fps_str)
    except Exception:
        fps = 24.0

    video_track_count = _safe_call(timeline, "GetTrackCount", "video", default=0) or 0
    audio_track_count = _safe_call(timeline, "GetTrackCount", "audio", default=0) or 0

    video_tracks = [
        _inspect_track(timeline, "video", i, fps)
        for i in range(1, int(video_track_count) + 1)
    ]
    audio_tracks = [
        _inspect_track(timeline, "audio", i, fps)
        for i in range(1, int(audio_track_count) + 1)
    ]

    total_clips = sum(t["item_count"] for t in video_tracks) + \
                  sum(t["item_count"] for t in audio_tracks)

    return {
        "success": True,
        "project_name": _safe_call(project, "GetName"),
        "timeline_name": _safe_call(timeline, "GetName"),
        "fps": fps,
        "video_track_count": int(video_track_count),
        "audio_track_count": int(audio_track_count),
        "total_clips": total_clips,
        "video_tracks": video_tracks,
        "audio_tracks": audio_tracks,
    }


# --------------------------------------------------------------------------- #
# Fusion comp probe                                                           #
# --------------------------------------------------------------------------- #

def _find_timeline_item_by_unique_id(timeline, unique_id: str):
    """Walk every video & audio track and return the TimelineItem matching unique_id."""
    if not unique_id:
        return None
    for track_type in ("video", "audio"):
        count = _safe_call(timeline, "GetTrackCount", track_type, default=0) or 0
        for idx in range(1, int(count) + 1):
            items = _safe_call(timeline, "GetItemListInTrack", track_type, idx) or []
            for it in items:
                if str(_safe_call(it, "GetUniqueId")) == str(unique_id):
                    return it
    return None


def _serialize_fusion_input(inp) -> Dict[str, Any]:
    """Best-effort dump of one Fusion Input's metadata + current value."""
    info: Dict[str, Any] = {}
    try:
        attrs = inp.GetAttrs() if hasattr(inp, "GetAttrs") else {}
        if isinstance(attrs, dict):
            # Keep useful attributes; convert non-JSON values to str.
            for k in ("INPS_Name", "INPS_ID", "INPS_DataType", "INPS_Default",
                      "INPS_Min", "INPS_Max", "INPID_InputControl"):
                if k in attrs:
                    v = attrs[k]
                    try:
                        info[k] = v if isinstance(v, (str, int, float, bool, list, dict, type(None))) else str(v)
                    except Exception:
                        info[k] = str(v)
    except Exception:
        pass
    # Try to read current value at frame 0.
    try:
        val = inp[0] if hasattr(inp, "__getitem__") else None
        if val is not None and not isinstance(val, (str, int, float, bool, list, dict, type(None))):
            val = str(val)
        info["current_value"] = val
    except Exception:
        pass
    return info


def _serialize_fusion_tool(tool) -> Dict[str, Any]:
    """Dump one Fusion node: name, ID, all attrs, and every input."""
    out: Dict[str, Any] = {}
    try:
        out["name"] = getattr(tool, "Name", None) or _safe_call(tool, "GetAttrs", default={}).get("TOOLS_Name")
    except Exception:
        out["name"] = None
    try:
        out["id"] = getattr(tool, "ID", None) or _safe_call(tool, "GetAttrs", default={}).get("TOOLS_RegID")
    except Exception:
        out["id"] = None

    attrs = _safe_call(tool, "GetAttrs", default={})
    if isinstance(attrs, dict):
        # Strip non-serializable; keep stringy attrs.
        clean: Dict[str, Any] = {}
        for k, v in attrs.items():
            try:
                if isinstance(v, (str, int, float, bool, list, dict, type(None))):
                    clean[k] = v
                else:
                    clean[k] = str(v)
            except Exception:
                continue
        out["attrs"] = clean

    # Walk inputs.
    inputs_dump: Dict[str, Any] = {}
    try:
        input_list = _safe_call(tool, "GetInputList", default={}) or {}
        if isinstance(input_list, dict):
            for key, inp in input_list.items():
                try:
                    name = (getattr(inp, "Name", None) or
                            (inp.GetAttrs().get("INPS_ID") if hasattr(inp, "GetAttrs") else str(key)))
                    inputs_dump[str(name)] = _serialize_fusion_input(inp)
                except Exception:
                    inputs_dump[str(key)] = {"error": "introspection failed"}
    except Exception as e:
        inputs_dump["__error__"] = str(e)

    out["inputs"] = inputs_dump
    out["input_count"] = len(inputs_dump)
    return out


def probe_fusion_comp(unique_id: str) -> Dict[str, Any]:
    """For a given TimelineItem unique_id, dump every Fusion comp's tool list."""
    try:
        resolve = _connect_resolve()
    except Exception as e:
        return {"success": False, "error": f"Failed to load DaVinciResolveScript: {e}"}
    if not resolve:
        return {"success": False, "error": "DaVinci Resolve is not running."}

    project_manager = resolve.GetProjectManager()
    project = project_manager.GetCurrentProject() if project_manager else None
    timeline = project.GetCurrentTimeline() if project else None
    if not timeline:
        return {"success": False, "error": "No timeline is open."}

    item = _find_timeline_item_by_unique_id(timeline, unique_id)
    if not item:
        return {"success": False, "error": f"Timeline item with unique_id {unique_id!r} not found."}

    comp_count = _safe_call(item, "GetFusionCompCount", default=0) or 0
    if not comp_count:
        return {
            "success": True,
            "clip_name": _safe_call(item, "GetName"),
            "unique_id": unique_id,
            "fusion_comp_count": 0,
            "comps": [],
            "note": "This clip has no Fusion compositions.",
        }

    comps_dump: List[Dict[str, Any]] = []
    for i in range(1, int(comp_count) + 1):
        comp = _safe_call(item, "GetFusionCompByIndex", i)
        comp_name = _safe_call(item, "GetFusionCompNameByIndex", i) or f"Composition {i}"
        if comp is None:
            comps_dump.append({
                "index": i,
                "name": comp_name,
                "error": "GetFusionCompByIndex returned None — comp is likely encrypted/locked (typical for paid templates).",
            })
            continue

        tool_list = _safe_call(comp, "GetToolList", default={}) or {}
        if not isinstance(tool_list, dict) or not tool_list:
            comps_dump.append({
                "index": i,
                "name": comp_name,
                "tool_count": 0,
                "tools": [],
                "note": "GetToolList returned no tools — composition is opaque (encrypted macro / protected template).",
            })
            continue

        tools_serialized = []
        for key, tool in tool_list.items():
            try:
                tools_serialized.append(_serialize_fusion_tool(tool))
            except Exception as e:
                tools_serialized.append({"name": str(key), "error": str(e)})

        comps_dump.append({
            "index": i,
            "name": comp_name,
            "tool_count": len(tools_serialized),
            "tools": tools_serialized,
        })

    return {
        "success": True,
        "clip_name": _safe_call(item, "GetName"),
        "unique_id": unique_id,
        "fusion_comp_count": int(comp_count),
        "comps": comps_dump,
    }


# --------------------------------------------------------------------------- #
# Save a Fusion comp from a clip as a reusable .setting preset                #
# --------------------------------------------------------------------------- #

# Default location for saved Fusion comp presets used by the auto-apply step
# in davinci_resolve_api.py.
PRESET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fusion_presets")
DEFAULT_BROLL_PRESET_PATH = os.path.join(PRESET_DIR, "default_broll.setting")


def save_comp_preset(unique_id: str, preset_name: Optional[str] = None,
                     comp_index: int = 1) -> Dict[str, Any]:
    """
    Save the entire Fusion composition from the timeline item identified by
    `unique_id` as a `.setting` file under PRESET_DIR. Saving the whole comp
    (rather than a single tool) preserves the MediaIn → effect → MediaOut
    wiring so we can re-load it on other clips and have it work end-to-end.

    Args:
      unique_id: TimelineItem.GetUniqueId() of the source clip.
      preset_name: filename stem (defaults to "default_broll" → default_broll.setting).
      comp_index: 1-based Fusion comp index on the source clip (usually 1).
    """
    try:
        resolve = _connect_resolve()
    except Exception as e:
        return {"success": False, "error": f"Failed to load DaVinciResolveScript: {e}"}
    if not resolve:
        return {"success": False, "error": "DaVinci Resolve is not running."}

    project_manager = resolve.GetProjectManager()
    project = project_manager.GetCurrentProject() if project_manager else None
    timeline = project.GetCurrentTimeline() if project else None
    if not timeline:
        return {"success": False, "error": "No timeline is open."}

    item = _find_timeline_item_by_unique_id(timeline, unique_id)
    if not item:
        return {"success": False, "error": f"Timeline item with unique_id {unique_id!r} not found."}

    comp_count = _safe_call(item, "GetFusionCompCount", default=0) or 0
    if comp_count < comp_index:
        return {"success": False,
                "error": f"Clip has {comp_count} Fusion comp(s); cannot save index {comp_index}."}

    comp = _safe_call(item, "GetFusionCompByIndex", comp_index)
    if comp is None:
        return {"success": False, "error": f"GetFusionCompByIndex({comp_index}) returned None."}

    os.makedirs(PRESET_DIR, exist_ok=True)
    stem = (preset_name or "default_broll").strip().replace(os.sep, "_")
    if not stem.endswith(".setting"):
        stem = f"{stem}.setting"
    out_path = os.path.join(PRESET_DIR, stem)

    # Back up an existing file rather than overwrite silently.
    backup_path = None
    if os.path.exists(out_path):
        import time
        backup_path = f"{out_path}.{time.strftime('%Y%m%d_%H%M%S')}.bak"
        try:
            os.rename(out_path, backup_path)
        except Exception as e:
            logger.warning(f"Could not back up existing preset: {e}")
            backup_path = None

    # Resolve/Fusion: SaveSettings only saves SELECTED tools. We need every
    # tool selected so the saved .setting captures the full graph
    # (MediaIn1 → mTuber macro → MediaOut1).
    tool_list = {}
    try:
        tool_list = comp.GetToolList(False) or {}  # False = all tools, not just selected
    except Exception as e:
        logger.warning(f"GetToolList failed: {e}")

    selected_count = 0
    if tool_list:
        # Open an Undo block so the selection change can be rolled back cleanly.
        try:
            comp.StartUndo("ScriptCraft: select-all for SaveSettings")
        except Exception:
            pass
        try:
            # Use SetActiveTool to add tools to the current selection. Some
            # builds also accept tool.SetAttrs({'TOOLB_Selected': True}).
            for t in tool_list.values():
                try:
                    set_attrs = getattr(t, "SetAttrs", None)
                    if callable(set_attrs):
                        set_attrs({"TOOLB_Selected": True})
                        selected_count += 1
                except Exception:
                    pass
        finally:
            try:
                comp.EndUndo(True)
            except Exception:
                pass

    # The Resolve Python bridge has a permissive __getattr__: hasattr() returns
    # True for ANY name, but the resolved attribute may be None. Detect that.
    save_fn = None
    for cand in ("SaveSettings", "Save", "SaveAs"):
        fn = getattr(comp, cand, None)
        if callable(fn):
            save_fn = (cand, fn)
            break

    if save_fn is None:
        return {"success": False,
                "error": ("Composition object exposes no callable SaveSettings/Save/SaveAs. "
                          "This Resolve build's Fusion comp object is read-only via Python.")}

    method_name, fn = save_fn
    last_err = None
    ok = False
    try:
        result = fn(out_path)
        # Fusion typically returns True / a settings table on success, or
        # None/False on failure. The file appearing on disk is the ground truth.
        ok = bool(result) or os.path.exists(out_path)
    except Exception as e:
        last_err = f"{method_name} raised: {e}"

    if not ok:
        return {
            "success": False,
            "error": (f"{method_name}({out_path!r}) did not produce a file"
                      + (f" — {last_err}" if last_err else "")
                      + f". Tools selected: {selected_count}/{len(tool_list)}."),
        }

    return {
        "success": True,
        "preset_path": out_path,
        "backup_path": backup_path,
        "clip_name": _safe_call(item, "GetName"),
        "comp_index": comp_index,
        "method": method_name,
        "tools_selected": selected_count,
        "tools_total": len(tool_list),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(inspect_current_timeline(), indent=2, default=str))
