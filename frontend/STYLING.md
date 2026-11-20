# Changing the appearance

This file explains where to change frontend colors, fonts, padding, layout, and responsive behavior: tokens in
`src/styles.css` and each page's CSS files. For frontend startup instructions, see the [main README](../README.md).

The theme follows local reference cards: cream paper, black ink, double borders, rounded corners, and soft blue
and peach accents. References in `communicationfolder` are ignored by Git and are not included as public assets.

Start with **src/styles.css**, in the DESIGN TOKENS and MEJA KAYU (Wooden Desk) sections:

| Variable | Usage |
| --- | --- |
| --color-bg / --color-text | Base page and text colors |
| --color-gold | Focus and text-selection accent |
| --font-body / --font-display / --font-hand | Body, heading, and handwriting fonts |
| --desk-text | Text on the wooden desk |
| --desk-chip-bg / --desk-chip-line | Desk control backgrounds and borders |
| --paper-ink / --paper-label | Text and label colors on paper |
| --radius-control / --shadow-control | Shared control corner radius and shadow |

Padding, column gaps, and page widths are defined in each page's stylesheet.

All pages use wooden scrollbar styling (`::-webkit-scrollbar` at the end of **src/styles.css**). Chromium ignores
this styling on elements with `scrollbar-width` or `scrollbar-color`, so do not set either property in components.
Firefox receives wooden colors through the `@supports not selector(::-webkit-scrollbar)` block.

Fraunces (headings) and Patrick Hand (handwriting) are self-hosted in `public/assets/fonts` (OFL licenses in the same
folder) and registered with `@font-face` at the start of **src/styles.css**, so they work without internet access
or third-party services.

Each page has separate HTML and CSS files in `src/app/features/`. Authentication currently uses `auth.html` and
`auth.scss` from Kimberly's design: a wooden desk, registration paper, and a login binder. Assets are in
`public/assets/`. Adjust `--em`, `.register-sheet`/`.login-journal` padding, and the 899px breakpoint for desktop/mobile
proportions: below 900px, the binder becomes two sheets of paper side by side; on phones (<= 640px), they stack.
Google uses the official GIS button. Main and Lobby templates have no inline styles. CSS uses multiline formatting,
with responsive sections at the bottom of each file.

The **game** page uses the login page's visual language (wooden desk, 9-slice `register-paper.png`, `btn-wood.png`
boards, wood/leather buttons, Fraunces and Patrick Hand fonts). It always fits one screen (100dvh) without page
scrolling; only panel contents scroll. Its styles are split across seven files because of the component stylesheet
budget in `angular.json` (12 kB warning, 16 kB error per file). The `Game` component's `styleUrls` order is:

| File | Contents |
| --- | --- |
| `game.css` | `--pad`/`--game-gap` tokens, paper, boards, buttons, HUD, left panel, role cards, `.sr-only` |
| `game-table.css` | Suspect board, player cards, vote effects, action tray, chat, phone tabs |
| `game-cards.css` | Player-card markers: Intip (Peek) results, Jaga (Guard) aura, GAG labels, *Disandera* (Hostage) and *Gagal* (Failed) stamps, bot-stage letters |
| `game-screens.css` | Phase transitions (including the `[data-phase='start']` opening curtain), `.splash`, `.reveal-nudge` card-reveal prompt, `.chat-jump` new-message button, `.final-count` five-second countdown, composition chips, teammate markers |
| `game-preparation.css` | Three preparation-screen cards (`.prep-*`) |
| `game-end.css` | `.end-stage` winner announcement, `.survey` questionnaire, rules modal, `.loading-card` and its error message |
| `game-motion.css` | Animations, responsive rules, `prefers-reduced-motion` (loaded last to override base rules) |

Vote heat is controlled by `--heat` (0–1) on each card; `Game.tableColumns` selects the number of table columns from
the board size. Player characters and label colors follow seat order, not roles. Room role composition
(`snapshot.composition`) appears as `.composition`/`.comp-chip` chips (base styles in `game-screens.css`) on the
preparation screen and along the top edge of the board (`.felt-composition`, with space reserved through
`.table-felt.has-composition` padding; icons are omitted on narrow tables). In rooms with multiple Hitmen, the Hitman
chip at the table edge shows "remaining/total" from `snapshot.hitman_remaining` and receives the red
`.comp-chip.reduced` class after a Hitman is eliminated. Screen readers receive the `.sr-only` text
"Hitman tersisa x dari n" (x of n Hitmen remaining). Teammate markers are rendered only for players who receive their
teammate list from the server: `.ally-tag` ("◆ Rekan", Teammate) on Syndicate teammate cards (for Hitmen) or Spy teammate
cards (for Spies in rooms with ≥ 2 Spies), and `.ally-pick` on cards selected by teammates at night ("◆ Incaran", Target,
for Hostage; "◆ Dijaga", Guarded, for Guard). Both are styled in `game-screens.css`.

At the 1099px breakpoint: table + chat with Meja/Kartu (Table/Cards) tabs (the HUD account box shows only the avatar).
At 899px: the preparation screen scrolls and its table bar stacks. At 759px: one panel per tab (Meja/Chat/Kartu,
Table/Chat/Cards), with an icon-only Keluar (Leave) button. Phone landscape mode (height <= 500px) uses the same tabs
with the action tray beside the table. Changes to these game files do not affect the login or main page.

**Shared desk controls** (end of `src/styles.css`, used by Main, Room, and the game HUD): `--desk-*`, `--paper-*`,
`--danger`, and `--radius-control` tokens; `.desk-chip` (dark buttons on wood, such as "Buka panduan", Open Guide),
`.danger-button` (Leave room / Keluar), `.desk-brand` (wooden nameplate), and `.stamp-label` (stamp labels on paper,
sized with `--stamp-size`). The account box (`core/profile-menu.ts`) uses the same tokens; its parent can set
`--profile-name-max` and `--profile-name-display: none` (avatar only).

**Main and Room** use the same leather binder (`main-page.css`, `lobby.css`; Main's case-file guide is styled in
`main-page-case-file.css`). On phones (<= 640px), the binder becomes two stacked sheets of paper
(`main-page-responsive.css`, `lobby-responsive.css`), and the page can scroll vertically. Phone landscape mode
(height <= 480px) uses the same sheets, arranged side by side.

**Initial loading screen:** `#boot-loader` markup is in `src/index.html` (outside `app-root`, so it appears on first
paint), with styles in `styles.css`. `core/boot-loader.ts` removes it after the first page, fonts, and Main's critical
images (`MAIN_CRITICAL_IMAGES` in `core/asset-preloader.ts`) are ready and one magnifying-glass sweep has finished
(`BOOT_LOADER_SCAN_MS`, 2.4 seconds). The timeout is `BOOT_LOADER_MAX_WAIT_MS` (4 seconds), allowing the application
to open even on slow networks. After login, `BootLoader.bukaSesudahLogin` displays the same screen again, opens Main
behind it, and fades it out only once Main has finished rendering: its critical images, every `<img>` on the page
(role cards, skins, props), and fonts are ready and painted. The timeout is `LOGIN_LOADER_MAX_WAIT_MS` (8 seconds).
Large images in `public/assets` have been resized to match their display sizes; keep new assets close to the size
at which they will be displayed.

To check changes, run this from the repository root while the frontend container is running:

```sh
docker compose exec -T frontend npm run build
```

Do not edit `dist`: it is deployment build output, not the styling source. Setup, application startup, and testing
instructions are centralized in the [main README](../README.md).
