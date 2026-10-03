# Error Analysis

This document presents a qualitative error analysis of OptSQL from two complementary perspectives: correctness and efficiency.

## Setup

For **correctness analysis**, three SQL experts randomly sample 100 evaluated cases where the generated SQL is judged incorrect by execution accuracy (EX). For each case, we inspect the natural-language question, evidence, predicted SQL, gold SQL, and execution behavior, and classify the root cause into two high-level categories: **Intent-violating Hallucination** and **Gold Error**. The final taxonomy contains fine-grained labels such as join logic hallucination, DISTINCT error, ORDER BY misuse, aggregation misuse, value specification error, and gold-SQL ambiguity. After resolving disagreements through discussion, we summarize the distribution of correctness errors, where 87% are caused by intent-violating hallucinations and 13% are caused by potential gold errors.

For **inefficiency analysis,** we randomly sample 100 semantically correct cases whose instance-level cost ratio satisfies CR_i < 1.0. These cases represent SQL queries that return correct results but are more expensive than the expert canonical SQL. For each case, we jointly inspect the predicted SQL, the expert SQL, and their query plans to identify recurring inefficiency patterns. Following an open-coding protocol, we first assign fine-grained labels to each case and then merge related labels into five high-level themes: **Join Logic**, **Subquery Logic**, **Timing Strategy**, **Access Strategy**, and **Others**. The resulting distribution shows that most inefficiencies come from join-related issues (58%), followed by other missed rewrite opportunities (28%), subquery logic (5%), timing strategy (5%), and access strategy (4%).

The detailed examples below illustrate representative cases for each category.

## Correctness Analysis

<span style="color:red"><strong>Description:</strong> This section records cases where the SQL result may be semantically incorrect because the query intent, selected output, filtering logic, or calculation does not match the expected answer.</span>


### Summary

![correctness_analysis](https://i.ibb.co/RWPkGcr/3d5ff66ba770938c1aa59f9b824bb53a.jpg)

### Gold Error (13%)

<span style="color:red"><strong>Description:</strong> This major category covers cases where the reference gold SQL is likely wrong, incomplete, or ambiguous, so the model prediction may actually better match the natural-language question.</span>


#### Aggregation

<span style="color:red"><strong>Description:</strong> This category refers to errors involving aggregate logic, such as missing COUNT, SUM, AVG, MIN, MAX, or using aggregation in a way that does not match the question.</span>


- id: 435
- db_id: card_games
- question: How many card border with black color ? List out the card id.
- evidence: border with black color refers to borderColor = 'black'
- reason: Question asks both “How many” and to list IDs/names, but gold SQL does not return COUNT.

Pred SQL:

```sql
SELECT id FROM cards WHERE borderColor = 'black'
```

Gold SQL:

```sql
SELECT id FROM cards WHERE borderColor = 'black' GROUP BY id
```

Notes: CHESS-style incorrect golden SQL candidate; confidence=strong_candidate; rule=how_many_and_list_but_gold_lacks_count

#### Column

<span style="color:red"><strong>Description:</strong> This category refers to cases where the selected output columns are missing, extra, or different from what the question explicitly asks for.</span>


- id: 267
- db_id: toxicology
- question: List down the bond type for molecules from molecule id TR000 to TR050.
- evidence: double bond refers to bond_type = ' = '; single bond refers to bond_type = '-'; triple bond refers to bond_type = '#';
- reason: Question asks for bond type; gold also selects molecule_id. CHESS flags this as extra selected column, but it is somewhat ambiguous.

Pred SQL:

```sql
SELECT DISTINCT b.bond_type
FROM bond b
JOIN molecule m ON b.molecule_id = m.molecule_id
WHERE m.molecule_id BETWEEN 'TR000' AND 'TR050'
```

Gold SQL:

```sql
SELECT T2.molecule_id, T2.bond_type FROM molecule AS T1 INNER JOIN bond AS T2 ON T1.molecule_id = T2.molecule_id WHERE T1.molecule_id BETWEEN 'TR000' AND 'TR050'
```

Notes: CHESS-style incorrect golden SQL candidate; confidence=possible_candidate; rule=bond_type_question_gold_selects_extra_molecule_id

#### Description

<span style="color:red"><strong>Description:</strong> This category refers to mistakes caused by misunderstanding schema descriptions, column meanings, or database-specific metadata.</span>


- id: 937
- db_id: formula_1
- question: What's the finish time for the driver who ranked second in 2008's AustChineseralian Grand Prix?
- evidence: finish time refers to time; Chinese Grand Prix refers to races.name = 'Chinese Grand Prix';
- reason: DB description says positionOrder is finishing order while rank is fastest-lap/start-rank related; gold uses rank for finish-time question.

Pred SQL:

```sql
SELECT r.time
FROM races ra
INNER JOIN results r ON ra.raceId = r.raceId
WHERE ra.name = 'Chinese Grand Prix' 
AND ra.year = 2008
AND r.position = 2
```

Gold SQL:

```sql
SELECT T1.time FROM results AS T1 INNER JOIN races AS T2 on T1.raceId = T2.raceId WHERE T1.rank = 2 AND T2.name = 'Chinese Grand Prix' AND T2.year = 2008
```

Notes: CHESS-style incorrect golden SQL candidate; confidence=confirmed_candidate; rule=finish_time_uses_rank_instead_of_position_order

#### Filtering

<span style="color:red"><strong>Description:</strong> This category refers to incorrect WHERE or HAVING conditions, including wrong logical requirements such as “both” being treated as “either.”</span>


- id: 593
- db_id: codebase_community
- question: How many users from New York have a teacher and supporter badge?
- evidence: "Supporter" and "Teachers" are both Name of badge; 'New York' is the Location; user refers to UserId
- reason: Question asks users having both badge/category values, but gold uses IN, which permits either value and lacks HAVING COUNT(DISTINCT ...)=2.

Pred SQL:

```sql
SELECT COUNT(*) 
FROM users u
INNER JOIN badges b1 ON u.Id = b1.UserId
INNER JOIN badges b2 ON u.Id = b2.UserId
WHERE u.Location = 'New York' 
AND b1.Name = 'Teacher' 
AND b2.Name = 'Supporter'
```

Gold SQL:

```sql
SELECT COUNT(DISTINCT T1.Id) FROM badges AS T1 INNER JOIN users AS T2 ON T1.UserId = T2.Id WHERE T1.Name IN ('Supporter', 'Teacher') AND T2.Location = 'New York'
```

Notes: CHESS-style incorrect golden SQL candidate; confidence=confirmed_candidate; rule=both_badges_gold_uses_in_without_having

#### Group By/Distinct

<span style="color:red"><strong>Description:</strong> This category refers to problems with grouping or deduplication, such as missing GROUP BY, unnecessary DISTINCT, or incorrect grouping granularity.</span>


- id: 94
- db_id: financial
- question: List out the account numbers of female clients who are oldest and has lowest average salary, calculate the gap between this lowest average salary with the highest average salary?
- evidence: Female means gender = 'F'; A11 refers to average salary; Gap = highest average salary - lowest average salary; If the person A's birthdate > B's birthdate, it means that person B is order than person A.
- reason: Gold SELECT mixes aggregate and non-aggregate outputs without GROUP BY; CHESS treats this pattern as a likely missing GROUP BY issue.

Pred SQL:

```sql
SELECT 
    a.account_id,
    (SELECT MAX(d.A11) - MIN(d.A11) FROM district d) AS salary_gap
FROM client c
JOIN disp d ON c.client_id = d.client_id
JOIN account a ON d.account_id = a.account_id
WHERE c.gender = 'F'
AND c.birth_date = (
    SELECT birth_date 
    FROM client 
    WHERE gender = 'F' 
    ORDER BY birth_date ASC 
    LIMIT 1
)
AND c.district_id = (
    SELECT district_id 
    FROM client 
    WHERE gender = 'F' 
    AND birth_date = (
        SELECT birth_date 
        FROM client 
        WHERE gender = 'F' 
        ORDER BY birth_date ASC 
        LIMIT 1
    )
    ORDER BY district_id ASC
    LIMIT 1
)
```

Gold SQL:

```sql
SELECT T1.account_id , ( SELECT MAX(A11) - MIN(A11) FROM district ) FROM account AS T1 INNER JOIN district AS T2 ON T1.district_id = T2.district_id INNER JOIN disp AS T3 ON T1.account_id = T3.account_id INNER JOIN client AS T4 ON T3.client_id = T4.client_id WHERE T2.district_id = ( SELECT district_id FROM client WHERE gender = 'F' ORDER BY birth_date ASC LIMIT 1 ) ORDER BY T2.A11 DESC LIMIT 1
```

Notes: CHESS-style incorrect golden SQL candidate; confidence=strong_candidate; rule=aggregate_nonaggregate_without_group_by

#### Operation

<span style="color:red"><strong>Description:</strong> This category refers to wrong arithmetic or formula usage, such as ranking by an incomplete revenue calculation instead of the intended computed value.</span>


- id: 1527
- db_id: debit_card_specializing
- question: Which gas station has the highest amount of revenue?
- evidence: 
- reason: DB description says total price = Amount x Price; gold ranks by SUM(Price) only.

Pred SQL:

```sql
SELECT GasStationID
FROM transactions_1k
GROUP BY GasStationID
ORDER BY SUM(Price * Amount) DESC
LIMIT 1
```

Gold SQL:

```sql
SELECT GasStationID FROM transactions_1k GROUP BY GasStationID ORDER BY SUM(Price) DESC LIMIT 1
```

Notes: CHESS-style incorrect golden SQL candidate; confidence=confirmed_candidate; rule=revenue_should_use_amount_times_price

### Intent-violating Hallucination (87%)

<span style="color:red"><strong>Description:</strong> This major category covers cases where the predicted SQL changes the user intent by adding, omitting, or inventing logic that is not supported by the question or evidence.</span>


#### Aggregation Function Misuse

<span style="color:red"><strong>Description:</strong> This category refers to using the wrong aggregate function or aggregation pattern, causing the query to compute a different statistic from the intended one.</span>


- id: 33
- db_id: california_schools
- question: If there are any, what are the websites address of the schools with a free meal count of 1,900-2,000 to students aged 5-17? Include the name of the school.
- evidence: 
- reason: The aggregate-function pattern differs from the gold SQL: predicted {'count': 2}, gold {'count': 1}.

Pred SQL:

```sql
SELECT DISTINCT s.Website, s.School
FROM frpm f
INNER JOIN schools s ON f.CDSCode = s.CDSCode
WHERE f.`Free Meal Count (Ages 5-17)` BETWEEN 1900 AND 2000
AND f.`Free Meal Count (Ages 5-17)` IS NOT NULL
```

Gold SQL:

```sql
SELECT T2.Website, T1.`School Name` FROM frpm AS T1 INNER JOIN schools AS T2 ON T1.CDSCode = T2.CDSCode WHERE T1.`Free Meal Count (Ages 5-17)` BETWEEN 1900 AND 2000 AND T2.Website IS NOT NULL
```

Notes: taxonomy_rule_reviewed; gold_error_not_confirmed_without_db

#### Column Selection Error

<span style="color:red"><strong>Description:</strong> This category refers to selecting the wrong set of output columns, including adding unnecessary administrator/name fields or omitting required answer fields.</span>


- id: 63
- db_id: california_schools
- question: In chartered schools with charter number 00D2, what are the names of all the administrators? Include the name of the school and the city to which it belongs
- evidence: Chartered schools refer to Charter = 1 in the table schools; Full name refers to first name, last name
- reason: The predicted SELECT output columns or expressions differ from the gold SQL.

Pred SQL:

```sql
SELECT AdmFName1, AdmLName1, AdmFName2, AdmLName2, AdmFName3, AdmLName3, School, City 
FROM schools 
WHERE Charter = 1 AND CharterNum = '00D2'
```

Gold SQL:

```sql
SELECT AdmFName1, AdmLName1, School, City FROM schools WHERE Charter = 1 AND CharterNum = '00D2'
```

Notes: taxonomy_rule_reviewed; gold_error_not_confirmed_without_db

#### Condition Logic Hallucination

<span style="color:red"><strong>Description:</strong> This category refers to predicted filter logic that differs from the required condition, often by using the wrong table field or adding unsupported restrictions.</span>


- id: 28
- db_id: california_schools
- question: Consider the average difference between K-12 enrollment and 15-17 enrollment of schools that are locally funded, list the names and DOC type of schools which has a difference above this average.
- evidence: Difference between K-12 enrollment and 15-17 enrollment can be computed by `Enrollment (K-12)` - `Enrollment (Ages 5-17)`
- reason: The predicted WHERE/HAVING conditions do not match the gold SQL, causing a different filtered result set.

Pred SQL:

```sql
SELECT 
    f."School Name",
    s."DOCType"
FROM frpm f
JOIN schools s ON f."CDSCode" = s."CDSCode"
WHERE f."Charter Funding Type" = 'Locally funded'
    AND (f."Enrollment (K-12)" - f."Enrollment (Ages 5-17)") > (
        SELECT AVG(f2."Enrollment (K-12)" - f2."Enrollment (Ages 5-17)")
        FROM frpm f2
        JOIN schools s2 ON f2."CDSCode" = s2."CDSCode"
        WHERE f2."Charter Funding Type" = 'Locally funded'
    )
```

Gold SQL:

```sql
SELECT T2.School, T2.DOC FROM frpm AS T1 INNER JOIN schools AS T2 ON T1.CDSCode = T2.CDSCode WHERE T2.FundingType = 'Locally funded' AND (T1.`Enrollment (K-12)` - T1.`Enrollment (Ages 5-17)`) > (SELECT AVG(T3.`Enrollment (K-12)` - T3.`Enrollment (Ages 5-17)`) FROM frpm AS T3 INNER JOIN schools AS T4 ON T3.CDSCode = T4.CDSCode WHERE T4.FundingType = 'Locally funded')
```

Notes: taxonomy_rule_reviewed; gold_error_not_confirmed_without_db

#### Distinct Error

<span style="color:red"><strong>Description:</strong> This category refers to incorrect use or omission of DISTINCT or COUNT(DISTINCT), which changes whether duplicate rows are kept or removed.</span>


- id: 49
- db_id: california_schools
- question: Which different county has the most number of closed schools? Please provide the name of each school as well as the closure date.
- evidence: Closure date and closed date are synonyms; 'Closed' was mentioned in schools.StatusType.
- reason: The predicted SQL and gold SQL differ in DISTINCT or COUNT(DISTINCT ...) usage.

Pred SQL:

```sql
SELECT s."School", s."ClosedDate"
FROM "schools" AS s
WHERE s."County" = (
    SELECT "County"
    FROM "schools"
    WHERE "StatusType" = 'Closed'
    GROUP BY "County"
    ORDER BY COUNT(*) DESC
    LIMIT 1
)
AND s."StatusType" = 'Closed'
```

Gold SQL:

```sql
SELECT DISTINCT County, School, ClosedDate FROM schools WHERE County = ( SELECT County FROM schools WHERE StatusType = 'Closed' GROUP BY County ORDER BY COUNT(School) DESC LIMIT 1 ) AND StatusType = 'Closed' AND school IS NOT NULL
```

Notes: taxonomy_rule_reviewed; gold_error_not_confirmed_without_db

#### GroupBy Misuse

<span style="color:red"><strong>Description:</strong> This category refers to grouping by the wrong columns or at the wrong granularity, which changes the meaning of the aggregated result.</span>


- id: 309
- db_id: toxicology
- question: List out the atom id that belongs to the TR346 molecule and how many bond type can be created by this molecule?
- evidence: 
- reason: The predicted SQL uses a different GROUP BY structure or grouping granularity from the gold SQL.

Pred SQL:

```sql
SELECT a.atom_id, 
       (SELECT COUNT(DISTINCT bond_type) 
        FROM bond 
        WHERE molecule_id = 'TR346') AS bond_type_count
FROM atom a
WHERE a.molecule_id = 'TR346'
```

Gold SQL:

```sql
SELECT T1.atom_id, COUNT(DISTINCT T2.bond_type),T1.molecule_id FROM atom AS T1 INNER JOIN bond AS T2 ON T1.molecule_id = T2.molecule_id WHERE T1.molecule_id = 'TR000' GROUP BY T1.atom_id, T2.bond_type
```

Notes: taxonomy_rule_reviewed; gold_error_not_confirmed_without_db

#### Join Logic Hallucination

<span style="color:red"><strong>Description:</strong> This category refers to joining the wrong tables, using an incorrect join path, or producing a table relationship that does not match the intended query.</span>


- id: 40
- db_id: california_schools
- question: What is the telephone number for the school with the lowest average score in reading in Fresno Unified?
- evidence: Fresno Unified is a name of district;
- reason: The predicted table/join structure differs from the gold SQL: predicted tables=['schools'], gold tables=['satscores'].

Pred SQL:

```sql
SELECT s.Phone
FROM schools s
JOIN satscores sc ON s.CDSCode = sc.cds
WHERE s.District = 'Fresno Unified'
ORDER BY sc.AvgScrRead ASC
LIMIT 1
```

Gold SQL:

```sql
SELECT T2.Phone FROM satscores AS T1 INNER JOIN schools AS T2 ON T1.cds = T2.CDSCode WHERE T2.District = 'Fresno Unified' AND T1.AvgScrRead IS NOT NULL ORDER BY T1.AvgScrRead ASC LIMIT 1
```

Notes: taxonomy_rule_reviewed; gold_error_not_confirmed_without_db

#### Limit Error

<span style="color:red"><strong>Description:</strong> This category refers to mistakes in top-k, pagination, LIMIT, or OFFSET logic, causing the query to return the wrong ranked positions or number of rows.</span>


- id: 31
- db_id: california_schools
- question: What is the eligible free rate of the 10th and 11th schools with the highest enrolment for students in grades 1 through 12?
- evidence: K-12 refers to students in grades 1 through 12; Eligible free rate for K-12 = `Free Meal Count (K-12)` / `Enrollment (K-12)`
- reason: The LIMIT requirement differs from the gold SQL: predicted LIMIT=2, gold LIMIT=9.

Pred SQL:

```sql
SELECT "Percent (%) Eligible Free (K-12)"
FROM frpm
JOIN schools ON frpm."CDSCode" = schools."CDSCode"
ORDER BY "Enrollment (K-12)" DESC
LIMIT 2 OFFSET 9
```

Gold SQL:

```sql
SELECT CAST(`Free Meal Count (K-12)` AS REAL) / `Enrollment (K-12)` FROM frpm ORDER BY `Enrollment (K-12)` DESC LIMIT 9, 2
```

Notes: taxonomy_rule_reviewed; gold_error_not_confirmed_without_db

#### Operator Misuse

<span style="color:red"><strong>Description:</strong> This category refers to using the wrong comparison or logical operator, such as >, >=, BETWEEN, IN, AND, or OR.</span>


- id: 23
- db_id: california_schools
- question: List the names of schools with more than 30 difference in enrollements between K-12 and ages 5-17? Please also give the full street adress of the schools.
- evidence: Diffrence in enrollement = `Enrollment (K-12)` - `Enrollment (Ages 5-17)`
- reason: The predicted SQL uses different comparison/operator logic from the gold SQL for the same numeric condition.

Pred SQL:

```sql
SELECT 
    f."School Name",
    s."Street"
FROM 
    frpm f
INNER JOIN 
    schools s ON f."CDSCode" = s."CDSCode"
WHERE 
    (f."Enrollment (K-12)" - f."Enrollment (Ages 5-17)") > 30
    AND f."Enrollment (Ages 5-17)" IS NOT NULL
```

Gold SQL:

```sql
SELECT T1.School, T1.Street FROM schools AS T1 INNER JOIN frpm AS T2 ON T1.CDSCode = T2.CDSCode WHERE T2.`Enrollment (K-12)` - T2.`Enrollment (Ages 5-17)` > 30
```

Notes: taxonomy_rule_reviewed; gold_error_not_confirmed_without_db

#### OrderBy Misuse

<span style="color:red"><strong>Description:</strong> This category refers to ordering or ranking by the wrong field, wrong direction, or wrong ranking expression.</span>


- id: 17
- db_id: california_schools
- question: Rank schools by their average score in Writing where the score is greater than 499, showing their charter numbers.
- evidence: Valid charter number means the number is not null
- reason: The query involves ranking/extreme selection, but the predicted ORDER BY field or direction differs from the gold SQL.

Pred SQL:

```sql
SELECT 
    sname, 
    AvgScrWrite, 
    CharterNum
FROM 
    satscores
JOIN 
    schools
ON 
    satscores.cds = schools.CDSCode
WHERE 
    AvgScrWrite > 499
    AND CharterNum IS NOT NULL
ORDER BY 
    AvgScrWrite DESC;
```

Gold SQL:

```sql
SELECT CharterNum, AvgScrWrite, RANK() OVER (ORDER BY AvgScrWrite DESC) AS WritingScoreRank FROM schools AS T1  INNER JOIN satscores AS T2 ON T1.CDSCode = T2.cds WHERE T2.AvgScrWrite > 499 AND CharterNum is not null
```

Notes: taxonomy_rule_reviewed; gold_error_not_confirmed_without_db

#### Violating Value Specification

<span style="color:red"><strong>Description:</strong> This category refers to using a wrong literal value, entity name, location, status, or other specified condition value from the question.</span>


- id: 16
- db_id: california_schools
- question: How many schools in merged Alameda have number of test takers less than 100?
- evidence: 
- reason: The predicted SQL uses different literal/entity filter values from the gold SQL.

Pred SQL:

```sql
SELECT COUNT(*) 
FROM schools s 
INNER JOIN satscores ss ON s.CDSCode = ss.cds 
WHERE s.County = 'Alameda' 
AND s.StatusType = 'Merged' 
AND ss.NumTstTakr < 100
```

Gold SQL:

```sql
SELECT COUNT(T1.CDSCode) FROM schools AS T1 INNER JOIN satscores AS T2 ON T1.CDSCode = T2.cds WHERE T1.StatusType = 'Merged' AND T2.NumTstTakr < 100 AND T1.County = 'Lake'
```

Notes: taxonomy_rule_reviewed; gold_error_not_confirmed_without_db

## Inefficiency Analysis

<span style="color:red"><strong>Description:</strong> This section records cases where the predicted SQL is intended to be semantically correct but could be made more efficient through simpler joins, better filtering, or cleaner query structure.</span>


### Summary

![ineffciency_analysis](https://i.ibb.co/dwQqGgjm/e70c269efbfa6af751d18a12c7319498.jpg)

### Access Strategy (4%)

<span style="color:red"><strong>Description:</strong> This major category covers inefficiencies related to how data is accessed from base tables, including scan reduction, pushdown opportunities, and index-friendly rewriting.</span>


#### Storage Pushdown

<span style="color:red"><strong>Description:</strong> This category refers to pushing filters, projections, or simple calculations closer to the table scan so fewer rows and columns are processed later.</span>


- id: 117
- db_id: financial
- question: What is the percentage of loan amount that has been fully paid with no issue.
- evidence: Loan paid with no issue means contract finished, no problems; status = 'A' means contract finished, no problems; Percentage of accounts by condition = [(total(amount) & condition) / (total amount)] * 100%
- reason: The SQL can benefit from keeping only the necessary rows and columns as close to the table scan as possible.

Pred SQL:

```sql
SELECT ((SUM(CASE WHEN status = 'A' THEN amount ELSE 0 END) * 100.0) / SUM(amount)) AS percentage
FROM loan
```

Gold SQL:

```sql
SELECT (CAST(SUM(CASE WHEN status = 'A' THEN amount ELSE 0 END) AS REAL) * 100) / SUM(amount) FROM loan
```

Notes: taxonomy_rule_reviewed

### Join Logic (58%)

<span style="color:red"><strong>Description:</strong> This major category covers inefficiencies caused by unnecessary, redundant, or replaceable joins that increase intermediate result size without changing the final answer.</span>


#### Cardinality-Preserving FK Join

<span style="color:red"><strong>Description:</strong> This category refers to foreign-key joins that preserve row counts but do not contribute useful selected, filtered, grouped, or ordered information.</span>


- id: 8
- db_id: california_schools
- question: What is the number of SAT test takers of the schools with the highest FRPM count for K-12 students?
- evidence: 
- reason: The extra join follows a key relationship and does not contribute selected, filtered, grouped, or ordered information.

Pred SQL:

```sql
SELECT s.`NumTstTakr`
FROM frpm f
JOIN schools sc ON f.`CDSCode` = sc.`CDSCode`
JOIN satscores s ON sc.`CDSCode` = s.`cds`
WHERE NOT f.`FRPM Count (K-12)` IS NULL
ORDER BY f.`FRPM Count (K-12)` DESC
LIMIT 1
```

Gold SQL:

```sql
SELECT NumTstTakr FROM satscores WHERE cds = ( SELECT CDSCode FROM frpm ORDER BY `FRPM Count (K-12)` DESC LIMIT 1 )
```

Notes: taxonomy_rule_reviewed; join_elimination_split_from=Join Elimination

#### Existence-Only Join

<span style="color:red"><strong>Description:</strong> This category refers to joins used mainly to check whether a matching row exists, which can often be replaced by EXISTS or a semi-join pattern.</span>


- id: 24
- db_id: california_schools
- question: Give the names of the schools with the percent eligible for free meals in K-12 is more than 0.1 and test takers whose test score is greater than or equal to 1500?
- evidence: Percent eligible for free meals = Free Meal Count (K-12) / Total (Enrollment (K-12)
- reason: The extra join is mainly used as an existence/membership check and can be avoided or replaced by a lighter semi-join pattern.

Pred SQL:

```sql
SELECT DISTINCT f."School Name"
FROM frpm f
INNER JOIN schools s ON f."CDSCode" = s."CDSCode"
INNER JOIN satscores st ON s."CDSCode" = st."cds"
WHERE (f."Free Meal Count (K-12)" / f."Enrollment (K-12)") > 0.1
AND st."NumGE1500" > 0
```

Gold SQL:

```sql
SELECT T2.`School Name` FROM satscores AS T1 INNER JOIN frpm AS T2 ON T1.cds = T2.CDSCode WHERE CAST(T2.`Free Meal Count (K-12)` AS REAL) / T2.`Enrollment (K-12)` > 0.1 AND T1.NumGE1500 > 0
```

Notes: taxonomy_rule_reviewed; join_elimination_split_from=Join Elimination

#### Filter-Substitutable Join

<span style="color:red"><strong>Description:</strong> This category refers to extra joins used only for filtering when the same filter can be applied directly through an existing table field.</span>


- id: 0
- db_id: california_schools
- question: What is the highest eligible free rate for K-12 students in the schools in Alameda County?
- evidence: Eligible free rate for K-12 = `Free Meal Count (K-12)` / `Enrollment (K-12)`
- reason: The predicted SQL joins an extra table mainly for filtering, but the filter can be applied through an existing/direct table field.

Pred SQL:

```sql
SELECT MAX("Free Meal Count (K-12)" / "Enrollment (K-12)") AS highest_rate
FROM frpm
INNER JOIN schools ON frpm."CDSCode" = schools."CDSCode"
WHERE schools."County" = 'Alameda' 
AND frpm."Free Meal Count (K-12)" IS NOT NULL
```

Gold SQL:

```sql
SELECT `Free Meal Count (K-12)` / `Enrollment (K-12)` FROM frpm WHERE `County Name` = 'Alameda' ORDER BY (CAST(`Free Meal Count (K-12)` AS REAL) / `Enrollment (K-12)`) DESC LIMIT 1
```

Notes: taxonomy_rule_reviewed; join_elimination_split_from=Join Elimination

#### Projection-Substitutable Join

<span style="color:red"><strong>Description:</strong> This category refers to extra joins used mainly to output a column that can be obtained without joining another table.</span>


- id: 143
- db_id: financial
- question: What are the accounts that have gold credit cards?
- evidence: 
- reason: The predicted SQL joins an extra table mainly for projected columns, but the output can be obtained without that extra join.

Pred SQL:

```sql
SELECT DISTINCT a.account_id
FROM card c
INNER JOIN disp d ON c.disp_id = d.disp_id
INNER JOIN account a ON d.account_id = a.account_id
WHERE c.type = 'gold'
```

Gold SQL:

```sql
SELECT T2.account_id FROM disp AS T2  INNER JOIN card AS T1 ON T1.disp_id = T2.disp_id  WHERE T1.type = 'gold'
```

Notes: taxonomy_rule_reviewed; join_elimination_split_from=Join Elimination

#### Redundant Lookup Join

<span style="color:red"><strong>Description:</strong> This category refers to lookup-table joins that do not materially contribute to the final answer and can be removed.</span>


- id: 4
- db_id: california_schools
- question: Please list the phone numbers of the direct charter-funded schools that are opened after 2000/1/1.
- evidence: Charter schools refers to `Charter School (Y/N)` = 1 in the frpm
- reason: The predicted SQL contains an extra lookup join that is not needed for the final answer.

Pred SQL:

```sql
SELECT s."Phone"
FROM "schools" s
INNER JOIN "frpm" f ON s."CDSCode" = f."CDSCode"
WHERE f."Charter School (Y/N)" = 1 
AND f."Charter Funding Type" = 'Directly funded'
AND s."OpenDate" > '2000-01-01'
```

Gold SQL:

```sql
SELECT T2.Phone FROM frpm AS T1 INNER JOIN schools AS T2 ON T1.CDSCode = T2.CDSCode WHERE T1.`Charter Funding Type` = 'Directly funded' AND T1.`Charter School (Y/N)` = 1 AND T2.OpenDate > '2000-01-01'
```

Notes: taxonomy_rule_reviewed; join_elimination_split_from=Join Elimination

#### Semi-Join Conversion

<span style="color:red"><strong>Description:</strong> This category refers to replacing duplicate-producing joins plus DISTINCT with a lighter EXISTS, IN, or semi-join form.</span>


- id: 2
- db_id: california_schools
- question: Please list the zip code of all the charter schools in Fresno County Office of Education.
- evidence: Charter schools refers to `Charter School (Y/N)` = 1 in the table fprm
- reason: The join is mainly used to test matching rows and then DISTINCT is applied; a semi-join/EXISTS form can avoid duplicate join output.

Pred SQL:

```sql
SELECT DISTINCT s.Zip
FROM frpm f
JOIN schools s ON f.CDSCode = s.CDSCode
WHERE f.`Charter School (Y/N)` = 1 
  AND f.`District Name` = 'Fresno County Office of Education'
```

Gold SQL:

```sql
SELECT T2.Zip FROM frpm AS T1 INNER JOIN schools AS T2 ON T1.CDSCode = T2.CDSCode WHERE T1.`District Name` = 'Fresno County Office of Education' AND T1.`Charter School (Y/N)` = 1
```

Notes: taxonomy_rule_reviewed

### Others (28%)

<span style="color:red"><strong>Description:</strong> This major category covers general optimization patterns that do not fit neatly into join, subquery, access, or timing categories.</span>


#### Constant Folding

<span style="color:red"><strong>Description:</strong> This category refers to precomputing constant expressions before execution instead of repeatedly evaluating fixed arithmetic inside the SQL plan.</span>


- id: 47
- db_id: california_schools
- question: What is the monthly average number of schools that opened in Alameda County under the jurisdiction of the Elementary School District in 1980?
- evidence: Elementary School District refers to DOC = 52; Monthly average number of schools that opened in 1980 = count(schools that opened in 1980) / 12
- reason: The SQL contains constant arithmetic that can be computed once before execution.

Pred SQL:

```sql
SELECT COUNT(*)/12.0 
FROM schools 
WHERE OpenDate >= '1980-01-01' 
  AND OpenDate < '1981-01-01' 
  AND County = 'Alameda' 
  AND DOC = 52
```

Gold SQL:

```sql
SELECT CAST(COUNT(School) AS REAL) / 12 FROM schools WHERE DOC = 52 AND County = 'Alameda' AND strftime('%Y', OpenDate) = '1980'
```

Notes: taxonomy_rule_reviewed

#### Fan-Out Pruning

<span style="color:red"><strong>Description:</strong> This category refers to reducing duplicate-generating join expansion before applying DISTINCT or final projection.</span>


- id: 724
- db_id: superhero
- question: Please list the superhero names of all the superheroes that have blue eyes and blond hair.
- evidence: blue eyes refers to colour = 'Blue' and eye_colour_id = colour.id; blond hair refers to colour = 'Blond' and hair_colour_id = colour.id; super power of "Agility" refers to power_name = 'Agility'
- reason: The query joins multiple tables and then removes duplicates with DISTINCT, suggesting join fan-out can be reduced before deduplication.

Pred SQL:

```sql
SELECT DISTINCT s.superhero_name
FROM superhero s
JOIN colour eye_c ON s.eye_colour_id = eye_c.id AND eye_c.colour = 'Blue'
JOIN colour hair_c ON s.hair_colour_id = hair_c.id AND hair_c.colour = 'Blond'
```

Gold SQL:

```sql
SELECT T1.superhero_name FROM superhero AS T1 INNER JOIN colour AS T2 ON T1.eye_colour_id = T2.id INNER JOIN colour AS T3 ON T1.hair_colour_id = T3.id WHERE T2.colour = 'Blue' AND T3.colour = 'Blond'
```

Notes: taxonomy_rule_reviewed

#### Predicate Pull-down

<span style="color:red"><strong>Description:</strong> This category refers to moving filters closer to the base tables or lower query levels so later operations handle fewer rows.</span>


- id: 3
- db_id: california_schools
- question: What is the unabbreviated mailing street address of the school with the highest FRPM count for K-12 students?
- evidence: 
- reason: The SQL is correct and has filters; pushing predicates closer to base table scans can reduce downstream processing.

Pred SQL:

```sql
SELECT s."MailStreet"
FROM frpm f
JOIN schools s ON f."CDSCode" = s."CDSCode"
WHERE f."FRPM Count (K-12)" IS NOT NULL
ORDER BY f."FRPM Count (K-12)" DESC
LIMIT 1
```

Gold SQL:

```sql
SELECT T2.MailStreet FROM frpm AS T1 INNER JOIN schools AS T2 ON T1.CDSCode = T2.CDSCode ORDER BY T1.`FRPM Count (K-12)` DESC LIMIT 1
```

Notes: taxonomy_rule_reviewed

#### SARGable Rewrite

<span style="color:red"><strong>Description:</strong> This category refers to rewriting non-index-friendly predicates, especially functions on columns, into searchable range or equality conditions.</span>


- id: 292
- db_id: toxicology
- question: Identify the atoms belong to the molecule with ID between TR010 to TR050 that contain the element carbon.
- evidence: carbon refers to element = 'c'; between TR010 to TR050 refers to substr(molecule_id, 3, 3)>=10 AND substr(molecule_id, 3, 3) <= 50
- reason: The WHERE clause uses a function or non-index-friendly pattern on a column; rewriting it into a searchable range/equality predicate can improve access.

Pred SQL:

```sql
SELECT atom_id
FROM atom
WHERE 
    element = 'c'
    AND 
    CAST(substr(molecule_id, 3, 3) AS INTEGER) >= 10 
    AND 
    CAST(substr(molecule_id, 3, 3) AS INTEGER) <= 50;
```

Gold SQL:

```sql
SELECT T.atom_id FROM atom AS T WHERE T.molecule_id BETWEEN 'TR010' AND 'TR050' AND T.element = 'c'
```

Notes: taxonomy_rule_reviewed

### Subquery Logic (5%)

<span style="color:red"><strong>Description:</strong> This major category covers inefficiencies caused by subquery structure, including unnecessary nesting, correlated execution, or set logic that could be simplified.</span>


#### Plan Flattening

<span style="color:red"><strong>Description:</strong> This category refers to removing unnecessary derived-table layers so the optimizer can work with a simpler single-level query plan.</span>


- id: 245
- db_id: toxicology
- question: What is the average number of bonds the atoms with the element iodine have?
- evidence: atoms with the element iodine refers to element = 'i'; average = DIVIDE(COUND(bond_id), COUNT(atom_id)) where element = 'i'
- reason: The derived-table nesting mostly passes rows upward and can be flattened into a simpler single-level query.

Pred SQL:

```sql
SELECT AVG(bond_count) 
FROM (
    SELECT COUNT(c.bond_id) as bond_count
    FROM atom a
    JOIN connected c ON a.atom_id = c.atom_id
    WHERE a.element = 'i'
    GROUP BY a.atom_id
) subquery
```

Gold SQL:

```sql
SELECT CAST(COUNT(T2.bond_id) AS REAL) / COUNT(T1.atom_id) FROM atom AS T1 INNER JOIN connected AS T2 ON T1.atom_id = T2.atom_id WHERE T1.element = 'i'
```

Notes: taxonomy_rule_reviewed

#### Subquery Decorrelation

<span style="color:red"><strong>Description:</strong> This category refers to rewriting correlated subqueries that may run once per outer row into joins or pre-aggregated tables.</span>


- id: 1258
- db_id: thrombosis_prediction
- question: How many patients with a normal Rhuematoid Factor has a positive measure of degree of coagulation?
- evidence: normal Rhuematoid Factor refers TO RA IN('-', '+-'); positive measure of degree of coagulation refers to KCT = '+'; Should compute the number of distinct ones
- reason: The predicted SQL contains a correlated subquery that may be evaluated per outer row; pre-aggregation or join rewriting can avoid repeated execution.

Pred SQL:

```sql
SELECT COUNT(*) 
FROM (
    SELECT DISTINCT L."ID"
    FROM "Laboratory" L
    WHERE L."RA" IN ('-', '+-')
    INTERSECT
    SELECT DISTINCT E."ID"
    FROM "Examination" E
    WHERE E."KCT" = '+'
) AS common_patients
```

Gold SQL:

```sql
SELECT COUNT(DISTINCT T1.ID) FROM Patient AS T1 INNER JOIN Laboratory AS T2 ON T1.ID = T2.ID INNER JOIN Examination AS T3 ON T3.ID = T2.ID WHERE (T2.RA = '-' OR T2.RA = '+-') AND T3.KCT = '+'
```

Notes: taxonomy_rule_reviewed

#### Subquery Decoupling

<span style="color:red"><strong>Description:</strong> This category refers to separating filtering, grouping, and projection responsibilities so the query is easier for the optimizer to simplify.</span>


- id: 92
- db_id: financial
- question: List out the no. of districts that have female average salary is more than 6000 but less than 10000?
- evidence: A11 refers to average salary; Female mapps to gender = 'F'
- reason: The SQL uses a subquery whose filtering, aggregation, or projection can be separated to make optimization clearer.

Pred SQL:

```sql
SELECT COUNT(*) 
FROM (
    SELECT d.district_id
    FROM client c
    INNER JOIN district d ON c.district_id = d.district_id
    WHERE c.gender = 'F' 
      AND d.A11 > 6000 
      AND d.A11 < 10000
    GROUP BY d.district_id
) AS filtered_districts
```

Gold SQL:

```sql
SELECT COUNT(DISTINCT T2.district_id)  FROM client AS T1 INNER JOIN district AS T2 ON T1.district_id = T2.district_id WHERE T1.gender = 'F' AND T2.A11 BETWEEN 6000 AND 10000
```

Notes: taxonomy_rule_reviewed

#### Subquery Joinify

<span style="color:red"><strong>Description:</strong> This category refers to converting IN, NOT IN, or EXISTS subqueries into join or semi-join forms where set-wise planning is more efficient.</span>


- id: 887
- db_id: formula_1
- question: Name the races in year 2017 that are not hosted in year 2000.
- evidence: not hosted means not in;
- reason: The IN/EXISTS subquery can often be represented as a join or semi-join so the optimizer can plan it set-wise.

Pred SQL:

```sql
SELECT name FROM races WHERE year = 2017 AND name NOT IN (SELECT name FROM races WHERE year = 2000)
```

Gold SQL:

```sql
SELECT name FROM races WHERE year = 2017 AND name NOT IN ( SELECT name FROM races WHERE year = 2000 )
```

Notes: taxonomy_rule_reviewed

### Timing Strategy (5%)

<span style="color:red"><strong>Description:</strong> This major category covers optimization opportunities based on when operations happen, such as aggregating, filtering, or joining earlier or later.</span>


#### Early Aggregation

<span style="color:red"><strong>Description:</strong> This category refers to aggregating on the relevant key before joining so the joined input becomes smaller.</span>


- id: 128
- db_id: financial
- question: List the top nine districts, by descending order, from the highest to the lowest, the number of female account holders.
- evidence: A2 refers to districts; Female refers to gender = 'F'
- reason: The SQL joins and groups data; aggregating on the relevant key before the join may shrink the joined input.

Pred SQL:

```sql
SELECT d.A2, COUNT(c.client_id) AS female_count 
FROM client c 
JOIN district d ON c.district_id = d.district_id 
WHERE c.gender = 'F' 
GROUP BY d.A2 
ORDER BY COUNT(c.client_id) DESC 
LIMIT 9
```

Gold SQL:

```sql
SELECT T2.A2, COUNT(T1.client_id) FROM client AS T1 INNER JOIN district AS T2 ON T1.district_id = T2.district_id WHERE T1.gender = 'F' GROUP BY T2.district_id, T2.A2 ORDER BY COUNT(T1.client_id) DESC LIMIT 9
```

Notes: taxonomy_rule_reviewed

#### Join Reordering

<span style="color:red"><strong>Description:</strong> This category refers to applying selective filters and choosing a better join order to reduce intermediate result sizes.</span>


- id: 106
- db_id: financial
- question: What is the biggest amount of transaction that the client whose card was opened in 1996/10/21 made?
- evidence: 
- reason: The SQL has multiple joins; applying selective filters before or during join ordering can reduce intermediate result size.

Pred SQL:

```sql
SELECT MAX(t.amount) 
FROM card c
JOIN disp d ON c.disp_id = d.disp_id
JOIN account a ON d.account_id = a.account_id
JOIN trans t ON a.account_id = t.account_id
WHERE c.issued = '1996-10-21'
```

Gold SQL:

```sql
SELECT T4.amount FROM card AS T1 JOIN disp AS T2 ON T1.disp_id = T2.disp_id JOIN account AS T3 on T2.account_id = T3.account_id JOIN trans AS T4 on T3.account_id = T4.account_id WHERE T1.issued = '1996-10-21' ORDER BY T4.amount DESC LIMIT 1
```

Notes: taxonomy_rule_reviewed
