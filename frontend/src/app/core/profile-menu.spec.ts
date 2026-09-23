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
    for (const key of [
      'shadow_heist_room',
      'shadow_heist_room_snapshot',
      'shadow_heist_game_entry',
    ]) {
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
    expect(
      fixture.nativeElement.querySelector('.profile-trigger').getAttribute('aria-expanded'),
    ).toBe('true');
    fixture.nativeElement.querySelector('.logout-button').click();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.logout-button').disabled).toBe(true);
    const request = TestBed.inject(HttpTestingController).expectOne((r) =>
      r.url.endsWith('/api/auth/logout'),
    );
    expect(request.request.method).toBe('POST');
    expect(request.request.headers.get('Authorization')).toBe('Bearer test-session');
    expect(localStorage.getItem('shadow_heist_access_token')).toBe('test-session');
    request.flush(null, { status: 204, statusText: 'No Content' });
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    expect(TestBed.inject(Router).navigateByUrl).toHaveBeenCalledWith('/login', {
      replaceUrl: true,
    });
    fixture.destroy();
  });

  it('keeps a failed logout retryable and does not pretend the server session was revoked', () => {
    const fixture = TestBed.createComponent(ProfileMenu);
    fixture.componentInstance.toggle();
    fixture.componentInstance.logout();
    TestBed.inject(HttpTestingController)
      .expectOne((r) => r.url.endsWith('/logout'))
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
    TestBed.inject(HttpTestingController)
      .expectOne((r) => r.url.endsWith('/logout'))
      .flush({}, { status: 401, statusText: 'Unauthorized' });
    expect(localStorage.getItem('shadow_heist_access_token')).toBeNull();
  });

  it('ignores an active-match response arriving during logout', () => {
    let active: unknown = 'pending';
    TestBed.inject(ActiveMatchService)
      .lookup()
      .subscribe((value) => (active = value));
    const pending = TestBed.inject(HttpTestingController).expectOne((r) =>
      r.url.endsWith('/active'),
    );
    TestBed.inject(SessionService).logout().subscribe();
    pending.flush({ active: { code: 'ABC123', match_id: 'one' } });
    expect(active).toBeNull();
    TestBed.inject(HttpTestingController)
      .expectOne((r) => r.url.endsWith('/logout'))
      .flush(null);
  });

  it('closes on Escape and returns focus to the profile button', () => {
    const fixture = TestBed.createComponent(ProfileMenu);
    fixture.detectChanges();
    fixture.componentInstance.toggle();
    fixture.detectChanges();
    fixture.nativeElement
      .querySelector('.logout-button')
      .dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    fixture.detectChanges();
    expect(fixture.componentInstance.open()).toBe(false);
    expect(document.activeElement).toBe(fixture.nativeElement.querySelector('.profile-trigger'));
    fixture.destroy();
  });

  // Submit form adalah jalur bersama untuk Enter dan tombol Simpan; server menentukan hasil akhirnya.
  it('saves the edited display name and restores it in a new profile component', async () => {
    localStorage.setItem(
      'shadow_heist_user',
      JSON.stringify({ username: 'alice', display_name: 'Alice' }),
    );
    const fixture = TestBed.createComponent(ProfileMenu);
    fixture.componentRef.setInput('username', 'alice');
    fixture.detectChanges();
    fixture.componentInstance.toggle();
    fixture.detectChanges();
    fixture.nativeElement.querySelector('.edit-name').click();
    fixture.detectChanges();
    await fixture.whenStable();
    const input = fixture.nativeElement.querySelector('input') as HTMLInputElement;
    expect(input.value).toBe('Alice');
    input.value = '  Alice Baru  ';
    input.dispatchEvent(new Event('input'));
    fixture.nativeElement
      .querySelector('form')
      .dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    fixture.detectChanges();
    expect(fixture.componentInstance.saving()).toBe(true);
    expect(fixture.componentInstance.displayName).toBe('Alice');
    fixture.componentInstance.saveName();
    const request = TestBed.inject(HttpTestingController).expectOne((r) =>
      r.url.endsWith('/api/auth/me'),
    );
    expect(request.request.method).toBe('POST');
    expect(request.request.headers.get('Authorization')).toBe('Bearer test-session');
    expect(request.request.body).toEqual({ display_name: 'Alice Baru' });
    request.flush({ username: 'alice', display_name: 'Alice Baru' });
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.profile-trigger').textContent).toContain(
      'Alice Baru',
    );
    expect(fixture.componentInstance.editing()).toBe(false);
    expect(JSON.parse(localStorage.getItem('shadow_heist_user')!).username).toBe('alice');
    fixture.destroy();
    const restored = TestBed.createComponent(ProfileMenu);
    restored.detectChanges();
    expect(restored.componentInstance.displayName).toBe('Alice Baru');
    restored.destroy();
  });

  it('keeps failed edits retryable and leaves the saved name unchanged', () => {
    const fixture = TestBed.createComponent(ProfileMenu);
    fixture.componentRef.setInput('username', 'alice');
    fixture.detectChanges();
    const profile = fixture.componentInstance;
    profile.editName();
    profile.draftName = 'New Name';
    profile.saveName();
    TestBed.inject(HttpTestingController)
      .expectOne((r) => r.url.endsWith('/me'))
      .flush({}, { status: 503, statusText: 'Unavailable' });
    expect(profile.displayName).toBe('alice');
    expect(profile.editing()).toBe(true);
    expect(profile.saving()).toBe(false);
    expect(profile.error()).toContain('belum berhasil');
    expect(localStorage.getItem('shadow_heist_user')).toBe('{"username":"alice"}');
    fixture.destroy();
  });

  it('updates username and notifies the lobby only after the server accepts it', () => {
    const fixture = TestBed.createComponent(ProfileMenu);
    fixture.componentRef.setInput('username', 'alice');
    fixture.detectChanges();
    const profile = fixture.componentInstance;
    const changed = vi.fn();
    profile.profileChanged.subscribe(changed);
    profile.editName();
    profile.draftName = 'Alice Detective';
    profile.draftUsername = 'alice_detective';
    profile.saveName();
    const request = TestBed.inject(HttpTestingController).expectOne((r) => r.url.endsWith('/me'));
    expect(request.request.body).toEqual({
      display_name: 'Alice Detective',
      username: 'alice_detective',
    });
    expect(changed).not.toHaveBeenCalled();
    request.flush({ username: 'alice_detective', display_name: 'Alice Detective' });
    expect(changed).toHaveBeenCalledWith({
      username: 'alice_detective',
      display_name: 'Alice Detective',
    });
    fixture.destroy();
  });

  it('validates blank names and cancels edits without sending requests', () => {
    const fixture = TestBed.createComponent(ProfileMenu);
    const profile = fixture.componentInstance;
    profile.editName();
    profile.draftName = '   ';
    profile.saveName();
    expect(profile.error()).toContain('1–100');
    profile.cancelEdit();
    expect(profile.editing()).toBe(false);
    TestBed.inject(HttpTestingController).expectNone((r) => r.url.endsWith('/me'));
    fixture.destroy();
  });

  it('does not overwrite another session with a late profile response', () => {
    const fixture = TestBed.createComponent(ProfileMenu);
    fixture.detectChanges();
    fixture.componentInstance.editName();
    fixture.componentInstance.draftName = 'Late Name';
    fixture.componentInstance.saveName();
    const pending = TestBed.inject(HttpTestingController).expectOne((r) => r.url.endsWith('/me'));
    localStorage.setItem('shadow_heist_access_token', 'new-session');
    localStorage.setItem('shadow_heist_user', '{"username":"bob"}');
    pending.flush({ username: 'alice', display_name: 'Late Name' });
    expect(localStorage.getItem('shadow_heist_user')).toBe('{"username":"bob"}');
    expect(fixture.componentInstance.saved()).toBe(false);
    fixture.destroy();
  });
});
