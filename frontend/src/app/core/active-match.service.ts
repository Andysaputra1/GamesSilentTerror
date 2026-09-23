import { backendUrl } from './backend-url';
import { isPlatformBrowser } from '@angular/common';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Inject, Injectable, PLATFORM_ID, inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { catchError, map, of, timeout } from 'rxjs';
import { SessionService } from './session.service';

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
    const token = localStorage.getItem('shadow_heist_access_token');
    if (!token || this.session.loggingOut()) return of(null);
    const base = `${backendUrl()}/api/rooms/active`;
    return this.http
      .get<{ active: ActiveMatch | null }>(base, {
        headers: new HttpHeaders({ Authorization: 'Bearer ' + token }),
      })
      .pipe(
        timeout(10000),
        map((result) =>
          !this.session.loggingOut() && localStorage.getItem('shadow_heist_access_token') === token
            ? result.active
            : null,
        ),
      );
  }

  // Simpan pointer saja; role dan izin tetap diambil melalui API privat.
  remember(active: ActiveMatch): void {
    sessionStorage.setItem('shadow_heist_room', active.code);
    sessionStorage.setItem('shadow_heist_game_entry', 'allowed');
  }
}

// Berlaku juga pada tab baru / login ulang; pertandingan selesai tidak memaksa redirect.
export const activeMatchGuard: CanActivateFn = (_, state) => {
  const service = inject(ActiveMatchService);
  const router = inject(Router);
  const platform = inject(PLATFORM_ID);
  if (!isPlatformBrowser(platform)) return true;
  const isGame = state.url.split('?')[0] === '/game';
  return service.lookup().pipe(
    map((active) => {
      if (active) {
        service.remember(active);
        return isGame ? true : router.createUrlTree(['/game']);
      }
      return isGame && sessionStorage.getItem('shadow_heist_game_entry') !== 'allowed'
        ? router.createUrlTree(['/main'])
        : true;
    }),
    catchError(() =>
      of(
        isGame
          ? sessionStorage.getItem('shadow_heist_game_entry') === 'allowed' ||
              router.createUrlTree(['/main'])
          : true,
      ),
    ),
  );
};
