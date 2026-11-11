"""Cricbuzz Cricket API client (RapidAPI, via the `requests` library) and JSON parsers.

Endpoint paths and JSON key names follow the RapidAPI documentation as best
recalled; verify them in the RapidAPI playground if a parser returns nothing.
Every parser is defensive (.get with defaults) so a missing field never crashes.
"""
import re
import threading
import time
from datetime import datetime, timezone

import pandas as pd
import requests
import streamlit as st

from utils.config import get_setting

API_HOST = "cricbuzz-cricket.p.rapidapi.com"
FORMATS = ["Test", "ODI", "T20I"]
FORMAT_ALIASES = {"test": "Test", "odi": "ODI", "t20": "T20I", "t20i": "T20I"}
MIN_GAP_SECONDS = 0.7  # stay under the per-second rate limit

_throttle_lock = threading.Lock()
_last_call = [0.0]


class ApiError(Exception):
    """Raised for API failures so that errors are never cached."""


def get_api_key():
    """Return the RapidAPI key from secrets.toml / environment (or None)."""
    return get_setting("RAPIDAPI_KEY")


def _throttle():
    with _throttle_lock:
        wait = MIN_GAP_SECONDS - (time.time() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.time()


@st.cache_data(ttl=300, show_spinner=False)
def _fetch(endpoint, params=None):
    """GET one endpoint (cached 5 min, retries on HTTP 429). Raises ApiError on failure."""
    host = get_setting("RAPIDAPI_HOST", API_HOST)
    headers = {"x-rapidapi-key": get_api_key(), "x-rapidapi-host": host}
    response = None
    for attempt in range(3):
        _throttle()
        response = requests.get(f"https://{host}{endpoint}", headers=headers,
                                params=params, timeout=15)
        if response.status_code == 429 and attempt < 2:
            time.sleep(2 * (attempt + 1))
            continue
        break
    if response.status_code in (401, 403):
        raise ApiError(f"HTTP {response.status_code}: key invalid or not subscribed to this API")
    if response.status_code == 429:
        raise ApiError("HTTP 429: rate limit or monthly quota reached")
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ApiError("Unexpected response format")
    return data


def call_api(endpoint, params=None):
    """Call an endpoint. Returns the JSON dict, or {"error": "message"} on failure."""
    if not get_api_key():
        return {"error": "No API key found. Add RAPIDAPI_KEY to .streamlit/secrets.toml"}
    try:
        return _fetch(endpoint, params)
    except ApiError as exc:
        return {"error": str(exc)}
    except requests.exceptions.RequestException as exc:
        return {"error": f"Network error: {exc}"}
    except ValueError:
        return {"error": "API did not return valid JSON"}


def api_error(data):
    """Return the error message of an API result, or None when it succeeded."""
    return data.get("error") if isinstance(data, dict) else "Unexpected response"


# ---------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------
def ms_to_date(ms):
    """Epoch milliseconds -> 'YYYY-MM-DD' (or None)."""
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return None


def to_int(value, default=0):
    """Parse '13,848' / '264*' / 12.0 into an int."""
    try:
        return int(float(str(value).replace(",", "").replace("*", "").strip()))
    except (TypeError, ValueError):
        return default


def to_float(value, default=0.0):
    """Parse a number-like value into a float."""
    try:
        return float(str(value).replace(",", "").replace("*", "").strip())
    except (TypeError, ValueError):
        return default


def pick(row, names, default=0):
    """Return the first non-empty value among several possible header names."""
    for name in names:
        if name in row and row[name] not in (None, "", "-"):
            return row[name]
    return default


def normalize_role(role):
    """Map Cricbuzz roles ('WK-Batsman', 'Bowling Allrounder') to our four roles."""
    text = (role or "").lower()
    if "keeper" in text or "wk" in text:
        return "Wicket-Keeper"
    if "all" in text:
        return "All-Rounder"
    if "bowl" in text:
        return "Bowler"
    return "Batsman"


def normalize_decision(decision):
    """Map a toss decision to 'Bat first' / 'Bowl first'."""
    text = (decision or "").lower()
    if "bat" in text:
        return "Bat first"
    if "bowl" in text or "field" in text:
        return "Bowl first"
    return None


def fmt_score(team_score):
    """{'inngs1': {'runs': 184, 'wickets': 3, 'overs': 20.0}} -> '184/3 (20.0)'."""
    if not isinstance(team_score, dict):
        return None
    parts = []
    for key in sorted(team_score):
        innings = team_score[key]
        if isinstance(innings, dict) and innings.get("runs") is not None:
            text = str(innings["runs"])
            if innings.get("wickets") is not None:
                text += f"/{innings['wickets']}"
            if innings.get("overs") is not None:
                text += f" ({innings['overs']})"
            parts.append(text)
    return " & ".join(parts) if parts else None


def parse_result(status, team1, team2):
    """'India won by 24 runs' -> ('India', 'runs', 24)."""
    text = (status or "").lower()
    for team in (team1, team2):
        if team and text.startswith(f"{team} won".lower()):
            if "inns" in text:
                vtype = "innings"
            elif "wkt" in text or "wicket" in text:
                vtype = "wickets"
            elif "run" in text:
                vtype = "runs"
            else:
                vtype = None
            found = re.search(r"by (\d+)", text)
            return team, vtype, int(found.group(1)) if found else None
    return None, None, None


# ---------------------------------------------------------------------
# Match list / series parsers
# ---------------------------------------------------------------------
def _match_row(info, score):
    """Build one database row from a matchInfo / matchScore pair."""
    team1 = (info.get("team1") or {}).get("teamName")
    team2 = (info.get("team2") or {}).get("teamName")
    status = info.get("status") or ""
    winner, vtype, margin = parse_result(status, team1, team2)
    venue = info.get("venueInfo") or {}
    score = score or {}
    return {
        "match_id": info.get("matchId"),
        "series_id": info.get("seriesId"),
        "series_name": info.get("seriesName"),
        "match_desc": info.get("matchDesc"),
        "match_format": info.get("matchFormat"),
        "start_date": ms_to_date(info.get("startDate")),
        "state": info.get("state"),
        "status": status,
        "team1": team1,
        "team2": team2,
        "team1_score": fmt_score(score.get("team1Score")),
        "team2_score": fmt_score(score.get("team2Score")),
        "venue_id": venue.get("id"),
        "venue": venue.get("ground"),
        "city": venue.get("city"),
        "country": venue.get("country"),
        "winner": winner,
        "victory_type": vtype,
        "victory_margin": margin,
    }


def parse_matches(data):
    """/matches/v1/live|recent|upcoming -> list of match rows."""
    rows = []
    for type_match in data.get("typeMatches", []):
        for series_match in type_match.get("seriesMatches", []):
            wrapper = series_match.get("seriesAdWrapper")
            if not wrapper:
                continue
            for match in wrapper.get("matches", []):
                info = match.get("matchInfo") or {}
                if info.get("matchId") is not None:
                    rows.append(_match_row(info, match.get("matchScore")))
    return rows


def parse_series_matches(data):
    """/series/v1/{id} -> list of match rows for that series."""
    rows = []
    for block in data.get("matchDetails", []):
        details = block.get("matchDetailsMap") if isinstance(block, dict) else None
        if not details:
            continue
        for match in details.get("match", []):
            info = match.get("matchInfo") or {}
            if info.get("matchId") is not None:
                rows.append(_match_row(info, match.get("matchScore")))
    return rows


def parse_series(data):
    """/series/v1/international -> list of series rows."""
    rows = []
    for block in data.get("seriesMapProto", []):
        for series in block.get("series", []):
            if series.get("id") is None:
                continue
            rows.append({
                "series_id": series["id"],
                "name": series.get("name"),
                "start_date": ms_to_date(series.get("startDt")),
                "end_date": ms_to_date(series.get("endDt")),
            })
    return rows


# ---------------------------------------------------------------------
# Single match: info, scorecard, venue
# ---------------------------------------------------------------------
def parse_match_info(data):
    """/mcenter/v1/{id} -> toss, result, venue details (None where missing)."""
    info = data.get("matchInfo") if isinstance(data.get("matchInfo"), dict) else data
    toss = info.get("tossResults") or {}
    result = info.get("result") or {}
    venue = info.get("venue") or info.get("venueInfo") or {}
    team1 = (info.get("team1") or {}).get("name") or (info.get("team1") or {}).get("teamName")
    team2 = (info.get("team2") or {}).get("name") or (info.get("team2") or {}).get("teamName")
    status = info.get("status")

    winner = result.get("winningTeam")
    margin = result.get("winningMargin")
    vtype = None
    if winner:
        if result.get("winByInnings"):
            vtype = "innings"
        elif result.get("winByRuns"):
            vtype = "runs"
        else:
            vtype = "wickets"
    else:  # fall back to the status sentence
        winner, vtype, margin = parse_result(status, team1, team2)

    return {
        "toss_winner": toss.get("tossWinnerName"),
        "toss_decision": normalize_decision(toss.get("decision")),
        "winner": winner,
        "victory_type": vtype,
        "victory_margin": to_int(margin, None) if margin is not None else None,
        "venue_id": venue.get("id"),
        "venue": venue.get("name") or venue.get("ground"),
        "city": venue.get("city"),
        "country": venue.get("country"),
        "state": info.get("state"),
        "status": status,
    }


def _ordered(mapping):
    """Sort {'bat_2': .., 'bat_1': ..} by the number in the key."""
    def number(key):
        digits = "".join(ch for ch in str(key) if ch.isdigit())
        return int(digits) if digits else 0
    return [(number(k), mapping[k]) for k in sorted(mapping, key=number)]


def parse_scorecard(data, match_id):
    """/mcenter/v1/{id}/scard -> (batting rows, bowling rows, partnership rows)."""
    batting, bowling, partnerships = [], [], []
    for index, inn in enumerate(data.get("scoreCard", []), start=1):
        innings_no = to_int(inn.get("inningsId"), index)
        bat_side = inn.get("batTeamDetails") or {}
        bowl_side = inn.get("bowlTeamDetails") or {}
        bat_team = bat_side.get("batTeamName")
        bowl_team = bowl_side.get("bowlTeamName")

        for position, b in _ordered(bat_side.get("batsmenData") or {}):
            balls = to_int(b.get("balls"))
            if balls == 0 and not b.get("outDesc"):
                continue  # did not bat
            batting.append({
                "match_id": match_id, "innings": innings_no, "team": bat_team,
                "player_id": str(b.get("batId", "")), "player_name": b.get("batName"),
                "batting_position": position, "runs": to_int(b.get("runs")), "balls": balls,
                "fours": to_int(b.get("fours")), "sixes": to_int(b.get("sixes")),
                "strike_rate": to_float(b.get("strikeRate")), "out_desc": b.get("outDesc"),
            })

        for _, w in _ordered(bowl_side.get("bowlersData") or {}):
            bowling.append({
                "match_id": match_id, "innings": innings_no, "team": bowl_team,
                "player_id": str(w.get("bowlerId", "")), "player_name": w.get("bowlName"),
                "overs": to_float(w.get("overs")), "maidens": to_int(w.get("maidens")),
                "runs_conceded": to_int(w.get("runs")), "wickets": to_int(w.get("wickets")),
                "economy": to_float(w.get("economy")),
            })

        for _, p in _ordered(bat_side.get("partnershipsData") or {}):
            runs = p.get("totalRuns")
            if runs is None:
                runs = to_int(p.get("bat1Runs")) + to_int(p.get("bat2Runs"))
            partnerships.append({
                "match_id": match_id, "innings": innings_no, "batting_team": bat_team,
                "player1": p.get("bat1Name"), "player2": p.get("bat2Name"),
                "runs": to_int(runs), "balls": to_int(p.get("totalBalls")),
            })
    return batting, bowling, partnerships


def parse_venue(data):
    """/venues/v1/{id} -> name, city, country, capacity."""
    capacity = data.get("capacity")
    return {
        "name": data.get("ground") or data.get("name"),
        "city": data.get("city"),
        "country": data.get("country"),
        "capacity": to_int(capacity, None) if capacity is not None else None,
    }


# ---------------------------------------------------------------------
# Player statistics
# ---------------------------------------------------------------------
def search_player(name):
    """Search players by name. Returns (list_of_players, error_or_None)."""
    data = call_api("/stats/v1/player/search", {"plrN": name})
    if api_error(data):
        return [], api_error(data)
    return data.get("player", []), None


def table_to_df(data):
    """Turn {'headers': [...], 'values': [{'values': [...]}, ...]} into a DataFrame."""
    headers = list(data.get("headers", []))
    rows = [r.get("values", []) for r in data.get("values", []) if isinstance(r, dict)]
    if not rows:
        return pd.DataFrame()
    width = max(len(r) for r in rows)
    if len(headers) < width:
        if width - len(headers) == 1:
            headers = ["id"] + headers
        else:
            headers += [f"col{i}" for i in range(len(headers), width)]
    rows = [list(r) + [None] * (width - len(r)) for r in rows]
    return pd.DataFrame(rows, columns=headers[:width])


def stat_table(data):
    """Player batting/bowling response -> {'ODI': {'Matches': '295', 'Runs': '13906', ...}}.

    Handles both layouts: formats as column headers (one row per statistic),
    or one row per format.
    """
    if not isinstance(data, dict):
        return {}
    headers = [str(h) for h in data.get("headers", [])]
    rows = [r.get("values", []) for r in data.get("values", []) if isinstance(r, dict)]
    header_formats = [FORMAT_ALIASES.get(h.lower()) for h in headers]
    out = {}
    if any(header_formats):  # layout A: columns are formats
        for row in rows:
            if len(row) != len(headers):
                continue
            stat = str(row[0])
            for fmt, value in zip(header_formats[1:], row[1:]):
                if fmt:
                    out.setdefault(fmt, {})[stat] = value
    else:  # layout B: each row starts with a format name
        for row in rows:
            if row and len(row) == len(headers):
                fmt = FORMAT_ALIASES.get(str(row[0]).lower())
                if fmt:
                    out[fmt] = dict(zip(headers, row))
    return out
