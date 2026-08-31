"""Phase 1: is assessment non-submission additive to the day-7 zero-activity rule?

Non-submission separates outcomes sharply -- 91.4% of GGG students who submitted
nothing due by day 90 failed or withdrew, 99.9% in BBB. But BBB's first assessment
falls on day 12, five days after the zero-activity rule fires, so much of that may be
students the rule already caught for free.

This measures the marginal cell: students the day-7 rule did NOT flag, who then
submitted nothing. Everything runs offline from Data/, no database, no session.

Handled here because each one would quietly corrupt the feature:
  - is_banked = 1 is a score carried from a previous sitting, not a submission
  - 11 of 206 assessments are exams with no due date
  - late submission is normal (28.4%), so "by day D" is what an observer knows
  - due dates are per presentation, not per module
"""

from pathlib import Path

import pandas as pd

DATA = Path(__file__).resolve().parent.parent / 'Data'
KEY = ['code_module', 'code_presentation', 'id_student']
PRES = ['code_module', 'code_presentation']
AT_RISK = ['Withdrawn', 'Fail']
RULE_DAY = 7
MODEL_DAY = 90

# Judge the trigger a fortnight after the deadline, not on it. Late submission is
# normal (28.4% overall), and three presentations -- CCC 2014B, CCC 2014J and
# DDD 2013B -- record ZERO submissions on or before the due date, median +2 to +3
# days, so the recorded date is not the operative deadline there. Evaluated on the
# day, the trigger flags 100% of those cohorts. At +14 days, 97-100% of genuine
# submitters have arrived in every presentation.
GRACE = 14

# Go/no-go, fixed before looking: the cell the rule misses must be worth building for.
GO_MIN_SHARE = 0.05
GO_MIN_RATE = 0.75
GO_MIN_MODULES = 4

reg = pd.read_csv(DATA / 'studentRegistration.csv')
info = pd.read_csv(DATA / 'studentInfo.csv', usecols=KEY + ['final_result'])
vle = pd.read_csv(DATA / 'studentVle.csv', usecols=KEY + ['date'])
assess = pd.read_csv(DATA / 'assessments.csv')
subs = pd.read_csv(DATA / 'studentAssessment.csv')

# --- the three exclusions -------------------------------------------------
gradeable = assess[assess.date.notna() & (assess.assessment_type != 'Exam')].copy()
print(f'assessments {len(assess)} -> {len(gradeable)} gradeable '
      f'(dropped {int(assess.date.isna().sum())} undated exams, '
      f'{int((assess.assessment_type == "Exam").sum())} exams total)')
real = subs[subs.is_banked == 0].copy()
print(f'submissions {len(subs):,} -> {len(real):,} real '
      f'(dropped {int((subs.is_banked == 1).sum()):,} banked)')

sub = real.merge(gradeable[['id_assessment'] + PRES + ['date']]
                 .rename(columns={'date': 'dueDate'}), on='id_assessment')

first_due = gradeable.groupby(PRES).date.min().rename('firstDue')
print(f'first assessment falls between day {first_due.min():.0f} '
      f'and day {first_due.max():.0f} across presentations')

first_activity = vle.groupby(KEY).date.min().rename('firstActivity')
base = (reg.merge(info, on=KEY, how='inner')
        .join(first_activity, on=KEY)
        .join(first_due, on=PRES))
base['atRisk'] = base.final_result.isin(AT_RISK)


def enrolled(day):
    """Students still registered at `day` -- both facts observable on the day."""
    return base[base.date_unregistration.isna() | (base.date_unregistration > day)]


def submission_state(day):
    """Per student-presentation: assessments due by `day`, and how many submitted."""
    due = (gradeable[gradeable.date <= day].groupby(PRES).id_assessment
           .nunique().rename('nDue'))
    got = (sub[(sub.dueDate <= day) & (sub.date_submitted <= day)]
           .groupby(KEY).id_assessment.nunique().rename('nSubmitted'))
    return due, got


def frame(day):
    df = enrolled(day).copy()
    due, got = submission_state(day)
    df = df.join(due, on=PRES).join(got, on=KEY)
    df['nDue'] = df.nDue.fillna(0).astype(int)
    df['nSubmitted'] = df.nSubmitted.fillna(0).astype(int)
    df['ruleFlagged'] = (df.firstActivity.isna() | (df.firstActivity > RULE_DAY)) & (
        df.date_unregistration.isna() | (df.date_unregistration > RULE_DAY))
    df['missedAll'] = (df.nDue > 0) & (df.nSubmitted == 0)
    return df


print('\n' + '=' * 100)
print(f'THE FOUR CELLS at day {MODEL_DAY} -- population is students still registered then')
print('=' * 100)
d = frame(MODEL_DAY)
cells = (d.groupby(['ruleFlagged', 'missedAll'])
         .agg(students=('atRisk', 'size'), at_risk_rate=('atRisk', 'mean')))
cells['share_of_cohort'] = cells.students / len(d)
print(f'cohort still registered at day {MODEL_DAY}: {len(d):,}\n')
print(cells.round(4).to_string())

print('\n' + '=' * 100)
print('THE MARGINAL CELL, PER MODULE: rule did NOT flag, but submitted nothing')
print('=' * 100)
rows = []
for module, g in d.groupby('code_module'):
    marginal = g[~g.ruleFlagged & g.missedAll]
    caught_by_rule = g[g.ruleFlagged]
    neither = g[~g.ruleFlagged & ~g.missedAll]
    rows.append({
        'module': module, 'cohort': len(g),
        'rule_only': len(caught_by_rule),
        'rule_rate': caught_by_rule.atRisk.mean() if len(caught_by_rule) else 0.0,
        'marginal_n': len(marginal),
        'marginal_share': len(marginal) / len(g),
        'marginal_rate': marginal.atRisk.mean() if len(marginal) else 0.0,
        'neither_rate': neither.atRisk.mean() if len(neither) else 0.0,
        'base_rate': g.atRisk.mean(),
    })
per = pd.DataFrame(rows).set_index('module')
per['passes'] = ((per.marginal_share >= GO_MIN_SHARE)
                 & (per.marginal_rate >= GO_MIN_RATE))
print(per.round(4).to_string())

n_pass = int(per.passes.sum())
print(f'\nGO CRITERION: marginal cell >= {GO_MIN_SHARE:.0%} of cohort at '
      f'>= {GO_MIN_RATE:.2f} at-risk rate, in >= {GO_MIN_MODULES} of 7 modules')
print(f'RESULT: {n_pass} of 7 modules pass -> '
      f'{"GO" if n_pass >= GO_MIN_MODULES else "NO-GO"}')

print('\n' + '=' * 100)
print(f'THE TRIGGER: missed the first assessment, judged {GRACE} days after it was due')
print('=' * 100)
trig = []
for (module, pres), g0 in base.groupby(PRES):
    day = int(g0.firstDue.iloc[0]) + GRACE
    d2 = frame(day)
    g = d2[(d2.code_module == module) & (d2.code_presentation == pres)]
    if not len(g):
        continue
    flagged = g[g.missedAll]
    newly = g[g.missedAll & ~g.ruleFlagged]
    trig.append({
        'module': module, 'presentation': pres,
        'firstDue': day - GRACE, 'judgedAt': day,
        'cohort': len(g), 'flagged': len(flagged),
        'precision': flagged.atRisk.mean() if len(flagged) else 0.0,
        'recall': (flagged.atRisk.sum() / g.atRisk.sum()) if g.atRisk.sum() else 0.0,
        'base': g.atRisk.mean(),
        'new_vs_rule': len(newly),
        'new_precision': newly.atRisk.mean() if len(newly) else 0.0,
        'lead_days': MODEL_DAY - day,
    })
t = pd.DataFrame(trig).set_index(['module', 'presentation'])
print(t.round(4).to_string())

print('\nby module, weighted across presentations:')
agg = t.groupby('module').apply(lambda g: pd.Series({
    'judgedAt': g.judgedAt.mean(),
    'flagged': g.flagged.sum(),
    'precision': (g.precision * g.flagged).sum() / g.flagged.sum() if g.flagged.sum() else 0,
    'base': (g.base * g.cohort).sum() / g.cohort.sum(),
    'new_vs_rule': g.new_vs_rule.sum(),
    'new_precision': ((g.new_precision * g.new_vs_rule).sum() / g.new_vs_rule.sum()
                      if g.new_vs_rule.sum() else 0),
    'lead_days': g.lead_days.mean(),
}), include_groups=False)
agg['lift'] = agg.precision / agg.base
print(agg.round(4).to_string())
