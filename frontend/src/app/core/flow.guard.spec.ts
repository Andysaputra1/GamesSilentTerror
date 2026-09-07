import { TestBed } from '@angular/core/testing';
import { provideRouter, Router, UrlTree } from '@angular/router';

import { gameEntryGuard, loginRedirectGuard } from './flow.guard';

describe('navigation flow guards', () => {
  let router: Router;

  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    TestBed.configureTestingModule({ providers: [provideRouter([])] });
    router = TestBed.inject(Router);
  });

  it('sends an authenticated player away from Login to Main Page', () => {
    localStorage.setItem('shadow_heist_access_token', 'valid-token');
    localStorage.setItem('shadow_heist_access_token_expires_at', new Date(Date.now() + 60_000).toISOString());

    const result = TestBed.runInInjectionContext(() => loginRedirectGuard({} as never, {} as never));

    expect(router.serializeUrl(result as UrlTree)).toBe('/main');
  });

  it('blocks a direct Game URL until Lobby grants access', () => {
    const result = TestBed.runInInjectionContext(() => gameEntryGuard({} as never, {} as never));

    expect(router.serializeUrl(result as UrlTree)).toBe('/main');
  });
});
