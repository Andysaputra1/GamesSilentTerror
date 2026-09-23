CREATE TABLE IF NOT EXISTS panel_configuration (
 id TINYINT NOT NULL PRIMARY KEY, config JSON NOT NULL,
 updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS panel_sessions (
 token_hash CHAR(64) NOT NULL PRIMARY KEY, expires_at DATETIME NOT NULL,
 credential_version CHAR(64) NOT NULL, INDEX idx_panel_expiry (expires_at)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS checker_traces (
 id CHAR(32) NOT NULL PRIMARY KEY, room_code VARCHAR(36) NOT NULL,
 trace JSON NOT NULL, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
 INDEX idx_checker_room (room_code, created_at, id)
) ENGINE=InnoDB;
INSERT INTO schema_migrations(version) VALUES ('V6__admin_panel');
