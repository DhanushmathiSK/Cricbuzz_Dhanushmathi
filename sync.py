"""Copy data from the Cricbuzz API into the database.

Every function returns plain values (counts / messages) and never raises for
API problems, so the UI can simply display the result.
"""
import time
from collections import Counter
from datetime import datetime

from utils import api_client as api
from utils import db_connection as db


def _clean(row):
    """Drop None values so partial data never overwrites good data with NULL."""
    return {k: v for k, v in row.items() if v is not None}


# ---------------------------------------------------------------------
# Matches and series
# ---------------------------------------------------------------------
def save_match_rows(rows):
    """Insert or update match rows (keyed by match_id)."""
    if rows:
        db.upsert_many("matches", [_clean(r) for r in rows], ["match_id"])


def sync_matches():
    """Sync recent and live matches. Returns (rows_saved, list_of_errors)."""
    total, errors = 0, []
    for endpoint in ("/matches/v1/recent", "/matches/v1/live"):
        data = api.call_api(endpoint)
        error = api.api_error(data)
        if error:
            errors.append(f"{endpoint}: {error}")
            continue
        rows = api.parse_matches(data)
        save_match_rows(rows)
        total += len(rows)
    return total, errors


def sync_series():
    """Sync the international series list. Returns (rows_saved, error_or_None)."""
    data = api.call_api("/series/v1/international")
    error = api.api_error(data)
    if error:
        return 0, error
    rows = api.parse_series(data)
    if rows:
        db.upsert_many("series", [_clean(r) for r in rows], ["series_id"])
    return len(rows), None


def sync_series_matches(series_id):
    """Fetch every match of one series (1 API call) and store them. Returns (ok, message)."""
    data = api.call_api(f"/series/v1/{series_id}")
    error = api.api_error(data)
    if error:
        return False, error
    rows = api.parse_series_matches(data)
    if not rows:
        return False, "No matches found for this series"
    save_match_rows(rows)
    formats = Counter(r["match_format"] for r in rows if r["match_format"])
    update = {"series_id": int(series_id), "total_matches": len(rows)}
    if formats:
        update["match_type"] = formats.most_common(1)[0][0]
    db.upsert_many("series", [update], ["series_id"])
    return True, f"Saved {len(rows)} matches for series {series_id}"


def store_match_details(match_id, info_data, card_data):
    """Write match info (toss/result/venue) and the scorecard to the database.

    Takes already-fetched API responses, so it makes no API calls itself.
    Returns (ok, message).
    """
    messages = []
    if info_data and not api.api_error(info_data):
        details = api.parse_match_info(info_data)
        row = _clean({**details, "match_id": match_id, "details_synced": 1})
        db.upsert_many("matches", [row], ["match_id"])
        if details.get("venue_id"):
            venue = _clean({"venue_id": details["venue_id"], "name": details["venue"],
                            "city": details["city"], "country": details["country"]})
            db.upsert_many("venues", [venue], ["venue_id"])
        messages.append("match info")

    if card_data and not api.api_error(card_data):
        batting, bowling, partnerships = api.parse_scorecard(card_data, match_id)
        if batting or bowling or partnerships:
            for table, rows in (("batting_performance", batting),
                                ("bowling_performance", bowling),
                                ("partnerships", partnerships)):
                db.execute(f"DELETE FROM {table} WHERE match_id = :mid", {"mid": match_id})
                db.insert_many(table, rows)
            db.execute("UPDATE matches SET details_synced = 1 WHERE match_id = :mid",
                       {"mid": match_id})
            messages.append(f"scorecard ({len(batting)} batting, {len(bowling)} bowling, "
                            f"{len(partnerships)} partnership rows)")

    if not messages:
        return False, "Nothing could be saved (API returned no usable data)"
    return True, "Saved " + " and ".join(messages)


def sync_match_details(match_id):
    """Fetch match info + scorecard (2 API calls) and store them. Returns (ok, message)."""
    info = api.call_api(f"/mcenter/v1/{match_id}")
    card = api.call_api(f"/mcenter/v1/{match_id}/scard")
    if api.api_error(info) and api.api_error(card):
        return False, api.api_error(info)
    return store_match_details(match_id, info, card)


def sync_recent_details(limit, progress=None):
    """Sync details for the newest completed matches that have none yet.

    Costs about 2 API calls per match. Returns a list of (ok, message).
    """
    df = db.run_query(
        "SELECT match_id FROM matches WHERE state = 'Complete' "
        "AND COALESCE(details_synced, 0) = 0 ORDER BY start_date DESC LIMIT :n",
        {"n": int(limit)})
    log = []
    ids = df["match_id"].tolist()
    for i, match_id in enumerate(ids):
        ok, msg = sync_match_details(int(match_id))
        log.append((ok, f"Match {match_id}: {msg}"))
        if progress:
            progress((i + 1) / len(ids))
    if not ids:
        log.append((False, "No completed matches without details. Sync matches first."))
    return log


def sync_venue_capacities(limit, progress=None):
    """Fetch capacity for venues that have none yet (1 API call each)."""
    # First collect venue ids already known from the synced matches (no API call)
    db.execute(
        "INSERT INTO venues (venue_id, name, city) "
        "SELECT venue_id, MAX(venue), MAX(city) FROM matches "
        "WHERE venue_id IS NOT NULL AND venue_id NOT IN (SELECT venue_id FROM venues) "
        "GROUP BY venue_id")
    df = db.run_query("SELECT venue_id FROM venues WHERE capacity IS NULL LIMIT :n",
                      {"n": int(limit)})
    log = []
    ids = df["venue_id"].tolist()
    for i, venue_id in enumerate(ids):
        data = api.call_api(f"/venues/v1/{int(venue_id)}")
        error = api.api_error(data)
        if error:
            log.append((False, f"Venue {venue_id}: {error}"))
        else:
            venue = _clean(api.parse_venue(data))
            venue["venue_id"] = int(venue_id)
            db.upsert_many("venues", [venue], ["venue_id"])
            log.append((True, f"Venue {venue_id}: capacity {venue.get('capacity', 'n/a')}"))
        if progress:
            progress((i + 1) / len(ids))
    if not ids:
        log.append((False, "No venues without capacity. Sync scorecards first to collect venues."))
    return log


# ---------------------------------------------------------------------
# Players
# ---------------------------------------------------------------------
def sync_player(api_id, fallback_name="", fallback_country=""):
    """Fetch profile + batting + bowling stats (3 API calls). Returns (ok, message)."""
    info = api.call_api(f"/stats/v1/player/{api_id}")
    if api.api_error(info):
        return False, f"Profile error: {api.api_error(info)}"
    bat_raw = api.call_api(f"/stats/v1/player/{api_id}/batting")
    bowl_raw = api.call_api(f"/stats/v1/player/{api_id}/bowling")
    bat, bowl = api.stat_table(bat_raw), api.stat_table(bowl_raw)

    name = info.get("name") or fallback_name or "Unknown"
    country = info.get("intlTeam") or fallback_country or "Unknown"
    role = api.normalize_role(info.get("role"))
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    rows = []
    for fmt in api.FORMATS:
        b, w = bat.get(fmt, {}), bowl.get(fmt, {})
        if not b and not w:
            continue
        rows.append({
            "api_player_id": str(api_id), "name": name, "country": country, "role": role,
            "batting_style": info.get("bat") or "Unknown",
            "bowling_style": info.get("bowl") or "Unknown",
            "format": fmt,
            "matches_played": api.to_int(api.pick(b, ["Matches"], api.pick(w, ["Matches"]))),
            "runs": api.to_int(api.pick(b, ["Runs"])),
            "wickets": api.to_int(api.pick(w, ["Wickets", "Wkts"])),
            "batting_avg": api.to_float(api.pick(b, ["Average", "Avg"])),
            "bowling_avg": api.to_float(api.pick(w, ["Average", "Avg"])),
            "economy_rate": api.to_float(api.pick(w, ["Economy", "Eco"])),
            "strike_rate": api.to_float(api.pick(b, ["SR", "Strike Rate"])),
            "centuries": api.to_int(api.pick(b, ["100", "100s"])),
            "highest_score": api.to_int(api.pick(b, ["Highest", "HS"])),
            "balls_bowled": api.to_int(api.pick(w, ["Balls"])),
            "last_synced": now,
        })
    if not rows:
        return False, (f"No Test/ODI/T20I stats found for {name}. "
                       f"Batting headers: {bat_raw.get('headers')} | "
                       f"error: {api.api_error(bat_raw)}")
    db.upsert_many("players", rows, ["api_player_id", "format"])
    return True, f"Saved {name} ({len(rows)} formats)"


def sync_players(names, progress=None):
    """Search and sync a list of player names. Returns a list of (ok, message)."""
    log = []
    for i, name in enumerate(names):
        results, error = api.search_player(name)
        if error:
            log.append((False, f"{name}: {error}"))
        elif not results:
            log.append((False, f"{name}: not found (try the full name, e.g. 'Steven Smith')"))
        else:
            first = results[0]
            log.append(sync_player(first.get("id"), first.get("name", name),
                                   first.get("teamName", "")))
        if progress:
            progress((i + 1) / len(names))
        time.sleep(1.0)  # be gentle with the rate limit
    return log
