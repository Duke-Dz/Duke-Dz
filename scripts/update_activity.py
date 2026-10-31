"""Render a weekly line graph from the public GitHub contribution calendar without a third-party stats API."""
import argparse
from datetime import date, datetime, timezone, timedelta
import math
from html import escape
from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.request import Request, urlopen


class CalendarParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.days = {}
        self.tips = {}
        self.tip_id = None
        self.in_heading = False
        self.heading = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'td' and 'data-date' in attrs:
            self.days[attrs['id']] = (date.fromisoformat(attrs['data-date']), int(attrs['data-level']))
        elif tag == 'tool-tip':
            self.tip_id = attrs.get('for')
            self.tips[self.tip_id] = []
        elif tag == 'h2':
            self.in_heading = True

    def handle_endtag(self, tag):
        if tag == 'tool-tip':
            self.tip_id = None
        elif tag == 'h2':
            self.in_heading = False

    def handle_data(self, data):
        if self.tip_id is not None:
            self.tips[self.tip_id].append(data)
        if self.in_heading:
            self.heading.append(data)

    def calendar(self):
        heading = ' '.join(self.heading)
        match = re.search(r'([\d,]+)\s+contributions?\s+in the last year', heading)
        if not match or not 350 <= len(self.days) <= 380:
            raise ValueError('GitHub calendar format changed; retaining the previous graph.')
        total = int(match[1].replace(',', ''))
        days = []
        for key, (day, level) in self.days.items():
            tip = ''.join(self.tips.get(key, [])).strip()
            count_match = re.match(r'(No|[\d,]+) contributions?\b', tip)
            if not count_match or level not in range(5):
                raise ValueError(f'Invalid calendar cell for {day}; retaining previous graph.')
            count = 0 if count_match[1] == 'No' else int(count_match[1].replace(',', ''))
            days.append((day, level, count))
        days.sort()
        if sum(d[2] for d in days) != total:
            raise ValueError('Daily counts do not match GitHub total; retaining previous graph.')
        if len({d[0] for d in days}) != len(days) or (days[-1][0] - days[0][0]).days + 1 != len(days):
            raise ValueError('Calendar contains duplicate or missing dates.')
        return total, days


def weekly_totals(days):
    weeks = {}
    for day, _, count in days:
        start = day - timedelta(days=(day.weekday() + 1) % 7)
        if start not in weeks:
            weeks[start] = [day, day, 0]
        weeks[start][1] = day
        weeks[start][2] += count
    return list(weeks.values())


def render(total, days, refreshed, dark):
    bg, border, fg, muted = ('#0d1117', '#30363d', '#e6edf3', '#9198a1') if dark else ('#ffffff', '#d1d9e0', '#1f2328', '#59636e')
    accent = '#38bdf8' if dark else '#2563eb'
    weeks = weekly_totals(days)
    if sum(w[2] for w in weeks) != total:
        raise ValueError('Weekly totals do not match the source calendar.')
    peak = max(w[2] for w in weeks)
    raw_step = max(1, peak / 4)
    magnitude = 10 ** math.floor(math.log10(raw_step))
    step = next(n * magnitude for n in (1, 2, 5, 10) if n * magnitude >= raw_step)
    tick_count = max(1, math.ceil(peak / step))
    ceiling = step * tick_count
    left, right, top, bottom = 64, 868, 100, 240
    points = [(left + i * (right - left) / max(1, len(weeks) - 1),
               bottom - w[2] / ceiling * (bottom - top)) for i, w in enumerate(weeks)]
    line = 'M ' + ' L '.join(f'{x:.2f},{y:.2f}' for x, y in points)
    area = line + f' L {right},{bottom} L {left},{bottom} Z'
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="900" height="320" viewBox="0 0 900 320" role="img" aria-labelledby="title desc">',
             '<title id="title">GitHub contribution activity — weekly totals</title>',
             f'<desc id="desc">Line graph of {total:,} contributions from {days[0][0]} through {days[-1][0]}, grouped by Sunday-to-Saturday week. Boundary weeks may be partial. Refreshed {escape(refreshed)}.</desc>',
             f'<rect x="0.5" y="0.5" width="899" height="319" rx="8" fill="{bg}" stroke="{border}"/>',
             '<g font-family="Segoe UI,Arial,sans-serif">',
             f'<text x="24" y="34" font-size="20" font-weight="600" fill="{fg}">Contribution activity</text>',
             f'<text x="868" y="34" text-anchor="end" font-size="16" font-weight="600" fill="{accent}">{total:,} contributions</text>',
             f'<text x="24" y="58" font-size="12" fill="{muted}">Weekly totals · {days[0][0]} to {days[-1][0]}</text>',
             f'<text x="64" y="84" font-size="11" fill="{muted}">Contributions / week</text>']
    for tick in range(tick_count + 1):
        value = tick * step
        y = bottom - tick * (bottom - top) / tick_count
        parts.append(f'<path d="M {left},{y} H {right}" stroke="{border}" stroke-width="1"/>')
        parts.append(f'<text x="50" y="{y + 4}" text-anchor="end" font-size="11" fill="{muted}">{value:g}</text>')
    parts.append(f'<path d="{area}" fill="{accent}" fill-opacity="0.12"/>')
    parts.append(f'<path d="{line}" fill="none" stroke="{accent}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>')
    for (x, y), (start, end, count) in zip(points, weeks):
        parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="2.4" fill="{accent}"><title>{start} to {end}: {count} contributions</title></circle>')
    ticks = sorted({round(i * (len(weeks) - 1) / 6) for i in range(7)})
    for index in ticks:
        x = points[index][0]
        anchor = 'start' if index == 0 else 'end' if index == len(weeks) - 1 else 'middle'
        parts.append(f'<text x="{x:.2f}" y="263" text-anchor="{anchor}" font-size="11" fill="{muted}">{weeks[index][0]:%d %b %Y}</text>')
    parts.append(f'<text x="24" y="302" font-size="11" fill="{muted}">Updated {escape(refreshed)}</text>')
    parts.append(f'<text x="868" y="302" text-anchor="end" font-size="11" fill="{muted}">Weeks: Sun–Sat · Current week may be partial</text></g></svg>')
    return '\n'.join(parts) + '\n'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--html', type=Path, help='Optional saved GitHub calendar for local verification')
    args = parser.parse_args()
    if args.html:
        content = args.html.read_text(encoding='utf-8')
    else:
        request = Request('https://github.com/users/Duke-Dz/contributions', headers={'User-Agent': 'Duke-Dz-profile-activity', 'Accept-Language': 'en-US'})
        with urlopen(request, timeout=30) as response:
            content = response.read().decode('utf-8')
    calendar = CalendarParser()
    calendar.feed(content)
    total, days = calendar.calendar()
    now = datetime.now(timezone.utc)
    if not 0 <= (now.date() - days[-1][0]).days <= 2:
        raise ValueError('GitHub returned an outdated calendar; retaining previous graph.')
    refreshed = now.strftime('%Y-%m-%d %H:%M UTC')
    output = Path(__file__).resolve().parents[1] / 'assets'
    output.mkdir(exist_ok=True)
    for dark, theme in [(False, 'light'), (True, 'dark')]:
        (output / f'activity-{theme}.svg').write_text(render(total, days, refreshed, dark), encoding='utf-8')
    print(f'Generated activity graph: {total} contributions, {len(days)} days, through {days[-1][0]}')


if __name__ == '__main__':
    main()
