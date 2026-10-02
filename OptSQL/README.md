
# OptSQL

## Repository Structure

```text
.
├── app.py                         # Main single-task pipeline entry point
├── config.py                      # Project paths and OpenAI-compatible endpoint routing
├── myTypes.py                     # Shared dataclasses and pipeline contracts
├── agent/
│   ├── schemaFilterAgent/         # Evidence-guided schema/value/join grounding
│   ├── sqlBuilderAgent/           # Initial SQL generation and execution repair
│   ├── explainAnalyserAgent/      # Plan normalization, capability checks, and bottleneck analysis
│   ├── controller.py              # Meta-cognitive orchestration and retry logic
│   ├── sql_rewriter.py            # SQL rewrite engine, RAG integration, LLM rewrite hooks
│   ├── validator.py               # Execution and semantic validation
│   ├── rag.py                     # Rewrite knowledge-base storage and retrieval
│   └── rewrite_operators/         # Deterministic rewrite rule detection and models
├── utils/
│   ├── db.py                      # SQLite DB resolution for BIRD, EESQLBench, and custom DBs
│   ├── openai_client.py           # OpenAI-compatible chat wrapper and token/request capture
│   ├── schema_grounding.py        # BIRD/custom schema metadata and value probing
│   ├── sql_comparison.py          # Semantic comparison and correction helpers
│   └── sql_safety.py              # SQL safety guards
├── scripts/
│   ├── eval_optimization_loop.py  # Batch optimization-loop evaluator
│   ├── run_full_eval.py           # Full optimization evaluation with logs and resume
├── data/
│   └── dev_20240627/              # BIRD dev metadata and row-count cache
└── tools/sqlite_scanstatus/       # Optional SQLite scanstatus probe source/binary
```

## Installation

### Requirements

- Python `>= 3.10`
- SQLite databases for the selected benchmark
- OpenAI-compatible LLM endpoint for LLM-backed stages

### LLM Configuration

LLM requests are routed through `utils/openai_client.py` and `config.py`.  If you need different default model names, change those constants or pass script-level model arguments where supported.

- For DeepSeek-style/default models:

  ```bash
  export DS_API_KEY="your-api-key"
  export DS_BASE_URL="https://your-openai-compatible-endpoint/v1"
  export DS_MAX_TOKENS=3200
  ```

- For GPT models:

  ```bash
  export OPENAI_API_KEY="your-api-key"
  export OPENAI_GPT_BASE_URL="https://your-openai-compatible-endpoint/v1"
  export GPT5_MAX_COMPLETION_TOKENS=3200
  ```

- Current model constants are defined in `config.py`:

  ```python
  DS_MODEL = "deepseek-v4-pro"
  GPT_MODEL = "gpt-5.4"
  ```

### Dataset Setup

- The default BIRD root is `./data` and dev split is expected at `./data/dev_20240627`

- Custom tasks do not need BIRD-style `dev_tables.json`. Run with `--db-path`, and the system derives metadata from SQLite DDL and PRAGMA calls:


## Quick Start

- Run one BIRD task by position

  ```bash
  python app.py \
    --split dev \
    --task-position 1 \
    --pipeline-out pipeline.out \
    --sql-out sql.out
  ```

	`--task-position` is 1-based and is ignored when `--question-id` is provided.

- Run one BIRD task by question ID

  ```bash
  python app.py \
    --split dev \
    --question-id 28 \
    --pipeline-out pipeline.out \
    --sql-out sql.out
  ```
