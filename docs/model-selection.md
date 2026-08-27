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

**1,208 of 7,692 students registered in module BBB never touched a material**, and 88.1% of them
withdrew, against 19.0% of engaged students. A student with no interactions has no edges, so
cannot be projected, embedded, or classified. Every result below is therefore conditional on
having engaged at all, and the excluded group is the one an intervention would most want to
reach. For GGG the equivalent figure is 172 students.

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

Accuracy, GGG, held-out 30% split:

| cutoff | students | majority | threshold | volume | **journey** | both |
| --- | --- | --- | --- | --- | --- | --- |
| day 30 | 2,199 | 0.6462 | 0.5703 | 0.6439 | **0.6348** | 0.6455 |
| day 60 | 2,314 | 0.6422 | 0.5808 | 0.6029 | **0.6892** | 0.6978 |
| day 90 | 2,342 | 0.6405 | 0.6161 | 0.6515 | **0.7127** | 0.7226 |
| whole journey | 2,359 | 0.6393 | 0.7681 | 0.8658 | **0.9280** | 0.9308 |

F1 macro for the journey embedding: 0.5198 → 0.5980 → 0.6449 → 0.9176.

### At-risk detection — the table that should drive the decision

Accuracy counts every unflagged failure against the model, which punishes a conservative
classifier for being conservative. What an intervention team needs is how many students get
flagged, what share of eventual failures that catches (**recall**), and what share of the flags
are real (**precision**). Journey + volume:

| cutoff | at risk | flagged | recall | precision | accuracy |
| --- | --- | --- | --- | --- | --- |
| day 30 | 773 | 271 | 0.323 | **0.923** | 0.6455 |
| day 60 | 822 | 420 | 0.381 | 0.745 | 0.6978 |
| **day 90** | 836 | 469 | **0.481** | **0.857** | 0.7226 |
| whole journey | 845 | 716 | 0.837 | 0.987 | 0.9308 |

Volume alone at the same cutoffs reaches precision 0.464, 0.523, 0.568 and 0.897. **The embedding
roughly doubles precision at every early cutoff** — a much stronger claim than the accuracy column
supports, and the clearest evidence in this exercise that the sequence carries something an
aggregate does not.

These figures come from `predict_stream` over every labelled student, including the 70% trained
on, so they read optimistic; GDS does not expose test-split membership. For the whole journey,
all-student agreement (0.9377) against held-out accuracy (0.9308) suggests the inflation is small,
but it is not quantified for precision.

### Three readings

**The signal starts between day 30 and day 60.** At day 30 the embedding sits *below* the
majority floor — nothing works. By day 60 it is 4.7 points above it and still climbing.

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

Flags 469 of 2,342 students; 402 of them genuinely fail. **Precision 0.857, recall 0.481.** It
beats day 60 on both measures at once — 0.481 against 0.381 recall, 0.857 against 0.745 precision
— so there is nothing to trade off between them. Roughly a fifth of the cohort is flagged and
about six in seven flags are real, which is a worklist an intervention team can act on.

**Day 30 is the alternative worth knowing about**: precision 0.923 on only 271 students, available
two months earlier. Lower coverage, cleaner list. If intervention capacity binds rather than
coverage, it is the better trade.

### Not recommended

**The whole-journey model**, despite 0.9308 accuracy and 0.987 precision. It needs the journey to
be finished, and once a presentation ends `finalResult` is already in the data — it predicts
something you know. Its apparent skill is largely the model noticing when activity stopped.

**FastRP**, worth +0.4 accuracy points over one logged aggregate. The pipeline complexity buys
nothing on this graph.

**Volume alone, early.** It works retrospectively (0.8658 accuracy, 0.897 precision) but collapses
in the window that matters: precision 0.464 to 0.568 across days 30 to 90, against 0.745 to 0.923
for the embedding. The interpretable single feature is not a viable fallback for early warning.

### Before any of this ships

**Measure a clean out-of-sample split.** The precision and recall above include training data.

**Validate on a second module.** Everything here is GGG.

**Build the zero-activity rule first.** Students who never touch a material cannot be projected,
embedded or classified, and in module BBB **88.1% of that group withdrew** against 19.0% of
engaged students. "No activity by day 14" flags a higher-risk population than any classifier here
and needs no graph analytics. This model belongs *after* that rule, over students who are engaging
but engaging badly.

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
~0.70 accuracy" and treated that as its ceiling. Measuring precision showed a 469-student worklist
at day 90 that is 86% correct — the model is conservative, and accuracy penalises exactly that.
**Cost: a recommendation pitched far below what the model can actually do, nearly discarded as
too weak to use.**

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
