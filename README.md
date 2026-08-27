# OULAD as a Neo4j graph

Loads the [Open University Learning Analytics Dataset](https://analyse.kmi.open.ac.uk/open-dataset)
into Neo4j as a property graph, then runs graph analytics over it with
[Aura Graph Analytics](https://neo4j.com/docs/aura/graph-analytics/) — engagement cohorts,
node embeddings, and outcome prediction.

The full graph is **66,920 nodes and 8,818,076 relationships**, loaded in about seven minutes.

---

## The graph

```
                    ┌──────────────┐
     WAS_REGISTERED │              │ IN_AGE_GROUP          → (:AgeGroup)
   ┌────────────────┤  (:Student)  ├─ LIVE_IN_REGION       → (:Region)
   │                │              │─ HAS_HIGHER_EDUCATION → (:Education)
   │                └──────┬───────┘─ IN_DEPRIVATION_GROUP → (:MultipleDeprivationIndex)
   │                       │
   ▼                       │ WAS_ASSESSED_IN {score, dateSubmitted}
(:StudentRegistration)     │ REVIEWED_MATERIAL {date, sumClick, count}
   │                       │
   │ CONTAINS_COURSE       ├──────────────────────► (:EducationalMaterial)
   │ {finalResult, …}      └──────────────────────► (:Assessment)
   ▼
(:Course) ─ HAS_MATERIAL   ─► (:EducationalMaterial)
          └ HAS_ASSESSMENT ─► (:Assessment)
```

Nine node labels, ten relationship types. `Student` also carries a secondary `DisabledStudent`
label where applicable. Outcomes live on `CONTAINS_COURSE` as `finalResult`, not on the student.

**All of it is defined in [`config.yaml`](config.yaml)** — labels, relationship types, Cypher,
source columns, join keys. The Python is a generic driver over that config, so adding a label or
a relationship is normally a config-only change.

---

## Quick start

### 1. Load the graph

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/jose-alvarado-guzman/oulad/blob/main/notebooks/oulad_data_load.ipynb)
&nbsp;`notebooks/oulad_data_load.ipynb`

Or locally, against a `.env` you fill in from [`src/.env.example`](src/.env.example):

```bash
pip install -r requirements.txt
cd src && python -m oulad
```

It downloads the 44.6 MiB archive, reshapes seven CSVs with pandas, and loads them. Re-running
is safe: node loads `MERGE` and relationship loads are guarded, so a second pass creates nothing.

### 2. Analyse it

| notebook | what it does | |
| --- | --- | --- |
| `aga_student_cohorts.ipynb` | node similarity → Louvain engagement cohorts → outcome cross-tab | [![Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/jose-alvarado-guzman/oulad/blob/main/notebooks/aga_student_cohorts.ipynb) |
| `aga_outcome_prediction.ipynb` | FastRP embedding → node classification pipeline | [![Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/jose-alvarado-guzman/oulad/blob/main/notebooks/aga_outcome_prediction.ipynb) |
| `aga_fastpath_journeys.ipynb` | event chain → FastPath sequence embedding → classification, with a cutoff sweep | [![Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/jose-alvarado-guzman/oulad/blob/main/notebooks/aga_fastpath_journeys.ipynb) |

Each opens its own analytics session and deletes it afterwards. Only the FastPath notebook writes
to the database, and it removes what it wrote.

---

## What the analysis found

Predicting whether a student passes, from engagement and demographics only — no assessment
scores, since those determine the outcome by definition.

| approach | accuracy | verdict |
| --- | --- | --- |
| always guess the majority class | 0.6393 | the floor |
| `sum(sumClick) >= median`, no model | 0.7681 | one line of Cypher |
| **one logged click total**, random forest | **0.8658** | the bar that matters |
| FastRP topology embedding + volume | 0.8588 | embedding worth **+0.4 pts** |
| FastPath sequence embedding, whole journey | 0.9280 | mostly **hindsight** |
| FastPath sequence embedding, **cut at day 60** | 0.6892 | **+8.6 pts over volume** |

Two conclusions, and neither survives alone:

- **The 0.93 is not an early-warning system.** With the whole journey, the embedding is reading
  *when activity stopped*, which for a withdrawal is the label restated. Truncated to the first
  30 days it scores 0.6348 — below the majority floor.
- **But at day 60 the sequence beats volume by 8.6 points**, and volume alone is *worse than
  guessing*. In the window where an intervention is still possible, journey shape carries signal
  no aggregate does. That is the one place a graph embedding earns its cost here.

**[`docs/model-selection.md`](docs/model-selection.md)** has the full record: every method, every
number, and the conclusions that had to be retracted along the way.

---

## Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
python -m pytest                      # 72 tests, offline, under a second
```

The suite needs no database and no network. Tests that use the real CSVs skip themselves when
`Data/` is absent, since it is gitignored.

### Credentials

Two groups, both defined in [`src/oulad/credentials.py`](src/oulad/credentials.py) and resolved
from — in order — the process environment, the Google Colab secret store, then a `.env` file.

| group | keys | needed by |
| --- | --- | --- |
| `ETL_SECRETS` | `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD` | loading the graph |
| `AGA_SECRETS` | `AURA_CLIENT_ID`, `AURA_CLIENT_SECRET`, `AURA_PROJECT_ID` | opening an analytics session |

`NEO4J_DATABASE` and `AURA_INSTANCEID` are optional; the instance id is derived from the
connection URI when absent. Copy [`src/.env.example`](src/.env.example) to `src/.env` and fill it
in — that file is gitignored, as is anything matching `.env.*`.

The `AURA_*` credentials come from the Aura console under your project's API credentials, and are
separate from the database login. The client secret is shown **once**, at creation.

---

## Layout

```
config.yaml                  the graph model: labels, relationships, Cypher
src/oulad/                   the loading pipeline
  __main__.py                orchestrator
  datasource.py              download and read the CSVs
  nodes.py, relationships.py reshape and load, with post-load QA
  credentials.py             Colab secrets, .env, and the two credential groups
notebooks/                   one loader, three analytics notebooks
docs/model-selection.md      what was tried, what it scored, what was wrong
tests/                       72 offline tests
requirements.txt             ETL dependencies
requirements-aga.txt         analytics dependencies (deliberately not a superset)
```

`Data/`, `Logs/` and `Result/` are gitignored; the loader creates them.

---

## Notes

**Dependencies are pinned with upper bounds** at the next major version — `pyneoinstance` 4 and
`neo4j` 6 both carried breaking changes, and `graphdatascience` is pinned exactly because its
session API is still in alpha and moves between releases.

**`traitlets>=5.10` is pinned although nothing here imports it.** `pyneoinstance` pulls in
`neo4j-viz`, which evaluates `traitlets.Instance[...]` at import time; Colab ships 5.7.1, where
that raises. Without the floor, `import pyneoinstance` fails in Colab.

**The dataset URL moved.** The address in the original OULAD paper now redirects to a homepage
and serves HTML. The live archive is linked from the
[OU Analyse dataset page](https://research.stem.open.ac.uk/ouanalyse/dataset/).

---

## Licence

[GPL-3.0-or-later](LICENSE). The OULAD dataset is published by The Open University under
CC BY 4.0.
