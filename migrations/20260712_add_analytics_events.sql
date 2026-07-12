CREATE TABLE IF NOT EXISTS analytics_events (
    id INTEGER PRIMARY KEY,
    event_name VARCHAR(80) NOT NULL,
    user_id INTEGER NULL REFERENCES users(id),
    session_id VARCHAR(80) NULL,
    guest_id VARCHAR(80) NULL,
    created_at TIMESTAMP NOT NULL,
    event_date DATE NOT NULL,
    metadata_json TEXT NULL
);
CREATE INDEX IF NOT EXISTS ix_analytics_events_event_name ON analytics_events (event_name);
CREATE INDEX IF NOT EXISTS ix_analytics_events_created_at ON analytics_events (created_at);
CREATE INDEX IF NOT EXISTS ix_analytics_events_event_date ON analytics_events (event_date);
CREATE INDEX IF NOT EXISTS ix_analytics_events_user_id ON analytics_events (user_id);
CREATE INDEX IF NOT EXISTS ix_analytics_events_session_id ON analytics_events (session_id);
CREATE INDEX IF NOT EXISTS ix_analytics_events_guest_id ON analytics_events (guest_id);
