"""Daily trending topics pipeline — fetch, score, report, seed.

Uses hot-topics API (60s.viki.moe) for Weibo/Zhihu/Baidu/Douyin hot searches.
Generates: markdown report + HTML report (template-based) + topics seed file.
"""

import json, re, sys, time
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

from rag_system.utils import logger

OUTPUT_DIR = Path("output/daily")
REPORT_MD = OUTPUT_DIR / "_daily_topic_report.md"
REPORT_HTML = OUTPUT_DIR / "_daily_topic_report.html"
SEED_FILE = OUTPUT_DIR / "topics_seed.txt"
CACHE_FILE = OUTPUT_DIR / "_topic_cache.json"
MAX_CACHE_AGE_DAYS = 7

HOT_TOPICS_API = "https://60s.viki.moe/v2"
PLATFORMS = {
    "weibo": f"{HOT_TOPICS_API}/weibo",
    "zhihu": f"{HOT_TOPICS_API}/zhihu",
    "baidu": f"{HOT_TOPICS_API}/baidu/hot",
    "douyin": f"{HOT_TOPICS_API}/douyin",
    "bili": f"{HOT_TOPICS_API}/bili",
}

TECH_CORE = [
    "键盘", "鼠标", "显示器", "耳机", "音响", "外设",
    "显卡", "CPU", "GPU", "RTX", "芯片", "主板", "内存", "SSD", "硬盘",
    "笔记本", "电脑", "手机", "平板", "iPad", "iPhone",
    "苹果", "华为", "小米", "ROG", "索尼", "微软", "英伟达", "NVIDIA",
    "AMD", "Intel", "高通", "联发科", "三星",
    "AI", "人工智能", "大模型", "DeepSeek", "ChatGPT",
    "5G", "WiFi", "蓝牙", "Type-C",
    "游戏", "电竞", "FPS", "机械", "磁轴", "客制化",
    "高刷", "2K", "4K", "HDR", "OLED", "MiniLED",
    "618", "发布", "新品", "降价", "性价比",
    "充电", "续航", "散热", "性能", "跑分", "评测",
]
TECH_BROAD = ["科技", "数码", "智能", "数据", "二手", "捡漏", "创业", "自媒体"]
NOISE_KW = ["旅游", "打卡", "美食", "景点", "天气", "房价", "油价", "车价",
            "电视剧", "综艺", "明星", "恋爱", "结婚", "离婚", "出轨",
            "足球", "篮球", "NBA", "世界杯", "特朗普", "拜登", "政治",
            "医院", "疫情", "病毒", "健康", "金价", "股市", "A股", "期货", "基金"]


def _fetch_platform(platform, url, max_retries=3):
    """Fetch hot topics from a platform API with retry on transient errors."""
    import requests
    last_error = None
    for attempt in range(max_retries):
        try:
            r = requests.get(url, timeout=10)
            data = r.json()
            items = data.get("data", [])
            if not items:
                return []
            for item in items:
                if isinstance(item, dict):
                    item.setdefault("rank", 99)
                    item.setdefault("热度", 0)
                    try:
                        item["热度"] = int(str(item["热度"]).replace(",", ""))
                    except Exception:
                        item["热度"] = 0
            logger.info("  %s: %d topics", platform, len(items))
            return items
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                logger.warning("  %s: retry %d/%d after %.0fs — %s", platform, attempt + 1, max_retries, wait, e)
                time.sleep(wait)
    logger.warning("  %s: all %d retries exhausted — %s", platform, max_retries, last_error)
    return []


def _fetch_bilibili():
    """Fetch B站 hot search topics. Primary: official API, fallback: 60s.viki.moe."""
    items = _fetch_bilibili_official()
    if items:
        return items
    logger.info("  bili: official API returned 0, falling back to aggregator")
    return _fetch_platform("bili", f"{HOT_TOPICS_API}/bili")


def _fetch_bilibili_official():
    """Fetch from B站 official hot search square API (no WBI sign required)."""
    import requests
    try:
        url = "https://api.bilibili.com/x/web-interface/wbi/search/square?limit=50"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.bilibili.com/",
        }
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        if data.get("code") != 0:
            logger.warning("  bili official API error: code=%s", data.get("code"))
            return []
        trending = data.get("data", {}).get("trending", {})
        raw_items = trending.get("list", [])
        result = []
        for i, item in enumerate(raw_items):
            keyword = item.get("keyword", "")
            show_name = item.get("show_name", "")
            result.append({
                "title": show_name or keyword,
                "rank": i + 1,
                "热度": item.get("heat_score", 0),
                "url": "https://search.bilibili.com/all?keyword=%s" % requests.utils.quote(keyword or show_name),
            })
        logger.info("  bili: %d topics (official API)", len(result))
        return result
    except Exception as e:
        logger.warning("  bili official: %s", e)
        return []


def _is_tech(title):
    for nk in NOISE_KW:
        if nk in title: return False
    for ck in TECH_CORE:
        if ck in title: return True
    hits = sum(1 for bk in TECH_BROAD if bk in title)
    return hits >= 2


def _score(topic, platform):
    title = topic.get("title", "")
    core_matches = sum(1 for kw in TECH_CORE if kw in title)
    broad_matches = sum(1 for kw in TECH_BROAD if kw in title)
    kw_score = core_matches * 10 + broad_matches * 3
    rank = topic.get("rank", 99)
    rank_score = max(0, (100 - min(rank, 100)) / 2)
    pw = {"douyin": 1.5, "bili": 1.3, "zhihu": 1.2, "weibo": 1.0, "baidu": 0.8}
    platform_bonus = pw.get(platform, 1.0) * 5
    content_bonus = 0
    if any(k in title for k in ["评测", "实测", "对比", "推荐", "选购", "盘点"]): content_bonus += 8
    if any(k in title for k in ["发布", "新品", "上市", "开售"]): content_bonus += 5
    if any(k in title for k in ["键盘", "鼠标", "显示器", "耳机", "外设"]): content_bonus += 10
    return round(kw_score + rank_score + platform_bonus + content_bonus, 1)


def _suggest_format(title):
    if any(k in title for k in ["键盘", "鼠标", "显示器", "耳机", "外设"]): return "实测体验"
    if any(k in title for k in ["推荐", "选购", "618", "降价", "性价比", "对比"]): return "选购指南"
    if any(k in title for k in ["盘点", "排行", "TOP"]): return "盘点排名"
    if any(k in title for k in ["发布", "新品", "上市"]): return "新品速览"
    if any(k in title for k in ["AI", "芯片", "技术", "原理"]): return "深度解读"
    if any(k in title for k in ["技巧", "教学", "设置", "优化"]): return "技巧教学"
    return "热点评论"


def _content_angles(title, platform, fmt):
    angles = []
    tech_hook = ""
    urgency = "中"
    difficulty = "中"

    if any(k in title for k in ["键盘", "鼠标", "外设", "磁轴", "机械"]):
        angles = [
            "上手实测：" + title[:20] + "到底值不值",
            "同价位对比：" + title[:15] + "跟竞品差在哪",
            "技术解读：" + title[:15] + "背后的供应链逻辑",
        ]
        tech_hook = "直接做实测/对比视频，上手体验就是内容"
        urgency, difficulty = "高", "低（有产品就能拍）"
    elif any(k in title for k in ["显示器", "屏幕", "高刷", "2K", "4K", "MiniLED", "OLED"]):
        angles = [
            "选购指南：" + title[:20] + "适合什么人",
            "实测对比：" + title[:15] + " vs 同价位VA/IPS",
            "避坑指南：买" + title[:12] + "前必须知道的3个参数",
        ]
        tech_hook = "显示器是数码博主最稳定的流量品类，选购指南永远有人看"
        urgency, difficulty = "高", "中（需要实拍画面）"
    elif any(k in title for k in ["显卡", "GPU", "RTX", "NVIDIA", "英伟达", "芯片"]):
        angles = [
            "深度解读：" + title[:20] + "对普通人意味着什么",
            "历史对比：从上一代到这一代，进步有多大",
            "购买建议：" + title[:15] + "值得等还是直接入手",
        ]
        tech_hook = "芯片/显卡话题永远是数码圈最大流量池，观点可以差异化"
        urgency, difficulty = "高", "中（需要专业知识储备）"
    elif any(k in title for k in ["笔记本", "电脑", "MacBook"]):
        angles = [
            "选购指南：" + title[:20] + "怎么选",
            "长期使用报告：" + title[:15] + "用了一年的真实感受",
            "对比评测：" + title[:15] + " vs 同价位竞品",
        ]
        tech_hook = "笔记本选购是常青内容，可以做成系列"
    elif any(k in title for k in ["手机", "iPhone", "华为", "小米"]):
        angles = [
            "新品速评：" + title[:20] + "值得升级吗",
            "功能挖掘：" + title[:15] + "中90%人不知道的隐藏功能",
        ]
        tech_hook = "手机话题流量大但竞争激烈，需找到差异化角度"
        urgency = "高"
    elif any(k in title for k in ["AI", "人工智能", "大模型", "DeepSeek"]):
        angles = [
            "通俗解读：" + title[:20] + "到底是怎么做到的",
            "实际测试：我用" + title[:15] + "做了X件事，结果出乎意料",
        ]
        tech_hook = "AI话题需要翻译——把技术语言变成普通人能懂的比喻"
        urgency, difficulty = "高", "高（需要准确理解技术原理）"
    elif any(k in title for k in ["618", "降价", "性价比", "推荐", "选购"]):
        angles = [
            "实时比价：" + title[:20] + "当前最低价是多少",
            "避坑指南：" + title[:12] + "这些型号千万别买",
        ]
        tech_hook = "价格敏感型内容在促销季流量极高，时效性窗口短"
        urgency = "极高"
    elif any(k in title for k in ["游戏", "电竞", "FPS"]):
        angles = [
            "装备推荐：打" + title[:10] + "用什么外设",
            "设置优化：" + title[:10] + "职业选手的游戏设置",
        ]
        tech_hook = "游戏内容转外设推荐是自然转化路径"
    else:
        angles = [
            "热点解读：" + title[:20] + "到底怎么回事",
            "深度分析：" + title[:15] + "背后的行业逻辑",
            "观点评论：我对" + title[:15] + "的看法",
        ]
        tech_hook = "需要找到一个数码/科技角度来切入这个话题"

    return {"angles": angles, "tech_hook": tech_hook, "urgency": urgency, "difficulty": difficulty}
def _generate_rich_html(scored_topics, date_str):
    """Generate rich HTML report by injecting JSON data into the template."""
    # Build topics JSON with content briefs
    topics_json = []
    for i, t in enumerate(scored_topics[:15], 1):
        title = t.get("title", "")
        fmt = _suggest_format(title)
        brief = _content_angles(title, t.get("_platform", ""), fmt)
        topics_json.append({
            "rank": i, "title": title,
            "platform": t.get("_platform", ""),
            "rank_orig": t.get("rank", 99),
            "score": t.get("_score", 0), "format": fmt,
            "effect": "high" if t.get("_score", 0) > 20 else "medium",
            "angles": brief["angles"], "tech_hook": brief["tech_hook"],
            "urgency": brief["urgency"], "difficulty": brief["difficulty"],
        })

    data_json = json.dumps({
        "date": date_str,
        "count": len(topics_json),
        "topScore": max((t["score"] for t in topics_json), default=0),
        "topics": topics_json,
    }, ensure_ascii=False, indent=2)

    # Chinese weekday
    weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    try:
        dt = datetime.fromisoformat(date_str)
        date_display = "%d年%d月%d日 · %s · 晨间简报" % (dt.year, dt.month, dt.day, weekdays[dt.weekday()])
    except:
        date_display = date_str

    # Rich HTML with inline styles and angles/tech_hook rendering
    html = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>数码圈每日热点选题 — __DATE__</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@400;600;700;900&family=Noto+Sans+SC:wght@300;400;500;700&display=swap" rel="stylesheet">
<style>
:root{--paper:#FAF7F2;--ink:#1C1C1C;--ink-light:#5C5C5C;--ink-muted:#999;--accent:#C03A2B;--gold:#B8960C;--divider:#E5E0D8;--card-bg:#FFFFFF;--tag-bg:#F3F0EA;--tag-text:#6B6258;--bar-bg:#EDE9E2;--weibo:#E6162D;--zhihu:#0066FF;--baidu:#2932E1;--douyin:#1E1E1E;--bili:#FB7299}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:"Noto Sans SC","PingFang SC","Microsoft YaHei",sans-serif;background:#EDE8DE;background-image:radial-gradient(ellipse at 20% 0%,rgba(180,160,130,.08) 0%,transparent 60%),radial-gradient(ellipse at 80% 100%,rgba(180,160,130,.05) 0%,transparent 60%);color:var(--ink);line-height:1.6}
.container{max-width:900px;margin:0 auto;padding:48px 24px 64px}
.paper{background:var(--card-bg);border-radius:2px;box-shadow:0 1px 3px rgba(0,0,0,.04),0 8px 32px rgba(0,0,0,.06);overflow:hidden;position:relative}
.paper::before{content:'';position:absolute;top:0;left:0;right:0;height:4px;background:linear-gradient(90deg,var(--accent) 0%,var(--accent) 40%,var(--gold) 40%,var(--gold) 42%,var(--accent) 42%,var(--accent) 100%)}
.masthead{padding:44px 48px 28px;border-bottom:2px solid var(--ink)}
.dateline{font-family:"Noto Serif SC",serif;font-size:12px;font-weight:600;letter-spacing:3px;color:var(--ink-muted);margin-bottom:12px}
.masthead h1{font-family:"Noto Serif SC",serif;font-size:34px;font-weight:900;letter-spacing:-.5px;line-height:1.2;margin-bottom:8px}
.subtitle{font-size:14px;color:var(--ink-light);font-weight:300}
.stats-row{display:flex;gap:32px;margin-top:20px}
.stat-item{display:flex;flex-direction:column}
.stat-num{font-family:"Noto Serif SC",serif;font-size:28px;font-weight:900;color:var(--accent);line-height:1}
.stat-label{font-size:11px;color:var(--ink-muted);letter-spacing:1px;margin-top:2px}
.content{padding:36px 48px 48px}
.section-header{display:flex;align-items:center;gap:12px;margin:12px 0 24px}
.section-header h2{font-family:"Noto Serif SC",serif;font-size:18px;font-weight:700;white-space:nowrap}
.section-header .rule{flex:1;height:1px;background:var(--divider)}
.topic-card{border:1px solid var(--divider);border-radius:3px;padding:20px 24px;margin-bottom:14px;transition:box-shadow .2s;opacity:0;animation:fadeIn .4s ease forwards}
.topic-card:hover{box-shadow:0 4px 16px rgba(0,0,0,.06)}
@keyframes fadeIn{to{opacity:1}}
.topic-card-header{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:12px}
.topic-card-left{display:flex;align-items:flex-start;gap:14px;flex:1}
.topic-rank{font-family:"Noto Serif SC",serif;font-size:26px;font-weight:900;width:36px;text-align:center;color:var(--ink-muted);flex-shrink:0;line-height:1.1}
.topic-card:nth-child(1) .topic-rank{color:var(--accent)}
.topic-card:nth-child(2) .topic-rank{color:#D4683A}
.topic-card:nth-child(3) .topic-rank{color:#C08030}
.topic-title-main{font-size:16px;font-weight:600;line-height:1.4}
.topic-meta-row{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-top:4px}
.platform-badge{display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:2px;font-size:10px;font-weight:600;letter-spacing:.5px}
.platform-badge.weibo{background:#FFF0F0;color:var(--weibo)}
.platform-badge.zhihu{background:#F0F4FF;color:var(--zhihu)}
.platform-badge.baidu{background:#F0F1FF;color:var(--baidu)}
.platform-badge.douyin{background:#F5F5F5;color:var(--douyin)}
.platform-badge.bili{background:#FFF0F4;color:var(--bili)}
.score-pill{display:inline-flex;align-items:center;gap:4px;font-size:13px;font-weight:700;color:var(--accent)}
.score-pill .bar{width:48px;height:4px;background:var(--bar-bg);border-radius:2px;overflow:hidden}
.score-pill .bar-fill{height:100%;background:var(--accent);border-radius:2px}
.tag-row{display:flex;gap:8px;flex-wrap:wrap}
.tag{display:inline-block;padding:3px 10px;border-radius:2px;font-size:10px;font-weight:600;letter-spacing:.5px}
.tag.format{background:var(--tag-bg);color:var(--tag-text)}
.tag.urgent-high{background:#FFF0ED;color:var(--accent)}
.tag.urgent-mid{background:#FFF9ED;color:var(--gold)}
.tag.diff-low{background:#EDFFF5;color:#10B981}
.tag.diff-mid{background:#FFF9ED;color:var(--gold)}
.tag.diff-high{background:#FFF0ED;color:var(--accent)}
.angles-section{margin-top:14px;padding-top:14px;border-top:1px solid var(--divider)}
.angles-section .label{font-size:11px;font-weight:700;letter-spacing:1px;color:var(--ink-muted);margin-bottom:8px;text-transform:uppercase}
.angle-item{display:flex;align-items:flex-start;gap:8px;padding:5px 0;font-size:13px;color:var(--ink-light);line-height:1.5}
.angle-num{width:20px;height:20px;border-radius:50%;background:var(--tag-bg);display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:700;color:var(--tag-text);flex-shrink:0}
.tech-hook{margin-top:10px;padding:10px 14px;background:#FFF9ED;border-radius:3px;border-left:3px solid var(--gold);font-size:12px;color:#8B6914;line-height:1.5}
.tech-hook strong{color:#6B5010}
.colophon{margin-top:48px;padding-top:24px;border-top:1px solid var(--divider);display:flex;justify-content:space-between;align-items:center;font-size:11px;color:var(--ink-muted)}
.colophon a{color:var(--ink-muted);text-decoration:none}
.colophon a:hover{color:var(--accent)}
@media(max-width:700px){.container{padding:16px 12px 32px}.masthead{padding:28px 24px 20px}.masthead h1{font-size:24px}.content{padding:24px 20px 32px}.topic-card{padding:16px}.topic-title-main{font-size:14px}.stats-row{gap:16px}}
</style>
</head>
<body>
<div class="container"><div class="paper">
<div class="masthead">
<div class="dateline">__DATE_DISPLAY__</div>
<h1>数码圈每日热点选题</h1>
<p class="subtitle">聚合微博/知乎/百度/抖音/B站热搜 · AI筛选 · 多维度评分 · 含切入角度与数码挂钩建议</p>
<div class="stats-row">
<div class="stat-item"><span class="stat-num">__COUNT__</span><span class="stat-label">数码相关话题</span></div>
<div class="stat-item"><span class="stat-num">5</span><span class="stat-label">数据平台</span></div>
<div class="stat-item"><span class="stat-num">__TOPSCORE__</span><span class="stat-label">最高评分</span></div>
</div></div>
<div class="content">
<div class="section-header"><h2>热搜话题 · 切入分析</h2><span class="rule"></span></div>
<div id="topicCards"></div>
<div class="colophon">
<span>数据截至今日 · 每日自动更新 · 下周数据自动清理</span>
<a href="https://deerflow.tech" target="_blank">Deerflow</a>
</div>
</div></div></div>
<script>
var DATA = __DATA__;
var PCN={weibo:"微博",zhihu:"知乎",baidu:"百度",douyin:"抖音",bili:"B站"};
var URG={"极高":"时效极强","高":"时效强","中":"时效中等"};
var DIFF={"低":"门槛低","中":"需准备","高":"需深耕"};
var c=document.getElementById("topicCards");
DATA.topics.forEach(function(t,i){
  var d=document.createElement("div");
  d.className="topic-card";
  d.style.animationDelay=(i*0.06)+"s";
  var bw=Math.min(t.score/50*100,100);
  var uc=t.urgency==="极高"||t.urgency==="高"?"urgent-high":"urgent-mid";
  var dc=t.difficulty==="低"?"diff-low":(t.difficulty==="高"?"diff-high":"diff-mid");
  var ah=t.angles.map(function(a,j){return '<div class="angle-item"><span class="angle-num">'+(j+1)+'</span><span>'+a+'</span></div>';}).join("");
  d.innerHTML='<div class="topic-card-header"><div class="topic-card-left"><span class="topic-rank">'+t.rank+'</span><div><div class="topic-title-main">'+t.title+'</div><div class="topic-meta-row"><span class="platform-badge '+t.platform+'">'+(PCN[t.platform]||t.platform)+'</span><span class="score-pill"><span class="bar"><span class="bar-fill" style="width:'+bw+'%"></span></span>'+t.score+'分</span></div></div></div><div class="tag-row"><span class="tag format">'+t.format+'</span><span class="tag '+uc+'">'+(URG[t.urgency]||t.urgency)+'</span><span class="tag '+dc+'">'+(DIFF[t.difficulty]||t.difficulty)+'</span></div></div><div class="angles-section"><div class="label">切入角度</div>'+ah+'</div><div class="tech-hook"><strong>数码挂钩：</strong>'+t.tech_hook+'</div>';
  c.appendChild(d);
});
</script>
</body>
</html>"""

    # Replace placeholders
    html = html.replace("__DATE__", date_str)
    html = html.replace("__DATE_DISPLAY__", date_display)
    html = html.replace("__COUNT__", str(len(topics_json)))
    html = html.replace("__TOPSCORE__", str(max((t["score"] for t in topics_json), default=0)))
    html = html.replace("__DATA__", data_json)

    REPORT_HTML.write_text(html, encoding="utf-8")
    return len(html)


def run_daily_pipeline():
    today = datetime.now().strftime("%Y-%m-%d")
    logger.info("Daily topics pipeline: %s", today)

    # 1. Fetch
    all_items = []
    for platform, url in PLATFORMS.items():
        if platform == "bili":
            items = _fetch_bilibili()
        else:
            items = _fetch_platform(platform, url)
        for item in items:
            item["_platform"] = platform
        all_items.extend(items)
    logger.info("Fetched %d total items", len(all_items))

    # 2. Filter tech
    tech_items = [t for t in all_items if _is_tech(t.get("title", ""))]
    logger.info("Tech filter: %d/%d passed", len(tech_items), len(all_items))

    # 3. Score
    for t in tech_items:
        t["_score"] = _score(t, t.get("_platform", ""))
    tech_items.sort(key=lambda x: x["_score"], reverse=True)

    # 4. Dedup
    seen = set()
    unique = []
    for t in tech_items:
        key = re.sub(r"[^一-鿿]", "", t.get("title", ""))[:20]
        if key and key not in seen:
            seen.add(key)
            unique.append(t)

    # 5. Markdown report
    lines = [
        "# 数码圈每日热点选题报告",
        "**%s** | 微博/知乎/百度/抖音/B站热搜 | %d 条数码相关" % (today, len(unique)),
        "",
        "## TOP 15",
        "",
        "| # | 话题 | 平台 | 排名 | 分 | 选题方向 |",
        "|---|------|------|------|-----|----------|",
    ]
    for i, t in enumerate(unique[:15], 1):
        title = t.get("title", "")[:45]
        plat = t.get("_platform", "?")
        rank = t.get("rank", "?")
        score = t.get("_score", 0)
        fmt = _suggest_format(title)
        lines.append("| %d | %s | %s | #%s | %.0f | %s |" % (i, title, plat, rank, score, fmt))
    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")

    # 6. Rich HTML report
    html_size = _generate_rich_html(unique, today)
    logger.info("HTML report: %d chars", html_size)

    # 7. Seed file
    seed_lines = [
        "# 选题种子库 — 自动更新于 %s" % today,
        "# 每日从微博/知乎/百度/抖音/B站热搜提取数码相关话题",
        "# 格式: 标题 | 来源 | URL | 备注",
    ]
    for t in unique[:15]:
        if t.get("_score", 0) > 5:
            seed_lines.append("%s | %s热搜 | %s | 得分%.0f" % (
                t.get("title", ""), t.get("_platform", ""),
                t.get("url", ""), t.get("_score", 0)
            ))
    if SEED_FILE.exists():
        old_lines = SEED_FILE.read_text(encoding="utf-8").splitlines()
        for line in old_lines:
            if line.startswith("#") and line not in seed_lines:
                seed_lines.insert(2, line)
    SEED_FILE.write_text("\n".join(seed_lines), encoding="utf-8")
    logger.info("Seed file updated: %s", SEED_FILE)

    # 8. Cache & cleanup
    try:
        cache = json.loads(CACHE_FILE.read_text(encoding="utf-8")) if CACHE_FILE.exists() else []
    except:
        cache = []
    cache.append({"date": today, "count": len(unique), "top_score": unique[0]["_score"] if unique else 0})
    cutoff = (datetime.now() - timedelta(days=MAX_CACHE_AGE_DAYS)).isoformat()
    cache = [e for e in cache if e.get("date", "") >= cutoff[:10]]
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"topics": unique, "count": len(unique),
            "report_md": str(REPORT_MD), "report_html": str(REPORT_HTML), "seed": str(SEED_FILE)}


if __name__ == "__main__":
    result = run_daily_pipeline()
    print("\n" + "=" * 50)
    print("  数码圈每日热点选题 — %s" % datetime.now().strftime("%Y-%m-%d"))
    print("  %d 条数码相关话题" % result["count"])
    print("=" * 50)
    for i, t in enumerate(result["topics"][:10], 1):
        score = t.get("_score", 0)
        title = t.get("title", "")[:50]
        platform = t.get("_platform", "")
        fmt = _suggest_format(title)
        print("  %2d. [%.0f分] [%s] %s" % (i, score, platform, title))
        print("      -> %s" % fmt)
    print("\n  报告: %s" % result["report_md"])
    print("  HTML: %s" % result["report_html"])
    print("  种子: %s" % result["seed"])
