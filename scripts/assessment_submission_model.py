"""Phase 3: do submission features add to the day-90 model, and does the embedding still earn a place?

Four arms, one harness, same split and seed:

  volume                        logClicks                       the floor
  journey                       journeyEmbedding + logClicks    current recommendation
  submission                    submission features alone       the challenger
  journey+submission            all three                       the ceiling
  volume+submission             no embedding                    THE decisive arm

If volume+submission matches journey+submission, the FastPath embedding contributes
nothing once submission behaviour is present, and the 1.1M-node chain build and billed
analytics session stop being justifiable.

Needs no analytics session: the journey embeddings were streamed to parquet by an earlier
run, and the submission features come straight from the CSVs.

Scored at a ranked budget as well as at argmax. With an imbalanced target, argmax lets a
classifier predict the majority class everywhere and report zero flagged -- reproducible on
this data with FastRP, and it looks like a result rather than an error. precision@K cannot
collapse that way, and "we can contact K students, who?" is the operational question anyway.
"""

import random
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GridSearchCV
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings('ignore')

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'Data'
FEATURES = Path('/tmp/harness')
KEY = ['code_module', 'code_presentation', 'id_student']
PRES = ['code_module', 'code_presentation']
DAY = 90
SEED = 42
HOLDOUT_FRACTION = 0.30

assess = pd.read_csv(DATA / 'assessments.csv')
subs = pd.read_csv(DATA / 'studentAssessment.csv')
reg = pd.read_csv(DATA / 'studentRegistration.csv')

gradeable = assess[assess.date.notna() & (assess.assessment_type != 'Exam')]
real = subs[subs.is_banked == 0]
sub = real.merge(gradeable[['id_assessment'] + PRES + ['date']]
                 .rename(columns={'date': 'dueDate'}), on='id_assessment')


def submission_features(module):
    """Per student, at DAY, aggregated across any presentations of the module."""
    g = gradeable[(gradeable.code_module == module) & (gradeable.date <= DAY)]
    if not len(g):
        return pd.DataFrame(columns=['id_student', 'submissionRate', 'missedAll',
                                     'missedFirst', 'meanLateness'])
    # how many were due to each student, via the presentation they registered for
    due_per_pres = g.groupby('code_presentation').id_assessment.nunique()
    enrolled = reg[reg.code_module == module][['code_presentation', 'id_student']]
    enrolled = enrolled.assign(nDue=enrolled.code_presentation.map(due_per_pres).fillna(0))

    s = sub[(sub.code_module == module) & (sub.dueDate <= DAY)
            & (sub.date_submitted <= DAY)]
    got = s.groupby('id_student').id_assessment.nunique().rename('nSubmitted')
    late = (s.assign(late=s.date_submitted - s.dueDate)
            .groupby('id_student').late.mean().rename('meanLateness'))

    first_due = g.groupby('code_presentation').date.min()
    first_ids = set(g.merge(first_due.rename('firstDue'), on='code_presentation')
                    .query('date == firstDue').id_assessment)
    got_first = set(s[s.id_assessment.isin(first_ids)].id_student)

    out = (enrolled.groupby('id_student').nDue.sum().to_frame()
           .join(got).join(late))
    out['nSubmitted'] = out.nSubmitted.fillna(0)
    out['meanLateness'] = out.meanLateness.fillna(0.0)
    out['submissionRate'] = np.where(out.nDue > 0, out.nSubmitted / out.nDue, 1.0)
    out['missedAll'] = ((out.nDue > 0) & (out.nSubmitted == 0)).astype(int)
    out['missedFirst'] = (~out.index.isin(got_first)).astype(int)
    return out.reset_index()[['id_student', 'submissionRate', 'missedAll',
                              'missedFirst', 'meanLateness']]


def fit_score(X, y, is_hold):
    Xtr, ytr, Xte, yte = X[~is_hold], y[~is_hold], X[is_hold], y[is_hold]
    best, best_cv = None, -1
    for est, grid in [
        (make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000)),
         {'logisticregression__C': [0.01, 0.1, 1.0, 10.0]}),
        (RandomForestClassifier(n_estimators=200, random_state=SEED, n_jobs=-1),
         {'max_depth': [4, 8, 16]}),
    ]:
        s = GridSearchCV(est, grid, scoring='f1_macro', cv=4, n_jobs=-1).fit(Xtr, ytr)
        if s.best_score_ > best_cv:
            best_cv, best = s.best_score_, s.best_estimator_
    pred = best.predict(Xte)
    ar = int((yte == 0).sum())
    fl = int((pred == 0).sum())
    ca = int(((yte == 0) & (pred == 0)).sum())
    risk = best.predict_proba(Xte)[:, list(best.classes_).index(0)]
    order = np.argsort(-risk)
    out = {'n': len(yte), 'at_risk': ar, 'flagged': fl, 'caught': ca,
           'precision': ca / fl if fl else 0.0,
           'recall': ca / ar if ar else 0.0}
    for k in (100, 200):
        k = min(k, len(yte))
        out[f'p@{k}'] = int((yte[order[:k]] == 0).sum()) / k
    return out


SUB_COLS = ['submissionRate', 'missedAll', 'missedFirst', 'meanLateness']
rows = []
for path in sorted(FEATURES.glob('*_d90.parquet')):
    module = path.stem.split('_')[0]
    tbl = pq.read_table(path)
    df = pd.DataFrame({c: tbl[c].to_pylist() for c in tbl.column_names})

    width = df.journeyEmbedding.map(lambda v: len(v) if hasattr(v, '__len__') else 0)
    dropped = int((width != width.max()).sum())
    df = df[width == width.max()]

    df = (df.merge(submission_features(module), left_on='id', right_on='id_student',
                   how='inner')
          .sort_values('id').reset_index(drop=True))

    y = df.passed.to_numpy().astype(int)
    ids = df.id.tolist()
    shuffled = sorted(ids)
    random.Random(SEED).shuffle(shuffled)
    holdout = set(shuffled[:int(len(shuffled) * HOLDOUT_FRACTION)])
    is_hold = np.array([i in holdout for i in df.id])

    emb = np.vstack(df.journeyEmbedding.apply(np.asarray).to_numpy())
    vol = df[['logClicks']].to_numpy()
    smx = df[SUB_COLS].to_numpy(dtype=float)

    arms = {
        'volume': vol,
        'journey': np.hstack([emb, vol]),
        'submission': smx,
        'volume+submission': np.hstack([vol, smx]),
        'journey+submission': np.hstack([emb, vol, smx]),
    }
    print(f'\n=== {module} day {DAY} | {len(df):,} students '
          f'({dropped} dropped, no embedding in window), '
          f'{int(is_hold.sum()):,} holdout ===', flush=True)
    for name, X in arms.items():
        r = fit_score(X, y, is_hold)
        rows.append({'module': module, 'features': name, **r})
        print(f'  {name:20s} flagged {r["flagged"]:5,}/{r["at_risk"]:,} | '
              f'precision {r["precision"]:.3f} recall {r["recall"]:.3f} | '
              f'p@100 {r["p@100"]:.3f} p@200 {r["p@200"]:.3f}', flush=True)

f = pd.DataFrame(rows).set_index(['module', 'features'])
print('\n' + '=' * 92)
print('PHASE 3 -- does the embedding still earn a place once submission is present?')
print('=' * 92)
print(f[['n', 'at_risk', 'flagged', 'caught', 'precision', 'recall',
         'p@100', 'p@200']].round(4).to_string())

print('\nthe decisive comparison: what the embedding adds on top of volume+submission')
for module in f.index.get_level_values(0).unique():
    a = f.loc[(module, 'volume+submission')]
    b = f.loc[(module, 'journey+submission')]
    print(f'  {module}: precision {a.precision:.4f} -> {b.precision:.4f} '
          f'({b.precision - a.precision:+.4f}) | '
          f'p@100 {a["p@100"]:.4f} -> {b["p@100"]:.4f} '
          f'({b["p@100"] - a["p@100"]:+.4f}) | '
          f'p@200 {a["p@200"]:.4f} -> {b["p@200"]:.4f} '
          f'({b["p@200"] - a["p@200"]:+.4f})')

print('\nand what submission adds to the current recommendation')
for module in f.index.get_level_values(0).unique():
    a = f.loc[(module, 'journey')]
    b = f.loc[(module, 'journey+submission')]
    print(f'  {module}: precision {a.precision:.4f} -> {b.precision:.4f} '
          f'({b.precision - a.precision:+.4f}) | '
          f'p@100 {a["p@100"]:.4f} -> {b["p@100"]:.4f} '
          f'({b["p@100"] - a["p@100"]:+.4f})')
