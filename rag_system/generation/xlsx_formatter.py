"""Format storyboard JSON into a professionally styled .xlsx file.

9-column layout optimized for A4 landscape print:
  A:镜号 B:景别·运镜 C:画面描述 D:口播文案 E:时长 F:花字/特效 G:音效/声画 H:灯光/机位 I:备注

Design: Swiss Modernism + Executive Dashboard
  Deep blue #1E40AF header | White + #DBEAFE alternating rows | Slate borders
  Microsoft YaHei 10pt body | 9pt secondary | 12pt title
"""

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


def _get_light_ratio(shot: dict) -> str:
    """Assign proper light ratio based on shot type/act."""
    act = shot.get("act", "")
    jingbie = shot.get("jingbie", "")
    visual = shot.get("visual", "")
    vo = shot.get("voiceover", "")

    # reveal / product debut → dramatic, high contrast
    if act == "reveal":
        return "3:1~4:1"
    # deep_dive close-up → soft, clear detail
    if act == "deep_dive" and jingbie in ("特写", "大特写"):
        return "2:1"
    # hook / opening → dramatic punch
    if act == "hook":
        return "3:1"
    # proof / data → clean, no drama
    if act == "proof":
        return "2:1"
    # cta → confident, clean
    if act == "cta":
        return "2:1~3:1"
    # hand-held / POV / over-shoulder → natural
    if any(kw in visual for kw in ["手持", "手部", "POV", "越肩"]):
        return "2:1"
    # product beauty / 360 → dramatic
    if any(kw in visual for kw in ["360", "环绕", "全貌", "亮相"]):
        return "3:1"
    # default
    return "2:1"


def _create_lighting_diagram_sheet(wb: Workbook, shots: list[dict], product_name: str, output_path: Path):
    """Create '灯光机位图' sheet referencing per-group SVG lighting diagrams.

    Each unique lighting setup gets an SVG file saved to a subfolder.
    The sheet lists each group with file reference and key parameters.
    SVGs open in any browser with pixel-perfect rendering.
    """
    import textwrap

    ws = wb.create_sheet("灯光机位图")

    # Group shots by lighting + camera + ratio
    groups = {}
    for si, shot in enumerate(shots):
        lt = shot.get("lighting", "").strip()
        cam = shot.get("camera_setup", "").strip()
        ratio = _get_light_ratio(shot)
        key = (lt, cam, ratio)
        if key not in groups:
            groups[key] = []
        groups[key].append(shot.get("shot_number", si + 1))

    # ── Column widths ──
    for c_letter, w in [("A", 5), ("B", 10), ("C", 28), ("D", 10), ("E", 28), ("F", 14)]:
        ws.column_dimensions[c_letter].width = w

    ctr = Alignment(horizontal="center", vertical="center")
    ctr_w = Alignment(horizontal="center", vertical="center", wrap_text=True)

    # ── Title ──
    ws.merge_cells("A1:F1")
    ws["A1"] = f"灯光机位图 — {product_name}  (SVG矢量图见同文件夹 .svg 文件)"
    ws["A1"].font = Font(name="微软雅黑", size=12, bold=True, color=TEXT_HEADER)
    ws["A1"].fill = PatternFill("solid", fgColor=PRIMARY)
    ws["A1"].alignment = ctr
    ws.row_dimensions[1].height = 28

    # ── Column headers ──
    headers = ["灯位编号", "镜号范围", "灯光配置", "光比", "机位配置", "SVG文件"]
    for ci, h in enumerate(headers, 1):
        cell = ws.cell(row=3, column=ci, value=h)
        cell.font = Font(name="微软雅黑", size=10, bold=True, color=TEXT_HEADER)
        cell.fill = PatternFill("solid", fgColor=PRIMARY)
        cell.alignment = ctr
        cell.border = Border(left=Side(style="thin", color=BORDER_COLOR),
                             right=Side(style="thin", color=BORDER_COLOR),
                             top=Side(style="thin", color=BORDER_COLOR),
                             bottom=Side(style="thin", color=BORDER_COLOR))
    ws.row_dimensions[3].height = 24

    # ── Generate SVGs and populate rows ──
    svg_dir = output_path.parent / f"{output_path.stem}_lighting"
    svg_dir.mkdir(parents=True, exist_ok=True)

    row = 4
    for gi, ((lt, cam, ratio), shot_nums) in enumerate(groups.items()):
        label = f"灯位{chr(65+gi)}"  # A, B, C...
        svg_filename = f"{label}_{product_name}.svg"
        svg_path = svg_dir / svg_filename

        # Generate SVG for this group
        technique = _derive_technique(shots[shot_nums[0]-1]) if shot_nums else ""
        _generate_lighting_svg(svg_path, label, ratio, lt, cam, technique, shot_nums, product_name)

        shot_ref = ", ".join(str(n) for n in shot_nums[:8])
        if len(shot_nums) > 8:
            shot_ref += f" …共{len(shot_nums)}镜"

        lt_short = lt[:40] if lt else "右前45°+柔光箱 5600K"
        cam_short = cam[:40] if cam else "50mm F2.8"

        data = [label, shot_ref, lt_short, f"主:辅≈{ratio}", cam_short, svg_filename]
        for ci, val in enumerate(data, 1):
            cell = ws.cell(row=row, column=ci, value=val)
            cell.font = Font(name="微软雅黑", size=9, color=TEXT_PRIMARY)
            cell.alignment = ctr_w
            cell.border = Border(left=Side(style="thin", color=BORDER_COLOR),
                                 right=Side(style="thin", color=BORDER_COLOR),
                                 top=Side(style="thin", color=BORDER_COLOR),
                                 bottom=Side(style="thin", color=BORDER_COLOR))
            if row % 2 == 0:
                cell.fill = PatternFill("solid", fgColor="F8FAFC")
        ws.row_dimensions[row].height = 22
        row += 1

    ws.sheet_properties.pageSetUpPr = None
    ws.page_setup.orientation = "landscape"


def _generate_lighting_svg(svg_path: Path, label: str, ratio: str, lighting: str, camera: str, technique: str, shot_nums: list, product_name: str = ""):
    """Generate a top-down lighting diagram SVG matching the user's reference format."""
    cam_short = camera.replace("机位:", "").replace("机位：", "")[:30] if camera else "50mm F2.8"
    shot_list = ", ".join(str(n) for n in shot_nums[:6])

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 520">
  <defs>
    <marker id="arrowBlue" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
      <polygon points="0 0, 8 3, 0 6" fill="#2563eb"/>
    </marker>
    <marker id="arrowGray" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
      <polygon points="0 0, 8 3, 0 6" fill="#64748b"/>
    </marker>
    <marker id="arrowGreen" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
      <polygon points="0 0, 8 3, 0 6" fill="#16a34a"/>
    </marker>
    <marker id="arrowRed" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
      <polygon points="0 0, 8 3, 0 6" fill="#dc2626"/>
    </marker>
    <style>
      text {{ font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif; }}
    </style>
  </defs>

  <rect width="600" height="520" fill="#ffffff" stroke="#e2e8f0" stroke-width="1"/>

  <text x="300" y="24" fill="#1e293b" font-size="12" font-weight="bold" text-anchor="middle">{label} — {product_name}  (镜号: {shot_list})</text>
  <line x1="30" y1="34" x2="570" y2="34" stroke="#e2e8f0" stroke-width="1"/>

  <!-- Product -->
  <rect x="240" y="165" width="120" height="90" rx="6" fill="#f8fafc" stroke="#475569" stroke-width="2"/>
  <text x="300" y="203" fill="#1e293b" font-size="12" font-weight="bold" text-anchor="middle">产品</text>
  <text x="300" y="221" fill="#94a3b8" font-size="9" text-anchor="middle">(桌面摆放)</text>
  <!-- Front direction -->
  <line x1="300" y1="255" x2="300" y2="290" stroke="#dc2626" stroke-width="2.5" marker-end="url(#arrowRed)"/>
  <text x="318" y="275" fill="#dc2626" font-size="10" font-weight="bold">正面朝向</text>

  <!-- Camera -->
  <circle cx="300" cy="400" r="20" fill="#f0fdf4" stroke="#16a34a" stroke-width="2"/>
  <text x="300" y="396" fill="#15803d" font-size="10" font-weight="bold" text-anchor="middle">机位</text>
  <text x="300" y="428" fill="#64748b" font-size="8" text-anchor="middle">{cam_short}</text>
  <!-- Lens direction -->
  <line x1="300" y1="380" x2="300" y2="305" stroke="#16a34a" stroke-width="2" marker-end="url(#arrowGreen)"/>
  <text x="318" y="345" fill="#16a34a" font-size="9" font-weight="bold">镜头朝向</text>
  <!-- FOV -->
  <line x1="300" y1="380" x2="240" y2="255" stroke="#16a34a" stroke-width="1" stroke-dasharray="4,3" opacity="0.4"/>
  <line x1="300" y1="380" x2="360" y2="255" stroke="#16a34a" stroke-width="1" stroke-dasharray="4,3" opacity="0.4"/>

  <!-- Key Light -->
  <circle cx="480" cy="120" r="22" fill="#eff6ff" stroke="#2563eb" stroke-width="2"/>
  <text x="480" y="115" fill="#1e40af" font-size="11" font-weight="bold" text-anchor="middle">主灯</text>
  <text x="480" y="132" fill="#64748b" font-size="8" text-anchor="middle">柔光箱</text>
  <text x="480" y="146" fill="#64748b" font-size="8" text-anchor="middle">5600K</text>
  <line x1="460" y1="135" x2="348" y2="190" stroke="#2563eb" stroke-width="2" marker-end="url(#arrowBlue)"/>
  <text x="425" y="152" fill="#2563eb" font-size="8">45°右前</text>

  <!-- Fill Light -->
  <circle cx="90" cy="200" r="20" fill="#f8fafc" stroke="#64748b" stroke-width="2"/>
  <text x="90" y="196" fill="#475569" font-size="11" font-weight="bold" text-anchor="middle">辅灯</text>
  <text x="90" y="214" fill="#94a3b8" font-size="8" text-anchor="middle">左侧补光</text>
  <line x1="110" y1="205" x2="240" y2="205" stroke="#64748b" stroke-width="2" marker-end="url(#arrowGray)"/>

  <!-- Camera-subject axis -->
  <line x1="300" y1="255" x2="300" y2="380" stroke="#cbd5e1" stroke-width="1" stroke-dasharray="2,4"/>

  <!-- Light Ratio Box -->
  <rect x="30" y="460" width="210" height="40" rx="6" fill="#f8fafc" stroke="#cbd5e1" stroke-width="1"/>
  <text x="135" y="478" fill="#1e293b" font-size="11" font-weight="bold" text-anchor="middle">光比</text>
  <text x="135" y="494" fill="#2563eb" font-size="10" text-anchor="middle">主灯 : 辅灯 = {ratio}</text>

  <!-- Technique -->
  <rect x="260" y="460" width="310" height="40" rx="6" fill="#f8fafc" stroke="#cbd5e1" stroke-width="1"/>
  <text x="415" y="478" fill="#64748b" font-size="9" text-anchor="middle">{technique}</text>

  <!-- Distance scale -->
  <line x1="30" y1="440" x2="160" y2="440" stroke="#cbd5e1" stroke-width="1"/>
  <text x="95" y="435" fill="#94a3b8" font-size="8" text-anchor="middle">≈ 1.5m</text>
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
