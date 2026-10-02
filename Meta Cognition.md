# Appendix: Meta-Cognitive State Transitions and Prompts

This appendix follows the state names and observation labels in the state-transition diagram. Prompt blocks specify the instructions associated with each state; flow descriptions identify where their outputs are used.

## Workflow

S1 → S2 → [G1] → S3 → S4 → S5. Acceptance at S5 updates the best SQL and returns to S3; rejection enters R for recovery through S4 and S5. S2 has a local repair loop. [G1] may bypass optimization, and stopping conditions lead to F. The Memory Engine retains feedback and supports retrieval across the workflow.

## S1 · Evidence-guided Schema Filter Agent

**Flow.** Link the question to schema objects, verify values, and complete join paths; pass the verified blueprint to S2.

| Observation | Meaning |
| --- | --- |
| schema | Tables and columns relevant to the question, identified through schema linking. |
| values | Database-grounded values used to construct query predicates. |
| join paths | Key relationships and intermediate tables connecting the selected schema objects. |

### Prompt A: Direct linking

```text
# Task:
You are an expert data analyst. Examine the database schema, question, and hint,
then select the specific tables and columns needed to answer the question.

# Instructions:
1. Select any column that is needed by SELECT, WHERE, JOIN, GROUP BY, ORDER BY, LIMIT, or calculations.
2. If a column may contain values related to the question, include it.
3. If multiple tables must be joined, include the join-key columns when visible.
4. It is safer to include a necessary neighboring key column than to omit it.

# Output Format:
Only output XML:
<reasoning>
    Concise reasoning.
</reasoning>
<result>
    <table table_name="table_name">
        <column column_name="column_name" />
    </table>
</result>

# Database Schema:
{DATABASE_SCHEMA}

# Question:
{QUESTION}

# Hint:
{HINT}
```

### Prompt B: Reverse linking

```text
# Task:
Generate one SQLite SQL query that answers the question using only the provided
schema. This SQL is used only to infer which schema elements are needed.

# Rules:
1. Use exact table and column names from the schema.
2. Prefer explicit joins using visible key relationships.
3. Do not invent schema objects.

# Output Format:
Only output XML:
<reasoning>
    Concise SQL construction reasoning.
</reasoning>
<result>
    SELECT ...
</result>

# Database Schema:
{DATABASE_SCHEMA}

# Question:
{QUESTION}

# Hint:
{HINT}
```

## S2 · Initial SQL Builder Agent

**Flow.** Select generation modes and generate candidates; revise failed candidates and validate again, then pass the selected SQL to [G1]. Local repair stops when successful or when its retry limit is exhausted; unresolved generation errors terminate the task.

| Observation | Meaning |
| --- | --- |
| examples | Available few-shot question–SQL pairs supporting ICL generation. |
| query structure | Required query operations and dependencies used to select skeleton or divide-and-conquer generation. |
| errors | Execution errors or blueprint violations used to guide local SQL repair. |

### Prompt A: Mode selection

```text
# Task
Select the SQL generation modes needed for the given question and context.

# Constraints
- Use "icl" as the base when few-shot examples are available; otherwise use
  "skeleton" and exclude "icl".
- Add "skeleton" when examples do not cover the required query structure, or
  joins, aggregation, filtering, and ranking require careful coordination.
- Add "divide_and_conquer" when the question requires dependent subgoals or
  separately computed results that must be combined or compared.
- Select only necessary modes. Simple joins, filters, or aggregations alone
  do not require extra modes. Use only the supplied context.

# Input
Question: {{QUESTION}}
Schema: {{SCHEMA}}
Additional context: {{CONTEXT}}
Few-shot examples: {{FEW_SHOT_EXAMPLES}}

# Output
Return only a JSON object containing the selected modes, for example:
{"modes": ["icl", "skeleton"]}
```

### Prompt B: Divide-and-conquer generation

```text
# Task:
Generate SQL with a recursive divide-and-conquer strategy.

First decompose the question into SQL sub-problems, then combine them into one executable query.
# Rules:
1. Generate SQLite SELECT SQL only.
2. Use only the provided tables, columns, value mappings, predicate hints, and join edges.
3. Do not invent schema objects or exact values.
4. Quote table or column identifiers when they contain spaces or punctuation.
5. Return only XML with a single <result> SQL block.

# Database Schema:
{DATABASE_SCHEMA}

# Question:
{QUESTION}

# Hint:
{HINT}

# Output:
<reasoning>
Brief decomposition and combination reasoning.
</reasoning>
<result>
SELECT ...
</result>
```

### Prompt C: Skeleton generation

```text
# Task:
Generate SQL with a plan -> skeleton -> complete strategy.

Plan the required SELECT/FROM/JOIN/WHERE/GROUP BY/HAVING/ORDER BY/LIMIT pieces, then fill the skeleton with exact schema names.
# Rules:
1. Generate SQLite SELECT SQL only.
2. Use only the provided tables, columns, value mappings, predicate hints, and join edges.
3. Do not invent schema objects or exact values.
4. Quote table or column identifiers when they contain spaces or punctuation.
5. Return only XML with a single <result> SQL block.

# Database Schema:
{DATABASE_SCHEMA}

# Question:
{QUESTION}

# Hint:
{HINT}

# Output:
<reasoning>
Brief plan and skeleton reasoning.
</reasoning>
<result>
SELECT ...
</result>
```

### Prompt D: ICL generation

```text
# Task:
Generate SQL by adapting the few-shot examples to the target schema.
# Rules:
1. Generate SQLite SELECT SQL only.
2. Use only the provided tables, columns, value mappings, predicate hints, and join edges.
3. Do not invent schema objects or exact values.
4. Quote table or column identifiers when they contain spaces or punctuation.
5. Return only XML with a single <result> SQL block.

# Few-Shot Examples:
{FEW_SHOT_EXAMPLES}

# Target Database Schema:
{DATABASE_SCHEMA}

# Target Question:
{QUESTION}

# Hint:
{HINT}

# Output:
<reasoning>
Brief example-pattern adaptation reasoning.
</reasoning>
<result>
SELECT ...
</result>
```

### Prompt E: Candidate revision

```text
# Task:
The SQL below failed syntax or execution validation. Revise it into executable SQLite SELECT SQL.

# Rules:
1. Preserve the question intent.
2. Use only the provided schema profile and verified values.
3. Fix syntax, identifier quoting, function usage, and other execution blockers.
4. Do not perform semantic rewrites beyond what is needed to make the SQL executable.
5. Return only XML with a single <result> SQL block.

# Database Schema:
{DATABASE_SCHEMA}

# Question:
{QUESTION}

# Hint:
{HINT}

# Failed SQL:
{SQL}

# Error / Result:
{ERROR}

# Output:
<reasoning>
Brief syntax fix explanation.
</reasoning>
<result>
SELECT ...
</result>
```

### Prompt F: Local repair

```text
The following SQL query failed to execute on {DBMS}.

Failed SQL:
{SQL}

Error message:
{ERROR_MESSAGE}

Repair the SQL so it executes successfully. Return this JSON shape:
{
  "sql": "the repaired SQL query",
  "explanation": "what was wrong and how you fixed it"
}

Rules:
- Only use tables, columns, values, and joins from the Verified Context Blueprint.
- Do not invent schema elements.
- Return only JSON.

Question:
{QUESTION}

Evidence:
{EVIDENCE}

Verified Context Blueprint:
{BLUEPRINT_JSON}
```

## [G1] · Optimization Guard

**Flow.** Choose optimization and enter S3, or choose planning_only and proceed to F with the initial SQL.

| Observation | Meaning |
| --- | --- |
| DB scale | Row-count-based size category of the tables involved in the task. |
| task complexity | Heuristic complexity of the question and SQL based on their features. |
| SQL shape | Query structures such as joins, aggregation, sorting, limits, and nested queries. |

### Prompt: Optimization decision

```text
# Task
Choose whether the initial SQL should enter the Optimization Loop.

# Constraints
Apply the supplied rule signals without inventing additional criteria.
Choose planning_plus_optimization if any of the following is true:
- database_scale is large or unknown;
- task_complexity is complex;
- has_join, has_group_by, has_order_by, has_limit, or has_nested_query is true.
Otherwise choose planning_only. Do not change the SQL or allocate a budget.

# Input
Database scale: {DATABASE_SCALE}
Task complexity: {TASK_COMPLEXITY}
SQL shape flags: {SQL_SHAPE_FLAGS}

# Output
Return only JSON:
{"plan": "planning_only or planning_plus_optimization"}
```

## S3 · Explain Analyzer Agent

**Flow.** Analyze the current SQL and execution evidence; send supported rewrite directions to S4, or proceed to F when no rewrite opportunity remains.

| Observation | Meaning |
| --- | --- |
| plan risks | Execution-plan features indicating potential bottlenecks. |
| SQL shape | Structural query patterns that may admit a semantics-preserving rewrite. |
| table size | Per-table row counts used to interpret access paths and scan costs. |

### Prompt: Rewrite analysis

```text
# Task
Analyze the supplied SQL and execution evidence. Identify supported rewrite
opportunities while preserving the source query's semantics.

# Constraints
- Use only the supplied plan, SQL, schema statistics, and rule conditions.
- Distinguish observed operators from inferred bottlenecks.
- Do not treat every full scan as a problem; consider table size and indexes.
- Check duplicate, NULL, aggregation, ordering, and LIMIT semantics before
  recommending a transformation.
- Do not recommend creating indexes or changing the database schema.
- If improvement requires an unavailable index or unsupported assumption,
  report no supported rewrite rather than inventing an opportunity.
- Produce suggestions, not rewritten SQL. Do not invent latency or cost gains.

# Input
Question: {QUESTION}
Current SQL: {CURRENT_SQL}
Schema and index metadata: {SCHEMA_AND_INDEXES}
Normalized execution plan: {PLAN}
Table statistics: {TABLE_STATISTICS}
Available rewrite rules and conditions: {RULES}
Previous risk tags: {PREVIOUS_RISK_TAGS}

# Output
Return only JSON:
{
  "decision": "rewrite or stop",
  "observed_signals": [],
  "rewrite_suggestions": [
    {"direction": "...", "support": "...", "required_conditions": []}
  ],
  "reason": "A concise evidence-based explanation."
}
```

## S4 · SQL Rewriter Agent

**Flow.** Use analysis hints or recovery feedback to produce a candidate and send it to S5; proceed to F if no usable candidate is available. Free exploration tries an alternative direction when enabled.

| Observation | Meaning |
| --- | --- |
| hints | Bottleneck descriptions and suggested rewrite directions supplied by analysis or retrieval. |
| applicability | Semantic prerequisites that must hold for a rewrite to be valid. |
| repair context | Failed SQL, validation differences, and diagnostic feedback used to correct a rejected transformation. |

### Prompt A: Constrained rewriting and repair

```text
# Task
Produce one improved SQLite SELECT query by applying the supplied rewrite plan.
If repair context is provided, first repair the failed transformation.

# Constraints
- Preserve the source result, including projected columns, duplicate
  multiplicities, NULL behavior, aggregation grain, ordering, and LIMIT ties.
- Use only the allowed tables, columns, values, and joins in the blueprint.
- Apply the supplied plan only when its applicability conditions are supported.
- In repair mode, use the source SQL, failed SQL, result difference, and diagnosis
  to correct the specific semantic or execution error. Preserve the optimization
  intent only where it remains safe.
- Do not invent values, indexes, schema objects, or measured performance gains.
- Make no database changes. Return SELECT SQL only.
- If no safe candidate is supported, return NO_OPTIMIZATION_SPACE.

# Input
Question: {QUESTION}
Evidence: {EVIDENCE}
Source SQL: {SOURCE_SQL}
Verified Context Blueprint: {BLUEPRINT}
Execution plan and statistics: {EXECUTION_CONTEXT}
Rewrite plan and applicability conditions: {REWRITE_PLAN}
Retrieved cases, if available: {RETRIEVED_CASES}
Failed candidate, if any: {FAILED_SQL}
Validation differences and repair hint, if any: {REPAIR_CONTEXT}

# Output
Return exactly one SQL fenced block, or exactly NO_OPTIMIZATION_SPACE.
Do not claim that the candidate has passed validation. S5 will test it.
```

### Prompt B: Free exploration

```text
# Task
Find one alternative SQL rewrite direction after a previous candidate failed
or no usable retrieved rule was available.

# Constraints
- Start from the last accepted source SQL, not from a rejected candidate.
- Preserve exact result semantics and remain within the verified blueprint.
- Use plan evidence and database metadata to select a plausible direction.
- Avoid repeating the supplied failed directions unless new evidence supports
  a specific correction.
- Do not change indexes, schema, or data. Do not invent benchmark results.
- If there is no supported safe alternative, return NO_OPTIMIZATION_SPACE.

# Input
Question: {QUESTION}
Source SQL: {SOURCE_SQL}
Verified Context Blueprint: {BLUEPRINT}
Plan and database statistics: {EXECUTION_CONTEXT}
Previous failed SQL and validation feedback: {FAILED_ATTEMPTS}
Failed directions: {FAILED_DIRECTIONS}

# Output
Return exactly one SQL fenced block, or exactly NO_OPTIMIZATION_SPACE.
```

## S5 · Validator Agent

**Flow.** Accept only when executable, equivalent, gain, and guardrails hold; update the best SQL and return to S3. Otherwise pass the rejected candidate and feedback to R.

| Observation | Meaning |
| --- | --- |
| executable | Whether the candidate executes successfully on the target database. |
| equivalent | Whether candidate and source results agree on the current database, including relevant ordering semantics. |
| gain | Whether measured latency or scan-work improvement satisfies the performance acceptance criteria. |

### Prompt: Validation summary

```text
# Task
Summarize the supplied validation report and its acceptance decision.

# Constraints
- Do not execute or rewrite SQL. Do not recompute missing measurements.
- Accept only when executable, equivalent, performance_better, and guardrails_ok
  are all true in the authoritative tool report.
- Keep semantic failure, execution failure, guardrail failure, and insufficient
  performance improvement distinct.
- Result equivalence on this database is not a universal equivalence proof.
- Do not promote a rejected candidate to the best SQL.

# Input
Source SQL: {SOURCE_SQL}
Candidate SQL: {CANDIDATE_SQL}
Authoritative execution and equivalence report: {VALIDATION_REPORT}
Measured latency and scan rows: {MEASUREMENTS}
Performance decision: {PERFORMANCE_DECISION}
Guardrail report: {GUARDRAIL_REPORT}

# Output
Return only JSON:
{
  "accepted": false,
  "failure_category": "none/execution/semantic/guardrail/performance",
  "summary": "A concise summary grounded in the supplied report."
}
```

## R · Validation-driven Recovery

**Flow.** A rejected non-free-exploration candidate may trigger free exploration; semantic or execution failures trigger diagnosis and repair through S4, followed by S5 validation. Free exploration may precede diagnosis; insufficient gain alone does not trigger semantic repair. Failed or exhausted recovery leads to F.

| Observation | Meaning |
| --- | --- |
| failure type | The rejection category used to distinguish execution, semantic, constraint, and performance failures. |
| diff | Observed differences between source and candidate results used to localize a failed transformation. |
| rejected rewrite | The failed candidate and its rewrite provenance used to select a recovery direction. |

### Prompt A: Semantic diagnosis

```text
You are diagnosing why an optimized SQLite query changed semantics.
Return 3 short lines using exactly these prefixes:
Changed clause:
Mismatch hypothesis:
Repair hint:

Question: {QUESTION}
Evidence: {EVIDENCE}
Source SQL:
{SOURCE_SQL}

Failed optimized SQL:
{FAILED_SQL}

Validator failure reason: {FAILURE_REASON}
Equivalence diff summary: {DIFF_SUMMARY}
Source row count: {SOURCE_ROW_COUNT}
Candidate row count: {CANDIDATE_ROW_COUNT}
Rewrite rule ids: {REWRITE_RULE_IDS}
Rewrite plan: {REWRITE_PLAN}
Focus on the exact clause or operator that likely changed set semantics, duplicate
behavior, NULL behavior, aggregation grain, or top-k behavior.
```

### Prompt B: Candidate repair

```text
# Task
Repair the failed optimized SQL using the source SQL and validation feedback.

# Constraints
- For semantic inconsistency, locate the changed clause, expression, join,
  predicate, aggregation, or ordering that could explain the observed difference.
- Treat the semantic diagnosis as a hypothesis to check against the SQL and
  feedback, not as a proven fact.
- For syntax or execution failure, fix the concrete invalid identifier, token,
  alias, function, clause, or dialect construct indicated by the error.
- Restore source-query semantics first. Retain the optimization basis only
  where safe. Stay within the verified blueprint.
- Do not alter data or schema, invent measurements, or claim validation success.
- Return a concise diagnosis rather than a detailed reasoning trace.

# Input
Question: {QUESTION}
Verified Context Blueprint: {BLUEPRINT}
Source SQL before optimization: {SOURCE_SQL}
Failed optimized SQL: {FAILED_SQL}
Failure type: {FAILURE_TYPE}
Database error / result difference: {VALIDATOR_FEEDBACK}
Semantic diagnosis: {SEMANTIC_DIAGNOSIS}
Original optimization basis: {OPTIMIZATION_BASIS}
Previous failed attempts: {FAILED_ATTEMPTS}

# Output
Return only JSON:
{"diagnosis": "A concise repair summary.", "sql": "Repaired SQLite SELECT SQL."}
```

The repair callback must use a consistent output format: the JSON interface above and the SQL-fenced-block interface in S4 are alternatives; every repaired candidate returns to S5.

## Memory Engine · Working Memory / AEKB

**Flow.** Record feedback and retain the best accepted SQL throughout execution; retrieve reusable knowledge for rewriting and save qualified final cases when AEKB storage is enabled.

| Observation | Meaning |
| --- | --- |
| SQL | Source, candidate, and best accepted query versions retained during the task. |
| metrics | Execution and validation observations associated with query versions. |
| failures | Rejected attempts and diagnostic feedback retained for recovery. |

### Prompt: Accepted-case summary

```text
# Task
Summarize an already accepted SQL rewrite as a reusable optimization case.

# Constraints
- The acceptance decision is supplied by validation; do not change it.
- Describe the concrete source-to-target transformation.
- Include only applicability assumptions supported by the supplied evidence.
- Distinguish observed benefits from hypotheses. Do not invent guarantees.
- Do not infer a new rule from rejected or unvalidated SQL.

# Input
Source SQL: {SOURCE_SQL}
Accepted SQL: {ACCEPTED_SQL}
Validated rewrite rules: {RULE_IDS}
Bottleneck evidence: {BOTTLENECK_EVIDENCE}
Validation and measured benefits: {VALIDATION_REPORT}
Supported applicability conditions: {SUPPORTED_CONDITIONS}

# Output
Return only JSON:
{
  "transformation": "...",
  "supported_conditions": [],
  "observed_benefit": "...",
  "limitations": []
}
```

## F · Final SQL

**Flow.** Return the best accepted SQL, or the initial SQL if no rewrite was accepted; save a qualified final case when eligible. This state terminates the workflow.

| Observation | Meaning |
| --- | --- |
| stop decision | The reason for termination, such as no rewrite space, no candidate, failed recovery, or an iteration limit. |
| retry count | The number of recovery attempts used to determine whether further retries remain. |
| status | The terminal outcome indicating completion, optimization bypass, or an error. |

### Prompt: Final report

```text
# Task
Report the final SQL and summarize why the workflow stopped.

# Constraints
- Return the exact supplied best SQL; do not rewrite or regenerate it.
- If no rewrite was accepted, retain the supplied initial SQL.
- State validation status and stop reason only from the provided records.
- Do not claim improved performance without an accepted measured improvement.
- Do not claim that an AEKB case was saved unless the storage result confirms it.

# Input
Initial SQL: {INITIAL_SQL}
Best SQL: {BEST_SQL}
Accepted rewrite history: {ACCEPTED_HISTORY}
Final validation report: {FINAL_VALIDATION}
Terminal status and reason: {TERMINAL_STATUS}
AEKB storage result: {STORAGE_RESULT}

# Output
Return only JSON:
{
  "sql": "Exact best SQL, or initial SQL when no rewrite was accepted.",
  "validation_status": "...",
  "stop_reason": "...",
  "optimization_summary": "..."
}
```
