"""Guided first-run setup wizard — gets a new user from zero to working in under 2 minutes.

Usage:
    from rag_system.init_wizard import run_init
    success = run_init()

Also provides check_environment() for standalone diagnostics (saiborui doctor).
"""

import os
import sys
from pathlib import Path

import click


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

# Mapping: display name -> import path (dotted name for __import__)
_PACKAGES = {
    "openai": "openai",
    "chromadb": "chromadb",
    "sentence_transformers": "sentence_transformers",
    "docx": "docx",
    "openpyxl": "openpyxl",
    "click": "click",
}

# Directories to ensure exist
_REQUIRED_DIRS = [
    "output/scripts",
    "output/storyboards",
    "output/audits",
    "output/covers",
    "output/competitive",
    "data",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mask_key(key: str) -> str:
    """Return a masked version of an API key: sk-...xxxx"""
    if not key:
        return "(未设置)"
    if len(key) <= 11:
        return key[:3] + "..." + key[-2:]
    return key[:5] + "..." + key[-4:]


# ---------------------------------------------------------------------------
# check_environment() — standalone, no interactivity
# ---------------------------------------------------------------------------

def check_environment() -> dict:
    """Diagnose the current environment, return a summary dict.

    Returns:
        {"python": "3.12.3",
         "packages": {"openai": True, "chromadb": True, ...},
         "api_configured": bool,
         "api_key_masked": Optional[str],
         "kb_chunks": int,
         "kb_ok": bool,
         "all_ok": bool}
    """
    result = {
        "python": "unknown",
        "packages": {},
        "api_configured": False,
        "api_key_masked": None,
        "kb_chunks": 0,
        "kb_ok": False,
        "all_ok": False,
    }

    # 1. Python version
    result["python"] = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

    # 2. Key packages
    for pkg_name, import_path in _PACKAGES.items():
        try:
            __import__(import_path)
            result["packages"][pkg_name] = True
        except ImportError:
            result["packages"][pkg_name] = False

    # 3. API key
    try:
        from rag_system.config import DEEPSEEK_API_KEY
        if DEEPSEEK_API_KEY and DEEPSEEK_API_KEY.startswith("sk-"):
            result["api_configured"] = True
            result["api_key_masked"] = _mask_key(DEEPSEEK_API_KEY)
    except Exception as e:
        import logging
        logging.getLogger("rag_system").warning("API key check failed (non-fatal): %s", e)

    # 4. Knowledge base
    try:
        from rag_system.storage.vector_store import VectorStore
        store = VectorStore()
        result["kb_chunks"] = store.count()
        result["kb_ok"] = True
    except Exception as e:
        import logging
        logging.getLogger("rag_system").warning("KB count check failed (non-fatal): %s", e)

    # 5. All clear?
    result["all_ok"] = (
        sys.version_info >= (3, 12)
        and all(result["packages"].values())
        and result["api_configured"]
        and result["kb_ok"]
    )

    return result


# ---------------------------------------------------------------------------
# run_init() — guided interactive wizard
# ---------------------------------------------------------------------------


def run_init() -> bool:
    """Guided first-run setup wizard. Returns True on success, False on failure."""
    click.echo()
    click.secho("=" * 48, fg="cyan", bold=True)
    click.secho("  赛博瑞 (Saiborui) — 首次运行设置向导", fg="cyan", bold=True)
    click.secho("=" * 48, fg="cyan", bold=True)
    click.echo()
    click.echo("这个向导会帮你检查环境、配置 API 密钥、初始化知识库。")
    click.echo("全程不超过 2 分钟。\n")

    # ---- Step 1: Python version ----
    if not _step_python():
        return False

    # ---- Step 2: Dependencies ----
    if not _step_dependencies():
        return False

    # ---- Step 3: API key ----
    if not _step_api_key():
        return False

    # ---- Step 4: Directories ----
    _step_directories()

    # ---- Step 5: Vector store ----
    kb_chunks = _step_vector_store()

    # ---- Step 6: Summary ----
    _print_summary(kb_chunks)

    return True


# ---------------------------------------------------------------------------
# Individual steps
# ---------------------------------------------------------------------------

def _step_python() -> bool:
    """Check Python >= 3.12."""
    major, minor, micro = sys.version_info[:3]
    current = f"{major}.{minor}.{micro}"

    click.echo("  [1/5] 检查 Python 版本...")
    if (major, minor) >= (3, 12):
        click.echo(f"    {click.style('OK', fg='green')}  Python {current}")
        return True
    else:
        click.echo(f"    {click.style('失败', fg='red')}  Python {current} (需要 >= 3.12)")
        click.echo()
        click.secho("  请安装 Python 3.12 或更新版本:", fg="yellow")
        click.echo("    https://www.python.org/downloads/")
        return False


def _step_dependencies() -> bool:
    """Check that key packages are importable."""
    click.echo("  [2/5] 检查依赖包...")
    all_ok = True
    for display_name, import_path in _PACKAGES.items():
        try:
            __import__(import_path)
            click.echo(f"    {click.style('[OK]', fg='green')}  {display_name}")
        except ImportError:
            click.echo(f"    {click.style('[!!]', fg='red')}  {display_name} — 未安装")
            all_ok = False

    if all_ok:
        return True

    click.echo()
    click.secho("  缺少依赖包。请运行以下命令安装:", fg="yellow")
    click.echo("    pip install -r requirements.txt")
    return False


def _step_api_key() -> bool:
    """Set up and validate DeepSeek API key."""
    click.echo("  [3/5] 配置 DeepSeek API 密钥...")

    # Try to load existing key from .env
    from dotenv import load_dotenv
    load_dotenv()
    existing_key = os.getenv("DEEPSEEK_API_KEY", "")

    if existing_key and existing_key.startswith("sk-") and len(existing_key) > 20:
        masked = _mask_key(existing_key)
        click.echo(f"    已检测到现有密钥: {masked}")
        keep = click.confirm("    是否保留现有密钥?", default=True)
        if keep:
            api_key = existing_key
        else:
            api_key = _prompt_for_key()
            if api_key is None:
                return False
            _save_key_to_env(api_key)
    else:
        if existing_key:
            click.echo(f"    {click.style('[!!]', fg='yellow')}  现有密钥格式可能不正确")
        api_key = _prompt_for_key()
        if api_key is None:
            return False
        _save_key_to_env(api_key)

    # Test the key
    click.echo("    正在验证 API 密钥...")
    if _test_api_key(api_key):
        click.echo(f"    {click.style('[OK]', fg='green')}  API 密钥有效")
        return True
    else:
        click.echo(f"    {click.style('[!!]', fg='red')}  API 密钥验证失败")
        click.echo()
        click.secho("  请确认密钥是否正确。可以从这里获取:", fg="yellow")
        click.echo("    https://platform.deepseek.com/api_keys")
        return False


def _step_directories() -> None:
    """Create output directories if they don't exist."""
    click.echo("  [4/5] 创建输出目录...")
    project_root = Path(__file__).parent.parent
    for d in _REQUIRED_DIRS:
        dir_path = project_root / d
        dir_path.mkdir(parents=True, exist_ok=True)
        click.echo(f"    {click.style('[OK]', fg='green')}  {d}/")


def _step_vector_store() -> int:
    """Initialize ChromaDB vector store, return chunk count."""
    click.echo("  [5/5] 初始化知识库 (ChromaDB)...")
    try:
        from rag_system.storage.vector_store import VectorStore
        store = VectorStore()
        count = store.count()
        if count > 0:
            click.echo(f"    {click.style('[OK]', fg='green')}  知识库就绪 — {count} 条数据已索引")
        else:
            seed_dir = Path(__file__).parent.parent / "examples"
            seed_count = len(list(seed_dir.glob("*.docx"))) if seed_dir.exists() else 0
            click.echo(f"    {click.style('[OK]', fg='green')}  知识库就绪 (空库)")
            if seed_count:
                click.echo(f"    {click.style('[..]', fg='cyan')}  发现 {seed_count} 篇种子示例脚本 (examples/)")
                click.echo(f"    {click.style('[..]', fg='cyan')}  运行 python -m rag_system ingest 即可导入")
        return count
    except Exception as e:
        click.echo(f"    {click.style('[!!]', fg='yellow')}  知识库初始化遇到问题: {e}")
        click.echo("    这不影响基本使用，可以稍后排查。")
        return 0


def _print_summary(kb_chunks: int) -> None:
    """Print final summary with next steps."""
    # Gather version info for display
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    from rag_system.config import DEEPSEEK_API_KEY
    masked = _mask_key(DEEPSEEK_API_KEY or "")

    click.echo()
    click.secho("=" * 48, fg="cyan", bold=True)
    click.secho("  赛博瑞 初始化完成!", fg="cyan", bold=True)
    click.secho("=" * 48, fg="cyan", bold=True)
    click.echo(f"  Python:   {py_ver}  {click.style('OK', fg='green')}")
    click.echo(f"  API:      DeepSeek ({masked})  {click.style('OK', fg='green')}")
    if kb_chunks > 0:
        click.echo(f"  知识库:   {kb_chunks} 条数据就绪")
    else:
        click.echo(f"  知识库:   (空库 — 稍后导入)")
    click.echo(f"  输出目录: output/  {click.style('OK', fg='green')}")
    click.echo()
    click.secho("  下一步:", bold=True)
    click.echo("    saiborui generate -p \"产品名\" -c keyboard -k \"卖点1,卖点2\"")
    click.echo("    saiborui --help")
    click.secho("=" * 48, fg="cyan", bold=True)
    click.echo()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _prompt_for_key() -> str | None:
    """Prompt the user for a DeepSeek API key, validate format locally."""
    click.echo()
    click.echo("    请输入 DeepSeek API 密钥")
    click.echo("    (从 https://platform.deepseek.com/api_keys 获取)")
    click.echo()

    try:
        key = click.prompt("    API Key", default="", hide_input=True, show_default=False)
    except (KeyboardInterrupt, click.Abort):
        click.echo("\n    已取消。")
        return None

    key = key.strip()
    if not key:
        click.echo(f"    {click.style('[!!]', fg='red')}  密钥不能为空")
        return None

    if not key.startswith("sk-"):
        click.echo(f"    {click.style('[!!]', fg='red')}  密钥格式不正确 (应该以 sk- 开头)")
        return None

    if len(key) < 20:
        click.echo(f"    {click.style('[!!]', fg='red')}  密钥长度不足 (至少 20 个字符)")
        return None

    return key


def _save_key_to_env(api_key: str) -> None:
    """Save the API key to the project's .env file."""
    project_root = Path(__file__).parent.parent
    env_path = project_root / ".env"

    # Read existing .env content
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    else:
        lines = []

    # Replace or append DEEPSEEK_API_KEY
    new_lines = []
    found = False
    for line in lines:
        if line.strip().startswith("DEEPSEEK_API_KEY") and "=" in line:
            new_lines.append(f"DEEPSEEK_API_KEY={api_key}")
            found = True
        else:
            new_lines.append(line)

    if not found:
        # Add a blank line before the key if the file doesn't end with one
        if new_lines and new_lines[-1].strip():
            new_lines.append("")
        new_lines.append(f"DEEPSEEK_API_KEY={api_key}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    click.echo(f"    密钥已保存到 .env")


def _test_api_key(api_key: str) -> bool:
    """Test a DeepSeek API key with a trivial completion call.

    Uses the OpenAI-compatible endpoint configured in rag_system.config.
    """
    try:
        from openai import OpenAI
        from rag_system.config import DEEPSEEK_BASE_URL

        client = OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)

        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=5,
            temperature=0.0,
        )

        # Any valid response means the key works
        if response and response.choices:
            return True
        return False

    except Exception as e:
        error_msg = str(e)
        # Surface a user-friendly summary of common errors
        if "401" in error_msg or "authentication" in error_msg.lower():
            click.echo(f"    {click.style('认证失败', fg='red')}: 密钥无效或已过期")
        elif "402" in error_msg or "insufficient" in error_msg.lower():
            click.echo(f"    {click.style('余额不足', fg='red')}: 请充值后重试")
        elif "429" in error_msg or "rate" in error_msg.lower():
            click.echo(f"    {click.style('请求过于频繁', fg='yellow')}: 请稍后重试")
        elif "timeout" in error_msg.lower() or "connect" in error_msg.lower():
            click.echo(f"    {click.style('网络错误', fg='red')}: 无法连接到 DeepSeek API")
        else:
            click.echo(f"    {click.style('错误', fg='red')}: {error_msg[:120]}")
        return False
