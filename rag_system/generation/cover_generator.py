"""Cover image prompt generator — DeepSeek API wrapper.

Implements 影视飓风's "封面前置" (cover-first) methodology.
Takes a product brief/concept and crafts a detailed 5-dimension
AI image generation prompt (Midjourney/DALL-E/SD compatible).

Does NOT generate images directly — produces structured text prompts
that can be fed into any image generation tool.
"""

from pathlib import Path
from openai import OpenAI

from rag_system.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, PROJECT_ROOT
from rag_system.utils import logger, sanitize_filename

# ============================================================
# COVER SYSTEM PROMPT — 影视飓风 封面前置 5维设计方法论
# ============================================================

COVER_SYSTEM_PROMPT = """你是一位顶级的数码科技视频封面设计师，深谙影视飓风"封面前置"方法论。

你的任务：根据产品信息和封面建议，输出一份完整的封面设计提示词，包含标题、5个设计维度和可直接使用的AI图像生成提示词。

## 5个设计维度说明

### 1. 类型 (Type) — 选其一
- **产品特写**：产品本身占据画面主体，适合单品深度评测
- **场景氛围**：产品融入使用场景，营造代入感，适合体验类内容
- **对比冲击**：多产品并置对比，突出差异，适合横评/选购指南
- **文字主导**：画面简洁，标题大字占主导，适合信息型内容
- **人物表情**：人物手持产品+夸张表情，适合vlog/搞笑向

### 2. 调色板 (Palette) — 选其一
- **赛博朋克霓虹**：紫蓝粉霓虹渐变，深色基底，适合电竞/游戏产品
- **暖色科技**：橙金+深灰，温暖而有未来感，适合消费电子产品
- **暗黑质感**：纯黑背景+单束侧光，突出产品线条，适合高端旗舰
- **高饱和冲击**：撞色/荧光色，极强的视觉抓力，适合性价比产品
- **极简白灰**：白底+浅灰阴影，干净利落，适合轻薄本/办公设备

### 3. 渲染风格 (Rendering) — 选其一
- **3D写实**：C4D/Blender质感，产品细节完美呈现
- **平面插画**：矢量风/卡通风，年轻化表达
- **摄影质感**：影棚级打光，金属/皮革/玻璃材质质感
- **电影级光效**：体积光、烟雾、粒子效果，大片感

### 4. 文字叠加 (Text Overlay)
- 封面标题文字（15-20字，抓眼球、有信息量）
- 文字在画面中的位置（顶部/底部/居中/左对齐/右对齐）
- 字体风格建议（粗黑体/手写体/等宽字体/描边）

### 5. 氛围 (Mood) — 选其一
- **紧迫**："再不买就没了"的稀缺感
- **震撼**："这也太强了吧"的冲击力
- **好奇**："到底是什么让博主这样"的探知欲
- **专业**："这评测我要收藏"的权威感
- **幽默**："笑死我了但产品是真的好"的轻松感

## 输出格式要求

请严格按照以下Markdown格式输出，不要添加额外解释：

## 封面标题
（15-20字，抓眼球的封面标题）

## 设计维度
- **类型**：（选一个，附一句话理由）
- **调色板**：（选一个，附一句话理由）
- **渲染风格**：（选一个，附一句话理由）
- **文字叠加**：（标题位置+字体建议）
- **氛围**：（选一个，附一句话理由）

## AI图像生成提示词
（一段完整的英文提示词，可直接用于Midjourney/DALL-E/Stable Diffusion。
包含：主体描述、构图、光线、色彩、风格、画质关键词。
结尾加上 --ar 16:9 --style raw --v 6.1 等参数建议。）
"""

# ============================================================
# Public API
# ============================================================


def generate_cover_prompt(
    product_name: str,
    category: str = "",
    persona: str = "折腾到吐",
    cover_suggestion: str = "",
    product_description: str = "",
    style: str = "douyin_tech_review",
) -> str:
    """Use DeepSeek API to expand a cover concept into a full 5-dimension design prompt.

    Args:
        product_name: Name of the product (e.g., "红魔11SPro")
        category: Product category (e.g., "phone", "keyboard", "laptop")
        persona: Content creator persona (e.g., "折腾到吐", "好设牛啊", "朋克")
        cover_suggestion: Optional cover idea from the brief analysis
        product_description: Optional longer product description for context
        style: Content style hint (e.g., "douyin_tech_review")

    Returns:
        Structured markdown string containing:
        - 封面标题 (cover title)
        - 设计维度 (5 design dimensions)
        - AI图像生成提示词 (English image generation prompt)
    """
    if not DEEPSEEK_API_KEY:
        raise ValueError("DeepSeek API key not configured. Set DEEPSEEK_API_KEY in .env")

    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

    user_message = _build_user_message(
        product_name=product_name,
        category=category,
        persona=persona,
        cover_suggestion=cover_suggestion,
        product_description=product_description,
        style=style,
    )

    logger.info("Generating cover prompt: product=%s, persona=%s, category=%s",
                 product_name, persona, category)

    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": COVER_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=0.9,
        max_tokens=2048,
    )

    raw = response.choices[0].message.content
    logger.info("Cover prompt generated: %d chars", len(raw))
    return raw


def save_cover_prompt(
    prompt_text: str,
    product_name: str,
    output_dir: Path | None = None,
) -> Path:
    """Save the cover prompt to a text file.

    Args:
        prompt_text: The generated cover prompt markdown text
        product_name: Product name used for filename
        output_dir: Optional output directory (defaults to PROJECT_ROOT/output/covers)

    Returns:
        Path to the saved file
    """
    if output_dir is None:
        output_dir = PROJECT_ROOT / "output" / "covers"

    output_dir.mkdir(parents=True, exist_ok=True)

    safe_name = sanitize_filename(product_name)
    filepath = output_dir / f"{safe_name}-cover-prompt.txt"
    filepath.write_text(prompt_text, encoding="utf-8")

    logger.info("Cover prompt saved: %s", filepath)
    return filepath


# ============================================================
# Internal helpers
# ============================================================


def _build_user_message(
    product_name: str,
    category: str,
    persona: str,
    cover_suggestion: str,
    product_description: str,
    style: str,
) -> str:
    """Build the user prompt from the given inputs."""

    # Map category codes to Chinese names for better LLM context
    category_names = {
        "phone": "手机",
        "keyboard": "键盘",
        "mouse": "鼠标",
        "monitor": "显示器",
        "gpu": "显卡",
        "laptop": "笔记本",
        "headphone": "耳机",
        "desk_chair": "电竞桌椅",
        "speaker": "音箱",
    }

    # Map persona to creator style context
    persona_styles = {
        "折腾到吐": "硬核技术流数码博主，重数据重实测，标题党风格，节奏快。封面通常带有强烈的价格对比或性能冲击。",
        "好设牛啊": "设计美学导向的数码博主，关注产品颜值和做工。封面强调产品设计感和视觉美感。",
        "朋克": "游戏宅朋克风数码博主，二次元/电竞调性。封面燃向、热血、电竞氛围浓厚。",
        "超机懂": "极客懂王，技术深度解说。封面偏极简专业风，重数据和对比。",
    }

    style_hints = {
        "douyin_tech_review": "抖音科技评测风格：高信息密度、视觉冲击力强、标题大字醒目",
        "bilibili_review": "B站评测风格：细节丰富、构图精致、可适当增加趣味元素",
        "xiaohongshu": "小红书种草风格：氛围感强、色调柔和、突出生活场景和使用体验",
    }

    lines = [
        f"请为以下产品设计一张封面图：",
        f"",
        f"**产品名称**：{product_name}",
    ]

    cat_cn = category_names.get(category, category)
    if cat_cn:
        lines.append(f"**产品品类**：{cat_cn}")

    persona_desc = persona_styles.get(persona, "")
    if persona_desc:
        lines.append(f"**博主风格**：{persona} — {persona_desc}")

    style_desc = style_hints.get(style, "")
    if style_desc:
        lines.append(f"**平台风格**：{style_desc}")

    if cover_suggestion:
        lines.append(f"**甲方封面建议**：{cover_suggestion}")

    if product_description:
        # Truncate if too long to avoid blowing up the prompt
        desc = product_description[:500]
        lines.append(f"**产品补充信息**：{desc}")

    lines.append("")
    lines.append("请根据以上信息，用5维设计方法论生成封面设计提示词。")

    return "\n".join(lines)
