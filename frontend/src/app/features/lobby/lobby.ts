import { isPlatformBrowser } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectorRef,
  Component,
  DestroyRef,
  Inject,
  OnDestroy,
  OnInit,
  PLATFORM_ID,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { finalize } from 'rxjs';
import { gameEntryStorageKey } from '../../core/flow.guard';
import { Room, RoomService } from '../../core/room.service';
import { ProfileMenu } from '../../core/profile-menu';

// DECORATOR: hubungkan Lobby dengan template, CSS, navigasi, dan binding form.
@Component({
  selector: 'app-lobby',
  imports: [RouterLink, FormsModule, ProfileMenu],
  templateUrl: './lobby.html',
  styleUrl: './lobby.css',
})
// CLASS KOMPONEN: mengatur buat/gabung ruangan, roster, pilihan bot, dan masuk chat.
export class Lobby implements OnInit, OnDestroy {
  // STATE/PROPERTY: data ruangan, input kode, dan status yang ditampilkan di lobby.html.
  username = 'Operative';
  room: Room | null = null;
  joinCode = '';
  error = '';
  busy = false;
  copied = false;
  quick = false;
  // PRIVATE PROPERTY: simpan timer polling agar dapat dihentikan ketika meninggalkan lobby.
  private timer?: ReturnType<typeof setInterval>;

  // CONSTRUCTOR: Angular menyediakan service ruangan, router, platform, dan fasilitas lifecycle.
  constructor(
    @Inject(PLATFORM_ID) private readonly platformId: object,
    private readonly router: Router,
    private readonly rooms: RoomService,
    private readonly cdr: ChangeDetectorRef,
    private readonly destroy: DestroyRef,
  ) {}

  // LIFECYCLE METHOD: baca sesi browser, ambil kembali ruangan, lalu perbarui roster tiap 3 detik.
  ngOnInit(): void {
    if (!isPlatformBrowser(this.platformId)) return;
    try {
      this.username =
        JSON.parse(localStorage.getItem('shadow_heist_user') ?? '{}').username || this.username;
    } catch {}
    const code = sessionStorage.getItem('shadow_heist_room');
    if (localStorage.getItem('shadow_heist_access_token')) this.restoreRoom();
    else if (code) this.load('GET', '/' + encodeURIComponent(code));
    this.timer = setInterval(() => {
      if (this.room && !this.busy) this.load('GET', '/' + this.room.code);
    }, 3000);
  }

  // LIFECYCLE METHOD: hentikan polling saat komponen dilepas agar tidak berjalan di belakang.
  ngOnDestroy(): void {
    if (this.timer) clearInterval(this.timer);
  }

  // METHOD EVENT TOMBOL: minta backend membuat ruangan dan kode baru.
  createRoom(): void {
    if (!this.busy && !this.room) this.load('POST', '');
  }

  // METHOD EVENT FORM: periksa format kode, lalu minta backend menambahkan keanggotaan.
  joinRoom(): void {
    if (this.busy || this.room) return;
    const code = this.joinCode.trim().toUpperCase();
    if (!/^[A-F0-9]{6}$/.test(code)) {
      this.error = 'Masukkan kode ruangan 6 karakter.';
      return;
    }
    this.load('POST', '/join', { code });
  }

  // METHOD EVENT TOMBOL: minta perubahan pilihan NOX; izin pembuat ruangan diperiksa backend.
  toggleBot(): void {
    if (this.room && !this.busy)
      this.load('POST', '/' + this.room.code + '/bot', { enabled: !this.room.bot_enabled });
  }

  // START: backend memeriksa host/jumlah peserta lalu mengacak role.
  startGame(): void {
    if (this.room && !this.busy)
      this.load('POST', '/' + this.room.code + '/start', { quick: this.quick });
  }

  // Keluar hanya dari lobby atau game selesai; tidak mengeluarkan pemain lain.
  leaveRoom(): void {
    if (!this.room || this.busy) return;
    this.busy = true;
    this.rooms
      .request('POST', '/' + this.room.code + '/leave')
      .pipe(
        takeUntilDestroyed(this.destroy),
        finalize(() => {
          this.busy = false;
          this.cdr.markForCheck();
        }),
      )
      .subscribe({
        next: () => {
          this.room = null;
          this.error = '';
          this.copied = false;
          sessionStorage.removeItem('shadow_heist_room');
          sessionStorage.removeItem('shadow_heist_room_snapshot');
          sessionStorage.removeItem(gameEntryStorageKey);
        },
        error: (error: HttpErrorResponse) => {
          this.error = error.error?.detail || 'Gagal keluar ruangan.';
        },
      });
  }

  restoreRoom(): void {
    if (this.busy) return;
    this.busy = true;
    this.rooms.current().pipe(
      takeUntilDestroyed(this.destroy),
      finalize(() => { this.busy = false; this.cdr.markForCheck(); }),
    ).subscribe({
      next: room => {
        this.room = room;
        this.error = '';
        if (room) sessionStorage.setItem('shadow_heist_room', room.code);
        else {
          sessionStorage.removeItem('shadow_heist_room');
          sessionStorage.removeItem('shadow_heist_room_snapshot');
          sessionStorage.removeItem(gameEntryStorageKey);
        }
      },
      error: (error: HttpErrorResponse) => {
        this.error = 'Ruangan belum bisa dipulihkan. Coba muat ulang.';
        if (error.status === 401) void this.router.navigateByUrl('/login');
      },
    });
  }

  // ASYNC METHOD: tunggu penyalinan kode ke clipboard; berikan pesan jika browser menolaknya.
  async copyCode(): Promise<void> {
    if (!this.room) return;
    try {
      await navigator.clipboard.writeText(this.room.code);
      this.copied = true;
    } catch {
      this.error = 'Salin kode ruangan secara manual.';
    }
    this.cdr.markForCheck();
  }

  // METHOD EVENT TOMBOL: simpan ruangan dan tanda navigasi pada tab ini, lalu buka /game.
  // Tanda lokal bukan otorisasi backend; koneksi chat tetap memeriksa token dan keanggotaan.
  enterGame(): void {
    if (!this.room || this.busy) return;
    sessionStorage.setItem('shadow_heist_room', this.room.code);
    sessionStorage.setItem('shadow_heist_room_snapshot', JSON.stringify(this.room));
    sessionStorage.setItem(gameEntryStorageKey, 'allowed');
    void this.router.navigateByUrl('/game');
  }

  // PRIVATE METHOD: jalankan Observable dari RoomService, kelola loading dan hasil/error.
  // takeUntilDestroyed membatalkan subscription saat komponen dilepas; finalize membuka UI.
  private load(method: 'GET' | 'POST', path: string, body?: unknown): void {
    this.busy = true;
    this.rooms
      .request(method, path, body)
      .pipe(
        takeUntilDestroyed(this.destroy),
        finalize(() => {
          this.busy = false;
          this.cdr.markForCheck();
        }),
      )
      .subscribe({
        next: (room) => {
          this.room = room;
          this.error = '';
          sessionStorage.setItem('shadow_heist_room', room.code);
          if (path.endsWith('/start')) {
            this.busy = false;
            this.enterGame();
          }
        },
        error: (error: HttpErrorResponse) => {
          this.error = error.error?.detail || 'Server belum bisa dihubungi. Coba lagi.';
          if (error.status === 401) {
            localStorage.removeItem('shadow_heist_access_token');
            void this.router.navigateByUrl('/login');
          }
          if (method === 'GET' && error.status === 400) {
            this.room = null;
            sessionStorage.removeItem('shadow_heist_room');
          }
        },
      });
  }
}
