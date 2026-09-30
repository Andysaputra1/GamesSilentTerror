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
});
