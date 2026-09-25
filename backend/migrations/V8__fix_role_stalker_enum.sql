-- Fix role ENUM: 'detective' is not used by the codebase.
-- All game logic references 'stalker' (Hitman, Spy, Stalker + civilians).
-- 'detective' exists only as a legacy/typo in the original schema.

USE shadow_heist;

-- First, verify current ENUM values (safeguard)
-- SELECT COLUMN_TYPE FROM INFORMATION_SCHEMA.COLUMNS
--   WHERE TABLE_SCHEMA = 'shadow_heist' AND TABLE_NAME = 'players' AND COLUMN_NAME = 'role';

-- Change ENUM to replace 'detective' with 'stalker'
ALTER TABLE players
MODIFY COLUMN role ENUM('civilian', 'hitman', 'spy', 'stalker')
  NULL DEFAULT NULL;

-- Verify the change
-- SELECT DISTINCT role FROM players;

INSERT INTO schema_migrations (version) VALUES ('V8__fix_role_stalker_enum');
