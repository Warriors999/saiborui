"""Analyze audio patterns in competitor videos: BGM changes, sound effects, volume dynamics."""

import json
import subprocess
from pathlib import Path

from rag_system.utils import logger


def analyze_audio(video_path: Path) -> dict:
    """Analyze audio from a video file for BGM and SFX patterns.

    Returns:
        bgm_segments: estimated BGM track segments
        sfx_count: estimated sound effect count (transient spikes)
        volume_profile: loudness over time
        silent_ratio: % of video that is silent/quiet
    """
    if not video_path.exists():
        return {"error": f"Video not found: {video_path}"}

    try:
        import numpy as np
        import librosa

        # Load audio (first 60s for efficiency, or full if short)
        y, sr = librosa.load(str(video_path), sr=22050, duration=120, mono=True)
        total_duration = len(y) / sr

        # ── Volume envelope ──
        hop_length = 512
        rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
        times = librosa.times_like(rms, sr=sr, hop_length=hop_length)

        # Normalize
        rms_db = librosa.amplitude_to_db(rms, ref=np.max(rms))

        # Segment into quiet/loud regions
        quiet_threshold = -25  # dB below peak
        is_quiet = rms_db < quiet_threshold
        silent_ratio = float(np.mean(is_quiet))

        # ── BGM segment detection ──
        # Detect significant volume changes as possible BGM transitions
        volume_diff = np.abs(np.diff(rms_db))
        bgm_changes = []
        threshold = np.mean(volume_diff) + 1.5 * np.std(volume_diff)
        for i in range(1, len(volume_diff)):
            if volume_diff[i] > threshold:
                bgm_changes.append(round(float(times[i]), 1))
        # Merge nearby changes (within 2 seconds)
        merged = []
        for t in bgm_changes:
            if not merged or t - merged[-1] > 2:
                merged.append(t)
        bgm_changes = merged

        # ── Sound effect detection (transient spikes) ──
        onset_frames = librosa.onset.onset_detect(
            y=y, sr=sr, hop_length=hop_length,
            backtrack=True, units='time',
        )
        # Filter to significant onsets only
        sfx_times = []
        for t in onset_frames:
            idx = int(t * sr / hop_length)
            if idx < len(rms_db) and rms_db[idx] > np.mean(rms_db):
                sfx_times.append(round(float(t), 1))

        # Merge nearby SFX (<0.5s apart)
        merged_sfx = []
        for t in sfx_times:
            if not merged_sfx or t - merged_sfx[-1] > 0.5:
                merged_sfx.append(t)

        # ── Segment-wise volume profile ──
        segment_dur = 5  # 5-second segments
        segments = []
        for start in range(0, int(total_duration), segment_dur):
            end = min(start + segment_dur, total_duration)
            seg_rms = rms_db[int(start * sr / hop_length):int(end * sr / hop_length)]
            if len(seg_rms) > 0:
                segments.append({
                    "start": start,
                    "end": end,
                    "avg_db": round(float(np.mean(seg_rms)), 1),
                    "peak_db": round(float(np.max(seg_rms)), 1),
                })

        result = {
            "duration_sec": round(total_duration, 1),
            "bgm_changes": len(bgm_changes),
            "bgm_change_times": bgm_changes[:20],  # first 20
            "sfx_estimated": len(merged_sfx),
            "sfx_times": merged_sfx[:30],  # first 30
            "silent_ratio": round(silent_ratio * 100, 1),
            "avg_volume_db": round(float(np.mean(rms_db)), 1),
            "volume_profile": segments,
        }
        logger.info(f"Audio: {len(bgm_changes)} BGM changes, ~{len(merged_sfx)} SFX, {result['silent_ratio']}% quiet")
        return result

    except ImportError:
        return {"error": "librosa not installed. pip install librosa"}
    except Exception as e:
        return {"error": str(e)}
