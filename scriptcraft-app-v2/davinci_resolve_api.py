#!/usr/bin/env python3
"""
DaVinci Resolve API Integration
Automates project creation, timeline setup, and bin organization
"""
import re
import sys
import os
import logging
from pathlib import Path

logger = logging.getLogger("davinci_resolve_api")
if not logger.handlers and not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger.setLevel(logging.INFO)


def _log(msg):
    """Log to both logger (Flask captures) and stdout (flushed)."""
    try:
        logger.info(msg)
    except Exception:
        pass
    try:
        print(msg, flush=True)
    except Exception:
        pass


def sanitize_project_name(title):
    """Create a condensed, filesystem-safe project name from script title"""
    # Remove special characters, keep alphanumeric and spaces
    clean = re.sub(r'[^\w\s-]', '', title)
    # Replace spaces with underscores, limit length
    condensed = clean.replace(' ', '_')[:50]
    return condensed if condensed else "AI_Video_Project"


def _collect_media_paths(folder, extensions):
    """Return sorted existing media paths under folder for given extensions."""
    if not folder:
        return []
    try:
        root = Path(folder)
        if not root.exists() or not root.is_dir():
            return []
        exts = {e.lower() for e in extensions}
        files = [p for p in root.rglob('*') if p.is_file() and p.suffix.lower() in exts]
        files.sort(key=lambda p: p.name.lower())
        return [str(p) for p in files]
    except Exception:
        return []


def _import_media_to_bin(resolve, media_pool, bin_mapping, bin_name, file_paths):
    """Import files directly into a target bin."""
    if not file_paths:
        return 0
    target_bin = bin_mapping.get(bin_name)
    if not target_bin:
        return 0

    # Critical: set current folder first so imported media lands in the intended bin,
    # rather than whatever folder was active previously (e.g. heygen/Transition_Clips).
    try:
        media_pool.SetCurrentFolder(target_bin)
    except Exception:
        pass

    imported = media_pool.ImportMedia(file_paths)
    if imported:
        return len(imported)

    # Fallback path for environments where ImportMedia may be flaky.
    storage = resolve.GetMediaStorage()
    if not storage:
        return 0
    imported = storage.AddItemsToMediaPool(file_paths)
    if not imported:
        return 0
    return len(imported)


def _generate_subtitles_from_audio(timeline):
    """Try to generate subtitles from timeline audio via Resolve scripting API.

    Resolve Studio's `Timeline:CreateSubtitlesFromAudio()` requires:
      - DaVinci Resolve **Studio** (not Free).
      - The Edit (or Cut) page to be active.
      - The project to be saved at least once.
      - The timeline to have audio on at least one track.
    """
    if not timeline:
        return {
            "attempted": True,
            "success": False,
            "message": "No active timeline available for subtitle generation",
        }

    # Try to put Resolve in a state where the AI Tools API will accept the call.
    try:
        import DaVinciResolveScript as _dvr
        _resolve = _dvr.scriptapp("Resolve")
        if _resolve is not None:
            try:
                _resolve.OpenPage("edit")
            except Exception:
                pass
            try:
                _pm = _resolve.GetProjectManager()
                _proj = _pm.GetCurrentProject() if _pm else None
                if _proj is not None:
                    try:
                        _proj.SetCurrentTimeline(timeline)
                    except Exception:
                        pass
                    try:
                        _proj.SaveProject()
                    except Exception:
                        pass
            except Exception:
                pass
    except Exception:
        pass

    settings_variants = (
        {"language": "en-US", "captionPreset": "subtitle_default"},
        {"language": "en-US"},
        {},
    )

    # Resolve's CreateSubtitlesFromAudio transcribes the *mixed* output of
    # ALL non-muted audio tracks. When the background music on A2 (and any
    # SFX on A3+) is loud relative to the dialog on A1, the speech-to-text
    # engine degrades into placeholder strings like "Mumbling". To get a
    # clean transcription, mute every non-dialog audio track for the
    # duration of the call and restore their original mute state afterward.
    muted_tracks = []  # list of (track_index, original_mute_state)
    try:
        audio_track_count = int(timeline.GetTrackCount("audio") or 0)
    except Exception:
        audio_track_count = 0
    for ti in range(2, audio_track_count + 1):
        try:
            was_muted = bool(timeline.GetIsTrackEnabled("audio", ti)) is False
        except Exception:
            was_muted = False
        try:
            # SetTrackEnable(False) = mute that track for playback/render,
            # which is what the AI subtitle engine sees.
            ok = timeline.SetTrackEnable("audio", ti, False)
            muted_tracks.append((ti, was_muted))
            if ok:
                print(f"   🔇 Muted A{ti} for subtitle transcription")
        except Exception as mute_err:
            print(f"   ⚠️ Could not mute A{ti} for subtitles: {mute_err}")

    # Try multiple known/possible API signatures for compatibility across versions.
    attempts = []
    for s in settings_variants:
        attempts.append(
            (f"CreateSubtitlesFromAudio({s})",
             lambda s=s: timeline.CreateSubtitlesFromAudio(s)))
    attempts.append(
        ("CreateSubtitlesFromAudio()", lambda: timeline.CreateSubtitlesFromAudio()))
    for s in settings_variants:
        attempts.append(
            (f"GenerateSubtitlesFromAudio({s})",
             lambda s=s: timeline.GenerateSubtitlesFromAudio(s)))
    attempts.append(
        ("GenerateSubtitlesFromAudio()", lambda: timeline.GenerateSubtitlesFromAudio()))

    last_error = None
    sub_result = None
    for label, fn in attempts:
        try:
            result = fn()
            if result is None:
                last_error = f"{label} returned None"
                continue
            if isinstance(result, bool):
                if result:
                    sub_result = {
                        "attempted": True,
                        "success": True,
                        "message": f"Subtitles generated via {label}",
                    }
                    break
                last_error = f"{label} returned False"
                continue
            sub_result = {
                "attempted": True,
                "success": True,
                "message": f"Subtitles generated via {label}",
            }
            break
        except AttributeError as ae:
            last_error = f"{label}: AttributeError {ae}"
            continue
        except Exception as e:
            last_error = f"{label}: {type(e).__name__} {e}"
            continue

    # Restore the original enabled state for every track we touched.
    for ti, was_muted in muted_tracks:
        try:
            timeline.SetTrackEnable("audio", ti, not was_muted)
        except Exception:
            pass

    if sub_result is not None:
        return sub_result

    detail = f" Last error: {last_error}" if last_error else ""
    return {
        "attempted": True,
        "success": False,
        "message": (
            "Could not auto-generate subtitles via scripting API. "
            "Requires Resolve Studio with Edit page active and a saved project. "
            "Fallback: Timeline > Create Subtitles from Audio."
            f"{detail}"
        ),
    }


def _try_set_track_color(timeline, track_type, track_index, color):
    """Try several method names / color casings to set a track's color.
    Returns True if any attempt succeeds."""
    if not timeline:
        return False
    method_names = ("SetTrackColor", "SetTrackColour")
    color_variants = (color, color.lower(), color.upper(), color.capitalize())
    seen = set()
    color_variants = tuple(c for c in color_variants if not (c in seen or seen.add(c)))
    last_err = None
    for mname in method_names:
        fn = getattr(timeline, mname, None)
        if not callable(fn):
            continue
        for cval in color_variants:
            try:
                res = fn(track_type, track_index, cval)
                if res:
                    _log(f"      \u21b3 {mname}('{track_type}', {track_index}, '{cval}') → True")
                    return True
                else:
                    _log(f"      \u21b3 {mname}('{track_type}', {track_index}, '{cval}') → False")
            except Exception as err:
                last_err = err
    if last_err:
        _log(f"      \u21b3 last error: {last_err}")
    return False


def _setup_video_tracks(timeline):
    """
    Configure the project's video track layout:
        V1 = aroll       (Yellow)
        V2 = adjustment  (Lime)
        V3 = broll       (Teal)
        V4 = animations  (Pink)
        V5 = temp clips  (Violet)
    Adds tracks if missing, renames and colors each one.
    Returns a dict {track_index: track_name} for what was set.
    """
    desired = [
        (1, "aroll", "Yellow"),
        (2, "adjustment", "Lime"),
        (3, "broll", "Teal"),
        (4, "animations", "Pink"),
        (5, "temp clips", "Violet"),
    ]
    if not timeline:
        return {}

    # Diagnostic: log which track-related methods are exposed (one-time per call)
    try:
        methods = [m for m in dir(timeline) if "track" in m.lower() or "color" in m.lower()]
        _log(f"   🔬 Timeline track/color methods: {methods}")
    except Exception:
        pass

    try:
        current_count = int(timeline.GetTrackCount("video") or 1)
    except Exception:
        current_count = 1

    # Add any missing tracks up to V5.
    while current_count < 5:
        try:
            timeline.AddTrack("video")
            current_count += 1
            _log(f"   ➕ Added video track V{current_count}")
        except Exception as add_err:
            _log(f"   ⚠️ Could not add video track V{current_count + 1}: {add_err}")
            break

    applied = {}
    for idx, name, color in desired:
        if idx > current_count:
            continue
        try:
            ok = timeline.SetTrackName("video", idx, name)
            if ok:
                applied[idx] = name
                _log(f"   🏷️  V{idx} → '{name}'")
            else:
                _log(f"   ⚠️ SetTrackName returned False for V{idx} → '{name}'")
        except Exception as name_err:
            _log(f"   ⚠️ SetTrackName failed for V{idx} → '{name}': {name_err}")
        ok_c = _try_set_track_color(timeline, "video", idx, color)
        if ok_c:
            _log(f"   🎨 V{idx} color → {color}")
        else:
            _log(f"   ⚠️ Could not set V{idx} color → {color} (API may not support it)")
    return applied


def _setup_audio_tracks(timeline):
    """
    Configure the project's audio track layout:
        A1 = aroll sound       (Orange)
        A2 = background sound  (Green)
        A3 = sound effects     (Purple)
    Adds tracks if missing, renames and colors each one.
    Returns a dict {track_index: track_name} for what was set.
    """
    desired = [
        (1, "aroll sound", "Orange"),
        (2, "background sound", "Green"),
        (3, "sound effects", "Purple"),
    ]
    if not timeline:
        return {}

    try:
        current_count = int(timeline.GetTrackCount("audio") or 1)
    except Exception:
        current_count = 1

    while current_count < 3:
        try:
            timeline.AddTrack("audio")
            current_count += 1
            _log(f"   ➕ Added audio track A{current_count}")
        except Exception as add_err:
            _log(f"   ⚠️ Could not add audio track A{current_count + 1}: {add_err}")
            break

    applied = {}
    for idx, name, color in desired:
        if idx > current_count:
            continue
        try:
            ok = timeline.SetTrackName("audio", idx, name)
            if ok:
                applied[idx] = name
                _log(f"   🏷️  A{idx} → '{name}'")
            else:
                _log(f"   ⚠️ SetTrackName returned False for A{idx} → '{name}'")
        except Exception as name_err:
            _log(f"   ⚠️ SetTrackName failed for A{idx} → '{name}': {name_err}")
        ok_c = _try_set_track_color(timeline, "audio", idx, color)
        if ok_c:
            _log(f"   🎨 A{idx} color → {color}")
        else:
            _log(f"   ⚠️ Could not set A{idx} color → {color} (API may not support it)")
    return applied


def _add_adjustment_clips_to_v2(media_pool, timeline, source_bin, count=3):
    """
    Place `count` adjustment-layer-style clips onto video track V2
    ('adjustment'), evenly spaced across the timeline duration.

    Why this approach:
      - Resolve's scripting API has NO method to set the destination track
        for `Insert*IntoTimeline()` calls. Locking V1 only makes the call
        refuse silently — it never redirects to V2.
      - The ONLY reliable per-track placement is `MediaPool.AppendToTimeline()`
        with `clip_info["trackIndex"]`. This is what we use here, mirroring
        the proven pattern used by `_add_broll_clips_above_aroll` (V3) and
        `_add_background_audio_clips` (A2).

    We append a short slice of an existing media-pool clip (typically the
    first aRoll video) onto V2 at each target frame, then convert each
    placed timeline item into a Fusion clip via `CreateFusionClip([item])`
    so it behaves like an empty adjustment / Fusion composition over the
    tracks below it.

    Returns: {attempted, success, count, message, clips}
    """
    if not timeline:
        return {"attempted": False, "success": False, "count": 0,
                "message": "No timeline", "clips": []}
    if not media_pool:
        return {"attempted": False, "success": False, "count": 0,
                "message": "No media pool", "clips": []}

    # ------------------------------------------------------------------
    # Find a usable media-pool item to anchor the V2 clip onto.
    # Prefer the supplied source_bin (typically the aRoll bin); fall back
    # to scanning all subfolders for any video clip.
    # ------------------------------------------------------------------
    anchor_clip = None
    try:
        if source_bin:
            for c in (source_bin.GetClipList() or []):
                anchor_clip = c
                break
    except Exception:
        anchor_clip = None
    if anchor_clip is None:
        try:
            root = media_pool.GetRootFolder()
            for sub in (root.GetSubFolders() or {}).values():
                for c in (sub.GetClipList() or []):
                    anchor_clip = c
                    break
                if anchor_clip:
                    break
        except Exception:
            pass
    if anchor_clip is None:
        return {"attempted": True, "success": False, "count": 0,
                "message": "No media-pool clip available to anchor V2 adjustment",
                "clips": []}

    # Compute timeline span.
    try:
        start_frame = int(timeline.GetStartFrame())
    except Exception:
        start_frame = 0
    try:
        end_frame = int(timeline.GetEndFrame())
    except Exception:
        end_frame = 0
    if end_frame <= start_frame:
        try:
            v1_items = timeline.GetItemListInTrack("video", 1) or []
            for item in v1_items:
                try:
                    e = int(item.GetEnd())
                    if e > end_frame:
                        end_frame = e
                except Exception:
                    continue
        except Exception:
            pass

    span = max(0, end_frame - start_frame)
    if span <= 0 or count <= 0:
        return {"attempted": True, "success": False, "count": 0,
                "message": f"Empty timeline span ({start_frame}..{end_frame})",
                "clips": []}

    fps = 24
    try:
        fps_val = timeline.GetSetting("timelineFrameRate")
        if fps_val:
            fps = int(round(float(fps_val)))
    except Exception:
        pass

    # Ensure V2 exists.
    try:
        vc = int(timeline.GetTrackCount("video") or 1)
    except Exception:
        vc = 1
    while vc < 2:
        try:
            timeline.AddTrack("video")
            vc += 1
        except Exception:
            break

    # Each adjustment clip spans its full segment (so V2 is fully covered
    # by adjustment clips back-to-back, which is what an "adjustment
    # layer" pattern looks like in a timeline).
    segment = max(1, span // count)

    # Source-clip duration (for clamping).
    src_dur = 0
    try:
        src_dur = int(anchor_clip.GetClipProperty("Frames") or 0)
    except Exception:
        src_dur = 0
    if src_dur <= 0:
        src_dur = segment  # assume long enough

    _log(f"\n✨ Placing {count} adjustment clip(s) on V2 via AppendToTimeline "
         f"(span {start_frame}..{end_frame} @ {fps}fps, segment {segment}f, "
         f"anchor={anchor_clip.GetName()})")

    appended = []
    placed_items = []
    for i in range(count):
        record_frame = start_frame + i * segment
        clip_len = min(segment, src_dur)
        clip_info = {
            "mediaPoolItem": anchor_clip,
            "trackIndex": 2,        # V2 = adjustment
            "mediaType": 1,         # 1 = video
            "startFrame": 0,
            "endFrame": max(1, clip_len - 1),
            "recordFrame": record_frame,
        }
        try:
            v2_before = {id(it) for it in (timeline.GetItemListInTrack("video", 2) or [])}
            result = media_pool.AppendToTimeline([clip_info])
        except Exception as ap_err:
            _log(f"   ❌ AppendToTimeline V2 #{i+1} raised: {ap_err}")
            continue
        if not result:
            _log(f"   ⚠️ AppendToTimeline V2 #{i+1} @ frame {record_frame} returned empty")
            continue

        # Identify the newly-placed item on V2 so we can convert it to a
        # Fusion clip (adjustment-layer behaviour).
        try:
            v2_after = timeline.GetItemListInTrack("video", 2) or []
            new_items = [it for it in v2_after if id(it) not in v2_before]
        except Exception:
            new_items = []

        new_item = new_items[0] if new_items else None
        if new_item:
            placed_items.append(new_item)
            try:
                new_item.SetClipColor("Teal")
            except Exception:
                pass
            try:
                new_item.SetName(f"Adjustment {i+1}")
            except Exception:
                pass

        appended.append(f"adjustment_{i+1}")
        _log(f"   ✅ V2 #{i+1} placed @ frame {record_frame} (+{clip_len}f)")

    # Convert all placed V2 items to a single Fusion clip so they act
    # like an adjustment layer (empty Fusion comp = transparent passthrough
    # that effects below propagate through). Best-effort.
    if placed_items:
        for it in placed_items:
            try:
                fusion_clip = timeline.CreateFusionClip([it])
                if fusion_clip:
                    _log(f"   🎬 Converted V2 item to Fusion clip")
            except Exception as fc_err:
                _log(f"   ⚠️ CreateFusionClip skipped: {fc_err}")

    if appended:
        return {"attempted": True, "success": True, "count": len(appended),
                "message": f"Placed {len(appended)} adjustment clip(s) on V2",
                "clips": appended}
    return {"attempted": True, "success": False, "count": 0,
            "message": "AppendToTimeline did not place any adjustment clips on V2",
            "clips": []}


def _add_background_audio_clips(media_pool, timeline, audio_bin):
    """
    Place background music clips on audio track A2 ('background sound') in
    a fixed order:
        1. AI with Roz Build Up.wav  (intro sting, once at the very start)
        2. 'Designed, Riser, Epic Sunrise Riser SND64445.wav'  (riser into the bed)
        3. 'Musical, Loop, Serious News Loop, Bass Octave Up Down,
            Stutter Chord SND84939.wav'  (repeated 2x per aRoll clip on V1)
        4. 'Designed, Riser, Epic Sunrise Riser SND64445.wav'  (riser tail)
        5. 'Mood Background Music.wav'  (mood bed, last A2 clip)
    Sequenced back-to-back starting at the timeline start frame.

    Also places a one-shot SFX on A3 ('sound effects') at the timeline
    start: 'Computers, Keyboard   Mouse, Classic Keyboard Typing SND81694.wav'.
    """
    build_up_name = "AI with Roz Build Up.wav"
    riser_name = "Designed, Riser, Epic Sunrise Riser SND64445.wav"
    main_bg_name = (
        "Musical, Loop, Serious News Loop, Bass Octave Up Down, "
        "Stutter Chord SND84939.wav"
    )
    mood_bg_name = "Mood Background Music.wav"
    sfx_intro_name = (
        "Computers, Keyboard   Mouse, Classic Keyboard Typing SND81694.wav"
    )
    sfx_swoosh_name = "AI Roz Swoosh.wav"
    main_bg_per_aroll = 2

    if not audio_bin:
        return {
            "attempted": False,
            "success": False,
            "count": 0,
            "message": "No audio bin available",
            "clips": [],
        }
    if not timeline or not media_pool:
        return {
            "attempted": True,
            "success": False,
            "count": 0,
            "message": "Timeline or media pool unavailable",
            "clips": [],
        }

    try:
        audio_clips = audio_bin.GetClipList() or []
    except Exception as list_err:
        return {
            "attempted": True,
            "success": False,
            "count": 0,
            "message": f"Could not list audio clips: {list_err}",
            "clips": [],
        }

    # Build name -> clip map (case-insensitive, also try basename).
    by_name = {}
    for c in audio_clips:
        try:
            n = c.GetName() or ""
        except Exception:
            continue
        by_name[n.lower()] = c

    # Ensure A2 exists.
    try:
        audio_track_count = int(timeline.GetTrackCount("audio") or 1)
    except Exception:
        audio_track_count = 1
    while audio_track_count < 2:
        try:
            timeline.AddTrack("audio")
            audio_track_count += 1
            print(f"   ➕ Added audio track A{audio_track_count} (fallback)")
        except Exception as add_err:
            print(f"   ⚠️ Could not add audio track A{audio_track_count + 1}: {add_err}")
            break

    try:
        start_frame = int(timeline.GetStartFrame())
    except Exception:
        start_frame = 0

    def _audio_duration_frames(mp_item):
        for prop in ("Frames", "Duration"):
            try:
                val = mp_item.GetClipProperty(prop)
            except Exception:
                val = None
            if not val:
                continue
            try:
                if str(val).isdigit():
                    return int(val)
            except Exception:
                pass
            try:
                parts = str(val).split(":")
                if len(parts) == 4:
                    h, m, s, f = (int(p) for p in parts)
                    fps = 24
                    try:
                        fps_val = mp_item.GetClipProperty("FPS")
                        if fps_val:
                            fps = int(round(float(fps_val)))
                    except Exception:
                        pass
                    return ((h * 3600) + (m * 60) + s) * fps + f
            except Exception:
                continue
        return 0

    appended = []
    missing = []
    cursor = start_frame

    # Count aRoll clips on V1 so we can repeat Main Background that many times.
    try:
        aroll_items = timeline.GetItemListInTrack("video", 1) or []
        aroll_count = len(aroll_items)
    except Exception:
        aroll_count = 0
    if aroll_count <= 0:
        aroll_count = 1
    print(f"   🔁 Repeating '{main_bg_name}' {aroll_count * main_bg_per_aroll}x "
          f"({main_bg_per_aroll} per aRoll clip on V1, {aroll_count} aRoll clips)")

    desired_order = (
        [build_up_name]
        + [riser_name]
        + [main_bg_name] * (aroll_count * main_bg_per_aroll)
        + [riser_name]
        + [mood_bg_name]
    )

    for target in desired_order:
        clip = by_name.get(target.lower())
        if not clip:
            # Try without extension match.
            base = target.rsplit(".", 1)[0].lower()
            for k, v in by_name.items():
                if k.rsplit(".", 1)[0] == base:
                    clip = v
                    break
        if not clip:
            print(f"   ⚠️ Background audio not found in audio bin: {target}")
            if target not in missing:
                missing.append(target)
            continue

        duration = _audio_duration_frames(clip)
        clip_info = {
            "mediaPoolItem": clip,
            "trackIndex": 2,
            "mediaType": 2,        # 2 = audio
            "recordFrame": cursor,
        }
        try:
            result = media_pool.AppendToTimeline([clip_info])
        except Exception as ap_err:
            print(f"   ❌ AppendToTimeline failed for {target}: {ap_err}")
            continue
        if result:
            appended.append(target)
            print(f"   ✅ A2 @ frame {cursor} (+{duration}f): {target}")
            cursor += duration if duration > 0 else 24
        else:
            print(f"   ⚠️ AppendToTimeline returned empty for {target} @ frame {cursor}")

    # Place a one-shot keyboard-typing SFX on A3 at the timeline start.
    sfx_clip = by_name.get(sfx_intro_name.lower())
    if not sfx_clip:
        sfx_base = sfx_intro_name.rsplit(".", 1)[0].lower()
        for k, v in by_name.items():
            if k.rsplit(".", 1)[0] == sfx_base:
                sfx_clip = v
                break
    if sfx_clip:
        # Ensure A3 exists.
        try:
            cur_audio = int(timeline.GetTrackCount("audio") or 1)
        except Exception:
            cur_audio = 1
        while cur_audio < 3:
            try:
                timeline.AddTrack("audio")
                cur_audio += 1
                print(f"   ➕ Added audio track A{cur_audio} (fallback for SFX)")
            except Exception as add_err:
                print(f"   ⚠️ Could not add audio track A{cur_audio + 1}: {add_err}")
                break
        sfx_info = {
            "mediaPoolItem": sfx_clip,
            "trackIndex": 3,
            "mediaType": 2,
            "recordFrame": start_frame,
        }
        try:
            sfx_result = media_pool.AppendToTimeline([sfx_info])
        except Exception as sfx_err:
            sfx_result = None
            print(f"   ❌ AppendToTimeline failed for SFX {sfx_intro_name}: {sfx_err}")
        if sfx_result:
            appended.append(sfx_intro_name)
            print(f"   ✅ A3 @ frame {start_frame}: {sfx_intro_name}")
        else:
            print(f"   ⚠️ AppendToTimeline returned empty for SFX {sfx_intro_name}")
    else:
        print(f"   ⚠️ SFX not found in audio bin: {sfx_intro_name}")
        if sfx_intro_name not in missing:
            missing.append(sfx_intro_name)

    # Place "AI Roz Swoosh.wav" on A3 alongside the other sound effects,
    # sequenced right after the keyboard-typing SFX so the two don't overlap.
    swoosh_clip = by_name.get(sfx_swoosh_name.lower())
    if not swoosh_clip:
        swoosh_base = sfx_swoosh_name.rsplit(".", 1)[0].lower()
        for k, v in by_name.items():
            if k.rsplit(".", 1)[0] == swoosh_base:
                swoosh_clip = v
                break
    if swoosh_clip:
        # Ensure A3 still exists (it should, from the keyboard SFX block above).
        try:
            cur_audio = int(timeline.GetTrackCount("audio") or 1)
        except Exception:
            cur_audio = 1
        while cur_audio < 3:
            try:
                timeline.AddTrack("audio")
                cur_audio += 1
                print(f"   ➕ Added audio track A{cur_audio} (fallback for Swoosh SFX)")
            except Exception as add_err:
                print(f"   ⚠️ Could not add audio track A{cur_audio + 1}: {add_err}")
                break

        # Sequence after the keyboard SFX if we placed it; otherwise at start.
        swoosh_start = start_frame
        if sfx_clip:
            kb_duration = _audio_duration_frames(sfx_clip)
            if kb_duration > 0:
                swoosh_start = start_frame + kb_duration

        swoosh_info = {
            "mediaPoolItem": swoosh_clip,
            "trackIndex": 3,
            "mediaType": 2,
            "recordFrame": swoosh_start,
        }
        try:
            swoosh_result = media_pool.AppendToTimeline([swoosh_info])
        except Exception as swoosh_err:
            swoosh_result = None
            print(f"   ❌ AppendToTimeline failed for SFX {sfx_swoosh_name}: {swoosh_err}")
        if swoosh_result:
            appended.append(sfx_swoosh_name)
            print(f"   ✅ A3 @ frame {swoosh_start}: {sfx_swoosh_name}")
        else:
            print(f"   ⚠️ AppendToTimeline returned empty for SFX {sfx_swoosh_name}")
    else:
        print(f"   ⚠️ SFX not found in audio bin: {sfx_swoosh_name}")
        if sfx_swoosh_name not in missing:
            missing.append(sfx_swoosh_name)

    if appended:
        return {
            "attempted": True,
            "success": True,
            "count": len(appended),
            "message": f"Added {len(appended)} background audio clip(s) to A2",
            "clips": appended,
            "missing": missing,
        }
    return {
        "attempted": True,
        "success": False,
        "count": 0,
        "message": "AppendToTimeline did not place any background audio clips on A2",
        "clips": [],
        "missing": missing,
    }


def _extract_magic_zoom_setting():
    """Extract MagicZoomPro.setting from the installed .drfx (zip) to a
    temp path and return its absolute path. Cached after first call."""
    import tempfile, zipfile
    cache_dir = Path(tempfile.gettempdir()) / "scriptcraft_fusion_settings"
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_path = cache_dir / "MagicZoomPro.setting"
    if out_path.exists() and out_path.stat().st_size > 0:
        return str(out_path)

    drfx = Path.home() / "Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Templates/MagicZoomPro.drfx"
    if not drfx.exists():
        return None
    try:
        with zipfile.ZipFile(drfx, "r") as z:
            for member in z.namelist():
                if member.endswith("/MagicZoomPro.setting") and "1. MagicZoom/" in member:
                    with z.open(member) as src, open(out_path, "wb") as dst:
                        dst.write(src.read())
                    return str(out_path)
    except Exception:
        return None
    return None


def _apply_effect_to_aroll_clips(timeline, effect_name="MagicZoomPro"):
    """
    Apply a Resolve FX / OpenFX video effect to every clip on the aRoll
    track (V1). Tries a few API method variants for compatibility across
    Resolve versions.

    Returns a result dict: {attempted, success, count, message, applied_to}
    """
    if not timeline:
        return {
            "attempted": False,
            "success": False,
            "count": 0,
            "message": "Timeline unavailable",
            "applied_to": [],
        }

    try:
        items = timeline.GetItemListInTrack("video", 1) or []
    except Exception as list_err:
        return {
            "attempted": True,
            "success": False,
            "count": 0,
            "message": f"Could not list V1 items: {list_err}",
            "applied_to": [],
        }

    if not items:
        return {
            "attempted": True,
            "success": False,
            "count": 0,
            "message": "No clips on V1 (aroll) to apply effect to",
            "applied_to": [],
        }

    # Effect name candidates. MagicZoomPro is a Fusion .drfx template (not
    # OFX), so AddVideoEffect should accept its display name as it appears
    # in the Effects Library. We also try a few path-style variants in case
    # Resolve namespaces it under its toolkit folder.
    name_candidates = [
        effect_name,
        effect_name.replace(" ", ""),
        "Magic Zoom Pro",
        "MagicZoom Pro",
        "MagicToolkit/MagicZoom/MagicZoomPro",
        "MagicZoom/MagicZoomPro",
        "Effects/MagicToolkit/MagicZoom/MagicZoomPro",
    ]
    # De-dup while preserving order.
    seen = set()
    name_candidates = [n for n in name_candidates if not (n in seen or seen.add(n))]

    print(f"\n✨ Applying '{effect_name}' to {len(items)} aRoll clip(s) on V1...")

    applied_to = []
    failures = []
    for idx, item in enumerate(items, 1):
        try:
            clip_name = item.GetName()
        except Exception:
            clip_name = f"V1 item #{idx}"

        success = False
        last_err = None
        for cand in name_candidates:
            # Try AddVideoEffect (Resolve 19.1+) — works for Resolve FX and
            # Fusion-template .drfx effects when called with display name.
            try:
                fn = getattr(item, "AddVideoEffect", None)
                if callable(fn):
                    res = fn(cand)
                    if res:
                        success = True
                        print(f"   \u21b3 matched name candidate: '{cand}'")
                        break
            except Exception as err:
                last_err = err
            # Older / alternate methods on some Resolve builds.
            for alt_method in ("AddPlugin", "AddOFXPlugin", "AddEffect"):
                try:
                    fn = getattr(item, alt_method, None)
                    if callable(fn):
                        res = fn(cand)
                        if res:
                            success = True
                            print(f"   \u21b3 matched via {alt_method}('{cand}')")
                            break
                except Exception as err:
                    last_err = err
            if success:
                break

        # Fusion-comp fallback: import the extracted .setting file directly
        # onto the clip. Works for Fusion-template based .drfx effects.
        if not success:
            setting_path = _extract_magic_zoom_setting()
            if setting_path:
                for fusion_method in ("ImportFusionCompFromFile", "LoadFusionCompFromFile"):
                    try:
                        fn = getattr(item, fusion_method, None)
                        if callable(fn):
                            res = fn(setting_path)
                            if res:
                                success = True
                                print(f"   \u21b3 matched via {fusion_method}('{setting_path}')")
                                # If imported, also try to activate by name.
                                if fusion_method == "ImportFusionCompFromFile":
                                    try:
                                        load_fn = getattr(item, "LoadFusionCompByName", None)
                                        if callable(load_fn):
                                            load_fn("MagicZoomPro")
                                    except Exception:
                                        pass
                                break
                    except Exception as err:
                        last_err = err

        if success:
            applied_to.append(clip_name)
            print(f"   ✅ {clip_name}")
        else:
            failures.append(clip_name)
            err_txt = f" ({last_err})" if last_err else ""
            print(f"   ⚠️ Could not apply '{effect_name}' to {clip_name}{err_txt}")

    if applied_to:
        return {
            "attempted": True,
            "success": True,
            "count": len(applied_to),
            "message": f"Applied '{effect_name}' to {len(applied_to)}/{len(items)} aRoll clip(s)",
            "applied_to": applied_to,
            "failures": failures,
        }
    return {
        "attempted": True,
        "success": False,
        "count": 0,
        "message": (
            f"Could not apply '{effect_name}' via scripting API. Your Resolve "
            "version may not expose AddVideoEffect for this OFX plugin — apply "
            "manually from the Effects panel."
        ),
        "applied_to": [],
        "failures": failures,
    }


def _broll_sort_key(clip_name: str):
    """
    Order broll clips by the index baked into the filename.

    Recognized naming patterns (case-insensitive, the leading folder/path
    is ignored — only the basename matters):

      1. ``grok_<timestamp>_<index>_<safe_term>.<ext>``  — produced by Grok
         e.g. ``grok_20260427_193603_05_cluttered_fitness_app.mp4``
      2. ``broll_<timestamp>_<index>_<safe_term>.<ext>``  — manual stock
         (recommended), with or without an extension
         e.g. ``broll_20260502_143022_05_gym_workout_montage.mov``
      3. ``broll_<index>_<anything>.<ext>``  — manual without timestamp
         e.g. ``broll_05_shutterstock_gym_montage.mp4``
      4. ``<index>_<anything>.<ext>``  — bare-index shorthand
         e.g. ``05_shutterstock_gym_montage.mp4``

    The ``<index>`` controls timeline order: clip with index 0 (or 00, 01…)
    is the first on V3, index 1 is the second, etc. Use zero-padded indexes
    (e.g. 01, 02 … 33) so the count matches the broll table row order even
    when you have more than 9 clips.

    Files that match no pattern sort to the end alphabetically.
    """
    import os as _os
    import re
    name = _os.path.basename(clip_name or "")
    lower = name.lower()

    # Pattern 1: grok_<ts>_<idx>_*
    m = re.match(r"grok_(\d+)_(\d+)_", lower)
    if m:
        ts = int(m.group(1))
        idx = int(m.group(2))
        return (0, idx, ts, lower)

    # Pattern 2: broll_<ts>_<idx>_*  (timestamped manual download)
    # Timestamp is 8+ digits (e.g. YYYYMMDD or YYYYMMDD_HHMMSS collapsed),
    # but to be lenient we accept any ≥6-digit number here.
    m = re.match(r"broll_(\d{6,})_(\d+)[_\-.]", lower)
    if m:
        ts = int(m.group(1))
        idx = int(m.group(2))
        return (0, idx, ts, lower)

    # Pattern 3: broll_<idx>_*  (no timestamp)
    m = re.match(r"broll_(\d+)[_\-.]", lower)
    if m:
        return (0, int(m.group(1)), 0, lower)

    # Pattern 4: <idx>_*  (bare leading number)
    m = re.match(r"(\d+)[_\-.]", lower)
    if m:
        return (0, int(m.group(1)), 0, lower)

    return (1, 0, 0, lower)


def _apply_fade_out_to_v3_clips(timeline, fade_seconds: float = 1.0, track_index: int = 3):
    """
    Add an opacity fade-out at the tail end of every clip on the given video
    track (default V3 = broll). The clip ramps from full opacity down to 0
    over the last `fade_seconds` of its duration so it eases back to the
    aroll underneath.

    Implementation:
      1. Try the documented TimelineItem keyframe API:
           item.AddVideoFadeKeyframe / SetClipEnabled - not in public API
         then fall back to opacity-property keyframes:
           item.SetProperty("Opacity", 100) at fade-start frame
           item.SetProperty("Opacity", 0)   at clip-end frame
         using item.AddKeyframe(propertyName, frame) when available.
      2. If keyframe APIs aren't exposed, fall back to a single static
         opacity reduction (logged) so we at least don't error out.

    Returns: {success, applied, skipped, failed, message, errors}
    """
    result = {
        "attempted": True,
        "success": False,
        "applied": 0,
        "skipped": 0,
        "failed": 0,
        "errors": [],
        "message": "",
    }
    if not timeline:
        result["message"] = "No timeline."
        return result

    try:
        items = timeline.GetItemListInTrack("video", track_index) or []
    except Exception as e:
        result["message"] = f"GetItemListInTrack failed: {e}"
        return result
    if not items:
        result["message"] = f"No clips on V{track_index}."
        return result

    # Determine timeline framerate so we can convert seconds → frames.
    fps = 24.0
    try:
        raw_fps = timeline.GetSetting("timelineFrameRate")
        if raw_fps:
            fps = float(raw_fps)
    except Exception:
        pass
    fade_frames = max(1, int(round(fade_seconds * fps)))

    print(f"\n🌅 Applying {fade_seconds}s fade-out ({fade_frames}f @ {fps}fps) to V{track_index} clips...")

    for idx, item in enumerate(items):
        try:
            name = item.GetName() or f"<clip {idx}>"
        except Exception:
            name = f"<clip {idx}>"
        try:
            duration = int(item.GetDuration() or 0)
        except Exception:
            duration = 0
        if duration <= 1:
            result["skipped"] += 1
            print(f"   ⏭️  {name}: duration <= 1, skipping")
            continue

        # Clamp fade so it doesn't exceed clip length
        local_fade = min(fade_frames, max(1, duration - 1))
        # Frames are clip-local (0..duration-1) for SetProperty/AddKeyframe APIs.
        fade_start_local = duration - local_fade
        fade_end_local = duration - 1

        applied_method = None
        last_err = None

        # --- Strategy 1: keyframed Opacity via AddKeyframe / SetProperty ---
        try:
            add_kf = getattr(item, "AddKeyframe", None)
            set_prop = getattr(item, "SetProperty", None)
            if callable(add_kf) and callable(set_prop):
                # Some Resolve builds expect property-value-at-frame writes.
                # Try the "AddKeyframe(prop, frame)" + "SetProperty(prop, val)"
                # pattern: jump playhead is not needed because AddKeyframe is
                # frame-addressed.
                ok1 = add_kf("Opacity", fade_start_local)
                set_prop("Opacity", 100.0)
                ok2 = add_kf("Opacity", fade_end_local)
                set_prop("Opacity", 0.0)
                if ok1 or ok2:
                    applied_method = "AddKeyframe+SetProperty"
        except Exception as e:
            last_err = e

        # --- Strategy 2: SetProperty with (name, value, frame) signature ---
        if not applied_method:
            try:
                set_prop = getattr(item, "SetProperty", None)
                if callable(set_prop):
                    r1 = set_prop("Opacity", 100.0, fade_start_local)
                    r2 = set_prop("Opacity", 0.0, fade_end_local)
                    if r1 or r2:
                        applied_method = "SetProperty(name,val,frame)"
            except Exception as e:
                last_err = e

        # --- Strategy 3: AddFlag/AddVideoOpacityKeyframe variants ---
        if not applied_method:
            for meth in ("AddVideoOpacityKeyframe", "AddOpacityKeyframe"):
                try:
                    fn = getattr(item, meth, None)
                    if callable(fn):
                        r1 = fn(fade_start_local, 100.0)
                        r2 = fn(fade_end_local, 0.0)
                        if r1 or r2:
                            applied_method = meth
                            break
                except Exception as e:
                    last_err = e

        if applied_method:
            result["applied"] += 1
            print(f"   ✅ {name}: fade-out via {applied_method} (frames {fade_start_local}→{fade_end_local})")
        else:
            result["failed"] += 1
            err = f"{name}: no opacity-keyframe API succeeded ({last_err})"
            result["errors"].append(err)
            print(f"   ⚠️ {err}")

    total = len(items)
    result["success"] = result["applied"] > 0
    result["message"] = (
        f"Faded {result['applied']}/{total} V{track_index} clip(s) "
        f"({result['skipped']} skipped, {result['failed']} failed)"
    )
    return result


def _clear_comp_tools(comp, name: str):
    """
    Delete every tool from `comp` so a subsequent Paste of a full preset
    (MediaIn1/MediaIn2/macro/MediaOut1) doesn't collide with existing
    tool names. Resolve renames pasted tools to ..._1 on collision, which
    breaks the preset's internal SourceOp wiring and silently drops nodes.
    """
    if comp is None:
        return
    try:
        gtl = getattr(comp, "GetToolList", None)
        if not callable(gtl):
            return
        tools = gtl(False) or {}
        deleted = 0
        for _k, t in list(tools.items()):
            try:
                tname = ""
                try:
                    tname = t.GetAttrs().get("TOOLS_Name") or ""
                except Exception:
                    pass
                # Use Comp.Delete(tool) if available; some builds expose it
                # only on the tool itself as Delete().
                ok = False
                try:
                    delete_fn = getattr(t, "Delete", None)
                    if callable(delete_fn):
                        delete_fn()
                        ok = True
                except Exception:
                    pass
                if ok:
                    deleted += 1
            except Exception:
                pass
        print(f"      🧹 {name}: cleared {deleted} pre-existing tool(s)")
    except Exception as _ce:
        print(f"      ⚠️ {name}: clear comp failed: {_ce}")


def _rewire_tiles_swap_with_fade(comp, item, timeline, name: str):
    """
    Find the pasted mTuber_4_Tiles_Swap macro inside `comp` (handles
    Resolve-renamed copies like `_1`), wire MediaIn1 → macro.Input1+Input2,
    insert AlphaMultiply(1.0→0.0) keyframed over the last second, and
    point MediaOut1 at it.

    Returns True if MediaOut1 was successfully connected to either the
    macro or the AlphaMultiply node.
    """
    if comp is None:
        return False
    try:
        media_in = comp.FindTool("MediaIn1")
        media_out = comp.FindTool("MediaOut1")
    except Exception:
        media_in = media_out = None

    # Locate the Tiles Swap macro by scanning all tools.
    mtuber = None
    try:
        tl = comp.GetToolList(False) or {}
        all_names = []
        for _k, _t in tl.items():
            try:
                tname = _t.GetAttrs().get("TOOLS_Name") or ""
            except Exception:
                tname = ""
            all_names.append(tname or "?")
            # Accept ANY mTuber-named tool. Resolve sometimes flattens the
            # macro and assigns it the inner engine name (mTuber_4_Pixels
            # vs mTuber_4_Tiles_Swap) — match on the common prefix so the
            # fade still attaches and MediaOut1 still gets rewired.
            if tname.startswith("mTuber"):
                mtuber = _t
        if mtuber:
            print(f"      🎯 {name}: matched macro tool in tools={all_names}")
        else:
            print(f"      ⚠️ {name}: no Tiles_Swap macro found. Tools: {all_names}")
    except Exception as _se:
        print(f"      ⚠️ {name}: tool scan failed: {_se}")

    if not mtuber:
        return False

    # Macro-only preset: comp already has MediaIn1 (auto-bound to this
    # V3 broll clip) and MediaOut1. We need to wire:
    #   macro.Input2 ← MediaIn1            (foreground = this broll clip)
    #   macro.Input1 ← Background (transparent, since per-clip comp has
    #                              no second media — the wipe reveals
    #                              transparency, which composites over
    #                              whatever is on V1/V2 below)
    #   MediaOut1.Input ← AlphaMultiply ← macro
    if media_out is None:
        print(f"      ↪️  {name}: comp lacks MediaOut1 — abort rewire")
        return False
    if media_in is None:
        print(f"      ↪️  {name}: comp lacks MediaIn1 — abort rewire")
        return False

    # 1) Add a transparent Background for macro.Input1.
    bg_node = None
    try:
        add_tool = getattr(comp, "AddTool", None)
        if callable(add_tool):
            bg_node = add_tool("Background", -32768, -32768)
            if bg_node:
                try:
                    bg_node.SetInput("TopLeftAlpha", 0.0)
                    bg_node.SetInput("TopLeftRed", 0.0)
                    bg_node.SetInput("TopLeftGreen", 0.0)
                    bg_node.SetInput("TopLeftBlue", 0.0)
                    bg_node.SetInput("Type", 0)  # solid
                except Exception:
                    pass
                print(f"      ➕ {name}: added transparent Background")
    except Exception as _be:
        print(f"      ⚠️ {name}: AddTool(Background) failed: {_be}")

    # 2) Wire macro inputs.
    try:
        if bg_node is not None:
            mtuber.ConnectInput("Input1", bg_node)
            print(f"      🔗 {name}: macro.Input1 ← Background")
    except Exception as _w1:
        print(f"      ⚠️ {name}: macro.Input1 ← Background failed: {_w1}")
    try:
        mtuber.ConnectInput("Input2", media_in)
        print(f"      🔗 {name}: macro.Input2 ← MediaIn1")
    except Exception as _w2:
        print(f"      ⚠️ {name}: macro.Input2 ← MediaIn1 failed: {_w2}")

    fade_node = None
    try:
        fps2 = 24.0
        try:
            fps2 = float(timeline.GetSetting("timelineFrameRate") or 24)
        except Exception:
            pass
        fade_frames2 = max(1, int(round(1.0 * fps2)))
        g_start = g_end = None
        try:
            cattrs = comp.GetAttrs() or {}
            g_start = cattrs.get("COMPN_GlobalStart")
            g_end = cattrs.get("COMPN_GlobalEnd")
        except Exception:
            pass
        if g_start is None or g_end is None:
            try:
                g_start = int(item.GetStart())
                g_end = int(item.GetEnd())
            except Exception:
                g_start = 0
                g_end = fade_frames2 * 5

        fade_start_f = max(int(g_start), int(g_end) - fade_frames2)
        fade_end_f = int(g_end) - 1

        try:
            add_tool = getattr(comp, "AddTool", None)
            if callable(add_tool):
                fade_node = add_tool("AlphaMultiply", -32768, -32768)
        except Exception as _ae:
            print(f"      ⚠️ {name}: AddTool(AlphaMultiply) failed: {_ae}")

        if fade_node:
            try:
                fade_node.ConnectInput("Input", mtuber)
                print(f"      🔗 {name}: connected AlphaMultiply.Input ← macro")
            except Exception as _ce:
                print(f"      ⚠️ {name}: AlphaMultiply.Input←macro failed: {_ce}")
            try:
                fade_node.SetInput("Multiplier", 1.0, fade_start_f)
                fade_node.SetInput("Multiplier", 0.0, fade_end_f)
                print(f"      🌅 {name}: fade Multiplier 1.0@{fade_start_f} → 0.0@{fade_end_f}")
            except Exception as _ke:
                print(f"      ⚠️ {name}: SetInput keyframe failed: {_ke}")
                try:
                    fade_node.SetInput("Multiplier", 1.0)
                except Exception:
                    pass
    except Exception as _fe:
        print(f"      ⚠️ {name}: fade injection failed: {_fe}")

    out_src = fade_node if fade_node else mtuber
    if media_out and out_src:
        try:
            media_out.ConnectInput("Input", out_src)
            print(f"      🔗 {name}: connected MediaOut1.Input ← {'AlphaMultiply' if fade_node else 'macro'}")
            return True
        except Exception as _ce:
            print(f"      ⚠️ {name}: ConnectInput MediaOut1←out failed: {_ce}")
    return False


def _apply_wipe_to_v3_clips(timeline, track_index: int = 3,
                            settings_path: str = None,
                            slide_seconds: float = 0.4):
    """
    Apply the user's saved Fusion wipe (myswipe.setting) to every clip on
    the given video track. The preset is a Transform driven by a PolyPath
    + BezierSpline displacement that slides the image off-screen on entry
    and exit.

    Strategy A (preferred): comp.Paste(settings_text). The pasted MediaIn
    /MediaOut from the .setting are deleted and the existing MediaIn1/
    MediaOut1 are rewired into the pasted CustomWipe.

    Strategy B (fallback if Paste fails / produces no Transform): build a
    Transform manually with AddTool and animate it directly. Because the
    Resolve external-Python bridge can't easily keyframe a Point input
    (Center) without a path modifier, the fallback animates Transform's
    `Size` (numeric, proven to keyframe via BezierSpline) — zooming the
    image in from 0→1 on entry and out 1→0 on exit. Not the same look as
    a slide-off, but at least visibly animated so the user sees the
    pipeline ran. We also keyframe `Angle` for an extra cue.

    Args:
        timeline: DaVinci Resolve timeline object.
        track_index: Video track to operate on (default 3 = V3 broll).
        settings_path: Path to the .setting file.
        slide_seconds: How long the slide-in (and slide-out) should take.
    """
    import os as _os
    if not settings_path:
        _here = _os.path.dirname(_os.path.abspath(__file__))
        settings_path = _os.path.join(_here, "fusion_presets", "myswipe.setting")

    result = {"success": False, "message": "", "applied": 0, "failed": 0,
              "errors": [], "strategy_a": 0, "strategy_b": 0}

    try:
        with open(settings_path, "r") as _f:
            settings_text = _f.read()
        print(f"   📄 wipe preset: {settings_path} ({len(settings_text)} bytes)")
    except Exception as e:
        result["message"] = f"Could not read wipe preset {settings_path}: {e}"
        settings_text = None
        print(f"   ⚠️ {result['message']}")

    try:
        items = timeline.GetItemListInTrack("video", track_index) or []
    except Exception as e:
        result["message"] = f"GetItemListInTrack(video, {track_index}) failed: {e}"
        return result
    if not items:
        result["success"] = True
        result["message"] = f"No clips on V{track_index}; nothing to wipe."
        return result

    try:
        fps = float(timeline.GetSetting("timelineFrameRate") or 24)
    except Exception:
        fps = 24.0
    slide_frames_target = max(1, int(round(slide_seconds * fps)))

    print(f"   🌬️ Applying wipe to {len(items)} V{track_index} clip(s) "
          f"(slide ~{slide_frames_target}f @ {fps:.2f}fps)")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _list_tools(_comp):
        out = []
        try:
            tl = _comp.GetToolList(False) or {}
            if isinstance(tl, dict):
                keys = list(tl.keys())
            else:
                keys = list(range(1, len(tl) + 1))
            for k in keys:
                t = tl[k]
                if t is None:
                    continue
                try:
                    out.append((t.Name, (t.GetAttrs() or {}).get("TOOLS_RegID", "?"), t))
                except Exception:
                    pass
        except Exception:
            pass
        return out

    def _set_keys(spline, keys, label):
        if spline is None:
            return False
        try:
            spline.SetKeyFrames(keys)
            return True
        except Exception:
            pass
        try:
            for _f, _v in keys.items():
                spline["Value"][_f] = _v[1]
            return True
        except Exception as _e:
            print(f"      ⚠️ {label}: spline keyframe write failed: {_e}")
            return False

    # ------------------------------------------------------------------
    # Per-clip
    # ------------------------------------------------------------------
    for item in items:
        try:
            name = item.GetName() or "<unnamed>"
        except Exception:
            name = "<unnamed>"

        # Get or create per-clip Fusion comp.
        comp = None
        try:
            cnt = item.GetFusionCompCount() or 0
            if cnt >= 1:
                comp = item.GetFusionCompByIndex(1)
            else:
                add_fn = getattr(item, "AddFusionComp", None)
                if callable(add_fn):
                    comp = add_fn()
        except Exception as e:
            result["errors"].append(f"{name}: get/add comp: {e}")
            result["failed"] += 1
            continue
        if comp is None:
            result["errors"].append(f"{name}: no comp returned")
            result["failed"] += 1
            continue

        # COMP-LOCAL frame range.
        f_start, f_end = 0, 24
        try:
            cattrs = comp.GetAttrs() or {}
            gs = cattrs.get("COMPN_GlobalStart")
            ge = cattrs.get("COMPN_GlobalEnd")
            if gs is not None and ge is not None and ge > gs:
                f_start = int(gs)
                f_end = int(ge) - 1
            else:
                raise ValueError("no comp range")
        except Exception:
            try:
                dur = int(item.GetEnd()) - int(item.GetStart())
                f_start = 0
                f_end = max(1, dur - 1)
            except Exception:
                pass
        if f_end <= f_start:
            f_end = f_start + 1
        clip_len = f_end - f_start
        slide_frames = max(1, min(slide_frames_target, clip_len * 4 // 10))
        k_in_done = f_start + slide_frames
        k_out_start = f_end - slide_frames
        if k_out_start <= k_in_done:
            k_out_start = k_in_done + 1
            if k_out_start >= f_end:
                f_end = k_out_start + 1

        media_in = comp.FindTool("MediaIn1")
        media_out = comp.FindTool("MediaOut1")
        if media_in is None or media_out is None:
            result["errors"].append(
                f"{name}: comp missing MediaIn1={media_in is not None} "
                f"MediaOut1={media_out is not None}"
            )
            result["failed"] += 1
            continue

        # ----------------------------------------------------------------
        # Strategy A: paste the .setting OUTSIDE the lock (Lock() blocks
        # Paste in Fusion).
        # ----------------------------------------------------------------
        wipe = comp.FindTool("CustomWipe")
        disp_spline = comp.FindTool("Path1Displacement")

        if wipe is None and settings_text:
            tools_before = {n for (n, _r, _t) in _list_tools(comp)}
            paste_fn = getattr(comp, "Paste", None)
            paste_ok = None
            if callable(paste_fn):
                try:
                    paste_ok = paste_fn(settings_text)
                except Exception as _pe:
                    print(f"      ⚠️ {name}: Paste threw: {_pe}")
                    paste_ok = False
            else:
                print(f"      ⚠️ {name}: comp.Paste not callable")
            tools_after = _list_tools(comp)
            new_tools = [(n, r, t) for (n, r, t) in tools_after if n not in tools_before]
            print(f"      📋 {name}: Paste returned {paste_ok!r}, "
                  f"+{len(new_tools)} tool(s): "
                  f"{[(n, r) for (n, r, _t) in new_tools]}")

            extra_media = []
            for (n, r, t) in new_tools:
                if r in ("MediaIn", "MediaOut"):
                    extra_media.append(t)
                elif r == "Transform" and wipe is None:
                    wipe = t
                elif r == "BezierSpline" and disp_spline is None:
                    disp_spline = t

            for t in extra_media:
                try:
                    delete_fn = getattr(t, "Delete", None)
                    if callable(delete_fn):
                        delete_fn()
                except Exception:
                    pass

            if wipe is not None:
                try:
                    wipe.ConnectInput("Input", media_in)
                    media_out.ConnectInput("Input", wipe)
                    print(f"      🔗 {name}: rewired MediaIn1 → CustomWipe → MediaOut1")
                    result["strategy_a"] += 1
                except Exception as _ce:
                    print(f"      ⚠️ {name}: rewire failed: {_ce}")

        elif wipe is not None:
            print(f"      ♻️ {name}: reusing existing CustomWipe")
            try:
                wipe.ConnectInput("Input", media_in)
                media_out.ConnectInput("Input", wipe)
            except Exception:
                pass

        # ----------------------------------------------------------------
        # If Strategy A produced a wipe + displacement spline, rescale
        # the displacement keyframes to this clip's frame range and we're
        # done.
        # ----------------------------------------------------------------
        if wipe is not None and disp_spline is not None:
            keys = {
                f_start:     {1: 0.0},
                k_in_done:   {1: 0.5},
                k_out_start: {1: 0.5},
                f_end:       {1: 1.0},
            }
            if _set_keys(disp_spline, keys, f"{name} displacement"):
                print(f"      🎚️ {name}: keys "
                      f"0@{f_start}, 0.5@{k_in_done}, 0.5@{k_out_start}, 1@{f_end}")
                _evaluate_comp(comp, f_start, f_end, wipe)
                result["applied"] += 1
                continue

        # ----------------------------------------------------------------
        # Strategy B fallback: build a Transform manually and keyframe
        # Size 0→1→1→0 + Angle 0→0→0→90 so the user sees a clear
        # animated transition even if Paste produced nothing usable.
        # ----------------------------------------------------------------
        try:
            # Clean up any stale zoom-fallback spline from previous runs.
            stale_size = comp.FindTool("WipeSizeSpline")
            if stale_size is not None:
                try:
                    stale_size.Delete()
                    print(f"      🧹 {name}: removed stale WipeSizeSpline (zoom)")
                except Exception:
                    pass

            xf = comp.FindTool("WipeFallback")
            if xf is None:
                add_tool = getattr(comp, "AddTool", None)
                if not callable(add_tool):
                    result["errors"].append(f"{name}: AddTool not callable; cannot fall back")
                    result["failed"] += 1
                    continue
                xf = add_tool("Transform", -32768, -32768)
                if xf is None:
                    result["errors"].append(f"{name}: AddTool('Transform') returned None")
                    result["failed"] += 1
                    continue
                try:
                    xf.SetAttrs({"TOOLS_Name": "WipeFallback"})
                except Exception:
                    pass
                print(f"      ➕ {name}: added WipeFallback (Transform)")

            try:
                xf.ConnectInput("Input", media_in)
                media_out.ConnectInput("Input", xf)
                print(f"      🔗 {name}: MediaIn1 → WipeFallback → MediaOut1")
            except Exception as _ce:
                print(f"      ⚠️ {name}: fallback rewire failed: {_ce}")

            # Make sure Size is a static 1.0 (in case a prior zoom spline
            # was attached) and clear any prior Center keyframes.
            try:
                xf.SetInput("Size", 1.0)
            except Exception:
                pass
            try:
                xf.SetInput("Center", [0.5, 0.5])
            except Exception:
                pass

            # ----------------------------------------------------------
            # Slide animation. The Transform's `Center` is a Point input,
            # which the scripting API will not let us keyframe with the
            # 3-arg `SetInput(name, val, frame)` form on this Resolve
            # build. The reliable approach is to attach an XYPath
            # modifier to the Center input — that's the same modifier
            # Fusion creates when you right-click → "Modify With → XY
            # Path" in the GUI. XYPath exposes `X` and `Y` numeric
            # inputs that accept BezierSplines via the normal
            # `ConnectInput` API.
            #
            # Slide-IN with cubic ease-out (fast start → gentle stop at
            # center). Per-frame keyframes are written because Fusion's
            # BezierSpline interpolation between sparse keys may be linear
            # on this build; explicit per-frame values guarantee the curve.
            #
            #   1.5 (off-screen right) @ f_start  \
            #   ... ease-out curve ...             |  slide_frames
            #   0.5 (center)          @ k_in_done /
            #   0.5 (hold)            @ f_end
            # ----------------------------------------------------------
            _sr = max(k_in_done - f_start, 1)
            slide_keys_x = {}
            for _i in range(int(_sr) + 1):
                _t = _i / _sr
                # cubic ease-out: f(t) = 1 - (1-t)^3
                _ease = 1.0 - (1.0 - _t) ** 3
                slide_keys_x[f_start + _i] = {1: round(1.5 - _ease, 6)}
            slide_keys_x[f_end] = {1: 0.5}  # hold
            slide_keys_y = {
                f_start: {1: 0.5},
                f_end:   {1: 0.5},
            }

            # Clean up any prior bare BezierSpline / XYPath from earlier
            # attempts so re-runs start fresh and don't accumulate
            # orphan nodes.
            for stale_name in ("WipeCenterX", "WipeCenterY", "WipeCenterPath",
                                "XYPath1", "XYPath1X", "XYPath1Y",
                                "WipeBlend", "WipeMerge"):
                stale = comp.FindTool(stale_name)
                if stale is not None:
                    try:
                        stale.Delete()
                        print(f"      🧹 {name}: removed stale {stale_name}")
                    except Exception:
                        pass

            wrote_slide = False
            add_modifier = getattr(xf, "AddModifier", None)

            xy_path = None
            if callable(add_modifier):
                # Snapshot tools before so we can find the new modifier
                # afterwards — `AddModifier` returns a bool on this build,
                # not the new tool object.
                names_before = {n for (n, _r, _t) in _list_tools(comp)}
                try:
                    add_ret = xf.AddModifier("Center", "XYPath")
                    print(f"      ➕ {name}: AddModifier(Center, XYPath) → {add_ret!r}")
                except Exception as _me:
                    add_ret = None
                    print(f"      ⚠️ {name}: AddModifier failed: {_me}")

                if add_ret:
                    # Find any newly-added XYPath tool.
                    for (n2, r2, t2) in _list_tools(comp):
                        if n2 in names_before:
                            continue
                        if r2 == "XYPath":
                            xy_path = t2
                            try:
                                t2.SetAttrs({"TOOLS_Name": "WipeCenterPath"})
                            except Exception:
                                pass
                            print(f"      🔎 {name}: located new XYPath modifier "
                                  f"as '{n2}'")
                            break

            if xy_path is not None:
                # The modifier auto-creates X / Y BezierSplines and wires
                # them to its inputs. Find them by the auto-naming
                # convention (<modifier_name>X, <modifier_name>Y) so we
                # can write keyframes directly without re-attaching.
                xy_name = None
                try:
                    xy_name = xy_path.GetAttrs().get("TOOLS_Name") or "XYPath1"
                except Exception:
                    xy_name = "XYPath1"

                cx_spline = comp.FindTool(f"{xy_name}X") or comp.FindTool("XYPath1X")
                cy_spline = comp.FindTool(f"{xy_name}Y") or comp.FindTool("XYPath1Y")

                if cx_spline is not None and _set_keys(cx_spline, slide_keys_x, f"{name} Center.X"):
                    wrote_slide = True
                    print(f"      🎚️ {name}: Center.X ease-out "
                          f"1.5@{f_start} → 0.5@{k_in_done} (hold → {f_end})")
                else:
                    print(f"      ⚠️ {name}: could not find/key XYPath X spline")

                if cy_spline is not None and _set_keys(cy_spline, slide_keys_y, f"{name} Center.Y"):
                    print(f"      🎚️ {name}: Center.Y held at 0.5")

            if not wrote_slide:
                # Fallback to the legacy explicit-spline approach.
                print(f"      ↩ {name}: XYPath path failed; trying bare "
                      f"BezierSpline + ConnectInput('Center.X')")
                add_tool = getattr(comp, "AddTool", None)
                cx_spline = None
                if callable(add_tool):
                    cx_spline = add_tool("BezierSpline", -32768, -32768)
                    if cx_spline is not None:
                        try:
                            cx_spline.SetAttrs({"TOOLS_Name": "WipeCenterX"})
                        except Exception:
                            pass
                if cx_spline is not None:
                    connect_tries = [
                        ("ConnectInput Center.X", lambda: xf.ConnectInput("Center.X", cx_spline)),
                        ("ConnectInput CenterX",  lambda: xf.ConnectInput("CenterX",  cx_spline)),
                    ]
                    connected = False
                    for label, fn in connect_tries:
                        try:
                            r = fn()
                            print(f"      🔌 {name}: {label} → {r}")
                            if r:
                                connected = True
                                break
                        except Exception as _ce:
                            print(f"      … {label} threw: {_ce}")
                    if connected and _set_keys(cx_spline, slide_keys_x, f"{name} Center.X"):
                        wrote_slide = True

            if not wrote_slide:
                # Last resort: per-frame Point write (likely no-op on
                # this build, but worth logging).
                print(f"      ⚠️ {name}: no spline attach worked; trying per-frame Center")
                try:
                    for _f, _v in slide_keys_x.items():
                        xf.SetInput("Center", [float(_v[1]), 0.5], int(_f))
                    print(f"      🎚️ {name}: per-frame Center attempted (may be silent no-op)")
                except Exception as _ke:
                    print(f"      ⚠️ {name}: per-frame Center failed: {_ke}")

            # ----------------------------------------------------------
            # Opacity fade-out at the end. Hold Blend at 1.0 for the
            # whole clip, then ramp to 0 across the same window the
            # Diagnostic dump of the comp tools after the attempt.
            try:
                final_tools = _list_tools(comp)
                print(f"      🔎 {name}: tools after wipe = {final_tools}")
            except Exception:
                pass

            _evaluate_comp(comp, f_start, f_end, xf)
            result["strategy_b"] += 1
            result["applied"] += 1
        except Exception as e:
            result["errors"].append(f"{name}: fallback build failed: {e}")
            result["failed"] += 1

    total = result["applied"] + result["failed"]
    result["success"] = result["applied"] > 0 and result["failed"] == 0
    result["message"] = (
        f"Wipe applied to {result['applied']}/{total} V{track_index} clip(s) "
        f"(paste={result['strategy_a']}, fallback-zoom={result['strategy_b']})"
        + (f" — {result['failed']} failed" if result["failed"] else "")
    )

    # Page bounce + scrub to refresh the editor preview cache.
    try:
        import DaVinciResolveScript as dvr_script
        _resolve = dvr_script.scriptapp("Resolve")
        if _resolve is not None:
            _resolve.OpenPage("fusion")
            for _it in items:
                try:
                    _s = int(_it.GetStart())
                    _e = int(_it.GetEnd())
                    _mid = _s + max(1, (_e - _s) // 2)
                    total_secs = _mid / fps
                    hh = int(total_secs // 3600)
                    mm = int((total_secs % 3600) // 60)
                    ss = int(total_secs % 60)
                    ff = int(round((_mid % fps)))
                    tc = f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"
                    timeline.SetCurrentTimecode(tc)
                except Exception:
                    pass
            _resolve.OpenPage("edit")
            print(f"   🔄 page bounce edit→fusion(scrub {len(items)} clips)→edit")
    except Exception as _pe:
        print(f"   ⚠️ page bounce failed: {_pe}")

    return result


def _evaluate_comp(comp, f_start, f_end, focus_tool=None):
    """Force the comp to evaluate at start/mid/end so Resolve caches the
    rendered output and the editor preview reflects the new effect
    without manual scrubbing.

    Note: we intentionally do NOT call comp.Render() here — it pops a
    modal "Render Complete" dialog for every clip. SetCurrentTime alone
    is enough to dirty the preview cache; the page-bounce + scrub at the
    end of the wipe pipeline finishes the job silently.
    """
    try:
        set_ct = getattr(comp, "SetCurrentTime", None)
        if callable(set_ct):
            mid = (f_start + f_end) // 2
            for _f in (f_start, mid, f_end):
                set_ct(_f)
    except Exception:
        pass


def _apply_blur_to_v3_clips(timeline, track_index: int = 3,
                            max_blur: float = 20.0):
    """
    Smoke-test for programmatic Fusion automation. For every clip on the
    given video track:

        MediaIn1 → Blur1 → MediaOut1

    with Blur1.XBlurSize keyframed 0.0 (clip start) → max_blur (clip end),
    so the image starts crisp and gradually blurs while playing.

    No .setting file, no plugins, no Paste(). Just AddTool + ConnectInput
    + SetInput(value, frame). If this works reliably, more elaborate
    Fusion effects can follow the same pattern.
    """
    result = {"success": False, "message": "", "applied": 0, "failed": 0,
              "errors": []}
    try:
        items = timeline.GetItemListInTrack("video", track_index) or []
    except Exception as e:
        result["message"] = f"GetItemListInTrack(video, {track_index}) failed: {e}"
        return result
    if not items:
        result["success"] = True
        result["message"] = f"No clips on V{track_index}; nothing to blur."
        return result

    print(f"   🌫️ Applying Blur smoke-test to {len(items)} V{track_index} clip(s) (0 → {max_blur})")

    for item in items:
        try:
            name = item.GetName() or "<unnamed>"
        except Exception:
            name = "<unnamed>"

        # Get or create per-clip Fusion comp.
        comp = None
        try:
            cnt = item.GetFusionCompCount() or 0
            if cnt >= 1:
                comp = item.GetFusionCompByIndex(1)
            else:
                add_fn = getattr(item, "AddFusionComp", None)
                if callable(add_fn):
                    comp = add_fn()
        except Exception as e:
            result["errors"].append(f"{name}: get/add comp: {e}")
            result["failed"] += 1
            continue
        if comp is None:
            result["errors"].append(f"{name}: no comp returned")
            result["failed"] += 1
            continue

        # Frame range for keyframes. Per-clip Fusion comps use comp-local
        # frames (0..duration-1), NOT timeline-absolute frames. Pull the
        # range from the comp itself when available, fall back to the
        # clip's source duration otherwise.
        f_start, f_end = 0, 24
        try:
            cattrs = comp.GetAttrs() or {}
            gs = cattrs.get("COMPN_GlobalStart")
            ge = cattrs.get("COMPN_GlobalEnd")
            if gs is not None and ge is not None and ge > gs:
                f_start = int(gs)
                f_end = int(ge) - 1
            else:
                raise ValueError("no comp range")
        except Exception:
            try:
                dur = int(item.GetEnd()) - int(item.GetStart())
                f_start = 0
                f_end = max(1, dur - 1)
            except Exception:
                pass
        if f_end <= f_start:
            f_end = f_start + 1

        lock = getattr(comp, "Lock", None)
        unlock = getattr(comp, "Unlock", None)
        try:
            if callable(lock):
                lock()

            media_in = comp.FindTool("MediaIn1")
            media_out = comp.FindTool("MediaOut1")
            if media_in is None or media_out is None:
                result["errors"].append(
                    f"{name}: comp missing MediaIn1={media_in is not None} "
                    f"MediaOut1={media_out is not None}"
                )
                result["failed"] += 1
                continue

            # Avoid stacking duplicate Blur tools on re-runs.
            blur = comp.FindTool("Blur1")
            if blur is None:
                add_tool = getattr(comp, "AddTool", None)
                if not callable(add_tool):
                    result["errors"].append(f"{name}: AddTool not callable")
                    result["failed"] += 1
                    continue
                blur = add_tool("Blur", -32768, -32768)
                if blur is None:
                    result["errors"].append(f"{name}: AddTool('Blur') returned None")
                    result["failed"] += 1
                    continue
                print(f"      ➕ {name}: added Blur1")
            else:
                print(f"      ♻️ {name}: reusing existing Blur1")

            # Wire MediaIn1 → Blur1 → MediaOut1.
            try:
                blur.ConnectInput("Input", media_in)
            except Exception as e:
                result["errors"].append(f"{name}: Blur1.Input ← MediaIn1: {e}")
            try:
                media_out.ConnectInput("Input", blur)
            except Exception as e:
                result["errors"].append(f"{name}: MediaOut1.Input ← Blur1: {e}")

            # Keyframe XBlurSize 0.0 → max_blur over clip duration.
            # Resolve's external scripting bridge will NOT auto-create a
            # BezierSpline modifier when you call SetInput(value, frame)
            # on a previously-static input. We have to add the spline
            # explicitly and connect it to the input, then write keyframes
            # onto the spline itself.
            try:
                add_tool = getattr(comp, "AddTool", None)
                spline_name = "BlurSpline1"
                spline = comp.FindTool(spline_name)
                if spline is None and callable(add_tool):
                    spline = add_tool("BezierSpline", -32768, -32768)
                    if spline is not None:
                        try:
                            spline.SetAttrs({"TOOLS_Name": spline_name})
                        except Exception:
                            pass
                        print(f"      ➕ {name}: added {spline_name}")

                if spline is not None:
                    # Connect the spline as the source of XBlurSize. After
                    # this, blur.XBlurSize is animated by the spline.
                    try:
                        blur.ConnectInput("XBlurSize", spline)
                        print(f"      🔗 {name}: Blur1.XBlurSize ← {spline_name}")
                    except Exception as _ce:
                        print(f"      ⚠️ {name}: ConnectInput XBlurSize failed: {_ce}")

                    # Write keyframes onto the spline. The spline's value
                    # is exposed as `Value` and indexed by frame.
                    try:
                        spline.SetKeyFrames({
                            f_start: {1: 0.0},
                            f_end: {1: float(max_blur)},
                        })
                        print(f"      🌅 {name}: spline keys 0.0@{f_start} → {max_blur}@{f_end}")
                    except Exception as _ke:
                        # Fallback: write via Value subscript syntax
                        try:
                            spline["Value"][f_start] = 0.0
                            spline["Value"][f_end] = float(max_blur)
                            print(f"      🌅 {name}: spline subscript keys 0.0@{f_start} → {max_blur}@{f_end}")
                        except Exception as _ke2:
                            print(f"      ⚠️ {name}: spline keyframe write failed: {_ke} / {_ke2}")
                else:
                    # Last-resort: still set a static value so the blur is at
                    # least visible at the midpoint.
                    blur.SetInput("XBlurSize", float(max_blur) / 2.0)
                    print(f"      ⚠️ {name}: no spline; static XBlurSize={max_blur/2.0}")

                # Lock Y to X so a single spline drives both axes.
                try:
                    blur.SetInput("LockXY", 1.0)
                except Exception:
                    pass

                # Force the comp to evaluate at start, mid, and end so
                # Resolve caches the rendered output. Without this the
                # editor's source viewer still shows the un-blurred frame
                # until the user manually scrubs in the Fusion page.
                try:
                    set_ct = getattr(comp, "SetCurrentTime", None)
                    if callable(set_ct):
                        mid = (f_start + f_end) // 2
                        for _f in (f_start, mid, f_end):
                            set_ct(_f)
                except Exception as _se:
                    print(f"      ⚠️ {name}: SetCurrentTime evaluate failed: {_se}")
                # Also try comp.Render() which forces a full evaluation.
                try:
                    render_fn = getattr(comp, "Render", None)
                    if callable(render_fn):
                        render_fn({"Tool": blur, "Quality": 1})
                except Exception:
                    pass

                result["applied"] += 1
            except Exception as e:
                result["errors"].append(f"{name}: keyframe block: {e}")
                result["failed"] += 1
        except Exception as e:
            result["errors"].append(f"{name}: outer: {e}")
            result["failed"] += 1
        finally:
            try:
                if callable(unlock):
                    unlock()
            except Exception:
                pass

    total = result["applied"] + result["failed"]
    result["success"] = result["applied"] > 0 and result["failed"] == 0
    result["message"] = (
        f"Blur applied to {result['applied']}/{total} V{track_index} clip(s)"
        + (f" — {result['failed']} failed" if result["failed"] else "")
    )

    # Force the timeline to re-cache the V3 thumbnails. Without this,
    # the editor still shows the un-blurred frame until the user opens
    # the Fusion page and scrubs once. Recipe:
    #   1. Switch to Fusion page (loads each comp into the engine)
    #   2. Seek the playhead through each V3 clip's mid-point
    #   3. Switch back to Edit page
    try:
        import DaVinciResolveScript as dvr_script
        _resolve = dvr_script.scriptapp("Resolve")
        if _resolve is not None:
            _resolve.OpenPage("fusion")
            try:
                fps = float(timeline.GetSetting("timelineFrameRate") or 24)
            except Exception:
                fps = 24.0
            for _it in items:
                try:
                    _s = int(_it.GetStart())
                    _e = int(_it.GetEnd())
                    _mid = _s + max(1, (_e - _s) // 2)
                    total_secs = _mid / fps
                    hh = int(total_secs // 3600)
                    mm = int((total_secs % 3600) // 60)
                    ss = int(total_secs % 60)
                    ff = int(round((_mid % fps)))
                    tc = f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"
                    timeline.SetCurrentTimecode(tc)
                except Exception:
                    pass
            _resolve.OpenPage("edit")
            print(f"   🔄 page bounce edit→fusion(scrub {len(items)} clips)→edit")
    except Exception as _pe:
        print(f"   ⚠️ page bounce failed: {_pe}")

    return result


def _apply_slide_wipe_to_v3_clips(timeline, track_index: int = 3,
                                  wipe_seconds: float = 1.0):
    """
    Apply a programmatic right-to-left slide-off wipe to every clip on the
    given video track (default V3 = broll). Uses ONLY built-in Fusion tools
    (no plugin, no macro, no .setting file):

        MediaIn1 → Transform1 (Center.X 0.5→-0.6 over last `wipe_seconds`)
                 → AlphaMultiply1 (Multiplier 1.0→0.0 over same range)
                 → MediaOut1

    The Transform slides the broll off the left edge while the AlphaMultiply
    cleanly reveals V1 underneath. Per-clip path uses the proven Strategy D
    sequence: seek playhead to mid-clip on Edit page, open Fusion page,
    grab fusion.GetCurrentComp(), edit it.
    """
    result = {"success": False, "applied": 0, "skipped": 0, "failed": 0,
              "errors": [], "message": "", "track": track_index}
    try:
        items = timeline.GetItemListInTrack("video", track_index) or []
    except Exception as e:
        result["message"] = f"GetItemListInTrack(video, {track_index}) failed: {e}"
        return result
    if not items:
        result["success"] = True
        result["message"] = f"No clips on V{track_index}; nothing to apply."
        return result

    try:
        import DaVinciResolveScript as dvr_script
        resolve_handle = dvr_script.scriptapp("Resolve")
        fusion_app = dvr_script.scriptapp("Fusion")
    except Exception as e:
        result["message"] = f"Could not get Resolve/Fusion handles: {e}"
        return result

    try:
        fps = float(timeline.GetSetting("timelineFrameRate") or 24)
    except Exception:
        fps = 24.0
    wipe_frames = max(1, int(round(wipe_seconds * fps)))

    print(f"   🌊 Applying {wipe_seconds}s right-to-left slide wipe to "
          f"{len(items)} V{track_index} clip(s) ({wipe_frames}f @ {fps}fps)")

    import time as _time
    for item in items:
        try:
            name = item.GetName() or ""
        except Exception:
            name = ""

        # --- Strategy D: seek to mid-clip, open Fusion page, get live comp.
        try:
            clip_start = int(item.GetStart())
            clip_end = int(item.GetEnd())
        except Exception as e:
            result["failed"] += 1
            result["errors"].append(f"{name}: GetStart/End failed: {e}")
            continue

        target_frame = clip_start + max(1, (clip_end - clip_start) // 2)
        total_secs = target_frame / fps
        tc = (f"{int(total_secs // 3600):02d}:"
              f"{int((total_secs % 3600) // 60):02d}:"
              f"{int(total_secs % 60):02d}:"
              f"{int(round(target_frame % fps)):02d}")

        try:
            resolve_handle.OpenPage("edit")
            _time.sleep(0.15)
            timeline.SetCurrentTimecode(tc)
        except Exception as _se:
            print(f"      ⚠️ {name}: seek to {tc} failed: {_se}")

        try:
            resolve_handle.OpenPage("fusion")
            _time.sleep(0.35)
        except Exception:
            pass

        live_comp = None
        try:
            gcc = getattr(fusion_app, "GetCurrentComp", None)
            if callable(gcc):
                live_comp = gcc()
        except Exception as _ce:
            print(f"      ⚠️ {name}: GetCurrentComp failed: {_ce}")

        if live_comp is None:
            result["failed"] += 1
            result["errors"].append(f"{name}: no live comp")
            print(f"      ⚠️ {name}: no live comp")
            continue

        # --- Build the wipe rig.
        try:
            media_in = live_comp.FindTool("MediaIn1")
            media_out = live_comp.FindTool("MediaOut1")
        except Exception as e:
            result["failed"] += 1
            result["errors"].append(f"{name}: FindTool failed: {e}")
            continue
        if not media_in or not media_out:
            result["failed"] += 1
            result["errors"].append(f"{name}: missing MediaIn1/MediaOut1")
            print(f"      ⚠️ {name}: missing MediaIn1/MediaOut1 in live comp")
            continue

        # Wipe window: last `wipe_frames` of the comp's render range.
        # IMPORTANT: keyframes MUST be set in the comp's local time domain.
        # COMPN_GlobalStart/End and item.GetStart()/End() can return timeline-
        # absolute frames (e.g. 86400+) depending on Resolve build, which puts
        # keyframes outside the visible playback window and the wipe never
        # animates. We always normalize to local comp time below.
        g_start = g_end = None
        try:
            cattrs = live_comp.GetAttrs() or {}
            g_start = cattrs.get("COMPN_GlobalStart")
            g_end = cattrs.get("COMPN_GlobalEnd")
        except Exception:
            pass
        clip_dur = max(1, int(clip_end) - int(clip_start))
        if g_start is None or g_end is None:
            local_start, local_end = 0, clip_dur
        else:
            # Local range is always 0 .. (g_end - g_start), regardless of
            # whether the comp reports global or local-absolute frames.
            local_end = max(1, int(g_end) - int(g_start))
            local_start = 0
        wipe_start_f = max(local_start, local_end - wipe_frames)
        wipe_end_f = local_end - 1
        if wipe_end_f <= wipe_start_f:
            wipe_end_f = wipe_start_f + 1

        try:
            live_comp.Lock()
        except Exception:
            pass

        transform_node = None
        fade_node = None
        try:
            # Build the wipe rig as a Fusion .setting text and Paste it. This
            # is the only mechanism that actually creates BezierSpline / XYPath
            # modifiers with multiple keyframes in this Resolve build —
            # AddTool("BezierSpline") + SetInput(value, time) and
            # `tool.Input = BezierSpline{KeyFrames=...}` in Lua both silently
            # produce empty splines (verified via .setting export).
            #
            # We give every operator a Wipe_-prefixed name so it can't collide
            # with anything Resolve auto-creates, then look them up by name.
            wipe_text = (
                "{\n"
                "  Tools = ordered() {\n"
                "    Wipe_Transform = Transform {\n"
                "      Inputs = {\n"
                "        Center = Input {\n"
                "          SourceOp = \"Wipe_XY\",\n"
                "          Source = \"Value\",\n"
                "        },\n"
                "      },\n"
                "      ViewInfo = OperatorInfo { Pos = { 165, 49.5 } },\n"
                "    },\n"
                "    Wipe_XY = XYPath {\n"
                "      DrawMode = \"ModifyOnly\",\n"
                "      Inputs = {\n"
                "        X = Input { SourceOp = \"Wipe_XSpline\", Source = \"Value\", },\n"
                "        Y = Input { SourceOp = \"Wipe_YSpline\", Source = \"Value\", },\n"
                "      },\n"
                "    },\n"
                "    Wipe_XSpline = BezierSpline {\n"
                "      SplineColor = { Red = 255, Green = 0, Blue = 0 },\n"
                "      NameSet = true,\n"
                "      KeyFrames = {\n"
                f"        [{wipe_start_f}] = {{ 0.5, Flags = {{ Linear = true }} }},\n"
                f"        [{wipe_end_f}]   = {{ -0.6, Flags = {{ Linear = true }} }},\n"
                "      },\n"
                "    },\n"
                "    Wipe_YSpline = BezierSpline {\n"
                "      SplineColor = { Red = 0, Green = 255, Blue = 0 },\n"
                "      NameSet = true,\n"
                "      KeyFrames = {\n"
                f"        [{wipe_start_f}] = {{ 0.5, Flags = {{ Linear = true }} }},\n"
                f"        [{wipe_end_f}]   = {{ 0.5, Flags = {{ Linear = true }} }},\n"
                "      },\n"
                "    },\n"
                "    Wipe_Alpha = AlphaMultiply {\n"
                "      Inputs = {\n"
                "        Multiplier = Input {\n"
                "          SourceOp = \"Wipe_ASpline\",\n"
                "          Source = \"Value\",\n"
                "        },\n"
                "        Input = Input {\n"
                "          SourceOp = \"Wipe_Transform\",\n"
                "          Source = \"Output\",\n"
                "        },\n"
                "      },\n"
                "      ViewInfo = OperatorInfo { Pos = { 275, 49.5 } },\n"
                "    },\n"
                "    Wipe_ASpline = BezierSpline {\n"
                "      SplineColor = { Red = 0, Green = 0, Blue = 255 },\n"
                "      NameSet = true,\n"
                "      KeyFrames = {\n"
                f"        [{wipe_start_f}] = {{ 1.0, Flags = {{ Linear = true }} }},\n"
                f"        [{wipe_end_f}]   = {{ 0.0, Flags = {{ Linear = true }} }},\n"
                "      },\n"
                "    },\n"
                "  },\n"
                "  ActiveTool = \"Wipe_Alpha\",\n"
                "}\n"
            )

            # Parse the text via dvr_script.readfile (writes a temp file first).
            paste_table = None
            paste_table_err = None
            try:
                import tempfile, os as _os
                tmp_dir = tempfile.gettempdir()
                tmp_path = _os.path.join(
                    tmp_dir, f"linedrive_wipe_{abs(hash(name)) & 0xffffffff:x}.setting"
                )
                with open(tmp_path, "w", encoding="utf-8") as _fw:
                    _fw.write(wipe_text)
                rf = getattr(dvr_script, "readfile", None)
                if callable(rf):
                    paste_table = rf(tmp_path)
                else:
                    rf2 = getattr(fusion_app, "readfile", None)
                    if callable(rf2):
                        paste_table = rf2(tmp_path)
            except Exception as _re:
                paste_table_err = str(_re)

            paste_status = "skipped"
            try:
                live_comp.Lock()
            except Exception:
                pass
            try:
                paste_fn = getattr(live_comp, "Paste", None)
                if callable(paste_fn):
                    if paste_table:
                        ret = paste_fn(paste_table)
                        paste_status = f"table:{ret!r}"
                    else:
                        # Fall back to string paste if readfile unavailable.
                        ret = paste_fn(wipe_text)
                        paste_status = f"text:{ret!r} (readfile_err={paste_table_err})"
                else:
                    paste_status = "no_paste_fn"
            except Exception as _pe:
                paste_status = f"paste_err:{_pe}"
            finally:
                try:
                    live_comp.Unlock()
                except Exception:
                    pass

            # Look up the pasted tools (Resolve may suffix _1 / _2 if the
            # comp was previously processed).
            def _find_first(tool_basename):
                # Try base, then _1.._5
                for cand in (tool_basename, *(f"{tool_basename}_{i}" for i in range(1, 6))):
                    try:
                        t = live_comp.FindTool(cand)
                        if t:
                            return t, cand
                    except Exception:
                        pass
                return None, None

            transform_node, t_used = _find_first("Wipe_Transform")
            fade_node, a_used = _find_first("Wipe_Alpha")

            # Wire MediaIn1 → Wipe_Transform → Wipe_Alpha → MediaOut1.
            connect_status = []
            if transform_node and media_in:
                try:
                    transform_node.ConnectInput("Input", media_in)
                    connect_status.append("In→T")
                except Exception as _e:
                    connect_status.append(f"In→T_err:{_e}")
            if fade_node and transform_node:
                # Wipe_Alpha already has Input wired to Wipe_Transform via
                # the pasted text, but re-assert in case the SourceOp lookup
                # was deferred until after both ops existed.
                try:
                    fade_node.ConnectInput("Input", transform_node)
                    connect_status.append("T→A")
                except Exception as _e:
                    connect_status.append(f"T→A_err:{_e}")
            if media_out and fade_node:
                try:
                    media_out.ConnectInput("Input", fade_node)
                    connect_status.append("A→Out")
                except Exception as _e:
                    connect_status.append(f"A→Out_err:{_e}")

            print(f"      🌊 {name}: wipe local frames {wipe_start_f}..{wipe_end_f} "
                  f"(g_start={g_start}, g_end={g_end}, dur={clip_dur}) "
                  f"paste={paste_status} t={t_used!r} a={a_used!r} "
                  f"wires={'/'.join(connect_status) or 'none'}")
            if transform_node and fade_node:
                result["applied"] += 1
            else:
                result["failed"] += 1
                result["errors"].append(
                    f"{name}: paste did not produce Wipe_Transform/Wipe_Alpha "
                    f"(paste={paste_status})"
                )
        except Exception as e:
            result["failed"] += 1
            result["errors"].append(f"{name}: build wipe failed: {e}")
            print(f"      ⚠️ {name}: build wipe failed: {e}")
        finally:
            try:
                live_comp.Unlock()
            except Exception:
                pass

    result["success"] = result["applied"] > 0
    result["message"] = (f"Slide-wipe applied to {result['applied']}/{len(items)} "
                         f"V{track_index} clip(s)"
                         + (f" — {result['failed']} failed" if result['failed'] else ""))
    return result


def _apply_fusion_preset_to_v3_clips(timeline, preset_path: str, track_index: int = 3):
    """
    Load a saved Fusion comp preset onto every clip on the given video track
    (default V3 = broll). Uses Composition.LoadSettings(path) so the entire
    saved comp (MediaIn → effect → MediaOut wiring) is applied in one shot.

    Each clip already has an implicit Fusion comp at index 1 (MediaIn1 →
    MediaOut1); LoadSettings replaces it with the saved one. The new
    composition's MediaIn1 reconnects to the host clip's media.

    Returns: {success, applied, skipped, failed, message}
    """
    result = {"success": False, "applied": 0, "skipped": 0, "failed": 0, "errors": [],
              "message": "", "track": track_index}
    try:
        items = timeline.GetItemListInTrack("video", track_index) or []
    except Exception as e:
        result["message"] = f"GetItemListInTrack(video, {track_index}) failed: {e}"
        return result

    if not items:
        result["success"] = True  # nothing to do is not a failure
        result["message"] = f"No clips on V{track_index}; nothing to apply."
        return result

    if not os.path.exists(preset_path):
        result["message"] = f"Preset file not found: {preset_path}"
        return result

    # Pre-read the preset text once for the Paste-into-comp fallback path.
    preset_text = ""
    try:
        with open(preset_path, "r", encoding="utf-8", errors="replace") as _pf:
            preset_text = _pf.read()
    except Exception as e:
        result["message"] = f"Could not read preset file: {e}"
        return result

    # Parse the .setting file into a Fusion settings table via the scripting
    # module's readfile() — this is what comp.Paste() actually expects (a
    # table, not a string). Without this, comp.Paste(text) silently returns
    # False on every clip.
    preset_table = None
    try:
        import DaVinciResolveScript as dvr_script
        readfile = getattr(dvr_script, "readfile", None)
        if callable(readfile):
            preset_table = readfile(preset_path)
            print(f"   📖 Parsed preset via dvr_script.readfile → type={type(preset_table).__name__} truthy={bool(preset_table)}")
        else:
            # Try via the Fusion app object
            try:
                fusion_app = dvr_script.scriptapp("Fusion")
                rf2 = getattr(fusion_app, "readfile", None) if fusion_app else None
                if callable(rf2):
                    preset_table = rf2(preset_path)
                    print(f"   📖 Parsed preset via fusion.readfile → type={type(preset_table).__name__} truthy={bool(preset_table)}")
                else:
                    print("   ⚠️ Neither dvr_script.readfile nor fusion.readfile available")
            except Exception as _e:
                print(f"   ⚠️ Fusion readfile path failed: {_e}")
    except Exception as e:
        print(f"   ⚠️ Could not parse preset into settings table: {e}")

    # Get Resolve + Fusion app handles. We deliberately do NOT switch to the
    # Fusion page here — Strategy D below alternates Edit (to seek playhead)
    # and Fusion (to load the per-clip comp into fusion.GetCurrentComp()).
    resolve_handle = None
    fusion_app = None
    try:
        import DaVinciResolveScript as dvr_script
        resolve_handle = dvr_script.scriptapp("Resolve")
        fusion_app = dvr_script.scriptapp("Fusion")
        print(f"   🪟 Fusion app handle: {fusion_app!r}")
    except Exception as _e:
        print(f"   ⚠️ Could not get Resolve/Fusion handles: {_e}")

    print(f"   🎨 Applying mTuber preset to {len(items)} V{track_index} clip(s) → {preset_path}")

    # Resolve's ImportFusionCompFromFile sometimes only accepts files with
    # .comp / .setting extensions in particular folders. Make a sibling .comp
    # copy of the preset to widen compatibility, since some builds dispatch
    # on file extension.
    preset_comp_copy = None
    try:
        if preset_path.lower().endswith(".setting"):
            comp_alt = preset_path[:-len(".setting")] + ".comp"
            # Always refresh from current .setting so the alias never goes
            # stale (a previous run may have written a different macro).
            import shutil as _shutil
            _shutil.copyfile(preset_path, comp_alt)
            preset_comp_copy = comp_alt
    except Exception as _e:
        print(f"   ⚠️ Could not create .comp alias for preset: {_e}")

    # One-time deep diagnostic on the first clip so we can see what Resolve
    # actually exposes (its __getattr__ is permissive: hasattr is unreliable).
    if items:
        first = items[0]
        try:
            fname = first.GetName() or ""
        except Exception:
            fname = "<no name>"
        print(f"   🔬 Diagnostic on first clip: {fname}")
        for meth in ("ImportFusionCompFromFile", "LoadFusionCompByName",
                     "GetFusionCompByIndex", "GetFusionCompCount",
                     "AddFusionComp", "DeleteFusionCompByName",
                     "GetFusionCompNameList", "RenameFusionCompByName"):
            obj = getattr(first, meth, None)
            print(f"      • {meth}: present={obj is not None} callable={callable(obj)}")
        try:
            print(f"      • current FusionCompCount = {first.GetFusionCompCount()}")
        except Exception as _e:
            print(f"      • GetFusionCompCount raised: {_e}")
        try:
            names = first.GetFusionCompNameList()
            print(f"      • current FusionCompNameList = {names}")
        except Exception as _e:
            print(f"      • GetFusionCompNameList raised: {_e}")

    for item in items:
        name = ""
        try:
            name = item.GetName() or ""
        except Exception:
            pass

        applied_via = None
        last_err = None

        # Strategy A: item.ImportFusionCompFromFile(path) — the canonical
        # clip-level API for loading a saved comp. Try both .setting and .comp.
        for try_path in (preset_path, preset_comp_copy):
            if not try_path or applied_via:
                continue
            # Call unconditionally; Resolve's permissive __getattr__ can
            # report `callable=True` from a diagnostic but still raise on
            # invocation. Capture the real outcome with full diagnostics.
            try:
                ret = item.ImportFusionCompFromFile(try_path)
                print(f"      🔎 {name}: ImportFusionCompFromFile({os.path.basename(try_path)}) → {ret!r}")
                if ret:
                    applied_via = f"ImportFusionCompFromFile({os.path.basename(try_path)}) → {ret!r}"
                    # Try to activate the just-imported comp if we got a name.
                    try:
                        if isinstance(ret, str):
                            load_named = getattr(item, "LoadFusionCompByName", None)
                            if callable(load_named):
                                load_ret = load_named(ret)
                                print(f"      🔎 {name}: LoadFusionCompByName({ret!r}) → {load_ret!r}")
                    except Exception as _le:
                        print(f"      ⚠️ {name}: LoadFusionCompByName raised: {_le}")
            except Exception as e:
                last_err = (last_err + " | " if last_err else "") + f"ImportFusionCompFromFile({os.path.basename(try_path) if try_path else '?'}): {type(e).__name__}: {e}"
                print(f"      ⚠️ {name}: ImportFusionCompFromFile raised: {type(e).__name__}: {e}")

        # Strategy D: DISABLED.
        # Seeking the playhead and grabbing fusion.GetCurrentComp() landed
        # on whichever clip Resolve happened to expose (often a V2 aroll or
        # a transition stub), then _clear_comp_tools() destroyed it. The
        # per-clip comp from item.GetFusionCompByIndex(1) (Strategy B) is
        # the only safe target.
        if False and not applied_via and fusion_app and preset_table is not None and resolve_handle is not None:
            try:
                import time as _time
                clip_start = int(item.GetStart())
                clip_end = int(item.GetEnd())
                try:
                    fps = float(timeline.GetSetting("timelineFrameRate") or 24)
                except Exception:
                    fps = 24.0
                # Middle of the clip avoids any transition zones at the edges.
                target_frame = clip_start + max(1, (clip_end - clip_start) // 2)
                total_secs = target_frame / fps
                hh = int(total_secs // 3600)
                mm = int((total_secs % 3600) // 60)
                ss = int(total_secs % 60)
                ff = int(round((target_frame % fps)))
                tc = f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"

                # Switch to Edit page so SetCurrentTimecode is honored.
                try:
                    resolve_handle.OpenPage("edit")
                    _time.sleep(0.15)
                except Exception:
                    pass
                try:
                    seek_ret = timeline.SetCurrentTimecode(tc)
                    print(f"      🎯 {name}: SetCurrentTimecode({tc}) → {seek_ret!r} (start={clip_start}, fps={fps})")
                except Exception as _se:
                    print(f"      ⚠️ {name}: SetCurrentTimecode failed: {_se}")

                # Now open Fusion page — this loads the clip-under-playhead's
                # comp as the live Fusion comp.
                try:
                    resolve_handle.OpenPage("fusion")
                    _time.sleep(0.35)
                except Exception:
                    pass

                live_comp = None
                try:
                    gcc = getattr(fusion_app, "GetCurrentComp", None)
                    if callable(gcc):
                        live_comp = gcc()
                    if live_comp is None:
                        live_comp = getattr(fusion_app, "CurrentComp", None)
                except Exception as _ce:
                    print(f"      ⚠️ {name}: GetCurrentComp failed: {_ce}")

                # Identify the live comp so we can confirm it differs per clip.
                comp_id = None
                try:
                    attrs = live_comp.GetAttrs() if live_comp else None
                    if isinstance(attrs, dict):
                        comp_id = attrs.get("COMPS_Name") or attrs.get("COMPS_FileName")
                except Exception:
                    pass
                print(f"      🔎 {name}: live_comp={live_comp!r} id={comp_id!r}")

                if live_comp is not None:
                    paste_fn = getattr(live_comp, "Paste", None)
                    lock_fn = getattr(live_comp, "Lock", None)
                    unlock_fn = getattr(live_comp, "Unlock", None)
                    # Tool count before/after to verify nodes were added.
                    pre_count = None
                    try:
                        gtl = getattr(live_comp, "GetToolList", None)
                        if callable(gtl):
                            pre_count = len(gtl(False) or {})
                    except Exception:
                        pass
                    if callable(paste_fn):
                        try:
                            if callable(lock_fn):
                                lock_fn()
                            # Clear existing tools so pasted MediaIn1/MediaOut1
                            # don't collide and get renamed.
                            _clear_comp_tools(live_comp, name)
                            try:
                                gtl = getattr(live_comp, "GetToolList", None)
                                pre_count = len(gtl(False) or {}) if callable(gtl) else 0
                            except Exception:
                                pre_count = 0
                            ret = paste_fn(preset_table)
                            post_count = None
                            try:
                                gtl = getattr(live_comp, "GetToolList", None)
                                if callable(gtl):
                                    post_count = len(gtl(False) or {})
                            except Exception:
                                pass
                            print(f"      🔎 {name}: live_comp.Paste(table) → {ret!r} tools {pre_count}→{post_count}")
                            # Fallback: if dict-paste added no tools, retry
                            # with the raw .setting text (string).
                            if (post_count is None or pre_count is None or post_count <= pre_count) and preset_text:
                                try:
                                    ret2 = paste_fn(preset_text)
                                    post_count2 = None
                                    try:
                                        gtl = getattr(live_comp, "GetToolList", None)
                                        if callable(gtl):
                                            post_count2 = len(gtl(False) or {})
                                    except Exception:
                                        pass
                                    print(f"      🔎 {name}: live_comp.Paste(text) → {ret2!r} tools {pre_count}→{post_count2}")
                                    if post_count2 is not None and pre_count is not None and post_count2 > pre_count:
                                        ret = ret2
                                        post_count = post_count2
                                except Exception as _pe2:
                                    print(f"      ⚠️ {name}: Paste(text) raised: {_pe2}")
                            if callable(unlock_fn):
                                unlock_fn()
                            if ret and post_count and pre_count and post_count > pre_count:
                                # Verify the macro actually landed in THIS comp.
                                # If not, live_comp is the wrong comp (a title/
                                # transition stacked on top of our V3 broll), so
                                # invalidate the success and let Strategy B run
                                # against item.GetFusionCompByIndex(1) instead.
                                wired = _rewire_tiles_swap_with_fade(live_comp, item, timeline, name)
                                if wired:
                                    applied_via = "live fusion.CurrentComp.Paste"
                                else:
                                    print(f"      ↪️  {name}: live comp lacks Tiles_Swap macro — falling through to per-clip comp (Strategy B)")
                        except Exception as _pe:
                            last_err = (last_err + " | " if last_err else "") + f"live Paste: {_pe}"
            except Exception as e:
                last_err = (last_err + " | " if last_err else "") + f"strategy D: {e}"

        # Strategy B: Get/create comp, then comp.Paste(text) — requires the
        # raw .setting text. Drops onto the existing MediaIn1/MediaOut1.
        if not applied_via:
            try:
                comp = None
                count = 0
                try:
                    count = item.GetFusionCompCount() or 0
                except Exception:
                    pass
                try:
                    if count >= 1:
                        comp = item.GetFusionCompByIndex(1)
                    else:
                        add_fn = getattr(item, "AddFusionComp", None)
                        if callable(add_fn):
                            comp = add_fn()
                except Exception as e:
                    last_err = (last_err + " | " if last_err else "") + f"get/add comp: {e}"

                print(f"      🔎 {name}: comp obj={comp!r} count={count}")
                if comp is not None:
                    paste_fn = getattr(comp, "Paste", None)
                    lock_fn = getattr(comp, "Lock", None)
                    unlock_fn = getattr(comp, "Unlock", None)
                    print(f"      🔎 {name}: Paste={callable(paste_fn)} Lock={callable(lock_fn)} Unlock={callable(unlock_fn)} table_truthy={bool(preset_table)}")

                    # Strategy B1: Lock comp + Paste the parsed settings TABLE.
                    # Lock() is required for structural edits to remote comps.
                    if callable(paste_fn) and preset_table:
                        try:
                            if callable(lock_fn):
                                lock_ret = lock_fn()
                                print(f"      🔎 {name}: comp.Lock() → {lock_ret!r}")
                            ret = paste_fn(preset_table)
                            print(f"      🔎 {name}: comp.Paste(table) → {ret!r}")
                            if ret:
                                # Rewire macro and inject 1s fade-out while
                                # the comp is still locked for structural edits.
                                _rewire_tiles_swap_with_fade(comp, item, timeline, name)
                                applied_via = "comp.Lock+Paste(table)+Unlock"
                            if callable(unlock_fn):
                                unlock_ret = unlock_fn()
                                print(f"      🔎 {name}: comp.Unlock() → {unlock_ret!r}")
                        except Exception as e:
                            last_err = (last_err + " | " if last_err else "") + f"Lock/Paste(table): {e}"
                            try:
                                if callable(unlock_fn):
                                    unlock_fn()
                            except Exception:
                                pass

                    # Strategy B2: legacy text-paste fallback (almost always
                    # fails on modern Resolve, kept for completeness).
                    if not applied_via and callable(paste_fn) and preset_text:
                        try:
                            if callable(lock_fn):
                                lock_fn()
                            ret = paste_fn(preset_text)
                            print(f"      🔎 {name}: comp.Paste(text) → {ret!r}")
                            if ret:
                                _rewire_tiles_swap_with_fade(comp, item, timeline, name)
                                applied_via = "comp.Paste(text)"
                            if callable(unlock_fn):
                                unlock_fn()
                        except Exception as e:
                            last_err = (last_err + " | " if last_err else "") + f"Paste(text): {e}"
                            try:
                                if callable(unlock_fn):
                                    unlock_fn()
                            except Exception:
                                pass

                    # Strategy C: comp.LoadSettings(path) — last resort; many
                    # Resolve builds expose this on Fusion Studio root only,
                    # not on per-clip comps, but try anyway.
                    if not applied_via:
                        load_fn = getattr(comp, "LoadSettings", None)
                        print(f"      🔎 {name}: comp.LoadSettings callable={callable(load_fn)}")
                        if callable(load_fn):
                            try:
                                ret = load_fn(preset_path)
                                print(f"      🔎 {name}: comp.LoadSettings(path) → {ret!r}")
                                if ret:
                                    applied_via = "comp.LoadSettings(path)"
                            except Exception as e:
                                last_err = (last_err + " | " if last_err else "") + f"LoadSettings: {e}"
            except Exception as e:
                last_err = (last_err + " | " if last_err else "") + f"strategy B/C: {e}"

        if applied_via:
            result["applied"] += 1
            print(f"      ✅ {name} ({applied_via})")
        else:
            result["failed"] += 1
            err_msg = last_err or "no method succeeded"
            result["errors"].append(f"{name}: {err_msg}")
            print(f"      ⚠️ {name} — {err_msg}")

    result["success"] = result["applied"] > 0 and result["failed"] == 0
    result["message"] = (f"mTuber preset applied to {result['applied']}/{len(items)} V{track_index} clip(s)"
                         + (f" — {result['failed']} failed" if result['failed'] else ""))
    return result


def _add_broll_clips_above_aroll(media_pool, timeline, broll_bin):
    """
    Append all clips from the broll bin onto video track V3 (above the
    aRoll on V1), in the order they appear in the broll table.

    Returns a result dict: {attempted, success, count, message, clips}
    """
    if not broll_bin:
        return {
            "attempted": False,
            "success": False,
            "count": 0,
            "message": "No bRoll bin available",
            "clips": [],
        }

    if not timeline or not media_pool:
        return {
            "attempted": True,
            "success": False,
            "count": 0,
            "message": "Timeline or media pool unavailable",
            "clips": [],
        }

    try:
        broll_clips = broll_bin.GetClipList() or []
    except Exception as list_err:
        return {
            "attempted": True,
            "success": False,
            "count": 0,
            "message": f"Could not list bRoll clips: {list_err}",
            "clips": [],
        }

    if not broll_clips:
        return {
            "attempted": True,
            "success": False,
            "count": 0,
            "message": "bRoll bin is empty",
            "clips": [],
        }

    # Dedupe clips that refer to the same underlying broll video. The broll
    # bin commonly accumulates 2–4 copies of every clip because the same
    # filename is imported from multiple locations:
    #   • ~/Dev/Davinci/Template/broll/*
    #   • {project}/bRoll/*  (and nested subdirs picked up by rglob)
    #   • case variations (broll vs bRoll) on APFS
    # All of those have different absolute paths but identical *basenames*,
    # so we dedupe by basename (case-insensitive). Among duplicates, prefer
    # the clip whose source path lives under the project's broll folder over
    # the template, so we use the project-generated copy when both exist.
    def _clip_basename(c):
        for prop in ("File Path", "Resolved File Path"):
            try:
                val = c.GetClipProperty(prop)
            except Exception:
                val = None
            if val:
                return os.path.basename(str(val)).lower()
        try:
            return (c.GetName() or "").lower()
        except Exception:
            return str(id(c))

    def _clip_is_template(c):
        for prop in ("File Path", "Resolved File Path"):
            try:
                val = c.GetClipProperty(prop)
            except Exception:
                val = None
            if val:
                p = str(val).lower()
                return ("/davinci/template/" in p) or ("/template/broll/" in p)
        return False

    by_name = {}
    for c in broll_clips:
        key = _clip_basename(c)
        if not key:
            continue
        existing = by_name.get(key)
        if existing is None:
            by_name[key] = c
        else:
            # Prefer the non-template copy if we have a choice.
            if _clip_is_template(existing) and not _clip_is_template(c):
                print(f"   ♻️  Replacing template duplicate with project copy: {c.GetName()}")
                by_name[key] = c
            else:
                print(f"   ⚠️ Skipping duplicate bRoll clip: {c.GetName()}")
    broll_clips = list(by_name.values())

    # Sort by index in the Grok filename so timeline order == broll table order.
    sorted_clips = sorted(broll_clips, key=lambda c: _broll_sort_key(c.GetName()))
    ordered_names = [c.GetName() for c in sorted_clips]
    print(f"\n🎞️  bRoll order on V3 ({len(sorted_clips)} clips):")
    for i, n in enumerate(ordered_names, 1):
        print(f"   {i}. {n}")

    # Ensure at least V3 exists (track setup helper normally handles this,
    # but keep a defensive add here in case the helper wasn't run).
    try:
        video_track_count = timeline.GetTrackCount("video")
    except Exception:
        video_track_count = 1
    if video_track_count is None:
        video_track_count = 1
    while video_track_count < 3:
        try:
            timeline.AddTrack("video")
            video_track_count += 1
            print(f"   ➕ Added video track V{video_track_count} (fallback)")
        except Exception as add_err:
            print(f"   ⚠️ Could not add V{video_track_count + 1} track: {add_err}")
            break

    # Make this timeline current so AppendToTimeline targets it.
    try:
        project = media_pool.GetCurrentFolder() and None  # no-op safe access
    except Exception:
        pass

    # Compute the timeline start frame so the first broll clip lines up with
    # the very beginning of V1 (above the first aRoll clip).
    try:
        start_frame = int(timeline.GetStartFrame())
    except Exception:
        start_frame = 0

    def _clip_duration_frames(mp_item):
        """Return the clip's duration in frames (best-effort)."""
        for prop in ("Frames", "Duration"):
            try:
                val = mp_item.GetClipProperty(prop)
            except Exception:
                val = None
            if not val:
                continue
            # "Frames" is usually an integer string; "Duration" is HH:MM:SS:FF.
            try:
                if str(val).isdigit():
                    return int(val)
            except Exception:
                pass
            # Parse timecode HH:MM:SS:FF assuming 24fps fallback.
            try:
                parts = str(val).split(":")
                if len(parts) == 4:
                    h, m, s, f = (int(p) for p in parts)
                    fps = 24
                    try:
                        fps_val = mp_item.GetClipProperty("FPS")
                        if fps_val:
                            fps = int(round(float(fps_val)))
                    except Exception:
                        pass
                    return ((h * 3600) + (m * 60) + s) * fps + f
            except Exception:
                continue
        return 0

    # Append clips one at a time on V3 starting at the timeline start frame.
    appended = []
    cursor = start_frame
    for clip in sorted_clips:
        duration = _clip_duration_frames(clip)
        clip_info = {
            "mediaPoolItem": clip,
            "trackIndex": 3,
            "mediaType": 1,        # 1 = video
            "recordFrame": cursor, # absolute timeline frame to drop onto V3
        }
        try:
            result = media_pool.AppendToTimeline([clip_info])
        except Exception as ap_err:
            print(f"   ❌ AppendToTimeline failed for {clip.GetName()}: {ap_err}")
            continue
        if result:
            appended.append(clip.GetName())
            print(f"   ✅ V3 @ frame {cursor} (+{duration}f): {clip.GetName()}")
            if duration > 0:
                cursor += duration
            else:
                # Fallback: bump cursor by 1 second @ 24fps so next clip doesn't overlap.
                cursor += 24
        else:
            print(f"   ⚠️ AppendToTimeline returned empty for {clip.GetName()} @ frame {cursor}")

    if appended:
        return {
            "attempted": True,
            "success": True,
            "count": len(appended),
            "message": f"Added {len(appended)} bRoll clip(s) to V3",
            "clips": appended,
        }
    return {
        "attempted": True,
        "success": False,
        "count": 0,
        "message": "AppendToTimeline did not place any bRoll clips on V3",
        "clips": [],
    }


def create_resolve_project(script_title, edl_filename=None, broll_folder=None, images_folder=None):
    """
    Create a new DaVinci Resolve project with automated setup

    Args:
        script_title: Full script title
        edl_filename: Optional EDL file to import

    Returns:
        dict with success status, project details, or error message
    """
    try:
        # Set required environment variables for DaVinci Resolve API
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

        # Add modules to Python path
        modules_path = os.path.join(resolve_script_api, "Modules")
        if modules_path not in sys.path:
            sys.path.append(modules_path)

        # Import DaVinci Resolve Python API
        import DaVinciResolveScript as dvr_script

        resolve = dvr_script.scriptapp("Resolve")
        if not resolve:
            return {
                "success": False,
                "error": "DaVinci Resolve is not running. Please start Resolve first."
            }

        project_manager = resolve.GetProjectManager()
        if not project_manager:
            return {
                "success": False,
                "error": "Failed to get Project Manager from Resolve"
            }

        # Create condensed project name
        project_name = sanitize_project_name(script_title)

        # Check if project already exists
        existing_project = project_manager.LoadProject(project_name)
        if existing_project:
            return {
                "success": False,
                "error": f"A project named '{project_name}' already exists. Please delete it from DaVinci Resolve or use a different script title."
            }

        # Create new project
        project = project_manager.CreateProject(project_name)
        if not project:
            return {
                "success": False,
                "error": f"Failed to create project '{project_name}'"
            }

        # Get media pool for bin creation
        media_pool = project.GetMediaPool()
        if not media_pool:
            return {
                "success": False,
                "error": "Failed to get Media Pool from project"
            }

        # Create master bins structure matching template directory.
        # NOTE: "heygen" and "raw" bins are intentionally omitted — those
        # template subdirectories are no longer copied into new projects and
        # the corresponding bins should not be created in the media pool.
        bins_created = []
        bin_structure = [
            "intro",
            "aroll",
            "broll",
            "animations",
            "timelines",
            "audio",
            "images"
        ]

        root_folder = media_pool.GetRootFolder()
        bin_mapping = {}  # Store bin objects for media import

        for bin_name in bin_structure:
            new_bin = media_pool.AddSubFolder(root_folder, bin_name)
            if new_bin:
                bins_created.append(bin_name)
                bin_mapping[bin_name] = new_bin

        # Import template media files into corresponding bins
        template_path = Path.home() / "Dev" / "Davinci" / "Template"
        media_imported = {}
        intro_clip = None  # Store AI with Roz v2.mov clip

        if template_path.exists():
            for bin_name in bin_structure:
                bin_folder = template_path / bin_name
                if bin_folder.exists() and bin_folder.is_dir():
                    # Get all media files directly in this bin folder
                    media_files = []
                    for ext in ['*.mp4', '*.mov', '*.avi', '*.mkv',
                                '*.mp3', '*.wav', '*.aac',
                                '*.jpg', '*.png', '*.tiff']:
                        media_files.extend(bin_folder.glob(ext))

                    if media_files and bin_name in bin_mapping:
                        # Convert paths to strings
                        file_paths = [str(f) for f in media_files]

                        # Import into corresponding bin
                        imported = media_pool.ImportMedia(file_paths)
                        if imported:
                            # Move imported clips to correct bin
                            target_bin = bin_mapping[bin_name]
                            for clip in imported:
                                media_pool.MoveClips([clip], target_bin)

                                # Check if this is the intro clip we need for timeline
                                if bin_name == "intro" and "AI with Roz v2.mov" in str(file_paths):
                                    clip_name = clip.GetName()
                                    if "AI with Roz v2" in clip_name:
                                        intro_clip = clip

                            media_imported[bin_name] = len(imported)

                    # Handle subdirectories for heygen bin
                    if bin_name == "heygen":
                        subdirs = [d for d in bin_folder.iterdir()
                                   if d.is_dir()]
                        for subdir in subdirs:
                            # Create sub-bin
                            sub_bin_name = subdir.name
                            sub_bin = media_pool.AddSubFolder(
                                bin_mapping[bin_name], sub_bin_name)

                            if sub_bin:
                                bins_created.append(
                                    f"{bin_name}/{sub_bin_name}")

                                # Get all media files in subdirectory
                                sub_media_files = []
                                for ext in ['*.mp4', '*.mov', '*.avi', '*.mkv',
                                            '*.mp3', '*.wav', '*.aac',
                                            '*.jpg', '*.png', '*.tiff']:
                                    sub_media_files.extend(subdir.glob(ext))

                                if sub_media_files:
                                    sub_file_paths = [str(f)
                                                      for f in sub_media_files]

                                    # Import into sub-bin
                                    sub_imported = media_pool.ImportMedia(
                                        sub_file_paths)
                                    if sub_imported:
                                        # Move imported clips to sub-bin
                                        for clip in sub_imported:
                                            media_pool.MoveClips(
                                                [clip], sub_bin)

                                        # Track imported media count
                                        sub_key = f"{bin_name}/{sub_bin_name}"
                                        media_imported[sub_key] = len(
                                            sub_imported)

        # Import additional project-generated media (e.g., prior Grok b-roll and generated images).
        supplemental_imported = {}
        broll_paths = _collect_media_paths(
            broll_folder,
            extensions={'.mp4', '.mov', '.m4v', '.avi', '.mkv'}
        )
        images_paths = _collect_media_paths(
            images_folder,
            extensions={'.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff'}
        )

        # Skip supplemental broll files whose basename was already imported
        # from the template (~/Dev/Davinci/Template/broll/*). Without this
        # filter the broll bin ends up with 2 copies of every clip that
        # exists in both folders — which is the common case because the
        # project's broll folder typically mirrors the template plus any
        # newly-generated Grok clips.
        try:
            template_broll_dir = Path.home() / "Dev" / "Davinci" / "Template" / "broll"
            template_broll_basenames = set()
            if template_broll_dir.exists():
                for p in template_broll_dir.iterdir():
                    if p.is_file():
                        template_broll_basenames.add(p.name.lower())
            if template_broll_basenames and broll_paths:
                filtered = []
                skipped = 0
                for p in broll_paths:
                    if os.path.basename(p).lower() in template_broll_basenames:
                        skipped += 1
                        continue
                    filtered.append(p)
                if skipped:
                    print(f"   ♻️ Skipping {skipped} supplemental broll file(s) already imported from template")
                broll_paths = filtered
        except Exception as dedupe_err:
            print(f"   ⚠️ Could not dedupe broll vs template: {dedupe_err}")

        broll_count = _import_media_to_bin(resolve, media_pool, bin_mapping, 'broll', broll_paths)
        images_count = _import_media_to_bin(resolve, media_pool, bin_mapping, 'images', images_paths)
        if broll_count > 0:
            supplemental_imported['broll'] = broll_count
        if images_count > 0:
            supplemental_imported['images'] = images_count

        # Set current folder to timelines bin before creating timeline
        if "timelines" in bin_mapping:
            media_pool.SetCurrentFolder(bin_mapping["timelines"])

        # Create timeline named after script title
        timeline_name = script_title
        timeline = media_pool.CreateEmptyTimeline(timeline_name)
        if not timeline:
            return {
                "success": False,
                "error": f"Failed to create timeline '{timeline_name}'"
            }

        # Add intro clip to timeline if found
        if intro_clip:
            media_pool.AppendToTimeline([intro_clip])

        # Set the timeline as current
        project.SetCurrentTimeline(timeline)

        # Import EDL file if provided
        edl_timeline = None
        if edl_filename:
            edl_path = Path(edl_filename)
            print(f"🎬 Attempting to import EDL from: {edl_path}")
            print(f"📁 EDL file exists: {edl_path.exists()}")

            if edl_path.exists():
                try:
                    # Set current folder to timelines bin before importing
                    if "timelines" in bin_mapping:
                        print(f"📁 Setting current folder to timelines bin")
                        media_pool.SetCurrentFolder(bin_mapping["timelines"])

                    print(f"�📥 Importing EDL timeline...")
                    # Try ImportTimelineFromFile method
                    edl_timeline = media_pool.ImportTimelineFromFile(
                        str(edl_path)
                    )

                    if edl_timeline:
                        print(
                            f"✅ EDL timeline imported: {edl_timeline.GetName()}")
                        bins_created.append("EDL Timeline Imported")
                    else:
                        # If ImportTimelineFromFile doesn't work, try CreateTimelineFromClips
                        print(
                            f"⚠️ ImportTimelineFromFile returned None, trying alternative...")
                        print(
                            f"⚠️ EDL import via API not supported - markers must be added manually")

                except Exception as edl_error:
                    # Don't fail the whole operation if EDL import fails
                    print(f"⚠️ Warning: Failed to import EDL: {edl_error}")
                    import traceback
                    traceback.print_exc()
            else:
                print(f"❌ EDL file not found at path: {edl_path}")

        result_data = {
            "success": True,
            "project_name": project_name,
            "timeline_name": timeline_name,
            "bins_created": bins_created,
            "media_imported": media_imported,
            "supplemental_media_imported": supplemental_imported,
            "message": "Project created successfully!"
        }

        # Add EDL import status if attempted
        if edl_filename:
            if edl_timeline:
                result_data["edl_imported"] = True
                result_data["edl_timeline_name"] = edl_timeline.GetName()
                result_data["edl_message"] = "EDL timeline imported successfully"
            else:
                result_data["edl_imported"] = False
                result_data["edl_message"] = (
                    "EDL created but not imported automatically. "
                    "DaVinci Resolve API doesn't support marker-only EDL import. "
                    "You can manually add markers by importing the EDL file "
                    "or copying markers from the EDL tab."
                )

        return result_data

    except ImportError:
        return {
            "success": False,
            "error": "DaVinci Resolve Python API not found. Please ensure Resolve is installed and Python API is configured."
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Unexpected error: {str(e)}"
        }


def create_resolve_project_with_videos(
    script_title,
    edl_filename=None,
    aroll_folder=None,
    sorted_video_files=None,
    broll_folder=None,
    images_folder=None,
    generate_subtitles=True,
):
    """
    Create a new DaVinci Resolve project with aRoll videos added to timeline

    Args:
        script_title: Full script title
        edl_filename: Optional EDL file to import
        aroll_folder: Path to folder containing aRoll videos
        sorted_video_files: List of video filenames in desired timeline order

    Returns:
        dict with success status, project details, videos added, or error
    """
    print("\n" + "="*80)
    print("🎬 CREATE DAVINCI PROJECT WITH VIDEOS")
    print("="*80)
    print(f"📝 Script title: {script_title}")
    print(f"📁 aRoll folder: {aroll_folder}")
    print(
        f"🎥 Videos to add: {len(sorted_video_files) if sorted_video_files else 0}")
    if sorted_video_files:
        for i, v in enumerate(sorted_video_files, 1):
            print(f"   {i}. {v}")

    try:
        # First create the base project
        print("\n📦 Creating base project...")
        base_result = create_resolve_project(
            script_title,
            edl_filename,
            broll_folder=broll_folder,
            images_folder=images_folder,
        )

        if not base_result.get("success"):
            print("❌ Base project creation failed")
            return base_result

        print("✅ Base project created")

        # If no videos to add, return base result
        if not aroll_folder or not sorted_video_files:
            print("⚠️ No videos to add - returning base result")
            return base_result

        print(f"\n🎥 Processing {len(sorted_video_files)} videos...")

        # Import DaVinci Resolve Python API
        resolve_script_api = (
            "/Library/Application Support/Blackmagic Design/"
            "DaVinci Resolve/Developer/Scripting"
        )
        modules_path = os.path.join(resolve_script_api, "Modules")
        if modules_path not in sys.path:
            sys.path.append(modules_path)

        import DaVinciResolveScript as dvr_script

        print("🔌 Connecting to DaVinci Resolve...")
        resolve = dvr_script.scriptapp("Resolve")
        if not resolve:
            print("❌ Could not connect to Resolve")
            base_result["warning"] = "Could not add videos - Resolve not accessible"
            return base_result

        print("✅ Connected to Resolve")

        project_manager = resolve.GetProjectManager()
        project_name = sanitize_project_name(script_title)

        print(f"📂 Loading project: {project_name}")
        project = project_manager.LoadProject(project_name)

        if not project:
            print(f"❌ Could not load project: {project_name}")
            base_result["warning"] = "Could not load project to add videos"
            return base_result

        print(f"✅ Project loaded: {project_name}")

        print("🎬 Getting media pool...")
        media_pool = project.GetMediaPool()
        if not media_pool:
            print("❌ Could not get media pool")
            base_result["warning"] = "Could not get media pool to add videos"
            return base_result

        print("✅ Media pool ready")

        # Import video files to aRoll bin
        root_folder = media_pool.GetRootFolder()
        aroll_bin = None

        print("📁 Looking for aroll bin...")
        # Find aroll bin
        for subfolder in root_folder.GetSubFolders().values():
            print(f"   Found bin: {subfolder.GetName()}")
            if subfolder.GetName() == "aroll":
                aroll_bin = subfolder
                break

        if not aroll_bin:
            print("❌ Could not find aroll bin")
            base_result["warning"] = "Could not find aroll bin"
            return base_result

        print("✅ Found aroll bin")

        # Set current folder to aRoll bin
        media_pool.SetCurrentFolder(aroll_bin)
        print("✅ Set current folder to aRoll bin")

        # Import all videos
        print(
            f"📦 Building video paths from {len(sorted_video_files)} files...")
        video_paths = [
            os.path.join(aroll_folder, filename)
            for filename in sorted_video_files
        ]

        # Filter to only existing files
        existing_paths = [p for p in video_paths if os.path.exists(p)]
        print(f"✅ Found {len(existing_paths)} existing video files")

        if not existing_paths:
            print("❌ No video files found to import")
            base_result["warning"] = "No video files found to import"
            return base_result

        # Import video files
        print("📥 Importing videos to media pool...")
        storage = resolve.GetMediaStorage()
        imported_clips = storage.AddItemsToMediaPool(existing_paths)

        if not imported_clips:
            print("❌ Failed to import video files to media pool")
            base_result["warning"] = "Failed to import video files to media pool"
            return base_result

        print(
            f"✅ Imported {len(imported_clips) if imported_clips else 0} clips")

        # Get the main timeline
        # Use the original script title (not sanitized) since timeline was created with it
        timeline_name = script_title  # NOT sanitize_project_name(script_title)
        print(f"🔍 Looking for timeline: {timeline_name}")
        print(f"📊 Project has {project.GetTimelineCount()} timeline(s)")
        timeline = None

        # Find timeline by name
        for i in range(project.GetTimelineCount()):
            tl = project.GetTimelineByIndex(i + 1)
            if tl:
                tl_name = tl.GetName()
                print(f"   Timeline {i+1}: {tl_name}")
                if tl_name == timeline_name:
                    timeline = tl
                    print(f"✅ Found matching timeline: {timeline_name}")
                    break

        if not timeline:
            print(f"❌ Could not find timeline matching: {timeline_name}")
            base_result["warning"] = "Could not find main timeline"
            return base_result

        # Set timeline as current
        project.SetCurrentTimeline(timeline)

        # WORKAROUND: AppendToTimeline doesn't work with existing content
        # We need to clear the timeline first, then add all videos in order
        print(f"\n🔧 Clearing existing timeline content...")

        # Get all items in all tracks
        video_track_items = timeline.GetItemListInTrack("video", 1)
        audio_track_items = timeline.GetItemListInTrack("audio", 1)

        total_items = len(video_track_items) + len(audio_track_items)
        print(
            f"   Found {len(video_track_items)} video items, {len(audio_track_items)} audio items")

        # Delete all existing items from both tracks
        if video_track_items:
            print(f"   Removing {len(video_track_items)} video items...")
            timeline.DeleteClips(video_track_items)

        if audio_track_items:
            print(f"   Removing {len(audio_track_items)} audio items...")
            timeline.DeleteClips(audio_track_items)

        if total_items > 0:
            print(f"   ✅ Cleared timeline (removed {total_items} items)")

        # Get clips from aRoll bin
        # Note: GetClipList() returns a list of MediaPoolItem objects
        aroll_clips = aroll_bin.GetClipList()

        if not aroll_clips:
            base_result["warning"] = "No clips found in aRoll bin after import"
            return base_result

        print(f"\n🔍 DEBUG: Found {len(aroll_clips)} clips in aRoll bin")
        print("🔍 DEBUG: Clip names in bin:")
        for clip in aroll_clips:
            clip_name = clip.GetName()
            print(f"   - {clip_name}")

        # Get intro video from Intro bin
        intro_bin = None
        for subfolder in root_folder.GetSubFolders().values():
            if subfolder.GetName() == "intro":
                intro_bin = subfolder
                break

        intro_clip = None
        exit_clip = None
        if intro_bin:
            intro_clips = intro_bin.GetClipList()
            print(f"\n🔍 Looking for intro/exit videos in intro bin...")
            print(f"   Found {len(intro_clips)} clips in Intro bin")

            # Look for "AI with Roz v2.mov" (intro) and
            # "AI with Roz NEW EXIT 4K Edited 2.mov" (exit)
            for clip in intro_clips:
                clip_name = clip.GetName()
                print(f"   - {clip_name}")
                if intro_clip is None and (
                        "AI with Roz v2" in clip_name
                        or "AI_with_Roz_v2" in clip_name):
                    intro_clip = clip
                    print(f"   ✅ Found intro video: {clip_name}")
                elif exit_clip is None and (
                        "AI with Roz NEW EXIT 4K Edited 2" in clip_name
                        or "AI_with_Roz_NEW_EXIT_4K_Edited_2" in clip_name):
                    exit_clip = clip
                    print(f"   ✅ Found exit video: {clip_name}")

            if not intro_clip:
                print(f"   ⚠️ Intro video 'AI with Roz v2.mov' not found in Intro bin")
            if not exit_clip:
                print(f"   ⚠️ Exit video 'AI with Roz NEW EXIT 4K Edited 2.mov' not found in Intro bin")

        # Create a mapping of clip name to clip object
        clip_map = {}
        for clip in aroll_clips:
            clip_name = clip.GetName()
            clip_map[clip_name] = clip

        # Build list of clips in sorted order (intro first, then aRoll videos)
        clips_to_add = []

        # Add intro video first if found
        if intro_clip:
            clips_to_add.append(intro_clip)
            print(f"\n📺 Intro video will be added first")

        for filename in sorted_video_files:
            print(f"\n🔍 DEBUG: Matching: {filename}")

            # Try to match clip by filename (without extension)
            clip_name_base = os.path.splitext(filename)[0]
            print(f"   Base name: {clip_name_base}")

            # Try exact match first
            clip = None
            if filename in clip_map:
                print(f"   ✅ Found exact match: {filename}")
                clip = clip_map[filename]
            elif clip_name_base in clip_map:
                print(f"   ✅ Found base name match: {clip_name_base}")
                clip = clip_map[clip_name_base]
            else:
                # Try partial match
                for name, clip_obj in clip_map.items():
                    if clip_name_base in name or name in clip_name_base:
                        print(f"   ✅ Found partial match: {name}")
                        clip = clip_obj
                        break

                if not clip:
                    print(f"   ❌ No match found for {filename}")

            if clip:
                clips_to_add.append(clip)

        # Add exit video last if found (always the final clip on V1)
        if exit_clip:
            clips_to_add.append(exit_clip)
            print(f"\n📺 Exit video will be added last")

        print(f"\n� Prepared {len(clips_to_add)} clips to add to timeline")

        # Verify timeline is empty
        current_items = timeline.GetItemListInTrack("video", 1)
        print(f"🔍 Current timeline items: {len(current_items)}")

        if clips_to_add:
            # Skip Method 1 (AppendToTimeline) and go directly to Method 2
            # Method 1 consistently fails with [None] results on empty timelines
            print(f"\n🎬 Creating new timeline from clips...")
            print(f"   (Skipping AppendToTimeline - known to fail on cleared timelines)")

            # Delete the current empty timeline
            media_pool.DeleteTimelines([timeline])

            # Create a new timeline from the clips
            timeline_name = sanitize_project_name(script_title)
            new_timeline = media_pool.CreateTimelineFromClips(
                timeline_name,
                clips_to_add
            )

            if new_timeline:
                print(
                    f"   ✅ Created new timeline with {len(clips_to_add)} clips!")
                videos_added = sorted_video_files
                timeline = new_timeline
                project.SetCurrentTimeline(timeline)

                # Configure track layout: V1=aroll, V2=adjustment, V3=broll, V4=animations, V5=temp clips
                print("\n🛤️  Configuring video track layout...")
                track_layout = _setup_video_tracks(timeline)
                base_result["video_track_layout"] = track_layout
            else:
                print(f"   ❌ CreateTimelineFromClips failed")
                print(f"\n⚠️ DaVinci Resolve API limitation detected")
                print(f"   Possible causes:")
                print(f"   1. 'External scripting using' not enabled in Preferences")
                print(f"   2. Timeline is locked or has restrictions")
                print(f"   3. Clips are in unsupported format")
                print(f"\n📝 Manual workaround:")
                print(f"   1. Open DaVinci Resolve")
                print(
                    f"   2. Go to project '{sanitize_project_name(script_title)}'")
                print(f"   3. Drag clips from aRoll bin to timeline manually")

        # Final verification
        final_items = timeline.GetItemListInTrack("video", 1)
        print(f"\n🔍 Final timeline items: {len(final_items)}")

        # ------------------------------------------------------------------
        # (Adjustment-clip insertion on V2 disabled — Resolve scripting
        # API has no reliable way to create empty adjustment clips.)
        # ------------------------------------------------------------------

        # ------------------------------------------------------------------
        # B-ROLL: import to the 'broll' bin ONLY — do NOT place it on the
        # timeline. Per project preference, generated b-roll (like the
        # animations and images bins) is left in the media pool for the editor
        # to place manually. The V3 wipe/fade styling passes are therefore
        # skipped too, since there are no auto-placed V3 clips to style.
        # ------------------------------------------------------------------
        broll_v2_result = {
            "attempted": False, "success": True, "count": 0,
            "message": "B-roll imported to the 'broll' bin only (not placed on the timeline)",
        }
        print(f"   ℹ️ {broll_v2_result['message']}")
        base_result["broll_wipe_v3"] = {
            "attempted": False, "success": True,
            "message": "Skipped — b-roll is bin-only, not on the timeline",
        }
        base_result["broll_fade_out"] = {
            "attempted": False, "success": True,
            "message": "Skipped — b-roll is bin-only, not on the timeline",
        }

        # ------------------------------------------------------------------
        # Configure audio tracks (A1='aroll sound', A2='background sound')
        # and place background music clips on A2 in fixed order.
        # ------------------------------------------------------------------
        print("\n🎵 Configuring audio track layout...")
        audio_track_layout = _setup_audio_tracks(timeline)
        base_result["audio_track_layout"] = audio_track_layout

        audio_bin = None
        try:
            for subfolder in root_folder.GetSubFolders().values():
                if subfolder.GetName() == "audio":
                    audio_bin = subfolder
                    break
        except Exception as bin_err:
            print(f"⚠️ Could not locate audio bin: {bin_err}")

        background_audio_result = _add_background_audio_clips(
            media_pool, timeline, audio_bin
        )
        print(
            f"   {'✅' if background_audio_result.get('success') else '⚠️'} "
            f"{background_audio_result.get('message')}"
        )
        base_result["background_audio"] = background_audio_result

        # Apply MagicZoomPro Resolve FX to every aRoll clip on V1.
        magic_zoom_result = _apply_effect_to_aroll_clips(timeline, "MagicZoomPro")
        print(
            f"   {'✅' if magic_zoom_result.get('success') else '⚠️'} "
            f"{magic_zoom_result.get('message')}"
        )
        base_result["magic_zoom_pro"] = magic_zoom_result

        # Build list of what was added
        videos_list = []
        if intro_clip and len(final_items) > 0:
            videos_list.append("AI with Roz v2.mov (intro)")

        if len(final_items) > (1 if intro_clip else 0):
            videos_list.extend(sorted_video_files)

        videos_added = videos_list if len(final_items) > 0 else []

        # Subtitles are intentionally NOT generated, per project preference.
        # (The generate_subtitles arg is ignored on purpose; flip this block back
        # on if auto-subtitles are ever wanted again.)
        subtitle_result = {
            "attempted": False,
            "success": False,
            "message": "Subtitle generation disabled",
        }

        # Update result with video info
        base_result["videos_added"] = videos_added
        base_result["videos_count"] = len(videos_added)
        base_result["subtitle_generation"] = subtitle_result
        base_result["broll_v2"] = broll_v2_result

        if intro_clip:
            base_result["message"] = (
                f"Project created with intro + {len(sorted_video_files)} "
                f"aRoll videos in timeline"
            )
        else:
            base_result["message"] = (
                f"Project created with {len(videos_added)} videos in timeline"
            )

        return base_result

    except Exception as e:
        # Return base result with warning if video addition fails
        if 'base_result' in locals():
            base_result["warning"] = f"Videos not added: {str(e)}"
            return base_result
        return {
            "success": False,
            "error": f"Failed to create project with videos: {str(e)}"
        }


def export_audio_only(output_path: str | None = None, timeline_name: str | None = None,
                      format_str: str = "wav", codec: str = "LinearPCM",
                      sample_rate: int = 48000) -> dict:
    """
    Render the current (or named) DaVinci Resolve timeline as audio only and
    save it to *output_path*.

    Args:
        output_path:   Absolute path for the exported file, WITHOUT extension.
                       Defaults to ~/Desktop/<project>_audio_<timestamp>
        timeline_name: Name of the timeline to render. Uses the currently
                       active timeline if None.
        format_str:    Resolve render format string.  Common values:
                           "wav"  – uncompressed PCM (default)
                           "mp3"  – MPEG Layer 3
                           "aiff" – AIFF / AIFC
                           "aac"  – AAC inside an M4A container
        codec:         Resolve codec string matching the format.
                           WAV  → "LinearPCM"   (24-bit)
                           MP3  → "MP3"
                           AIFF → "AIFF"
                           AAC  → "AAC"
        sample_rate:   Sample rate in Hz (48000 or 44100 are most common).

    Returns:
        dict with keys:
            success (bool)
            output_file (str)  – final rendered file path (if success)
            message  (str)
            error    (str)     – only present on failure
    """
    import time

    try:
        import DaVinciResolveScript as dvr_script
        resolve = dvr_script.scriptapp("Resolve")
        if resolve is None:
            return {"success": False, "error": "DaVinci Resolve is not running or not reachable."}

        project_manager = resolve.GetProjectManager()
        project = project_manager.GetCurrentProject()
        if project is None:
            return {"success": False, "error": "No project is currently open in DaVinci Resolve."}

        project_name = project.GetName()

        # ── Select timeline ────────────────────────────────────────────────
        if timeline_name:
            tl = None
            for i in range(1, project.GetTimelineCount() + 1):
                t = project.GetTimelineByIndex(i)
                if t and t.GetName() == timeline_name:
                    tl = t
                    break
            if tl is None:
                return {"success": False, "error": f"Timeline '{timeline_name}' not found."}
            project.SetCurrentTimeline(tl)
        else:
            tl = project.GetCurrentTimeline()
            if tl is None:
                return {"success": False, "error": "No timeline is active. Open a timeline first."}

        tl_name = tl.GetName()
        _log(f"🎵 Audio export: project='{project_name}'  timeline='{tl_name}'")

        # ── Build output path ──────────────────────────────────────────────
        if not output_path:
            ts = time.strftime("%Y%m%d_%H%M%S")
            safe_name = re.sub(r'[^\w\-]', '_', project_name)[:40]
            output_path = str(Path.home() / "Desktop" / f"{safe_name}_audio_{ts}")

        output_path = str(Path(output_path))  # normalise
        output_dir = str(Path(output_path).parent)
        output_filename = Path(output_path).name

        Path(output_dir).mkdir(parents=True, exist_ok=True)
        _log(f"📁 Output dir: {output_dir}  file: {output_filename}")

        # ── Configure render settings ──────────────────────────────────────
        # Resolve's SetRenderSettings accepts a flat dict of key/value pairs.
        settings = {
            "SelectAllFrames":    True,
            "TargetDir":          output_dir,
            "CustomName":         output_filename,
            "ExportVideo":        False,       # ← audio only
            "ExportAudio":        True,
            "AudioCodec":         codec,
            "AudioSampleRate":    sample_rate,
            "AudioBitDepth":      24,
            "FormatWidth":        0,           # ignored for audio-only jobs
            "FormatHeight":       0,
        }

        # Switch to the correct render format
        if not project.SetCurrentRenderFormatAndCodec(format_str, codec):
            _log(f"⚠️  SetCurrentRenderFormatAndCodec('{format_str}', '{codec}') returned False — "
                 f"Resolve may still accept the job with a default codec.")

        if not project.SetRenderSettings(settings):
            return {"success": False,
                    "error": "SetRenderSettings failed. Check that the format/codec combination is "
                             "supported by your installed version of DaVinci Resolve."}

        # ── Queue and start render ─────────────────────────────────────────
        job_id = project.AddRenderJob()
        if not job_id:
            return {"success": False, "error": "AddRenderJob failed. Check Render page in Resolve."}

        _log(f"⏳ Render job queued (id={job_id}). Starting …")

        if not project.StartRendering(job_id):
            project.DeleteRenderJobList()
            return {"success": False, "error": "StartRendering failed."}

        # Poll until done (max 30 minutes)
        deadline = time.time() + 1800
        while time.time() < deadline:
            time.sleep(3)
            status = project.GetRenderJobStatus(job_id)
            job_status = (status or {}).get("JobStatus", "")
            _log(f"   render status: {job_status}")
            if job_status in ("Complete", "Cancelled", "Failed"):
                break

        if job_status != "Complete":
            return {"success": False,
                    "error": f"Render ended with status '{job_status}'. Check Resolve's Deliver page."}

        # ── Find actual output file ────────────────────────────────────────
        # Resolve appends the extension, so locate it.
        expected = Path(output_dir) / output_filename
        candidates = list(Path(output_dir).glob(f"{output_filename}*"))
        actual_file = str(candidates[0]) if candidates else f"{output_path}.{format_str}"

        _log(f"✅ Audio export complete: {actual_file}")
        return {
            "success": True,
            "output_file": actual_file,
            "message": f"Audio exported from '{tl_name}' → {actual_file}",
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    # Test the API
    print("🎬 Testing DaVinci Resolve API...")
    result = create_resolve_project("Test AI Video Project", None)
    print(f"Result: {result}")
