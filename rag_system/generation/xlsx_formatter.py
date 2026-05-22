"""Format storyboard JSON into a professionally styled .xlsx file.

9-column layout optimized for A4 landscape print:
  A:镜号 B:景别·运镜 C:画面描述 D:口播文案 E:时长 F:花字/特效 G:音效/声画 H:灯光/机位 I:备注

Design: Swiss Modernism + Executive Dashboard
  Deep blue #1E40AF header | White + #DBEAFE alternating rows | Slate borders
  Microsoft YaHei 10pt body | 9pt secondary | 12pt title
"""

import math
import re as _re
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# ── Design System Colors ──
PRIMARY = "1E40AF"
PRIMARY_LIGHT = "DBEAFE"
BACKGROUND = "FFFFFF"
SURFACE = "F8FAFC"
BORDER_COLOR = "CBD5E1"
TEXT_PRIMARY = "1E293B"
TEXT_SECONDARY = "64748B"
TEXT_HEADER = "FFFFFF"


def format_storyboard_to_xlsx(
    storyboard: dict,
    product_name: str,
    persona: str,
    output_path: Path,
) -> Path:
    """Convert storyboard JSON to a professionally formatted .xlsx file."""
    wb = Workbook()
    ws = wb.active
    ws.title = "分镜脚本"

    metadata = storyboard.get("metadata", {})
    shots = storyboard.get("shots", [])

    # ── Column Widths (9 columns, A4 landscape) ──
    col_widths = {
        "A": 5.0,   # 镜号
        "B": 9.0,   # 景别·运镜
        "C": 38,    # 画面描述
        "D": 48,    # 口播文案
        "E": 5.0,   # 时长
        "F": 17,    # 花字/特效
        "G": 16,    # 音效/声画
        "H": 28,    # 灯光/机位/光比
        "I": 20,    # 备注
    }
    for col_letter, width in col_widths.items():
        ws.column_dimensions[col_letter].width = width

    # ── Typography ──
    font_title = Font(name="微软雅黑", size=12, bold=True, color=TEXT_PRIMARY)
    font_title_header = Font(name="微软雅黑", size=12, bold=True, color=TEXT_HEADER)
    font_label_accent = Font(name="微软雅黑", size=10, bold=True, color=PRIMARY)
    font_body = Font(name="微软雅黑", size=10, color=TEXT_PRIMARY)
    font_body_bold = Font(name="微软雅黑", size=10, bold=True, color=TEXT_PRIMARY)
    font_small = Font(name="微软雅黑", size=9, color=TEXT_SECONDARY)
    font_col_header = Font(name="微软雅黑", size=10, bold=True, color=TEXT_HEADER)
    font_shot_number = Font(name="微软雅黑", size=10, bold=True, color=PRIMARY)
    font_framing = Font(name="微软雅黑", size=10, color=TEXT_PRIMARY)

    # ── Fills ──
    fill_header = PatternFill("solid", fgColor=PRIMARY)
    fill_alt_row = PatternFill("solid", fgColor=PRIMARY_LIGHT)
    fill_white = PatternFill("solid", fgColor=BACKGROUND)
    fill_metadata_bg = PatternFill("solid", fgColor=SURFACE)

    # ── Borders ──
    thin_side = Side(style="thin", color=BORDER_COLOR)
    border_all_thin = Border(
        left=thin_side, right=thin_side, top=thin_side, bottom=thin_side,
    )
    border_bottom_thick = Border(
        left=thin_side, right=thin_side, top=thin_side,
        bottom=Side(style="medium", color=PRIMARY),
    )

    # ── Alignments ──
    align_center = Alignment(horizontal="center", vertical="center")
    align_center_wrap = Alignment(horizontal="center", vertical="top", wrap_text=True)
    align_left_wrap = Alignment(horizontal="left", vertical="top", wrap_text=True)
    align_left_center = Alignment(horizontal="left", vertical="center")

    # ═══════════════════════════════════════════
    # METADATA HEADER (Rows 1-7)
    # ═══════════════════════════════════════════
    meta_rows = [
        (1, "分镜脚本", None, font_title, 32, True),
        (2, "达人名称", persona, font_body, 24, False),
        (3, "标题", metadata.get("title", product_name), font_body_bold, 26, False),
        (4, "必带话题", metadata.get("hashtags", ""), font_small, 22, False),
        (5, "内容方向", f"测评+种草          |          视频总时长：{metadata.get('total_duration', '60-90s')}", font_body, 22, False),
        (6, "封面文案", metadata.get("title", product_name), font_small, 22, False),
        (7, "拍摄版式", "16:9 横版视频", font_body, 22, False),
    ]

    for row_num, label, value, val_font, row_height, is_title in meta_rows:
        ws.row_dimensions[row_num].height = row_height
        if is_title:
            ws.merge_cells(f"A{row_num}:I{row_num}")
            cell_label = ws.cell(row=row_num, column=1, value=label)
            cell_label.font = font_title_header
            cell_label.alignment = align_center
            cell_label.fill = fill_header
        else:
            ws.merge_cells(f"A{row_num}:B{row_num}")
            cell_label = ws.cell(row=row_num, column=1, value=f"{label}：")
            cell_label.font = font_label_accent
            cell_label.alignment = Alignment(horizontal="right", vertical="center")
            cell_label.fill = fill_metadata_bg
            ws.merge_cells(f"C{row_num}:I{row_num}")
            cell_val = ws.cell(row=row_num, column=3, value=value)
            cell_val.font = val_font
            cell_val.alignment = align_left_center
            cell_val.fill = fill_metadata_bg

    # Row 8: Separator
    ws.row_dimensions[8].height = 8

    # ═══════════════════════════════════════════
    # COLUMN HEADERS (Row 9)
    # ═══════════════════════════════════════════
    col_headers = [
        "镜号", "景别·运镜", "画面描述", "口播文案", "时长",
        "花字/特效", "音效/声画", "灯光/机位", "备注",
    ]
    ws.row_dimensions[9].height = 28
    for ci, header_text in enumerate(col_headers, 1):
        cell = ws.cell(row=9, column=ci, value=header_text)
        cell.font = font_col_header
        cell.fill = fill_header
        cell.alignment = align_center
        cell.border = border_all_thin

    # ═══════════════════════════════════════════
    # SHOT DATA ROWS (Row 10+)
    # ═══════════════════════════════════════════
    for ri, shot in enumerate(shots):
        row_num = 10 + ri
        is_alt = ri % 2 == 1
        row_fill = fill_alt_row if is_alt else fill_white

        # ── Build each column ──
        shot_num = str(shot.get("shot_number", ri + 1))

        # B: 景别·运镜 (with transition prefix)
        jingbie = shot.get("jingbie", "")
        yunjing = shot.get("yunjing", "")
        transition = shot.get("transition", "")
        framing = " | ".join(p for p in [jingbie, yunjing] if p) or "-"
        if transition and transition not in ("硬切", "开场", ""):
            framing = f"[转场:{transition}] {framing}"

        # C: 画面描述 — pure visual, no camera prefixes
        visual = shot.get("visual", "")

        # D: 口播
        voiceover = shot.get("voiceover", "")

        # E: 时长
        duration = shot.get("duration", "")

        # F: 花字
        huazi = shot.get("huazi", "")

        # G: 音效
        audio = shot.get("audio", "")

        # H: 灯光/机位/光比
        lighting = shot.get("lighting", "")
        camera_setup = shot.get("camera_setup", "")
        light_ratio = _get_light_ratio(shot)
        light_parts = []
        if lighting:
            light_parts.append(lighting)
        if camera_setup:
            light_parts.append(camera_setup)
        # Always include light ratio
        light_parts.append(f"光比: 主:辅≈{light_ratio}")
        light_cam = "\n".join(light_parts)

        # I: 备注 — simple, actionable, ≤20 chars
        notes = shot.get("notes", "")
        notes = _re.sub(r'\[幕:[^\]]+\]', '', notes)
        notes = _re.sub(r'\[转场:[^\]]+\]', '', notes).strip()
        if len(notes) > 20:
            notes = notes[:18] + "…"

        data = [shot_num, framing, visual, voiceover, duration, huazi, audio, light_cam, notes]

        # ── Calculate row height (column-aware) ──
        col_chars_per_line = {
            2: 4.5,   # B: ~4.5 Chinese chars/line at width 9
            3: 19,    # C: ~19 at width 38
            4: 24,    # D: ~24 at width 48
            6: 8.5,   # F: ~8.5 at width 17
            7: 8,     # G: ~8 at width 16
            8: 14,    # H: ~14 at width 28
            9: 10,    # I: ~10 at width 20
        }
        max_lines = 1
        for ci, val in enumerate(data):
            if ci + 1 in col_chars_per_line and val:
                lines_needed = max(1, len(str(val)) / col_chars_per_line[ci + 1])
                max_lines = max(max_lines, lines_needed)
        ws.row_dimensions[row_num].height = max(28, min(140, int(max_lines * 18 + 6)))

        # ── Write cells ──
        for ci, value in enumerate(data, 1):
            cell = ws.cell(row=row_num, column=ci, value=value)
            cell.fill = row_fill

            if ci == 1:  # 镜号
                cell.font = font_shot_number
                cell.alignment = align_center
            elif ci == 2:  # 景别·运镜
                cell.font = font_framing
                cell.alignment = align_center_wrap
            elif ci == 5:  # 时长
                cell.font = font_body
                cell.alignment = align_center_wrap
            elif ci in (6, 7):  # 花字, 音效
                cell.font = font_small
                cell.alignment = align_left_wrap
            elif ci in (8, 9):  # 灯光/机位, 备注
                cell.font = font_small
                cell.alignment = align_left_wrap
            else:  # 画面描述, 口播
                cell.font = font_body
                cell.alignment = align_left_wrap

            if ri == len(shots) - 1:
                cell.border = border_bottom_thick
            else:
                cell.border = border_all_thin

    # ═══════════════════════════════════════════
    # FINAL TOUCHES — Main Sheet
    # ═══════════════════════════════════════════
    ws.sheet_properties.pageSetUpPr = None
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.auto_filter.ref = f"A9:I{9 + len(shots)}"
    ws.freeze_panes = "A10"

    # ═══════════════════════════════════════════
    # LIGHTING DIAGRAM SHEET — per-shot top-down
    # ═══════════════════════════════════════════
    _create_lighting_diagram_sheet(wb, shots, product_name, output_path)

    wb.save(str(output_path))
    return output_path


def _get_lighting_setup(shot: dict) -> dict:
    """Return minimal lighting setup: key angle, fill (optional), ratio.

    Only 1-2 lights. Variation comes from key angle and ratio, not gear list.
    """
    act = shot.get("act", "")
    jingbie = shot.get("jingbie", "")
    visual = shot.get("visual", "")

    # ── Key light angle varies by shot context ──
    if act == "hook":
        key_angle, ratio, fill = "右前60°", "3:1", "辅光:左侧反光板弱补"
    elif act == "reveal":
        key_angle, ratio, fill = "右前45°", "3:1~4:1", "辅光:左侧补光"
    elif act == "deep_dive" and jingbie in ("特写", "大特写"):
        key_angle, ratio, fill = "正前15°", "2:1", "辅光:底部反光板"
    elif act == "proof":
        key_angle, ratio, fill = "正前10°", "2:1", "辅光:左侧反光板"
    elif act == "cta":
        key_angle, ratio, fill = "右前35°", "2:1~3:1", "辅光:左侧补光"
    elif any(kw in visual for kw in ["俯拍", "顶部", "顶置"]):
        key_angle, ratio, fill = "顶部垂直", "2:1", ""  # single light
    elif any(kw in visual for kw in ["手持", "手部", "POV"]):
        key_angle, ratio, fill = "右前30°", "2:1", ""
    elif any(kw in visual for kw in ["360", "环绕"]):
        key_angle, ratio, fill = "右前45°", "2:1~3:1", "辅光:左后45°"
    elif act == "deep_dive":
        key_angle, ratio, fill = "右前40°", "2:1~3:1", "辅光:左侧补光"
    else:
        key_angle, ratio, fill = "右前40°", "2:1", "辅光:左侧补光"

    return {
        "ratio": ratio,
        "key_angle": key_angle,
        "fill": fill,
        "key": f"主光:{key_angle}+柔光箱 | 色温:5600K",
        "camera": "机位:正面 | 焦段:50mm | 光圈:F2.8",
    }


def _get_light_ratio(shot: dict) -> str:
    return _get_lighting_setup(shot)["ratio"]


def _create_lighting_diagram_sheet(wb: Workbook, shots: list[dict], product_name: str, output_path: Path):
    """Create '灯光机位图' sheet with a single combined PNG strip of all lighting diagrams.

    All diagrams are drawn into one tall PNG using Pillow, then embedded as a single image.
    One image = zero overlap/alignment issues.
    """
    from PIL import Image as PILImage, ImageDraw, ImageFont
    from openpyxl.drawing.image import Image as XLImage

    # ── Group shots by lighting setup ──
    groups = {}
    for si, shot in enumerate(shots):
        lt = shot.get("lighting", "").strip()
        cam = shot.get("camera_setup", "").strip()
        ratio = _get_light_ratio(shot)
        key = (lt, cam, ratio)
        if key not in groups:
            groups[key] = []
        groups[key].append(shot.get("shot_number", si + 1))

    n_groups = len(groups)
    if n_groups == 0:
        return

    # ── Font setup ──
    try:
        font_title = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 14)
        font_label = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 11)
        font_note = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 9)
    except (OSError, IOError):
        font_title = font_label = font_note = ImageFont.load_default()

    # ── Diagram dimensions ──
    DW, DH = 520, 420  # single diagram size
    STRIP_W = DW
    STRIP_H = DH * n_groups + 60  # all diagrams stacked + title

    strip = PILImage.new("RGB", (STRIP_W, STRIP_H), "#FFFFFF")
    draw = ImageDraw.Draw(strip)

    # ── Title ──
    draw.text((20, 12), f"灯光机位俯视图 — {product_name}", fill="#1E40AF", font=font_title)
    draw.line([(20, 36), (STRIP_W - 20, 36)], fill="#CBD5E1", width=1)

    # ── Draw each diagram per professional cinematography standard ──
    # Standard: 俯视横切面, 光轴基准, 角度标注, max 2 lights
    for gi, ((lt, cam, ratio), shot_nums) in enumerate(groups.items()):
        label = f"灯位{chr(65+gi)}"
        # Get the representative shot's lighting setup
        ref_shot = shots[shot_nums[0]-1] if shot_nums else {}
        setup = _get_lighting_setup(ref_shot)
        technique = _derive_technique(shots[shot_nums[0]-1]) if shot_nums else ""
        off_y = 48 + gi * DH  # y offset for this diagram

        # Diagram border
        draw.rectangle([10, off_y, DW - 10, off_y + DH - 10], outline="#D1D5DB", width=1)

        # Header bar
        draw.rectangle([10, off_y, DW - 10, off_y + 30], fill="#1E40AF")
        shot_ref = ", ".join(str(n) for n in shot_nums[:6])
        header = f"{label} — 镜号: {shot_ref} — 光比: 主:辅 ≈ {ratio}"
        draw.text((DW//2, off_y + 15), header, fill="#FFFFFF", font=font_label, anchor="mm")

        # === 光轴 (Optical Axis) — 中心虚线 ===
        axis_x = DW // 2
        axis_top = off_y + 60
        axis_bot = off_y + DH - 50
        for seg in range(axis_top, axis_bot, 12):
            draw.line([axis_x, seg, axis_x, min(seg + 6, axis_bot)], fill="#9CA3AF", width=1)
        draw.text((axis_x + 8, axis_top + 5), "光轴", fill="#9CA3AF", font=font_note)

        # === 被摄主体 (Subject) — 中央 ===
        sx, sy, sw, sh = axis_x - 45, off_y + 145, 90, 70
        draw.rectangle([sx, sy, sx + sw, sy + sh], fill="#F1F5F9", outline="#374151", width=2)
        draw.text((axis_x, sy + 22), "产品", fill="#1E293B", font=font_label, anchor="mm")
        draw.text((axis_x, sy + 44), "(桌面摆放)", fill="#9CA3AF", font=font_note, anchor="mm")
        # Front direction arrow (toward camera = down)
        draw.line([axis_x, sy + sh, axis_x, sy + sh + 25], fill="#DC2626", width=2)
        draw.polygon([axis_x - 4, sy + sh + 20, axis_x + 4, sy + sh + 20, axis_x, sy + sh + 28], fill="#DC2626")
        draw.text((axis_x + 15, sy + sh + 15), "正面", fill="#DC2626", font=font_note)

        # === 摄影机位 (Camera) — 6点钟方向 ===
        cam_y = off_y + DH - 75
        draw.ellipse([axis_x - 18, cam_y - 18, axis_x + 18, cam_y + 18], fill="#F0FDF4", outline="#16A34A", width=2)
        draw.text((axis_x, cam_y), "机位", fill="#15803D", font=font_note, anchor="mm")
        cam_label = cam[:22] if cam else "50mm F2.8"
        draw.text((axis_x, cam_y + 22), cam_label, fill="#64748B", font=font_note, anchor="mm")

        # === 主光 (Key Light) — position varies by shot ===
        key_angle = setup.get("key_angle", "右前40°")
        kx, ky = axis_x + 210, off_y + 80
        draw.ellipse([kx - 18, ky - 18, kx + 18, ky + 18], fill="#EFF6FF", outline="#1E40AF", width=2)
        draw.text((kx, ky - 2), "主光", fill="#1E40AF", font=font_note, anchor="mm")
        draw.text((kx, ky + 14), f"{key_angle} 5600K", fill="#64748B", font=font_note, anchor="mm")
        draw.line([kx - 16, ky + 4, sx + sw, sy + 20], fill="#1E40AF", width=2)
        draw.text((axis_x + 55, sy - 55), key_angle, fill="#1E40AF", font=font_note)

        # === 辅光 (Fill Light) — 左侧, 只在有辅光时绘制 ===
        flx, fly = axis_x - 220, off_y + (200 if setup.get("fill") else 210)
        if setup.get("fill"):
            draw.ellipse([flx - 16, fly - 16, flx + 16, fly + 16], fill="#F8FAFC", outline="#64748B", width=2)
            draw.text((flx, fly - 2), "辅光", fill="#475569", font=font_note, anchor="mm")
            draw.text((flx, fly + 16), "补光", fill="#94A3B8", font=font_note, anchor="mm")
            draw.line([flx + 16, fly, sx, sy + 35], fill="#64748B", width=2)
        else:
            draw.text((axis_x - 210, off_y + 195), "单灯", fill="#94A3B8", font=font_note, anchor="mm")

        # === 光比标注 (Ratio Box) ===
        rx, ry = DW - 200, off_y + DH - 40
        draw.rectangle([rx, ry, rx + 185, ry + 28], fill="#F8FAFC", outline="#D1D5DB", width=1)
        draw.text((rx + 92, ry + 14), f"光比 主:辅 = {ratio}", fill="#1E40AF", font=font_label, anchor="mm")

        # === 拍摄手法 (Technique) ===
        draw.text((10 + 140, off_y + DH - 26), technique, fill="#6B7280", font=font_note, anchor="mm")

    # ── Save combined PNG ──
    png_dir = output_path.parent / f"{output_path.stem}_lighting"
    png_dir.mkdir(parents=True, exist_ok=True)
    png_path = png_dir / f"lighting_all.png"
    strip.save(str(png_path), "PNG")

    # ── Create sheet and embed single image ──
    ws = wb.create_sheet("灯光机位图")
    ws.column_dimensions["A"].width = 76  # ~530px at 7px/unit
    ws.row_dimensions[1].height = int(STRIP_H * 0.75)  # pt ≈ px * 0.75

    img = XLImage(str(png_path))
    img.width = STRIP_W
    img.height = STRIP_H
    ws.add_image(img, "A1")

    ws.sheet_properties.pageSetUpPr = None
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0


def _generate_lighting_svg(svg_path: Path, label: str, ratio: str, lighting: str, camera: str, technique: str, shot_nums: list, product_name: str = ""):
    """Generate a clean top-down lighting diagram SVG — professional studio layout."""
    cam_short = camera.replace("机位:", "").replace("机位：", "")[:25] if camera else "50mm F2.8"
    shot_list = ", ".join(str(n) for n in shot_nums[:8])

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 500 460">
  <defs>
    <marker id="aK" markerWidth="7" markerHeight="5" refX="7" refY="2.5" orient="auto">
      <polygon points="0 0, 7 2.5, 0 5" fill="#1e40af"/>
    </marker>
    <marker id="aF" markerWidth="7" markerHeight="5" refX="7" refY="2.5" orient="auto">
      <polygon points="0 0, 7 2.5, 0 5" fill="#64748b"/>
    </marker>
    <marker id="aC" markerWidth="7" markerHeight="5" refX="7" refY="2.5" orient="auto">
      <polygon points="0 0, 7 2.5, 0 5" fill="#16a34a"/>
    </marker>
    <marker id="aR" markerWidth="7" markerHeight="5" refX="7" refY="2.5" orient="auto">
      <polygon points="0 0, 7 2.5, 0 5" fill="#dc2626"/>
    </marker>
    <style>
      text {{ font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif; }}
      .title {{ font-size:13px; font-weight:bold; fill:#1e293b; }}
      .label {{ font-size:10px; font-weight:bold; fill:#1e293b; }}
      .note {{ font-size:8px; fill:#64748b; }}
      .ratio {{ font-size:11px; font-weight:bold; fill:#1e40af; }}
    </style>
  </defs>

  <rect width="500" height="460" fill="#ffffff"/>

  <!-- Title -->
  <text x="250" y="22" class="title" text-anchor="middle">{label} — {product_name}</text>
  <text x="250" y="40" class="note" text-anchor="middle">镜号: {shot_list}  |  光比 主:辅 ≈ {ratio}</text>
  <line x1="30" y1="50" x2="470" y2="50" stroke="#e2e8f0" stroke-width="1"/>

  <!-- === Product center === -->
  <rect x="200" y="160" width="100" height="80" rx="4" fill="#f8fafc" stroke="#334155" stroke-width="2"/>
  <text x="250" y="196" class="label" text-anchor="middle">产品</text>
  <text x="250" y="214" class="note" text-anchor="middle">桌面摆放</text>
  <!-- Product front arrow (down = facing camera) -->
  <line x1="250" y1="240" x2="250" y2="275" stroke="#dc2626" stroke-width="2" marker-end="url(#aR)"/>

  <!-- === Camera (bottom) === -->
  <circle cx="250" cy="380" r="16" fill="#f0fdf4" stroke="#16a34a" stroke-width="2"/>
  <text x="250" y="376" class="label" text-anchor="middle" fill="#15803d">机位</text>
  <text x="250" y="406" class="note" text-anchor="middle">{cam_short}</text>
  <!-- Camera → product (lens direction) -->
  <line x1="250" y1="364" x2="250" y2="285" stroke="#16a34a" stroke-width="1.5" marker-end="url(#aC)"/>
  <!-- FOV cone -->
  <line x1="250" y1="364" x2="200" y2="240" stroke="#16a34a" stroke-width="0.8" stroke-dasharray="3,3" opacity="0.4"/>
  <line x1="250" y1="364" x2="300" y2="240" stroke="#16a34a" stroke-width="0.8" stroke-dasharray="3,3" opacity="0.4"/>

  <!-- === Key Light (top-right) === -->
  <circle cx="420" cy="110" r="18" fill="#eff6ff" stroke="#1e40af" stroke-width="1.5"/>
  <text x="420" y="105" fill="#1e40af" font-size="10" font-weight="bold" text-anchor="middle">主灯</text>
  <text x="420" y="122" class="note" text-anchor="middle">柔光箱</text>
  <text x="420" y="134" class="note" text-anchor="middle">5600K</text>
  <!-- Key → product -->
  <line x1="404" y1="120" x2="295" y2="178" stroke="#1e40af" stroke-width="1.5" marker-end="url(#aK)"/>
  <text x="360" y="142" fill="#1e40af" font-size="8">45°右前</text>

  <!-- === Fill Light (left) === -->
  <circle cx="70" cy="200" r="16" fill="#f8fafc" stroke="#64748b" stroke-width="1.5"/>
  <text x="70" y="196" fill="#475569" font-size="10" font-weight="bold" text-anchor="middle">辅灯</text>
  <text x="70" y="214" class="note" text-anchor="middle">左侧补光</text>
  <!-- Fill → product -->
  <line x1="86" y1="200" x2="200" y2="200" stroke="#64748b" stroke-width="1.5" marker-end="url(#aF)"/>

  <!-- Camera-subject axis (dashed center line) -->
  <line x1="250" y1="240" x2="250" y2="364" stroke="#cbd5e1" stroke-width="0.8" stroke-dasharray="4,4"/>

  <!-- === Light Ratio Box (bottom-left) === -->
  <rect x="25" y="418" width="180" height="30" rx="4" fill="#f8fafc" stroke="#cbd5e1" stroke-width="1"/>
  <text x="115" y="437" class="ratio" text-anchor="middle">光比  主灯 : 辅灯 = {ratio}</text>

  <!-- === Technique (bottom-right) === -->
  <rect x="220" y="418" width="255" height="30" rx="4" fill="#f8fafc" stroke="#cbd5e1" stroke-width="1"/>
  <text x="348" y="437" class="note" text-anchor="middle">{technique}</text>
</svg>'''

    svg_path.write_text(svg, encoding="utf-8")


def _derive_technique(shot: dict) -> str:
    """Derive professional shooting technique note from shot data. Not fabricated."""
    yunjing = shot.get("yunjing", "")
    jingbie = shot.get("jingbie", "")
    jiandu = shot.get("jiandu", "")
    visual = shot.get("visual", "")

    techniques = []

    # Camera movement technique
    if "推" in yunjing:
        techniques.append("滑轨缓推")
    elif "拉" in yunjing:
        techniques.append("滑轨缓拉")
    elif "摇" in yunjing:
        techniques.append("云台匀速摇摄")
    elif "移" in yunjing:
        techniques.append("滑轨横移跟焦")
    elif "跟" in yunjing:
        techniques.append("手持稳定器跟焦")
    elif "升" in yunjing or "降" in yunjing:
        techniques.append("电动滑轨升降")
    elif "环绕" in yunjing:
        techniques.append("电动转盘或手动环绕")
    elif "微距" in yunjing:
        techniques.append("微距镜头+手动对焦")
    elif "POV" in yunjing:
        techniques.append("头戴或手持POV")
    elif "固定" in yunjing:
        techniques.append("三脚架锁定云台")

    # Angle technique
    if "仰拍" in jiandu:
        techniques.append("低机位仰角")
    elif "俯拍" in jiandu:
        techniques.append("高机位俯角/顶置")
    elif "越肩" in jiandu:
        techniques.append("肩后机位")

    # Shot type technique
    if "特写" in jingbie:
        if "大特写" in jingbie:
            techniques.append("微距镜头")
        else:
            techniques.append("长焦端压缩景深")

    if not techniques:
        techniques.append("标准机位")

    return " | ".join(techniques[:2])
