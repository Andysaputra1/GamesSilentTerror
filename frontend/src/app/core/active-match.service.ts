import { backendUrl } from './backend-url';
import { isPlatformBrowser } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Inject, Injectable, PLATFORM_ID, inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { catchError, map, of, switchMap, timeout } from 'rxjs';
import { saveRoomSession } from '../shared/room-helpers';
import { RoomService } from './room.service';
import { SessionService } from './session.service';
import { authHeaders, forgetRoom, STORAGE } from './storage';

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

// Pulihkan pertandingan atau lobby saat pindah halaman, termasuk tab baru / login ulang.
// Room yang pertandingannya selesai tidak memaksa redirect, sehingga Main dan survei tetap tersedia.
export const activeMatchGuard: CanActivateFn = (_, state) => {
  const service = inject(ActiveMatchService);
  const rooms = inject(RoomService);
  const session = inject(SessionService);
  const router = inject(Router);
  const platform = inject(PLATFORM_ID);
  if (!isPlatformBrowser(platform)) return true;
  const path = state.url.split(/[?#]/)[0];
  const isGame = path === '/game';
  const token = localStorage.getItem(STORAGE.token);
  const fallback = () =>
    isGame && sessionStorage.getItem(STORAGE.gameEntry) !== 'allowed'
      ? router.createUrlTree(['/main'])
      : true;
  // Masuk dari lobby yang sudah mulai: jangan menahan layar game satu round trip backend.
  // Masuk lobby baru menghapus tanda 'allowed' milik pertandingan sebelumnya.
  if (isGame && sessionStorage.getItem(STORAGE.gameEntry) === 'allowed') return true;
  return service.lookup().pipe(
    switchMap((active) => {
      if (active) {
        service.remember(active);
        return of(isGame ? true : router.createUrlTree(['/game']));
      }
      // Lobby memulihkan room sendiri; jangan menambah request atau membuat redirect berulang.
      if (
        path === '/lobby' ||
        !token ||
        session.loggingOut() ||
        localStorage.getItem(STORAGE.token) !== token
      )
        return of(fallback());

      return rooms.current().pipe(
        map((room) => {
          // Respons akun lama tidak boleh mengembalikan pengguna yang sudah logout/ganti akun.
          if (session.loggingOut() || localStorage.getItem(STORAGE.token) !== token)
            return fallback();
          if (!room) {
            forgetRoom();
            return fallback();
          }
          if (room.phase === 'finished') return fallback();
          saveRoomSession(room);
          if (room.phase === 'lobby') return router.createUrlTree(['/lobby']);
          // Host bisa mulai di sela lookup /active dan /current; langsung ikuti fase terbaru.
          sessionStorage.setItem(STORAGE.gameEntry, 'allowed');
          return isGame ? true : router.createUrlTree(['/game']);
        }),
      );
    }),
    catchError(() => of(fallback())),
  );
};
