CREATE TABLE IF NOT EXISTS spaces (
  id TEXT PRIMARY KEY,
  title TEXT,
  fetched_at TEXT
);

CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  space_id TEXT NOT NULL REFERENCES spaces(id),
  parent_id TEXT,
  person_id TEXT,
  person_email TEXT,
  created_at TEXT,
  text TEXT,
  html TEXT,
  markdown TEXT,
  mentioned_people TEXT,
  links TEXT,
  day TEXT
);

CREATE INDEX IF NOT EXISTS idx_messages_space ON messages(space_id);
CREATE INDEX IF NOT EXISTS idx_messages_parent ON messages(parent_id);
CREATE INDEX IF NOT EXISTS idx_messages_day ON messages(space_id, day);
