# Assessment submission as an early-warning signal

A student who has not submitted a single assessment due so far is at risk. Measured across all
seven modules, this is **the sharpest single signal in the dataset** — precision 0.74 to 0.93,
firing 15 to 59 days before the day-90 model.

Phases 1 and 2 complete: measured offline, ported to Cypher, reconciled exactly. Phase 3 (adding
it to the model) is not done.

---

## Why this was available and unused

`WAS_ASSESSED_IN` is excluded from every model here because assessment **scores** determine
`finalResult`. That is right for scores. It also discarded **whether a student submitted at all**,
which is behaviour rather than outcome.

The objection is that a withdrawn student never submits, so non-submission *is* the outcome. That
applies with equal force to clicks — a withdrawn student stops clicking, and the day-90 model
rests entirely on reading that. The test is not correlation with the outcome; it is whether the
fact is **observable at the decision point without the label**. At day 33 you know who missed the
TMA due on day 19. You do not know `finalResult` until the presentation ends.

Scores stay excluded. Submission does not need to be.

---

## Phase 1 — is it additive to the day-7 rule?

The concern going in was overlap: BBB's first assessment falls on day 12, five days after the
[zero-activity rule](early-warning-rule.md) fires, so much of the signal might be students already
caught for free.

**The four cells at day 90**, over the 25,562 students still registered:

| day-7 rule | missed all assessments | students | share | at-risk rate |
| --- | --- | --- | --- | --- |
| no | no | 22,012 | 86.1% | 0.342 |
| no | **yes** | **1,312** | **5.1%** | **0.912** |
| yes | yes | 823 | 3.2% | 0.926 |
| yes | no | 1,415 | 5.5% | 0.497 |

**1,312 students at 91.2% at risk that the rule never sees.** The signal is additive.

### The go criterion, and how narrowly it passed

Fixed before measuring: the marginal cell must hold ≥5% of the cohort at ≥0.75 at-risk rate, in at
least 4 of 7 modules.

| module | cohort | marginal n | share | at-risk rate | passes |
| --- | --- | --- | --- | --- | --- |
| AAA | 693 | 22 | 0.032 | 0.773 | no |
| BBB | 6,089 | 209 | 0.034 | 0.952 | no |
| CCC | 3,054 | 122 | 0.040 | 0.926 | no |
| DDD | 4,835 | 308 | 0.064 | 0.893 | **yes** |
| EEE | 2,412 | 124 | 0.051 | 0.984 | **yes** |
| FFF | 6,105 | 337 | 0.055 | 0.908 | **yes** |
| GGG | 2,374 | 190 | 0.080 | 0.863 | **yes** |

**4 of 7 — exactly the threshold.** Worth being precise about how it passed: the three failures are
all on *share*, not rate, and **every module clears the rate bar**, from 0.773 to 0.984. The signal
is uniformly high quality; only the volume varies. Read it as "reliable but sometimes small",
not as "worked in four modules and failed in three".

### An unplanned finding: submission refines the rule as well as extending it

Students the day-7 rule flags who then **do** submit are only **49.7%** at risk, against 92.6% for
those who don't. The rule alone substantially over-flags that group. Combining the two gives a
four-tier triage rather than two independent alarms:

| priority | cell | students | at-risk |
| --- | --- | --- | --- |
| 1 | silent at day 7 **and** no submission | 823 | 0.926 |
| 2 | active early, then no submission | 1,312 | 0.912 |
| 3 | silent at day 7, but submitted | 1,415 | 0.497 |
| 4 | neither | 22,012 | 0.342 |

---

## The trigger in operation

Judged 14 days after the first assessment is due:

| module | fires at day | flagged | precision | base rate | lift | new vs rule | lead over day 90 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AAA | 33 | 50 | 0.740 | 0.257 | 2.88 | 44 | 57d |
| BBB | 31 | 672 | 0.897 | 0.414 | 2.17 | 342 | 59d |
| CCC | 32 | 361 | 0.906 | 0.513 | 1.77 | 248 | 58d |
| DDD | 37 | 605 | 0.886 | 0.499 | 1.77 | 465 | 53d |
| EEE | 47 | 277 | 0.931 | 0.341 | 2.73 | 179 | 43d |
| FFF | 36 | 656 | 0.892 | 0.442 | 2.02 | 493 | 55d |
| GGG | 75 | 398 | 0.847 | 0.365 | 2.32 | 213 | 15d |

**It beats the day-90 model on precision in both modules the model has been measured on** — 0.847
against 0.722 on GGG, 0.897 against 0.838 on BBB — and arrives 15 and 59 days earlier. Recall is
lower (0.17–0.41 per presentation against the model's 0.372 and 0.528): a sharper, smaller net.

GGG is the weak case, and instructively so. Its first assessment is on day 61, so the trigger buys
only 15 days over the model. For modules whose first assessment falls late, this adds little in the
window where intervention actually helps.

### Why 14 days of grace, and the quirk that forced it

Late submission is normal — 28.4% of all submissions arrive after the due date. Worse, **three
presentations record zero submissions on or before the due date**:

| presentation | due day | on/before due | within +7d | median |
| --- | --- | --- | --- | --- |
| CCC 2014B | 18 | **0.0%** | 99.9% | +2d |
| CCC 2014J | 18 | **0.0%** | 99.8% | +3d |
| DDD 2013B | 23 | **0.0%** | 99.6% | +2d |
| *(every other presentation)* | — | 87–95% | 96–99% | −1 to −3d |

The recorded `date` is evidently not the operative deadline in those three. Judged on the due date,
the trigger flagged **100% of those cohorts** with precision equal to the base rate — a result that
looks like a finding and is an artefact. At +14 days, 97–100% of genuine submitters have arrived
everywhere.

---

## Phase 2 — the Cypher, reconciled

```cypher
MATCH (c:Course {codeModule: $module, codePresentation: $presentation})
OPTIONAL MATCH (c)-[:HAS_ASSESSMENT]->(a:Assessment)
WHERE a.date IS NOT NULL AND NOT isNaN(a.date)
  AND a.assessmentType <> 'Exam'
  AND a.date <= $day
WITH c, collect(a) AS due
WITH c, due, size(due) AS nDue
MATCH (s:Student)-[:WAS_REGISTERED]->(:StudentRegistration)-[cc:CONTAINS_COURSE]->(c)
WHERE cc.dateUnregistration IS NULL
   OR isNaN(cc.dateUnregistration)
   OR cc.dateUnregistration > $day
OPTIONAL MATCH (s)-[w:WAS_ASSESSED_IN]->(a2:Assessment)
WHERE a2 IN due
  AND w.dateSubmitted <= $day
  AND (w.isBanked IS NULL OR w.isBanked = 0)
WITH nDue, s, count(DISTINCT a2) AS nSubmitted
WHERE nDue > 0 AND nSubmitted = 0
RETURN s.id AS studentId
```

**Reconciliation: 176 of 176 comparisons exact**, across 22 presentations × two evaluation days ×
four quantities (`assessmentsDue`, `population`, `missedAll`, `missedAllAtRisk`). Zero gaps,
against a gate of 1%.

That is tighter than the [zero-activity rule](early-warning-rule.md), which reconciled to within
four students. The reason is worth keeping: **scoping through `Course` on both `codeModule` and
`codePresentation` sidesteps the dual-presentation collapse.** A `Student` is one node across
presentations, but each `StudentRegistration`→`Course` edge is presentation-specific, so a
presentation-scoped query matches the CSVs exactly while a module-scoped one inherits the
collapse.

### Which guards actually matter

Measured by removing each one, over four sample presentations:

| variant | population | flagged | precision |
| --- | --- | --- | --- |
| both guards (correct) | 6,335 | 765 | 0.851 |
| no `isNaN` on `a.date` | 6,335 | 765 | 0.851 |
| **no `isNaN` on `dateUnregistration`** | **1,155** | 217 | **1.000** |
| **no banked exclusion** | 6,335 | **634** | 0.886 |

**`isNaN` on `dateUnregistration` is critical** — without it the population collapses by 82% and
precision reads a perfect 1.000, because 22,521 of 32,593 values are NaN and none are null.

**The banked exclusion is real**: 1,909 rows carry a score from a previous sitting, and counting
them as engagement loses 131 flags across these four presentations.

**`isNaN` on `a.date` is *not* load-bearing here.** It measures identically with and without,
because `a.date <= $day` already excludes NaN — every comparison with NaN is false. It stays as a
guard against the date filter being removed, but it is not what makes this query correct, and the
plan for this work claimed otherwise.

---

## What is not done

**Phase 3 — adding these as model features** — has not been run. The open question is whether
`logClicks + submission` matches `journeyEmbedding + logClicks + submission`; if it does, the
FastPath embedding contributes nothing once submission behaviour is present.

**Everything is measured against the final outcome on the full dataset**, with no train/test split,
because the trigger has no parameters to fit. That is legitimate for a fixed rule and would not be
for a model.

**The split is not temporal.** Like everything else in this repository, presentations are pooled
rather than held out in time order.

---

## Caveats

**Precision is not actionability.** A student who has missed the first TMA may already be past
recovery. High precision and low remediability is a real combination, and nothing here measures
whether contacting these students changes anything.

**Module timing varies by a factor of five** — first assessment between day 12 and day 61. This is
a per-presentation trigger, and its lead time must be quoted per presentation.

**Recall is modest**, 0.17–0.41. It is a high-confidence shortlist, not coverage.

---

## Reproducing

```bash
python scripts/assessment_submission.py         # Phase 1, offline, no database
python scripts/assessment_submission_graph.py   # Phase 2, reconciliation, exits 1 on gate failure
```
