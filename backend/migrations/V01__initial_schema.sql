-- Shadow Heist initial schema. Applied automatically only when the MySQL
-- Docker volume is created for the first time.

CREATE DATABASE IF NOT EXISTS shadow_heist
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE shadow_heist;

CREATE TABLE IF NOT EXISTS schema_migrations (
  version VARCHAR(50) NOT NULL PRIMARY KEY,
  applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS game_sessions (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  room_code CHAR(36) NOT NULL,
  phase ENUM('lobby', 'day', 'night', 'tribunal', 'finished') NOT NULL DEFAULT 'lobby',
  started_at DATETIME NULL,
  finished_at DATETIME NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_game_sessions_room_code (room_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS players (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  game_session_id BIGINT UNSIGNED NULL,
  username VARCHAR(100) NOT NULL,
  display_name VARCHAR(100) NULL,
  role ENUM('civilian', 'hitman', 'spy', 'detective') NULL,
  status ENUM('active', 'gagged', 'hostage', 'eliminated') NOT NULL DEFAULT 'active',
  aggressiveness TINYINT UNSIGNED NOT NULL DEFAULT 0,
  suspicion_score DECIMAL(5,2) NOT NULL DEFAULT 0.00,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_players_session_username (game_session_id, username),
  CONSTRAINT fk_players_game_session
    FOREIGN KEY (game_session_id) REFERENCES game_sessions(id)
    ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS chat_messages (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  game_session_id BIGINT UNSIGNED NULL,
  player_id BIGINT UNSIGNED NULL,
  sender_name VARCHAR(100) NOT NULL,
  message TEXT NOT NULL,
  intent VARCHAR(50) NULL,
  suspicion_score DECIMAL(5,2) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_chat_messages_session_created (game_session_id, created_at),
  CONSTRAINT fk_chat_messages_game_session
    FOREIGN KEY (game_session_id) REFERENCES game_sessions(id)
    ON DELETE CASCADE,
  CONSTRAINT fk_chat_messages_player
    FOREIGN KEY (player_id) REFERENCES players(id)
    ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ai_analyses (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  chat_message_id BIGINT UNSIGNED NULL,
  intent VARCHAR(50) NOT NULL,
  aggressiveness TINYINT UNSIGNED NOT NULL,
  suspicion_score DECIMAL(5,2) NOT NULL,
  suspicion_status ENUM('AMAN', 'SUS', 'BAHAYA') NOT NULL,
  llm_response TEXT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_ai_analyses_chat_message (chat_message_id),
  CONSTRAINT fk_ai_analyses_chat_message
    FOREIGN KEY (chat_message_id) REFERENCES chat_messages(id)
    ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO schema_migrations (version) VALUES ('V1__initial_schema');
