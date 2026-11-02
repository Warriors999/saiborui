"""Generate output/index.html — a complete, clickable file browser for all output files.

Called after every pipeline run to keep the file map up-to-date.
"""

import json
from datetime import datetime
from pathlib import Path

OUTPUT_DIR = Path("output")
INDEX_PATH = OUTPUT_DIR / "index.html"

# Directories to skip
SKIP_DIRS = {"douyin_sessions", "sessions", ".git", "__pycache__", "archive"}

FILE_TYPE_ICONS = {
    ".docx": "📄", ".doc": "📄",
    ".xlsx": "📈", ".xls": "📈",
    ".pptx": "💾", ".ppt": "💾",
    ".pdf": "📕",
    ".html": "🌐", ".htm": "🌐",
    ".md": "📝",
    ".json": "📊",
    ".png": "🖼", ".jpg": "🖼", ".jpeg": "🖼",
    ".svg": "🎨",
    ".txt": "📜",
    ".py": "🐛",
    ".csv": "📊",
    ".mp4": "🎥", ".mov": "🎥",
    ".mp3": "🎵", ".wav": "🎵",
}


def _icon(path: Path) -> str:
    return FILE_TYPE_ICONS.get(path.suffix.lower(), "📁")


def _size_str(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def build_index() -> str:
    """Scan output/ and return paths grouped by directory, sorted by mtime desc."""
    if not OUTPUT_DIR.exists():
        return ""

    # Collect all files grouped by relative directory
    groups: dict[str, list[Path]] = {}
    for f in sorted(OUTPUT_DIR.rglob("*")):
        if not f.is_file():
            continue
        # Skip hidden files and skip-dirs
        parts = f.relative_to(OUTPUT_DIR).parts
        if any(p.startswith(".") for p in parts):
            continue
        if any(d in SKIP_DIRS for d in parts):
            continue

        # Group by immediate subdirectory (or "根目录" for top-level)
        rel = f.relative_to(OUTPUT_DIR)
        group_name = str(rel.parent) if str(rel.parent) != "." else "根目录"

        if group_name not in groups:
            groups[group_name] = []
        groups[group_name].append(f)

    # Sort groups: top-level first, then alphabetically
    def _group_key(g: str) -> tuple:
        if g == "根目录":
            return (0, "")
        return (1, g)

    sorted_groups = sorted(groups.items(), key=lambda x: _group_key(x[0]))

    # Build HTML
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    total_count = sum(len(files) for _, files in sorted_groups)

    html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Output 文件地图 · 赛博瑞</title>
<style>
:root{{--bg:#0d1117;--card:#161b22;--border:#30363d;--text:#c9d1d9;--text2:#8b949e;--accent:#58a6ff;--accent2:#f78166}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif;background:var(--bg);color:var(--text);padding:32px 24px;max-width:1200px;margin:0 auto}}
h1{{font-size:24px;margin-bottom:4px}}
.meta{{color:var(--text2);font-size:13px;margin-bottom:28px}}
.group{{margin-bottom:32px}}
.group-title{{font-size:14px;font-weight:600;color:var(--accent);margin-bottom:10px;padding:8px 12px;background:var(--card);border-radius:6px;border:1px solid var(--border);display:flex;justify-content:space-between;align-items:center}}
.group-title .count{{font-size:12px;color:var(--text2);font-weight:400}}
.file-row{{display:flex;align-items:center;gap:10px;padding:7px 12px;border-radius:4px;font-size:13px;transition:background .1s;cursor:pointer}}
.file-row:hover{{background:var(--card)}}
.file-row .icon{{width:20px;text-align:center;flex-shrink:0}}
.file-row .name{{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.file-row .size{{color:var(--text2);font-size:12px;white-space:nowrap}}
.file-row .mtime{{color:var(--text2);font-size:12px;white-space:nowrap}}
a{{color:inherit;text-decoration:none;display:contents}}
.search-bar{{margin-bottom:24px}}
.search-bar input{{width:100%;padding:10px 14px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text);font-size:14px;outline:none}}
.search-bar input:focus{{border-color:var(--accent)}}
.hidden{{display:none!important}}
.stats{{display:flex;gap:24px;margin-bottom:8px;flex-wrap:wrap}}
.stat{{display:flex;align-items:center;gap:6px;font-size:13px;color:var(--text2)}}
.stat strong{{color:var(--text)}}
.no-match{{text-align:center;padding:48px;color:var(--text2)}}
</style>
</head>
<body>

<h1>📁 Output 文件地图</h1>
<p class="meta">全部产出文件 · {total_count} 个文件 · 更新于 {now} · 点击即打开</p>

<div class="search-bar">
  <input type="text" id="search" placeholder="🔍 搜索文件名... (例如: 竞品 / 选题 / 脚本 / docx)" oninput="filter(this.value)">
</div>

<div class="stats">
  <div class="stat">📄 文档 <strong>{sum(1 for _,fs in sorted_groups for f in fs if f.suffix=='.docx')}</strong></div>
  <div class="stat">📈 表格 <strong>{sum(1 for _,fs in sorted_groups for f in fs if f.suffix=='.xlsx')}</strong></div>
  <div class="stat">💾 演示 <strong>{sum(1 for _,fs in sorted_groups for f in fs if f.suffix=='.pptx')}</strong></div>
  <div class="stat">🌐 网页 <strong>{sum(1 for _,fs in sorted_groups for f in fs if f.suffix=='.html')}</strong></div>
  <div class="stat">📊 数据 <strong>{sum(1 for _,fs in sorted_groups for f in fs if f.suffix=='.json')}</strong></div>
</div>
"""

    for group_name, files in sorted_groups:
        # Sort files by mtime desc
        files_sorted = sorted(files, key=lambda f: f.stat().st_mtime, reverse=True)

        html += f'<div class="group">\n'
        html += f'<div class="group-title"><span>📂 {group_name}/</span><span class="count">{len(files_sorted)} 个文件</span></div>\n'

        for f in files_sorted:
            icon = _icon(f)
            name = f.name
            size = _size_str(f.stat().st_size)
            mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%m-%d %H:%M")
            # Use file:// URI for opening in native apps
            abs_path = f.resolve().as_uri()
            html += (
                f'<a href="{abs_path}" title="{name}">'
                f'<div class="file-row" data-name="{name.lower()}">'
                f'<span class="icon">{icon}</span>'
                f'<span class="name">{name}</span>'
                f'<span class="size">{size}</span>'
                f'<span class="mtime">{mtime}</span>'
                f'</div></a>\n'
            )

        html += '</div>\n'

    html += """
<div class="no-match hidden" id="no-match">没有匹配的文件</div>

<script>
function filter(q){
  var rows=document.querySelectorAll('.file-row');
  var groups=document.querySelectorAll('.group');
  var any=false;
  groups.forEach(function(g){
    var visible=false;
    g.querySelectorAll('.file-row').forEach(function(r){
      if(!q||r.dataset.name.includes(q.toLowerCase())){
        r.classList.remove('hidden');visible=true;
      }else{r.classList.add('hidden')}
    });
    g.classList.toggle('hidden',!visible);
    if(visible)any=true;
  });
  document.getElementById('no-match').classList.toggle('hidden',any||!q);
}
</script>
</body></html>"""

    return html


def write_index() -> Path:
    """Generate and write the index file. Returns the path."""
    html = build_index()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(html, encoding="utf-8")
    return INDEX_PATH


if __name__ == "__main__":
    path = write_index()
    print(f"File index written: {path} ({path.stat().st_size} bytes)")
