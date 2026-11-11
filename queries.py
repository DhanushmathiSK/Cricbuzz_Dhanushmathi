"""The 25 SQL practice questions, grouped by difficulty.

Each question is a dict:
    id, title   - number and label shown in the UI
    sql         - portable SQL using :named parameters
    inputs      - optional UI widgets (thresholds from the assignment are the defaults)
    prep        - optional function(values) -> dict of SQL parameters
    post        - optional function(df, values) -> DataFrame or {title: DataFrame}
                  (used where a standard deviation / trend is easier in pandas and
                  works on every database)
    scoped      - True if the {MF:alias} placeholder can limit it to one selected match
    note        - caveat shown under the result
    chart       - optional (x_column, y_column) for a bar chart
"""
import re
from datetime import datetime, timedelta

import numpy as np
import pandas as pd


def _int_input(name, label, default, lo=1, hi=100000):
    return {"name": name, "label": label, "kind": "int", "min": lo, "max": hi, "default": default}


def _days_ago(days):
    return (datetime.now() - timedelta(days=int(days))).strftime("%Y-%m-%d")


def build_sql(question, values, selected_match_id=None, only_selected=False):
    """Return (sql, params) for a question, optionally limited to one match."""
    params = question["prep"](values) if question.get("prep") else dict(values)
    sql = question["sql"]
    if only_selected and selected_match_id and question.get("scoped"):
        sql = re.sub(r"\{MF:(\w+)\}", lambda m: f" AND {m.group(1)}.match_id = :mid", sql)
        params["mid"] = int(selected_match_id)
    else:
        sql = re.sub(r"\{MF:\w+\}", "", sql)
    return sql, params


# =====================================================================
# Post-processing helpers (pandas)
# =====================================================================
def post_consistency(df, v):
    """Q19: average and standard deviation of runs per batsman."""
    if df.empty:
        return df
    df = df.copy()
    df["runs"] = pd.to_numeric(df["runs"], errors="coerce")
    out = (df.groupby("player_name")["runs"]
           .agg(innings="count", avg_runs="mean", std_dev=lambda s: s.std(ddof=0))
           .reset_index())
    out = out[out["innings"] >= v["min_innings"]].sort_values("std_dev")
    return out


def post_head_to_head(df, v):
    """Q22: head-to-head summary and batting-first vs bowling-first by venue."""
    if df.empty:
        return df
    df = df.copy()
    df["victory_margin"] = pd.to_numeric(df["victory_margin"], errors="coerce")
    summary = []
    for (team_a, team_b), g in df.groupby(["team_a", "team_b"]):
        if len(g) < v["min_matches"]:
            continue
        decided = g[g["winner"].notna()]
        wins_a = int((decided["winner"] == team_a).sum())
        wins_b = int((decided["winner"] == team_b).sum())

        def margin(team, vtype):
            rows = decided[(decided["winner"] == team) & (decided["victory_type"] == vtype)]
            return rows["victory_margin"].mean()

        total = len(g)
        summary.append({
            "team_a": team_a, "team_b": team_b, "total_matches": total,
            "team_a_wins": wins_a, "team_b_wins": wins_b,
            "team_a_win_pct": 100.0 * wins_a / total, "team_b_win_pct": 100.0 * wins_b / total,
            "a_avg_margin_runs": margin(team_a, "runs"), "a_avg_margin_wkts": margin(team_a, "wickets"),
            "b_avg_margin_runs": margin(team_b, "runs"), "b_avg_margin_wkts": margin(team_b, "wickets"),
        })
    result = {"Head-to-head summary": pd.DataFrame(summary)}
    if not summary:
        return result

    pairs = {(s["team_a"], s["team_b"]) for s in summary}
    venue_rows = []
    for _, row in df.iterrows():
        if (row["team_a"], row["team_b"]) not in pairs or pd.isna(row["winner"]):
            continue
        if pd.isna(row["toss_winner"]) or pd.isna(row["toss_decision"]):
            continue
        other = row["team_b"] if row["toss_winner"] == row["team_a"] else row["team_a"]
        bat_first = row["toss_winner"] if row["toss_decision"] == "Bat first" else other
        venue_rows.append({"team_a": row["team_a"], "team_b": row["team_b"], "venue": row["venue"],
                           "bat_first_won": int(row["winner"] == bat_first)})
    if venue_rows:
        vdf = pd.DataFrame(venue_rows)
        grouped = (vdf.groupby(["team_a", "team_b", "venue"])["bat_first_won"]
                   .agg(matches="count", batting_first_wins="sum").reset_index())
        grouped["bowling_first_wins"] = grouped["matches"] - grouped["batting_first_wins"]
        result["Batting first vs bowling first by venue"] = grouped
    return result


def post_form(df, v):
    """Q23: recent form from each player's last 10 batting innings."""
    if df.empty:
        return df
    rows = []
    for name, g in df.groupby("player_name"):
        g = g.sort_values("start_date").tail(10)
        runs = pd.to_numeric(g["runs"], errors="coerce")
        strike = pd.to_numeric(g["strike_rate"], errors="coerce")
        avg5, avg10 = runs.tail(5).mean(), runs.mean()
        sr_recent = strike.tail(5).mean()
        sr_before = strike.iloc[:-5].mean() if len(strike) > 5 else np.nan
        if np.isnan(sr_before):
            trend = "n/a"
        elif sr_recent > sr_before * 1.05:
            trend = "Rising"
        elif sr_recent < sr_before * 0.95:
            trend = "Falling"
        else:
            trend = "Steady"
        std = runs.std(ddof=0)
        cv = std / avg10 if avg10 else np.nan
        if avg5 >= 50 and avg5 >= avg10:
            form = "Excellent Form"
        elif avg5 >= 35:
            form = "Good Form"
        elif avg5 >= 20:
            form = "Average Form"
        else:
            form = "Poor Form"
        rows.append({
            "player_name": name, "innings_used": len(runs), "avg_last_5": avg5, "avg_last_10": avg10,
            "recent_sr": sr_recent, "sr_trend": trend, "scores_50_plus": int((runs >= 50).sum()),
            "std_dev": std, "consistency_score": 100 / (1 + cv) if cv == cv else np.nan, "form": form,
        })
    return pd.DataFrame(rows).sort_values("avg_last_5", ascending=False)


def post_trajectory(df, v):
    """Q25: quarterly performance and career-phase classification."""
    if df.empty:
        return df
    df = df.copy()
    df["date"] = pd.to_datetime(df["start_date"], errors="coerce")
    df = df.dropna(subset=["date"])
    df["runs"] = pd.to_numeric(df["runs"], errors="coerce")
    df["strike_rate"] = pd.to_numeric(df["strike_rate"], errors="coerce")
    df["quarter"] = df["date"].dt.to_period("Q").astype(str)
    quarterly = (df.groupby(["player_name", "quarter"])
                 .agg(matches=("match_id", "nunique"), avg_runs=("runs", "mean"),
                      avg_strike_rate=("strike_rate", "mean")).reset_index())
    quarterly = quarterly[quarterly["matches"] >= v["min_matches"]].sort_values(["player_name", "quarter"])
    quarterly["runs_change_vs_prev"] = quarterly.groupby("player_name")["avg_runs"].diff()
    quarterly["sr_change_vs_prev"] = quarterly.groupby("player_name")["avg_strike_rate"].diff()

    summary = []
    for name, g in quarterly.groupby("player_name"):
        if len(g) < v["min_quarters"]:
            continue
        slope = np.polyfit(range(len(g)), g["avg_runs"].to_numpy(dtype=float), 1)[0]
        phase = "Career Ascending" if slope > 1 else "Career Declining" if slope < -1 else "Career Stable"
        summary.append({"player_name": name, "quarters": len(g), "trend_runs_per_quarter": slope,
                        "career_phase": phase})
    return {"Career phase (needs enough quarters)": pd.DataFrame(summary),
            "Quarterly averages": quarterly}


# =====================================================================
# BEGINNER (Q1-Q8)
# =====================================================================
BEGINNER = [
    {"id": 1, "title": "Players who represent India",
     "sql": "SELECT DISTINCT name AS full_name, role, batting_style, bowling_style "
            "FROM players WHERE country = 'India' ORDER BY name"},

    {"id": 2, "title": "Matches played in the last few days",
     "inputs": [_int_input("days", "Last N days", 30, 1, 3650)],
     "prep": lambda v: {"cutoff": _days_ago(v["days"])},
     "sql": "SELECT m.match_desc, m.team1, m.team2, m.venue, m.city, m.start_date AS match_date, m.status "
            "FROM matches m WHERE m.start_date >= :cutoff {MF:m} ORDER BY m.start_date DESC",
     "scoped": True},

    {"id": 3, "title": "Top 10 ODI run scorers",
     "sql": "SELECT name, runs AS total_runs, batting_avg, centuries FROM players "
            "WHERE format = 'ODI' ORDER BY runs DESC LIMIT 10"},

    {"id": 4, "title": "Venues with capacity above 25,000",
     "sql": "SELECT name AS venue, city, country, capacity FROM venues "
            "WHERE capacity > 25000 ORDER BY capacity DESC LIMIT 10",
     "note": "Needs venue data: use 'Sync scorecards' then 'Sync venue capacities' in the sidebar."},

    {"id": 5, "title": "Matches won by each team",
     "sql": "SELECT m.winner AS team_name, COUNT(*) AS total_wins FROM matches m "
            "WHERE m.winner IS NOT NULL {MF:m} GROUP BY m.winner ORDER BY total_wins DESC",
     "scoped": True},

    {"id": 6, "title": "Players per playing role",
     "sql": "SELECT role, COUNT(DISTINCT name) AS player_count FROM players "
            "GROUP BY role ORDER BY player_count DESC"},

    {"id": 7, "title": "Highest individual score per format",
     "sql": "SELECT p.format, p.name, p.highest_score FROM players p "
            "WHERE p.highest_score = (SELECT MAX(x.highest_score) FROM players x WHERE x.format = p.format) "
            "ORDER BY p.format"},

    {"id": 8, "title": "Series that started in a chosen year",
     "inputs": [_int_input("year", "Year", 2024, 1990, 2100)],
     "prep": lambda v: {"y_start": f"{int(v['year'])}-01-01", "y_end": f"{int(v['year']) + 1}-01-01"},
     "sql": "SELECT s.name AS series_name, "
            "COALESCE(s.host_country, (SELECT MAX(m.country) FROM matches m WHERE m.series_id = s.series_id)) "
            "AS host_country, s.match_type, s.start_date, s.total_matches "
            "FROM series s WHERE s.start_date >= :y_start AND s.start_date < :y_end ORDER BY s.start_date",
     "note": "Match type and total matches fill in after 'Sync series matches' (1 API call per series)."},
]

# =====================================================================
# INTERMEDIATE (Q9-Q16)
# =====================================================================
INTERMEDIATE = [
    {"id": 9, "title": "All-rounders with 1000+ runs and 50+ wickets",
     "sql": "SELECT name, runs AS total_runs, wickets AS total_wickets, format FROM players "
            "WHERE role = 'All-Rounder' AND runs > 1000 AND wickets > 50 ORDER BY runs DESC"},

    {"id": 10, "title": "Last 20 completed matches",
     "sql": "SELECT m.match_desc, m.team1, m.team2, m.winner AS winning_team, m.victory_margin, "
            "m.victory_type, m.venue FROM matches m WHERE m.winner IS NOT NULL {MF:m} "
            "ORDER BY m.start_date DESC LIMIT 20",
     "scoped": True},

    {"id": 11, "title": "Cross-format comparison (players in 2+ formats)",
     "sql": "SELECT name, "
            "SUM(CASE WHEN format = 'Test' THEN runs ELSE 0 END) AS test_runs, "
            "SUM(CASE WHEN format = 'ODI' THEN runs ELSE 0 END) AS odi_runs, "
            "SUM(CASE WHEN format = 'T20I' THEN runs ELSE 0 END) AS t20i_runs, "
            "SUM(batting_avg * matches_played) * 1.0 / NULLIF(SUM(matches_played), 0) AS overall_batting_avg "
            "FROM players GROUP BY name HAVING COUNT(DISTINCT format) >= 2 ORDER BY name",
     "note": "Overall average is weighted by matches played in each format."},

    {"id": 12, "title": "Home vs away wins per team",
     "sql": "SELECT team, SUM(is_home) AS home_matches, "
            "SUM(CASE WHEN is_home = 1 AND won = 1 THEN 1 ELSE 0 END) AS home_wins, "
            "SUM(1 - is_home) AS away_matches, "
            "SUM(CASE WHEN is_home = 0 AND won = 1 THEN 1 ELSE 0 END) AS away_wins FROM ("
            "SELECT team1 AS team, CASE WHEN team1 = country THEN 1 ELSE 0 END AS is_home, "
            "CASE WHEN winner = team1 THEN 1 ELSE 0 END AS won "
            "FROM matches WHERE country IS NOT NULL AND team1 IS NOT NULL "
            "UNION ALL "
            "SELECT team2, CASE WHEN team2 = country THEN 1 ELSE 0 END, "
            "CASE WHEN winner = team2 THEN 1 ELSE 0 END "
            "FROM matches WHERE country IS NOT NULL AND team2 IS NOT NULL) t "
            "GROUP BY team ORDER BY team",
     "note": "Needs the venue country, which comes from 'Sync scorecards' (match info)."},

    {"id": 13, "title": "Partnerships of 100+ runs",
     "inputs": [_int_input("min_runs", "Minimum partnership runs", 100, 1, 1000)],
     "sql": "SELECT p.player1, p.player2, p.runs AS partnership_runs, p.innings, m.match_desc "
            "FROM partnerships p JOIN matches m ON m.match_id = p.match_id "
            "WHERE p.runs >= :min_runs {MF:p} ORDER BY p.runs DESC",
     "scoped": True,
     "note": "Uses the scorecard's wicket-by-wicket partnership pairs (the two batsmen at the crease)."},

    {"id": 14, "title": "Bowling economy by venue",
     "inputs": [_int_input("min_matches", "Min matches at the venue", 3, 1, 100),
                _int_input("min_overs", "Min overs bowled per match", 4, 1, 10)],
     "sql": "SELECT bp.player_name AS bowler, m.venue, COUNT(DISTINCT bp.match_id) AS matches_played, "
            "SUM(bp.wickets) AS total_wickets, AVG(bp.economy) AS avg_economy "
            "FROM bowling_performance bp JOIN matches m ON m.match_id = bp.match_id "
            "WHERE bp.overs >= :min_overs AND m.venue IS NOT NULL "
            "GROUP BY bp.player_name, m.venue HAVING COUNT(DISTINCT bp.match_id) >= :min_matches "
            "ORDER BY avg_economy"},

    {"id": 15, "title": "Performance in close matches",
     "inputs": [_int_input("run_margin", "Close = decided by fewer than N runs", 50, 1, 500),
                _int_input("wkt_margin", "or fewer than N wickets", 5, 1, 10)],
     "sql": "SELECT b.player_name, AVG(b.runs) AS avg_runs, COUNT(DISTINCT b.match_id) AS close_matches_played, "
            "COUNT(DISTINCT CASE WHEN m.winner = b.team THEN b.match_id END) AS close_matches_won "
            "FROM batting_performance b JOIN matches m ON m.match_id = b.match_id "
            "WHERE m.victory_margin IS NOT NULL AND ((m.victory_type = 'runs' AND m.victory_margin < :run_margin) "
            "OR (m.victory_type = 'wickets' AND m.victory_margin < :wkt_margin)) "
            "GROUP BY b.player_name ORDER BY avg_runs DESC"},

    {"id": 16, "title": "Batting performance by year since 2020",
     "inputs": [_int_input("since_year", "Since year", 2020, 1990, 2100),
                _int_input("min_matches", "Min matches in the year", 5, 1, 100)],
     "prep": lambda v: {"since": f"{int(v['since_year'])}-01-01", "min_matches": v["min_matches"]},
     "sql": "SELECT b.player_name, substr(m.start_date, 1, 4) AS match_year, "
            "COUNT(DISTINCT b.match_id) AS matches, AVG(b.runs) AS avg_runs_per_match, "
            "AVG(b.strike_rate) AS avg_strike_rate "
            "FROM batting_performance b JOIN matches m ON m.match_id = b.match_id "
            "WHERE m.start_date >= :since "
            "GROUP BY b.player_name, substr(m.start_date, 1, 4) "
            "HAVING COUNT(DISTINCT b.match_id) >= :min_matches ORDER BY b.player_name, match_year"},
]

# =====================================================================
# ADVANCED (Q17-Q25)
# =====================================================================
ADVANCED = [
    {"id": 17, "title": "Does winning the toss help?",
     "sql": "SELECT toss_decision, COUNT(*) AS matches, "
            "SUM(CASE WHEN winner = toss_winner THEN 1 ELSE 0 END) AS toss_winner_won, "
            "100.0 * SUM(CASE WHEN winner = toss_winner THEN 1 ELSE 0 END) / COUNT(*) AS win_pct "
            "FROM matches WHERE toss_winner IS NOT NULL AND winner IS NOT NULL {MF:matches} "
            "GROUP BY toss_decision",
     "scoped": True,
     "note": "Toss data comes from 'Sync scorecards' (match info)."},

    {"id": 18, "title": "Most economical limited-overs bowlers",
     "inputs": [_int_input("min_matches", "Min matches", 10, 1, 1000),
                _int_input("min_overs", "Min average overs per match", 2, 1, 10)],
     "sql": "SELECT name, format, economy_rate, wickets, matches_played, "
            "balls_bowled / 6.0 / NULLIF(matches_played, 0) AS avg_overs_per_match "
            "FROM players WHERE format IN ('ODI', 'T20I') AND economy_rate > 0 "
            "AND matches_played >= :min_matches "
            "AND balls_bowled / 6.0 / NULLIF(matches_played, 0) >= :min_overs "
            "ORDER BY economy_rate ASC",
     "note": "Average overs per match is estimated as career balls bowled / 6 / matches."},

    {"id": 19, "title": "Batting consistency (standard deviation of runs)",
     "inputs": [_int_input("min_balls", "Min balls faced per innings", 10, 1, 300),
                _int_input("since_year", "Since year", 2022, 1990, 2100),
                _int_input("min_innings", "Min innings", 3, 1, 100)],
     "prep": lambda v: {"since": f"{int(v['since_year'])}-01-01", "min_balls": v["min_balls"]},
     "sql": "SELECT b.player_name, b.runs, b.balls, m.start_date "
            "FROM batting_performance b JOIN matches m ON m.match_id = b.match_id "
            "WHERE b.balls >= :min_balls AND m.start_date >= :since",
     "post": post_consistency,
     "note": "Standard deviation is calculated in pandas (works on every database). Lower = more consistent."},

    {"id": 20, "title": "Matches and batting average per format",
     "inputs": [_int_input("min_total", "Min total matches", 20, 1, 5000)],
     "sql": "SELECT name, "
            "SUM(CASE WHEN format = 'Test' THEN matches_played ELSE 0 END) AS test_matches, "
            "SUM(CASE WHEN format = 'ODI' THEN matches_played ELSE 0 END) AS odi_matches, "
            "SUM(CASE WHEN format = 'T20I' THEN matches_played ELSE 0 END) AS t20i_matches, "
            "MAX(CASE WHEN format = 'Test' THEN batting_avg END) AS test_avg, "
            "MAX(CASE WHEN format = 'ODI' THEN batting_avg END) AS odi_avg, "
            "MAX(CASE WHEN format = 'T20I' THEN batting_avg END) AS t20i_avg "
            "FROM players GROUP BY name HAVING SUM(matches_played) >= :min_total "
            "ORDER BY name"},

    {"id": 21, "title": "Player performance ranking (weighted score)",
     "inputs": [_int_input("top_n", "Top N per format", 5, 1, 100)],
     "sql": "WITH pts AS ("
            "SELECT name, format, "
            "(runs * 0.01) + (batting_avg * 0.5) + (strike_rate * 0.3) AS batting_points, "
            "CASE WHEN wickets > 0 THEN (wickets * 2) + ((50 - bowling_avg) * 0.5) + ((6 - economy_rate) * 2) "
            "ELSE 0 END AS bowling_points, "
            "(catches * 1) + (stumpings * 2) + (run_outs * 1) AS fielding_points FROM players), "
            "ranked AS (SELECT name, format, batting_points, bowling_points, fielding_points, "
            "batting_points + bowling_points + fielding_points AS total_points, "
            "RANK() OVER (PARTITION BY format ORDER BY batting_points + bowling_points + fielding_points DESC) "
            "AS rank_in_format FROM pts) "
            "SELECT * FROM ranked WHERE rank_in_format <= :top_n ORDER BY format, rank_in_format",
     "chart": ("name", "total_points"),
     "note": "Bowling points only count for players with wickets. Fielding = catches + 2 x stumpings + "
             "run-outs; the API does not return fielding stats, so those columns stay 0 unless edited on the CRUD page."},

    {"id": 22, "title": "Head-to-head analysis between teams",
     "inputs": [_int_input("min_matches", "Min matches between the teams", 5, 1, 100),
                _int_input("years", "Look back N years", 3, 1, 50)],
     "prep": lambda v: {"since": _days_ago(int(v["years"]) * 365)},
     "sql": "SELECT CASE WHEN team1 < team2 THEN team1 ELSE team2 END AS team_a, "
            "CASE WHEN team1 < team2 THEN team2 ELSE team1 END AS team_b, "
            "winner, victory_type, victory_margin, venue, toss_winner, toss_decision, start_date "
            "FROM matches WHERE team1 IS NOT NULL AND team2 IS NOT NULL AND start_date >= :since",
     "post": post_head_to_head,
     "note": "Lower 'Min matches' to 1 to see results on a small dataset."},

    {"id": 23, "title": "Recent form and momentum",
     "sql": "SELECT b.player_name, m.start_date, b.runs, b.balls, b.strike_rate "
            "FROM batting_performance b JOIN matches m ON m.match_id = b.match_id "
            "ORDER BY m.start_date",
     "post": post_form,
     "note": "Form: Excellent = last-5 average 50+ and above the last-10 average; Good 35+; Average 20+; else Poor."},

    {"id": 24, "title": "Best batting partnerships",
     "inputs": [_int_input("min_partnerships", "Min partnerships together", 5, 1, 100)],
     "sql": "SELECT CASE WHEN player1 < player2 THEN player1 ELSE player2 END AS player_a, "
            "CASE WHEN player1 < player2 THEN player2 ELSE player1 END AS player_b, "
            "COUNT(*) AS partnerships, AVG(runs) AS avg_partnership_runs, "
            "SUM(CASE WHEN runs > 50 THEN 1 ELSE 0 END) AS partnerships_over_50, "
            "MAX(runs) AS highest_partnership, "
            "100.0 * SUM(CASE WHEN runs > 50 THEN 1 ELSE 0 END) / COUNT(*) AS success_rate_pct "
            "FROM partnerships WHERE player1 IS NOT NULL AND player2 IS NOT NULL "
            "GROUP BY player_a, player_b HAVING COUNT(*) >= :min_partnerships "
            "ORDER BY success_rate_pct DESC, avg_partnership_runs DESC"},

    {"id": 25, "title": "Career trajectory over time (quarterly)",
     "inputs": [_int_input("min_quarters", "Min quarters of data", 6, 1, 40),
                _int_input("min_matches", "Min matches per quarter", 3, 1, 50)],
     "sql": "SELECT b.player_name, b.match_id, m.start_date, b.runs, b.strike_rate "
            "FROM batting_performance b JOIN matches m ON m.match_id = b.match_id",
     "post": post_trajectory,
     "note": "Rising/declining = slope of quarterly average runs (more than +1 or less than -1 per quarter)."},
]

CATEGORIES = [
    ("🟢 Beginner-Level (Questions 1-8)", BEGINNER, "beg"),
    ("🟡 Intermediate-Level (Questions 9-16)", INTERMEDIATE, "int"),
    ("🔴 Advanced-Level (Questions 17-25)", ADVANCED, "adv"),
]
