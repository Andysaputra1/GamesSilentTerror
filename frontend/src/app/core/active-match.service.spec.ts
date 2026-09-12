import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { provideRouter, Router, UrlTree } from '@angular/router';
import { Observable } from 'rxjs';
import { ActiveMatchService, activeMatchGuard } from './active-match.service';

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
  });

  it('does not request private state for anonymous visitors', () => {
    TestBed.inject(ActiveMatchService)
      .lookup()
      .subscribe((value) => expect(value).toBe(null));
    navigate('/games/checker').subscribe((value) => expect(value).toBe(true));
    TestBed.inject(HttpTestingController).expectNone((r) => r.url.includes('/api/rooms'));
  });
});
