"""Render the contribution graph as a metro: a train runs the grid and picks up every station.

Usage: GITHUB_TOKEN=... python scripts/train.py <user> <out_dir>
Writes github-train.svg and github-train-dark.svg.
"""
import json
import math
import os
import sys
import urllib.request

CELL, GAP = 11, 4
STEP = CELL + GAP
MARGIN_X, MARGIN_Y = 24, 14
LEAD = 90          # off-canvas run-in / run-out, longer than the train
SPEED = 170        # px per second
CARS = ["#D3311F", "#E5559B", "#1E5BD8", "#12A5A5"]  # L1, L2, L5, L8

THEMES = {
    "dark": {
        "levels": ["#161B22", "#0E4F4A", "#0F766E", "#12A5A5", "#5EEAD4"],
        "track": "#30363D",
        "flash": "#E3C27A",
        "loco": "#C9A04A",
        "window": "#0F1115",
    },
    "light": {
        "levels": ["#EBEDF0", "#A7E3DD", "#5CC4BD", "#12A5A5", "#0B6B6B"],
        "track": "#D0D7DE",
        "flash": "#C9A04A",
        "loco": "#C9A04A",
        "window": "#17150F",
    },
}
LEVELS = {"NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2, "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4}

QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        weeks { contributionDays { weekday contributionLevel } }
      }
    }
  }
}
"""


def fetch_weeks(user, token):
    body = json.dumps({"query": QUERY, "variables": {"login": user}}).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=body,
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        data = json.load(resp)
    if "errors" in data:
        raise SystemExit(f"GraphQL error: {data['errors']}")
    weeks = data["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
    return [[(d["weekday"], LEVELS[d["contributionLevel"]]) for d in w["contributionDays"]] for w in weeks]


def geometry(n_weeks):
    """Boustrophedon track through the row centres: row 0 left→right, row 1 right→left, …"""
    x_start = MARGIN_X + CELL / 2
    x_end = MARGIN_X + (n_weeks - 1) * STEP + CELL / 2
    row_y = [MARGIN_Y + r * STEP + CELL / 2 for r in range(7)]
    r = STEP / 2
    straight = x_end - x_start
    arc = math.pi * r

    d = [f"M{x_start - LEAD:.1f} {row_y[0]:.1f} H{x_end:.1f}"]
    for i in range(1, 7):
        sweep = 1 if i % 2 else 0
        x_turn = x_end if i % 2 else x_start
        x_next = x_start if i % 2 else x_end
        d.append(f"A{r:.1f} {r:.1f} 0 0 {sweep} {x_turn:.1f} {row_y[i]:.1f} H{x_next:.1f}")
    exit_x = x_end + LEAD  # row 6 runs left→right
    d.append(f"H{exit_x:.1f}")
    total = LEAD + 7 * straight + 6 * arc + LEAD

    def dist(col, row):
        x = MARGIN_X + col * STEP + CELL / 2
        along = (x - x_start) if row % 2 == 0 else (x_end - x)
        return LEAD + row * (straight + arc) + along

    return " ".join(d), total, dist


def render(weeks, theme):
    t = THEMES[theme]
    n = len(weeks)
    width = MARGIN_X * 2 + n * STEP - GAP
    height = MARGIN_Y * 2 + 7 * STEP - GAP
    path, total, dist = geometry(n)
    dur = total / SPEED
    spacing = 15  # px between car centres
    lag = spacing / SPEED
    head_offset = len(CARS) * lag  # loco starts this far ahead on the path

    def frac(sec):
        return max(0.0, min(1.0, sec / dur))

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height:.0f}" width="{width:.0f}" height="{height:.0f}">',
        "<defs>",
        f'<path id="track" d="{path}"/>',
        '<filter id="glow" x="-100%" y="-100%" width="300%" height="300%"><feGaussianBlur stdDeviation="1.6" result="b"/>'
        '<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>',
        "</defs>",
        f'<use href="#track" fill="none" stroke="{t["track"]}" stroke-width="2"/>',
    ]

    empty = t["levels"][0]
    for col, week in enumerate(weeks):
        for weekday, level in week:
            x = MARGIN_X + col * STEP
            y = MARGIN_Y + weekday * STEP
            fill = t["levels"][level]
            rect = f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="2.5" fill="{fill}"'
            if level == 0:
                out.append(rect + "/>")
                continue
            hit = dist(col, weekday) / SPEED - head_offset
            k = [0, frac(hit), frac(hit + 0.12), frac(hit + 0.7), 0.985, 1]
            for i in range(1, len(k)):  # keyTimes must strictly increase
                k[i] = max(k[i], k[i - 1] + 1e-4)
            k = [min(v, 1) for v in k]
            k[-1] = 1
            if len(set(k)) < len(k):  # station sits at the very end of the run; leave it alone
                out.append(rect + "/>")
                continue
            vals = [fill, fill, t["flash"], empty, empty, fill]
            out.append(
                rect + f'><animate attributeName="fill" dur="{dur:.2f}s" repeatCount="indefinite" '
                f'keyTimes="{";".join(f"{v:.4f}" for v in k)}" values="{";".join(vals)}"/></rect>'
            )

    def mover(body, delay):
        return (
            f'<g>{body}<animateMotion dur="{dur:.2f}s" begin="{-delay:.3f}s" repeatCount="indefinite" '
            f'rotate="auto"><mpath href="#track"/></animateMotion></g>'
        )

    for i, color in enumerate(reversed(CARS)):  # last car first so the loco draws on top
        delay = i * lag
        out.append(mover(f'<rect x="-6" y="-4" width="12" height="8" rx="2" fill="{color}"/>', delay))
    loco = (
        f'<rect x="-8" y="-4.5" width="16" height="9" rx="3" fill="{t["loco"]}"/>'
        f'<rect x="-5" y="-2.5" width="5" height="5" rx="1" fill="{t["window"]}"/>'
        f'<circle cx="7" cy="0" r="1.8" fill="#FFF8E1" filter="url(#glow)"/>'
    )
    out.append(mover(loco, head_offset))
    out.append("</svg>")
    return "\n".join(out)


def main():
    user, out_dir = sys.argv[1], sys.argv[2]
    weeks = fetch_weeks(user, os.environ["GITHUB_TOKEN"])
    os.makedirs(out_dir, exist_ok=True)
    for theme, name in (("light", "github-train.svg"), ("dark", "github-train-dark.svg")):
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as f:
            f.write(render(weeks, theme))
    print(f"{len(weeks)} weeks rendered to {out_dir}")


if __name__ == "__main__":
    main()
