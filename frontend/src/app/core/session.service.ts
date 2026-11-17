import { isPlatformBrowser } from '@angular/common';
import { HttpClient, HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject, Injectable, PLATFORM_ID, signal } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, defer, finalize, map, of, tap, timeout } from 'rxjs';
import { backendUrl } from './backend-url';
import { authHeaders, forgetRoom, STORAGE, titipPemberitahuan } from './storage';

export interface UserProfile {
  username: string;
  displayName: string;
  skinId?: string;
}

// Ubah respons API (snake_case) menjadi profil aplikasi (camelCase).
function toUserProfile(respons: {
  username: string;
  display_name: string;
  skin_id?: string;
}): UserProfile {
  return { username: respons.username, displayName: respons.display_name, skinId: respons.skin_id };
}

// SESI LOGIN: profil, skin, dan logout. Token disimpan di localStorage; backend tetap memvalidasinya.
@Injectable({ providedIn: 'root' })
export class SessionService {
  readonly loggingOut = signal(false);

  // Sediakan HTTP untuk pencabutan token dan router untuk kembali ke halaman login.
  constructor(
    private readonly http: HttpClient,
    private readonly router: Router,
  ) {}

  // Simpan profil di server terlebih dahulu; abaikan respons jika sesi berganti saat request berjalan.
  updateProfile(displayName: string, username?: string) {
    const token = localStorage.getItem(STORAGE.token);
    return this.http
      .post<{ username: string; display_name: string; skin_id?: string }>(
        backendUrl() + '/api/auth/me',
        { display_name: displayName, ...(username ? { username } : {}) },
        {
          headers: authHeaders(token),
        },
      )
      .pipe(
        timeout(10_000),
        map(toUserProfile),
        tap((profile) => this.storeProfile(token, profile)),
      );
  }

  // Ambil profil terbaru dari server (termasuk skin yang mungkin diganti di perangkat lain).
  refreshProfile() {
    const token = localStorage.getItem(STORAGE.token);
    return this.http
      .get<{ username: string; display_name: string; skin_id?: string }>(
        backendUrl() + '/api/auth/me',
        { headers: authHeaders(token) },
      )
      .pipe(
        timeout(10_000),
        map(toUserProfile),
        tap((profile) => this.storeProfile(token, profile)),
      );
  }

  // Simpan skin pilihan ke akun; lobby dan pertandingan membacanya dari server, bukan dari browser.
  updateSkin(skinId: string) {
    const token = localStorage.getItem(STORAGE.token);
    return this.http
      .put<{ skin_id: string }>(
        backendUrl() + '/api/auth/skin',
        { skin_id: skinId },
        { headers: authHeaders(token) },
      )
      .pipe(
        timeout(10_000),
        map((response) => response.skin_id),
        tap((saved) => {
          const profile = JSON.parse(localStorage.getItem(STORAGE.user) ?? '{}');
          this.storeProfile(token, { ...profile, skinId: saved });
        }),
      );
  }

  // Tulis profil hanya bila sesi tidak berganti selama request berjalan.
  private storeProfile(token: string | null, profile: UserProfile): void {
    if (!token || this.loggingOut() || localStorage.getItem(STORAGE.token) !== token) {
      throw new Error('Sesi berubah. Silakan login kembali.');
    }
    localStorage.setItem(STORAGE.user, JSON.stringify(profile));
  }

  // Hapus hanya data akun dan pointer ruangan milik aplikasi dari penyimpanan browser.
  clearLocalSession(): void {
    for (const key of [STORAGE.token, STORAGE.tokenExpiresAt, STORAGE.user])
      localStorage.removeItem(key);
    forgetRoom();
  }

  // Cabut token di server lalu bersihkan sesi lokal. HTTP 401 berarti sesi memang sudah tidak berlaku. Gagal lain
  // (server mati, 5xx, timeout) tetap membersihkan sesi lokal supaya pengguna bisa keluar atau ganti akun; token di
  // server berakhir sendiri saat kedaluwarsa, dan halaman login menampilkan peringatannya.
  logout() {
    return defer(() => {
      this.loggingOut.set(true);
      const token = localStorage.getItem(STORAGE.token);
      const pencabutanToken = token
        ? this.http
            .post<void>(
              backendUrl() + '/api/auth/logout',
              {},
              {
                headers: authHeaders(token),
              },
            )
            .pipe(timeout(10000))
        : of(undefined);
      return pencabutanToken.pipe(
        catchError((error: unknown) => {
          if (!(error instanceof HttpErrorResponse && error.status === 401))
            titipPemberitahuan(
              'Server belum bisa dihubungi, jadi logout hanya dilakukan di browser ini. Sesi lama di server berakhir sendiri saat kedaluwarsa.',
            );
          return of(undefined);
        }),
        tap(() => {
          this.clearLocalSession();
          void this.router.navigateByUrl('/login', { replaceUrl: true });
        }),
        finalize(() => this.loggingOut.set(false)),
      );
    });
  }
}

// SESI DITOLAK SERVER: 401 untuk token yang masih tersimpan berarti sesinya sudah tidak berlaku di server (akun
// dinonaktifkan, sesi dicabut, atau jam perangkat keliru), walau masa berlaku lokal belum habis. Sesi lokal dihapus lalu
// pengguna dibawa ke /login, supaya tidak terjebak di halaman yang tampak sudah login. Request login dan daftar tidak
// membawa token, request dengan token lama (akun sudah berganti di tab lain) dilewati, dan logout menangani 401-nya
// sendiri.
export const sesiDitolakInterceptor: HttpInterceptorFn = (request, next) => {
  const session = inject(SessionService);
  const router = inject(Router);
  const diBrowser = isPlatformBrowser(inject(PLATFORM_ID));
  return next(request).pipe(
    tap({
      error: (error: unknown) => {
        if (!diBrowser || !(error instanceof HttpErrorResponse) || error.status !== 401) return;
        const token = localStorage.getItem(STORAGE.token);
        if (
          !token ||
          request.headers.get('Authorization') !== 'Bearer ' + token ||
          request.url.endsWith('/api/auth/logout')
        )
          return;
        session.clearLocalSession();
        titipPemberitahuan('Sesi berakhir. Silakan login kembali.');
        void router.navigateByUrl('/login', { replaceUrl: true });
      },
    }),
  );
};
