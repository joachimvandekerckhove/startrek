#!/usr/bin/env python3
"""Build startrek.db from STAPI and Memory Alpha (build-time only; requires network)."""

from __future__ import annotations

import argparse
import html
import json
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

STAPI_BASE = "https://stapi.co/api/v1/rest"
MA_API = "https://memory-alpha.fandom.com/api.php"
MA_DELAY = 0.5
STAPI_DELAY = 0.1

SERIES_TITLE = "Star Trek: Short Treks"
SERIES_KEY_ST = "ST"
FILM_KEY = "FILM"
FILM_TITLE = "Star Trek (Film)"

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
  id              INTEGER PRIMARY KEY,
  kind            TEXT NOT NULL CHECK(kind IN ('episode','movie')),
  series_key      TEXT,
  series_title    TEXT NOT NULL,
  season_number   INTEGER,
  episode_number  INTEGER,
  title           TEXT NOT NULL,
  air_date        TEXT NOT NULL,
  month_day       TEXT NOT NULL,
  summary         TEXT,
  stapi_uid       TEXT,
  ma_page_title   TEXT
);
CREATE INDEX IF NOT EXISTS idx_month_day ON entries(month_day);
CREATE UNIQUE INDEX IF NOT EXISTS idx_episode
  ON entries(series_key, season_number, episode_number) WHERE kind = 'episode';
CREATE INDEX IF NOT EXISTS idx_movie_title ON entries(title) WHERE kind = 'movie';
"""


@dataclass
class Entry:
    kind: str
    series_key: str | None
    series_title: str
    season_number: int | None
    episode_number: int | None
    title: str
    air_date: str
    summary: str | None = None
    stapi_uid: str | None = None
    ma_page_title: str | None = None

    @property
    def month_day(self) -> str:
        return self.air_date[5:10]

    def dedupe_key(self) -> tuple:
        if self.kind == "episode":
            return ("episode", self.series_key, self.season_number, self.episode_number)
        return ("movie", self.title, self.air_date)


class SummaryCache:
    def __init__(self) -> None:
        self._cache: dict[str, str | None] = {}

    def get(self, page_title: str, fetcher) -> str | None:
        if page_title not in self._cache:
            self._cache[page_title] = fetcher(page_title)
        return self._cache[page_title]


def http_get_json(url: str, delay: float = 0.0) -> dict:
    if delay:
        time.sleep(delay)
    req = urllib.request.Request(url, headers={"User-Agent": "startrek-cli-build/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def ma_api(params: dict) -> dict:
    url = MA_API + "?" + urllib.parse.urlencode({**params, "format": "json"})
    time.sleep(MA_DELAY)
    return http_get_json(url)


def strip_html(text: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def fetch_ma_teaser(page_title: str) -> str | None:
    try:
        sections = ma_api(
            {"action": "parse", "page": page_title, "prop": "sections"}
        )
        teaser_idx = None
        for sec in sections.get("parse", {}).get("sections", []):
            if sec.get("line") == "Teaser":
                teaser_idx = sec.get("index")
                break
        if teaser_idx:
            parsed = ma_api(
                {
                    "action": "parse",
                    "page": page_title,
                    "section": teaser_idx,
                    "prop": "text",
                }
            )
            raw = parsed.get("parse", {}).get("text", {}).get("*", "")
            text = strip_html(raw)
            if text:
                return text

        parsed = ma_api({"action": "parse", "page": page_title, "prop": "text"})
        raw = parsed.get("parse", {}).get("text", {}).get("*", "")
        m = re.search(
            r'class="mw-headline"[^>]*id="Summary"[^>]*>.*?</h2>(.*?)(?:<h[23]|$)',
            raw,
            flags=re.I | re.S,
        )
        if m:
            text = strip_html(m.group(1))
            if text:
                return text[:2000] if len(text) > 2000 else text
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, KeyError):
        return None
    return None


def guess_ma_page(entry: Entry) -> str:
    if entry.ma_page_title:
        return entry.ma_page_title
    title = entry.title.strip()
    if entry.series_key == SERIES_KEY_ST:
        return f"{title} (episode)"
    if entry.kind == "movie":
        return f"{title} (film)"
    return f"{title} (episode)"


def fetch_series_abbreviations() -> dict[str, str]:
    """Map STAPI series UID -> abbreviation (TNG, DS9, ...)."""
    mapping: dict[str, str] = {}
    data = http_get_json(f"{STAPI_BASE}/series/search?pageSize=50", STAPI_DELAY)
    for s in data.get("series") or []:
        uid = s.get("uid")
        abbr = s.get("abbreviation")
        if uid and abbr:
            mapping[uid] = abbr
    return mapping


def fetch_all_stapi_episodes(series_abbr: dict[str, str]) -> list[Entry]:
    entries: list[Entry] = []
    page = 0
    while True:
        url = f"{STAPI_BASE}/episode/search?pageNumber={page}&pageSize=100"
        data = http_get_json(url, STAPI_DELAY)
        eps = data.get("episodes") or []
        if not eps:
            break
        for ep in eps:
            air = ep.get("usAirDate")
            if not air:
                continue
            series = ep.get("series") or {}
            series_title = series.get("title") or "Unknown"
            series_uid = series.get("uid")
            abbr = series_abbr.get(series_uid) if series_uid else None
            if not abbr and series_title.startswith("Star Trek:"):
                abbr = series_title.split(":", 1)[1].strip().upper()[:4]
            entries.append(
                Entry(
                    kind="episode",
                    series_key=abbr,
                    series_title=series_title,
                    season_number=ep.get("seasonNumber"),
                    episode_number=ep.get("episodeNumber"),
                    title=ep.get("title") or "Unknown",
                    air_date=air,
                    stapi_uid=ep.get("uid"),
                )
            )
        page_info = data.get("page") or {}
        if page_info.get("lastPage"):
            break
        page += 1
    return entries


def fetch_all_stapi_movies() -> list[Entry]:
    entries: list[Entry] = []
    page = 0
    while True:
        url = f"{STAPI_BASE}/movie/search?pageNumber={page}&pageSize=100"
        data = http_get_json(url, STAPI_DELAY)
        movies = data.get("movies") or []
        if not movies:
            break
        for mv in movies:
            release = mv.get("usReleaseDate")
            if not release:
                continue
            entries.append(
                Entry(
                    kind="movie",
                    series_key=FILM_KEY,
                    series_title=FILM_TITLE,
                    season_number=None,
                    episode_number=None,
                    title=mv.get("title") or "Unknown",
                    air_date=release,
                    stapi_uid=mv.get("uid"),
                )
            )
        page_info = data.get("page") or {}
        if page_info.get("lastPage"):
            break
        page += 1
    return entries


def parse_short_treks() -> list[Entry]:
    data = ma_api({"action": "parse", "page": "Star_Trek:_Short_Treks", "prop": "text"})
    html_text = data.get("parse", {}).get("text", {}).get("*", "")
    row_pattern = re.compile(
        r'data-tpt-row-id="(\d+)x(\d+)"[\s\S]*?'
        r'title="[^"]* \(ST \d+x\d+\)"[^>]*>([^<]+)</span></a>"</td>\s*'
        r'<td>\d+x\d+</td>[\s\S]*?'
        r'>(\d{4})</a>-<a[^>]*>(\d{2})-(\d{2})</a>',
        re.MULTILINE,
    )
    entries: list[Entry] = []
    seen: set[tuple[int, int]] = set()
    for m in row_pattern.finditer(html_text):
        season = int(m.group(1))
        episode = int(m.group(2))
        if (season, episode) in seen:
            continue
        seen.add((season, episode))
        title = html.unescape(m.group(3).strip())
        year = int(m.group(4))
        month = int(m.group(5))
        day = int(m.group(6))
        air = date(year, month, day).isoformat()
        entries.append(
            Entry(
                kind="episode",
                series_key=SERIES_KEY_ST,
                series_title=SERIES_TITLE,
                season_number=season,
                episode_number=episode,
                title=title,
                air_date=air,
                ma_page_title=f"{title} (episode)",
            )
        )
    entries.sort(key=lambda e: (e.season_number or 0, e.episode_number or 0))
    return entries


def merge_entries(*groups: list[Entry]) -> list[Entry]:
    seen: set[tuple] = set()
    merged: list[Entry] = []
    for group in groups:
        for entry in group:
            key = entry.dedupe_key()
            if key in seen:
                continue
            seen.add(key)
            merged.append(entry)
    return merged


def attach_summaries(entries: list[Entry], cache: SummaryCache) -> None:
    total = len(entries)
    for i, entry in enumerate(entries, 1):
        page = guess_ma_page(entry)
        entry.ma_page_title = page
        if i % 50 == 0 or i == total:
            print(f"  summaries: {i}/{total}", file=sys.stderr)
        entry.summary = cache.get(page, fetch_ma_teaser)


def write_db(path: Path, entries: list[Entry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.executemany(
        """
        INSERT INTO entries (
          kind, series_key, series_title, season_number, episode_number,
          title, air_date, month_day, summary, stapi_uid, ma_page_title
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                e.kind,
                e.series_key,
                e.series_title,
                e.season_number,
                e.episode_number,
                e.title,
                e.air_date,
                e.month_day,
                e.summary,
                e.stapi_uid,
                e.ma_page_title,
            )
            for e in entries
        ],
    )
    conn.commit()
    conn.close()


def print_report(entries: list[Entry]) -> None:
    movies = [e for e in entries if e.kind == "movie"]
    st = [e for e in entries if e.series_key == SERIES_KEY_ST]
    episodes = [e for e in entries if e.kind == "episode"]
    by_series: dict[str, int] = {}
    for e in episodes:
        key = e.series_key or "?"
        by_series[key] = by_series.get(key, 0) + 1
    print("\n=== Build report ===")
    print(f"Total entries: {len(entries)}")
    print(f"Episodes: {len(episodes)}")
    print(f"Movies: {len(movies)}")
    print(f"Short Treks: {len(st)}")
    print("Per series:")
    for key in sorted(by_series):
        print(f"  {key}: {by_series[key]}")
    summaries = sum(1 for e in entries if e.summary)
    print(f"Summaries fetched: {summaries}/{len(entries)}")


def validate(entries: list[Entry]) -> None:
    movies = sum(1 for e in entries if e.kind == "movie")
    st = sum(1 for e in entries if e.series_key == SERIES_KEY_ST)
    total = len(entries)
    errors = []
    if movies != 14:
        errors.append(f"expected 14 movies, got {movies}")
    if st != 10:
        errors.append(f"expected 10 Short Treks, got {st}")
    if total < 884:
        errors.append(f"expected at least 884 total entries, got {total}")
    if errors:
        for err in errors:
            print(f"VALIDATION ERROR: {err}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build startrek.db")
    parser.add_argument("-o", "--output", type=Path, default=Path("startrek.db"))
    parser.add_argument(
        "--skip-summaries",
        action="store_true",
        help="Skip Memory Alpha summary fetch (dev only)",
    )
    args = parser.parse_args()

    print("Phase 1: STAPI episodes...", file=sys.stderr)
    series_abbr = fetch_series_abbreviations()
    stapi_eps = fetch_all_stapi_episodes(series_abbr)
    print(f"  fetched {len(stapi_eps)} episodes", file=sys.stderr)

    print("Phase 1b: STAPI movies...", file=sys.stderr)
    movies = fetch_all_stapi_movies()
    print(f"  fetched {len(movies)} movies", file=sys.stderr)

    print("Phase 2: Short Treks from Memory Alpha...", file=sys.stderr)
    short_treks = parse_short_treks()
    print(f"  fetched {len(short_treks)} Short Treks", file=sys.stderr)

    entries = merge_entries(stapi_eps, short_treks, movies)
    print(f"Merged {len(entries)} unique entries", file=sys.stderr)

    if not args.skip_summaries:
        print("Phase 3: Fetching summaries from Memory Alpha...", file=sys.stderr)
        cache = SummaryCache()
        attach_summaries(entries, cache)

    validate(entries)
    write_db(args.output, entries)
    print_report(entries)
    print(f"\nWrote {args.output}")


if __name__ == "__main__":
    main()
