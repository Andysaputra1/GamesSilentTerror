import { backendUrl } from './backend-url';
import { isPlatformBrowser } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Inject, Injectable, PLATFORM_ID, inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { catchError, map, of, timeout } from 'rxjs';
import { SessionService } from './session.service';
import { authHeaders, STORAGE } from './storage';

interface ActiveMatch {
  code: string;
  match_id: string;
}

// Pemulihan lintas tab/login: backend menentukan room aktif, bukan data tab lama.
@Injectable({ providedIn: 'root' })
export class ActiveMatchService {
  // Sediakan HTTP, status logout, dan platform untuk pemulihan pertandingan.
  constructor(
    private readonly http: HttpClient,
    private readonly session: SessionService,
    @Inject(PLATFORM_ID) private readonly platform: object,
  ) {}

  // Cari pertandingan aktif; abaikan respons jika token berubah atau logout dimulai.
  lookup() {
    if (!isPlatformBrowser(this.platform)) return of(null);
    const token = localStorage.getItem(STORAGE.token);
    if (!token || this.session.loggingOut()) return of(null);
    const base = `${backendUrl()}/api/rooms/active`;
    return this.http
      .get<{ active: ActiveMatch | null }>(base, {
        headers: authHeaders(token),
      })
      .pipe(
        timeout(10000),
        map((result) =>
          !this.session.loggingOut() && localStorage.getItem(STORAGE.token) === token
            ? result.active
            : null,
        ),
      );
  }

  // Simpan pointer saja; role dan izin tetap diambil melalui API privat.
  remember(active: ActiveMatch): void {
    sessionStorage.setItem(STORAGE.room, active.code);
    sessionStorage.setItem(STORAGE.gameEntry, 'allowed');
  }
}

// Berlaku juga pada tab baru / login ulang; pertandingan selesai tidak memaksa redirect.
export const activeMatchGuard: CanActivateFn = (_, state) => {
  const service = inject(ActiveMatchService);
  const router = inject(Router);
  const platform = inject(PLATFORM_ID);
  if (!isPlatformBrowser(platform)) return true;
  const isGame = state.url.split('?')[0] === '/game';
  // Masuk dari lobby (tanda 'allowed'): semua cabang di bawah menghasilkan true, jadi jangan
  // menahan layar game satu round trip backend. Polling App tetap memulihkan pointer room.
  if (isGame && sessionStorage.getItem(STORAGE.gameEntry) === 'allowed') return true;
  return service.lookup().pipe(
    map((active) => {
      if (active) {
        service.remember(active);
        return isGame ? true : router.createUrlTree(['/game']);
      }
      return isGame && sessionStorage.getItem(STORAGE.gameEntry) !== 'allowed'
        ? router.createUrlTree(['/main'])
        : true;
    }),
    catchError(() =>
      of(
        isGame
          ? sessionStorage.getItem(STORAGE.gameEntry) === 'allowed' ||
              router.createUrlTree(['/main'])
          : true,
      ),
    ),
  );
};
