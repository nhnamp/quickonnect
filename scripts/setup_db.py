#!/usr/bin/env python3
"""Create the QuicKonNect database schema in PostgreSQL."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg

SCHEMA_SQL = """
-- Drop existing types and tables for clean setup
DROP TABLE IF EXISTS whiteboard_events CASCADE;
DROP TABLE IF EXISTS messages CASCADE;
DROP TABLE IF EXISTS room_participants CASCADE;
DROP TABLE IF EXISTS rooms CASCADE;
DROP TABLE IF EXISTS friendships CASCADE;
DROP TABLE IF EXISTS sessions CASCADE;
DROP TABLE IF EXISTS users CASCADE;
DROP TYPE IF EXISTS friend_status;
DROP TYPE IF EXISTS message_type;

-- Custom enum types
CREATE TYPE friend_status AS ENUM ('pending', 'accepted');
CREATE TYPE message_type AS ENUM ('text', 'image', 'file');

-- Users
CREATE TABLE users (
    id            SERIAL PRIMARY KEY,
    username      VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- Sessions (JWT tracking / revocation)
CREATE TABLE sessions (
    id            SERIAL PRIMARY KEY,
    user_id       INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token         VARCHAR(512) NOT NULL,
    expires_at    TIMESTAMPTZ NOT NULL,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_sessions_user_id ON sessions(user_id);
CREATE INDEX idx_sessions_token ON sessions(token);

-- Friendships
CREATE TABLE friendships (
    user_id       INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    friend_id     INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status        friend_status NOT NULL DEFAULT 'pending',
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, friend_id)
);

-- Rooms (video call / chat rooms)
CREATE TABLE rooms (
    id            SERIAL PRIMARY KEY,
    room_code     VARCHAR(20) UNIQUE NOT NULL,
    created_by    INT NOT NULL REFERENCES users(id),
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- Room participants
CREATE TABLE room_participants (
    room_id       INT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    user_id       INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    joined_at     TIMESTAMPTZ DEFAULT NOW(),
    left_at       TIMESTAMPTZ,
    PRIMARY KEY (room_id, user_id, joined_at)
);

-- Messages
CREATE TABLE messages (
    id            BIGSERIAL PRIMARY KEY,
    room_id       INT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    sender_id     INT NOT NULL REFERENCES users(id),
    content       TEXT NOT NULL,
    msg_type      message_type NOT NULL DEFAULT 'text',
    sent_at       TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_messages_room_id ON messages(room_id, sent_at);

-- Whiteboard events (for Phase 4)
CREATE TABLE whiteboard_events (
    id            BIGSERIAL PRIMARY KEY,
    room_id       INT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    user_id       INT NOT NULL REFERENCES users(id),
    seq_num       INT NOT NULL,
    event_type    VARCHAR(30) NOT NULL,
    payload       JSONB NOT NULL,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_whiteboard_room_seq ON whiteboard_events(room_id, seq_num);
"""


def main():
    db_host = os.environ.get("DB_HOST", "127.0.0.1")
    db_port = os.environ.get("DB_PORT", "5432")
    db_name = os.environ.get("DB_NAME", "quickonnect")
    db_user = os.environ.get("DB_USER", "quickonnect")
    db_password = os.environ.get("DB_PASSWORD", "quickonnect")

    dsn = f"host={db_host} port={db_port} dbname={db_name} user={db_user} password={db_password}"

    print(f"Connecting to PostgreSQL at {db_host}:{db_port}/{db_name} as {db_user}...")
    try:
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(SCHEMA_SQL)
            conn.commit()
        print("Schema created successfully.")
    except psycopg.OperationalError as e:
        print(f"\nConnection failed: {e}")
        print("\nMake sure PostgreSQL is running and the database exists.")
        print("To create the database and user, run:")
        print(f"  sudo -u postgres psql -c \"CREATE USER {db_user} WITH PASSWORD '{db_password}';\"")
        print(f"  sudo -u postgres psql -c \"CREATE DATABASE {db_name} OWNER {db_user};\"")
        sys.exit(1)


if __name__ == "__main__":
    main()
