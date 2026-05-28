# 赛博瑞 · 数据驱动内容工厂

> 取其精华，去其糟粕。每一步都基于数据做决策，不是凭感觉。

短视频创作者的AI全栈工具箱。从客户Brief到成片分镜，全链路自动化。

**v1.0.0** | 568知识库chunks | 8品类 | 17次迭代

---

## 能做什么

```
甲方Brief → 文案生成(4人设+3格式) → 14项审核 → Docx定稿
                                              ↓
                                         分镜生成(9列xlsx)
                                              ↓
                                    灯位SVG + 运镜强制分配
```

**文案引擎**：模仿D先生写作风格，支持4人设(折腾到吐/好设牛啊/朋克/超机懂)、8品类、10条铁律。3种格式：评测体/榜单体/对比体。

**分镜引擎**：北电教材标准，9列专业xlsx，运镜强制分配(固定≤40%)，灯位SVG俯视图。

**审核引擎**：14项自动检查(口语化、电商味、流水账、禁用词、态度密度、节奏等)，不合格自动修复。

**竞品学习**：B站搜索→下载→Whisper转录→OpenCV视觉分析→librosa音频分析→LLM深度解读→Karpathy Wiki知识复利。

---

## 快速开始

### 环境要求
- Python 3.12+
- Git
- DeepSeek API Key ([申请地址](https://platform.deepseek.com))

### 安装

```bash
git clone https://github.com/Warriors999/saibotao.git
cd saibotao
cp .env.example .env
# 编辑 .env，填入你的 DEEPSEEK_API_KEY
pip install -r requirements.txt
```

### 初始化知识库

```bash
# 将你的历史脚本(docx/xlsx)放入 2025text/ 目录
python -m rag_system ingest
python -m rag_system stats  # 查看索引状态
```

### 生成第一支脚本

```bash
python -m rag_system generate \
  --product "你的产品名" \
  --category "keyboard" \
  --persona "折腾到吐" \
  --key-points "卖点1,卖点2,卖点3" \
  --duration 2.5
# 输出: output/scripts/产品名-人设.docx
```

### 出分镜

```bash
python -m rag_system generate-storyboard \
  "output/scripts/你的脚本.docx" \
  "产品名" \
  "折腾到吐"
# 输出: output/storyboards/产品名-xx.xlsx + 灯位SVG
```

### 竞品学习

```bash
python -m rag_system competitive search --category keyboard --top 3
python -m rag_system competitive report  # 生成周报
```

---

## 项目结构

```
赛博瑞/
├── rag_system/           # 核心引擎(40模块, ~7600行)
│   ├── generation/       # 文案+分镜+审核
│   ├── competitive/      # 竞品学习管线
│   ├── retrieval/        # RAG语义检索
│   ├── embedding/        # BGE向量嵌入
│   ├── storage/          # ChromaDB向量库
│   └── ingest/           # 文档解析
├── wiki/                 # Karpathy Wiki知识页
├── output/               # 输出目录
│   ├── scripts/          # 文案docx
│   ├── storyboards/      # 分镜xlsx+灯位SVG
│   ├── audits/           # 审核报告
│   ├── competitive/      # 竞品分析
│   └── dashboard.html    # Web控制台
├── 2025text/             # 历史文档(知识库源)
└── requirements.txt
```

## 命令行参考

| 命令 | 用途 |
|------|------|
| `rag_system generate` | 生成文案 |
| `rag_system generate-storyboard` | 定稿→分镜 |
| `rag_system storyboard` | RAG分镜(从Brief) |
| `rag_system audit` | 审核脚本/分镜 |
| `rag_system search` | 语义搜索知识库 |
| `rag_system stats` | 知识库统计 |
| `rag_system competitive search` | 竞品搜索+分析 |
| `rag_system competitive report` | 竞品周报 |

---

## 专业方法论

所有规则均有出处，不再凭感觉：

- **文案**: Claude Hopkins《Scientific Advertising》(1923), David Ogilvy《Confessions of an Advertising Man》(1963), 抖音爆款文案分析(新榜2025)
- **分镜**: 北电《电影摄影画面创作》张会军(2021), 《电影摄影造型技巧》巩如梅(2023), Apple/Manfrotto商业产品视频规范
- **灯位**: 北电《电影摄影画面创作》光线章节, 影视照明技术标准

---

## License

MIT
