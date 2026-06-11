# 赛博瑞 · 数据驱动内容工厂

> 取其精华，去其糟粕。每一步都基于数据做决策，不是凭感觉。

短视频创作者的AI全栈工具箱。从客户Brief到成片分镜，全链路自动化。

**v1.0.0** | 71次提交 | 60模块 · 16,485行Python | 568知识库chunks · 10品类 | 12条铁律 · 4人设 | 5种评测格式

---
## 能做什么

```
甲方Brief → 文案生成(4人设+5格式+观点注入) → 12项审核+自动修复 → Docx定稿
                                                       ↓
                                                  分镜生成(10列xlsx+灯位SVG)
                                                       ↓
                                              AI点映团(audit --audience)
```

**文案引擎**：模仿D先生写作风格，支持4人设(折腾到吐/好设牛啊/朋克/超机懂)、10品类、12条铁律。5种格式：评测体(review)/榜单体(tierlist)/对比体(comparison)/HKRR(hkrr)/HAM-D(hamd)。支持`--brief`(Brief解析)、`--perspective`(观点注入)、`--format-ref`(甲方参考格式)，输出真正docx。

**分镜引擎**：北电教材标准，10列专业xlsx(AI视觉钩子)，运镜强制分配(固定≤40%)，灯位SVG俯视图。支持`--columns`(口头描述列)、`--preview`(秒级预览)。

**审核引擎**：12项自动检查(口语化、电商味、流水账、禁用词、态度密度、节奏等)，不合格自动修复(`auto-fix`循环)。`--audience`模式启动AI点映团(模拟目标观众反馈)。

**竞品学习**：B站搜索→下载→Whisper转录→OpenCV视觉分析→librosa音频分析→LLM深度解读→Karpathy Wiki知识复利。

**选题日报**(`topic-daily`)：自动追踪品类热点，生成选题建议日报。

**管线分析**(`analytics`)：全链路数据追踪+交叉矩阵，透视文案/分镜/审核各环节质量。

**封面设计**(`cover`)：AI生成短视频封面图，支持多风格多尺寸。

**引导向导**(`init`)：交互式项目初始化，自动配置知识库和工作环境。

---

## 快速开始

### 环境要求
- Python 3.12+
- Git
- DeepSeek API Key ([申请地址](https://platform.deepseek.com))

### 安装

```bash
git clone https://github.com/Warriors999/saiborui.git
cd saiborui
cp .env.example .env
# 编辑 .env，填入你的 DEEPSEEK_API_KEY
pip install -r requirements.txt
```

### 初始化知识库

```bash
# 将你的历史脚本(docx/xlsx)放入 2025text/ 目录
python -m rag_system init     # 引导向导(推荐首次使用)
python -m rag_system ingest   # 若已有数据可跳过init直接接入
python -m rag_system stats    # 查看索引状态
```

### 生成第一支脚本

```bash
python -m rag_system generate \
  --product "你的产品名" \
  --category "keyboard" \
  --persona "折腾到吐" \
  --key-points "卖点1,卖点2,卖点3" \
  --duration 2.5 \
  --format review \
  --brief "客户Brief路径或文字"
# 输出: output/scripts/产品名-人设.docx
```

### 出分镜

```bash
python -m rag_system generate-storyboard \
  "output/scripts/你的脚本.docx" \
  "产品名" \
  "折腾到吐"
# 输出: output/storyboards/产品名-xx.xlsx + 灯位SVG

# 直接出分镜(跳过文案):
python -m rag_system storyboard \
  --product "产品名" \
  --persona "折腾到吐" \
  --key-points "卖点1,卖点2" \
  --columns  # 生成口头描述列
```

### 审核

```bash
python -m rag_system audit "output/scripts/你的脚本.docx"
python -m rag_system audit "output/storyboards/分镜.xlsx" --audience  # AI点映团
```

### 竞品学习

```bash
python -m rag_system competitive search --category keyboard --top 3
python -m rag_system competitive report  # 生成周报
```

### 其他工具

```bash
python -m rag_system analytics            # 管线分析+交叉矩阵
python -m rag_system cover --product "产品名"  # 封面设计
python -m rag_system topic-daily          # 选题日报
python -m rag_system dashboard            # 启动Web控制台
python -m rag_system outputs              # 输出文件管理
```

---

## 项目结构

```
赛博瑞/
├── rag_system/           # 核心引擎(60模块, ~16,485行)
│   ├── generation/       # 文案+分镜+审核+封面
│   ├── competitive/      # 竞品学习管线
│   ├── retrieval/        # RAG语义检索
│   ├── embedding/        # BGE向量嵌入
│   ├── storage/          # ChromaDB向量库
│   ├── chunking/         # 文档分块
│   └── ingest/           # 文档解析
├── tests/                # 自动化测试(5文件, 59项冒烟测试)
├── wiki/                 # Karpathy Wiki知识页(568 chunks, 10品类)
├── output/               # 输出目录
│   ├── scripts/          # 文案docx
│   ├── storyboards/      # 分镜xlsx+灯位SVG
│   ├── audits/           # 审核报告
│   ├── competitive/      # 竞品分析
│   ├── covers/           # 封面图
│   ├── briefs/           # Brief解析结果
│   └── dashboard.html    # Web控制台
├── 2025text/             # 历史文档(知识库源)
├── requirements.txt
└── .env.example
```

## 命令行参考

| 命令 | 用途 |
|------|------|
| `rag_system init` | 引导向导(交互式初始化) |
| `rag_system generate` | 生成文案(Brief→docx) |
| `rag_system generate-storyboard` | 定稿→分镜(9列xlsx) |
| `rag_system storyboard` | RAG分镜(从Brief直出) |
| `rag_system audit` | 审核脚本/分镜(含AI点映团) |
| `rag_system search` | 语义搜索知识库 |
| `rag_system stats` | 知识库统计 |
| `rag_system competitive` | 竞品搜索/分析/周报 |
| `rag_system analytics` | 管线分析+交叉矩阵 |
| `rag_system cover` | 封面设计 |
| `rag_system dashboard` | 启动Web控制台 |
| `rag_system topic-daily` | 选题日报 |
| `rag_system outputs` | 输出文件管理 |

---

## 专业方法论

所有规则均有出处，不再凭感觉：

- **文案**: Claude Hopkins《Scientific Advertising》(1923), David Ogilvy《Confessions of an Advertising Man》(1963), 抖音爆款文案分析(新榜2025)
- **分镜**: 北电《电影摄影画面创作》张会军(2021), 《电影摄影造型技巧》巩如梅(2023), Apple/Manfrotto商业产品视频规范
- **灯位**: 北电《电影摄影画面创作》光线章节, 影视照明技术标准

---

## License

MIT
