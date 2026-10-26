import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';

import { Game } from './game';
import { HttpErrorResponse, provideHttpClient } from '@angular/common/http';
import { of, Subject, throwError } from 'rxjs';
import { By } from '@angular/platform-browser';
import { GameService, GameSnapshot } from '../../core/game.service';
import { SurveyForm } from '../../core/survey-form/survey-form';

// TEST SUITE: kelompok pengujian otomatis, bukan logika yang dijalankan halaman production.
// Callback () => { ... } berisi setup dan skenario yang dipanggil oleh test runner.
describe('Game', () => {
  // INSTANCE TES: component adalah class halaman; fixture membungkus komponen untuk pengujian.
  let component: Game;
  let fixture: ComponentFixture<Game>;
  const member = (name: string) => ({ name, skin_id: 'dexter' });

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
        members: [member('alice')],
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

  it('shows display names while actions keep the username', () => {
    const state = snapshot();
    state.game.players = [
      { name: 'alice', label: 'Alice Wonder', bot: false, alive: true },
      { name: 'NOX', label: 'NOX', bot: true, alive: true },
    ];
    state.game.phase = 'tribunal';
    state.game.tribunal_votes = [{ target: 'NOX', voters: ['alice'] }];
    component.game = state.game;
    component.code = 'ABC123';
    fixture.componentRef.changeDetectorRef.markForCheck();
    fixture.detectChanges();
    const cards = fixture.nativeElement.querySelectorAll('.player-card');
    expect((cards[0] as HTMLElement).querySelector('.name-tag')?.textContent).toBe('Alice Wonder');
    expect((cards[1] as HTMLElement).querySelector('.voter-badges')?.getAttribute('title')).toBe(
      'Alice Wonder',
    );
    expect(component.nama('alice')).toBe('Alice Wonder');
    expect(component.nama('tamu')).toBe('tamu'); // snapshot lama tanpa label
    state.game.players[1].metode = 'fuzzy';
    expect(component.nama('NOX')).toBe('NOX · FL');
    state.game.players[1].metode = 'utility';
    expect(component.nama('NOX')).toBe('NOX · UA');
    state.game.players[1].metode = 'bt';
    expect(component.nama('NOX')).toBe('NOX · BT');
    component.target = 'NOX';
    const request = vi.spyOn(TestBed.inject(GameService), 'request').mockReturnValue(of(state));
    component.act();
    expect(request.mock.calls[0][1]).toMatchObject({ target: 'NOX' });
  });

  // Awan berpikir hanya di bot yang sedang menyusun chat, dan tidak tampil setelah pertandingan selesai.
  it('shows a thinking cloud on the bot that is composing a chat', () => {
    const state = snapshot();
    state.game.players[1].thinking = true;
    component.game = state.game;
    fixture.componentRef.changeDetectorRef.markForCheck();
    fixture.detectChanges();
    const clouds = fixture.nativeElement.querySelectorAll('.thought');
    expect(clouds.length).toBe(1);
    expect((clouds[0] as HTMLElement).getAttribute('aria-label')).toBe('NOX sedang berpikir');
    component.game = { ...state.game, winner: 'civilians' };
    fixture.componentRef.changeDetectorRef.markForCheck();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.thought')).toBeNull();
  });

  // Tombol aksi menyebut nama tampilan target; username hanya dikirim ke server.
  it('names the selected target by display name on the vote button', () => {
    const state = snapshot();
    state.game.players.push({ name: 'bob123', label: 'Bobby Sapu', bot: false, alive: true });
    state.game.phase = 'tribunal';
    state.game.me = { ...state.game.me, role: 'civilian', can_vote: true, can_act: false };
    component.game = state.game;
    component.target = 'bob123';
    fixture.componentRef.changeDetectorRef.markForCheck();
    fixture.detectChanges();
    const button = fixture.nativeElement.querySelector('.action-buttons .red') as HTMLElement;
    expect(button.textContent).toContain('Bobby Sapu');
    expect(button.textContent).not.toContain('bob123');
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

  // KARAKTER: skin pilihan dari server, cadangan urutan kursi, tidak pernah dari role (tidak membocorkan rahasia).
  it('uses server skins, falls back to seat order, never by role', () => {
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
    game.players = game.players.map((player) => ({
      ...player,
      skin_id: player.name === 'alice' ? 'kiera' : 'sadie',
    }));
    expect(component.skinFor('alice')).toBe('/assets/characters/skin_kiera.png');
    expect(component.skinFor('NOX')).toBe('/assets/characters/skin_sadie.png');
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
    // Status sendiri hanya di kartu sendiri; kartu pemain lain tidak membawa status apa pun.
    const [own, other] = fixture.nativeElement.querySelectorAll('.player-card');
    expect(own.querySelector('.gag-tag')?.textContent).toContain('GAG');
    expect(other.textContent).not.toContain('HOSTAGE');
    expect(other.textContent).not.toContain('GAG');
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
    component.code = 'ABC123';
    component.refresh();
    component.refresh();
    expect(survey).toHaveBeenCalledTimes(1);
    expect(component.surveyState).toBe('ready');
    // Formulir ada di SurveyForm (diuji tersendiri); Game hanya menampilkan "terima kasih" setelahnya.
    component.goToSurvey();
    render();
    const form = fixture.debugElement.query(By.directive(SurveyForm));
    expect(form.nativeElement.textContent).toContain('Seberapa seru?');
    (form.componentInstance as SurveyForm).submitted.emit();
    expect(component.surveyState).toBe('done');
    expect(render().querySelector('.survey-done')?.textContent).toContain('Terima kasih');
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

    state.game.composition = { hitman: 2, spy: 1, stalker: 1, civilian: 4 };
    const splash = render().querySelector('.splash') as HTMLElement;
    expect(splash.querySelectorAll('.comp-chip').length).toBe(4);
    expect(component.compositionLabel).toBe('2 Hitman · 1 Spy · 1 Stalker · 4 Civilian');
    expect(splash.querySelectorAll('.prep-card').length).toBe(3);
    expect(splash.querySelector('.prep-target')?.textContent).toContain('Buka kartu role');
    expect(splash.querySelector('.prep-actions')?.textContent).not.toContain('Sandera');
    component.revealRole = true;
    const opened = render();
    expect(opened.querySelector('.prep-actions')?.textContent).toContain('Sandera');
    expect(opened.querySelector('.prep-target')?.textContent).toContain('bebas bersuara');
    expect(opened.querySelector('.nudge-hand')).toBeNull();

    state.game.phase = 'day';
    state.game.me.role = 'spy';
    const felt = render().querySelector('.table-felt') as HTMLElement;
    expect(felt.classList).toContain('has-composition');
    expect(felt.querySelector('.felt-composition')?.textContent).toContain('Hitman');
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
    expect(panel.firstElementChild?.classList).toContain('action-buttons');
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

  function preparing(revealed = false, elapsed = 3): GameSnapshot {
    const state = snapshot();
    state.game.phase = 'preparing';
    state.game.preparation = {
      ready: true,
      detail: 'AI siap.',
      progress: 1,
      starts_in: Math.max(0, 40 - elapsed),
      max_wait: 80,
      agreed: 0,
      required: 2,
      consented: false,
      bots: 1,
      elapsed,
      revealed,
      unrevealed: revealed ? 1 : 2,
    };
    return state;
  }

  // KARTU ROLE: pembukaan pertama dilaporkan ke server; dikirim ulang tiap 4 detik dengan polling di sela.
  it('reports the first role reveal and retries until the server records it', () => {
    let now = 50_000;
    vi.spyOn(Date, 'now').mockImplementation(() => now);
    const request = vi
      .spyOn(TestBed.inject(GameService), 'request')
      .mockReturnValue(of(preparing()));
    component.code = 'ABC123';
    component.refresh();
    expect(request).toHaveBeenLastCalledWith('ABC123', undefined, 'play');
    component.toggleRole();
    expect(request).toHaveBeenLastCalledWith('ABC123', { match_id: 'match-1' }, 'reveal');
    component.refresh(); // belum 4 detik: polling biasa agar layar tetap mengikuti server
    expect(request).toHaveBeenLastCalledWith('ABC123', undefined, 'play');
    now += 4000;
    component.refresh(); // server belum mencatat: kirim ulang
    expect(request).toHaveBeenLastCalledWith('ABC123', { match_id: 'match-1' }, 'reveal');
    request.mockReturnValue(of(preparing(true)));
    now += 4000;
    component.refresh();
    now += 4000;
    component.refresh(); // sudah tercatat: kembali polling biasa
    expect(request).toHaveBeenLastCalledWith('ABC123', undefined, 'play');
    expect(component.notice).toBe('');
    expect(render().querySelector('.splash')?.textContent).toContain(
      'Ronde 1 dimulai dalam 37 detik',
    );
  });

  // KOMPATIBEL: backend lama tanpa /reveal (404) tidak menampilkan error dan tidak menghentikan polling.
  it('keeps polling silently when the backend does not know the reveal endpoint', () => {
    let now = 50_000;
    vi.spyOn(Date, 'now').mockImplementation(() => now);
    const api = TestBed.inject(GameService);
    const request = vi.spyOn(api, 'request').mockReturnValue(of(preparing()));
    component.code = 'ABC123';
    component.refresh();
    request.mockImplementation((_code, body) =>
      body
        ? throwError(() => new HttpErrorResponse({ status: 404, error: { detail: 'Not Found' } }))
        : of(snapshot()),
    );
    component.toggleRole();
    expect(component.error).toBe('');
    expect(component.busy).toBe(false);
    component.refresh(); // polling berikutnya tetap GET dan membawa fase terbaru
    expect(request).toHaveBeenLastCalledWith('ABC123', undefined, 'play');
    expect(component.game?.phase).toBe('day');
  });

  // KARTU ROLE: ajakan membuka kartu hanya pada sepuluh detik terakhir.
  it('keeps the prompted card visible for three seconds after opening it', () => {
    vi.useFakeTimers();
    try {
      component.game = preparing(false, 29).game;
      expect(component.revealPrompt).toBe(false);
      component.game = preparing(false, 30).game;
      expect(component.revealPrompt).toBe(true);
      const nudge = render().querySelector('.reveal-nudge') as HTMLElement;
      expect(nudge.textContent).toContain('Ketuk kartumu');
      vi.spyOn(TestBed.inject(GameService), 'request').mockReturnValue(of(preparing(false, 30)));
      (nudge.querySelector('.role-flip') as HTMLButtonElement).click();
      expect(component.revealRole).toBe(true);
      expect(render().querySelector('.reveal-nudge .role-flip')?.classList).toContain('open');
      expect(render().querySelector('#nudge-title')?.textContent).toContain('Role kamu: Hitman');
      vi.advanceTimersByTime(2999);
      expect(render().querySelector('.reveal-nudge')).not.toBeNull();
      vi.advanceTimersByTime(1);
      expect(component.readingRole).toBe(false);
      expect(component.revealPrompt).toBe(false);
      // Sudah tercatat di server (mis. setelah memuat ulang halaman): tidak ditegur lagi.
      component.revealRole = false;
      component.game = preparing(true, 30).game;
      expect(component.revealPrompt).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });

  it('holds the last player’s role before showing the game and start curtain', () => {
    vi.useFakeTimers();
    try {
      const request = vi
        .spyOn(TestBed.inject(GameService), 'request')
        .mockReturnValue(of(preparing(false, 34)));
      component.code = 'ABC123';
      component.refresh();
      request.mockReturnValue(of(snapshot()));
      (render().querySelector('.reveal-nudge .role-flip') as HTMLButtonElement).click();
      expect(component.game?.phase).toBe('day');
      expect(component.showPreparation).toBe(true);
      expect(component.transition).toBeNull();
      expect(render().querySelector('.hud')).toBeNull();
      const card = render().querySelector('.reveal-nudge .role-flip') as HTMLButtonElement;
      expect(card.classList).toContain('open');
      expect(card.disabled).toBe(true);
      component.toggleRole();
      expect(component.revealRole).toBe(true);

      vi.advanceTimersByTime(2000);
      const latest = snapshot();
      latest.game.server_time = 102;
      request.mockReturnValue(of(latest));
      component.refresh();
      expect(component.seconds).toBe(18);
      expect(component.showPreparation).toBe(true);
      expect(component.transition).toBeNull();
      vi.advanceTimersByTime(999);
      expect(component.showPreparation).toBe(true);
      vi.advanceTimersByTime(1);
      expect(component.showPreparation).toBe(false);
      expect(component.transition?.phase).toBe('start');
      expect(render().querySelector('.hud')).not.toBeNull();
      expect(component.revealRole).toBe(true);
    } finally {
      fixture.destroy();
      vi.useRealTimers();
    }
  });

  it('does not add another delay when a role was read before the match starts', () => {
    vi.useFakeTimers();
    try {
      const request = vi
        .spyOn(TestBed.inject(GameService), 'request')
        .mockReturnValue(of(preparing()));
      component.code = 'ABC123';
      component.refresh();
      component.toggleRole();
      vi.advanceTimersByTime(3000);
      expect(component.readingRole).toBe(false);
      expect(component.showPreparation).toBe(true);
      component.toggleRole();
      component.toggleRole();
      expect(component.readingRole).toBe(false);
      request.mockReturnValue(of(snapshot()));
      component.refresh();
      expect(component.showPreparation).toBe(false);
      expect(component.transition?.phase).toBe('start');
    } finally {
      fixture.destroy();
      vi.useRealTimers();
    }
  });

  it('automatically opens an unread card at five seconds and preserves the reading time', () => {
    vi.useFakeTimers();
    try {
      const request = vi
        .spyOn(TestBed.inject(GameService), 'request')
        .mockReturnValue(of(preparing(false, 34)));
      component.code = 'ABC123';
      component.refresh();
      expect(component.revealRole).toBe(false);
      request.mockReturnValue(of(preparing(false, 35)));
      component.refresh();
      expect(component.revealRole).toBe(true);
      expect(component.readingRole).toBe(true);
      expect(render().querySelector('.reveal-nudge .role-flip')?.classList).toContain('open');
      component.refresh();
      expect(request).toHaveBeenLastCalledWith('ABC123', { match_id: 'match-1' }, 'reveal');
      vi.advanceTimersByTime(3000);
      request.mockReturnValue(of(preparing(true, 38)));
      component.refresh();
      component.toggleRole();
      component.refresh();
      expect(component.revealRole).toBe(false); // Do not reopen a card the player has already read.
    } finally {
      fixture.destroy();
      vi.useRealTimers();
    }
  });

  it('uses the fallback countdown when AI is not ready', () => {
    const state = preparing(false, 80).game;
    state.preparation!.ready = false;
    state.preparation!.starts_in = null;
    state.preparation!.max_wait = 11;
    component.game = state;
    expect(component.revealPrompt).toBe(false);
    state.preparation!.max_wait = 10;
    expect(component.revealPrompt).toBe(true);
  });

  it('opens the role after reconnect if the last five seconds were missed', () => {
    vi.useFakeTimers();
    try {
      const request = vi
        .spyOn(TestBed.inject(GameService), 'request')
        .mockReturnValue(of(preparing(false, 28)));
      component.code = 'ABC123';
      component.refresh();
      request.mockReturnValue(of(snapshot()));
      component.refresh();
      expect(component.revealRole).toBe(true);
      expect(component.showPreparation).toBe(true);
      vi.advanceTimersByTime(3000);
      expect(component.showPreparation).toBe(false);
    } finally {
      fixture.destroy();
      vi.useRealTimers();
    }
  });

  it('cancels the role-reading timer when the game component is destroyed', () => {
    vi.useFakeTimers();
    try {
      component.game = preparing().game;
      component.toggleRole();
      expect(component.readingRole).toBe(true);
      fixture.destroy();
      vi.advanceTimersByTime(3000);
      expect(component.readingRole).toBe(false);
      expect(component.transition).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it('shows action buttons directly without the discussion heading or explanation', () => {
    component.game = snapshot().game;
    component.game.me = { ...component.game.me, role: 'civilian', can_act: false, ability: null };
    const panel = render().querySelector('.action-panel') as HTMLElement;
    expect(panel.firstElementChild?.classList).toContain('action-buttons');
    expect(panel.querySelector('.skip-button')).not.toBeNull();
    expect(panel.textContent).not.toContain('Diskusi siang');
    expect(panel.textContent).not.toContain('Bicara di chat:');
    expect(panel.querySelector('.action-text')).toBeNull();

    component.game.me.can_act = true;
    component.game.me.ability = 'gag';
    expect(render().querySelector('.action-buttons .green')?.textContent).toContain('Gag Order');
    expect(render().querySelector('.action-buttons .skip-button')).not.toBeNull();
  });

  // TRANSISI: dari layar persiapan, tirai "Ronde 1 dimulai" menutup splash lalu membuka meja.
  it('uses the start curtain when leaving the preparation screen', () => {
    const request = vi
      .spyOn(TestBed.inject(GameService), 'request')
      .mockReturnValue(of(preparing(true)));
    component.code = 'ABC123';
    component.refresh();
    request.mockReturnValue(of(snapshot()));
    component.refresh();
    expect(component.transition).toEqual(
      expect.objectContaining({ phase: 'start', title: 'Ronde 1 dimulai' }),
    );
  });

  // 5 DETIK TERAKHIR: angka besar hanya di fase berjalan, bukan saat persiapan, transisi, atau selesai.
  it('shows a large countdown in the last five seconds of a phase', () => {
    component.game = snapshot().game;
    component.seconds = 6;
    expect(component.finalCountdown).toBe(false);
    component.seconds = 5;
    expect(component.finalCountdown).toBe(true);
    const overlay = render().querySelector('.final-count') as HTMLElement;
    expect(overlay.getAttribute('aria-hidden')).toBe('true');
    expect(overlay.textContent).toContain('5');
    expect(overlay.textContent).toContain('Diskusi segera berakhir');
    expect(render().querySelector('.timer')?.classList).toContain('final');
    // Chat tetap bisa dipakai: overlay tidak menggantikan atau menonaktifkan input.
    expect((render().querySelector('.composer input') as HTMLInputElement).disabled).toBe(false);
    component.seconds = 0;
    expect(component.finalCountdown).toBe(false);
    component.seconds = 3;
    component.transition = { phase: 'night', title: 'Malam', subtitle: '' };
    expect(component.finalCountdown).toBe(false);
    component.transition = null;
    component.game.winner = 'hitman';
    expect(component.finalCountdown).toBe(false);
  });

  // CHAT: pemain yang membaca riwayat tidak ditarik turun; pesan sendiri dan tombol "pesan baru" menurunkan.
  it('keeps the reader position while scrolled up and offers a jump to new messages', () => {
    const state = snapshot();
    const request = vi.spyOn(TestBed.inject(GameService), 'request').mockReturnValue(of(state));
    component.code = 'ABC123';
    component.refresh();
    expect(component.chatAtBottom).toBe(true);
    component.chatAtBottom = false; // pemain menggulir ke atas
    const next = snapshot();
    next.game.messages = [{ id: 'm1', sender: 'NOX', message: 'Halo' }];
    request.mockReturnValue(of(next));
    component.refresh();
    expect(component.newBelow).toBe(1);
    expect(render().querySelector('.chat-jump')?.textContent).toContain('1 pesan baru');
    const own = snapshot();
    own.game.messages = [...next.game.messages, { id: 'm2', sender: 'alice', message: 'Aku?' }];
    request.mockReturnValue(of(own));
    component.refresh();
    expect(component.newBelow).toBe(0);
    expect(component.chatAtBottom).toBe(true);
    component.chatAtBottom = false;
    component.newBelow = 4;
    (render().querySelector('.chat-jump') as HTMLButtonElement).click();
    expect([component.newBelow, component.chatAtBottom]).toEqual([0, true]);
  });

  // KELUAR: konfirmasi dulu; server menandai pemain tereliminasi, lalu tab ini kembali ke menu utama.
  it('leaves the match after confirmation and returns to the main menu', () => {
    component.game = snapshot().game;
    component.code = 'ABC123';
    sessionStorage.setItem('shadow_heist_room', 'ABC123');
    const confirm = vi.spyOn(window, 'confirm');
    const leave = vi
      .spyOn(TestBed.inject(GameService), 'leave')
      .mockReturnValue(of({ left: true }));
    const page = render();
    (page.querySelector('.leave-match') as HTMLButtonElement).click();
    fixture.detectChanges();
    const modal = page.querySelector('.leave-modal') as HTMLElement;
    expect(modal.getAttribute('role')).toBe('alertdialog');
    expect(leave).not.toHaveBeenCalled(); // belum keluar sebelum dikonfirmasi
    (modal.querySelector('.wood-button.red') as HTMLButtonElement).click();
    expect(confirm).not.toHaveBeenCalled(); // tidak memakai dialog bawaan browser
    expect(leave).toHaveBeenCalledWith('ABC123');
    expect(TestBed.inject(Router).navigateByUrl).toHaveBeenCalledWith('/main');
    expect(component.game).toBeNull();
    expect(sessionStorage.getItem('shadow_heist_room')).toBeNull();
    expect(component.leaving).toBe(false);
  });

  it('stays in the match when leaving is cancelled or the network fails', () => {
    component.game = snapshot().game;
    component.code = 'ABC123';
    const leave = vi
      .spyOn(TestBed.inject(GameService), 'leave')
      .mockReturnValue(throwError(() => ({ status: 0, error: null })));
    component.leaveMatch();
    const page = render();
    (page.querySelector('.leave-modal .wood-button.plank') as HTMLButtonElement).click();
    expect(render().querySelector('.leave-modal')).toBeNull();
    expect(leave).not.toHaveBeenCalled();
    component.leaveMatch();
    component.confirmLeaveMatch();
    expect(leave).toHaveBeenCalledTimes(1);
    expect(component.game).not.toBeNull();
    expect(component.error).toContain('Gagal keluar');
    expect(TestBed.inject(Router).navigateByUrl).not.toHaveBeenCalledWith('/main');
  });

  it('marks players who left apart from executed players', () => {
    const game = snapshot().game;
    game.players = [
      { name: 'alice', bot: false, alive: true },
      { name: 'bob', bot: false, alive: false, left: true },
      { name: 'NOX', bot: true, alive: false },
    ];
    component.game = game;
    const stamps = [...render().querySelectorAll('.stamp-dead')].map((s) => s.textContent?.trim());
    expect(stamps).toEqual(['Keluar', 'Dieksekusi']);
    expect(fixture.nativeElement.querySelectorAll('.stamp-left').length).toBe(1);
  });

  it('explains a civilian win when the last Hitman left instead of being executed', () => {
    const game = snapshot().game;
    game.phase = 'finished';
    game.winner = 'civilians';
    game.players = [
      { name: 'alice', bot: false, alive: false, left: true, role: 'hitman' },
      { name: 'NOX', bot: true, alive: true, role: 'civilian' },
    ];
    game.result = {
      reason: 'hitman_executed',
      team: 'hitman',
      outcome: 'lost',
      civilians_alive: 1,
      civilians_hostage: 0,
      civilians_eliminated: 0,
    };
    component.game = game;
    expect(component.resultExplanation).toContain('Hitman telah tersingkir');
  });

  // SIAP: tombol Siap yang langsung memulai ronde 1 tidak meninggalkan pesan "Pilihan dikunci" di meja.
  it('does not leave a locked-choice notice when ready starts round 1', () => {
    const request = vi
      .spyOn(TestBed.inject(GameService), 'request')
      .mockReturnValue(of(preparing(true)));
    component.code = 'ABC123';
    component.refresh();
    request.mockReturnValue(of(snapshot()));
    component.readyUp();
    expect(request).toHaveBeenLastCalledWith('ABC123', { match_id: 'match-1' }, 'ready');
    expect(component.transition?.phase).toBe('start');
    expect(component.notice).toBe('');
  });

  // CATATAN: panel catatan pertandingan dihapus; hasil Tribunal (publik) tampil di tirai pagi.
  // Tribunal (mulai ronde 2) berlanjut ke malam: hasil vote tampil di tirai malam.
  it('drops the match notes panel and shows the Tribunal verdict on the night curtain', () => {
    const state = snapshot();
    state.game.round = 2;
    state.game.phase = 'tribunal';
    state.game.events = ['Permainan dimulai.', 'Malam selesai.'];
    const request = vi.spyOn(TestBed.inject(GameService), 'request').mockReturnValue(of(state));
    component.code = 'ABC123';
    component.refresh();
    const page = render();
    expect(page.textContent).not.toContain('Catatan pertandingan');
    expect(page.textContent).not.toContain('Malam selesai.');
    expect(page.querySelector('.events')).toBeNull();

    const verdict = 'Tribunal mengeksekusi NOX. Role tetap dirahasiakan sampai permainan selesai.';
    const next = snapshot();
    next.game.round = 2;
    next.game.phase = 'night';
    next.game.events = [
      ...state.game.events,
      verdict,
      'Malam tiba. Chat dikunci; lakukan aksi secara rahasia.',
    ];
    request.mockReturnValue(of(next));
    component.refresh();
    expect(component.transition).toEqual(
      expect.objectContaining({ phase: 'night', subtitle: verdict }),
    );
    expect(render().querySelector('.phase-transition')?.textContent).toContain(verdict);
  });

  // INTIP: hasil Peek di kartu target (di atas karakter), bertahan lintas ronde; hanya layar Stalker.
  it('keeps the Peek result on the target card across rounds, only for the Stalker', () => {
    const game = snapshot().game;
    game.players = ['alice', 'NOX', 'bob'].map((name) => ({ name, alive: true }));
    game.phase = 'night';
    game.me = {
      ...game.me,
      role: 'stalker',
      ability: 'peek',
      can_act: false,
      action: { ability: 'peek', target: 'NOX' },
    };
    component.game = game;
    const label = (index: number) =>
      render().querySelectorAll('.player-card')[index].querySelector('.peek-role');
    // Baru dikunci: "?" sampai server menyelesaikan malam.
    expect(label(1)?.textContent).toContain('?');
    expect(label(2)).toBeNull();

    // Malam selesai: role dari intel privat server menggantikan "?".
    game.phase = 'tribunal';
    game.me.action = null;
    game.me.intel = [{ round: 1, name: 'NOX', role: 'hitman' }];
    expect(label(1)?.textContent).toContain('Hitman');
    expect(label(1)?.getAttribute('data-role')).toBe('hitman');
    expect(fixture.nativeElement.querySelectorAll('.player-card.peeked').length).toBe(1);
    // Ronde berikutnya (atau setelah refresh) intel dikirim ulang, jadi label tetap ada.
    game.round = 3;
    game.phase = 'day';
    expect(label(1)?.textContent).toContain('Hitman');
    // Daftar intel di panel kiri sudah diganti label di kartu.
    expect(render().querySelector('.side-panel')?.textContent).not.toContain('Intel');

    // Role lain tidak menampilkan intel walaupun data salah ikut terkirim.
    game.me.role = 'civilian';
    expect(render().querySelector('.peek-role')).toBeNull();
  });

  // JAGA: aura emas hanya di layar Spy, pada target Guard yang dikunci malam ini.
  it('shows the guard aura only on the Spy screen during the night', () => {
    const game = snapshot().game;
    game.players = ['alice', 'NOX', 'bob'].map((name) => ({ name, alive: true }));
    game.phase = 'night';
    game.me = {
      ...game.me,
      role: 'spy',
      ability: 'guard',
      can_act: false,
      action: { ability: 'guard', target: 'bob' },
    };
    component.game = game;
    const cards = render().querySelectorAll('.player-card');
    expect([...cards].map((card) => card.classList.contains('guarded'))).toEqual([
      false,
      false,
      true,
    ]);
    expect(cards[2].textContent).toContain('Kamu menjaga pemain ini');

    // Tribunal: perlindungan malam sudah selesai.
    game.phase = 'tribunal';
    game.me.action = null;
    expect(render().querySelector('.guarded')).toBeNull();

    // Aksi malam role lain (Hostage Hitman) tidak pernah menjadi aura.
    game.phase = 'night';
    game.me = {
      ...game.me,
      role: 'hitman',
      ability: 'hostage',
      action: { ability: 'hostage', target: 'bob' },
    };
    expect(render().querySelector('.guarded')).toBeNull();
  });

  // GAG: label di kartu target untuk Syndicate (me.ally_gags dari server) dan di kartu korban sendiri;
  // pemain lain tidak melihat apa pun.
  it('shows GAG to the Syndicate and the gagged player only', () => {
    const state = snapshot();
    state.game.players = ['alice', 'NOX', 'bob'].map((name) => ({ name, alive: true }));
    vi.spyOn(TestBed.inject(GameService), 'request').mockReturnValue(of(state));
    component.code = 'ABC123';
    component.refresh();
    expect(render().querySelector('.gag-tag')).toBeNull();

    const gag = (index: number) =>
      render().querySelectorAll('.player-card')[index].querySelector('.gag-tag');
    state.game.me = { ...state.game.me, ally_gags: ['NOX'] };
    expect(gag(1)?.textContent).toContain('GAG');
    expect(gag(2)).toBeNull();
    // Server mengosongkan ally_gags saat ronde berganti (Gag berakhir setelah Tribunal).
    state.game.me = { ...state.game.me, ally_gags: [] };
    expect(render().querySelector('.gag-tag')).toBeNull();

    // Korban (NOX) melihat GAG hanya di kartunya sendiri lewat me.gagged dari server.
    state.game.me = {
      ...state.game.me,
      name: 'NOX',
      role: 'civilian',
      ability: null,
      gagged: true,
    };
    expect(gag(1)?.textContent).toContain('GAG');
    expect(fixture.nativeElement.querySelectorAll('.gag-tag').length).toBe(1);
    // Pemain lain yang tidak dibungkam tidak tahu siapa yang kena Gag.
    state.game.me = { ...state.game.me, name: 'bob', gagged: false };
    expect(render().querySelector('.gag-tag')).toBeNull();
  });

  // SANDERA: cap besar dan kartu gelap hanya untuk Hitman (target malam ini) dan korban (kartunya sendiri).
  it('stamps the hostage only for the Hitman target and on the victim own card', () => {
    const game = snapshot().game;
    game.players = ['alice', 'NOX', 'bob'].map((name) => ({ name, alive: true }));
    game.phase = 'night';
    game.me = {
      ...game.me,
      ability: 'hostage',
      can_act: false,
      action: { ability: 'hostage', target: 'bob' },
    };
    component.game = game;
    component.target = 'bob';
    let cards = render().querySelectorAll('.player-card');
    expect(cards[2].querySelector('.stamp-sandera')?.textContent).toBe('Disandera');
    expect(cards[2].querySelector('.player')?.classList).toContain('held');
    expect(cards[2].querySelector('.stamp-target')).toBeNull(); // tidak bertumpuk dengan cap Target
    expect(cards[1].querySelector('.stamp-sandera')).toBeNull();
    // Dua Hitman memilih berbeda: cap mengikuti korban tim dari server, bukan pilihan sendiri.
    game.me = { ...game.me, syndicate_target: 'NOX' };
    component.target = '';
    cards = render().querySelectorAll('.player-card');
    expect(cards[1].querySelector('.stamp-sandera')).not.toBeNull();
    expect(cards[2].querySelector('.stamp-sandera')).toBeNull();
    game.me = { ...game.me, syndicate_target: undefined };

    // Setelah malam tanpa hasil dari server (backend lama tanpa syndicate_hostages): cap hilang.
    game.phase = 'tribunal';
    game.me.action = null;
    component.target = '';
    expect(render().querySelector('.stamp-sandera')).toBeNull();

    // Korban melihat cap hanya di kartunya sendiri; warga lain tidak tahu siapa yang disandera.
    game.me = { ...game.me, name: 'bob', role: 'civilian', ability: null, hostage: true };
    cards = render().querySelectorAll('.player-card');
    expect(cards[2].querySelector('.stamp-sandera')).not.toBeNull();
    expect(fixture.nativeElement.querySelectorAll('.stamp-sandera').length).toBe(1);
    game.me = { ...game.me, name: 'NOX', hostage: false };
    expect(render().querySelector('.stamp-sandera')).toBeNull();

    // Akhir permainan: server membuka status Hostage untuk semua pemain.
    game.phase = 'finished';
    game.winner = 'hitman';
    game.players = game.players.map((player) => ({
      ...player,
      role: player.name === 'alice' ? 'hitman' : 'civilian',
      hostage: player.name === 'bob',
    }));
    cards = render().querySelectorAll('.player-card');
    expect(cards[2].querySelector('.stamp-sandera')).not.toBeNull();
    expect(fixture.nativeElement.querySelectorAll('.stamp-sandera').length).toBe(1);
  });

  // HASIL SANDERA (hanya Hitman): berhasil → cap tetap sampai akhir; gagal (dijaga Guard) → cap
  // "Gagal disandera" pada siang sesudah malamnya, lalu memudar lewat CSS.
  it('keeps a successful hostage stamp and shows a fading failed stamp for the Syndicate', () => {
    const game = snapshot().game;
    game.players = ['alice', 'NOX', 'bob'].map((name) => ({ name, alive: true }));
    game.phase = 'day';
    game.round = 3;
    game.me = {
      ...game.me,
      role: 'hitman',
      action: null,
      syndicate_hostages: [
        { round: 1, name: 'bob', success: true },
        { round: 2, name: 'NOX', success: false },
      ],
    };
    component.game = game;
    component.target = '';
    let cards = render().querySelectorAll('.player-card');
    expect(cards[2].querySelector('.stamp-sandera')?.textContent).toBe('Disandera');
    expect(cards[2].querySelector('.player')?.classList).toContain('held');
    expect(cards[1].querySelector('.stamp-gagal')?.textContent).toBe('Gagal disandera');
    expect(cards[1].querySelector('.player')?.classList).not.toContain('held');
    // Cap gagal hanya pada siang sesudah malamnya; cap berhasil tetap di fase lain.
    game.phase = 'tribunal';
    cards = render().querySelectorAll('.player-card');
    expect(cards[1].querySelector('.stamp-gagal')).toBeNull();
    expect(cards[2].querySelector('.stamp-sandera')).not.toBeNull();
    // Warga tidak pernah menerima data ini, jadi tidak melihat cap apa pun.
    game.phase = 'day';
    game.me = { ...game.me, name: 'alice', role: 'civilian', syndicate_hostages: [] };
    expect(render().querySelector('.stamp-sandera')).toBeNull();
  });
});
