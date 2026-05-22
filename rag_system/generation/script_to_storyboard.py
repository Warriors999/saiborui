"""定稿脚本 → 分镜表 + 自审 + 自动修复。

Pipeline:
  1. 读取定稿 .docx 脚本
  2. LLM 将定稿口播逐句拆分为镜头（不修改口播文字）
  3. 生成 .xlsx 分镜表
  4. 自审（内容质量 + 可拍性）
  5. 自动修复可拍性问题
  6. 重新自审直至通过
"""

import json
import re
from collections import Counter
from pathlib import Path

from openai import OpenAI

from rag_system.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from rag_system.generation.xlsx_formatter import format_storyboard_to_xlsx, _get_lighting_setup
from rag_system.generation.auditor import audit_storyboard, audit_shootability, _auto_fix_shots
from rag_system.utils import logger


SYSTEM_PROMPT = """你是专业短视频拍摄分镜师，擅长将口播脚本拆解为可执行的分镜表。

## 核心铁律

### 铁律A：产品绝对主体 — 商业产品视频标准 (Mercado 2022, 北电张会军2021)
- 景别分布：1宽:2中:3-4特写 (远景10-15% 中景25-30% 特写40-50% 微距5-10%)
- **人脸绝对禁止**。手部仅键盘/鼠标/手持场景(1-2镜)。越肩仅显示器场景

### 铁律B：运镜必须有动机 — 商业广告标准 (Apple/Manfrotto, 北电巩如梅2023)
- 固定30-40% / 滑轨推拉25-35% / 跟拍15-25% / 摇摄5-10%
- 运动动机：reveal→滑轨推 / 细节→摇摄扫表面 / 手部→跟拍 / 材质→微距静态

### 铁律D：一句话 = 一个画面（绝对铁律）
- 口播的每个句号/问号/感叹号 = 一个独立的镜头画面
- 念到什么，画面就展示什么；念完一句，切下一个画面
- 极短句(≤6字)且紧跟前句意思连贯 → 可合并到上一个镜头，最多合并一次
- 290字/分钟 = 4.8字/秒。每镜VO字数参考：
  2s≤10字 | 3s≤14字 | 4s≤19字 | 5s≤24字 | 6s≤29字 | 8s≤38字

### 铁律E：转场设计
- 不少于25%镜头有设计转场（动作匹配/遮挡转场/声音先入/叠化）
- 优先用动作匹配：手指右划→下镜产品从左入画
- 全程硬切=视觉疲劳

### 铁律F：音效和花字克制
- 音效15-25%（全片5-8处），描述具体（"金属敲击声"不是"转场音"）
- 花字20-30%，只在核心规格处标注
- 多数镜头音效和花字留空""

### 铁律G：备注说人话
- 给拍摄团队简短指令，≤15中文字
- ✅ "桌面铺黑布" "logo擦亮" "螺丝提前拧松"
- ❌ "采用深色背景以突出产品轮廓"

## 输出格式
返回包含 metadata 和 shots 的 JSON 对象。每镜字段：
- shot_number: 镜号
- act: 叙事幕（hook/problem/reveal/deep_dive/proof/summary/cta）
- jingbie: 景别（特写/近景/中景/中近景/全景/远景/大特写）
- yunjing: 运镜（固定/推/拉/摇/移/跟/升/降/环绕/POV/微距/产品360）
- jiandu: 拍摄角度（仰拍/俯拍/平视/前侧45°/左45°/右45°/越肩/POV）
- duration: 时长——2s/3s/4s/5s/6s/8s/10s（离散值，口播字数不能超过铁律D上限）
- transition: 转场方式（开场/动作匹配/遮挡转场/声音先入/相似图形匹配/运动方向一致/叠化/甩镜/闪白/硬切）
- visual: 画面描述（摄像机位、产品摆放、手部动作、道具、构图——给摄影师看）
- voiceover: 口播文案（从定稿逐句复制，一字不改。每镜必须有口播——A-roll画面+B-roll口播成对出现）
- huazi: 花字（只在核心规格处标注，多数留空""）
- audio: 音效（只在关键瞬间标注，多数留空""——描述必须具体如"金属敲击声""叮"）
- lighting: 灯光（关键镜标注，格式:"主灯:右前45°+柔光箱 | 辅灯:左侧补光 | 色温:5600K"）
- camera_setup: 机位（关键镜标注，格式:"机位:仰拍30° | 焦段:35mm | 光圈:F2.8"）
- notes: 备注（简短人话，≤15字，给拍摄团队用）

请直接返回JSON，不要markdown包裹。"""


def parse_docx_script(docx_path: Path) -> dict:
    """Extract script content from formatted .docx."""
    from docx import Document
    doc = Document(str(docx_path))

    lines = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    if not lines:
        raise ValueError("Empty docx")

    cover = lines[0]
    body_lines = []
    huazi_notes = []
    signature = ""

    for line in lines[1:]:
        if line.startswith("简介"):
            continue
        # Detect huazi annotations
        if "（花字：" in line:
            huazi_notes.append(line)
            body_lines.append(line)
        elif "我是" in line and "下期再见" in line:
            signature = line
        else:
            body_lines.append(line)

    full_script = "\n".join(body_lines)

    return {
        "cover": cover,
        "body": body_lines,
        "full_script": full_script,
        "huazi_notes": huazi_notes,
        "signature": signature,
    }


def _parse_and_repair_json(raw: str) -> dict | list:
    """Parse LLM JSON output with repair for common formatting errors."""
    import json as _json
    try:
        return _json.loads(raw)
    except _json.JSONDecodeError:
        pass

    # Repair attempt 1: objects missing commas between them in arrays
    # Fix pattern: }\s*\n\s*{ → },{
    repaired = re.sub(r'\}\s*\n\s*\{', '},\n    {', raw)
    # Fix pattern: "value"\s*\n\s*" → "value",\n    "
    repaired = re.sub(r'"\s*\n\s*\n\s*"', '",\n    "', repaired)
    # Fix trailing comma before ]
    repaired = re.sub(r',\s*\]', ']', repaired)
    # Fix trailing comma before }
    repaired = re.sub(r',\s*\}', '}', repaired)

    try:
        return _json.loads(repaired)
    except _json.JSONDecodeError:
        pass

    # Repair attempt 2: use regex to extract the shots array
    shots_match = re.search(r'"shots"\s*:\s*\[', raw)
    if shots_match:
        # Try to extract each shot object individually
        shot_objs = re.findall(r'\{[^{}]*"shot_number"[^{}]*\}', raw, re.DOTALL)
        if shot_objs:
            shots = []
            for so in shot_objs:
                try:
                    shots.append(_json.loads(so))
                except _json.JSONDecodeError:
                    continue
            if shots:
                md_match = re.search(r'"metadata"\s*:\s*(\{[^{}]*\})', raw, re.DOTALL)
                metadata = _json.loads(md_match.group(1)) if md_match else {}
                return {"metadata": metadata, "shots": shots}

    raise ValueError(f"Failed to parse JSON after repair. Raw length: {len(raw)}")


def generate_storyboard(script_data: dict, product_name: str, persona: str) -> dict:
    """Call LLM to break finalized script into shots."""
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

    user_prompt = f"""## 产品信息
产品名称：{product_name}
人设：{persona}

## 定稿口播文案（一字不改）
{script_data['full_script']}

## 要求
1. 将口播拆分为30-45个镜头（根据内容密度，不强行凑数）
2. 不修改口播文字，只添加画面、景别、运镜、转场、音效、灯光、机位
3. 每镜必须有口播——A-roll(画面)和B-roll(口播)成对出现。至少3镜标注灯光和机位
4. 转场多样化——不少于25%的镜头用动作匹配/遮挡转场/声音先入
5. 音效克制——只在产品亮相、数据弹出、材质特写、1处吐槽处使用
6. 返回包含 metadata 和 shots 的 JSON 对象"""

    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.75,
        max_tokens=8192,
    )

    raw = response.choices[0].message.content.strip()

    # Parse JSON
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

    parsed = _parse_and_repair_json(raw)

    # Handle both formats: flat array or {metadata, shots}
    if isinstance(parsed, list):
        shots = parsed
        metadata = {}
    elif isinstance(parsed, dict):
        shots = parsed.get("shots", [])
        metadata = parsed.get("metadata", {})
    else:
        raise ValueError(f"Expected JSON array or object, got {type(parsed)}")

    # Clean up — ensure all fields exist with sensible defaults
    for i, shot in enumerate(shots):
        shot.setdefault("shot_number", i + 1)
        shot.setdefault("act", "")
        shot.setdefault("jingbie", "中景")
        shot.setdefault("yunjing", "固定")
        shot.setdefault("jiandu", "")
        shot.setdefault("visual", "")
        shot.setdefault("duration", "3s")
        shot.setdefault("voiceover", "")
        shot.setdefault("huazi", "")
        shot.setdefault("audio", "")
        shot.setdefault("lighting", "")
        shot.setdefault("camera_setup", "")
        shot.setdefault("notes", "")
        # Transition: "开场" for first shot, "硬切" for rest
        if i == 0:
            shot.setdefault("transition", "开场")
        else:
            shot.setdefault("transition", "硬切")

    # Extract huazi from voiceover lines
    for shot in shots:
        vo = shot.get("voiceover", "")
        if "（花字：" in vo:
            m = re.search(r"（花字：([^）]+)）", vo)
            if m:
                shot["huazi"] = m.group(1)
                shot["voiceover"] = re.sub(r"（花字：[^）]+）", "", vo).strip()

    # Merge LLM metadata with defaults
    final_metadata = {
        "title": metadata.get("title") or script_data.get("cover", product_name),
        "hashtags": metadata.get("hashtags", ""),
        "total_duration": metadata.get("total_duration", f"{len(shots) * 3}s"),
    }

    return {"metadata": final_metadata, "shots": shots}


def _auto_trim_overuse(shots: list[dict]):
    """Post-process shots to meet restraint thresholds: huazi 20-35%, audio ≤30%, duration variety."""
    n = len(shots)

    # 1. Trim excess huazi — keep only the best ones (specs, price, tech terms)
    huazi_count = sum(1 for s in shots if s.get("huazi", "").strip())
    max_huazi = int(n * 0.30)  # 30% max
    if huazi_count > max_huazi:
        # Score huazi by keyword relevance (spec data, prices, comparisons)
        scored = []
        for i, s in enumerate(shots):
            hz = s.get("huazi", "").strip()
            if not hz:
                continue
            score = 0
            if any(c.isdigit() for c in hz): score += 3  # has numbers
            if any(kw in hz for kw in ["帧", "度", "W", "Hz", "mm", "kg", "芯", "卡"]): score += 2
            if any(kw in hz for kw in ["ROG", "Ultra", "RTX", "DLSS"]): score += 1
            if len(hz) > 30: score -= 1  # too verbose
            scored.append((i, score))
        scored.sort(key=lambda x: -x[1])
        to_keep = {i for i, _ in scored[:max_huazi]}
        for i, s in enumerate(shots):
            if s.get("huazi", "").strip() and i not in to_keep:
                s["huazi"] = ""
        logger.info(f"花字剪裁: {huazi_count} → {max_huazi}")

    # 2. Trim excess audio — keep best ones (specific foley, reveal, data pop sounds)
    audio_count = sum(1 for s in shots if s.get("audio", "").strip())
    max_audio = int(n * 0.22)  # 22% target
    if audio_count > max_audio:
        scored = []
        for i, s in enumerate(shots):
            au = s.get("audio", "").strip()
            if not au:
                continue
            score = 0
            if any(kw in au for kw in ["敲击", "摩擦", "咔", "叮", "碰撞", "刮"]): score += 3  # foley
            if any(kw in au for kw in ["升势", "落势", "确认"]): score += 2
            if "转场" in au or "氛围" in au or au in ("音效",): score -= 2  # generic = bad
            if len(au) < 3: score -= 2  # too short to be useful
            scored.append((i, score))
        scored.sort(key=lambda x: -x[1])
        to_keep = {i for i, _ in scored[:max_audio]}
        for i, s in enumerate(shots):
            if s.get("audio", "").strip() and i not in to_keep:
                s["audio"] = ""
        logger.info(f"音效剪裁: {audio_count} → {max_audio}")

    # 3. Ensure at least 2 long shots (≥6s) — extend reveal/product shots
    long_count = sum(1 for s in shots
                     if _parse_dur(s.get("duration", "")) >= 6)
    if long_count < 2:
        for s in shots:
            if _parse_dur(s.get("duration", "")) >= 6:
                continue
            act = s.get("act", "")
            if act in ("reveal", "deep_dive") and s.get("voiceover", "").strip():
                s["duration"] = "6s"
                long_count += 1
                if long_count >= 2:
                    break
    # Ensure at least 2 short shots (1-2s)
    short_count = sum(1 for s in shots
                      if _parse_dur(s.get("duration", "")) in (1, 2))
    if short_count < 2:
        for s in shots:
            dur = _parse_dur(s.get("duration", ""))
            if dur in (1, 2, 0):
                continue
            if s.get("act", "") in ("hook", "problem") and s.get("voiceover", "").strip():
                s["duration"] = "2s"
                short_count += 1
                if short_count >= 2:
                    break

    # 4. Ensure context-aware lighting AND camera_setup on ALL shots
    for s in shots:
        setup = _get_lighting_setup(s)
        if not s.get("lighting", "").strip():
            s["lighting"] = setup["key"]
            if setup.get("fill"):
                s["lighting"] += " | " + setup["fill"]
        if not s.get("camera_setup", "").strip():
            s["camera_setup"] = setup["camera"]


def _parse_dur(dur_str: str) -> int:
    try:
        return int(dur_str.replace("s", "").strip())
    except (ValueError, AttributeError):
        return 0


def _split_long_vo_shots(shots: list[dict]) -> list[dict]:
    """Apply the iron rule: one sentence = one shot.

    Each 。！？ in the voiceover creates a separate shot.
    Very short sentences (≤6 chars) that naturally continue the previous
    sentence are merged — but only once.
    """
    VO_LIMITS = {2: 10, 3: 14, 4: 19, 5: 24, 6: 29, 8: 38, 10: 48}
    new_shots = []

    for shot in shots:
        vo = shot.get("voiceover", "").strip()

        if not vo:
            new_shots.append(shot)
            continue

        # Split into sentences at 。！？
        raw_parts = re.split(r'(?<=[。！？\.\!\?])', vo)
        sentences = []
        for rp in raw_parts:
            rp = rp.strip()
            if not rp:
                continue
            # If a part doesn't end with punctuation, it's a fragment — append to last
            if not re.search(r'[。！？\.\!\?]$', rp) and sentences:
                sentences[-1] += rp
            else:
                sentences.append(rp)

        sentences = [s.strip() for s in sentences if s.strip()]
        if not sentences:
            new_shots.append(shot)
            continue

        # Merge very short sentences (≤6 chars) with the next one
        merged = []
        skip_next = False
        for i, s in enumerate(sentences):
            if skip_next:
                skip_next = False
                continue
            if len(s) <= 6 and i + 1 < len(sentences):
                merged.append(s + sentences[i + 1])
                skip_next = True
            else:
                merged.append(s)

        if not merged:
            new_shots.append(shot)
            continue

        # Assign each sentence to its own shot
        for si, sentence in enumerate(merged):
            if si == 0:
                # Update original shot with first sentence
                shot["voiceover"] = sentence
                shot["transition"] = shot.get("transition", "硬切")
                # Assign duration based on VO length
                for d, limit in sorted(VO_LIMITS.items()):
                    if len(sentence) <= limit:
                        shot["duration"] = f"{d}s"
                        break
                new_shots.append(shot)
            else:
                # Clone shot for subsequent sentences
                new_shot = dict(shot)
                new_shot["voiceover"] = sentence
                new_shot["huazi"] = ""
                new_shot["audio"] = ""
                new_shot["transition"] = "声音先入"
                new_shot["notes"] = ""
                for d, limit in sorted(VO_LIMITS.items()):
                    if len(sentence) <= limit:
                        new_shot["duration"] = f"{d}s"
                        break
                new_shots.append(new_shot)

    for i, s in enumerate(new_shots):
        s["shot_number"] = i + 1

    split_count = len(new_shots) - len(shots)
    if split_count > 0:
        logger.info(f"分句拆分: {len(shots)}镜 → {len(new_shots)}镜 (+{split_count}镜, 一句话=一个画面)")
    return new_shots


def storyboard_pipeline(docx_path: Path, product_name: str, persona: str = "折腾到吐") -> Path:
    """Full pipeline: script → storyboard → audit → fix → save."""
    output_dir = Path("output/storyboards")
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = product_name.replace("/", "-").replace(":", "-")
    xlsx_path = output_dir / f"{safe_name}-{persona}-分镜表.xlsx"

    # Step 1: Parse script
    logger.info(f"读取定稿脚本: {docx_path}")
    script_data = parse_docx_script(docx_path)
    logger.info(f"口播行数: {len(script_data['body'])}, 总字数: {len(script_data['full_script'])}")

    # Step 2: Generate storyboard
    logger.info("生成分镜表...")
    storyboard = generate_storyboard(script_data, product_name, persona)

    shot_count = len(storyboard.get("shots", []))
    total_vo = sum(len(s.get("voiceover", "")) for s in storyboard["shots"])
    logger.info(f"生成 {shot_count} 镜, 口播总字数: {total_vo}")

    # Step 2.5: Split shots with excessive VO (3+ sentences in one shot)
    shots = storyboard["shots"]
    shots = _split_long_vo_shots(shots)
    # Auto-trim overuse (huazi, audio, duration distribution)
    _auto_trim_overuse(shots)
    storyboard["shots"] = shots

    # Step 3: Audit — content quality
    logger.info("自审 (内容质量)...")
    audit_result = audit_storyboard(storyboard, key_points="")
    passed_count = sum(1 for c in audit_result.checks if c["passed"])
    total_checks = len(audit_result.checks)
    logger.info(f"内容审核: {passed_count}/{total_checks} 通过")

    # Step 4: Audit — shootability
    logger.info("自审 (可拍性)...")
    shootability = audit_shootability(storyboard)
    filmable = sum(1 for s in shootability.get("shot_checks", []) if s.get("filmable", True))
    unfilmable = len(shootability.get("shot_checks", [])) - filmable
    logger.info(f"可拍性检查: {filmable} 可拍, {unfilmable} 不可拍")

    # Step 5: Auto-fix unfilmable shots
    if unfilmable > 0 or shootability.get("transition_issues"):
        logger.info("自动修复不可拍镜头...")
        storyboard["shots"] = _auto_fix_shots(
            storyboard["shots"],
            shootability.get("shot_checks", []),
        )

        # Re-audit after fix
        logger.info("修复后重新自审...")
        shootability = audit_shootability(storyboard)
        filmable = sum(1 for s in shootability.get("shot_checks", []) if s.get("filmable", True))
        unfilmable = len(shootability.get("shot_checks", [])) - filmable
        logger.info(f"修复后可拍性: {filmable} 可拍, {unfilmable} 不可拍")

    # Step 6: Save (use timestamp to avoid file lock)
    import time as _time
    safe_path = xlsx_path.parent / f"{xlsx_path.stem}_{int(_time.time()) % 100000}.xlsx"
    format_storyboard_to_xlsx(
        storyboard=storyboard,
        product_name=product_name,
        persona=persona,
        output_path=safe_path,
    )
    logger.info(f"分镜表已保存: {xlsx_path}")

    # Step 7: Print summary
    shots = storyboard["shots"]
    jingbies = Counter(s.get("jingbie", "") for s in shots)
    yunjings = Counter(s.get("yunjing", "") for s in shots)
    huazi_shots = sum(1 for s in shots if s.get("huazi", "").strip())
    audio_shots = sum(1 for s in shots if s.get("audio", "").strip())
    trans_shots = sum(1 for s in shots if s.get("transition", "") not in ("硬切", "开场", ""))
    light_shots = sum(1 for s in shots if s.get("lighting", "").strip())
    cam_shots = sum(1 for s in shots if s.get("camera_setup", "").strip())
    pure_vis = sum(1 for s in shots if not s.get("voiceover", "").strip())

    print(f"\n{'='*60}")
    print(f"分镜表: {product_name} — {persona}")
    print(f"{'='*60}")
    print(f"  总镜数: {len(shots)}  |  口播: {total_vo}字  |  转场: {trans_shots}镜")
    print(f"  花字: {huazi_shots}镜  |  音效: {audio_shots}镜  |  设计转场: {trans_shots}镜")
    print(f"  灯光: {light_shots}镜  |  机位: {cam_shots}镜")
    print(f"  内容审核: {passed_count}/{total_checks}  |  可拍性: {filmable}/{len(shots)}")
    print(f"  景别: {dict(jingbies.most_common())}")
    print(f"  运镜: {dict(yunjings.most_common(8))}")
    print(f"  文件: {xlsx_path}")
    print(f"{'='*60}")

    return xlsx_path


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python script_to_storyboard.py <docx_path> [product_name] [persona]")
        sys.exit(1)

    docx_path = Path(sys.argv[1])
    product = sys.argv[2] if len(sys.argv) > 2 else docx_path.stem
    persona = sys.argv[3] if len(sys.argv) > 3 else "折腾到吐"

    storyboard_pipeline(docx_path, product, persona)
