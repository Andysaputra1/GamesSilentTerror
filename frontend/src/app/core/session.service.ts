import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, signal } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, defer, finalize, map, of, tap, throwError, timeout } from 'rxjs';
import { backendUrl } from './backend-url';
import { authHeaders, forgetRoom, STORAGE } from './storage';

export interface UserProfile {
  username: string;
  displayName: string;
  skinId?: string;
}

// Transform API response (snake_case) to TypeScript interface (camelCase).
function toUserProfile(raw: {
  username: string;
  display_name: string;
  skin_id?: string;
}): UserProfile {
  return { username: raw.username, displayName: raw.display_name, skinId: raw.skin_id };
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

  // Cabut token sebelum membersihkan sesi; HTTP 401 berarti sesi sudah tidak berlaku.
  logout() {
    return defer(() => {
      this.loggingOut.set(true);
      const token = localStorage.getItem(STORAGE.token);
      const revoke = token
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
      return revoke.pipe(
        catchError((error: unknown) =>
          error instanceof HttpErrorResponse && error.status === 401
            ? of(undefined)
            : throwError(() => error),
        ),
        tap(() => {
          this.clearLocalSession();
          void this.router.navigateByUrl('/login', { replaceUrl: true });
        }),
        finalize(() => this.loggingOut.set(false)),
      );
    });
  }
}
