# Silent Terror: game rules and bot behavior

This file is the reference for game rules, NPC bot behavior, and role composition balance. Code locations are
explained in [CODE_GUIDE.md](CODE_GUIDE.md); setup instructions are in [README.md](README.md).

Silent Terror is a multiplayer web-based social deduction game with asymmetric hidden roles. It focuses on
deduction through conversation, alibis, and voting. There is no economy, item purchasing, or ransom. These rules
follow the original GDD with several changes (see [Changes from the original GDD](#changes-from-the-original-gdd)).

## Terminology

| Term | Meaning |
| --- | --- |
| Townspeople (Warga) | The Spy, Stalker, and Civilian team |
| Syndicate | The Hitman team |
| Hostage | A nighttime hostage-taking action by the Syndicate. The victim remains alive but loses all actions |
| Gag Order (Gag) | Silences one player's public chat during the day |
| Guard | Protects one player from Hostage that night (Spy) |
| Peek | Reveals one player's actual role privately (Stalker) |
| Tribunal | The voting phase for executing one suspect |
| Snapshot | Match data sent by the server for one player; other players' private information is excluded |

## Changes from the original GDD

| Since | Change |
| --- | --- |
| Initial version | Small modes for 4 and 5 players; phase durations depend on participant count |
| October 23, 2026 | Round order: day → Tribunal → night (no Tribunal in round 1). Hostage victims lose all actions, including night skills |
| October 26, 2026 | Every Hitman receives the team's Hostage result each night (success, or failure because of Guard) |
| November 1, 2026 | Hostage victims are announced to all players at the end of the night, and their markers remain until the match ends |
| November 3, 2026 | Guard may target the same player on consecutive nights; a Tribunal tie adds time once; Spies know each other in rooms with ≥ 2 Spies; Hitmen and Spies have nighttime team chat in rooms that started with ≥ 2 players of their role |
| November 17, 2026 | Public chat is limited to one message per 2 seconds and 5 messages per 20 seconds per player; abandoned rooms are removed automatically |

## Rooms and roles

- **4–10 participants**, mixing humans and NPCs. The host chooses the room capacity; the game can start with at
  least four participants.
- **No round limit.** Play continues until one team wins.
- Role composition follows participant count (`KOMPOSISI_PERAN` in `match_engine.py`). There may be multiple
  Hitmen and Spies, always one Stalker, and Civilians fill the remaining seats. The server randomizes roles for
  humans and NPCs. Everyone knows each role's count (`composition` in the snapshot); the holders remain secret.

| Participants | Hitman | Spy | Stalker | Civilian | Town win rate (Fuzzy only, 200 games, 6 steps per phase, Nov 7, 2026) | Average rounds |
| --- | --- | --- | --- | --- | --- | --- |
| 4 | 1 | 1 | 1 | 1 | 47.0% ± 6.9 | 2.00 |
| 5 | 1 | 1 | 1 | 2 | 47.0% ± 6.9 | 2.39 |
| 6 | 1 | 1 | 1 | 3 | 46.0% ± 6.9 | 3.23 |
| 7 | 2 | 2 | 1 | 2 | 60.5% ± 6.8 (1000 games: 55.1% ± 3.1) | 3.88 |
| 8 | 2 | 2 | 1 | 3 | 52.5% ± 6.9 | 4.82 |
| 9 | 2 | 2 | 1 | 4 | 56.0% ± 6.9 | 6.05 |
| 10 | 2 | 2 | 1 | 5 | 59.5% ± 6.8 | 7.23 |

The measurement method and history are in [Composition balance](#composition-balance).

- The host adds NPCs individually (**+ Tambah bot**, Add Bot, one bot per click) and removes them the same way,
  up to 5 bots per room. The bot count is the host's selection, capped by empty seats (capacity minus humans).
  A human joining a full room replaces the last bot. The roster locks after starting; existing members may
  reconnect. Players who leave during a match cannot rejoin that match.
- One account occupies one room. Leave the lobby before switching rooms. A completed room is released
  automatically when a player creates or joins another room; its survey can still be submitted.
- The server removes rooms abandoned without using Leave (for example, by closing a tab): lobbies not opened by
  a member for one hour, and completed rooms idle for 30 minutes. Active matches are never removed. The server
  supports at most 500 rooms at once.
- Failed room-code joins are limited to 10 per account and 30 per IP per minute. Missing codes and rooms belonging
  to other people return the same message, "Ruangan tidak ditemukan atau kamu bukan anggotanya." (Room not found
  or you are not a member), preventing repeated code guessing.
- During an active match, opening a new tab, another application page, or logging in again returns the account to
  `/game` based on backend data. The account cannot create or join another match until the current one ends.
  Logging out revokes the session without stopping the match; logging back in restores membership.

## Round phases

Round order: **day → Tribunal → night**. Round 1 skips Tribunal (day goes directly to night), since there are no
night events to discuss before voting. The first Tribunal occurs in round 2, always immediately after day discussion.

| Phase | Interaction and resolution |
| --- | --- |
| Day | Public discussion. Hitmen can use Gag Order instantly. |
| Tribunal | From round 2 onward. Eligible players choose a suspect; votes may be canceled and recast until time runs out. A sole vote leader is executed. In rooms with ≥ 2 Hitmen, the remaining living Hitman count is announced after execution. |
| Night | The screen dims and public chat locks (team chat: see [Abilities and statuses](#abilities-and-statuses)). Hostage, Guard, and Peek are selected privately and resolved together when the timer expires; Guard resolves before Hostage. Night results appear on the morning curtain and become visible from the next round's day phase. |

**Tribunal ties.** If ≥ 2 candidates lead when time expires, the Tribunal gets **one** extension: 30 seconds
(10 in fast mode). A note and the public `tribunal_extra` flag announce it. Existing votes remain; humans can
cancel and recast them, including for candidates outside the tie. If the tie remains after the extension, nobody
is executed and play proceeds to night. No votes at all is not a tie: there is no extension or execution.

**The public night recap** names only Hostage victims: "Malam selesai. X disandera: …" (Night ended. X taken
hostage: …), or "Malam selesai. Malam ini tidak ada yang disandera." (Night ended. Nobody was taken hostage
tonight) if Guard blocked Hostage or the Syndicate made no selection. Failed Hostage, Guard, and Peek targets
are not announced.

### Phase durations

Durations depend on the initial participant count N (humans + NPCs) and remain fixed throughout the match.
A tie extension only moves that Tribunal's `deadline`. The server timer continues even when tabs are closed.

| Mode | Day | Tribunal | Night |
| --- | --- | --- | --- |
| Standard | 20N seconds | 7.5N rounded up, + 30 seconds | 5N seconds |
| Fast | 10N/3 rounded up | 2.5N rounded up | 2.5N rounded up |

The extra 30 seconds in standard Tribunal gives players time to consider and lock votes after discussion.
Standard examples (day/Tribunal/night): 4 players 80/60/20 seconds, 6 players 120/75/30 seconds, 10 players
200/105/50 seconds. Fast mode with 6 players: 20/15/15 seconds.

Public chat is available during day and Tribunal for players who may still speak. Each player can send at most
one message per 2 seconds and 5 messages per 20 seconds. Messages sent too quickly are not delivered; the sender
sees "Chat terlalu cepat. Tunggu N detik lalu kirim lagi." (Chat too fast. Wait N seconds and send again), and
the text returns to the input box for resubmission. This is because IndoBERT takes about 9 seconds to read each
message on a single thread shared with bot steps across all rooms. Nighttime team chat uses a separate route
(without the database or IndoBERT) and has no such rate limit.

### Skipping discussion

During the day, **Setuju skip diskusi** (Agree to Skip Discussion) advances to the next phase (night in round 1,
Tribunal afterward) once **all living humans** agree. Bots do not count. Gagged players and Hostage victims may
still agree because this is neither chat nor voting. Agreement cannot be withdrawn that round, and offline
players are not assumed to agree. Only the agreement count is public; otherwise, the normal timer applies.

## Abilities and statuses

| Role | Team | Abilities |
| --- | --- | --- |
| Hitman | Syndicate | Hitmen know each other (`me.allies`). The Syndicate takes **one** player hostage per night: each Hitman chooses, and the most selected target wins (`me.ally_actions` shows teammates' choices). A human/bot tie favors the human choice; ties among humans or among bots use the earliest choice. Gag Order silences one player during the day, **once for the entire Syndicate**, with a full-round cooldown (round 1, then round 3). Hostage and Gag cannot target teammates; voting for them is allowed. After each night, every Hitman knows the team's Hostage result (`me.syndicate_hostages`): success, or failure because Guard protected the target. |
| Spy | Town | Guard one player, including yourself, and the same target may be chosen on consecutive nights. Guard prevents Hostage that night but does not free existing victims. In rooms starting with ≥ 2 Spies, Spies know each other (`me.spy_allies`) and see teammates' Guard choices that night (`me.spy_actions`). |
| Stalker | Town | Peek at one player's actual role; the private result arrives after night ends. Available every other round: round 1, then round 3. |
| Civilian | Town | No night skill; observes, debates, and votes. |

**Team chat.** Available only at night to living Hitmen in rooms starting with ≥ 2 Hitmen, and living Spies who
are not hostages in rooms starting with ≥ 2 Spies. Hitman and Spy channels are separate and invisible to each
other. Messages use `POST /api/rooms/{code}/team-chat` (match, round, and phase token; 1–1000 characters), are
stored in match memory (last 100 messages per team), and are read through `me.team_messages` by the sender and
eligible teammates. Eliminated or hostage teammates no longer receive them. Gag does not affect team chat.
Bots use team chat only when a living human teammate is not held hostage; bots do not chat among themselves.

**Hostage.** The victim remains alive on the roster but permanently loses **all actions**: chat, voting, and
night skills. This is stricter than the original GDD, which retained night skills. The engine rejects their
actions, snapshot `can_act` is always `false`, and hostage bots also stop acting. Victims remain on the town team.

- At night end, victims are **announced to all players**: the public roster includes `hostage: true` and
  `hostage_round` (the night they were captured), and a *Disandera* (Hostage) stamp stays on their card until
  the match ends.
- Existing hostages cannot be taken hostage or Gagged again (the engine rejects this and the UI disables them
  as targets), avoiding wasted Syndicate nights.
- During the night, only Hitmen see the *Disandera* stamp for their team's victim that night. Guard-protected
  targets remain secret from the town; Hitmen see a *Disandera* stamp marked *GAGAL* (FAILED), fading next day.

**Gag Order.** Restricts only public chat until the next day (including that round's Tribunal, if any). Voting
and night skills remain available, and Gag does not reduce the town's voting strength for win conditions.

**Executed.** Cannot chat, act, or vote; becomes a spectator. Victory or defeat follows the player's team,
including for executed players and hostages.

**Leaving mid-match** (the Leave button, with confirmation) is treated like execution, and victory is checked
immediately. The roster marks the player `left` ("Keluar"), and the note says "X meninggalkan permainan."
(X left the game), with the same suffix as an execution (remaining Hitman count, roles still hidden). Their
votes and night actions are removed; votes and actions targeting them are also removed so others may reselect.
The phase does not wait for them (discussion skipping and preparation readiness are recalculated). The player
returns to the main menu.

**Changing a selection.** One selection per phase; cancel before changing it.

- Tribunal votes: **Batalkan vote** (Cancel Vote), `POST /api/rooms/{code}/cancel-vote`, then select again.
  The vote at the deadline is counted.
- Hostage, Guard, and Peek: **Batalkan Sandera/Jaga/Intip** (Cancel Hostage/Guard/Peek),
  `POST /api/rooms/{code}/cancel-action`, then select again. The selection at night end is resolved.
- Gag Order cannot be canceled because it takes effect immediately: the target is silenced and the team
  cooldown starts upon submission.
- Targets must be alive; only Guard allows self-targeting. Hostage and Gag cannot target existing hostages
  (their status is public). Guard, Peek, and votes may target hostages, although doing so is unhelpful.

## Victory

The backend checks victory after night resolution, after Tribunal, and when a player leaves:

1. **Town wins** when **all** Hitmen have been executed (or left).
2. **Syndicate wins**, provided a Hitman is still alive, when living townspeople who are not hostages
   **do not outnumber living Hitmen**. Executed townspeople and hostages do not count; Gagged townspeople do.

Matches cannot end in a draw. Without a winner, play continues to the next round. Votes still tied after the
extension, or no votes, execute nobody. Executed players' roles remain hidden until the end.

Six-player example (one Hitman): three of five townspeople are hostages, two remain free → continue. One more
becomes a hostage or is executed → Hitman wins. A successful Guard keeps two townspeople free → continue.
The Hitman is executed in any Tribunal → town wins.

Ten-player example (two Hitmen): one Hitman is executed → continue and announce "Hitman tersisa: 1"
(Hitmen remaining: 1). With one Hitman left, Syndicate wins when only one free townsperson remains;
town wins as soon as the last Hitman is executed.

**Hitman count announcements (only rooms starting with ≥ 2 Hitmen).** After each Tribunal execution, the engine
writes "Tribunal mengeksekusi X. Hitman tersisa: n. Role tetap dirahasiakan sampai permainan selesai."
(Tribunal executed X. Hitmen remaining: n. Roles remain secret until the game ends). Every snapshot (all
players, all phases including preparation and completion) includes `hitman_remaining`, the living Hitman count.
Single-Hitman rooms have `hitman_remaining: null` and unchanged execution text. In single-Hitman rooms, the
town already knows whether the executed player was a Hitman because the game ends or continues. This announcement
provides equivalent information in multi-Hitman rooms without revealing the victim's role. Without it, a two-Hitman
Syndicate is too strong (see [Measurement history](#measurement-history)). The count changes only through
execution or leaving.

The results screen shows the winning team, the reason, the current account's victory or defeat, counts of living,
hostage, executed, and voting-eligible townspeople, and every participant's role and final status.

## Hidden information

- Active snapshots contain only the requesting account's role, status, action selections, and Peek results.
  Other players' roster entries include only names and alive/dead status, plus `left` for those who left and
  `hostage`/`hostage_round` for Hostage victims (both already announced).
- Gag, Guard, Peek, and failed Hostage targets are not announced. Failed attacks and nights without an attack
  both announce that nobody was taken hostage; only the Syndicate knows which target was Guard-protected.
- Public to everyone: role counts (`composition`) and, in rooms with ≥ 2 Hitmen, the remaining Hitman count
  (`hitman_remaining`).
- Hitman-only: teammates (`me.allies`), teammates' Hostage choices that night (`me.ally_actions`), the team's
  Hostage victim that night (`me.syndicate_target`), each night's Hostage results (`me.syndicate_hostages`),
  this round's Gag targets (`me.ally_gags`), and the shared Gag cooldown (`me.next_gag`). Townspeople always
  receive empty values and `next_gag` 1, so they cannot infer when Gag was used or on whom.
- Spy-only: Spy teammates (`me.spy_allies`) and their Guard choices (`me.spy_actions`); empty in 4–6-player rooms
  and for other roles. These fields are separate from `me.allies`, which bot code treats as Syndicate allies.
- Team messages (`me.team_messages`) are sent only at night to the sender and eligible teammates. They never
  enter `messages`, `events`, chat history, the database, NLU, Checker, panel activity traces, other players'
  snapshots, or the results screen, and do not use public chat sequence numbers.
- Gagged players know only their own status (`me.gagged`); Hostage status is public.
- Submitted votes are visible during Tribunal, including voter names per target, without a list of eligible
  voters. Silence may reflect strategy, Gag, or being offline.
- Bot brain methods are hidden from players but visible in the administrator panel. The lobby and preparation
  screen still show bot counts, so this version **is not yet a fully blinded Turing Test experiment protocol**.
  A blinded experiment requires hidden lobby identities, recruitment procedures, and separate evaluation.

## Match preparation and presentation

After the host clicks Start, all participants enter a **preparation screen** with three cards: their private
role (character and accessories as on Main), example actions, and the victory objective. Participant characters
and AI progress appear below.

- Round 1 has not begun, and the minimum reading time is **40 seconds**. Revealing the role or clicking Ready
  does not shorten the shared countdown.
- With **10 seconds** left, players who have not revealed their role receive a reminder; in the **last 5 seconds**,
  the card opens automatically. The first reveal still gives a local 3-second reading pause, including when
  reconnecting after the countdown.
- If AI becomes ready near the end of reading time, the countdown allows up to 10 extra seconds, without
  exceeding the **90-second** wait limit. At that limit, the game starts using engine fallback actions.
  Rooms without bots still wait at least 40 seconds.
- At round 1 start, a transition curtain covers the fading splash and appearing table; reduced motion disables
  the animation.

During play, chat scrolls to the latest message if the player is at the bottom or has just sent a message.
Players reading older messages are not pulled down; a "↓ n pesan baru" (n new messages) button appears instead.
In the last 5 seconds of day, night, and Tribunal, a large central countdown appears without intercepting clicks,
so chat, votes, and actions remain usable.

## Match end and survey

The results screen congratulates the individual winner or winning team, lists winners with their roles, and
shows final statistics. A **survey** appears below.

- Administrators configure questions, answer types (stars, numeric scales, multiple choice, text), scale ranges,
  and endpoint meanings in the **Survei** (Survey) panel, not in the frontend. Since November 13, 2026, the default
  set contains ten formal research questions from migration V12; their list and the bot aspects measured are in
  [V12 notes](backend/migrations/README.md#v12-notes).
- A multiple-choice option named `Lainnya` (Other) opens a free-text field, stored as `Lainnya: <answer>`.
- Optional multiple-choice, star, and scale answers can be cleared with "Kosongkan pilihan" (Clear Selection).
  While Submit is disabled, incomplete question numbers appear above it. Entered answers remain when players
  open "Lihat meja" (View Table) or "← Pengumuman" (Announcement), then return to the questionnaire.
- New questions are appended at the bottom. Drag the ⋮⋮ handle or use ▲▼ (Alt+↑/↓) to reorder them; the order is
  saved immediately through `PUT /api/panel/survey/questions/order` and used by the player form and CSV exports.
- Each human account submits once per match; simultaneous duplicate submissions also return "already submitted".
  Submissions with no answers are rejected (400), leaving the survey available. Responses store a snapshot of
  each question at submission time plus the player's role, team, and outcome.
- Surveys are tied to usernames. Usernames still present in participant archives or responses cannot be reused
  by another account through registration, renaming, or admin creation, even after the original account is deleted.
- Human participants of every completed match are archived in `match_participants`, allowing submissions after
  leaving a room, room cleanup, or server restart. If archiving fails, the backend retains participants in memory
  for 30 minutes. V12 removes archives for matches completed before November 13, 2026, so those older matches
  can no longer receive surveys.
- Until a survey is completed, Main shows "Mohon isi survei untuk pertandingan di ruangan …" (Please complete
  the survey for the match in room …) above the binder, one scrollable row per match. X hides it only until Main
  is reopened. Form text, thanks, and reminders use formal Indonesian ("Anda").
- The Survey panel displays:
  - One submission per person: one submission means one account answering for one match. For accounts answering
    across matches, only the latest submission is shown and counted (latest timestamp; highest `match_id` breaks
    ties). Older submissions remain in the database.
  - Respondent and match counts, plus "N kiriman lama tidak ditampilkan" (N older submissions not shown), if any.
  - Answer-distribution charts for each question, using each person's latest submission.
  - A respondent list, one row per person, newest first, with the account's display name (username if deleted),
    room, role, team, outcome, and answered-question count. Clicking a name opens every answer in that submission,
    the match's bots, username, and match number. Data comes from `GET /api/panel/survey/respondents`
    (`total_people`, `total_matches`, and `total_submissions_all` counts all submissions, including older ones).
    The average-by-bot-method table was removed because the thesis no longer compares methods.
- The Survey panel can also permanently delete all responses and participant archives (the administrator types
  BERSIHKAN), then delete questions with no responses. CSV exports are explained in
  [README.md](README.md#administrator-panel).

## NPC: bot brain

Each NPC bot has **its own memory and persona**; memory is not shared between bots. Bots step on a timer without
waiting for human messages, and all use the fuzzy brain. Each bot's method and persona are recorded in `match_bots`
for survey analysis. Code locations are in [CODE_GUIDE.md](CODE_GUIDE.md#bot-brain-in-code).

### Three stages

1. **NLU (IndoBERT).** All bots share the model, with results cached once per message. Model 1 reads intent
   (`offend`, `defend`, `neutral`); Model 2 reads targets per player using 12 previous messages as context.
   Because usernames are arbitrary (for example, `tester`, `andy123`), player names are replaced with names
   familiar to the model before intent inference; otherwise short accusations such as "curiga sama tester"
   (I suspect tester) are read as neutral. Named players become targets for neutral messages. Without model
   folders, the brain cannot load: bots do not chat and only use engine fallback actions.
2. **Reasoning (Mamdani fuzzy logic).** Public evidence per player is computed from bot memory. [FUZZY 1]
   evaluates players: suspicion from the town perspective, threats and scapegoats for Hitmen. [FUZZY 2] selects
   actions per session: Tribunal (vote), Discussion (chat), and Night Actions (Gag, Hostage, Guard, Peek).
   It produces chat plans, votes, and secret actions.
   - Hitman bots read team Hostage results from the server (`me.syndicate_hostages`), so they know successful
     victims and Spy-protected targets; if absent, they use public roster Hostage announcements.
   - All bots read Hostage victims from the public roster (`players[].hostage`, `hostage_round`). Victims are
     confirmed townspeople: suspicion 0, never voted for, Guarded, Peeked, or captured again, and not defended
     in chat because their status is already public. Silence without an announcement does not imply Hostage.
   - Hitman bots abandon a target after two failed Hostage attempts throughout the match (likely repeated Spy
     protection), provided another target exists. Without this rule, some all-bot matches never end.
   - Bots reread all Tribunal votes on every step and lock them into memory only at the phase change, so
     canceled votes are not treated as evidence.
3. **NLG (dialogue writer).** Plans become dialogue through an LLM writer **priority chain**, then templates:
   - Routes: OpenRouter (key in Konfigurasi AI) and a custom LLM endpoint (tunnel URL in Konfigurasi AI, such as
     Docker Ollama; detected as Ollama or an OpenAI-compatible server). Order and enabled routes are configured
     in **Otak NPC** (NPC Brain), initially from `NPC_WRITER_ORDER`.
   - OpenRouter model: code default `qwen/qwen3-14b`; production uses `google/gemini-2.5-flash`, selected in Otak NPC.
   - Each route is checked when the brain loads, configuration changes, or **Tes koneksi semua prioritas**
     (Test All Priority Connections) is clicked. OpenRouter checks the key, model, and one short message with the
     same token limit as gameplay, exposing insufficient balance immediately; custom endpoints check their model list.
   - Rejected routes (401/403/402/404) are skipped until rechecked. Temporary failures (429, server errors,
     timeouts) pause the route for 30 seconds, doubling on repeated failure up to 5 minutes.
   - One LLM request is limited to 20 seconds. A second attempt occurs only if the first finishes before
     20 seconds. Writing one sentence is limited to 25 seconds; afterward, a template is used.
   - The writer does not receive the bot's actual role. Each sentence is checked against rules (no admission of
     being a bot or AI, no role/action leaks, target named), then sent immediately; IndoBERT reads it afterward.
     All routes fail or no key → persona-specific template variants. The writing route is recorded in traces
     (`penulis`).
   - Prompts include the triggering chat (accusation, Tribunal vote, or question directed at the bot) and the bot's
     previous sentence, without template examples. Bots therefore respond to actual events and may address their
     accuser or questioner. LLM sentences that barely paraphrase recently heard dialogue (similarity ≥ 0.75)
     are rejected and rewritten.
   - Pre-send IndoBERT rereading was archived on November 4, 2026 because it took longer than the LLM itself
     (median 5.7 seconds, p95 21 seconds); the archive is outside the repository at `../arsip_validasi_nlg_2026-11-04/`.

### Scheduling and speaking turns

- Bots step every `NPC_STEP_SECONDS` (default 3 seconds), slightly staggered per bot.
- Messages addressing a bot (IndoBERT neutral target or an explicit name/address) or accusing it schedule its
  next step immediately, at least 1 second after its previous step. A bot answers a direct question once per
  trigger, still subject to quotas, delays, and speaking-turn limits.
- Votes and secret actions apply as soon as they are decided. Dialogue uses a **speaking floor**: at most 3 bots
  (`LANTAI_MAKS`) per match compose and "type" simultaneously, sending LLM requests in parallel. The floor is
  scoped to the match and phase; a phase change releases old-phase writers. Six writer threads are shared across
  all rooms, so two full rooms can write at once while a third waits. A bot does not write while another is
  writing an identical plan (same intent and target). Plans created before another bot message arrives are
  canceled and reconsidered with the latest chat. Deferred plans and their NLG inputs remain visible in the panel.
  Human chat is never held back.
- If the remaining phase is shorter than one LLM call's limit (20 seconds), a template is used immediately,
  since an LLM answer could arrive after the phase change and be discarded. Otherwise, the LLM wait limit is
  also capped by remaining phase time.
- While writing, a bot's card shows a thinking bubble 🤔 (`players[].thinking`), removed when its sentence appears.
- The lower-left corner of a living bot's card shows the latest step stage (`players[].tahap`): **I**, snapshot
  input received; **L**, logic and dialogue generation in progress; **O**, output/action complete. Failed or
  timed-out steps stay at **L** until the next step. Bots step in every phase regardless of role, so this does
  not reveal roles.
- Bots do not ask another question immediately after someone else asks, become a third voice repeating the same
  accusation or defense in a phase (anti-echo), or repeat a sentence just heard in the room.
- Bots do not wait for humans to speak: one opens discussion. If the room is silent (no chat for ≥ max(15 seconds,
  20% of phase duration), about 24 seconds in a standard six-player day), a bot may restart conversation or
  invite someone who has not spoken. Bots still do not accuse without evidence.
- Decisions apply only if round and phase are unchanged; engine-rejected actions do not alter state. A bot owns
  its phase once its vote/action is accepted or its brain deliberately declines to act (abstention or no available
  action); the engine does not replace that choice with a random action. "Wait" and rejected choices do not
  claim the phase, so engine fallback still fills in at phase end if the next step fails.
- Hostage bots are no longer scheduled because they cannot chat, vote, or act for the rest of the match.
- Matches started while the brain failed to load gain bot brains once reloading succeeds (no sooner than
  60 seconds after failure); until then, bots use engine fallback actions.
- Bot scheduling and panel simulation calculate elapsed phase time through `Match.phase_length()`, so extensions
  do not make phase progress appear to move backward.

### Bot rules at a glance

These rules apply after brain-rework Phases 1–9 (November 2026) and follow the November 3, 2026 game rules.
Details are in the `npc_fuzzy` notebook's per-role strategy section.

- **Day and Tribunal chat.** Bots choose among five actions, each with a type: `bela_diri` and `jawab` (reactive),
  `tuduh`, `bela_orang`, and `tanya_info` (initiative), or `tunggu` (wait). Priority: reveal a Hitman Peek result
  → `bela_diri` → `jawab` → highest-scoring initiative, minimum 40 → probe a suspect as fallback → `tunggu`.
  Initiative quotas are 3 per day and 2 per Tribunal; reactive caps are 8 and 5. Each trigger is answered once,
  and another trigger from the same person waits 12% of phase duration. Bots do not repeat accusations/defenses
  already voiced by two others, except Stalker claims. A bot's own Stalker claim (Hitman or clean Peek result)
  occurs at most once per round: in Tribunal after a daytime claim, it invites/explains a vote or defends without
  mentioning Peek. Peek claims name the actual Peek night; "last night" is used only for the latest night.
- **Role reveals** occur at most once per game, only under pressure (vote share against the bot ≥ 0.3, pressure
  ≥ 0.5, or town close to losing). Spies cite last night's Guard evidence; Stalkers cite Peek results. Otherwise,
  bots defend themselves through persuasion (too early, risk of a wrong vote), pointing to another suspect, or
  ordinary denial. Hitmen claim Civilian, or Spy with a fake Guard when at high risk.
- **Accusations.** Town bots accuse only with evidence: suspicion ≥ 0.40 and a reason beyond "many people accuse
  them". Hitmen attack Gag victims, counter-accuse accusers, or twist public evidence; all eligible accusation
  types are scored and the highest wins. Once per game, when suspected, a Hitman makes a fake Peek claim using
  a possible Stalker night (Peek every other night: 1, 3, 5, ...). Role claims by a proven Hitman (executed or left
  as Hitman, or identified by the bot's Peek) are treated as lies, even after that player's death.
- **Tribunal.** `tanya_info` is only for conflicting claims and probing suspects. Bots may invite voting once
  (switching during extra time, unifying votes, or explaining their vote), except when their vote was forced.
- **Gag** (Hitman, day) is always used. A townsperson with threat ≥ 0.7 is Gagged immediately if no living human
  teammate exists. Before 60% of the day, only townspeople who have spoken and score ≥ 60 are Gagged. After 60%,
  Gag is mandatory.
- **Town votes.** Priority: Hitman Peek result → vote immediately; readiness ≥ 75 → immediately; before halfway
  through Tribunal → wait; readiness ≥ 45 → vote; ≥ 2 votes and suspicion of the leader ≥ 0.35 → follow. When
  town is critical (`warga_terdesak` ≥ 0.75, `PAKSA_VOTE_KRITIS = True`), the bot forces a vote for the highest
  eligible suspect. Equal scores use stable per-bot randomization, skipping players cleared by a claimed
  Stalker. Otherwise, abstain. Town votes never target Hostage victims or confirmed good players.
- **Hitman votes.** Hitmen never open voting. They join votes against a teammate whose execution is inevitable,
  and equalize the strongest rival's vote count when they or their teammate lead. Without pressure, they wait
  until halfway through Tribunal. Without town votes, they abstain; otherwise, they follow an eligible town
  vote leader or select the top scapegoat.
- **Tie extensions.** Bots that already voted reconsider once. Town bots switch only to an eligible target with
  higher suspicion; Hitmen use their own voting rules, including preserving a tie.
- **Night.** Night actions are always used when a target exists. Bots lock their choice 15 seconds (fast mode
  10 seconds) before night ends; humans may change choices until the deadline.
  - **Hostage:** at lock-in, follow a human Hitman who has chosen. Lock-in is the first step after the cutoff
    whose decision reaches the engine, so a timed-out step does not consume it. Otherwise, follow a bot
    teammate who has chosen, or select the townsperson maximizing threat × (1 − 0.5 × accusation history).
    Ties use stable per-bot, per-round randomization.
  - **Guard:** self if the role is revealed and the bot is still under attack this round. Otherwise, protect
    the most threatened player believed good (Spy ally or suspicion < 0.3), avoiding the other Spy's target;
    if none exists, self. Repeated targets are allowed, and Hitman bots do not assume last night's protected
    target is safe to capture tonight. Unlocked bots switch if a human Spy guards the same target; among bots,
    the Spy whose name sorts later switches.
  - **Peek:** choose an unchecked player who is not confirmed good or a Hostage victim, maximizing the `intip`
    system score. If everyone is skipped, Peek any living player.
- **Team chat** (Hitman and Spy) requires a living human teammate who is not a hostage, with at most 3 messages
  per night. Messages explain the bot's chosen target and reason, agreement/disagreement with a teammate, or
  a target switch. LLMs or templates write them without IndoBERT. Team-chat content does not change targets.

### Archived methods

Utility AI and Behavior Tree once alternated with Fuzzy, then were archived on November 3, 2026 outside the repo
at `../arsip_bt_utility_2026-11-03/` (last commit containing both: `2d0e9b9`; restoration instructions are in that
folder's README). Historical `match_bots`, `checker_traces`, and survey data may retain those method values,
and the panel can still display them.

## Composition balance

Target: a 40–60% town win rate for every room size. All figures here come from bot-versus-bot matches, so they
are only indicative for human matches. Composition needs changing in only one place (`KOMPOSISI_PERAN`) if
human-match data indicates otherwise.

### Measurement method

- Script: `backend/tests/simulasi/simulasi_keseimbangan.py` (commands in
  [CODE_GUIDE.md](CODE_GUIDE.md#balance-simulation-and-ab-testing)).
- All seats are bots against the actual engine, with perfect NLU labels, remaining-Hitman announcements enabled,
  6 decision steps per phase (close to runtime, where bots step every `NPC_STEP_SECONDS`), and 200 matches per
  size with fixed seeds.
- Selection rule: if a composition with ≥ 2 Hitmen gives a 40–60% town win rate, choose the one closest to 50%.
  Hitman and Spy counts must not decrease as participant count rises, and 4–6-player rooms retain one Hitman.

### Current figures (November 7, 2026)

The [Rooms and roles](#rooms-and-roles) table was measured on November 7, 2026 using Fuzzy only, after three bot
fixes that day: scoring all eligible Hitman accusation types, using possible nights in Peek claims, and avoiding
repeated Stalker claims within a round. Illegal actions: 0; matches without a winner: 0.

- Compared with November 6 (`be1bf7f`, same seeds), 4–6 and 10 players were unchanged; 7/8/9 players shifted
  +2.5/−1.5/+1.0 percentage points (paired differences).
- **7 players (60.5%) slightly exceeded the target in 200 games**, so the test was rerun with 1000 games (same
  first 200 seeds): 55.1% ± 3.1. Before the fixes: 54.6% ± 3.1 (paired difference +0.5 ± 1.1; 19 games flipped
  to town, 14 to Hitman). Composition was unchanged.
- **10 players (59.5%) remain close to the upper target bound.**
- Before the brain rework (Fuzzy only, `1f11806`), rates were 40.0/65.5/70.0/25.0/28.0/41.0/46.5% for 4–10 players.

### Forced-vote A/B test

`PAKSA_VOTE_KRITIS` enabled versus disabled, Fuzzy only, 200 games per size, 6 steps per phase, identical seeds
for both policies. Measured November 6, 2026 at `4a5e48f`, before Hostage tie-breaking changes and handling claims
by proven Hitmen. Reproduction script: `backend/tests/simulasi/uji_ab_vote.py`.

| Town wins | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| No forced vote | 65.0% | 58.0% | 54.0% | 39.5% | 37.0% | 40.0% | 39.5% |
| Force when critical | 49.5% | 48.0% | 54.5% | 55.5% | 53.5% | 50.5% | 54.0% |

Without forced voting, 4 players exceed 60% and 7–10 players are at or below 40%. With it, every size is at
48–56%. Therefore, **forced voting remains enabled**. The reasoning matches the rules: a critically threatened
town that abstains lets another vote, possibly a Hitman's, decide the execution.

History: the older test (6 players, `PAKSA_VOTE_BUKTI_LEMAH` without a critical-state condition, mixed methods
still present) selected Fuzzy without forced voting (forced → unforced: October 26, 50.5% → 58.5%; November 1,
52.0% → 60.0%).

### Measurement history

Measurements before November 3, 2026 used **mixed methods**: Fuzzy, Utility AI, and Behavior Tree alternated as
bot brains. Entries below are newest first.

- **November 1, 2026** (after announcing Hostage victims to everyone and switching Hitman targets after Hostage
  failed against the same target on two consecutive nights): the same composition yielded
  49.5/65.5/71.0/46.5/43.5/50.0/58.0% for 4–10 players. Composition stayed unchanged: 7–10 players remained at
  40–60%, with no stalled matches. The voting-policy A/B test repeated the same direction (Fuzzy unforced 60.0%
  vs forced 52.0%; Utility AI forced 81.0% vs 30.5%; Behavior Tree forced 97.5% vs 61.5%), so per-method policies
  were unchanged.
- **October 27, 2026** (after Hitman bots stopped opening votes and Utility AI bots adopted forced voting):
  7–10 players all reached 40–60% for the first time: 47.5/42.5/56.5/59.5%; 4–6 players: 47.5/61.5/70.0%.
  Comparisons: 7 players, 1/1/1 64.0% and 2/1/1 36.5%; 8 players, 2/1/1 40.0%; 9 players, 2/1/1 46.0%
  (Spy count decreases, disallowed) and 3/2/1 19.0%; 10 players, 2/1/1 53.0% (Spy count decreases, disallowed),
  3/2/1 27.5%, 3/1/1 27.0%.
- **October 23, 2026** (new rules: day → Tribunal → night, no round-1 Tribunal, Hostage disables all actions,
  Tribunal +30 seconds; 6 steps per phase):
  - **7 players** changed from 1/1/1 (75.0% town wins) to 2 Hitmen + 2 Spies (42.0%); 2/1/1 gave only 26.0%.
  - **8 players** retained 2/2/1 (48.5%; 2/1/1: 42.0%).
  - **9 and 10 players** retained 2/2/1 despite town win rates of 64.5% and 67.0%. The only 40–60% candidate was
    2/1/1 (57.0% and 59.5%), which reduced Spy count, while three Hitmen were too strong (9: 3/2/1 15.0%;
    10: 3/2/1 29.5%, 3/1/1 17.0%).
- **Initial selection** (old order: day → night → Tribunal). If no composition with ≥ 2 Hitmen reached 40–60%,
  that size retained one Hitman.
  - Rejected comparisons: 7 players with two Hitmen + one Spy 26.0%, and two Hitmen + two Spies 37.5% (both below
    40%, so one Hitman remained); two Hitmen + one Spy at 8 and 9 players 37.5% and 39.0%; three Hitmen at
    9 and 10 players 4–16%; at 10 players, two Hitmen + one Spy 46.5% was closer to 50%, but Spy count could not
    drop from two (at 9 players), so two Spies were chosen (57.0%).
  - Without remaining-Hitman announcements, two Hitmen were too strong: town won only 21–32% at 8–10 players.
  - Selection was repeated with 6 decision steps per phase because 9–10-player results were sensitive to step
    count. The table stayed: 8 and 9 players balanced (53.5% and 52.0%). At 10 players, no candidate reached
    40–60% (2/2/1: 64.5%; 2/1/1: 61.5% but Spy count cannot decrease; 3/2/1: 29.0%; 3/1/1: 15.5%), so the
    closest-to-50% composition satisfying the monotonic rule was chosen: 2/2/1, favoring town. Seven players
    deliberately retained one Hitman despite favoring town (71%), because two Hitmen gave only 32–37.5%.
