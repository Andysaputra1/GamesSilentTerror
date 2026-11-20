# MySQL Migrations

This document covers the database schema SQL directory: when these files run, what each migration contains, and
how to add a new migration. Commands for applying migrations on the production server are in
[backend/deployment/README.md](../deployment/README.md#applying-migrations-to-an-existing-database).

## When migrations run

- This directory is used both locally **and** on Azure. Compose mounts it at `/docker-entrypoint-initdb.d`, and
  the MySQL image runs all files in order **only when the database volume is first initialized**.
- Databases that already contain data **do not** run new files automatically. The backend does not run migrations
  on startup either. Back up first, then apply unrecorded files in version order using a MySQL client or the
  phpMyAdmin Import menu. Do not rerun all SQL without inspecting the database first.
- Do not use `docker compose down -v` to "rerun migrations": it deletes both the database volume **and** Ollama
  models. Plain `docker compose down` preserves the data.
- This directory does not create any accounts. Create accounts through registration, Google login, the panel's
  Manajemen user (User Management) menu, or `scripts/create_user.py`.

## Migration list

Filenames use two-digit numbers so MySQL runs them in order on an empty volume (otherwise, `V10` runs before
`V1`). Versions recorded in `schema_migrations` are defined inside each file. Older files retain version names
without a leading zero, such as `V5__chat_history`, to match existing databases.

| File | Recorded version | Contents |
| --- | --- | --- |
| `V01__initial_schema.sql` | `V1__initial_schema` | `schema_migrations`, `game_sessions`, `players`, `chat_messages`, `ai_analyses` |
| `V02__add_authentication.sql` | `V2__add_authentication` | `user_accounts`, `auth_sessions` |
| `V04__account_identities.sql` | `V4__account_identities` | `account_identities`: email and Google `sub` with unique constraints and an account foreign key. Existing accounts can still log in with a username |
| `V05__chat_history.sql` | `V5__chat_history` | History columns in `chat_messages` (`sender_kind`, `match_id`, round, phase, …). Older messages are marked `legacy` |
| `V06__admin_panel.sql` | `V6__admin_panel` | `panel_configuration`, `panel_sessions`, `checker_traces` |
| `V07__add_skin_preference.sql` | `V7__add_skin_preference` | `user_accounts.skin_id` column (default `dexter`) |
| `V07__survey_and_npc.sql` | `V7__survey_and_npc` | `survey_questions`, `survey_responses` (one submission per account per match, with a question snapshot), `match_bots` (each bot's method and persona). Six initial questions are inserted with `INSERT IGNORE` |
| `V08__fix_role_stalker_enum.sql` | `V8__fix_role_stalker_enum` | The role enum in `players` uses `stalker` instead of `detective` |
| `V09__chat_nlu.sql` | `V9__chat_nlu` | `chat_messages.nlu` column: IndoBERT's interpretation of each message for Riwayat chat (Chat History) |
| `V10__match_participants.sql` | `V10__match_participants` | `match_participants`: human participants in each completed match, allowing surveys to be submitted at any later time |
| `V11__survey_player_feedback.sql` | `V11__survey_player_feedback` | Five gameplay experience survey questions; no table structure changes |
| `V12__survey_formal.sql` | `V12__survey_formal` | Formal research survey: eleven older questions replaced with ten new questions, and survey reminders limited to matches from November 13, 2026 onward; no table structure changes |

V03 no longer exists: it previously contained demo accounts removed on October 26, 2026. The resulting schema has
15 tables, including `schema_migrations`. Backend usage of each table is described in
[backend/deployment/README.md](../deployment/README.md#table-audit).

`/ready` checks V5, V6, and the latest migration (V12) through `MIGRASI_WAJIB` in
`app/services/panel_service.py`. Missing versions appear in `migrasi_kurang`, and `/ready` returns 503.
Because migrations are applied in order, a recorded latest version implies earlier files have also run.
If an intermediate file was skipped, `/ready` can still pass while the affected feature fails: without V07,
`skin_id` and survey tables are missing (login may fail with 503); without V08, Stalker participants cannot be
archived; without V09, Chat History cannot load; without V10, participant archives cannot be saved, so surveys
after leaving a room can only be submitted for 30 minutes using backend memory; without V11, older survey
questions remain visible.

### V11 notes

V11 adds five questions: gameplay experience, suggestions/impressions/comments, enjoyment with NPC bots (1–5),
expectations for NPC bots, and enjoyment of individual play (1–5). NPC bot expectations are optional, with choices
`Lebih cepat` (Faster), `Lebih berempati` (More Empathetic), and `Lainnya` (Other); the other four questions are
required. For `choice` questions, an option named `Lainnya` opens a free-text field, stored as
`Lainnya: <answer>`.

All five questions are appended at the bottom: their positions are the largest existing position plus
10, 20, …, 50 (70–110 on a new database), matching new questions added through the panel. Subsequent ordering is
managed in Survei (Survey) using the ⋮⋮ drag handle or ▲▼ buttons, which rewrite positions as 10, 20, 30, ….
Unique question codes prevent duplicates if the file is rerun. Deploy an application version that supports
`Lainnya` free-text answers together with this migration; restarting the backend alone does not add questions.

### V12 notes

V12 replaces the V07 and V11 questions with ten formal research questions. Eight are statements rated on a
1–5 scale (`Sangat tidak setuju` = Strongly Disagree through `Sangat setuju` = Strongly Agree), each measuring
one aspect of the bots. The statements below are English translations of the Indonesian survey text:

| Code | Statement | Measures |
| --- | --- | --- |
| `kesenangan_bermain` | Playing Silent Terror with NPC bots is an enjoyable experience. | Gameplay experience |
| `kemiripan_manusia` | NPC bots behave like human players. | Similarity to humans |
| `pemahaman_pesan` | NPC bots understand the meaning of the messages I send during discussions. | NLU (IndoBERT) |
| `kewajaran_bahasa` | NPC bot messages use natural language that fits the discussion. | NLG |
| `ketepatan_keputusan` | NPC bots' accusations, defenses, and voting choices make sense given the events in the game. | Fuzzy logic |
| `kesesuaian_peran` | NPC bots' actions are consistent with their assigned roles. | Fuzzy logic by role |
| `tingkat_tantangan` | NPC bots provide an appropriate level of challenge, both as opponents and as teammates. | Balance |
| `kecepatan_respons` | NPC bots respond to messages and game events quickly enough. | Response time |

The other two questions are optional. `aspek_perbaikan` is a multiple-choice question about the bot aspect most
in need of improvement, with a `Lainnya` (Other) option for free text. `saran_masukan` is a free-text field for
impressions, suggestions, or feedback.

Older questions with no answers are deleted. Those with answers are only deactivated because the
`survey_responses` foreign key preserves those answers. Older responses can be cleared through the Survei menu.

V12 also deletes `match_participants` archives for matches completed before November 13, 2026 at 00:00 WIB
(Western Indonesian Time). That table is used only for surveys, so Main page reminders and survey submissions
apply only to matches from that day onward. Back up the database before running V12 on the server.

## Rerunning older migrations

Older migration files are not changed after being applied in production, so rerunning them is not always safe:

- **Do not rerun V07 (`V07__survey_and_npc.sql`) or V11 after V12.** Both insert older survey questions with
  `INSERT IGNORE`. V12 deletes unanswered older questions, so rerunning V07 or V11 restores them as active
  questions alongside the formal V12 questions.
- **V05 through V09 are not designed to run twice.** `ADD COLUMN`, `ADD CONSTRAINT`, and version-marker
  `INSERT` statements without `IGNORE` stop with an error because the column, constraint, or version already
  exists. The error itself does not damage data, but do not force execution with `mysql --force`, which continues
  running statements after the error.

## Adding a migration

1. Create a file with the next two-digit number. The current latest version is V12, so the next file could be
   `V13__short_name.sql`.
2. Prefer additive changes (`CREATE TABLE IF NOT EXISTS`, `ADD COLUMN`, `INSERT IGNORE`). If a migration must
   delete or deactivate data, as V12 does, explain why in the file's opening comments and the migration notes
   below the table, and remind readers to back up the database first.
3. End with `INSERT IGNORE INTO schema_migrations (version) VALUES ('V13__short_name');`.
4. Test on an empty database (new volume) and a copy of an existing database.
5. Add the file to the table above and its command to the migration table in
   [backend/deployment/README.md](../deployment/README.md#applying-migrations-to-an-existing-database).
6. Replace the latest migration in `MIGRASI_WAJIB` (`app/services/panel_service.py`) with the new version so
   `/ready` passes only after that migration is applied. The `test_required_migrations_include_latest_file` test
   fails if this step is missed.
7. Remind users that existing local and production databases must apply the file manually. On Azure, run it after
   the [`mysqldump` backup](../deployment/README.md#database-backups) and before starting the new backend version;
   otherwise, `/ready` returns 503 and the backend container is marked unhealthy.

MySQL `ALTER TABLE` cannot be rolled back together with the migration-marker `INSERT`. If SQL fails partway
through, inspect the column structure before rerunning it.
