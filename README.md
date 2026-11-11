# 🏏 Cricbuzz LiveStats: Real-Time Cricket Insights & SQL-Based Analytics

A Streamlit dashboard that pulls live data from the **Cricbuzz Cricket API** (RapidAPI) with
Python's `requests`, stores it in a SQL database, and answers 25 analytics questions with SQL.

## Pages
| Page | What it does |
|---|---|
| Home | Project description, tools, instructions, folder structure, schema/data download |
| Live Match Centre | Live / recent / upcoming matches, full scorecards (batsmen, bowlers, partnerships), toss and venue. Select one match to analyse |
| Top Player Stats | API leaderboards (most runs, highest score, most wickets, ...) plus charts |
| Player Registry (CRUD) | Create, read, update, delete players and matches with forms. Import players from the API |
| Advanced SQL Query Engine | Q1 to Q25, with adjustable thresholds and an optional "selected match only" filter |

## Setup
1. Install Python 3.10 or newer.
2. Install the packages:
   ```bash
   python -m pip install -r requirements.txt
   ```
3. Get an API key: subscribe to the free plan of the
   [Cricbuzz Cricket API](https://rapidapi.com/cricketapilive/api/cricbuzz-cricket/) on RapidAPI,
   then copy the key from **My Apps > default-application > Authorization**.
4. Create `.streamlit/secrets.toml` (copy `secrets.toml.example`):
   ```toml
   RAPIDAPI_KEY = "your-key-here"
   ```
   Never commit this file (it is already in `.gitignore`).
5. Run:
   ```bash
   python -m streamlit run main.py
   ```

## First run: load the data
Use the numbered buttons in the sidebar, in order:
1. **Sync matches & series** (3 API calls)
2. **Sync scorecards** (2 calls per match): fills batting, bowling, partnerships, toss, venue country
3. **Sync venue capacities** (1 call per venue)
4. **Sync player stats** (about 4 calls per player)

The free plan has a small quota, so start with small numbers. Data is stored locally, so each item
only needs syncing once. Responses are cached for 5 minutes.

## Database
* Default: SQLite file `cricket.db` (no setup).
* Other databases: set `DATABASE_URL` in `secrets.toml`
  (`postgresql://user:pass@host:5432/db` needs `psycopg2-binary`;
  `mysql://user:pass@host:3306/db` needs `pymysql`). Only SQLite has been tested.
* All connections go through `utils/db_connection.py`.
* Schema: `sql/schema.sql`. Sample data: use **Home > Prepare full dump** to export your synced
  data as `sample_data.sql`.
* Older `cricket.db` files are upgraded automatically (new columns are added, data is kept).

## Folder structure
```
cricbuzz_livestats/
├── main.py
├── requirements.txt
├── README.md
├── .gitignore
├── .streamlit/secrets.toml(.example)
├── sql/schema.sql
└── utils/
    ├── config.py          settings and secrets
    ├── db_connection.py   connection handling, schema, helpers
    ├── api_client.py      API calls and JSON parsers
    ├── sync.py            API -> database
    └── queries.py         the 25 SQL questions
```

## Data limits (be aware)
* Questions that need many matches (for example "at least 5 matches between two teams in 3 years")
  return rows only after enough scorecards are synced. Lower the thresholds in the question's
  inputs to experiment with small data.
* The API does not return fielding stats, so catches, stumpings and run-outs default to 0
  (editable on the CRUD page).
* Standard deviations and trends (Q19, Q22, Q23, Q25) are computed in pandas so they work on every database.
* Endpoint paths and JSON keys follow the RapidAPI docs. If a page shows no data, open the
  "Raw API response" expander and compare it with the parser in `utils/api_client.py`.

## Guidelines checklist
PEP 8 style, docstrings on functions, exception handling around API and database calls, secrets
kept out of the code, modular `utils` package, Git-ready (`.gitignore` included).
