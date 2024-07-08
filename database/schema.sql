CREATE TABLE IF NOT EXISTS server_regions (
    server_id INTEGER,
    region_code TEXT,
    PRIMARY KEY (server_id, region_code)
);

CREATE TABLE IF NOT EXISTS weather_cache (
    city_code TEXT PRIMARY KEY,
    data TEXT,
    timestamp TEXT,
    date TEXT
);
