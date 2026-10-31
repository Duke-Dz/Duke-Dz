"""Render the public GitHub contribution calendar without a third-party stats API."""
import argparse
from datetime import date, datetime, timezone
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


def render(total, days, refreshed, dark):
    bg, border, fg, muted = ('#0d1117', '#30363d', '#e6edf3', '#9198a1') if dark else ('#ffffff', '#d1d9e0', '#1f2328', '#59636e')
    colors = ['#161b22', '#0e4429', '#006d32', '#26a641', '#39d353'] if dark else ['#eff2f5', '#9be9a8', '#40c463', '#30a14e', '#216e39']
    first = days[0][0]
    offset = (first.weekday() + 1) % 7
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="900" height="220" viewBox="0 0 900 220" role="img" aria-labelledby="title desc">',
             f'<title id="title">{total:,} contributions in the last year</title>',
             f'<desc id="desc">GitHub public profile calendar, {first} through {days[-1][0]}. Refreshed {refreshed}.</desc>',
             f'<rect x="0.5" y="0.5" width="899" height="219" rx="8" fill="{bg}" stroke="{border}"/>',
             '<g font-family="Segoe UI,Arial,sans-serif">',
             f'<text x="24" y="33" font-size="20" font-weight="600" fill="{fg}">{total:,} contributions in the last year</text>',
             f'<text x="24" y="55" font-size="12" fill="{muted}">{first} to {days[-1][0]}</text>']
    for day, level, count in days:
        position = (day - first).days + offset
        week, row = divmod(position, 7)
        x, y = 56 + week * 15, 86 + row * 13
        if day.day == 1:
            label_x = 56 + ((position + 6) // 7) * 15
            if label_x < 840:
                parts.append(f'<text x="{label_x}" y="76" font-size="11" fill="{muted}">{day:%b}</text>')
        parts.append(f'<rect x="{x}" y="{y}" width="11" height="10" rx="2" fill="{colors[level]}"><title>{day}: {count} contributions</title></rect>')
    for row, label in [(1, 'Mon'), (3, 'Wed'), (5, 'Fri')]:
        parts.append(f'<text x="24" y="{94 + row * 13}" font-size="10" fill="{muted}">{label}</text>')
    parts.append(f'<text x="24" y="202" font-size="11" fill="{muted}">GitHub public profile · Updated {escape(refreshed)}</text>')
    parts.append(f'<text x="728" y="202" font-size="10" fill="{muted}">Less</text>')
    for i, color in enumerate(colors):
        parts.append(f'<rect x="{756 + i * 15}" y="193" width="11" height="10" rx="2" fill="{color}"/>')
    parts.append(f'<text x="836" y="202" font-size="10" fill="{muted}">More</text></g></svg>')
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
    print(f'Generated calendar: {total} contributions, {len(days)} days, through {days[-1][0]}')


if __name__ == '__main__':
    main()
