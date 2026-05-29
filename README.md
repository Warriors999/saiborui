# 赛博瑞 · 数据驱动内容工厂

> 取其精华，去其糟粕。每一步都基于数据做决策，不是凭感觉。

短视频创作者的AI全栈工具箱。从客户Brief到成片分镜，全链路自动化。

**v1.0.0** | 40模块 · 10,732行 · 42提交 | 568 chunks · 10品类 | 13条CLI · 59测试

---

## 能做什么

```
甲方Brief → 文案生成(4人设+3格式) → 14项审核 → Docx定稿
                                              ↓
                                         分镜生成(9列xlsx)
                                              ↓
                                    灯位SVG + 运镜强制分配
```

**文案引擎**：模仿D先生写作风格，支持4人设、10品类、12条铁律、5种格式(review/tierlist/comparison/hkrr/hamd)、2种模式(normal/experimental)。Brief结构化解析+封面方向注入+个人观点注入+抖音禁词过滤。

**分镜引擎**：北电教材标准，LLM拆镜+视觉对齐(英文concept prompt)+运镜强制分配(固定≤40%)+自审修复。3种输出模式：默认9列/甲方参考文件(--format-ref)/口头描述列(--columns)/秒级预览(--preview)。灯位SVG全格式支持。

**审核引擎**：15项自动检查(含信息搬运检测)。自动修复循环(最多3轮)，句级结构重写(长短句/电商味/态度密度程序化修复)。AI点映团3视角模拟审稿。

**竞品学习**：B站搜索→下载→Whisper转录→OpenCV/librosa分析→LLM解读→Karpathy Wiki知识复利。

**数据闭环**：管线事件追踪+审计闭环+人设×品类交叉效能矩阵+产出索引管理+动态仪表盘。

**选题系统**：AI每日选题日报，6维评分(热度/信息差/争议/人设匹配/实操价值/差异化)。

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
├── rag_system/           # 核心引擎(40模块, ~10700行)
├── tests/                # 测试套件(5文件, 59测试)
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
| `rag_system generate` | 生成文案 (支持--brief/--perspective) |
| `rag_system generate-storyboard` | 定稿→分镜 (--format-ref/--columns/--preview) |
| `rag_system storyboard` | RAG分镜(从Brief，支持--perspective) |
| `rag_system audit` | 审核脚本/分镜 (--audience AI点映团) |
| `rag_system search` | 语义搜索知识库 |
| `rag_system stats` | 知识库统计 |
| `rag_system init` | 首次运行引导向导 |
| `rag_system competitive search` | 竞品搜索+分析 |
| `rag_system competitive report` | 竞品周报 |
| `rag_system analytics` | 管线分析 (--matrix 交叉效能) |
| `rag_system cover` | 5维封面设计prompt |
| `rag_system dashboard` | 动态仪表盘 |
| `rag_system topic-daily` | 选题日报 |
| `rag_system outputs` | 产出管理 |

---

## 专业方法论

所有规则均有出处，不再凭感觉：

- **文案**: Claude Hopkins《Scientific Advertising》(1923), David Ogilvy《Confessions of an Advertising Man》(1963), 抖音爆款文案分析(新榜2025)
- **分镜**: 北电《电影摄影画面创作》张会军(2021), 《电影摄影造型技巧》巩如梅(2023), Apple/Manfrotto商业产品视频规范
- **灯位**: 北电《电影摄影画面创作》光线章节, 影视照明技术标准

---

## License

MIT
