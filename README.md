# Legacy Code Modernization — Agentic AI Pipeline

An agentic legacy-code modernization pipeline built with Python, LangGraph, Azure OpenAI, Tree-sitter, FastAPI, Pydantic, Pytest, and Streamlit.

## Pipeline

Legacy Source → Parser → Supervisor Agent → Splitting / Documentation / Evaluation / Coding / Testing → Dashboard & Reports

The Supervisor Agent makes state-driven routing decisions instead of relying only on a fixed sequence.

## What it demonstrates

- Legacy source parsing with Tree-sitter
- Agentic orchestration with LangGraph
- LLM-assisted documentation and Gherkin generation
- Evaluation and feedback loops
- Modern FastAPI code generation
- Automated testing and reporting
- Streamlit dashboard artifacts
- OpenAPI generation

## Setup

```bash
python -m venv .venv
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and add your own Azure OpenAI credentials. Never commit `.env` or API keys.

Run the pipeline with:

```bash
python run_pipeline.py
```

## Security

The repository intentionally excludes `.env`, virtual environments, caches, and local runtime databases.

## Disclaimer

Generated code and tests should be reviewed and validated before production use.
