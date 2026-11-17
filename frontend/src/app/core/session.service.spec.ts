import { HttpClient, HttpHeaders, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { sesiDitolakInterceptor } from './session.service';

// INTERCEPTOR 401: sesi yang ditolak server dihapus sekali di satu tempat, bukan di tiap halaman.
describe('sesiDitolakInterceptor', () => {
  let http: HttpClient;
  let httpMock: HttpTestingController;
  const header = (token: string) => ({
    headers: new HttpHeaders({ Authorization: 'Bearer ' + token }),
  });
  const tolak = (url: string) =>
    httpMock
      .expectOne(url)
      .flush({ detail: 'Sesi tidak valid.' }, { status: 401, statusText: 'Unauthorized' });

  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([sesiDitolakInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
    });
    vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);
    http = TestBed.inject(HttpClient);
    httpMock = TestBed.inject(HttpTestingController);
    localStorage.setItem('shadow_heist_access_token', 'token-a');
    localStorage.setItem('shadow_heist_access_token_expires_at', '2099-01-01');
    localStorage.setItem('shadow_heist_user', '{"username":"alice"}');
    sessionStorage.setItem('shadow_heist_room', 'ABC123');
  });

  afterEach(() => {
    httpMock.verify();
    localStorage.clear();
    sessionStorage.clear();
  });

  it('clears the session and opens login when the server rejects the stored token', () => {
    const error = vi.fn();
    http.get('/api/rooms/active', header('token-a')).subscribe({ error });
    tolak('/api/rooms/active');
    expect(error).toHaveBeenCalled(); // pemanggil tetap menerima error-nya
    expect(localStorage.getItem('shadow_heist_access_token')).toBeNull();
    expect(sessionStorage.getItem('shadow_heist_room')).toBeNull();
    expect(sessionStorage.getItem('shadow_heist_notice')).toBe(
      'Sesi berakhir. Silakan login kembali.',
    );
    expect(TestBed.inject(Router).navigateByUrl).toHaveBeenCalledWith('/login', {
      replaceUrl: true,
    });
  });

  it('ignores login failures, stale tokens, and logout', () => {
    http.post('/api/auth/login', {}).subscribe({ error: () => {} });
    tolak('/api/auth/login');
    http.get('/api/auth/me', header('token-lama')).subscribe({ error: () => {} });
    tolak('/api/auth/me');
    http.post('/api/auth/logout', {}, header('token-a')).subscribe({ error: () => {} });
    tolak('/api/auth/logout');
    expect(localStorage.getItem('shadow_heist_access_token')).toBe('token-a');
    expect(TestBed.inject(Router).navigateByUrl).not.toHaveBeenCalled();
  });
});
