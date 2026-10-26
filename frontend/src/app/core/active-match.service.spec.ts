import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { provideRouter, Router, UrlTree } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { Observable, of } from 'rxjs';
import { routes } from '../app.routes';
import { ActiveMatchService, activeMatchGuard } from './active-match.service';
import { Room, RoomService } from './room.service';
import { SessionService } from './session.service';
import { STORAGE } from './storage';

const waitingRoom: Room = {
  code: 'ABC123',
  owner: 'alice',
  members: [{ name: 'alice', skin_id: 'dexter' }],
  bots: [],
  bot_enabled: false,
  phase: 'lobby',
};

@Component({ template: '' })
class GuardedPage {}

describe('active match recovery', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
  });
  afterEach(() => {
    TestBed.inject(HttpTestingController).verify();
    localStorage.clear();
    sessionStorage.clear();
  });

  function navigate(url: string) {
    return TestBed.runInInjectionContext(() =>
      activeMatchGuard({} as never, { url } as never),
    ) as Observable<boolean | UrlTree>;
  }

  it('recovers a fresh tab and redirects main to server-owned match', () => {
    localStorage.setItem('shadow_heist_access_token', 'test-token');
    const results: (boolean | UrlTree)[] = [];
    navigate('/main').subscribe((value) => results.push(value));
    const request = TestBed.inject(HttpTestingController).expectOne((r) =>
      r.url.endsWith('/api/rooms/active'),
    );
    expect(request.request.headers.get('Authorization')).toBe('Bearer test-token');
    request.flush({ active: { code: 'ABC123', match_id: 'one' } });
    expect(TestBed.inject(Router).serializeUrl(results[0] as UrlTree)).toBe('/game');
    expect(sessionStorage.getItem('shadow_heist_room')).toBe('ABC123');
  });

  it('allows game after restoring storage and allows main once finished', () => {
    localStorage.setItem('shadow_heist_access_token', 'test-token');
    navigate('/game').subscribe((value) => expect(value).toBe(true));
    TestBed.inject(HttpTestingController)
      .expectOne((r) => r.url.endsWith('/active'))
      .flush({ active: { code: 'ABC123', match_id: 'one' } });
    navigate('/main').subscribe((value) => expect(value).toBe(true));
    TestBed.inject(HttpTestingController)
      .expectOne((r) => r.url.endsWith('/active'))
      .flush({ active: null });
    TestBed.inject(HttpTestingController)
      .expectOne((r) => r.url.endsWith('/current'))
      .flush({ room: { ...waitingRoom, phase: 'finished' } });
  });

  it('opens the game from the lobby without waiting for the active-match lookup', () => {
    localStorage.setItem('shadow_heist_access_token', 'test-token');
    sessionStorage.setItem('shadow_heist_game_entry', 'allowed');
    const result = TestBed.runInInjectionContext(() =>
      activeMatchGuard({} as never, { url: '/game' } as never),
    );
    expect(result).toBe(true);
    TestBed.inject(HttpTestingController).expectNone((r) => r.url.endsWith('/active'));
  });

  it('does not request private state for anonymous visitors', () => {
    TestBed.inject(ActiveMatchService)
      .lookup()
      .subscribe((value) => expect(value).toBe(null));
    navigate('/games/checker').subscribe((value) => expect(value).toBe(true));
    TestBed.inject(HttpTestingController).expectNone((r) => r.url.includes('/api/rooms'));
  });

  it.each(['/main', '/login', '/main?from=lobby#top', '/game', '/game#cards'])(
    'returns a player with a waiting room from %s to the lobby',
    (url) => {
      localStorage.setItem(STORAGE.token, 'test-token');
      const results: (boolean | UrlTree)[] = [];
      navigate(url).subscribe((value) => results.push(value));
      const http = TestBed.inject(HttpTestingController);
      http.expectOne((r) => r.url.endsWith('/active')).flush({ active: null });
      const request = http.expectOne((r) => r.url.endsWith('/current'));
      expect(request.request.headers.get('Authorization')).toBe('Bearer test-token');
      request.flush({ room: waitingRoom });

      expect(TestBed.inject(Router).serializeUrl(results[0] as UrlTree)).toBe('/lobby');
      expect(sessionStorage.getItem(STORAGE.room)).toBe('ABC123');
      expect(JSON.parse(sessionStorage.getItem(STORAGE.roomSnapshot)!)).toEqual(waitingRoom);
      expect(sessionStorage.getItem(STORAGE.gameEntry)).toBeNull();
    },
  );

  it('lets the lobby restore itself without another room request or redirect loop', () => {
    localStorage.setItem(STORAGE.token, 'test-token');
    navigate('/lobby?from=main#room').subscribe((value) => expect(value).toBe(true));
    const http = TestBed.inject(HttpTestingController);
    http.expectOne((r) => r.url.endsWith('/active')).flush({ active: null });
    http.expectNone((r) => r.url.endsWith('/current'));
  });

  it('allows main after leaving and discards a stale room snapshot', () => {
    localStorage.setItem(STORAGE.token, 'test-token');
    sessionStorage.setItem(STORAGE.room, 'ABC123');
    sessionStorage.setItem(STORAGE.roomSnapshot, JSON.stringify(waitingRoom));
    sessionStorage.setItem(STORAGE.gameEntry, 'allowed');
    navigate('/main').subscribe((value) => expect(value).toBe(true));
    const http = TestBed.inject(HttpTestingController);
    http.expectOne((r) => r.url.endsWith('/active')).flush({ active: null });
    http.expectOne((r) => r.url.endsWith('/current')).flush({ room: null });
    expect(sessionStorage.getItem(STORAGE.room)).toBeNull();
    expect(sessionStorage.getItem(STORAGE.roomSnapshot)).toBeNull();
    expect(sessionStorage.getItem(STORAGE.gameEntry)).toBeNull();
  });

  it('redirects directly to game if the host starts during room recovery', () => {
    localStorage.setItem(STORAGE.token, 'test-token');
    const results: (boolean | UrlTree)[] = [];
    navigate('/main').subscribe((value) => results.push(value));
    const http = TestBed.inject(HttpTestingController);
    http.expectOne((r) => r.url.endsWith('/active')).flush({ active: null });
    http
      .expectOne((r) => r.url.endsWith('/current'))
      .flush({
        room: { ...waitingRoom, phase: 'preparing' },
      });
    expect(TestBed.inject(Router).serializeUrl(results[0] as UrlTree)).toBe('/game');
    expect(sessionStorage.getItem(STORAGE.room)).toBe('ABC123');
    expect(sessionStorage.getItem(STORAGE.gameEntry)).toBe('allowed');
  });

  it.each(['logout', 'account-change'])('ignores a room response after %s', (change) => {
    localStorage.setItem(STORAGE.token, 'test-token');
    navigate('/main').subscribe((value) => expect(value).toBe(true));
    const http = TestBed.inject(HttpTestingController);
    http.expectOne((r) => r.url.endsWith('/active')).flush({ active: null });
    const request = http.expectOne((r) => r.url.endsWith('/current'));
    if (change === 'logout') TestBed.inject(SessionService).loggingOut.set(true);
    else localStorage.setItem(STORAGE.token, 'another-token');
    request.flush({ room: waitingRoom });
    expect(sessionStorage.getItem(STORAGE.room)).toBeNull();
  });

  it('does not trap navigation when room recovery fails', () => {
    localStorage.setItem(STORAGE.token, 'test-token');
    navigate('/main').subscribe((value) => expect(value).toBe(true));
    const http = TestBed.inject(HttpTestingController);
    http.expectOne((r) => r.url.endsWith('/active')).flush({ active: null });
    http
      .expectOne((r) => r.url.endsWith('/current'))
      .flush(null, {
        status: 503,
        statusText: 'Service Unavailable',
      });
  });

  it('keeps real route navigation in the lobby until the player leaves or the match starts', async () => {
    TestBed.configureTestingModule({
      imports: [GuardedPage],
      providers: [
        provideRouter(
          routes.map((route) =>
            route.redirectTo === undefined
              ? { ...route, component: GuardedPage, loadComponent: undefined }
              : route,
          ),
        ),
      ],
    });
    localStorage.setItem(STORAGE.token, 'test-token');
    localStorage.setItem(STORAGE.tokenExpiresAt, new Date(Date.now() + 60_000).toISOString());
    const lookup = vi.spyOn(TestBed.inject(ActiveMatchService), 'lookup').mockReturnValue(of(null));
    const current = vi
      .spyOn(TestBed.inject(RoomService), 'current')
      .mockReturnValue(of(waitingRoom));
    const harness = await RouterTestingHarness.create('/lobby');
    const router = TestBed.inject(Router);

    for (const url of ['/main', '/login', '/game', '/unknown-page']) {
      await harness.navigateByUrl(url);
      expect(router.url).toBe('/lobby');
    }

    current.mockReturnValue(of(null));
    await harness.navigateByUrl('/main');
    expect(router.url).toBe('/main');

    lookup.mockReturnValue(of({ code: 'ABC123', match_id: 'one' }));
    await harness.navigateByUrl('/lobby');
    expect(router.url).toBe('/game');
  });
});
