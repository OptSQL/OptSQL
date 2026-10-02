# Case Study

This document presents a detailed case study of how OptSQL processes a Text-to-SQL task from initial cognition to final optimized SQL generation. Using the question “Chlorine is in what type of bond?” as an example, we illustrate how the Meta-Cognitive Controller perceives task complexity, selects suitable evidence construction and SQL generation strategies, and monitors the optimization process.

![](https://i.ibb.co/MxH3rCQf/20260630161818-8037-28.png)

## Preflight: Overall Task Complexity Cognition

<span style="color:#D4247A">[Meta-Cognitive Controller] </span> → **Cognition** →  [Task Meta]

- User Question: "Chlorine is in what type of bond?"  (<span style="color:#71AD48">Easy</span>)
- Evidence: "type of bond refers to bond_type; chlorine refers to element = 'cl'"
- Database Environment: <span style="color:#71AD48">Simple</span> table topology & <span style="color:red">Large</span> Data Scale

## 1 Generation Phase

### 1.1 Evidence-guidede Schema Filter

<span style="color:#D4247A">[Meta-Cognitive Controller] </span> → **Adaptation** →   [Strategy = Direct Schema Linking ]:    It's a easy question.

- Retrieved Schema is as follows:

  ```json
  {
    "atom": ["atom_id", "element"],
    "bond": ["bond_id", "bond_type"]
  }
  ```

- with value grounding evidence: `cl` is in `atom.elemet` 

- After supplement necessary join keys, the finally retrieved version is:

  ```json
  {
    "atom": ["atom_id", "element"],
    "bond": ["bond_id", "bond_type"],
    "connected": ["atom_id", "bond_id", "atom_id2"]
  }
  ```

### 1.2 Initial SQL Builder Agent

<span style="color:#D4247A">[Meta-Cognitive Controller] </span> → **Adaptation** →  [Strategy = Skeleton-based Generation ]:   It's a easy question with clear schema structure

This process generates 4 SQL candidates (without syntax error):

```py
{
  1: """
	SELECT DISTINCT b.bond_type FROM atom a
	INNER JOIN connected c ON a.atom_id = c.atom_id OR a.atom_id = c.atom_id2
	INNER JOIN bond b ON c.bond_id = b.bond_id
	WHERE a.element = 'cl'
	""",
  2: """
  SELECT DISTINCT b.bond_type FROM atom a
  INNER JOIN connected c ON a.atom_id = c.atom_id OR a.atom_id = c.atom_id2
  INNER JOIN bond b ON c.bond_id = b.bond_id
  WHERE a.element = 'cl'
  """,
  3: """
  SELECT DISTINCT b.bond_type FROM atom a
  INNER JOIN connected c ON a.atom_id = c.atom_id OR a.atom_id = c.atom_id2
  INNER JOIN bond b ON c.bond_id = b.bond_id
  WHERE a.element = 'cl'
  """,
  4: """
  SELECT DISTINCT b.bond_type FROM atom a1
  INNER JOIN connected c ON a1.atom_id = c.atom_id
  INNER JOIN atom a2 ON c.atom_id2 = a2.atom_id
  INNER JOIN bond b ON c.bond_id = b.bond_id
  WHERE (a1.element = 'cl' OR a2.element = 'cl') AND b.bond_type IS NOT NULL
  """
}
```

### 1.3 Candidate Selection

<span style="color:#D4247A">[Meta-Cognitive Controller] </span>→ **Cognition** →   [Selection = dominant majority] selects a representative query from cluster

- (dominant) `Cluster 1`: 1,2,3 => 2
- `Cluster 2`: 4

Thus, the base SQL is:

```sql
SELECT DISTINCT b.bond_type FROM atom a
INNER JOIN connected c ON 
	a.atom_id = c.atom_id 
	OR 
	a.atom_id = c.atom_id2
INNER JOIN bond b ON c.bond_id = b.bond_id
WHERE a.element = 'cl'
```

## 2 Optimization Loop

<span style="color:#D4247A">[Meta-Cognitive Controller] </span> → **Adaptation** →  [Strategy = Full Optimization Workflow ]:   The large data scale might suffers from slow query

### LOOP - 1 (converged)

- Explain Analyzer

  - Risks Found: "full_table_scan", "temp_distinct", "function_on_column", "or_predicate"
  - Rewrite Hints: "push_down_filter", "avoid_function_on_column", "rewrite_or_to_union"

- SQL Rewriter

  - <span style="color:blue;">[RAG Result]</span> Retrieved Rule

    ```
    SELECT DISTINCT COLUMN FROM TABLE 
    INNER JOIN TABLE ON FK_COLUMN = FK_COLUMN 
    INNER JOIN TABLE ON FK_COLUMN = FK_COLUMN 
    WHERE TEXT_COLUMN = LITERAL IN
    SELECT DISTINCT COLUMN FROM TABLE 
    INNER JOIN TABLE ON FK_COLUMN = FK_COLUMN AND TEXT_COLUMN = LITERAL 
    INNER JOIN TABLE ON FK_COLUMN = FK_COLUMN
    ```

  - Use hint `push_down_filter` and rewrite into

    ```sql
    SELECT DISTINCT b.bond_type
    FROM (
    	SELECT atom_id FROM atom
    	WHERE element = 'cl'
    ) AS a
    INNER JOIN connected c 
    	ON a.atom_id = c.atom_id
      OR a.atom_id = c.atom_id2
    INNER JOIN bond b ON c.bond_id = b.bond_id;
    ```

- Validator

  |                   EX                    |                     Cost                     |
  | :-------------------------------------: | :------------------------------------------: |
  | <span style="color:#71AD48">PASS</span> | <span style="color:#71AD48">Converged</span> |

<span style="color:#D4247A">[Meta-Cognitive Controller] </span>→ **Adaptation** → [Convergence Monitoring]:  <span style="color:#71AD48">Accepted</span>. 1 < maxiter, continue.

### LOOP - 2 (fail)

- Explain Analyzer

  - Risks Found: "temp_distinct", "or_predicate"

  - Rewrite Hints: "rewrite_or_to_union"

- SQL Rewriter

  - RAG Result: NO Result => Free Explore

  - Use hint `rewrite_or_to_union` and rewrite into

    ```sql
    SELECT DISTINCT b.bond_type FROM atom a
    JOIN connected c ON c.atom_id = a.atom_id
    JOIN bond b ON b.bond_id = c.bond_id
    WHERE a.element = 'cl'
    UNION ALL
    SELECT DISTINCT b.bond_type
    FROM atom a JOIN connected c ON c.atom_id2 = a.atom_id
    JOIN bond b ON b.bond_id = c.bond_id
    WHERE a.element = 'cl'
    ```

- Validator

  |                 EX                  |                  Cost                   |
  | :---------------------------------: | :-------------------------------------: |
  | <span style="color:red">Fail</span> | <span style="color:grey">Skipped</span> |

<span style="color:#D4247A">[Meta-Cognitive Controller] </span> → **Adaptation** → [Convergence Monitoring]:  <span style="color:red">Rejeted</span>. 2 < maxiter, continue.

### LOOP - 3 (reflection -> converged)

- Working Memory

  ```
  {
  	"hints":  ["rewrite_or_to_union"],
  	"failed": [
  		{
  			"hint": "rewrite_or_to_union",
  			"sql": """SELECT DISTINCT b.bond_type FROM atom a
                  JOIN connected c ON c.atom_id = a.atom_id
                  JOIN bond b ON b.bond_id = c.bond_id
                  WHERE a.element = 'cl'
                  UNION ALL
                  SELECT DISTINCT b.bond_type
                  FROM atom a JOIN connected c ON c.atom_id2 = a.atom_id
                  JOIN bond b ON b.bond_id = c.bond_id
                  WHERE a.element = 'cl'""",
        "reason": "It uses UNION ALL instead of UNION, so it does not preserve the global duplicate-elimination semantics of the original SELECT DISTINCT query. A correct repair should either use UNION or wrap the UNION ALL result with an outer SELECT DISTINCT."
  		}
  	]
  }
  ```

- SQL Rewriter

  - RAG Result: NO Result => Free Explore

  - Use hint `rewrite_or_to_union` and rewrite into

    ```sql
    SELECT b.bond_type FROM atom a
    JOIN connected c ON c.atom_id = a.atom_id
    JOIN bond b ON b.bond_id = c.bond_id
    WHERE a.element = 'cl'
    UNION
    SELECT b.bond_type FROM atom a
    JOIN connected c ON c.atom_id2 = a.atom_id
    JOIN bond b ON b.bond_id = c.bond_id
    WHERE a.element = 'cl';
    ```

- Validator

  |                   EX                    |                     Cost                     |
  | :-------------------------------------: | :------------------------------------------: |
  | <span style="color:#71AD48">PASS</span> | <span style="color:#71AD48">Converged</span> |

  <span style="color:#D4247A">[Meta-Cognitive Controller] </span>→ **Adaptation** → [Convergence Monitoring]:  <span style="color:#71AD48">Accepted</span>. 3 = maxiter, stop.

Thus, the finally output SQL is:

```sql
SELECT b.bond_type FROM atom a
JOIN connected c ON c.atom_id = a.atom_id
JOIN bond b ON b.bond_id = c.bond_id
WHERE a.element = 'cl'
UNION
SELECT b.bond_type FROM atom a
JOIN connected c ON c.atom_id2 = a.atom_id
JOIN bond b ON b.bond_id = c.bond_id
WHERE a.element = 'cl';
```

