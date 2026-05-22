"""Centralized configuration from environment variables with sensible defaults."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ---- Paths ----
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
DOCS_DIR = Path(os.getenv("RAG_DOCS_DIR", PROJECT_ROOT / "2025text"))
DATA_DIR = Path(os.getenv("RAG_DATA_DIR", PROJECT_ROOT / "data"))
CHROMA_DIR = DATA_DIR / "chroma_db"
CACHE_DIR = DATA_DIR / "cache"

# ---- API ----
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# ---- Embedding ----
EMBEDDING_MODEL = os.getenv("RAG_EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5")
EMBEDDING_DEVICE = os.getenv("RAG_EMBEDDING_DEVICE", "cpu")

# ---- Chunking ----
CHUNK_SIZE = int(os.getenv("RAG_CHUNK_SIZE", "400"))
CHUNK_OVERLAP = int(os.getenv("RAG_CHUNK_OVERLAP", "60"))

# ---- Retrieval ----
DEFAULT_TOP_K = int(os.getenv("RAG_DEFAULT_TOP_K", "8"))

# ---- Supported extensions ----
SUPPORTED_EXTENSIONS = {".docx", ".doc", ".docm", ".xlsx", ".xls", ".pdf"}

# ---- Category keywords ----
CATEGORY_KEYWORDS = {
    "keyboard": ["键盘", "磁轴", "轴体", "键帽", "机械键盘", "客制化", "热插拔"],
    "monitor": ["显示器", "电竞显示器", "IPS", "VA面板", "TN面板", "HDR", "刷新率",
                 "AOC", "飞利浦", "HKC", "华硕", "卓威", "外星人"],
    "mouse": ["鼠标", "轻量化", "传感器", "微动", "DPI", "回报率", "无线鼠标",
              "雷柏", "罗技", "雷蛇", "ROG龙鳞", "英菲克"],
    "gpu": ["显卡", "RTX", "GTX", "5060", "5070", "5080", "5090", "英特尔",
            "铭瑄", "七彩虹", "华硕", "微星", "帧生成", "DLSS"],
    "laptop": ["笔记本", "游戏本", "轻薄本", "全能本", "处理器", "独显",
               "红魔", "机械革命", "华硕天选", "联想", "旷世"],
    "headphone": ["耳机", "电竞耳机", "头戴式", "入耳式", "TWS", "降噪",
                  "西伯利亚", "iKF", "绯乐", "觅声", "耳魔", "雷魔人"],
    "phone": ["手机", "苹果", "iPhone", "安卓", "红魔", "旗舰",
              "转转", "两千价位", "性价比神机"],
    "desk_chair": ["桌椅", "电竞椅", "人体工学", "升降桌", "骁骑", "黑白调"],
    "speaker": ["音箱", "音响", "电竞音箱", "迈从K20"],
    "other": [],
}
