"""Analyze video visual patterns: shot rhythm, scene changes, editing pace."""

import json
import subprocess
from pathlib import Path

from rag_system.utils import logger


def analyze_visual(video_path: Path) -> dict:
    """Analyze a video file for visual/editing patterns.

    Returns:
        shot_count: estimated number of shots (scene changes)
        duration_sec: total video duration
        avg_shot_sec: average shot duration
        shot_variance: variance in shot durations
        cuts_per_minute: editing pace
        shot_durations: list of individual shot durations
    """
    if not video_path.exists():
        return {"error": f"Video not found: {video_path}"}

    try:
        import cv2
        import numpy as np

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return {"error": "Cannot open video"}

        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration_sec = total_frames / fps if fps > 0 else 0

        if duration_sec < 1:
            cap.release()
            return {"error": "Video too short"}

        # Sample every N frames (5 per second for efficiency)
        sample_interval = max(1, int(fps / 5))
        prev_hist = None
        shot_changes = []
        frame_num = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_num % sample_interval == 0:
                # Convert to HSV for better scene detection
                hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
                hist = cv2.calcHist([hsv], [0, 1], None, [50, 60], [0, 180, 0, 256])
                cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)

                if prev_hist is not None:
                    diff = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CHISQR)
                    # Threshold determined empirically for scene changes
                    if diff > 0.5:
                        shot_changes.append(frame_num / fps)

                prev_hist = hist

            frame_num += 1
            if frame_num > total_frames * 0.95:  # don't need last 5%
                break

        cap.release()

        if not shot_changes:
            return {"error": "No scene changes detected", "duration_sec": duration_sec}

        # Calculate shot durations
        shot_durations = []
        prev_time = 0
        for t in shot_changes:
            dur = t - prev_time
            if dur > 0.3:  # filter extremely short flashes
                shot_durations.append(round(dur, 2))
            prev_time = t

        if not shot_durations:
            return {"error": "No valid shots", "duration_sec": duration_sec}

        avg_shot = sum(shot_durations) / len(shot_durations)
        variance = sum((d - avg_shot) ** 2 for d in shot_durations) / len(shot_durations)

        # Classify shots
        short_shots = sum(1 for d in shot_durations if d <= 2)
        medium_shots = sum(1 for d in shot_durations if 2 < d <= 5)
        long_shots = sum(1 for d in shot_durations if d > 5)

        result = {
            "shot_count": len(shot_durations),
            "duration_sec": round(duration_sec, 1),
            "avg_shot_sec": round(avg_shot, 2),
            "shot_variance": round(variance, 2),
            "cuts_per_minute": round(len(shot_durations) / (duration_sec / 60), 1),
            "short_shots_pct": round(short_shots / len(shot_durations) * 100, 1),
            "medium_shots_pct": round(medium_shots / len(shot_durations) * 100, 1),
            "long_shots_pct": round(long_shots / len(shot_durations) * 100, 1),
        }
        logger.info(f"Visual: {result['shot_count']} shots, {result['avg_shot_sec']}s avg, {result['cuts_per_minute']} cpm")
        return result

    except ImportError:
        return {"error": "opencv-python not installed"}
    except Exception as e:
        return {"error": str(e)}
