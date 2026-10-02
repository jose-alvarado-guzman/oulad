"""Render the early-warning timeline at the top of the README, in light and dark variants.

The figures are typed in, not computed: each one is quoted from the README's own table, which in
turn cites the docs. Change them here only when the README changes, then re-run:

    python scripts/readme_timeline.py

Writes imgs/early_warning_timeline_light.svg and imgs/early_warning_timeline_dark.svg; the README
picks between them with a <picture> element.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

THEMES = {
    'light': dict(surface='#fcfcfb', ink='#0b0b0b', ink2='#52514e', axis='#b5b4ae',
                  mark='#2a78d6'),
    'dark': dict(surface='#1a1a19', ink='#ffffff', ink2='#c3c2b7', axis='#5a5955',
                 mark='#3987e5'),
}

W, H = 920, 300
AXIS_Y = 150
X0, PX_PER_DAY = 50, 7.2          # day 0 at x=50, day 90 at x=698


def x(day):
    return X0 + day * PX_PER_DAY


def label(lines, lx, ly, anchor, t):
    """First line bold in primary ink, the rest in secondary ink."""
    out = []
    for i, text in enumerate(lines):
        weight = 600 if i == 0 else 400
        size = 15 if i == 0 else 14
        fill = t['ink'] if i < 2 else t['ink2']
        out.append(f'<text x="{lx}" y="{ly + i * 19}" text-anchor="{anchor}" '
                   f'font-size="{size}" font-weight="{weight}" fill="{fill}">{text}</text>')
    return '\n'.join(out)


def svg(t):
    p = []
    p.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
             f'viewBox="0 0 {W} {H}" role="img" '
             f'aria-label="Early-warning timeline: day 7 silence, days 31 to 75 missed '
             f'assessments, day 90 sequence model, then an unseen module">')
    p.append(f'<rect width="{W}" height="{H}" rx="8" fill="{t["surface"]}"/>')
    p.append('<g font-family="-apple-system, BlinkMacSystemFont, \'Segoe UI\', Helvetica, '
             'Arial, sans-serif">')

    # axis: day 0 to day 100, then a break before the unseen-module marker
    p.append(f'<line x1="{x(0)}" y1="{AXIS_Y}" x2="{x(100)}" y2="{AXIS_Y}" '
             f'stroke="{t["axis"]}" stroke-width="2" stroke-linecap="round"/>')
    for day in (0, 30, 60, 90):
        p.append(f'<line x1="{x(day)}" y1="{AXIS_Y - 4}" x2="{x(day)}" y2="{AXIS_Y + 4}" '
                 f'stroke="{t["axis"]}" stroke-width="2"/>')
        p.append(f'<text x="{x(day)}" y="{AXIS_Y + 22}" text-anchor="middle" font-size="12" '
                 f'fill="{t["ink2"]}">day {day}</text>')
    bx = x(100) + 22
    p.append(f'<text x="{bx}" y="{AXIS_Y + 5}" text-anchor="middle" font-size="16" '
             f'fill="{t["ink2"]}">//</text>')

    # days 31-75: the submission trigger fires somewhere in this window, per module
    p.append(f'<rect x="{x(31)}" y="{AXIS_Y - 5}" width="{x(75) - x(31)}" height="10" rx="4" '
             f'fill="{t["mark"]}" stroke="{t["surface"]}" stroke-width="2"/>')

    # point milestones, each ringed in the surface colour so it sits cleanly on the axis
    ux = W - 70
    for mx in (x(7), x(90), ux):
        p.append(f'<circle cx="{mx}" cy="{AXIS_Y}" r="8" fill="{t["mark"]}" '
                 f'stroke="{t["surface"]}" stroke-width="2"/>')

    # leader lines from marks to their labels
    def leader(mx, y2):
        return (f'<line x1="{mx}" y1="{AXIS_Y}" x2="{mx}" y2="{y2}" stroke="{t["axis"]}" '
                f'stroke-width="1"/>')

    p.append(leader(x(7), 84))
    p.append(label(['Day 7 · still silent', '74% fail or withdraw',
                    'against a 47% base rate'], x(7) - 6, 36, 'start', t))

    mid = (x(31) + x(75)) / 2
    p.append(leader(mid, 214))
    p.append(label(['Days 31–75 · no assessment handed in', '74–93% precision',
                    'in all seven modules'], mid, 234, 'middle', t))

    p.append(leader(x(90), 84))
    p.append(label(['Day 90 · sequence model', '83–86% precision',
                    'on held-out students'], x(90) + 6, 36, 'end', t))

    p.append(leader(ux, 214))
    p.append(label(['A module never trained on', '96 of its top 100 correct',
                    'against a 27% base rate'], ux + 50, 234, 'end', t))

    p.append('</g></svg>')
    return '\n'.join(p) + '\n'


out = ROOT / 'imgs'
for name, theme in THEMES.items():
    (out / f'early_warning_timeline_{name}.svg').write_text(svg(theme))
