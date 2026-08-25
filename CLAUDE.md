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

Virtualenv in use: `~/.virtualenvs/OULAD` (Python 3.13). Dependencies are pinned in `requirements.txt` and `pyproject.toml` with upper bounds at the next major version — pyneoinstance 4 and neo4j 6 both carried breaking changes. `neo4j-rust-ext` is an optional drop-in driver speedup (`pip install -e '.[fast]'`).

In Colab, open `notebooks/oulad_data_load.ipynb` — it clones the repo, installs, resolves credentials from the Secrets panel, runs the suite, runs the ETL, and checks the graph. One thing it does deliberately: it calls `main()` **in the kernel** rather than `!python -m oulad`, because Colab's secret store is only reachable from the kernel process. A subprocess can import `google.colab`, but its `userdata.get` has no channel back to the notebook, so resolution would fall through to a `.env` that a fresh clone doesn't have. Keep that in mind before "tidying" it into a shell call.

Credentials come in **two required groups**, both defined in `credentials.py`:

| Group | Keys | Needed by |
| --- | --- | --- |
| `ETL_SECRETS` | `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD` | the loading pipeline |
| `AGA_SECRETS` | `CLIENT_SECRET`, `CLIENT_ID`, `PROJECT_ID` | Aura Graph Analytics, run against the loaded graph afterwards |

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

### QA output

`load_nodes_qa` / `load_relas_qa` run automatically after each load phase. They compare the driver's reported creation counts against `get_node_label_freq` / `get_rela_type_freq` from the live database and write a timestamped CSV to `Result/`. `qaFlag` is `toLoad - postCount`; nonzero means the graph doesn't hold what the dataframes contained (expected for labels/types that dedupe, e.g. distinct-value dimension nodes). A label or type absent from the frequency table is counted as 0 rather than left as `NaN`, so a total load failure shows up as the full row count instead of a blank cell. Note it compares *counts only* — it cannot detect a MERGE that silently overwrote a property.

On a first load against an empty database `priorNodeCount` is 0 everywhere and `nodesCreated` carries the totals; on a rerun the two swap, which is the quickest way to tell from a QA csv which kind of run produced it.

`get_logger` configures once and sets `propagate = False`, so re-entering `main` from a notebook cell doesn't emit every record two or three times. Idempotence keys on a private `_oulad_configured` marker rather than on whether the logger has handlers — with `propagate = False`, pytest attaches its own capture handler directly to this logger, and a presence check would mistake that for our own work and skip configuration entirely. Logs go to both stdout and `Logs/import.log` (appended, never rotated).
