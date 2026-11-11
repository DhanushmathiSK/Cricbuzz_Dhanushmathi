-- Cricbuzz LiveStats database schema
-- Dialect: sqlite

CREATE TABLE IF NOT EXISTS players (
    player_id INTEGER PRIMARY KEY AUTOINCREMENT,
    api_player_id VARCHAR(32),
    name VARCHAR(120) NOT NULL,
    country VARCHAR(80) NOT NULL DEFAULT 'Unknown',
    role VARCHAR(20) DEFAULT 'Batsman',
    batting_style VARCHAR(60) DEFAULT 'Unknown',
    bowling_style VARCHAR(60) DEFAULT 'Unknown',
    format VARCHAR(10) DEFAULT 'ODI',
    matches_played INTEGER DEFAULT 0,
    runs INTEGER DEFAULT 0,
    wickets INTEGER DEFAULT 0,
    batting_avg FLOAT DEFAULT 0,
    bowling_avg FLOAT DEFAULT 0,
    economy_rate FLOAT DEFAULT 0,
    strike_rate FLOAT DEFAULT 0,
    centuries INTEGER DEFAULT 0,
    highest_score INTEGER DEFAULT 0,
    balls_bowled INTEGER DEFAULT 0,
    catches INTEGER DEFAULT 0,
    stumpings INTEGER DEFAULT 0,
    run_outs INTEGER DEFAULT 0,
    last_synced VARCHAR(20),
    UNIQUE (api_player_id, format),
    CHECK (role IN ('Batsman', 'Bowler', 'All-Rounder', 'Wicket-Keeper')),
    CHECK (format IN ('Test', 'ODI', 'T20I')),
    CHECK (length(trim(name)) > 0)
);
CREATE INDEX IF NOT EXISTS ix_players_country ON players (country);
CREATE INDEX IF NOT EXISTS ix_players_format ON players (format);
CREATE INDEX IF NOT EXISTS ix_players_name ON players (name);

CREATE TABLE IF NOT EXISTS series (
    series_id INTEGER PRIMARY KEY,
    name VARCHAR(200),
    host_country VARCHAR(100),
    match_type VARCHAR(30),
    start_date VARCHAR(10),
    end_date VARCHAR(10),
    total_matches INTEGER
);
CREATE INDEX IF NOT EXISTS ix_series_start ON series (start_date);

CREATE TABLE IF NOT EXISTS venues (
    venue_id INTEGER PRIMARY KEY,
    name VARCHAR(200),
    city VARCHAR(100),
    country VARCHAR(100),
    capacity INTEGER
);
CREATE INDEX IF NOT EXISTS ix_venues_capacity ON venues (capacity);

CREATE TABLE IF NOT EXISTS matches (
    match_id INTEGER PRIMARY KEY AUTOINCREMENT,
    series_id INTEGER,
    series_name VARCHAR(200),
    match_desc VARCHAR(120),
    match_format VARCHAR(20),
    start_date VARCHAR(10),
    state VARCHAR(40),
    status VARCHAR(300),
    team1 VARCHAR(100),
    team2 VARCHAR(100),
    team1_score VARCHAR(100),
    team2_score VARCHAR(100),
    venue_id INTEGER,
    venue VARCHAR(200),
    city VARCHAR(100),
    country VARCHAR(100),
    winner VARCHAR(100),
    victory_type VARCHAR(20),
    victory_margin INTEGER,
    toss_winner VARCHAR(100),
    toss_decision VARCHAR(20),
    details_synced INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_matches_date ON matches (start_date);
CREATE INDEX IF NOT EXISTS ix_matches_winner ON matches (winner);
CREATE INDEX IF NOT EXISTS ix_matches_series ON matches (series_id);

CREATE TABLE IF NOT EXISTS batting_performance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER,
    innings INTEGER,
    team VARCHAR(100),
    player_id VARCHAR(32),
    player_name VARCHAR(120),
    batting_position INTEGER,
    runs INTEGER DEFAULT 0,
    balls INTEGER DEFAULT 0,
    fours INTEGER DEFAULT 0,
    sixes INTEGER DEFAULT 0,
    strike_rate FLOAT DEFAULT 0,
    out_desc VARCHAR(200)
);
CREATE INDEX IF NOT EXISTS ix_bat_match ON batting_performance (match_id);
CREATE INDEX IF NOT EXISTS ix_bat_player ON batting_performance (player_name);

CREATE TABLE IF NOT EXISTS bowling_performance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER,
    innings INTEGER,
    team VARCHAR(100),
    player_id VARCHAR(32),
    player_name VARCHAR(120),
    overs FLOAT DEFAULT 0,
    maidens INTEGER DEFAULT 0,
    runs_conceded INTEGER DEFAULT 0,
    wickets INTEGER DEFAULT 0,
    economy FLOAT DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_bowl_match ON bowling_performance (match_id);
CREATE INDEX IF NOT EXISTS ix_bowl_player ON bowling_performance (player_name);

CREATE TABLE IF NOT EXISTS partnerships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER,
    innings INTEGER,
    batting_team VARCHAR(100),
    player1 VARCHAR(120),
    player2 VARCHAR(120),
    runs INTEGER DEFAULT 0,
    balls INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_part_match ON partnerships (match_id);

