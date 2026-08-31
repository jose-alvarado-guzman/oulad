# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A one-shot ETL pipeline that downloads the OULAD (Open University Learning Analytics Dataset) zip, reshapes the seven CSVs with pandas, and loads them into Neo4j as a property graph. All graph structure — node labels, relationship types, Cypher, source columns, join keys — lives in `config.yaml`, not in Python. The Python modules are a generic driver over that config.

## Commands

Tests (no linter):

```bash
pip install -e '.[dev]' && python -m pytest      # or just: python -m pytest
python -m pytest tests/test_relationships.py -k first_by    # one module / one test
```

The whole suite is offline — no Neo4j, no network — and runs in under a second. `pythonpath = ["src"]` in `pyproject.toml` means it works without installing the package. Tests needing the real CSVs skip themselves when `Data/` is absent, since it's gitignored. Neo4j is faked by a class exposing just `get_node_label_freq` / `get_rela_type_freq`; the Colab secrets store is stubbed via `sys.modules` in the `colab` fixture.

The pipeline runs as a module from `src/`, which must be the working directory or on `PYTHONPATH` unless the package is installed:

```bash
cd src && python -m oulad          # no install needed
pip install -e . && oulad-load     # or via the console script
```

Use `pip install -e .`, not `pip install .`: the pipeline finds `config.yaml`, `Data/`, `Logs/`, and `Result/` relative to the package directory, which only resolves to the repo root while the install points back at this checkout.

Virtualenv in use: `~/.virtualenvs/OULAD` (Python 3.13). Dependencies are pinned in `requirements.txt` and `pyproject.toml` with upper bounds at the next major version — pyneoinstance 4 and neo4j 6 both carried breaking changes.

**`traitlets>=5.10` is pinned even though nothing here imports it.** `pyneoinstance` pulls in `neo4j-viz`, whose `widget.py` evaluates `traitlets.Instance[...]` while defining a class, so it runs on import; `Instance` only became subscriptable in traitlets 5.10. `neo4j-viz` asks for `traitlets>=5,<6`, which an environment already pinned to 5.7 satisfies, so pip leaves it alone and `import pyneoinstance` dies with `type 'Instance' is not subscriptable`. Colab pins exactly 5.7.1, so this bites there and not locally. `tests/test_environment.py` fails by name rather than letting the third-party import error surface. Note also that `neo4j-rust-ext` is a *hard* requirement of pyneoinstance, not an optional speedup — it arrives whether or not it's named.

Three notebooks live in `notebooks/`. `oulad_data_load.ipynb` runs the ETL; `aga_student_cohorts.ipynb` opens an Aura Graph Analytics session over the loaded graph (node similarity → Louvain cohorts → outcome cross-tab → degree centrality → write-back), with `graphdatascience` pinned exactly because its session API is still in alpha. A session is billed compute separate from AuraDB, so it carries a 2-hour TTL and a delete step.

Two AGA traps, both of which return plausible zeros rather than failing, and both now
guarded in the notebook. **A `node_labels` filter induces a subgraph**: passing
`node_labels=['EducationalMaterial']` to an algorithm over `REVIEWED_MATERIAL` discards every
relationship, because each one's source is a `Student`, so degree centrality scored every
material 0. Score the whole graph and filter the results instead. **A missing relationship
weight is not an error either** — it is treated as zero. Step 6 therefore prints
`G.relationship_properties()` and aborts if the weight is absent, and step 11 cross-checks the
session's weighted degree against `sum(r.sumClick)` from the database; they must agree to the
click. That cross-check is what caught the `node_labels` bug after two wrong diagnoses (a
dropped property, then a missing inverse index — both disproved by probing a live session).

`aga_outcome_prediction.ipynb` embeds students with **FastRP** over their engagement and
demographic neighbourhood and trains a GDS **node classification pipeline** to predict whether
they pass. It writes nothing to the database — the class label is computed inside the
projection query, so it exists only in the session. `WAS_ASSESSED_IN` is deliberately excluded:
scores determine `finalResult`, so training on them is leakage.

**It trains two variants on purpose**, embedding+volume and volume-only, because the ablation
is the whole point. Measured on GGG: embedding alone collapses to a constant classifier (F1
macro 0.372, accuracy 0.592, against a 0.598 majority rate) because **FastRP normalises away
degree, and degree is the signal**; volume alone scores 0.843/0.855; both together 0.847/0.859.
The embedding is worth **+0.4 accuracy points**, i.e. nothing. Keep the ablation in — without
it the notebook reads as though 128 dimensions bought the +5.7 points over the median-threshold
baseline, when a random forest on one logged feature did.

`aga_fastpath_journeys.ipynb` builds an event chain in AuraDB
(`(:Student)-[:FIRST_INTERACTION]->(:Interaction)-[:NEXT_INTERACTION]->…`, one node per
student/material/day, ~281k for the default module) so **FastPath** can embed each student's
*sequence*, then scores that embedding as a classifier feature. Its parameters were renamed
between alphas (`dimension` → `embedding_dimension`, `max_elapsed_time` → `lookback_horizon`,
`num_elapsed_times` → `num_time_anchors`, `time_node_property` → `event_node_time_property`,
`output_time` → `observation_time`, `decay_factor` → `decay_rate`), so 2.0a1 examples do not run.
Numeric event features go in via `event_node_feature_vector_property` as a **list**, even for one
number — omitting it means click intensity never reaches the algorithm.

**Quote the cutoff sweep, never a single number.** Step 14 sweeps cutoffs by projecting *day
prefixes* of one chain — a prefix by day of a day-ordered chain is the same graph a truncated
build produces, verified by reproducing both the day-30 and full-journey runs exactly. Module GGG
accuracy, journey embedding: **0.6348 at day 30, 0.6892 at day 60, 0.7127 at day 90, 0.9280 on
the whole journey**, against a ~0.64 majority floor throughout.

Two conclusions follow, and neither survives on its own. The untruncated 0.93 is mostly
hindsight — the embedding reads *when activity stopped*, which for a withdrawal is the label — so
it is a strong retrospective classifier and a poor early-warning one. But from day 60 the
embedding beats click volume by **+8.6 accuracy points** (0.6892 against 0.6029, where volume is
*below* the floor), so in the window where an intervention is still possible the sequence carries
signal no aggregate does. That is the one place in this repository where a graph embedding earns
its cost.

When changing `CUTOFF_DAY`, the cutoff must reach **every** feature. It gates the chain build,
`LABEL_QUERY`'s `logClicks`, and `BASELINE_QUERY`; missing any one pits a truncated feature
against a hindsight one. Judging the embedding by Louvain modularity was the original mistake
here (0.5470 and 0.5122 across two runs, both read as failure) — modularity scores partition
quality, not predictive value.

Cypher gotcha hit twice while writing that chain builder: **a node or list element pulled out
of a map or list cannot be used directly inside a `CREATE` pattern**. `CREATE
(ev)-[:OF_MATERIAL]->(event.material)` and `CREATE (s)-[:FIRST]->(chain[0])` are both syntax
errors; bind them with a `WITH` first. `EXPLAIN` catches this without writing anything, which
is the cheap way to check a mutating query.

`requirements-aga.txt` deliberately does **not** include `-r requirements.txt`. The AGA notebooks use the `neo4j` driver and `graphdatascience` directly and touch this repo only to import `oulad.credentials`, which needs nothing but `python-dotenv`. Adding the ETL stack would install pyneoinstance, neo4j-viz, pyvis, traitlets, wget and PyYAML for nothing — and neo4j-viz is what forces the `traitlets>=5.10` floor, so the AGA notebooks avoid that trap entirely and need no session restart after installing. They still clone the repo, but only so the secret names, resolution order and instance-id derivation live in one place.

In Colab, open `notebooks/oulad_data_load.ipynb` — it clones the repo, installs, resolves credentials from the Secrets panel, runs the ETL, and checks the graph. It deliberately does not run the test suite; that stays a local concern. One thing it does deliberately: it calls `main()` **in the kernel** rather than `!python -m oulad`, because Colab's secret store is only reachable from the kernel process. A subprocess can import `google.colab`, but its `userdata.get` has no channel back to the notebook, so resolution would fall through to a `.env` that a fresh clone doesn't have. Keep that in mind before "tidying" it into a shell call.

Two staleness traps the notebook now guards against, both of which present as the *old* code running with no error. Step 1 does `fetch` + `reset --hard origin/main` rather than `pull --ff-only`, because a `--depth 1` clone cannot always fast-forward and would leave the checkout behind. Step 3 deletes `oulad*` from `sys.modules` before importing, because a git pull cannot change what Python has already imported — a renamed constant would otherwise keep its old value for the whole session. Step 3 also prints `ETL_SECRETS` and `AGA_SECRETS` so a stale session is visible at a glance.

`docs/model-selection.md` is the write-up of the whole model-selection process: every method
tried, the numbers each produced, the conclusions that turned out to be wrong and what they cost.
Read it before adding another model — several apparently good results in this repository are
beaten by one logged aggregate, and the document says which.

Credentials come in **two required groups**, both defined in `credentials.py`:

| Group | Keys | Needed by |
| --- | --- | --- |
| `ETL_SECRETS` | `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD` | the loading pipeline |
| `AGA_SECRETS` | `AURA_CLIENT_SECRET`, `AURA_CLIENT_ID`, `AURA_PROJECT_ID` | Aura Graph Analytics, run against the loaded graph afterwards |

`NEO4J_DATABASE` (`OPTIONAL_SECRETS`) belongs to neither. `main` resolves it once and passes it to every write and QA call, so a load and the counts that verify it can't target different databases; unset means the driver's default. A group is enforced only by the code that needs it: `load_credentials` validates `ETL_SECRETS` by default, so the ETL runs fine with the AGA keys absent — a successful load is not evidence the AGA half is configured. Analytics code should call `load_credentials(logger, required=AGA_SECRETS)`. Either way every known secret is resolved into `os.environ`, so the group that wasn't enforced is still readable. `load_credentials` resolves them from — in precedence order — the existing process environment, the Google Colab secrets store, then a `.env` file. `src/.env.example` is the tracked template; `src/.env` itself is gitignored (as is anything else matching `.env.*`, with `.env.example` negated). `load_credentials` writes what it finds into `os.environ`, which is why `main` can build the single `Neo4jInstance` from plain `os.getenv`; add new secrets to `credentials.py` rather than threading a config object through.

## Architecture

`src/oulad/__main__.py` is the only orchestrator. Fixed order, and the order matters:

1. `get_logger` then `credentials.load_credentials` — the logger comes first so credential resolution can report its source, and a `MissingCredentialsError` exits 1 with a message naming the missing secrets and where to add them.
2. `Neo4jInstance` + `execute_write_queries(pre-load)` — **deliberately before the data work.** The constraints don't depend on the data, so running them first means a bad password or unreachable host fails in seconds rather than after the dataset has been downloaded and the 8.4M-row frames built. Don't move this back down.
3. `datasource.get_data` — skipped when `Data/` already holds CSVs. Download and extraction both happen in a `TemporaryDirectory` and are only moved into place on success, so an interrupted run can't leave a partial `Data/` that the next run mistakes for complete. `_download` streams via `urllib.request` with a socket timeout (`DOWNLOAD_TIMEOUT`), so a server that accepts the connection and then stalls raises instead of hanging the run forever.

    The dataset URL moved. The original `analyse.kmi.open.ac.uk/open-dataset/download` now redirects to the OU Analyse homepage and returns HTML, so a cold start could not fetch anything — the failure was invisible because an existing `Data/` skips the download. The live archive is `https://schools.stem.open.ac.uk/cdn/files/anonymisedData.zip` (44.6 MiB, 7 CSVs), linked from <https://research.stem.open.ac.uk/ouanalyse/dataset/>. If it breaks again, that dataset page is where to look.
4. `datasource.read_data` — reads the `.csv` files in `Data/` (only those; a stray `.DS_Store` used to break this) into a dict keyed by filename-without-extension (`studentInfo`, `studentVle`, `assessments`, …). **These keys are the contract**: `config.yaml` references dataframes by exactly these names.
5. `nodes.prepare_node_data` → `nodes.load_nodes` — the node-key constraints from step 2 are what the node MERGEs depend on.
6. `relationships.prepare_rela_data` → `load_relationships` — relationship Cypher uses `MATCH` on both endpoints, so every node label must already exist.

`main` builds one `Neo4jInstance` and passes it, plus the resolved database, into both loaders. `Neo4jInstance` exposes no `close`/context manager, so don't add teardown expecting one.

Path resolution: `__main__.py` and the QA writers derive the repo root as `Path(__file__).parent.parent.parent`, so `config.yaml`, `Data/`, `Logs/`, and `Result/` always resolve against the repo root regardless of cwd. Only the module import needs cwd to be `src/`.

`Data/`, `Logs/`, and `Result/` are all gitignored.

### config.yaml is the schema

- `cypher.pre-load` — list of `CREATE CONSTRAINT ... IS NODE KEY` statements, one per label.
- `cypher.load.defaults.nodes` / `.relationships` — `parallel`, `batch-size`, `dropna`, applied to any label or type that doesn't override them. Every one of these was a hardcoded conditional in Python before; keep new per-item behavior here rather than reintroducing `if label == '...'` branches.
- `cypher.load.nodes.<Label>` — `dataframe` (one source), `columns` (subset to select), `cql`. Every query takes `$rows`, `UNWIND`s it, and `MERGE`s.
- `cypher.load.relationships.<TYPE>` — `dataframes` (one or two sources; a null column list means all columns), optional `key` (merge keys when two sources), optional `groupby` (`group-cols` / `value-col` / `functions`, used for `REVIEWED_MATERIAL` click aggregation), optional `first-by` (`group-cols` / `order-cols` — sort then keep one row per group, used by `IN_AGE_GROUP`), `sort-key`, `cql`.

Adding a label or relationship type is normally a config-only change: add the constraint, add the block, name the source dataframe and columns. Only touch Python if the reshape needs a transform the driver doesn't support.

To validate config edits without a database: load `config.yaml`, then check every `dataframe`/`columns` reference against `read_data('Data', logger)` and run `prepare_node_data` / `prepare_rela_data`. That catches renames, typos, and missing columns offline.

### Load semantics worth knowing before editing Cypher

- Node loads `MERGE`; relationship loads mostly `CREATE` guarded by `WHERE NOT EXISTS {...}` — that guard is what makes reruns idempotent. Dropping it produces duplicate relationships on a second run. `REVIEWED_MATERIAL` is the exception and uses `MERGE` on the relationship pattern.
- **Rerunning the whole pipeline is verified safe.** A second full run against the already-loaded graph created nothing: every label and type reported 0 created with `qaFlag` 0, node and relationship totals stayed at 66,920 / 8,818,076, `DisabledStudent` stayed at 2,717 with no double-labelling, and there were no duplicate `CONTAINS_COURSE` pairs or second `IN_AGE_GROUP` edges. `pre-load` returned `{}`, the `IF NOT EXISTS` clauses no-opping. So a rerun is a safe way to top up after a partial load — it is not a way to reload changed properties, since `qaFlag` compares counts only.
- Matching is cheaper than creating here: `REVIEWED_MATERIAL`'s 8.46M rows took 3m58s to `MERGE` against existing relationships versus 6m35s to create them. A rerun costs about 4½ minutes end to end against ~7 for a first load.
- Presentation codes (`code_presentation`, e.g. `2013J`) are decomposed *in Cypher*, not pandas: `left(...,4)` → year, `right(...,1)` → term, `B`→February / `J`→October. `StudentRegistration` node keys and the `CONTAINS_COURSE` / `WAS_REGISTERED` matches all repeat this derivation, so a change to it must be applied consistently across all of them.
- Writes go through `execute_write_query_with_data`, with `parallel`/`batch-size` from config. `REVIEWED_MATERIAL` overrides `parallel: false` (lock contention on the dense student↔material writes); relationships default to `batch-size: 200000`.
- Rows are dropped when *all* selected columns are null, except `IN_DEPRIVATION_GROUP`, which sets `dropna: any` so a student with no `imd_band` gets no relationship.
- `Student` node Cypher applies a second `DisabledStudent` label when `disability = 'Y'` — that label has no constraint in `pre-load`.
- The `imd_band` field is the UK Index of Multiple **Deprivation**. The label, type, and constraint were originally spelled "Depravation"; if you see that spelling anywhere it predates the rename.

### Source data quirks, verified against the CSVs

- `studentInfo` has 32,593 rows for 28,785 distinct students — one row per student *per module*, so any per-student attribute is duplicated across rows.
- `studied_credits` is consistent across all 31,512 student-presentation pairs (1,078 span multiple modules, zero conflicts), so `StudentRegistration`'s `(studentId, year, startMonth)` MERGE key doesn't lose data.
- `gender`, `disability`, `region`, `highest_education`, and `imd_band` are all single-valued per student. `age_band` is not: **72 students report two different bands** (they crossed a boundary between presentations) and student 685015 reports two *within* presentation `2014J`, across modules CCC and DDD — contradictory source data rather than aging.
- `IN_AGE_GROUP` therefore uses `first-by` to keep the band from the student's **earliest presentation**, giving exactly one `AgeGroup` per student (28,785 rows = 28,785 distinct students). Without it those 72 students got two relationships each, since the `WHERE NOT EXISTS` guard only blocks duplicates to the *same* `AgeGroup` node. `order-cols` is `[code_presentation, age_band]`: `code_presentation` sorts chronologically as a plain string (fixed 4-digit year, `B` before `J`), and the `age_band` tiebreak keeps 685015 deterministic (resolves to `0-35`) instead of row-order dependent.
- If you add another per-student dimension relationship, check for this first — the pattern is `si.groupby('id_student')[col].nunique(dropna=False) > 1`.

**Activity-type vocabularies differ by module and must be enumerated globally.** GGG has 7
activity types, BBB 12, EEE 11, out of 20 in the dataset. `activityTypeId` is a *categorical*
input to FastPath, so a per-module enumeration makes `0` mean `forumng` in GGG and `dualpane` in
EEE — the embedding spaces are then unrelated and a model trained on one module scores another
confidently and meaninglessly, with no error anywhere. `aga_fastpath_journeys.ipynb` step 4 and
`aga_score_unseen_module.ipynb` step 4 both enumerate the whole dataset for this reason. Changing
either back to a per-module `WHERE c.codeModule = $module` silently breaks the stored model.

**`sessions.estimate()` under-sizes FastPath — treat it as a floor to raise, not a size to
trust.** For a 113k-node / 220k-relationship chain it returned `m_2GB`, and FastPath aborted
mid-run with *"The job ran out of memory"*. The cascade is worse than the cause: no embedding is
written, so the next cell fails with *"Node properties [journeyEmbedding] do not exist in the
graph"*, which reads as a pipeline bug rather than a memory one. Both FastPath notebooks now
override the estimate with a floor by node count (8/16/32 GB). BBB at day 90 is 603,803 nodes and
needs 16 GB where the estimate said 8.

**Give the Neo4j driver `liveness_check_timeout`.** FastPath and pipeline training leave the driver
idle for tens of minutes, and a stale pooled connection surfaces as *"Unable to retrieve routing
information"* or *"Failed to read from defunct connection"* in whichever cell runs next. On one run
that cell was the cleanup step, which left **597,336 orphan `Interaction` nodes** in the database.
Both notebooks now pass `liveness_check_timeout=30, max_connection_lifetime=600` and route
teardown writes through a `db_execute` helper that rebuilds the driver mid-loop rather than
abandoning a half-finished deletion.

**`ModelDetails` has no `.name`** — the field is `.model_name`. `[m.name for m in
gds.model.list()]` raises `AttributeError` *after* a successful `store()`, which looks like the
store failed when it did not.

**A session model dies with its session; `gds.model.store()` is what persists it.** Step 15 of
`aga_fastpath_journeys.ipynb` trains the recommended day-90 configuration and stores it as
`oulad-atrisk-d90`; `aga_score_unseen_module.ipynb` loads it with `gds.model.load()`. Dropping the
in-session copy during cleanup does not remove the stored one — use `gds.model.delete()` for that.
Before storing, the notebook checks the model flags a non-zero number of students, because the GDS
pipeline can return a majority-class classifier and report it as a successful train.

### A trap that applies to every query in this repository

**pandas NaN arrives in Neo4j as a float NaN, not as null.** `dateUnregistration` on
`CONTAINS_COURSE` is the worst case: **22,521 of 32,593 values are NaN and none are null**. Both
of these are therefore false for a missing value:

- `r.dateUnregistration IS NULL`
- `r.dateUnregistration > 14` — every comparison with NaN is false, including `<=`, `>=` and `=`

So an `IS NULL OR > $day` test silently excludes 69% of the data and returns a plausible answer.
Writing the zero-activity rule that way returned **49** flagged students for GGG at day 14 instead
of **391**. Guard with `isNaN(...)` alongside the null check. `dateRegistration` carries 45 NaN
values with the same hazard, and any numeric column that was nullable in the CSV will behave the
same way. `docs/early-warning-rule.md` has the worked case.

### QA output

`load_nodes_qa` / `load_relas_qa` run automatically after each load phase. They compare the driver's reported creation counts against `get_node_label_freq` / `get_rela_type_freq` from the live database and write a timestamped CSV to `Result/`. `qaFlag` is `toLoad - postCount`; nonzero means the graph doesn't hold what the dataframes contained (expected for labels/types that dedupe, e.g. distinct-value dimension nodes). A label or type absent from the frequency table is counted as 0 rather than left as `NaN`, so a total load failure shows up as the full row count instead of a blank cell. Note it compares *counts only* — it cannot detect a MERGE that silently overwrote a property.

On a first load against an empty database `priorNodeCount` is 0 everywhere and `nodesCreated` carries the totals; on a rerun the two swap, which is the quickest way to tell from a QA csv which kind of run produced it.

`get_logger` configures once and sets `propagate = False`, so re-entering `main` from a notebook cell doesn't emit every record two or three times. Idempotence keys on a private `_oulad_configured` marker rather than on whether the logger has handlers — with `propagate = False`, pytest attaches its own capture handler directly to this logger, and a presence check would mistake that for our own work and skip configuration entirely. Logs go to both stdout and `Logs/import.log` (appended, never rotated).
