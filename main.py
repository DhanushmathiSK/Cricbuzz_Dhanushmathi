"""Cricbuzz LiveStats: real-time cricket insights and SQL-based analytics.

Run with:  python -m streamlit run main.py
"""
from datetime import date

import pandas as pd
import streamlit as st

from utils import api_client as api
from utils import db_connection as db
from utils import queries, sync
from utils.config import get_setting

st.set_page_config(page_title="Cricbuzz LiveStats Analytics Suite", layout="wide", page_icon="🏏")

DEFAULT_PLAYERS = ["Virat Kohli", "Rohit Sharma", "Jasprit Bumrah",
                   "Ravindra Jadeja", "Steven Smith", "Rashid Khan"]

TOP_STATS = {
    "Most runs": "mostRuns", "Highest score": "highestScore", "Highest average": "highestAvg",
    "Highest strike rate": "highestSr", "Most hundreds": "mostHundreds", "Most fifties": "mostFifties",
    "Most fours": "mostFours", "Most sixes": "mostSixes", "Most wickets": "mostWickets",
    "Best bowling average": "lowestAvg", "Best economy": "lowestEcon",
    "Best bowling strike rate": "lowestSr", "Most five-wicket hauls": "mostFiveWickets",
    "Best bowling innings": "bestBowlingInnings",
}

PROJECT_TREE = """cricbuzz_livestats/
├── main.py                  # Streamlit app (5 pages)
├── requirements.txt         # dependencies
├── README.md                # setup + API key instructions
├── .gitignore
├── .streamlit/
│   ├── secrets.toml         # YOUR keys (never commit)
│   └── secrets.toml.example
├── sql/
│   └── schema.sql           # table structure
└── utils/
    ├── config.py            # settings / secrets helper
    ├── db_connection.py     # centralised DB connection + schema
    ├── api_client.py        # Cricbuzz API calls + JSON parsers
    ├── sync.py              # API -> database sync
    └── queries.py           # the 25 SQL questions"""


# =====================================================================
# Small UI helpers
# =====================================================================
def show_table(df):
    """Display a DataFrame at full width (works on old and new Streamlit)."""
    df = df.round(2) if not df.empty else df
    try:
        st.dataframe(df, width="stretch")
    except TypeError:
        st.dataframe(df, use_container_width=True)


def show_log(log, container=st):
    """Show a list of (ok, message) results."""
    for ok, message in log:
        (container.success if ok else container.error)(message)


def selected_match():
    """Return (match_id, label) of the match chosen on the Live Match Centre."""
    return st.session_state.get("selected_match_id"), st.session_state.get("selected_match_label")


# =====================================================================
# Sidebar: navigation + data sync
# =====================================================================
def sidebar():
    """Draw the navigation menu and sync controls. Returns the chosen page name."""
    st.sidebar.header("🧭 Navigation Menu")
    page = st.sidebar.radio("Go to:", list(PAGES))

    match_id, label = selected_match()
    if match_id:
        st.sidebar.info(f"🎯 Selected match:\n\n{label}")

    st.sidebar.markdown("---")
    st.sidebar.subheader("🔄 Sync from Cricbuzz API")
    if not api.get_api_key():
        st.sidebar.warning("No API key found. Add RAPIDAPI_KEY to .streamlit/secrets.toml")
    st.sidebar.caption("Free plans have a small quota. Sync only when you need to.")

    if st.sidebar.button("1) Sync matches & series (3 calls)"):
        with st.spinner("Fetching matches and series..."):
            n_matches, errors = sync.sync_matches()
            n_series, series_error = sync.sync_series()
        for error in errors + ([series_error] if series_error else []):
            st.sidebar.error(error)
        st.sidebar.success(f"Saved {n_matches} matches and {n_series} series.")

    n_details = st.sidebar.number_input("Matches for scorecard sync", 1, 20, 3)
    if st.sidebar.button("2) Sync scorecards (2 calls per match)"):
        bar = st.sidebar.progress(0.0)
        show_log(sync.sync_recent_details(n_details, bar.progress), st.sidebar)
        bar.empty()

    n_venues = st.sidebar.number_input("Venues for capacity sync", 1, 20, 5)
    if st.sidebar.button("3) Sync venue capacities (1 call each)"):
        bar = st.sidebar.progress(0.0)
        show_log(sync.sync_venue_capacities(n_venues, bar.progress), st.sidebar)
        bar.empty()

    player_text = st.sidebar.text_area("Players to sync (one per line):", "\n".join(DEFAULT_PLAYERS))
    st.sidebar.caption("Each player uses about 4 API calls.")
    if st.sidebar.button("4) Sync player stats"):
        names = [n.strip() for n in player_text.splitlines() if n.strip()]
        if names:
            bar = st.sidebar.progress(0.0)
            show_log(sync.sync_players(names, bar.progress), st.sidebar)
            bar.empty()
    return page


# =====================================================================
# PAGE 1: Home
# =====================================================================
def page_home():
    st.header("Welcome to Cricbuzz LiveStats")
    st.markdown("""
    **Real-time cricket insights and SQL-based analytics.** This app reads live data from the
    **Cricbuzz Cricket API** (RapidAPI) with Python's `requests`, stores it in a SQL database,
    and lets you explore it through five pages.

    ### 🛠️ Tools used
    * **Streamlit**: multi-page web interface
    * **requests**: REST calls to the Cricbuzz API
    * **SQLite** (PostgreSQL / MySQL supported via `DATABASE_URL`): relational storage
    * **pandas**: tables, charts and analytics

    ### 🧭 How to use it
    1. Use the **sidebar sync buttons** to download matches, scorecards, venues and player stats.
    2. **Live Match Centre**: live/recent/upcoming matches and full scorecards. Pick one match to analyse.
    3. **Top Player Stats**: API leaderboards (most runs, highest score, most wickets...).
    4. **Player Registry (CRUD)**: add, search, update and delete players and matches.
    5. **Advanced SQL Query Engine**: the 25 analytical questions.
    """)

    counts = db.table_counts()
    cols = st.columns(5)
    cols[0].metric("API key", "Found" if api.get_api_key() else "Missing")
    cols[1].metric("Player rows", counts["players"])
    cols[2].metric("Matches", counts["matches"])
    cols[3].metric("Scorecard rows", counts["batting_performance"])
    cols[4].metric("Series", counts["series"])

    st.subheader("📁 Folder structure")
    st.code(PROJECT_TREE)

    st.subheader("📚 Documentation")
    st.markdown("Setup steps and API key configuration are in **README.md** (project folder). "
                "API documentation: "
                "[Cricbuzz Cricket API on RapidAPI](https://rapidapi.com/cricketapilive/api/cricbuzz-cricket/).")

    st.subheader("🗄️ Database schema and sample data")
    st.download_button("⬇️ Download schema.sql", db.export_schema_sql(), "schema.sql")
    if st.button("Prepare full dump (schema + current data)"):
        st.download_button("⬇️ Download sample_data.sql", db.export_dump(), "sample_data.sql")


# =====================================================================
# PAGE 2: Live Match Centre
# =====================================================================
def render_scorecard(match):
    """Fetch and display match info and the full scorecard for one match."""
    match_id = match["match_id"]
    info = api.call_api(f"/mcenter/v1/{match_id}")
    card = api.call_api(f"/mcenter/v1/{match_id}/scard")

    if api.api_error(info):
        st.warning(f"Match info unavailable: {api.api_error(info)}")
    else:
        details = api.parse_match_info(info)
        c1, c2, c3 = st.columns(3)
        c1.metric("Status", details.get("status") or match.get("status") or "-")
        toss = f"{details['toss_winner']} ({details['toss_decision']})" if details.get("toss_winner") else "-"
        c2.metric("Toss", toss)
        place = ", ".join(x for x in (details.get("venue"), details.get("city"), details.get("country")) if x)
        c3.metric("Venue", place or "-")

    if api.api_error(card):
        st.warning(f"Scorecard unavailable: {api.api_error(card)}")
    else:
        batting, bowling, partnerships = api.parse_scorecard(card, match_id)
        bat_df, bowl_df, part_df = pd.DataFrame(batting), pd.DataFrame(bowling), pd.DataFrame(partnerships)
        if bat_df.empty and bowl_df.empty:
            st.info("The API returned no scorecard for this match yet.")
        else:
            for innings in sorted(bat_df["innings"].unique()) if not bat_df.empty else []:
                part = bat_df[bat_df["innings"] == innings]
                st.markdown(f"#### Innings {innings}: {part['team'].iloc[0]}")
                show_table(part[["player_name", "runs", "balls", "fours", "sixes", "strike_rate", "out_desc"]])
                if not bowl_df.empty:
                    st.markdown("**Bowling**")
                    show_table(bowl_df[bowl_df["innings"] == innings][
                        ["player_name", "overs", "maidens", "runs_conceded", "wickets", "economy"]])
                if not part_df.empty:
                    st.markdown("**Partnerships**")
                    show_table(part_df[part_df["innings"] == innings][["player1", "player2", "runs", "balls"]])

    if st.button("💾 Save match details & scorecard to database"):
        sync.save_match_rows([match])
        ok, message = sync.store_match_details(match_id, info, card)
        (st.success if ok else st.error)(message)


def matches_tab():
    feed = st.radio("Match feed:", ["Live", "Recent", "Upcoming"], horizontal=True)
    endpoint = {"Live": "/matches/v1/live", "Recent": "/matches/v1/recent",
                "Upcoming": "/matches/v1/upcoming"}[feed]
    data = api.call_api(endpoint)
    if api.api_error(data):
        st.error(f"API error: {api.api_error(data)}")
        return
    rows = api.parse_matches(data)
    if not rows:
        st.info(f"No {feed.lower()} matches returned right now.")
        return

    df = pd.DataFrame(rows)
    show_table(df[["series_name", "match_desc", "match_format", "team1", "team2",
                   "team1_score", "team2_score", "venue", "city", "status"]])

    options = {f"{r['team1']} vs {r['team2']} · {r['match_desc']} · id {r['match_id']}": r for r in rows}
    choice = st.selectbox("🎯 Select one match:", list(options))
    chosen = options[choice]

    c1, c2 = st.columns(2)
    if c1.button("✅ Use this match for analysis"):
        sync.save_match_rows([chosen])
        st.session_state["selected_match_id"] = chosen["match_id"]
        st.session_state["selected_match_label"] = choice
        st.success("Match selected. Open the SQL Query Engine page and tick 'Limit to selected match'.")
    if c2.button("💾 Save this whole feed to the database"):
        sync.save_match_rows(rows)
        st.success(f"Saved {len(rows)} matches.")

    st.subheader("Match summary")
    st.write(f"**{chosen['team1']}** {chosen['team1_score'] or '-'}  vs  "
             f"**{chosen['team2']}** {chosen['team2_score'] or '-'}")
    st.write(f"Status: {chosen['status'] or chosen['state'] or '-'}  |  "
             f"Venue: {chosen['venue'] or '-'}, {chosen['city'] or '-'}")

    if st.button("📋 Load scorecard & batsmen/bowler details (2 API calls)"):
        st.session_state["scorecard_for"] = chosen["match_id"]
    if st.session_state.get("scorecard_for") == chosen["match_id"]:
        render_scorecard(chosen)

    with st.expander("Raw API response (for debugging)"):
        st.json(data)


def series_tab():
    data = api.call_api("/series/v1/international")
    if api.api_error(data):
        st.error(f"API error: {api.api_error(data)}")
        return
    rows = api.parse_series(data)
    if not rows:
        st.info("No series returned.")
        return
    show_table(pd.DataFrame(rows))
    c1, c2 = st.columns(2)
    if c1.button("💾 Save series to database"):
        sync.db.upsert_many("series", [{k: v for k, v in r.items() if v is not None} for r in rows],
                            ["series_id"])
        st.success(f"Saved {len(rows)} series.")
    labels = {f"{r['name']} · id {r['series_id']}": r["series_id"] for r in rows}
    choice = c2.selectbox("Series to download in full:", list(labels))
    if st.button("⬇️ Sync all matches of this series (1 API call)"):
        ok, message = sync.sync_series_matches(labels[choice])
        (st.success if ok else st.error)(message)


def page_live():
    st.header("Live Match Centre")
    tab_matches, tab_series = st.tabs(["🏏 Matches & scorecards", "🏆 Series"])
    with tab_matches:
        matches_tab()
    with tab_series:
        series_tab()


# =====================================================================
# PAGE 3: Top Player Stats
# =====================================================================
def chart_top_stats(df):
    """Let the user choose a numeric column and chart it against the player name."""
    numeric = df.apply(pd.to_numeric, errors="coerce")
    num_cols = [c for c in df.columns if str(c).lower() != "id" and numeric[c].notna().sum() > 0]
    text_cols = [c for c in df.columns if c not in num_cols and str(c).lower() != "id"]
    if not num_cols or not text_cols:
        return
    metric = st.selectbox("Chart column:", num_cols, index=len(num_cols) - 1)
    chart_df = pd.DataFrame({"player": df[text_cols[0]], "value": numeric[metric]}).dropna()
    st.bar_chart(chart_df, x="player", y="value")


def page_top_stats():
    st.header("📊 Top Player Stats")
    st.subheader("🌐 From the Cricbuzz API")
    c1, c2 = st.columns(2)
    category = c1.selectbox("Category:", list(TOP_STATS))
    fmt = c2.selectbox("Format:", api.FORMATS, index=1)
    match_type = {"Test": 1, "ODI": 2, "T20I": 3}[fmt]  # verify in the API playground

    data = api.call_api("/stats/v1/topstats/0", {"statsType": TOP_STATS[category], "matchType": match_type})
    if api.api_error(data):
        st.error(api.api_error(data))
    else:
        df = api.table_to_df(data)
        if df.empty:
            st.info("Empty result. Check the raw response below.")
        else:
            show_table(df.head(15))
            chart_top_stats(df.head(15))
        with st.expander("Raw response"):
            st.json(data)

    st.markdown("---")
    st.subheader("🗄️ From your database")
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**Leading run scorers**")
        show_table(db.run_query("SELECT name, country, format, runs, batting_avg, highest_score "
                                "FROM players ORDER BY runs DESC LIMIT 5"))
    with col_b:
        st.markdown("**Leading wicket takers**")
        show_table(db.run_query("SELECT name, country, format, wickets, economy_rate "
                                "FROM players ORDER BY wickets DESC LIMIT 5"))


# =====================================================================
# PAGE 4: CRUD
# =====================================================================
def players_crud():
    st.subheader("🌐 Import a player from the API")
    c1, c2 = st.columns([3, 1])
    query = c1.text_input("Search player name:", key="api_player_q")
    if c2.button("Search API") and query.strip():
        results, error = api.search_player(query.strip())
        if error:
            st.error(error)
        st.session_state["api_results"] = results
    results = st.session_state.get("api_results", [])
    if results:
        labels = {f"{p.get('name')} ({p.get('teamName', '?')}) · id {p.get('id')}": p for p in results}
        choice = st.selectbox("Search results:", list(labels))
        if st.button("⬇️ Import selected player"):
            p = labels[choice]
            ok, message = sync.sync_player(p.get("id"), p.get("name", ""), p.get("teamName", ""))
            (st.success if ok else st.error)(message)

    st.markdown("---")
    st.subheader("➕ Create: add a player")
    with st.form("add_player_form", clear_on_submit=True):
        name = st.text_input("Player full name:")
        country = st.text_input("Country / team:")
        role = st.selectbox("Playing role:", ["Batsman", "Bowler", "All-Rounder", "Wicket-Keeper"])
        fmt = st.selectbox("Format:", api.FORMATS, index=1)
        if st.form_submit_button("Save player"):
            if name.strip() and country.strip():
                try:
                    db.execute("INSERT INTO players (name, country, role, format) "
                               "VALUES (:name, :country, :role, :format)",
                               {"name": name.strip(), "country": country.strip(), "role": role, "format": fmt})
                    st.success(f"Added {name.strip()}.")
                except Exception as exc:
                    st.error(f"Could not save: {exc}")
            else:
                st.error("Please fill in both name and country.")

    st.markdown("---")
    st.subheader("🔍 Read: search & filter")
    c1, c2 = st.columns(2)
    search_name = c1.text_input("Search by name:")
    filter_country = c2.text_input("Filter by country / team:")
    sql = ("SELECT player_id, name, country, role, format, matches_played, runs, wickets, "
           "batting_avg, bowling_avg, economy_rate, strike_rate FROM players WHERE 1 = 1")
    params = {}
    if search_name:
        sql += " AND LOWER(name) LIKE :name"
        params["name"] = f"%{search_name.lower()}%"
    if filter_country:
        sql += " AND LOWER(country) LIKE :country"
        params["country"] = f"%{filter_country.lower()}%"
    df = db.run_query(sql + " ORDER BY name, format", params)
    if df.empty:
        st.warning("No players found. Sync players from the sidebar or add one above.")
        return
    show_table(df)
    st.caption(f"Showing {len(df)} rows.")

    st.markdown("---")
    st.subheader("🛠️ Update & delete")
    player_id = int(st.selectbox("Select player ID:", df["player_id"].tolist()))
    row = db.run_query("SELECT * FROM players WHERE player_id = :id", {"id": player_id}).iloc[0]
    st.write(f"**Editing:** {row['name']} ({row['format']})")

    with st.form("update_player_form"):
        a, b, c = st.columns(3)
        runs = a.number_input("Runs", min_value=0, value=int(row["runs"]))
        wickets = a.number_input("Wickets", min_value=0, value=int(row["wickets"]))
        matches = a.number_input("Matches", min_value=0, value=int(row["matches_played"]))
        bat_avg = b.number_input("Batting avg", min_value=0.0, value=float(row["batting_avg"]))
        bowl_avg = b.number_input("Bowling avg", min_value=0.0, value=float(row["bowling_avg"]))
        economy = b.number_input("Economy", min_value=0.0, value=float(row["economy_rate"]))
        strike = c.number_input("Strike rate", min_value=0.0, value=float(row["strike_rate"]))
        catches = c.number_input("Catches", min_value=0, value=int(row["catches"]))
        stumpings = c.number_input("Stumpings", min_value=0, value=int(row["stumpings"]))
        run_outs = c.number_input("Run-outs", min_value=0, value=int(row["run_outs"]))
        if st.form_submit_button("💾 Apply changes"):
            db.execute(
                "UPDATE players SET runs = :runs, wickets = :wickets, matches_played = :matches, "
                "batting_avg = :bat, bowling_avg = :bowl, economy_rate = :eco, strike_rate = :sr, "
                "catches = :catches, stumpings = :stumpings, run_outs = :run_outs WHERE player_id = :id",
                {"runs": runs, "wickets": wickets, "matches": matches, "bat": bat_avg, "bowl": bowl_avg,
                 "eco": economy, "sr": strike, "catches": catches, "stumpings": stumpings,
                 "run_outs": run_outs, "id": player_id})
            st.success("Player updated. Reload the table to see the change.")

    confirm = st.checkbox("I confirm I want to permanently delete this player row.")
    if st.button("🗑️ Delete player", type="primary", disabled=not confirm):
        db.execute("DELETE FROM players WHERE player_id = :id", {"id": player_id})
        st.success("Player deleted.")
        st.rerun()


def matches_crud():
    st.subheader("➕ Create: add a match")
    with st.form("add_match_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        team1 = c1.text_input("Team 1:")
        team2 = c2.text_input("Team 2:")
        series_name = c1.text_input("Series name:")
        desc = c2.text_input("Match description (e.g. 1st ODI):")
        fmt = c1.selectbox("Format:", ["TEST", "ODI", "T20"])
        match_date = c2.date_input("Date:", value=date.today())
        venue = c1.text_input("Venue:")
        city = c2.text_input("City:")
        country = c1.text_input("Venue country:")
        status = c2.text_input("Status / result text:")
        winner = c1.text_input("Winner (optional):")
        if st.form_submit_button("Save match"):
            if team1.strip() and team2.strip():
                try:
                    db.execute(
                        "INSERT INTO matches (series_name, match_desc, match_format, start_date, state, status, "
                        "team1, team2, venue, city, country, winner) VALUES (:series, :desc, :fmt, :date, "
                        ":state, :status, :t1, :t2, :venue, :city, :country, :winner)",
                        {"series": series_name, "desc": desc, "fmt": fmt, "date": match_date.strftime("%Y-%m-%d"),
                         "state": "Complete" if winner.strip() else "Upcoming", "status": status,
                         "t1": team1.strip(), "t2": team2.strip(), "venue": venue, "city": city,
                         "country": country, "winner": winner.strip() or None})
                    st.success("Match added.")
                except Exception as exc:
                    st.error(f"Could not save: {exc}")
            else:
                st.error("Both team names are required.")

    st.markdown("---")
    st.subheader("🔍 Read: matches")
    team_filter = st.text_input("Filter by team name:")
    sql = ("SELECT match_id, match_desc, team1, team2, start_date, venue, status, winner, "
           "victory_type, victory_margin FROM matches WHERE 1 = 1")
    params = {}
    if team_filter:
        sql += " AND (LOWER(team1) LIKE :t OR LOWER(team2) LIKE :t)"
        params["t"] = f"%{team_filter.lower()}%"
    df = db.run_query(sql + " ORDER BY start_date DESC LIMIT 200", params)
    if df.empty:
        st.warning("No matches stored. Sync matches from the sidebar or add one above.")
        return
    show_table(df)

    st.markdown("---")
    st.subheader("🛠️ Update & delete")
    match_id = int(st.selectbox("Select match ID:", df["match_id"].tolist()))
    row = db.run_query("SELECT * FROM matches WHERE match_id = :id", {"id": match_id}).iloc[0]
    st.write(f"**Editing:** {row['team1']} vs {row['team2']}")
    with st.form("update_match_form"):
        status = st.text_input("Status:", value=row["status"] or "")
        winner = st.text_input("Winner:", value=row["winner"] or "")
        vtype = st.selectbox("Victory type:", ["", "runs", "wickets", "innings"],
                             index=["", "runs", "wickets", "innings"].index(row["victory_type"] or ""))
        margin = st.number_input("Victory margin:", min_value=0,
                                 value=int(row["victory_margin"]) if pd.notna(row["victory_margin"]) else 0)
        if st.form_submit_button("💾 Apply changes"):
            db.execute("UPDATE matches SET status = :s, winner = :w, victory_type = :v, victory_margin = :m "
                       "WHERE match_id = :id",
                       {"s": status, "w": winner or None, "v": vtype or None, "m": margin, "id": match_id})
            st.success("Match updated. Reload the table to see the change.")

    confirm = st.checkbox("I confirm I want to delete this match and its scorecard data.")
    if st.button("🗑️ Delete match", type="primary", disabled=not confirm):
        for table in ("batting_performance", "bowling_performance", "partnerships"):
            db.execute(f"DELETE FROM {table} WHERE match_id = :id", {"id": match_id})
        db.execute("DELETE FROM matches WHERE match_id = :id", {"id": match_id})
        st.success("Match deleted.")
        st.rerun()


def page_crud():
    st.header("🗄️ CRUD Operations")
    tab_players, tab_matches = st.tabs(["🏏 Players", "📅 Matches"])
    with tab_players:
        players_crud()
    with tab_matches:
        matches_crud()


# =====================================================================
# PAGE 5: SQL Query Engine
# =====================================================================
def render_question(question, key, match_id, only_selected):
    """Show the inputs, SQL and result of one question."""
    label_map = {q["id"]: q for q in queries.BEGINNER + queries.INTERMEDIATE + queries.ADVANCED}
    st.markdown(f"**Q{question['id']}: {label_map[question['id']]['title']}**")
    values = {}
    for item in question.get("inputs", []):
        widget_key = f"{key}_{question['id']}_{item['name']}"
        values[item["name"]] = int(st.number_input(item["label"], min_value=item["min"],
                                                    max_value=item["max"], value=item["default"],
                                                    step=1, key=widget_key))
    sql, params = queries.build_sql(question, values, match_id, only_selected)
    st.code(sql, language="sql")
    try:
        df = db.run_query(sql, params)
        result = question["post"](df, values) if question.get("post") else df
    except Exception as exc:
        st.error(f"Query failed: {exc}")
        return

    results = result if isinstance(result, dict) else {None: result}
    if all(r.empty for r in results.values()):
        st.info("No rows. Sync more data from the sidebar, or lower the thresholds above.")
    for title, frame in results.items():
        if title:
            st.markdown(f"*{title}*")
        if not frame.empty:
            show_table(frame)
    if question.get("chart") and isinstance(result, pd.DataFrame) and not result.empty:
        x, y = question["chart"]
        st.bar_chart(result, x=x, y=y)
    if question.get("note"):
        st.caption(question["note"])


def page_sql():
    st.header("🔬 SQL Query Engine (Questions 1-25)")
    counts = db.table_counts()
    st.caption("Rows available: " + " | ".join(f"{t}: {n}" for t, n in counts.items()))

    match_id, label = selected_match()
    only_selected = st.checkbox("🎯 Limit match-based questions (Q2, Q5, Q10, Q13, Q17) to the selected match",
                                disabled=match_id is None)
    if match_id is None:
        st.caption("Select a match on the Live Match Centre page to enable this option.")
    else:
        with st.expander(f"Data stored for the selected match: {label}"):
            for title, table in (("Batting", "batting_performance"), ("Bowling", "bowling_performance"),
                                 ("Partnerships", "partnerships")):
                frame = db.run_query(f"SELECT * FROM {table} WHERE match_id = :mid", {"mid": int(match_id)})
                st.markdown(f"**{title}**")
                if frame.empty:
                    st.caption("Nothing stored yet. Load the scorecard on the Live Match Centre and save it.")
                else:
                    show_table(frame)

    for title, questions, key in queries.CATEGORIES:
        with st.expander(title):
            choice = st.selectbox("Choose a question:", [f"Q{q['id']}: {q['title']}" for q in questions],
                                  key=f"{key}_choice")
            question = next(q for q in questions if choice.startswith(f"Q{q['id']}:"))
            render_question(question, key, match_id, only_selected)


# =====================================================================
# App entry
# =====================================================================
PAGES = {
    "🏠 Home Dashboard Overview": page_home,
    "🏏 Live Match Centre": page_live,
    "📊 Top Player Stats Analytics": page_top_stats,
    "🗄️ Player Registry (SQL CRUD)": page_crud,
    "🔬 Advanced SQL Query Engine": page_sql,
}


@st.cache_resource
def setup_database():
    """Create/upgrade the tables once per server run."""
    db.init_db()
    return True


def main():
    st.title("⚡ Cricbuzz LiveStats Analytics Platform")
    try:
        setup_database()
    except Exception as exc:
        st.error(f"Could not open the database ({db.get_url()}): {exc}")
        st.stop()
    page = sidebar()
    try:
        PAGES[page]()
    except Exception as exc:  # last-resort guard so the app never shows a raw traceback
        st.error(f"Something went wrong on this page: {exc}")


main()
