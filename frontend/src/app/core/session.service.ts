import { HttpClient, HttpErrorResponse, HttpHeaders } from '@angular/common/http';
import { Injectable, signal } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, defer, finalize, of, tap, throwError, timeout } from 'rxjs';
import { backendUrl } from './backend-url';

@Injectable({ providedIn: 'root' })
export class SessionService {
  readonly loggingOut = signal(false);

  // Sediakan HTTP untuk pencabutan token dan router untuk kembali ke halaman login.
  constructor(
    private readonly http: HttpClient,
    private readonly router: Router,
  ) {}

  // Hapus hanya data akun dan pointer ruangan milik aplikasi dari penyimpanan browser.
  clearLocalSession(): void {
    for (const key of [
      'shadow_heist_access_token',
      'shadow_heist_access_token_expires_at',
      'shadow_heist_user',
    ]) {
      localStorage.removeItem(key);
    }
    for (const key of [
      'shadow_heist_room',
      'shadow_heist_room_snapshot',
      'shadow_heist_game_entry',
    ]) {
      sessionStorage.removeItem(key);
    }
  }

  // Cabut token sebelum membersihkan sesi; HTTP 401 berarti sesi sudah tidak berlaku.
  logout() {
    return defer(() => {
      this.loggingOut.set(true);
      const token = localStorage.getItem('shadow_heist_access_token');
      const revoke = token
        ? this.http
            .post<void>(
              backendUrl() + '/api/auth/logout',
              {},
              {
                headers: new HttpHeaders({ Authorization: 'Bearer ' + token }),
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
