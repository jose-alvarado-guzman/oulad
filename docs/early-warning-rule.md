# The zero-activity rule

A student who is still registered and has not touched a single material by day *D* is at risk.
No graph analytics, no embedding, no session — one `NOT EXISTS` clause, weeks before any model
in this repository can say anything.

This document is the measurement. It exists because the claim that motivated the rule turned out
not to support it.

---

## The claim that started this, and why it was wrong

`README.md` and `docs/model-selection.md` both said:

> 1,208 of 7,692 students registered in module BBB never touched a material, and 88.1% of them
> withdrew.

The arithmetic is right — the figure is 1,287 of 7,909 registrations and 88.03%. As evidence for
an early-warning rule it is close to worthless, for two reasons.

**It measures the whole presentation, not a decision point.** "Never touched a material *ever*" is
knowable only in hindsight. A rule has to fire on what is visible on day *D*.

**It is dominated by students who left before the module started.** Of those 1,287, **790 (61.4%)
unregistered before day 0.** The headline is largely "students who quit before teaching began were
later recorded as withdrawn."

Measured properly — among students *still registered* at day *D* — the overstatement is severe and
grows with the threshold:

| day | withdrawal rate among flagged, all registered | still registered only | overstated by |
| --- | --- | --- | --- |
| 7 | 0.647 | 0.340 | **+0.307** |
| 14 | 0.727 | 0.273 | **+0.454** |
| 21 | 0.785 | 0.277 | **+0.509** |
| 28 | 0.811 | 0.222 | **+0.589** |

---

## The rule does not predict withdrawal

Among students still registered at the threshold, against `final_result = 'Withdrawn'`:

| day | population | flagged | % of cohort | withdrawal rate flagged | base rate | lift | recall |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 7 | 29,178 | 2,924 | 10.0% | 0.340 | 0.219 | 1.55 | 0.147 |
| 14 | 28,119 | 1,691 | 6.0% | 0.273 | 0.198 | 1.38 | 0.081 |
| 21 | 27,908 | 1,185 | 4.3% | 0.277 | 0.193 | 1.44 | 0.060 |
| 28 | 27,538 | 921 | 3.3% | 0.222 | 0.184 | 1.20 | 0.040 |

Lift of 1.2 to 1.55 and recall under 15%. On its own that would be a negative result and the end
of the idea.

## It predicts *failure*

Silent students overwhelmingly go on to **fail** rather than formally withdraw. Against
`Withdrawn OR Fail` — the same target the day-90 model is trained on:

| day | flagged | % of cohort | **precision** | base rate | lift | recall | caught / at risk |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **7** | 2,924 | 10.0% | **0.736** | 0.473 | 1.66 | **0.156** | 2,151 / 13,793 |
| 14 | 1,691 | 6.0% | 0.765 | 0.453 | 1.77 | 0.102 | 1,293 / 12,734 |
| 21 | 1,185 | 4.3% | 0.813 | 0.449 | 1.88 | 0.077 | 963 / 12,523 |
| 28 | 921 | 3.3% | 0.823 | 0.441 | 1.92 | 0.062 | 758 / 12,153 |

Roughly **three of every four students who are still enrolled and silent are going to fail or
withdraw**, against a base rate of about 45%.

### Take day 7, not day 28

Precision rises only 8.7 points from day 7 to day 28 while recall falls by 60%. The rule's entire
value is lead time, so the earliest threshold with the best coverage wins. Day 14 was the
threshold originally proposed here and it is dominated by day 7 on both counts that matter.

---

## Per module

Pooled figures hide the same spread the model shows. Day 14, at-risk target:

| module | population | flagged | precision | base rate | lift | recall |
| --- | --- | --- | --- | --- | --- | --- |
| AAA | 722 | 5 | 0.800 | 0.265 | 3.02 | 0.021 |
| BBB | 6,566 | 622 | 0.764 | 0.428 | 1.78 | 0.169 |
| CCC | 3,675 | 147 | 0.884 | 0.543 | 1.63 | 0.065 |
| DDD | 5,411 | 191 | 0.859 | 0.518 | 1.66 | 0.059 |
| EEE | 2,576 | 124 | 0.823 | 0.360 | 2.29 | 0.110 |
| FFF | 6,720 | 207 | 0.879 | 0.457 | 1.92 | 0.059 |
| GGG | 2,449 | 395 | 0.598 | 0.382 | 1.56 | 0.252 |

GGG is the weakest module for the rule and the one where most students start late — it flags 16.1%
of the cohort at 0.598 precision. AAA has 5 flagged students in total, so its 0.800 is four
students and should not be read as a rate.

---

## It does not replace the model

| | precision | recall | fires at |
| --- | --- | --- | --- |
| rule, GGG | 0.598 | 0.252 | day 7–14 |
| day-90 model, GGG | 0.722 | 0.372 | day 90 |
| rule, BBB | 0.764 | 0.169 | day 7–14 |
| day-90 model, BBB | 0.838 | 0.528 | day 90 |

The model wins on both axes in both modules. What the rule buys is **76 to 83 days of lead time
for nothing** — no session, no chain build, no embedding. The two are complements: the rule takes
the students who never start, the model takes the students who start and fade.

See [`model-selection.md`](model-selection.md) for the model's marginal value once the rule has
taken its share.

---

## The query

```cypher
MATCH (s:Student)-[:WAS_REGISTERED]->(:StudentRegistration)-[cc:CONTAINS_COURSE]->(c:Course)
WHERE c.codeModule = $module
WITH s, max(CASE WHEN cc.dateUnregistration IS NULL
                   OR isNaN(cc.dateUnregistration)          // see below
                   OR cc.dateUnregistration > $day
                 THEN 1 ELSE 0 END) AS stillRegistered
OPTIONAL MATCH (s)-[r:REVIEWED_MATERIAL]->(:EducationalMaterial)<-[:HAS_MATERIAL]-(c2:Course)
WHERE c2.codeModule = $module AND r.date <= $day
WITH s, stillRegistered, count(r) AS earlyEvents
WHERE stillRegistered = 1 AND earlyEvents = 0
RETURN s.id AS studentId
```

Both facts it depends on are observable on day *D*: who has unregistered so far, and who has
clicked so far. Nothing here reads the future.

### `isNaN` is load-bearing, and leaving it out fails silently

**22,521 of 32,593 `dateUnregistration` values are float `NaN`. None are `null`.** pandas writes
missing numerics as NaN and the driver stores them as real floats, so:

- `r.dateUnregistration IS NULL` → **false** for every missing value
- `r.dateUnregistration > 14` → **false** as well, because every comparison with NaN is false

An `IS NULL OR > $day` test therefore excludes every student who never unregistered — which is
69% of the data, and precisely the students the rule is about. For GGG at day 14 that returns
**49** flagged students instead of **391**, an 8× undercount, with no error and a plausible-looking
result. `dateRegistration` carries 45 NaN values with the same hazard.

This is a property of the loaded graph, not of this query. Any Cypher in this repository that
null-checks a numeric column sourced from pandas needs the same guard.

### Reconciliation

The graph rule was validated against the offline measurement: GGG at day 14 gives **391 flagged /
2,444 population** in Cypher against **395 / 2,449** in pandas. The four-student gap is students
enrolled in two GGG presentations, which the graph collapses to one `Student` node and the CSV
keeps as two rows.

---

## Caveats

**Four of the flagged population's defining attributes are not demographic — this rule is purely
behavioural**, which is worth keeping if it is ever compared against a model that uses region, IMD
band, age or disability. Those are protected or near-protected characteristics under UK equality
law; targeting *support* with them is defensible, gating anything with them is not.

**Lead time is not uniform.** At day 7, 36.2% of flagged students who eventually unregister do so
within a week — for that third the flag is nearly concurrent with the withdrawal rather than ahead
of it. The at-risk framing is less exposed to this, since failure is only determined at the end of
the presentation.

**A flag is not a diagnosis.** The rule cannot distinguish a student who has dropped out in all but
name from one who registered late or is studying offline. It identifies a population worth
contacting, and the contact is what establishes which.

---

## Reproducing

Offline, from the gitignored `Data/` directory, no database required:

```bash
python scripts/zero_activity_rule.py
```

Reads `studentRegistration.csv`, `studentInfo.csv` and `studentVle.csv`, computes the first
activity day per student-presentation once, then sweeps the thresholds.
