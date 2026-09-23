import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';

import { Game } from './game';
import { provideHttpClient } from '@angular/common/http';
import { of, throwError } from 'rxjs';
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
        max_rounds: 8,
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

  it('releases loading on network errors so retry remains available', () => {
    component.code = 'ABC123';
    vi.spyOn(TestBed.inject(GameService), 'request').mockReturnValue(
      throwError(() => ({ status: 503 })),
    );
    component.refresh();
    expect(component.busy).toBe(false);
    expect(component.error).toBe('Server belum bisa dihubungi.');
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
    game.players = ['a','b','c','d','e','f'].map(name => ({name,bot:false,alive:true}));
    game.tribunal_votes = [{target:'f',voters:['a','b','c','d','e']}];
    component.game = game;
    fixture.componentRef.changeDetectorRef.markForCheck();
    fixture.detectChanges();
    const cards = fixture.nativeElement.querySelectorAll('.player-card');
    const target = cards[5] as HTMLElement;
    expect(target.querySelector('.vote-count')?.textContent).toContain('5 vote');
    expect(target.querySelectorAll('.voter-badge').length).toBe(5);
    expect(target.querySelector('.voter-badges')?.textContent).toContain('+1');
    expect(target.querySelectorAll('.voter-details p').length).toBe(5);
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
    game.me = {...game.me, role: 'spy', alive: false, can_chat: false, can_act: false};
    game.result = {reason: 'hitman_executed', team: 'civilians', outcome: 'won', civilians_alive: 2, civilians_hostage: 1, civilians_eliminated: 1};
    component.game = game;
    fixture.componentRef.changeDetectorRef.markForCheck();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.result').textContent).toContain('KAMU MENANG');
    expect(fixture.nativeElement.querySelector('.result').textContent).toContain('Hitman telah dieksekusi');
    expect(fixture.nativeElement.querySelector('.action-panel')).toBeNull();
  });

  it('explains permanent hostage and temporary gag separately without exposing roster statuses', () => {
    component.game = snapshot().game;
    component.game.me.hostage = true;
    expect(component.privateStatus).toContain('sampai pertandingan berakhir');
    component.game.me.hostage = false;
    component.game.me.gagged = true;
    expect(component.privateStatus).toContain('Aksi malam tetap boleh');
    fixture.componentRef.changeDetectorRef.markForCheck();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.players').textContent).not.toContain('HOSTAGE');
    expect(fixture.nativeElement.querySelector('.players').textContent).not.toContain('GAG');
  });

  it('shows a loss for a hostage when Hitman wins and a neutral result for a draw', () => {
    component.game = snapshot().game;
    component.game.me.role = 'civilian';
    component.game.me.hostage = true;
    component.game.winner = 'hitman';
    expect(component.outcomeLabel).toBe('KAMU KALAH');
    component.game.winner = 'draw';
    expect(component.outcomeLabel).toBe('SERI');
    expect(component.resultExplanation).toContain('8 ronde');
  });
});
