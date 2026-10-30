#!/usr/bin/env python3
"""
Draw the homepage charts (inline SVG) from remote/results/ and put them into
site/index.html between <!-- chart:NAME --> and <!-- /chart:NAME -->.

    python3 -I site/charts.py

Standard library only. Re-run after new results land; the page needs no build step.
"""
import json
import re
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / 'remote' / 'results'
PAGE = ROOT / 'site' / 'index.html'

INK, INK2, MUTED = '#1e2129', '#565e76', '#7a839f'
GRID, TRACK = '#e7e9ee', '#f3f4f6'
SERIES = ['#2a78d6', '#eb6834']  # validated pair (dataviz validator, light surface)
FONT = 'font-family="Inter, system-ui, sans-serif"'


def bar(x, y, w, h, fill, title=''):
    """A horizontal bar: square at the baseline, 4px rounded at the data end."""
    if w <= 0:
        return ''
    r = min(4, w, h / 2)
    d = (f'M{x:.1f},{y:.1f} h{w - r:.1f} a{r},{r} 0 0 1 {r},{r} v{h - 2 * r:.1f} '
         f'a{r},{r} 0 0 1 -{r},{r} h-{w - r:.1f} z')
    t = f'<title>{escape(title)}</title>' if title else ''
    return f'<path d="{d}" fill="{fill}">{t}</path>'


def vram_chart():
    """GPU memory in use per tier recipe (model + whisper), from vram-*.txt."""
    rows = [
        ('e4b', 'Gemma 4 E4B', 'translation and analysis, all tiers'),
        ('26b-ngl12', 'Gemma 4 26B, partly on the GPU', '12 layers on the GPU, the rest in RAM'),
        ('26b', 'Gemma 4 26B', 'budget-tier assistant'),
        ('gptoss', 'gpt-oss-120b', 'recommended-tier assistant'),
    ]
    gb = {}
    for key, *_ in rows:
        text = (RESULTS / f'vram-{key}.txt').read_text()
        gb[key] = max(int(m) for m in re.findall(r'(\d+) MiB, \d+ MiB', text)) / 1000
    left, width, row_h, top, bar_h = 250, 360, 46, 34, 20
    scale = width / 80
    h = top + row_h * len(rows) + 8
    out = [f'<svg class="chart" viewBox="0 0 680 {h}" role="img" aria-labelledby="vram-title" {FONT}>',
           '<title id="vram-title">GPU memory used by each recipe, including Whisper transcription</title>']
    # Reference lines: the GPU sizes the tiers are measured against
    for gbs, label in ((8, '8 GB laptop GPU'), (20, '20 GB card'), (80, '80 GB')):
        x = left + gbs * scale
        out.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{top - 8}" y2="{h - 8}" stroke="#c3c2b7" stroke-width="1"/>')
        # 8 and 20 are close: 8's label sits left of its line, 20's right of its own
        anchor = 'start' if gbs == 20 else 'end'
        dx = 3 if gbs == 20 else -3 if gbs == 8 else -2
        out.append(f'<text x="{x + dx:.1f}" y="{top - 14}" font-size="11" fill="{MUTED}" text-anchor="{anchor}">{label}</text>')
    for i, (key, name, note) in enumerate(rows):
        y = top + i * row_h
        out.append(f'<text x="0" y="{y + 9}" font-size="13" font-weight="600" fill="{INK}">{escape(name)}</text>')
        out.append(f'<text x="0" y="{y + 26}" font-size="11.5" fill="{INK2}">{escape(note)}</text>')
        w = gb[key] * scale
        out.append(bar(left, y, w, bar_h, SERIES[0], f'{name}: {gb[key]:.1f} GB'))
        out.append(f'<text x="{left + w + 6:.1f}" y="{y + 14}" font-size="12.5" fill="{INK}">{gb[key]:.1f} GB</text>')
    out.append(f'<line x1="{left}" x2="{left}" y1="{top - 8}" y2="{h - 8}" stroke="#c3c2b7" stroke-width="1"/>')
    out.append('</svg>')
    return '\n'.join(out)


def agent_chart():
    """Tasks passed per category for both agent models, from the W4 run summaries."""
    runs = [
        ('gpt-oss-120b', 'w4-gpt-oss-120b-20261029-105458.json'),
        ('Gemma 4 26B', 'w4-gemma-4-26b-a4b-20261029-104657.json'),
    ]
    summaries = [json.loads((RESULTS / f).read_text())['summary'] for _, f in runs]
    cats = list(summaries[0]['by_category'])
    def parse(s):
        a, b = s.split('/')
        return int(a), int(b)
    left, unit, bar_h, gap, row_h, top = 150, 52, 10, 2, 36, 40
    h = top + row_h * len(cats) + 4
    out = [f'<svg class="chart" viewBox="0 0 560 {h}" role="img" aria-labelledby="agent-title" {FONT}>',
           '<title id="agent-title">Agent tasks passed per category, out of the tasks in each</title>']
    # Legend: identity never by colour alone
    lx = 0
    for (name, _), s, colour in zip(runs, summaries, SERIES):
        label = f'{name}: {s["passed"]} of {s["tasks"]}'
        out.append(f'<rect x="{lx}" y="4" width="12" height="12" rx="3" fill="{colour}"/>')
        out.append(f'<text x="{lx + 18}" y="14.5" font-size="13" fill="{INK}">{escape(label)}</text>')
        lx += 18 + len(label) * 7.4 + 22
    for i, cat in enumerate(cats):
        y = top + i * row_h
        n = parse(summaries[0]['by_category'][cat])[1]
        out.append(f'<text x="0" y="{y + 15}" font-size="13" fill="{INK}">{escape(cat.capitalize())} '
                   f'<tspan fill="{MUTED}">({n})</tspan></text>')
        # The track is the category's task count: a full bar is every task passed
        out.append(f'<rect x="{left}" y="{y}" width="{n * unit}" height="{2 * bar_h + gap}" rx="4" fill="{TRACK}"/>')
        for j, ((name, _), s, colour) in enumerate(zip(runs, summaries, SERIES)):
            p, total = parse(s['by_category'][cat])
            out.append(bar(left, y + j * (bar_h + gap), p * unit, bar_h, colour, f'{name}, {cat}: {p} of {total}'))
            if p == 0:
                out.append(f'<text x="{left + 4}" y="{y + j * (bar_h + gap) + 9}" font-size="10.5" fill="{INK2}">none</text>')
    out.append('</svg>')
    return '\n'.join(out)


def main():
    page = PAGE.read_text()
    for name, svg in (('vram', vram_chart()), ('agent', agent_chart())):
        pattern = re.compile(rf'(<!-- chart:{name} -->).*?(<!-- /chart:{name} -->)', re.S)
        if not pattern.search(page):
            raise SystemExit(f'no chart:{name} markers in {PAGE}')
        page = pattern.sub(lambda m: f'{m.group(1)}\n{svg}\n{m.group(2)}', page)
    PAGE.write_text(page)
    print(f'wrote charts into {PAGE}')


if __name__ == '__main__':
    main()
