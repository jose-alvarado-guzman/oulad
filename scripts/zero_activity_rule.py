"""Does a 'no activity by day D' rule predict withdrawal, or just report it?

The claim in README.md and docs/model-selection.md is that 88.1% of BBB students who
never touched a material withdrew. That measures activity over the WHOLE presentation
and counts students who unregistered before the module started -- the 25th percentile
of date_unregistration is day -2. Neither supports an early-warning rule at day D.

This measures the rule as it would actually be operated: among students STILL
REGISTERED at day D, flag those with no material interaction on or before day D.
"""

from pathlib import Path

import pandas as pd

DATA = Path(__file__).resolve().parent.parent / 'Data'
KEY = ['code_module', 'code_presentation', 'id_student']
THRESHOLDS = [7, 14, 21, 28]
WITHDRAWN = ['Withdrawn']
AT_RISK = ['Withdrawn', 'Fail']

reg = pd.read_csv(DATA / 'studentRegistration.csv')
info = pd.read_csv(DATA / 'studentInfo.csv', usecols=KEY + ['final_result'])
vle = pd.read_csv(DATA / 'studentVle.csv', usecols=KEY + ['date'])

print(f'registrations {len(reg):,} | studentInfo {len(info):,} | vle rows {len(vle):,}')

# One pass: the first day each student touched anything in that presentation.
# "touched by day D" is then a comparison, not a re-scan.
first = vle.groupby(KEY, sort=False).date.min().rename('firstActivity')
print(f'students with any activity: {len(first):,}')

base = reg.merge(info, on=KEY, how='inner').join(first, on=KEY)
print(f'joined population: {len(base):,} '
      f'(dropped {len(reg) - len(base):,} registrations with no studentInfo row)')
base['presentation'] = base.code_module + '-' + base.code_presentation


def measure(day, still_registered=True):
    df = base
    if still_registered:
        df = df[df.date_unregistration.isna() | (df.date_unregistration > day)]
    df = df.assign(
        flagged=df.firstActivity.isna() | (df.firstActivity > day),
        withdrew=df.final_result.isin(WITHDRAWN),
        at_risk=df.final_result.isin(AT_RISK),
    )
    return df


def summarise(df, day, label):
    n, f = len(df), int(df.flagged.sum())
    flag, keep = df[df.flagged], df[~df.flagged]
    row = {
        'day': day, 'scope': label, 'pop': n, 'flagged': f,
        'pct_flagged': f / n if n else 0.0,
        'wd_rate_flagged': float(flag.withdrew.mean()) if f else 0.0,
        'wd_rate_rest': float(keep.withdrew.mean()) if len(keep) else 0.0,
        'risk_rate_flagged': float(flag.at_risk.mean()) if f else 0.0,
        'risk_rate_rest': float(keep.at_risk.mean()) if len(keep) else 0.0,
        'wd_recall': float(flag.withdrew.sum() / df.withdrew.sum())
                     if df.withdrew.sum() else 0.0,
    }
    row['wd_lift'] = (row['wd_rate_flagged'] / row['wd_rate_rest']
                      if row['wd_rate_rest'] else float('nan'))
    row['risk_lift'] = (row['risk_rate_flagged'] / row['risk_rate_rest']
                        if row['risk_rate_rest'] else float('nan'))
    return row


print('\n' + '=' * 96)
print('THE RULE AS IT WOULD BE OPERATED  (only students still registered at day D)')
print('=' * 96)
operated = pd.DataFrame([summarise(measure(d), d, 'still-registered') for d in THRESHOLDS])
print(operated.set_index('day')[
    ['pop', 'flagged', 'pct_flagged', 'wd_rate_flagged', 'wd_rate_rest', 'wd_lift',
     'wd_recall']].round(4).to_string())

print('\nsame rule, at-risk = Withdrawn OR Fail (the model\'s target)')
print(operated.set_index('day')[
    ['risk_rate_flagged', 'risk_rate_rest', 'risk_lift']].round(4).to_string())

print('\n' + '=' * 96)
print('HOW MUCH OF THE HEADLINE NUMBER WAS THE PRE-START ARTEFACT')
print('=' * 96)
naive = pd.DataFrame([summarise(measure(d, still_registered=False), d, 'all-registered')
                      for d in THRESHOLDS])
cmp = pd.DataFrame({
    'withdrawal rate among flagged, all registered': naive.set_index('day').wd_rate_flagged,
    'withdrawal rate among flagged, still registered': operated.set_index('day').wd_rate_flagged,
})
cmp['overstatement'] = cmp.iloc[:, 0] - cmp.iloc[:, 1]
print(cmp.round(4).to_string())

print('\n-- the committed claim, checked --')
bbb = base[base.code_module == 'BBB']
never = bbb[bbb.firstActivity.isna()]
print(f'BBB registrations: {len(bbb):,}; never touched a material ever: {len(never):,}')
print(f'  withdrawal rate among them: {never.final_result.isin(WITHDRAWN).mean():.4f}')
print(f'  of those, unregistered before day 0: '
      f'{(never.date_unregistration < 0).sum():,} '
      f'({(never.date_unregistration < 0).mean():.1%})')
engaged = bbb[bbb.firstActivity.notna()]
print(f'  withdrawal rate among engaged BBB students: '
      f'{engaged.final_result.isin(WITHDRAWN).mean():.4f}')

print('\n' + '=' * 96)
print('PER MODULE, day 14 (pooled figures hide a 12-point spread on the model)')
print('=' * 96)
d14 = measure(14)
per = d14.groupby('code_module').apply(
    lambda g: pd.Series({
        'pop': len(g), 'flagged': int(g.flagged.sum()),
        'pct_flagged': g.flagged.mean(),
        'wd_flagged': g[g.flagged].withdrew.mean() if g.flagged.any() else 0.0,
        'wd_rest': g[~g.flagged].withdrew.mean(),
        'wd_recall': (g[g.flagged].withdrew.sum() / g.withdrew.sum()
                      if g.withdrew.sum() else 0.0),
    }), include_groups=False)
per['lift'] = per.wd_flagged / per.wd_rest
print(per.round(4).to_string())

print('\n' + '=' * 96)
print('LEAD TIME: does the flag arrive before the withdrawal?')
print('=' * 96)
for day in THRESHOLDS:
    df = measure(day)
    gone = df[df.flagged & df.withdrew & df.date_unregistration.notna()]
    lead = gone.date_unregistration - day
    print(f'  day {day:2d}: {len(gone):,} flagged students later unregistered | '
          f'median lead {lead.median():.0f} days, '
          f'{(lead <= 7).mean():.1%} within a week, '
          f'{(lead > 30).mean():.1%} more than a month later')
