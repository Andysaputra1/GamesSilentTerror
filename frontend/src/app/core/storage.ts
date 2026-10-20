import { HttpHeaders } from '@angular/common/http';

// Kunci penyimpanan browser milik aplikasi. Satu sumber, karena salah ketik satu kunci memutus sesi
// atau pemulihan room tanpa error apa pun.
export const STORAGE = {
  // localStorage: sesi login (dibagi semua tab).
  token: 'shadow_heist_access_token',
  tokenExpiresAt: 'shadow_heist_access_token_expires_at',
  user: 'shadow_heist_user',
  // sessionStorage: pointer room tab ini; role dan izin tetap dari backend.
  room: 'shadow_heist_room',
  roomSnapshot: 'shadow_heist_room_snapshot',
  gameEntry: 'shadow_heist_game_entry',
  // sessionStorage: undangan layar penuh sudah dijawab di tab ini.
  fullscreenAsked: 'shadow_heist_fullscreen_asked',
} as const;

// Header Bearer untuk API backend; bawaannya token sesi yang sedang tersimpan.
export function authHeaders(token = localStorage.getItem(STORAGE.token)): HttpHeaders {
  return new HttpHeaders({ Authorization: 'Bearer ' + (token ?? '') });
}

// Lepas room di tab ini: kode, snapshot lobby, dan izin masuk layar game.
export function forgetRoom(): void {
  for (const key of [STORAGE.room, STORAGE.roomSnapshot, STORAGE.gameEntry])
    sessionStorage.removeItem(key);
}
