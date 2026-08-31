# Model selection: predicting OULAD module outcome from the graph

A record of what was tried, what the numbers were, which conclusions turned out to be wrong,
and what the wrong ones cost. Every figure here came from a run against a live AuraDB instance
and an Aura Graph Analytics session; nothing is estimated.

---

## The question

Given the OULAD graph, can a student's **final result** be predicted from their position in it —
which materials they engaged with, in what order, and which demographic groups they belong to?

Binary target: `passed = 1` for `Pass` or `Distinction`, `0` for `Fail` or `Withdrawn`, taken
from `finalResult` on `(:StudentRegistration)-[:CONTAINS_COURSE]->(:Course)`.

Module **GGG** throughout, except where noted. It has 2,531 registered students, 2,359 of whom
touched at least one material, across 281,277 interactions.

### What was deliberately excluded, and why

**Assessment relationships.** `WAS_ASSESSED_IN` carries scores, and scores determine
`finalResult` almost by definition. Predicting an outcome from the marks that produced it is
leakage in a costume. Only engagement and demographics were used.

Two things sit closer to that line than they look, and both are called out in the notebooks:
`date_unregistration` on `CONTAINS_COURSE` is effectively the withdrawal label, and interactions
recorded *after* a student stopped participating leak the same information backwards. The second
turned out to matter enormously — see the cutoff sweep.

### A structural blind spot

**1,287 of 7,909 BBB registrations never touched a material**, and 88.0% of them withdrew against
19.0% of engaged students. A student with no interactions has no edges, so cannot be projected,
embedded, or classified. Every result below is therefore conditional on having engaged at all, and
the excluded group is the one an intervention would most want to reach.

That 88.0% is a real number and a bad argument, which took a dedicated measurement to establish —
**790 of those 1,287 students (61.4%) unregistered before day 0.** It is largely "students who quit
before teaching began were recorded as withdrawn." It says nothing about what is visible at a
decision point, and it was cited here and in `README.md` as support for a day-14 rule that nobody
had measured. See [`early-warning-rule.md`](early-warning-rule.md) for the rule as it would
actually be operated: it does *not* predict withdrawal (lift 1.38 at day 14), but it does predict
failure — **precision 0.736 at day 7 against a 0.473 base rate**, 83 days before this model can
speak.

---

## The bar

Any model has to beat these. Both computed over the same population the models see.

| baseline | F1 macro | accuracy |
| --- | --- | --- |
| always predict the majority class | — | 0.6393 |
| `clicks >= median`, no model at all | 0.7635 | 0.7681 |
| `logClicks` through the same random forest | 0.8436 | 0.8658 |

The third row is the one that matters. A single logged aggregate, given a decent model, reaches
0.8658 — and it is the reason several apparently good results below are not good at all.

---

## Method 1 — weighted node similarity and Louvain cohorts

`notebooks/aga_student_cohorts.ipynb`, module BBB.

Project the `(:Student)-[:REVIEWED_MATERIAL]->(:EducationalMaterial)` bipartite graph aggregated
to one relationship per pair, run node similarity (Jaccard, weighted by clicks) to link
comparable learners, then Louvain over those links.

| | similarity mean | cohorts | modularity |
| --- | --- | --- | --- |
| unweighted Jaccard | 0.6401 | 14 | 0.8183 |
| weighted by clicks | 0.5786 | 15 | 0.8510 |

Weighting is stricter and separates better. The cohorts track outcomes strikingly: pass rates
from **0.8% to 72.4%** against a 39.2% module baseline.

**Status: descriptive, not predictive.** This is unsupervised clustering scored on outcome
spread, which is a legitimate way to describe a population but is not a model and produces no
held-out metric. It is also the analysis that surfaced the zero-engagement blind spot above.

---

## Method 2 — FastRP embedding into a node classification pipeline

`notebooks/aga_outcome_prediction.ipynb`. FastRP over each student's engagement and demographic
neighbourhood, fed to a GDS node classification pipeline. Held-out 30% split, 2,525 students.

| features | F1 macro | accuracy |
| --- | --- | --- |
| embedding only | 0.3720 | 0.5923 |
| volume only (`logClicks`) | 0.8428 | 0.8549 |
| embedding + volume | 0.8475 | 0.8588 |

**The embedding alone is a constant classifier.** It predicted "pass" for all 2,525 students —
1,508 right, 1,017 wrong. F1 macro 0.372 is exactly what a majority-class guess scores.

The mechanism: **FastRP normalises its embeddings, which suppresses degree**, and degree is the
signal here. Handing the model one logged click total fixes it completely, at which point it
catches 751 of 1,017 at-risk students.

**Status: the embedding contributes +0.4 accuracy points over one feature.** Noise on a
760-student split. The working model is real and useful; FastRP is not what makes it work.

---

## Method 3 — FastPath sequence embedding

`notebooks/aga_fastpath_journeys.ipynb`. The loaded graph has no sequence in it, so the notebook
builds one: `(:Student)-[:FIRST_INTERACTION]->(:Interaction)-[:NEXT_INTERACTION]->…`, one node
per (student, material, day) in date order — 281,277 nodes for GGG, deleted afterwards. FastPath
embeds each chain; the embedding is then scored as a classifier feature.

### The cutoff sweep

The decisive experiment. `CUTOFF_DAY` limits how much of each journey the model may see, so the
sweep answers *when* the information arrives rather than only whether a model works.

Accuracy as GDS reports it, GGG, on its own internal 30% test split — so these figures are
genuinely out-of-sample, unlike the precision figures the first version of this document carried:

| cutoff | students | majority | threshold | volume | **journey** | both |
| --- | --- | --- | --- | --- | --- | --- |
| day 30 | 2,199 | 0.6462 | 0.5703 | 0.6439 | **0.6348** | 0.6455 |
| day 60 | 2,314 | 0.6422 | 0.5808 | 0.6029 | **0.6892** | 0.6978 |
| day 90 | 2,342 | 0.6405 | 0.6161 | 0.6515 | **0.7127** | 0.7226 |
| whole journey | 2,359 | 0.6393 | 0.7681 | 0.8658 | **0.9280** | 0.9308 |

F1 macro for the journey embedding: 0.5198 → 0.5980 → 0.6449 → 0.9176.

Day 60 appears here and not in the holdout table below; the holdout sweep ran 30 / 90 / whole.

### At-risk detection — the table that should drive the decision

Accuracy counts every unflagged failure against the model, which punishes a conservative
classifier for being conservative. What an intervention team needs is how many students get
flagged, what share of eventual failures that catches (**recall**), and what share of the flags
are real (**precision**).

Evaluated on a **707-student holdout the model never trained on** (30%, seed 42), journey + volume:

| cutoff | at risk | flagged | recall | precision | accuracy |
| --- | --- | --- | --- | --- | --- |
| day 30 | 234 | 112 | 0.231 | 0.482 | 0.635 |
| **day 90** | 258 | 133 | **0.372** | **0.722** | 0.717 |
| whole journey | 261 | 204 | 0.759 | 0.971 | 0.902 |

Volume alone on the same holdout reaches precision 0.382, 0.417 and 0.825. **The embedding nearly
doubles it at day 90**, which is the clearest evidence in this exercise that the sequence carries
something an aggregate does not — and it survives an honest split.

#### The split, and why it had to be built by hand

GDS splits internally but does not expose which nodes its test set held, so `predict_stream` over
all students mixes training data into the evaluation. The split here is explicit: students carry an
`isHoldout` flag projected as a node property, the pipeline trains on a `TrainStudent` label and
predicts on `HoldoutStudent`.

**Order matters.** `fast_path.mutate` registers its output property against `base_node_label` only,
so a `TrainStudent` label that existed at projection time does not carry `journeyEmbedding` and
training dies with *"node properties do not exist in the graph or part of the pipeline"*. The
labels have to be added with `gds.graph.node_labels.mutate` **after** the embedding step.

#### How much the in-sample-inclusive figures overstated it

| cutoff | precision gap | recall gap | accuracy gap |
| --- | --- | --- | --- |
| day 30 | **+0.450** | +0.356 | +0.206 |
| day 90 | +0.165 | +0.144 | +0.090 |
| whole journey | +0.017 | +0.068 | +0.033 |

Day 30 was almost entirely memorisation: 0.932 precision in-sample against 0.482 held out.

Note the shape of those gaps. Accuracy moved 3–21 points while precision moved up to 45. Accuracy
is dominated by the majority class and conceals memorisation, so "the accuracy gap is small,
therefore the inflation is small" is not a valid argument — and it was the argument that let a bad
day-30 recommendation stand for one revision of this document.

The reassurance was circular on top of that. The accuracy column in the sweep above is GDS's own
held-out metric, so it *could not* show inflation; agreement between a clean number and a dirty one
says nothing about the dirty one. The holdout accuracy measured here (0.635 at day 30) lands close
to GDS's reported 0.6455, which confirms the two evaluations agree on accuracy while diverging by
45 points on precision.

### Validation on a second module

Everything above is module GGG. Repeating the identical procedure on **BBB** — 6,484 students,
1,139,085 events, days -23..268, same seed, same 30% holdout — gives 1,938 held-out students at
day 90:

| cutoff | features | flagged | of at risk | recall | precision | accuracy | precision gap |
| --- | --- | --- | --- | --- | --- | --- | --- |
| day 30 | volume | 549 | 812 | 0.425 | 0.628 | 0.650 | −0.015 |
| day 30 | both | 446 | 812 | 0.386 | 0.702 | 0.670 | +0.141 |
| day 90 | volume | 591 | 826 | 0.504 | 0.704 | 0.698 | −0.010 |
| **day 90** | **both** | **520** | **826** | **0.528** | **0.838** | 0.755 | **+0.015** |
| whole journey | volume | 735 | 829 | 0.679 | 0.766 | 0.775 | −0.011 |
| whole journey | both | 677 | 829 | 0.776 | 0.950 | 0.887 | +0.023 |

**The day-90 recommendation replicates, and more cleanly than on GGG.** Precision 0.838 against
GGG's 0.722, recall 0.528 against 0.372, and an inflation gap of +0.015 against +0.165.

**At day 90 the embedding dominates volume outright in both modules** — not a precision/recall
trade. On BBB it flags *fewer* students than volume (520 against 591) and catches *more* failures
(436 against 416). On GGG, 133 against 163 flags and 96 against 68 caught. That is the single most
robust result in this exercise.

**GGG's day-30 collapse does not generalise.** On BBB, day 30 holds out at 0.702 precision with a
+0.141 gap. Day 30 on GGG was memorisation; day 30 on BBB is signal. So "the embedding needs 60
days" is a statement about GGG, not about the method — which is exactly the kind of claim a single
module cannot support and is the reason this section exists.

**But the absolute numbers are not transferable.** Day-90 precision is 0.722 on GGG and 0.838 on
BBB for identical code and hyperparameters. Quote a range, or re-measure per module; do not quote
one module's figure as the model's performance.

#### Only the embedding inflates, and that is mechanically why

Across all six BBB configurations the volume-only gaps are −0.015 to −0.010 — negative, i.e. the
holdout scored *better* than the training rows, which is what you expect from noise around zero
inflation. Every positive gap belongs to a model carrying `journeyEmbedding`.

One logged feature cannot memorise 4,500 training rows; 129 features can. So the size of the gap
tracks feature dimensionality, not the cutoff, and any figure quoted for an embedding model
without a holdout should be assumed inflated. The corollary is reassuring in one direction: the
volume-only baselines in this document never needed the correction, so the comparisons that use
them as a floor were never wrong — only the embedding's own numbers were.

### Three readings

**On GGG the signal starts between day 30 and day 60.** At day 30 the embedding sits *below* the
majority floor — nothing works. By day 60 it is 4.7 points above it and still climbing. This is
where it matters that BBB behaves differently: its day-30 embedding already holds out at 0.702
precision, so the arrival time of the signal is a property of the presentation, not of the method.

**Inside that window, sequence beats volume decisively.** Journey minus volume, in accuracy
points: day 30 −0.9, **day 60 +8.6**, day 90 +6.1, whole journey +6.2. At day 60 click volume
alone (0.6029) is *worse than guessing*, while the shape of the same two months reaches 0.6892.

**The untruncated score is mostly hindsight.** 0.7127 at day 90 against 0.9280 at the end: about
two thirds of the apparent skill arrives after month three of a nine-month presentation, which is
largely the model noticing who stopped. For a withdrawal, "when did activity stop" is the label
restated.

### Sweep methodology

The sweep projects **day prefixes** of one chain rather than rebuilding four times. Because the
chain is ordered by day, a prefix by day is exactly the graph a truncated build produces — a
`tgt.day <= cutoff + SHIFT` filter is the whole trick. Verified: the day-30 and whole-journey
points reproduced their independent rebuilds *exactly* (0.6348 and 0.9280) on byte-identical
projections of 64,762 and 283,636 nodes.

`logClicks`, the threshold baseline and the majority floor are recomputed per window, so no
cutoff is scored against another's hindsight.

---

## Conclusions

### Recommended: FastPath journey + volume, cut at day 90

On holdouts the model never trained on: **precision 0.722 on GGG and 0.838 on BBB**, recall 0.372
and 0.528. It flags fewer students than a click-volume model and catches more of the failures, in
both modules — 133 flags catching 96 against volume's 163 catching 68 on GGG, and 520 catching 436
against 591 catching 416 on BBB.

Two modules is not "validated", but it is enough to say the result is not an artefact of GGG, and
enough to show the absolute number moves by 12 precision points between modules. Re-measure per
module rather than carrying a figure across.

**The zero-activity rule does not eat into this.** Restricted to holdout students the day-7 rule
did *not* already flag, precision rises to **0.760 on GGG and 0.856 on BBB** — the model performs
better on the population left after the rule, not worse. The overlap group is the model's weakest
(0.606 on GGG): students silent for a week and then engaging have an irregular journey the
embedding reads poorly. The two triggers are complements, and these committed figures are if
anything conservative. Full partition in [`early-warning-rule.md`](early-warning-rule.md).

**Day 30 is module-dependent, so do not ship it on one module's evidence.** An earlier version of
this document recommended a day-30 worklist on the strength of 0.923 precision. That figure
included training data; held out it is **0.482** on GGG, close to a coin flip on the flagged set.
On BBB the same configuration holds out at 0.702. Day 90 is the cutoff that worked in both, which
is why it is the recommendation.

### Amended by assessment submission

The figures above predate [`assessment-submission.md`](assessment-submission.md), which adds four
submission scalars to the same day-90 model. **The combined arm — journey embedding + volume +
submission — is the top-precision configuration in both modules**, 0.855 on BBB and 0.832 on GGG,
and it is the recommended day-90 model.

Adding submission moves precision **+0.283 on GGG and +0.092 on BBB** over the embedding alone,
the largest single gain recorded in this document.

The embedding's own marginal contribution over volume + submission varies by module: **+0.051 on
GGG against +0.008 on BBB**. GGG's first assessment falls on day 61, leaving only 9 gradeable
assessments by the cutoff against BBB's 15 — so the sparser the assessment evidence, the more the
sequence embedding carries. That is the useful predictor for an unseen module, not a reason to
drop it.

Those arms were compared within a single harness and are not directly comparable to the
GDS-derived numbers above.

### Cross-module transfer works, and costs nothing

The first transfer measurement in this repository. The recommended configuration was trained on
**BBB**, persisted to the Aura model catalog with `gds.model.store()`, then loaded in a separate
session and applied to **EEE**, which it had never seen — 2,632 students, 983 at risk, base rate
0.373.

Over the whole population it scores **precision 1.000 at k = 50, 100 and 200**. That number is
real and it is not the model's: `missedAll` alone flags 388 EEE students of whom 98.7% fail, so
any ranker respecting that boolean is perfect on the top 200. The refit-on-target control matching
it exactly was the tell — both were reading the same column.

**The informative test is the 2,244 students `missedAll` does not flag**, where the base rate is
0.2674:

| k | precision | recall | lift |
| --- | --- | --- | --- |
| 50 | 0.98 | 0.082 | **3.67** |
| 100 | 0.96 | 0.160 | **3.59** |
| 200 | 0.93 | 0.310 | **3.48** |
| 400 | 0.69 | 0.460 | 2.58 |

A hundred-student worklist that is 96% correct where a quarter of students fail, produced by a
model trained on a different module. Precision collapses past k ≈ 300, so the usable budget is
about 200.

**Transfer is free.** The refit-on-EEE control reached 0.98 at k = 50 and 100 against the
transferred model's 1.000 — transferring slightly *beat* retraining locally, which is within noise
but rules out a transfer penalty. Retraining per module is not required.

Two conditions make this work, and both are easy to lose. The activity-type vocabulary must be
enumerated globally rather than per module, or `activityTypeId` means different things in
different modules and the embedding spaces are unrelated. And the submission features must stay
scale-free — a ratio, two booleans and a day count — so they carry across modules with different
assessment counts.

**What this does not isolate.** The hard subpopulation still contains `submissionRate` and
`missedFirst`, so "beyond `missedAll`" is not "beyond submission behaviour". Separating the
embedding's own contribution on an unseen module would need the Phase 3 arms re-run on EEE. One
module, one seed.

### Not recommended

**The whole-journey model**, despite 0.902 holdout accuracy and 0.971 holdout precision. It needs the journey to
be finished, and once a presentation ends `finalResult` is already in the data — it predicts
something you know. Its apparent skill is largely the model noticing when activity stopped.

**FastRP**, worth +0.4 accuracy points over one logged aggregate. The pipeline complexity buys
nothing on this graph.

**Volume alone, early.** It works retrospectively (0.825 and 0.766 holdout precision on the whole
journey) but is beaten in the window that matters: 0.382 and 0.417 at days 30 and 90 on GGG, 0.628
and 0.704 on BBB, against 0.482/0.722 and 0.702/0.838 for the embedding. The interpretable single
feature is not a viable fallback for early warning — though it is the one baseline in this document
whose numbers needed no holdout correction, so it remains the honest floor to measure against.

### Before any of this ships

**Validate on the remaining five modules.** GGG and BBB agree on the recommendation and disagree by
12 precision points on its value, which is enough to rule out an artefact and not enough to
calibrate anything. AAA through FFF are unmeasured.

**Build the zero-activity rule first — it is measured, and it works.** Students still registered
and silent at day 7 fail or withdraw at **0.736** against a 0.473 base rate, with no graph
analytics and 83 days of lead time. It does not replace this model: on GGG and BBB the day-90
model wins on both precision and recall. The two are complements — the rule takes the students who
never start, the model takes the students who start and fade. Full measurement, including the
day-14 threshold this document originally proposed and why day 7 beats it, in
[`early-warning-rule.md`](early-warning-rule.md).

### On choosing a measure

The same FastPath embedding was judged three ways and got three verdicts: Louvain modularity said
it had failed, accuracy said it was mediocre early, precision said it produces a usable worklist.
None of the measurements were wrong; two of them were answering a question nobody was asking.

## Mistakes, and what they cost

The wrong turns are the most reusable part of this record.

**Measuring clustering quality instead of predictive performance.** Two FastPath runs were judged
on Louvain modularity — 0.5470 and 0.5122 — and both were read as failure. Modularity scores how
cleanly a similarity graph partitions, not whether the partition predicts anything. The same
embedding, scored as a classifier feature, reached 0.9280. **Cost: a nearly-abandoned method, and
a written conclusion that had to be retracted.**

**Never passing the feature to the algorithm.** `sumClick` was copied onto the event nodes and
projected into the session, then never handed to FastPath, because
`event_node_feature_vector_property` was unset. A page opened once and one hammered fifty times
were identical events. **Cost: an entire full-scale run measuring the wrong configuration.**

**Two wrong diagnoses of the same zero.** Weighted degree centrality returned 0.0 for every
material. First blamed on the projection dropping a property (disproved by probing a live
session), then on `orientation='REVERSE'` needing an inverse index (disproved by adding one). The
actual cause: `node_labels=['EducationalMaterial']` induces a subgraph of *material nodes only*,
which discards every `REVIEWED_MATERIAL` relationship, since each one's source is a `Student`.
Degree over a relationship-free subgraph is zero, silently. **Cost: two sessions and a committed
explanation that was wrong.**

**A rewritten query that changed its own grouping.** Dropping `s.id` from a baseline query's
`RETURN` made `sum()` aggregate by the class label, returning **2 rows instead of 2,359**. The
baseline and majority-class figures in that run were meaningless, which showed up as a suspicious
`0.5000`. **Cost: one misleading comparison table, caught by the number looking wrong.**

**A truncation that only truncated half the features.** `CUTOFF_DAY` initially gated the chain
build but not `logClicks` or the baseline, which would have pitted a 30-day sequence embedding
against nine months of hindsight volume. **Caught before running.**

**Overstating a result before testing it.** "The strongest predictor in this repository" was
written after the untruncated run and before the truncation test. It needed splitting into a
retrospective claim and an early-warning claim, which are not interchangeable.

**Recommending on accuracy.** The first version of this document called the day-60 model "modest,
~0.70 accuracy" and treated that as its ceiling. Measuring precision showed a much better-looking
worklist — the model is conservative, and accuracy penalises exactly that. **Cost: a
recommendation pitched below what the model can do.**

**Then recommending on in-sample precision.** The precision that replaced it was measured with
`predict_stream` over every labelled student, including the 70% trained on. Held out properly, day
90 fell from 0.857 to 0.722 and day 30 from 0.923 to **0.482** — the day-30 configuration was
recommended as a high-precision early worklist and is nothing of the kind. Worse, the inflation was
dismissed by pointing at a small accuracy gap, when accuracy is the metric least sensitive to
memorisation on an imbalanced target. **Cost: a recommendation that would have put a coin-flip
model in front of an intervention team.**

---

## What caught them

Worth keeping in any similar exercise:

- **A trivial baseline in the notebook, not in your head.** Every notebook trains or computes one.
  Most of the wrong conclusions above were caught by a single aggregate doing better.
- **Ablations built in.** Training embedding-only, feature-only and both is three runs of a few
  seconds and is the only way to attribute a gain.
- **Cross-check the session against the database.** The step that compares a session's weighted
  degree to `sum(r.sumClick)` from AuraDB is what surfaced the `node_labels` bug. The gap was
  420,908 before the fix and 0 after.
- **Guards that abort rather than warn.** A missing relationship weight is not an error in GDS —
  it is a silent zero. Projections now print what they actually carry and stop if a needed
  property is absent.
- **Anchor points in a sweep.** Including a cutoff whose answer is already known turns a
  shortcut into a self-validating one.

---

## Reproducing

| notebook | what it does | knobs |
| --- | --- | --- |
| `oulad_data_load.ipynb` | loads the graph | — |
| `aga_student_cohorts.ipynb` | similarity + Louvain cohorts | `MODULES`, `WEIGHT` |
| `aga_outcome_prediction.ipynb` | FastRP + classification, with ablation | `MODULE`, `PASS_RESULTS`, `VARIANTS` |
| `aga_fastpath_journeys.ipynb` | FastPath + classification, with sweep | `MODULE`, `MAX_STUDENTS`, `CUTOFF_DAY`, `RUN_SWEEP`, `SWEEP_CUTOFFS`, `DELETE_CHAIN` |

All three analytics notebooks delete their sessions, and the FastPath one deletes its event chain
and the two `Student` properties it writes. The graph returns to 66,920 nodes and 8,818,076
relationships, verified after every run in this record.

### Untested

- **Module FFF** — 6,799 students, 3,248,703 interactions, average chain 478 against GGG's 119.
  The day-60 finding is about *when* signal appears rather than chain length, so a longer module
  may not move it, but it is the obvious robustness check.
- **Finer cutoffs** — `[20, 30, 40, 50, 60]` would locate the onset more precisely than the
  current 30-to-60 bracket. Cheaper than FFF and more informative.
- **A day-cut feature set for the interpretable model** — `sum(sumClick)` and last-active-day
  computed at day 60, which is the honest comparison for the day-60 embedding.
