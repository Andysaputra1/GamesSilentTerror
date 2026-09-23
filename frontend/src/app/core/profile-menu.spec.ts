import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter, Router } from '@angular/router';
import { ProfileMenu } from './profile-menu';
import { SessionService } from './session.service';
import { ActiveMatchService } from './active-match.service';

describe('profile logout', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    TestBed.configureTestingModule({
      imports: [ProfileMenu],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);
    localStorage.setItem('shadow_heist_access_token', 'test-session');
    localStorage.setItem('shadow_heist_access_token_expires_at', '2099-01-01');
    localStorage.setItem('shadow_heist_user', '{"username":"alice"}');
    for (const key of ['shadow_heist_room', 'shadow_heist_room_snapshot', 'shadow_heist_game_entry']) {
      sessionStorage.setItem(key, 'old-room');
    }
  });
  afterEach(() => {
    TestBed.inject(HttpTestingController).verify();
    localStorage.clear();
    sessionStorage.clear();
  });

  it('opens the profile menu and revokes the session before clearing storage and redirecting', () => {
    const fixture = TestBed.createComponent(ProfileMenu);
    fixture.componentRef.setInput('username', 'alice');
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.logout-button')).toBeNull();
    fixture.nativeElement.querySelector('.profile-trigger').click();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.profile-trigger').getAttribute('aria-expanded')).toBe('true');
    fixture.nativeElement.querySelector('.logout-button').click();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.logout-button').disabled).toBe(true);
    const request = TestBed.inject(HttpTestingController).expectOne(r => r.url.endsWith('/api/auth/logout'));
    expect(request.request.method).toBe('POST');
    expect(request.request.headers.get('Authorization')).toBe('Bearer test-session');
    expect(localStorage.getItem('shadow_heist_access_token')).toBe('test-session');
    request.flush(null, { status: 204, statusText: 'No Content' });
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    expect(TestBed.inject(Router).navigateByUrl).toHaveBeenCalledWith('/login', { replaceUrl: true });
    fixture.destroy();
  });

  it('keeps a failed logout retryable and does not pretend the server session was revoked', () => {
    const fixture = TestBed.createComponent(ProfileMenu);
    fixture.componentInstance.toggle();
    fixture.componentInstance.logout();
    TestBed.inject(HttpTestingController).expectOne(r => r.url.endsWith('/logout'))
      .flush({}, { status: 503, statusText: 'Unavailable' });
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[role=alert]').textContent).toContain('coba lagi');
    expect(fixture.nativeElement.querySelector('.logout-button').disabled).toBe(false);
    expect(localStorage.getItem('shadow_heist_access_token')).toBe('test-session');
    expect(TestBed.inject(Router).navigateByUrl).not.toHaveBeenCalled();
    fixture.destroy();
  });

  it('clears an already expired server session', () => {
    TestBed.inject(SessionService).logout().subscribe();
    TestBed.inject(HttpTestingController).expectOne(r => r.url.endsWith('/logout'))
      .flush({}, { status: 401, statusText: 'Unauthorized' });
    expect(localStorage.getItem('shadow_heist_access_token')).toBeNull();
  });

  it('ignores an active-match response arriving during logout', () => {
    let active: unknown = 'pending';
    TestBed.inject(ActiveMatchService).lookup().subscribe(value => active = value);
    const pending = TestBed.inject(HttpTestingController).expectOne(r => r.url.endsWith('/active'));
    TestBed.inject(SessionService).logout().subscribe();
    pending.flush({ active: { code: 'ABC123', match_id: 'one' } });
    expect(active).toBeNull();
    TestBed.inject(HttpTestingController).expectOne(r => r.url.endsWith('/logout')).flush(null);
  });

  it('closes on Escape and returns focus to the profile button', () => {
    const fixture = TestBed.createComponent(ProfileMenu);
    fixture.detectChanges();
    fixture.componentInstance.toggle();
    fixture.detectChanges();
    fixture.nativeElement.querySelector('.logout-button').dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
    fixture.detectChanges();
    expect(fixture.componentInstance.open()).toBe(false);
    expect(document.activeElement).toBe(fixture.nativeElement.querySelector('.profile-trigger'));
    fixture.destroy();
  });
});
