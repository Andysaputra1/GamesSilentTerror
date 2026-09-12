import { Injectable } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { timeout } from 'rxjs';

// INTERFACE: bentuk data ruangan dari API; hanya tipe TypeScript, bukan class atau tabel DB.
export interface Room {
  code: string;
  owner: string;
  members: string[];
  bot_enabled: boolean;
  bots: string[];
  phase: string;
}

// DECORATOR: daftarkan service agar Angular dapat menyuntikkannya ke komponen.
@Injectable({ providedIn: 'root' })
// CLASS SERVICE: pusat request HTTP ruangan agar komponen tidak mengulang URL dan header.
export class RoomService {
  // CONSTRUCTOR: Angular menyediakan HttpClient melalui dependency injection.
  constructor(private readonly http: HttpClient) {}
  // METHOD: siapkan request ber-token dengan timeout 10 detik.
  // Mengembalikan Observable; request dikirim ketika pemanggil melakukan subscribe.
  // Hanya dipanggil di browser karena menggunakan window dan localStorage.
  request(method: 'GET' | 'POST', path: string, body?: unknown) {
    const base = window.location.protocol + '//' + window.location.hostname + ':8000/api/rooms';
    const headers = new HttpHeaders({
      Authorization: 'Bearer ' + (localStorage.getItem('shadow_heist_access_token') ?? ''),
    });
    return this.http.request<Room>(method, base + path, { body, headers }).pipe(timeout(10000));
  }
}
