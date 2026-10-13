import { backendUrl } from './backend-url';
import { Injectable } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { map, timeout } from 'rxjs';

// INTERFACE: bentuk data ruangan dari API; hanya tipe TypeScript, bukan class atau tabel DB.
export interface PhaseDurations {
  day: number;
  night: number;
  tribunal: number;
}

export interface RoomMember {
  name: string;
  skin_id: string;
}

export interface Room {
  code: string;
  owner: string;
  members: RoomMember[];
  bot_enabled: boolean;
  bots: string[];
  phase: string;
  capacity?: number;
  match_durations?: PhaseDurations | null;
  phase_durations?: { standard: PhaseDurations; quick: PhaseDurations };
}

// DECORATOR: daftarkan service agar Angular dapat menyuntikkannya ke komponen.
@Injectable({ providedIn: 'root' })
// CLASS SERVICE: pusat request HTTP ruangan agar komponen tidak mengulang URL dan header.
export class RoomService {
  // CONSTRUCTOR: Angular menyediakan HttpClient melalui dependency injection.
  // function Object() { [native code] }
  constructor(private readonly http: HttpClient) {}
  // Pulihkan keanggotaan ruangan dari server tanpa mengandalkan cache tab.
  current() {
    return this.http
      .get<{ room: Room | null }>(backendUrl() + '/api/rooms/current', {
        headers: new HttpHeaders({
          Authorization: 'Bearer ' + (localStorage.getItem('shadow_heist_access_token') ?? ''),
        }),
      })
      .pipe(
        timeout(10000),
        map((response) => response.room),
      );
  }
  // METHOD: siapkan request ber-token dengan timeout 10 detik.
  // Mengembalikan Observable; request dikirim ketika pemanggil melakukan subscribe.
  // Hanya dipanggil di browser karena menggunakan window dan localStorage.
  request(method: 'GET' | 'POST', path: string, body?: unknown) {
    const base = backendUrl() + '/api/rooms';
    const headers = new HttpHeaders({
      Authorization: 'Bearer ' + (localStorage.getItem('shadow_heist_access_token') ?? ''),
    });
    return this.http.request<Room>(method, base + path, { body, headers }).pipe(timeout(10000));
  }
}
