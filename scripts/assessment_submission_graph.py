"""Phase 2: port the submission feature to Cypher and reconcile against pandas.

Read-only. Computes nothing new -- it recomputes Phase 1's figures from the graph and
compares them cell by cell against the same figures from the CSVs. A relative gap above
GATE on any quantity fails the phase.

The gate exists because every silent failure in this repository presented as a plausible
number nobody cross-checked: a node_labels filter that induced a subgraph and scored every
material 0, a FastPath weight that was projected but never passed to the algorithm, and an
IS NULL test that missed 69% of the data because pandas writes NaN rather than null. The
same NaN trap is live here -- 11 of 206 Assessment.date values are NaN and none are null.
"""

import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from neo4j import GraphDatabase

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / 'src' / '.env')
DATA = ROOT / 'Data'

KEY = ['code_module', 'code_presentation', 'id_student']
PRES = ['code_module', 'code_presentation']
AT_RISK = ['Withdrawn', 'Fail']
GRACE = 14
GATE = 0.01

# isNaN on cc.dateUnregistration is load-bearing: without it the population falls
# from 6,335 to 1,155 across four sample presentations and precision reads a fake
# 1.0000, because 22,521 of 32,593 values are NaN and none are null.
#
# isNaN on a.date is NOT load-bearing here and measured identically with and
# without -- `a.date <= $day` already excludes NaN, since every comparison with
# NaN is false. It stays as a guard in case the date filter is ever removed.
#
# The banked exclusion is load-bearing: without it 131 fewer students are flagged
# across the same four presentations, because a score carried from a prior sitting
# reads as engagement.
FEATURE = '''
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
WITH nDue, s, cc.finalResult AS finalResult, count(DISTINCT a2) AS nSubmitted
RETURN nDue AS assessmentsDue,
       count(*) AS population,
       sum(CASE WHEN nDue > 0 AND nSubmitted = 0 THEN 1 ELSE 0 END) AS missedAll,
       sum(CASE WHEN nDue > 0 AND nSubmitted = 0 AND finalResult IN $atRisk
                THEN 1 ELSE 0 END) AS missedAllAtRisk
'''

driver = GraphDatabase.driver(os.environ['NEO4J_URI'],
                              auth=(os.environ['NEO4J_USERNAME'],
                                    os.environ['NEO4J_PASSWORD']))
DB = os.getenv('NEO4J_DATABASE') or None

reg = pd.read_csv(DATA / 'studentRegistration.csv')
info = pd.read_csv(DATA / 'studentInfo.csv', usecols=KEY + ['final_result'])
assess = pd.read_csv(DATA / 'assessments.csv')
subs = pd.read_csv(DATA / 'studentAssessment.csv')

gradeable = assess[assess.date.notna() & (assess.assessment_type != 'Exam')]
real = subs[subs.is_banked == 0]
sub = real.merge(gradeable[['id_assessment'] + PRES + ['date']]
                 .rename(columns={'date': 'dueDate'}), on='id_assessment')
base = reg.merge(info, on=KEY, how='inner')
base['atRisk'] = base.final_result.isin(AT_RISK)
first_due = gradeable.groupby(PRES).date.min()


def pandas_cell(module, presentation, day):
    g = base[(base.code_module == module) & (base.code_presentation == presentation)]
    g = g[g.date_unregistration.isna() | (g.date_unregistration > day)]
    due_ids = gradeable[(gradeable.code_module == module)
                        & (gradeable.code_presentation == presentation)
                        & (gradeable.date <= day)].id_assessment
    got = (sub[sub.id_assessment.isin(due_ids) & (sub.date_submitted <= day)]
           .groupby('id_student').id_assessment.nunique())
    n_sub = g.id_student.map(got).fillna(0)
    missed = (len(due_ids) > 0) & (n_sub == 0)
    return {'assessmentsDue': int(len(due_ids)), 'population': int(len(g)),
            'missedAll': int(missed.sum()),
            'missedAllAtRisk': int((missed & g.atRisk).sum())}


rows = []
with driver.session(database=DB) as session:
    for (module, presentation), due_day in first_due.items():
        for label, day in [('trigger', int(due_day) + GRACE), ('day90', 90)]:
            graph = session.run(FEATURE, module=module, presentation=presentation,
                                day=day, atRisk=AT_RISK).data()[0]
            pan = pandas_cell(module, presentation, day)
            for field in ['assessmentsDue', 'population', 'missedAll', 'missedAllAtRisk']:
                gv, pv = graph[field], pan[field]
                rows.append({
                    'module': module, 'presentation': presentation, 'at': label,
                    'day': day, 'field': field, 'graph': gv, 'pandas': pv,
                    'diff': gv - pv,
                    'rel': abs(gv - pv) / pv if pv else (0.0 if gv == 0 else 1.0),
                })
driver.close()

r = pd.DataFrame(rows)
worst = r.sort_values('rel', ascending=False)

print('=' * 96)
print('RECONCILIATION: graph against pandas, every presentation, two evaluation days')
print('=' * 96)
print(f'{len(r):,} comparisons across {r.presentation.nunique()} presentations '
      f'x {r.module.nunique()} modules')
print(f'\nexact matches: {int((r["diff"] == 0).sum()):,} of {len(r):,} '
      f'({(r["diff"] == 0).mean():.1%})')

mismatched = r[r['diff'] != 0]
if len(mismatched):
    print(f'\n{len(mismatched)} mismatched comparisons, worst first:')
    print(mismatched.sort_values('rel', ascending=False)
          .head(20).to_string(index=False))
else:
    print('\nno mismatches at all.')

print('\nlargest relative gap by field:')
print(r.groupby('field').rel.max().round(6).to_string())

fails = r[r.rel > GATE]
print('\n' + '=' * 96)
if len(fails):
    print(f'GATE FAILED: {len(fails)} comparisons exceed {GATE:.0%} relative gap')
    print(fails.sort_values('rel', ascending=False).head(20).to_string(index=False))
    print('=' * 96)
    sys.exit(1)
print(f'GATE PASSED: every comparison within {GATE:.0%} '
      f'(max {r.rel.max():.4%}) -- the Cypher reproduces the offline measurement')
print('=' * 96)
