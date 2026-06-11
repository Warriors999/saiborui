"""Analyze video visual patterns using ffmpeg + cloud VLM. Zero local model inference.

- Shot/cut detection: ffmpeg scene detect (hardware decoder, no model)
- Transition analysis: ffprobe frame analysis (~0 CPU)
- Visual composition: Gemini Vision / OpenAI Vision on keyframes (cloud API)
"""

import base64
import json
import subprocess
from pathlib import Path

from rag_system.utils import logger


# ── Shot detection (ffmpeg, no OpenCV) ──

def analyze_visual(video_path: Path) -> dict:
    """Detect shot boundaries and pacing using ffmpeg scene detection.

    Uses ffmpeg's built-in scene detection filter — no OpenCV, no local model.
    Returns shot stats suitable for editing analysis.
    """
    if not video_path.exists():
        return {"error": f"Video not found: {video_path}"}

    try:
        # Get duration
        probe_cmd = ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                      "-of", "csv=p=0", str(video_path)]
        result = subprocess.run(probe_cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=15)
        duration_sec = float(result.stdout.strip()) if result.stdout.strip() else 0

        if duration_sec < 1:
            return {"error": "Video too short", "duration_sec": duration_sec}

        # ffmpeg scene detect — outputs list of scene change timestamps
        scene_cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vf", "select='gt(scene,0.3)',showinfo",
            "-vsync", "vfr",
            "-f", "null",
            "-",
        ]
        result = subprocess.run(scene_cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=60)

        # Parse timestamps from showinfo output
        import re
        timestamps = []
        for line in result.stderr.split("\n"):
            m = re.search(r'pts_time:([\d.]+)', line)
            if m:
                timestamps.append(float(m.group(1)))

        if not timestamps:
            return {"shot_count": 1, "duration_sec": round(duration_sec, 1),
                    "avg_shot_sec": round(duration_sec, 1), "cuts_per_minute": 0,
                    "short_shots_pct": 0, "medium_shots_pct": 0, "long_shots_pct": 100}

        # Calculate shot durations
        shot_durations = []
        prev = 0
        for t in timestamps:
            dur = t - prev
            if dur > 0.3:
                shot_durations.append(round(dur, 2))
            prev = t

        if not shot_durations:
            return {"error": "No valid shots", "duration_sec": round(duration_sec, 1)}

        avg_shot = sum(shot_durations) / len(shot_durations)
        variance = sum((d - avg_shot) ** 2 for d in shot_durations) / len(shot_durations)

        short = sum(1 for d in shot_durations if d <= 2)
        medium = sum(1 for d in shot_durations if 2 < d <= 5)
        long = sum(1 for d in shot_durations if d > 5)
        total = len(shot_durations)

        # Classify rhythm
        rapid_pct = short / total * 100
        slow_pct = long / total * 100
        if rapid_pct >= 40:
            rhythm = "快节奏高密度剪辑"
        elif slow_pct >= 40:
            rhythm = "慢节奏沉浸式展示"
        else:
            rhythm = "标准口播节奏"

        result = {
            "shot_count": total,
            "duration_sec": round(duration_sec, 1),
            "avg_shot_sec": round(avg_shot, 2),
            "shot_variance": round(variance, 2),
            "cuts_per_minute": round(total / (duration_sec / 60), 1),
            "short_shots_pct": round(rapid_pct, 1),
            "medium_shots_pct": round(medium / total * 100, 1),
            "long_shots_pct": round(slow_pct, 1),
            "transitions": {"dominant": rhythm, "rapid_pct": round(rapid_pct, 1),
                           "standard_pct": round(medium / total * 100, 1),
                           "slow_pct": round(slow_pct, 1)},
        }
        logger.info(f"Visual (ffmpeg): {total} shots, {avg_shot:.1f}s avg, {rhythm}")
        return result

    except Exception as e:
        return {"error": str(e)}


# ── Cloud VLM Keyframe Analysis ──

def analyze_keyframes(keyframe_dir: Path, transcript: str = "",
                      category: str = "", video_title: str = "") -> str:
    """Analyze keyframes using cloud VLM API for visual composition learning.

    Sends up to 5 representative frames to a vision-capable LLM.
    Priority: 智谱 GLM-4V > Gemini Vision > OpenAI Vision > text inference.
    """
    frame_paths = []
    if keyframe_dir and keyframe_dir.exists():
        frame_paths = sorted(keyframe_dir.glob("frame_*.jpg"))[:5]

    if not frame_paths:
        return "（无关键帧可供分析）"

    # Try providers in order: 智谱 > Gemini > OpenAI Vision
    for fn in (_analyze_with_zhipu, _analyze_with_gemini, _analyze_with_openai_vision):
        result = fn(frame_paths, category, video_title)
        if result:
            return result

    return _infer_from_transcript(transcript, category, video_title)


def _analyze_with_zhipu(frame_paths: list[Path], category: str, title: str) -> str | None:
    """Analyze keyframes via 智谱 GLM-4V-Plus API."""
    import os, base64
    api_key = os.getenv("ZHIPU_API_KEY", "")
    if not api_key:
        return None

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url="https://open.bigmodel.cn/api/paas/v4/")

        content = [{"type": "text", "text": f"""请逐图分析这{len(frame_paths)}张来自竞品视频的关键帧画面：

视频: {title} | 品类: {category}

从以下维度分析（标注图1-图N）:
1. 构图: 产品怎么摆？画面元素？(居中/三分法/俯拍桌面/手持特写)
2. 灯光: 硬光柔光？主光方向？RGB氛围灯？色温？
3. 产品角度: 正面/侧面45°/俯拍/微距特写
4. 花字: 画面里的文字位置、颜色、风格
5. 调色: 高饱和/低饱和/暖色/冷色/电影感
直接输出，不要套话。"""}]

        for fp in frame_paths:
            with open(fp, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode("utf-8")
            content.append({"type": "image_url",
                           "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}})

        response = client.chat.completions.create(
            model="glm-4v-plus",
            messages=[{"role": "user", "content": content}],
            temperature=0.5, max_tokens=800,
        )
        text = response.choices[0].message.content.strip()
        logger.info(f"智谱 GLM-4V: {len(text)} chars")
        return text
    except Exception as e:
        logger.warning(f"智谱 Vision failed: {e}")
        return None


def _analyze_with_gemini(frame_paths: list[Path], category: str, title: str) -> str | None:
    """Analyze keyframes via Google Gemini Vision API."""
    import os
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        return None

    try:
        import urllib.request

        parts = []
        for i, fp in enumerate(frame_paths):
            with open(fp, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode("utf-8")
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": img_b64}})
            parts.append({"text": f"[图{i+1}]"})

        parts.append({"text": f"""请分析这{len(frame_paths)}张来自竞品视频的关键帧截图。

视频: {title} | 品类: {category}

从以下维度分析（每点1-2句，直接可用）:

1. 构图模式: 产品怎么摆放？(居中/三分法/对角线/俯拍桌面/手持特写) 画面元素有哪些？
2. 灯光打法: 硬光还是柔光？主光方向？有没有RGB氛围灯？色温偏冷还是偏暖？
3. 产品展示角度: 用了哪些拍摄角度？(正面/侧面45°/俯拍/微距特写/旋转)
4. 花字/文字叠加: 画面里有没有文字？什么位置？什么颜色风格？
5. 调色风格: 整体画面风格？(高饱和数码感/低饱和高级灰/暖色调/冷色调)
6. 特效与转场: 能看到什么后期效果？(关键帧动画/缩放/模糊/遮罩)

直接输出中文分析，不要套话。"""})

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
        body = {"contents": [{"parts": parts}]}
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            logger.info(f"Gemini Vision: {len(text)} chars")
            return text
    except Exception as e:
        logger.warning(f"Gemini Vision failed: {e}")
        return None


def _analyze_with_openai_vision(frame_paths: list[Path], category: str, title: str) -> str | None:
    """Analyze keyframes via OpenAI-compatible Vision API."""
    import os
    api_key = os.getenv("OPENAI_API_KEY", "") or os.getenv("VISION_API_KEY", "")
    base_url = os.getenv("VISION_BASE_URL", "") or os.getenv("OPENAI_BASE_URL", "")
    if not api_key:
        return None

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)

        content = [{"type": "text", "text": f"""请分析这{len(frame_paths)}张来自竞品视频的关键帧截图。

视频: {title} | 品类: {category}

分析维度（每点1-2句）:
1. 构图模式: 产品摆放方式、画面元素
2. 灯光: 硬光/柔光、主光方向、RGB氛围、色温
3. 产品角度: 正面/侧面/俯拍/微距/旋转展示
4. 花字: 文字位置、颜色、风格
5. 调色: 整体风格、饱和度、影调
6. 特效: 动画、转场效果

直接输出中文，不要套话。"""}]

        for fp in frame_paths:
            with open(fp, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode("utf-8")
            content.append({"type": "image_url",
                           "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}})

        response = client.chat.completions.create(
            model=os.getenv("VISION_MODEL", "gpt-4o"),
            messages=[{"role": "user", "content": content}],
            temperature=0.5, max_tokens=800,
        )
        text = response.choices[0].message.content.strip()
        logger.info(f"OpenAI Vision: {len(text)} chars")
        return text
    except Exception as e:
        logger.warning(f"OpenAI Vision failed: {e}")
        return None


def _infer_from_transcript(transcript: str, category: str, title: str) -> str | None:
    """Fallback: use text LLM to infer likely visual patterns from transcript."""
    if not transcript or len(transcript) < 50:
        return "（无足够数据）"
    try:
        from openai import OpenAI
        from rag_system.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
        client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": f"""根据口播内容推断这条{category}评测视频的拍摄手法:

{transcript[:1000]}

推断并输出（标注[推断]）:
1. 构图: 每段口播对应什么画面？
2. 灯光: {category}品类常见灯光方案
3. 剪辑: 根据信息密度推断的节奏
直接输出。"""}],
            temperature=0.5, max_tokens=400,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"（推断失败: {e}）"


def detect_transitions(video_path: Path) -> dict:
    """Detect transition types via ffprobe frame analysis."""
    if not video_path.exists():
        return {"error": "Video not found"}
    try:
        cmd = ["ffprobe", "-v", "quiet", "-show_frames", "-select_streams", "v:0",
               "-show_entries", "frame=pkt_pts_time,pict_type", "-of", "json", str(video_path)]
        result = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=30)
        if result.returncode != 0:
            return {"dominant": "hard_cut", "note": "标准硬切"}
        data = json.loads(result.stdout)
        frames = data.get("frames", [])
        if not frames:
            return {"dominant": "hard_cut"}
        i_frames = sum(1 for f in frames if f.get("pict_type") == "I")
        ratio = i_frames / len(frames) * 100 if frames else 0
        if ratio < 5:
            dominant = "长镜头为主"
        elif ratio < 15:
            dominant = "标准硬切节奏"
        else:
            dominant = "高频快切"
        return {"dominant": dominant, "i_frame_ratio": round(ratio, 1)}
    except Exception as e:
        return {"dominant": "hard_cut", "note": str(e)}
