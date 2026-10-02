"""Coordinator for SQL generation, syntax revision, and selection."""

from __future__ import annotations

from typing import Callable

from agent.sqlBuilderAgent.generation_methods.few_shots import BirdFewShotStore
from agent.sqlBuilderAgent.generation_methods.generators import CandidateSQLGenerator
from agent.sqlBuilderAgent.generation_methods.models import GenerationResult
from agent.sqlBuilderAgent.generation_methods.prompts import build_mode_selection_prompt
from agent.sqlBuilderAgent.json_parser import parse_json_object
from agent.sqlBuilderAgent.generation_methods.revision import SyntaxOnlyReviser
from agent.sqlBuilderAgent.generation_methods.selection import ConsistencySelector
from agent.sqlBuilderAgent.generation_methods.utils import build_blueprint_schema_profile
from myTypes import VerifiedContextBlueprint


LLMTextFn = Callable[[str], str]


class SQLGenerationPipeline:
    """Generate candidate SQLs, run syntax-only revision, and select one SQL."""

    def __init__(
        self,
        *,
        enabled_methods: tuple[str, ...] | None = None,
        few_shot_store: BirdFewShotStore | None = None,
    ) -> None:
        self.enabled_methods = enabled_methods
        self.few_shot_store = few_shot_store or BirdFewShotStore()
        self.reviser = SyntaxOnlyReviser()
        self.selector = ConsistencySelector()

    def run(
        self,
        *,
        blueprint: VerifiedContextBlueprint,
        question: str,
        evidence: str | None,
        db_id: str,
        question_id: int | str | None = None,
        llm_text: LLMTextFn,
    ) -> GenerationResult:
        schema_profile = build_blueprint_schema_profile(blueprint)
        few_shot_examples = self.few_shot_store.get_examples(question_id)
        mode_prompt = ""
        mode_response = ""
        mode_error = None
        if self.enabled_methods is None:
            base = "icl" if few_shot_examples else "skeleton"
            methods = (base,)
            mode_prompt = build_mode_selection_prompt(
                schema_profile=schema_profile,
                question=question,
                evidence=evidence,
                few_shot_examples=few_shot_examples,
            )
            try:
                mode_response = llm_text(mode_prompt)
                modes = parse_json_object(mode_response).get("modes")
                allowed = {"icl", "skeleton", "divide_and_conquer"}
                if not isinstance(modes, list) or not modes or any(
                    not isinstance(mode, str) or mode not in allowed for mode in modes
                ):
                    raise ValueError("modes must be a non-empty list of supported mode names.")
                methods = tuple(dict.fromkeys(
                    [base] + [mode for mode in modes if mode != "icl" or few_shot_examples]
                ))
            except Exception as exc:
                mode_error = str(exc)
        else:
            methods = tuple(
                method for method in self.enabled_methods
                if method != "icl" or few_shot_examples
            )
        generator = CandidateSQLGenerator(enabled_methods=methods)
        raw_candidates, generation_prompts, generation_responses = generator.generate(
            schema_profile=schema_profile,
            question=question,
            evidence=evidence,
            few_shot_examples=few_shot_examples,
            llm_text=llm_text,
        )
        if not raw_candidates:
            raise ValueError("SQL generation methods produced no candidates.")

        revised_candidates, revision_prompts, revision_responses = self.reviser.revise(
            candidates=raw_candidates,
            db_id=db_id,
            schema_profile=schema_profile,
            question=question,
            evidence=evidence,
            llm_text=llm_text,
        )
        selected, trace = self.selector.select(
            candidates=revised_candidates or raw_candidates,
            db_id=db_id,
        )
        return GenerationResult(
            selected_sql=selected.sql,
            raw_candidates=raw_candidates,
            revised_candidates=revised_candidates,
            selected_candidate=selected,
            prompts={
                **({"mode_selection": mode_prompt} if mode_prompt else {}),
                **generation_prompts, **revision_prompts,
            },
            raw_responses={
                **({"mode_selection": mode_response} if mode_prompt else {}),
                **generation_responses, **revision_responses,
            },
            selection_trace=trace,
            selected_methods=list(methods),
            mode_selection_error=mode_error,
        )
