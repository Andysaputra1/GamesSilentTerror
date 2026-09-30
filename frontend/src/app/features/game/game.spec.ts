import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';

import { Game } from './game';
import { provideHttpClient } from '@angular/common/http';
import { of, Subject, throwError } from 'rxjs';
import { GameService, GameSnapshot } from '../../core/game.service';

// TEST SUITE: kelompok pengujian otomatis, bukan logika yang dijalankan halaman production.
// Callback () => { ... } berisi setup dan skenario yang dipanggil oleh test runner.
describe('Game', () => {
  // INSTANCE TES: component adalah class halaman; fixture membungkus komponen untuk pengujian.
  let component: Game;
  let fixture: ComponentFixture<Game>;

  // SETUP CALLBACK: siapkan lingkungan/instance baru sebelum setiap skenario tes.
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [Game],
      providers: [provideRouter([]), provideHttpClient()],
    }).compileComponents();
    vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);

    fixture = TestBed.createComponent(Game);
    component = fixture.componentInstance;
    await fixture.whenStable();
  });

  // TES: pastikan komponen halaman dapat dibuat; belum menguji seluruh interaksinya.
  it('should create', () => {
    expect(component).toBeTruthy();
  });

  // FIXTURE: snapshot hanya memuat role sendiri, bukan rahasia pemain lain.
  function snapshot(): GameSnapshot {
    return {
      room: {
        code: 'ABC123',
        owner: 'alice',
        members: ['alice'],
        bots: ['NOX'],
        bot_enabled: true,
        phase: 'day',
      },
      game: {
        id: 'match-1',
        phase: 'day',
        round: 1,
        deadline: 120,
        server_time: 100,
        winner: null,
        tribunal_votes: [],
        discussion_skip: { agreed: 0, required: 1, consented: false, can_consent: true },
        events: [],
        messages: [],
        players: [
          { name: 'alice', bot: false, alive: true },
          { name: 'NOX', bot: true, alive: true },
        ],
        me: {
          name: 'alice',
          role: 'hitman',
          alive: true,
          muted: false,
          can_chat: true,
          can_vote: false,
          vote: null,
          ability: 'gag',
          can_act: true,
          action: null,
          next_gag: 1,
          next_peek: 1,
          last_guard: null,
          intel: [],
        },
      },
    };
  }

  it('loads private state and resets stale target on phase change', () => {
    const state = snapshot();
    const request = vi.spyOn(TestBed.inject(GameService), 'request').mockReturnValue(of(state));
    component.code = 'ABC123';
    component.refresh();
    expect(component.seconds).toBe(20);
    component.target = 'NOX';
    request.mockReturnValue(of({ ...state, game: { ...state.game, phase: 'night' } }));
    component.refresh();
    expect(component.target).toBe('');
    expect(component.busy).toBe(false);
  });

  it('sends match and phase token with the selected ability', () => {
    component.game = snapshot().game;
    component.code = 'ABC123';
    component.target = 'NOX';
    const request = vi
      .spyOn(TestBed.inject(GameService), 'request')
      .mockReturnValue(of(snapshot()));
    component.act();
    expect(request).toHaveBeenCalledWith(
      'ABC123',
      {
        match_id: 'match-1',
        round_number: 1,
        phase: 'day',
        target: 'NOX',
        ability: 'gag',
      },
      'play',
    );
    expect(component.notice).toContain('dikunci');
    expect(component.busy).toBe(false);
  });

  it('keeps chat received during polling without duplicates or cross-match messages', () => {
    component.game = snapshot().game;
    component.code = 'ABC123';
    const response = new Subject<GameSnapshot>();
    vi.spyOn(TestBed.inject(GameService), 'request').mockReturnValue(response);
    component.refresh();
    const message = { id: 'new-chat', sender: 'NOX', message: 'Alibimu?' };
    component.game.messages.push(message);
    response.next(snapshot());
    response.complete();
    expect(component.game.messages).toEqual([message]);

    const state = snapshot();
    state.game.messages = [message];
    vi.spyOn(TestBed.inject(GameService), 'request').mockReturnValue(of(state));
    component.refresh();
    expect(component.game.messages).toEqual([message]);

    state.game = { ...state.game, id: 'match-2', messages: [] };
    component.refresh();
    expect(component.game.messages).toEqual([]);
  });

  it('releases loading on network errors so retry remains available', () => {
    component.code = 'ABC123';
    vi.spyOn(TestBed.inject(GameService), 'request').mockReturnValue(
      throwError(() => ({ status: 503 })),
    );
    component.refresh();
    expect(component.busy).toBe(false);
    expect(component.error).toBe('Server belum bisa dihubungi.');
  });

  it('returns to the lobby when the server no longer has the current match', () => {
    component.game = snapshot().game;
    component.code = 'ABC123';
    for (const key of [
      'shadow_heist_room',
      'shadow_heist_room_snapshot',
      'shadow_heist_game_entry',
    ])
      sessionStorage.setItem(key, 'stale');
    const request = vi
      .spyOn(TestBed.inject(GameService), 'request')
      .mockReturnValue(
        throwError(() => ({ status: 400, error: { detail: 'Ruangan tidak ditemukan.' } })),
      );
    component.refresh();
    expect(TestBed.inject(Router).navigateByUrl).toHaveBeenCalledWith('/lobby');
    expect(component.game).toBeNull();
    expect(component.busy).toBe(false);
    for (const key of [
      'shadow_heist_room',
      'shadow_heist_room_snapshot',
      'shadow_heist_game_entry',
    ])
      expect(sessionStorage.getItem(key)).toBeNull();
    component.refresh();
    expect(request).toHaveBeenCalledTimes(1);
  });

  it('keeps the current match when an action is rejected after a phase change', () => {
    component.game = snapshot().game;
    component.code = 'ABC123';
    component.target = 'NOX';
    const navigate = vi.mocked(TestBed.inject(Router).navigateByUrl);
    navigate.mockClear();
    vi.spyOn(TestBed.inject(GameService), 'request').mockReturnValue(
      throwError(() => ({ status: 400, error: { detail: 'Fase sudah berubah.' } })),
    );
    component.act();
    expect(component.code).toBe('ABC123');
    expect(component.game).not.toBeNull();
    expect(component.error).toBe('Fase sudah berubah.');
    expect(component.busy).toBe(false);
    expect(navigate).not.toHaveBeenCalled();
  });

  it('only allows self target for Guard and excludes consecutive target', () => {
    component.game = snapshot().game;
    expect(component.canTarget('alice')).toBe(false);
    component.game.me.ability = 'guard';
    expect(component.canTarget('alice')).toBe(true);
    component.game.me.last_guard = 'alice';
    expect(component.canTarget('alice')).toBe(false);
  });

  it('caps voter badges at four plus overflow, retaining all names in details', () => {
    const game = snapshot().game;
    game.phase = 'tribunal';
    game.players = ['a', 'b', 'c', 'd', 'e', 'f'].map((name) => ({
      name,
      bot: false,
      alive: true,
    }));
    game.tribunal_votes = [{ target: 'f', voters: ['a', 'b', 'c', 'd', 'e'] }];
    component.game = game;
    fixture.componentRef.changeDetectorRef.markForCheck();
    fixture.detectChanges();
    const cards = fixture.nativeElement.querySelectorAll('.player-card');
    const target = cards[5] as HTMLElement;
    expect(target.querySelector('.vote-count')?.textContent).toContain('5 vote');
    expect(target.querySelectorAll('.voter-badge').length).toBe(5);
    expect(target.querySelector('.voter-badges')?.textContent).toContain('+1');
    expect(target.querySelectorAll('.voter-details li').length).toBe(5);
    expect(target.querySelector('.voter-badges')?.getAttribute('title')).toBe('a, b, c, d, e');
  });

  // VOTE: bingkai makin merah seiring suara; suara terbanyak tunggal ditandai "terancam".
  it('heats up voted players and marks only a unique leader', () => {
    const game = snapshot().game;
    game.phase = 'tribunal';
    game.players = ['a', 'b', 'c', 'd', 'e', 'f'].map((name) => ({
      name,
      bot: false,
      alive: true,
    }));
    game.tribunal_votes = [
      { target: 'e', voters: ['a'] },
      { target: 'f', voters: ['b', 'c'] },
    ];
    component.game = game;
    // 6 pemain hidup: mayoritas 4 suara = panas penuh.
    expect(component.voteHeat('e')).toBeCloseTo(0.25);
    expect(component.voteHeat('f')).toBeCloseTo(0.5);
    expect(component.voteHeat('a')).toBe(0);
    expect(component.leadingTarget).toBe('f');
    game.tribunal_votes.push({ target: 'a', voters: ['d', 'e'] });
    expect(component.leadingTarget).toBe('');
    game.tribunal_votes[1].voters.push('a', 'd', 'e');
    expect(component.voteHeat('f')).toBe(1);
    fixture.componentRef.changeDetectorRef.markForCheck();
    fixture.detectChanges();
    const leading = fixture.nativeElement.querySelector('.player-card.leading');
    expect(leading?.textContent).toContain('f');
    expect(leading?.textContent).toContain('Terancam');
  });

  // KARAKTER: ditentukan urutan kursi, tidak pernah dari role (tidak membocorkan rahasia).
  it('assigns avatars and colors by seat order, never by role', () => {
    const game = snapshot().game;
    component.game = game;
    const before = [
      component.skinFor('alice'),
      component.skinFor('NOX'),
      component.colorFor('NOX'),
    ];
    game.players = game.players.map((player, index) => ({
      ...player,
      role: index ? 'hitman' : 'civilian',
    }));
    expect([
      component.skinFor('alice'),
      component.skinFor('NOX'),
      component.colorFor('NOX'),
    ]).toEqual(before);
    expect(component.skinFor('alice')).not.toBe(component.skinFor('NOX'));
    expect(component.roleCard('spy')).toBe('/assets/cards/card_spy.png');
    expect(component.roleCard('unknown')).toBe('/assets/cards/card_blank.png');
  });

  // TIMER: sisa waktu dibandingkan durasi fase dari room snapshot.
  it('computes the timer ring from the room phase durations', () => {
    const state = snapshot();
    state.room.match_durations = { day: 120, night: 30, tribunal: 45 };
    vi.spyOn(TestBed.inject(GameService), 'request').mockReturnValue(of(state));
    component.code = 'ABC123';
    component.refresh();
    expect(component.seconds).toBe(20);
    expect(component.timerFraction).toBeCloseTo(20 / 120);
    expect(component.timerUrgent).toBe(false);
  });

  // TAB HP: pesan baru saat tab lain aktif ditandai, dan dihapus saat tab chat dibuka.
  it('counts unread chat on other mobile tabs and clears it when chat opens', () => {
    const state = snapshot();
    const request = vi.spyOn(TestBed.inject(GameService), 'request').mockReturnValue(of(state));
    component.code = 'ABC123';
    component.refresh();
    expect(component.unread).toBe(0);
    const next = snapshot();
    next.game.messages = [
      { id: 'm1', sender: 'NOX', message: 'Halo' },
      { id: 'm2', sender: 'NOX', message: 'Ada yang curiga?' },
    ];
    request.mockReturnValue(of(next));
    component.refresh();
    expect(component.unread).toBe(2);
    component.selectTab('chat');
    expect(component.unread).toBe(0);
    expect(component.mobileTab).toBe('chat');
  });

  // AKHIR: pengumuman pemenang → kuesioner → meja akhir, tanpa baki aksi.
  it('walks from the winner announcement to the survey and the final board', () => {
    const state = snapshot();
    state.game.phase = 'finished';
    state.game.winner = 'hitman';
    state.game.players = [
      { name: 'alice', bot: false, alive: true, role: 'hitman' },
      { name: 'NOX', bot: true, alive: false, role: 'civilian' },
    ];
    const api = TestBed.inject(GameService);
    vi.spyOn(api, 'request').mockReturnValue(of(state));
    vi.spyOn(api, 'survey').mockReturnValue(
      of({ match_id: 'match-1', submitted: false, questions: [] }),
    );
    component.code = 'ABC123';
    component.refresh();
    fixture.componentRef.changeDetectorRef.markForCheck();
    fixture.detectChanges();
    const stage = fixture.nativeElement.querySelector('.end-stage');
    expect(stage.textContent).toContain('Hitman menang!');
    expect(stage.textContent).toContain('KAMU MENANG');
    expect(stage.querySelectorAll('.lineup li').length).toBe(1);
    component.goToSurvey();
    fixture.componentRef.changeDetectorRef.markForCheck();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.survey')).not.toBeNull();
    component.showBoard();
    fixture.componentRef.changeDetectorRef.markForCheck();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.end-stage')).toBeNull();
    expect(fixture.nativeElement.querySelector('.board-bar')).not.toBeNull();
    expect(fixture.nativeElement.querySelector('.action-panel')).toBeNull();
    expect(fixture.nativeElement.querySelector('.players').textContent).toContain('BOT');
  });

  it('does not clear draft when chat is disconnected or locked', () => {
    component.game = snapshot().game;
    component.draft = 'Alibiku';
    component.sendMessage();
    expect(component.draft).toBe('Alibiku');
    component.connected = true;
    component.game.me.can_chat = false;
    component.sendMessage();
    expect(component.draft).toBe('Alibiku');
  });

  it('shows a team victory for an eliminated citizen, with the server reason', () => {
    const game = snapshot().game;
    game.phase = 'finished';
    game.winner = 'civilians';
    game.me = { ...game.me, role: 'spy', alive: false, can_chat: false, can_act: false };
    game.result = {
      reason: 'hitman_executed',
      team: 'civilians',
      outcome: 'won',
      civilians_alive: 2,
      civilians_hostage: 1,
      civilians_eliminated: 1,
    };
    component.game = game;
    fixture.componentRef.changeDetectorRef.markForCheck();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.result').textContent).toContain('KAMU MENANG');
    expect(fixture.nativeElement.querySelector('.result').textContent).toContain(
      'Hitman telah dieksekusi',
    );
    expect(fixture.nativeElement.querySelector('.action-panel')).toBeNull();
  });

  it('explains permanent hostage and temporary gag separately without exposing roster statuses', () => {
    component.game = snapshot().game;
    component.game.me.hostage = true;
    expect(component.privateStatus).toContain('sampai pertandingan berakhir');
    component.game.me.hostage = false;
    component.game.me.gagged = true;
    expect(component.privateStatus).toContain('Voting dan aksi malam tetap boleh');
    fixture.componentRef.changeDetectorRef.markForCheck();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.players').textContent).not.toContain('HOSTAGE');
    expect(fixture.nativeElement.querySelector('.players').textContent).not.toContain('GAG');
    expect(fixture.nativeElement.querySelector('.players').textContent).not.toContain('BOT');
  });

  it('shows a loss for a hostage when Hitman wins', () => {
    component.game = snapshot().game;
    component.game.me.role = 'civilian';
    component.game.me.hostage = true;
    component.game.winner = 'hitman';
    expect(component.outcomeLabel).toBe('KAMU KALAH');
  });

  // PERSIAPAN: layar panduan tampil sebelum ronde 1; tombol siap mengirim token pertandingan.
  it('shows the preparation screen and sends ready with the match token', () => {
    const state = snapshot();
    state.game.phase = 'preparing';
    state.game.preparation = {
      ready: false,
      detail: 'Memuat NLU IndoBERT…',
      progress: 0.4,
      starts_in: null,
      max_wait: 80,
      agreed: 0,
      required: 1,
      consented: false,
      bots: 1,
    };
    const request = vi.spyOn(TestBed.inject(GameService), 'request').mockReturnValue(of(state));
    component.code = 'ABC123';
    component.refresh();
    fixture.componentRef.changeDetectorRef.markForCheck();
    fixture.detectChanges();
    const splash = fixture.nativeElement.querySelector('.splash');
    expect(splash.textContent).toContain('Memuat NLU IndoBERT');
    expect(fixture.nativeElement.querySelector('.match-grid')).toBeNull();
    component.readyUp();
    expect(request).toHaveBeenLastCalledWith('ABC123', { match_id: 'match-1' }, 'ready');
  });

  // TRANSISI: overlay muncul saat fase berganti, tidak saat halaman pertama kali dimuat.
  it('shows the night transition only when the phase changes', () => {
    const state = snapshot();
    const request = vi.spyOn(TestBed.inject(GameService), 'request').mockReturnValue(of(state));
    component.code = 'ABC123';
    component.refresh();
    expect(component.transition).toBeNull();
    request.mockReturnValue(of({ ...state, game: { ...state.game, phase: 'night' } }));
    component.refresh();
    expect(component.transition?.phase).toBe('night');
    expect(component.transition?.title).toContain('Malam');
  });

  // HASIL: ucapan selamat dan daftar pemenang dari role yang dibuka setelah selesai.
  it('congratulates the winning team', () => {
    component.game = snapshot().game;
    component.game.winner = 'civilians';
    component.game.me.role = 'spy';
    component.game.players = [
      { name: 'alice', alive: true, role: 'spy', bot: false },
      { name: 'NOX', alive: false, role: 'hitman', bot: true },
    ];
    expect(component.congratsTitle).toBe('Selamat, kamu menang!');
    expect(component.winners.map((player) => player.name)).toEqual(['alice']);
    component.game.me.role = 'hitman';
    expect(component.congratsTitle).toBe('Selamat untuk kubu warga!');
  });

  // SURVEI: pertanyaan dari backend, wajib diisi sebelum kirim, dan dikirim sekali.
  it('loads the survey once after the match and submits required answers', () => {
    const state = snapshot();
    state.game.winner = 'civilians';
    state.game.phase = 'finished';
    const api = TestBed.inject(GameService);
    vi.spyOn(api, 'request').mockReturnValue(of(state));
    const survey = vi.spyOn(api, 'survey').mockReturnValue(
      of({
        match_id: 'match-1',
        submitted: false,
        questions: [
          {
            id: 1,
            code: 'seru',
            prompt: 'Seberapa seru?',
            kind: 'stars',
            scale_min: 1,
            scale_max: 6,
            label_min: 'Bosan',
            label_max: 'Seru',
            options: [],
            required: true,
          },
          {
            id: 2,
            code: 'komentar',
            prompt: 'Komentar',
            kind: 'text',
            scale_min: 1,
            scale_max: 6,
            label_min: null,
            label_max: null,
            options: [],
            required: false,
          },
        ],
      }),
    );
    const submit = vi
      .spyOn(api, 'submitSurvey')
      .mockReturnValue(of({ submitted: true, answers: 1 }));
    component.code = 'ABC123';
    component.refresh();
    component.refresh();
    expect(survey).toHaveBeenCalledTimes(1);
    expect(component.surveyState).toBe('ready');
    expect(component.surveyComplete).toBe(false);
    const [stars] = component.survey!.questions;
    component.setAnswer(stars, 5);
    expect(component.isSelected(stars, 4)).toBe(true);
    expect(component.isSelected(stars, 6)).toBe(false);
    expect(component.surveyComplete).toBe(true);
    component.submitSurvey();
    expect(submit).toHaveBeenCalledWith('ABC123', 'match-1', [{ question_id: 1, value: 5 }]);
    expect(component.surveyState).toBe('done');
  });

  it('treats an already submitted survey as done', () => {
    component.code = 'ABC123';
    component.survey = { match_id: 'match-1', submitted: false, questions: [] };
    component.surveyState = 'ready';
    vi.spyOn(TestBed.inject(GameService), 'submitSurvey').mockReturnValue(
      throwError(() => ({ status: 409, error: { detail: 'Sudah dikirim.' } })),
    );
    component.submitSurvey();
    expect(component.surveyState).toBe('done');
    expect(component.surveyError).toBe('');
  });

  function render(): HTMLElement {
    fixture.componentRef.changeDetectorRef.markForCheck();
    fixture.detectChanges();
    return fixture.nativeElement;
  }

  // KOMPOSISI: jumlah role dari server tampil di persiapan dan di meja; tanpa data, tidak ada chip.
  it('shows the room composition from the server on the splash and the table', () => {
    const state = snapshot();
    state.game.phase = 'preparing';
    state.game.preparation = {
      ready: true,
      detail: 'AI siap.',
      progress: 1,
      starts_in: 5,
      max_wait: 80,
      agreed: 0,
      required: 1,
      consented: false,
      bots: 7,
    };
    component.game = state.game;
    expect(render().querySelector('.composition')).toBeNull();
    expect(component.threatLine).toBe('Hitman bersembunyi di antara kalian.');

    state.game.composition = { hitman: 2, spy: 1, stalker: 1, civilian: 4 };
    const splash = render().querySelector('.splash') as HTMLElement;
    expect(splash.querySelectorAll('.comp-chip').length).toBe(4);
    expect(component.compositionLabel).toBe('2 Hitman · 1 Spy · 1 Stalker · 4 Civilian');
    expect(splash.textContent).toContain('2 Hitman bersembunyi di antara kalian');
    expect(splash.textContent).toContain('Jumlah Hitman dan Spy mengikuti jumlah pemain');

    state.game.phase = 'day';
    state.game.me.role = 'spy';
    const felt = render().querySelector('.table-felt') as HTMLElement;
    expect(felt.classList).toContain('has-composition');
    expect(felt.querySelector('.felt-composition')?.textContent).toContain('Hitman');
    expect(component.objective).toContain('semua 2 Hitman');
    const hitmanChip = () =>
      render().querySelector('.felt-composition [data-role="hitman"]') as HTMLElement;
    expect(hitmanChip().textContent?.trim()).toMatch(/^\S*\s*2\s+Hitman$/); // belum diumumkan

    // Room multi-Hitman: server mengumumkan Hitman tersisa → chip meja "tersisa/total", merah bila berkurang.
    state.game.hitman_remaining = 2;
    expect(hitmanChip().textContent).toContain('2/2');
    expect(hitmanChip().classList).not.toContain('reduced');
    state.game.hitman_remaining = 1;
    expect(hitmanChip().textContent).toContain('1/2');
    expect(hitmanChip().classList).toContain('reduced');
    expect(hitmanChip().title).toBe('Hitman tersisa 1 dari 2');
    // Pembaca layar mendengar kalimat utuh, bukan pecahan "1/2".
    expect(hitmanChip().querySelector('.sr-only')?.textContent).toBe('Hitman tersisa 1 dari 2');
    expect(hitmanChip().querySelector('[aria-hidden="true"] b')?.textContent).toBe('1/2');
    expect(render().querySelector('.splash')).toBeNull();
  });

  // REKAN: hanya Hitman yang melihat rekan; rekan tidak bisa jadi target Hostage/Gag, tetapi boleh di-vote.
  it('shows Syndicate allies only to a Hitman and keeps them out of Hostage and Gag targets', () => {
    const game = snapshot().game;
    game.players = ['alice', 'NOX', 'bob'].map((name) => ({ name, alive: true }));
    game.me.allies = ['NOX'];
    component.game = game;
    component.revealRole = true;
    let cards = render().querySelectorAll('.player-card');
    expect(component.canTarget('NOX')).toBe(false);
    expect(component.canTarget('bob')).toBe(true);
    expect(cards[1].querySelector('.ally-tag')?.textContent).toContain('Rekan');
    expect((cards[1].querySelector('button') as HTMLButtonElement).disabled).toBe(true);
    expect((cards[2].querySelector('button') as HTMLButtonElement).disabled).toBe(false);
    expect(cards[2].querySelector('.ally-tag')).toBeNull();
    expect(fixture.nativeElement.querySelector('.private-card .allies')?.textContent).toContain(
      'NOX',
    );
    expect(fixture.nativeElement.querySelector('.action-panel').textContent).toContain(
      'dipakai bersama rekan',
    );

    game.phase = 'tribunal';
    game.me = { ...game.me, ability: null, can_act: false, can_vote: true };
    cards = render().querySelectorAll('.player-card');
    expect(component.canTarget('NOX')).toBe(true);
    expect((cards[1].querySelector('button') as HTMLButtonElement).disabled).toBe(false);

    // Role lain tidak pernah menampilkan rekan, walaupun data salah ikut terkirim.
    game.me.role = 'civilian';
    expect(component.allies).toEqual([]);
    expect(render().querySelector('.ally-tag')).toBeNull();
  });

  // MALAM: pilihan Hostage rekan terlihat, dan target terbanyak (seri → pilihan pertama) bisa disamakan.
  it('lists ally Hostage choices at night and offers to match them', () => {
    const game = snapshot().game;
    game.phase = 'night';
    game.players = ['alice', 'NOX', 'VEIL', 'bob', 'eka'].map((name) => ({ name, alive: true }));
    game.me = {
      ...game.me,
      ability: 'hostage',
      can_act: true,
      allies: ['NOX', 'VEIL'],
      ally_actions: [{ name: 'VEIL', target: 'bob' }],
    };
    component.game = game;
    const page = render();
    expect(component.allyPlan).toEqual([
      { name: 'NOX', target: null },
      { name: 'VEIL', target: 'bob' },
    ]);
    expect(component.allyTarget).toBe('bob');
    const panel = page.querySelector('.action-panel') as HTMLElement;
    expect(panel.textContent).toContain('belum memilih');
    expect(panel.textContent).toContain('Syndicate hanya menyandera satu orang');
    expect(page.querySelectorAll('.player-card')[3].querySelector('.ally-pick')).not.toBeNull();
    (panel.querySelector('.ally-match') as HTMLButtonElement).click();
    expect(component.target).toBe('bob');
    expect(render().querySelector('.ally-match')).toBeNull();

    game.me.ally_actions = [
      { name: 'VEIL', target: 'eka' },
      { name: 'NOX', target: 'bob' },
    ];
    expect(component.allyTarget).toBe('eka');
  });

  // ATURAN BARU: semua Hitman harus dieksekusi; Hitman menang saat warga bebas ≤ Hitman hidup.
  it('explains the multi-Hitman win conditions in the rules and the result', () => {
    const game = snapshot().game;
    game.composition = { hitman: 2, spy: 2, stalker: 1, civilian: 5 };
    component.game = game;
    component.showRules = true;
    const rules = (render().querySelector('.rules-modal') as HTMLElement).textContent ?? '';
    expect(rules).toContain('2 Hitman · 2 Spy · 1 Stalker · 5 Civilian');
    expect(rules).toContain('menang jika semua Hitman dieksekusi');
    expect(rules).toContain('tidak lebih banyak dari Hitman yang masih hidup');
    expect(rules).not.toContain('Hitman yang tersisa diumumkan');
    game.hitman_remaining = 2;
    const announced = (render().querySelector('.rules-modal') as HTMLElement).textContent ?? '';
    expect(announced).toContain('jumlah Hitman yang tersisa diumumkan setelah setiap eksekusi');

    game.phase = 'finished';
    game.winner = 'civilians';
    game.me.role = 'spy';
    game.players = [
      { name: 'alice', alive: true, role: 'spy' },
      { name: 'NOX', alive: false, role: 'hitman' },
      { name: 'VEIL', alive: false, role: 'hitman' },
    ];
    game.result = {
      reason: 'hitman_executed',
      team: 'civilians',
      outcome: 'won',
      civilians_alive: 1,
      civilians_hostage: 0,
      civilians_eliminated: 0,
    };
    expect(component.resultExplanation).toContain('Semua Hitman telah dieksekusi');

    // Syndicate menang walau satu Hitman sudah dieksekusi (keadaan yang mungkin di engine).
    game.winner = 'hitman';
    game.players = [
      { name: 'alice', alive: true, role: 'spy' },
      { name: 'NOX', alive: true, role: 'hitman' },
      { name: 'VEIL', alive: false, role: 'hitman' },
    ];
    game.result = {
      reason: 'vote_control',
      team: 'civilians',
      outcome: 'lost',
      civilians_alive: 1,
      civilians_hostage: 0,
      civilians_eliminated: 0,
    };
    expect(component.winners.map((player) => player.name)).toEqual(['NOX', 'VEIL']);
    expect(component.congratsTitle).toBe('Selamat untuk Syndicate!');
    expect(component.resultExplanation).toContain('tidak lebih banyak dari Hitman');
    expect(render().querySelectorAll('.lineup li').length).toBe(2);
  });

  // Room satu Hitman: teks Syndicate (Hostage/Gag bersama, "para Hitman") tidak ditampilkan.
  it('keeps single-Hitman wording in rooms with one Hitman', () => {
    const game = snapshot().game;
    game.composition = { hitman: 1, spy: 1, stalker: 1, civilian: 2 };
    game.me.role = 'hitman';
    component.game = game;
    component.showRules = true;
    const rules = (render().querySelector('.rules-modal') as HTMLElement).textContent ?? '';
    expect(rules).not.toContain('Syndicate hanya menyandera');
    expect(rules).not.toContain('dipakai bersama');
    expect(rules).toContain('Hitman menyandera satu pemain per malam');
    expect(component.guide.map((item) => item.text).join(' ')).not.toMatch(/Para Hitman|bersama/);
    expect(component.roleHelp['hitman']).not.toContain('Syndicate');
    expect(component.roleHelp['spy']).not.toContain('Spy lain');

    game.composition = { hitman: 2, spy: 2, stalker: 1, civilian: 3 };
    expect(component.guide.find((item) => item.title === 'Malam')?.text).toContain('Para Hitman');
    expect(component.roleHelp['hitman']).toContain('Syndicate');
    expect(component.roleHelp['spy']).toContain('Spy lain');
  });

  // Malam Hitman: rekan yang sudah mati tidak masuk rencana; beda pilihan dengan rekan diberi tahu.
  it('lists only living allies and warns when the Hitman picks a different target', () => {
    const game = snapshot().game;
    game.phase = 'night';
    game.composition = { hitman: 2, spy: 2, stalker: 1, civilian: 3 };
    game.me.role = 'hitman';
    game.me.ability = 'hostage';
    game.me.can_act = true;
    game.me.allies = ['NOX', 'VEIL'];
    game.players = [
      { name: 'alice', alive: true },
      { name: 'NOX', alive: true },
      { name: 'VEIL', alive: false },
      { name: 'eka', alive: true },
      { name: 'bob', alive: true },
    ];
    game.me.ally_actions = [{ name: 'NOX', target: 'eka' }];
    component.game = game;
    expect(component.allyPlan).toEqual([{ name: 'NOX', target: 'eka' }]);
    expect(render().textContent).not.toContain('Pilihanmu berbeda dengan rekan');
    // Setelah pilihan sendiri dikunci ke target lain, Hitman diberi tahu aturan target terbanyak.
    game.me.can_act = false;
    game.me.action = { ability: 'hostage', target: 'bob' };
    expect(render().textContent).toContain('Pilihanmu berbeda dengan rekan');
    const pick = render().querySelector('.ally-pick') as HTMLElement;
    expect(pick.textContent).toContain('◆ Incaran');
    expect(pick.querySelector('.sr-only')?.textContent).toContain('Hostage pilihan rekan: NOX');
  });
});
