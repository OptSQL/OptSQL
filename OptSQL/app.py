"""Application entrypoint for the multi-agent text-to-SQL workflow."""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import sqlglot
import sqlglot.expressions as exp

from agent.controller import MetaCognitiveController
from agent.schemaFilterAgent import EvidenceGuidedSchemaFilterAgent
from agent.sqlBuilderAgent import InitialSQLBuilderAgent
from myTypes import AgentRequest
from myTypes import AgentTask
from myTypes import FinalAnswer
from utils.db import register_database_path
from utils.schema_grounding import build_sqlite_metadata_from_ddl
from utils.schema_grounding import register_database_metadata
from utils.sql_comparison import compare_with_semantic_correction
from utils.tasks import get_bird_task_by_question_id
from utils.tasks import load_bird_tasks


class MultiAgentApplication:
    """Root facade for launching the full multi-agent workflow."""

    def __init__(
        self,
        controller: MetaCognitiveController,
        *,
        schema_filter: EvidenceGuidedSchemaFilterAgent | None = None,
        sql_builder: InitialSQLBuilderAgent | None = None,
    ) -> None:
        self.controller = controller
        self.schema_filter = schema_filter or EvidenceGuidedSchemaFilterAgent()
        self.sql_builder = sql_builder or InitialSQLBuilderAgent()
        self.last_schema_response = None
        self.last_sql_response = None
        self.last_controller_response = None
        self.last_final_answer = None
        self.last_artifacts: dict[str, Any] = {}

    def run(self, task: AgentTask, *, gold_sql: str | None = None) -> FinalAnswer:
        """Run SchemaFilter -> SQLBuilder -> Controller for one task."""
        self.last_schema_response = None
        self.last_sql_response = None
        self.last_controller_response = None
        self.last_final_answer = None
        self.last_artifacts = {}

        schema_response = self.schema_filter.run(
            AgentRequest(
                request_id=f"schema-filter-{task.task_id}",
                task=task,
                runtime_state={},
                input_artifacts={},
                constraints={},
            )
        )
        self.last_schema_response = schema_response
        if schema_response.status != "success":
            raise RuntimeError(
                "SchemaFilter failed: " + "; ".join(schema_response.errors)
            )

        blueprint = schema_response.output_artifacts["blueprint"]
        sql_input_artifacts: dict[str, Any] = {"blueprint": blueprint}
        if gold_sql:
            sql_input_artifacts["gold_sql"] = gold_sql
        sql_response = self.sql_builder.run(
            AgentRequest(
                request_id=f"sql-builder-{task.task_id}",
                task=task,
                runtime_state={},
                input_artifacts=sql_input_artifacts,
                constraints={},
            )
        )
        self.last_sql_response = sql_response
        if sql_response.status != "success":
            raise RuntimeError("SQLBuilder failed: " + "; ".join(sql_response.errors))

        sql_version = sql_response.output_artifacts["sql_version"]
        planning_gate = _planning_gate_decision(
            task=task,
            gold_sql=gold_sql,
            generated_sql=sql_version.sql,
            schema_artifacts=schema_response.output_artifacts,
            sql_artifacts=sql_response.output_artifacts,
        )
        if planning_gate["action"] == "stop":
            final_answer = FinalAnswer(
                sql=sql_version.sql,
                selected_schema=[
                    f"{column.table_name}.{column.column_name}"
                    for column in blueprint.selected_columns
                ],
                value_bindings=[
                    f"{mapping.keyword} -> {mapping.table_name}.{mapping.column_name}={mapping.value}"
                    for mapping in blueprint.value_mappings
                ],
                join_path=[
                    f"{edge.source_table}.{edge.source_column} -> "
                    f"{edge.target_table}.{edge.target_column}"
                    for edge in blueprint.join_topology.edges
                ],
                optimization_steps=[],
                validation_summary="planning_failed",
                performance_summary="not_available",
                caveats=[planning_gate["reason"]],
            )
            self.last_final_answer = final_answer
            self.last_artifacts = {
                "schema": schema_response.output_artifacts,
                "sql_builder": sql_response.output_artifacts,
                "planning_gate": planning_gate,
                "controller": {},
                "final_answer": final_answer,
            }
            return final_answer

        controller_response = self.controller.run(
            AgentRequest(
                request_id=f"controller-{task.task_id}",
                task=task,
                runtime_state={},
                input_artifacts={
                    "blueprint": blueprint,
                    "sql_version": sql_version,
                    "execution_metrics": sql_response.output_artifacts.get(
                        "execution_metrics"
                    ),
                },
                constraints={},
            )
        )
        self.last_controller_response = controller_response
        if controller_response.status != "success":
            raise RuntimeError(
                "Controller failed: " + "; ".join(controller_response.errors)
            )

        self.last_artifacts = {
            "schema": schema_response.output_artifacts,
            "sql_builder": sql_response.output_artifacts,
            "planning_gate": planning_gate,
            "controller": controller_response.output_artifacts,
        }
        self.last_final_answer = controller_response.output_artifacts["final_answer"]
        return self.last_final_answer


def build_controller() -> MetaCognitiveController:
    """Create and wire the meta-cognitive controller and submodules."""
    return MetaCognitiveController()


def build_application(
    *,
    split: str = "dev",
    controller: MetaCognitiveController | None = None,
) -> MultiAgentApplication:
    """Create the full workflow facade."""
    return MultiAgentApplication(
        controller or build_controller(),
        schema_filter=EvidenceGuidedSchemaFilterAgent(split=split),
        sql_builder=InitialSQLBuilderAgent(max_repair_attempts=3),
    )


def main(argv: list[str] | None = None) -> int:
    """Run one BIRD task through the full pipeline."""
    args = _parse_args(argv)
    pipeline_path = Path(args.pipeline_out)
    sql_path = Path(args.sql_out)
    pipeline_path.parent.mkdir(parents=True, exist_ok=True)
    sql_path.parent.mkdir(parents=True, exist_ok=True)
    sql_path.write_text("", encoding="utf-8")

    with pipeline_path.open("w", encoding="utf-8") as pipeline_file:
        with contextlib.redirect_stdout(pipeline_file), contextlib.redirect_stderr(
            pipeline_file
        ):
            try:
                final_answer = _run_from_args(args)
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 1
            sql_path.write_text(final_answer.sql.strip() + "\n", encoding="utf-8")
            return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", default="dev", choices=["dev", "train"])
    parser.add_argument(
        "--task-position",
        type=int,
        default=1,
        help="1-based task position in the selected split. Ignored when --question-id is set.",
    )
    parser.add_argument("--question-id", type=int, default=None)
    parser.add_argument(
        "--db-path",
        default=None,
        help="SQLite database path for a custom task. Requires --question.",
    )
    parser.add_argument(
        "--db-id",
        default=None,
        help="Custom database id. Defaults to a normalized --db-path stem.",
    )
    parser.add_argument(
        "--question",
        default=None,
        help="Natural-language question for a custom task. Requires --db-path.",
    )
    parser.add_argument(
        "--evidence",
        default=None,
        help="Optional evidence/hint text for a custom task.",
    )
    parser.add_argument(
        "--task-id",
        default=None,
        help="Optional task id for a custom task.",
    )
    parser.add_argument(
        "--gold-sql",
        default=None,
        help="Optional gold SQL for custom-task VES/planning-gate evaluation.",
    )
    parser.add_argument("--pipeline-out", default="pipeline.out")
    parser.add_argument("--sql-out", default="sql.out")
    args = parser.parse_args(argv)
    if args.task_position < 1:
        parser.error("--task-position must be >= 1")
    custom_mode = any(
        value is not None
        for value in (
            args.db_path,
            args.db_id,
            args.question,
            args.evidence,
            args.task_id,
            args.gold_sql,
        )
    )
    if custom_mode:
        if not args.db_path:
            parser.error("--db-path is required for a custom task")
        if not args.question or not args.question.strip():
            parser.error("--question is required for a custom task")
        if args.question_id is not None:
            parser.error("--question-id cannot be used with custom task arguments")
    return args


def _run_from_args(args: argparse.Namespace) -> FinalAnswer:
    if args.db_path:
        return _run_custom_from_args(args)

    bird_task = _select_bird_task(args.split, args.task_position, args.question_id)
    task = AgentTask(
        task_id=f"{args.split}-position-{args.task_position}-qid-{bird_task.question_id}",
        question_id=bird_task.question_id,
        db_id=bird_task.db_id,
        question=bird_task.question,
        evidence=bird_task.evidence,
        dbms="sqlite",
        user_constraints={},
    )
    application = build_application(split=args.split)
    started_at = time.monotonic()
    print(
        json.dumps(
            {
                "event": "task_selected",
                "split": args.split,
                "task_position": args.task_position,
                "question_id": bird_task.question_id,
                "db_id": bird_task.db_id,
                "question": bird_task.question,
                "evidence": bird_task.evidence,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    final_answer = application.run(task, gold_sql=bird_task.sql)
    _print_pipeline_summary(application, elapsed_seconds=time.monotonic() - started_at)
    return final_answer


def _run_custom_from_args(args: argparse.Namespace) -> FinalAnswer:
    db_path = Path(args.db_path).expanduser().resolve()
    db_id = args.db_id.strip() if args.db_id else _db_id_from_path(db_path)
    metadata, description_metadata = build_sqlite_metadata_from_ddl(db_id, db_path)
    register_database_path(db_id, db_path)
    register_database_metadata(db_id, metadata, description_metadata)

    task = AgentTask(
        task_id=args.task_id or f"custom-{db_id}",
        question_id=None,
        db_id=db_id,
        question=args.question.strip(),
        evidence=args.evidence,
        dbms="sqlite",
        user_constraints={"db_path": str(db_path)},
    )
    application = build_application(split=args.split)
    started_at = time.monotonic()
    print(
        json.dumps(
            {
                "event": "custom_task_selected",
                "split": args.split,
                "task_id": task.task_id,
                "db_id": db_id,
                "db_path": str(db_path),
                "question": task.question,
                "evidence": task.evidence,
                "metadata_source": "sqlite_ddl",
                "table_count": len(metadata.get("table_names_original", [])),
                "column_count": max(0, len(metadata.get("column_names_original", [])) - 1),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    final_answer = application.run(task, gold_sql=args.gold_sql)
    _print_pipeline_summary(application, elapsed_seconds=time.monotonic() - started_at)
    return final_answer


def _db_id_from_path(db_path: Path) -> str:
    db_id = re.sub(r"[^A-Za-z0-9_]+", "_", db_path.stem).strip("_").lower()
    return db_id or "custom_db"


def _select_bird_task(split: str, task_position: int, question_id: int | None):
    if question_id is not None:
        return get_bird_task_by_question_id(split, question_id)
    tasks = load_bird_tasks(split)
    if task_position > len(tasks):
        raise ValueError(
            f"--task-position {task_position} is beyond split size {len(tasks)}"
        )
    return tasks[task_position - 1]


def _planning_gate_decision(
    *,
    task: AgentTask,
    gold_sql: str | None,
    generated_sql: str,
    schema_artifacts: dict[str, Any],
    sql_artifacts: dict[str, Any],
) -> dict[str, Any]:
    ves_metric = sql_artifacts.get("ves_metric")
    if gold_sql is None or ves_metric is None:
        return {
            "action": "continue",
            "reason": "No gold SQL/VES metric available for planning gate.",
        }
    if getattr(ves_metric, "valid", False) or float(getattr(ves_metric, "score", 0.0)) != 0.0:
        return {
            "action": "continue",
            "reason": "Planning SQL passed EX/VES gate.",
            "ves_valid": getattr(ves_metric, "valid", None),
            "ves_score": getattr(ves_metric, "score", None),
        }

    comparison, corrected_comparison, correction_log = compare_with_semantic_correction(
        gold_sql=gold_sql,
        generated_sql=generated_sql,
        db_id=task.db_id,
        schema_filter_artifacts=schema_artifacts,
    )
    corrections = list(correction_log.corrections)
    column_name_ambiguity = _has_column_name_ambiguity(gold_sql, generated_sql)
    if (
        corrections and corrected_comparison is not None and corrected_comparison.equivalent
    ) or column_name_ambiguity:
        return {
            "action": "continue",
            "reason": (
                "Planning EX=false/VES=0.0 is attributable to column-name "
                "semantic ambiguity; continue to Controller."
            ),
            "ves_valid": getattr(ves_metric, "valid", None),
            "ves_score": getattr(ves_metric, "score", None),
            "comparison_diff": comparison.diff_summary,
            "column_name_ambiguity": column_name_ambiguity,
            "corrections": [str(correction) for correction in corrections],
        }

    return {
        "action": "stop",
        "reason": (
            "Planning EX=false and VES=0.0 for a reason other than resolvable "
            "column-name semantic ambiguity; stop before Optimization."
        ),
        "ves_valid": getattr(ves_metric, "valid", None),
        "ves_score": getattr(ves_metric, "score", None),
        "comparison_diff": comparison.diff_summary,
        "column_name_ambiguity": column_name_ambiguity,
        "corrections": [str(correction) for correction in corrections],
    }


def _has_column_name_ambiguity(gold_sql: str, generated_sql: str) -> bool:
    gold_columns = _top_level_select_column_names(gold_sql)
    generated_columns = _top_level_select_column_names(generated_sql)
    if not gold_columns or len(gold_columns) != len(generated_columns):
        return False
    return any(
        gold != generated and _similar_column_name(gold, generated)
        for gold, generated in zip(gold_columns, generated_columns)
    )


def _top_level_select_column_names(sql: str) -> list[str]:
    try:
        ast = sqlglot.parse_one(sql, dialect="sqlite")
    except Exception:
        return []
    select = ast if isinstance(ast, exp.Select) else ast.find(exp.Select)
    if select is None:
        return []
    names: list[str] = []
    for expression in select.expressions:
        column = expression.find(exp.Column)
        if column is not None:
            names.append(_normalize_column_name(column.name))
        elif expression.output_name:
            names.append(_normalize_column_name(expression.output_name))
        else:
            return []
    return names


def _similar_column_name(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return left in right or right in left


def _normalize_column_name(name: str) -> str:
    return "".join(character for character in name.lower() if character.isalnum())


def _print_pipeline_summary(
    application: MultiAgentApplication,
    *,
    elapsed_seconds: float,
) -> None:
    schema_response = application.last_schema_response
    sql_response = application.last_sql_response
    controller_response = application.last_controller_response
    controller_artifacts = controller_response.output_artifacts if controller_response else {}
    runtime_state = controller_artifacts.get("runtime_state")
    final_answer = application.last_final_answer or controller_artifacts.get("final_answer")
    summary = {
        "event": "pipeline_finished",
        "elapsed_seconds": round(elapsed_seconds, 3),
        "schema_filter": _response_summary(schema_response),
        "sql_builder": _response_summary(sql_response),
        "planning_gate": application.last_artifacts.get("planning_gate", {}),
        "controller": _response_summary(controller_response),
        "task_complexity": controller_artifacts.get("task_complexity"),
        "db_scale": controller_artifacts.get("db_scale"),
        "plan_decision": controller_artifacts.get("plan_decision"),
        "runtime_state": {
            "status": getattr(runtime_state, "status", None),
            "strategy": getattr(runtime_state, "strategy", None),
            "complexity_score": getattr(runtime_state, "complexity_score", None),
            "iteration": getattr(runtime_state, "iteration", None),
            "best_sql_version_id": getattr(runtime_state, "best_sql_version_id", None),
            "sql_version_count": len(getattr(runtime_state, "sql_versions", []) or []),
        },
        "final_answer": final_answer,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


def _response_summary(response) -> dict:
    if response is None:
        return {}
    return {
        "agent": response.agent_name,
        "status": response.status,
        "reasoning_summary": response.reasoning_summary,
        "errors": response.errors,
        "tool_calls": response.tool_calls,
    }


if __name__ == "__main__":
    raise SystemExit(main())
