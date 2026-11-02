# Saiborui · AI Content Workflow for Short-Form Video

[中文](README.md) | **English**

Saiborui is a Python toolkit for creators making short-form technology and product-review videos. It brings topic research, retrieval-augmented script writing, review, storyboarding, and competitor analysis into one workflow. It is designed primarily around Chinese-language content and the creator's existing editorial style.

**AI content creation · video script generator · storyboarding · creator tools · competitive research · RAG · DeepSeek · Python**

## What it does

- **Plan:** explore topics and learn from editorial feedback.
- **Write:** generate review, comparison, and other scripts from product details and a brief, with relevant past material retrieved as context.
- **Review:** check scripts for writing and structural issues; an optional simulated audience offers another perspective.
- **Storyboard:** turn a finalized script or product brief into a shot list and lighting diagram.
- **Research:** search and analyze comparable videos and compile reports for later reference.

```text
Topic research / product brief → RAG-assisted script → review → storyboard
                    ↑
          reference material & competitor research
```

Saiborui is an evolving project, not a substitute for editorial judgment. Outputs depend on the model, knowledge base, and supplied inputs. Verify factual claims and rights before publishing. Some features require network access, additional tools, or paid API services.

## Getting started

You need Python 3.12+, Git, and a DeepSeek API key for model-powered features. Other integrations may require their own credentials and dependencies.

```bash
git clone https://github.com/Warriors999/saiborui.git
cd saiborui
python -m venv .venv
# Activate the virtual environment for your platform, then:
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and set `DEEPSEEK_API_KEY` locally. Never commit your API keys. Run the setup wizard, then consult the command help:

```bash
python -m rag_system init
python -m rag_system --help
python -m rag_system generate --help
python -m rag_system topics --help
```

Example: generate a Chinese-language product-review script after configuring the required services and reference data:

```bash
python -m rag_system generate --product "Example keyboard" --category keyboard --key-points "compact layout,wireless" --format review
```

Review a text or Word script with `python -m rag_system audit path/to/script.docx`. Use `python -m rag_system storyboard --help` for direct storyboard generation, and `python -m rag_system competitive --help` for competitive research. The commands themselves provide the current options and supported formats.

## Project layout

| Path | Purpose |
| --- | --- |
| `rag_system/` | CLI, generation, topic research, retrieval and analysis |
| `wiki/` | Editorial knowledge and reference material |
| `tests/` | Lightweight test suite |
| `scripts/` | Supporting and historical scripts |
| `output/` | Generated artifacts; new outputs are kept local by default |

Run the local tests with `python tests/run_all.py`. This checks selected components, not every external service or end-to-end workflow.

## Contributing

Issues and focused pull requests are welcome. Describe the use case, steps to reproduce, and the environment when reporting a problem. Please do not include API keys, private briefs, or client materials.

The existing project metadata identifies the license as MIT. Check the repository's license terms before reuse and independently verify rights to any third-party material.
