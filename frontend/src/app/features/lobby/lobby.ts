import { isPlatformBrowser } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectorRef,
  Component,
  DestroyRef,
  ElementRef,
  HostListener,
  Inject,
  OnDestroy,
  OnInit,
  PLATFORM_ID,
  ViewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { finalize } from 'rxjs';
import { Room, RoomService } from '../../core/room.service';
import { ProfileMenu } from '../../core/profile-menu';
import { skinImageUrl } from '../../core/asset-preloader';
import { forgetRoom, STORAGE } from '../../core/storage';
import { saveRoomSession } from '../../shared/room-helpers';

// DECORATOR: hubungkan Lobby dengan template, CSS, navigasi, dan binding form.
@Component({
  selector: 'app-lobby',
  imports: [RouterLink, FormsModule, ProfileMenu],
  templateUrl: './lobby.html',
  styleUrls: ['./lobby.css', './lobby-responsive.css'],
})
// CLASS KOMPONEN: mengatur ruangan aktif, roster, pilihan bot, dan masuk chat.
export class Lobby implements OnInit, OnDestroy {
  // STATE/PROPERTY: data ruangan dan status yang ditampilkan di lobby.html.
  username = 'Operative';
  room: Room | null = null;
  error = '';
  busy = false;
  memulai = false; // label PREPARING… hanya untuk permintaan start, bukan tombol bot
  copied = false;
  modeCepat = false;
  capacity = 6;
  helpOpen = false;

  // Fokus kembali ke tombol yang membuka Case File setelah overlay ditutup.
  private helpReturnFocus?: HTMLElement;
  @ViewChild('helpClose') private helpClose?: ElementRef<HTMLButtonElement>;
  @ViewChild('helpDialog') private helpDialog?: ElementRef<HTMLElement>;

  // Pratinjau memakai durasi dari server; fallback hanya untuk backend lama sebelum deployment.
  get durations() {
    if (this.room?.match_durations) return this.room.match_durations;
    if (this.room?.phase_durations)
      return this.room.phase_durations[this.modeCepat ? 'quick' : 'standard'];
    const jumlahPemain = this.room
      ? Math.max(4, this.room.members.length + this.room.bots.length)
      : this.capacity;
    return this.modeCepat
      ? {
          day: Math.ceil((jumlahPemain * 10) / 3),
          night: Math.ceil(jumlahPemain * 2.5),
          tribunal: Math.ceil(jumlahPemain * 2.5),
        }
      : {
          day: jumlahPemain * 20,
          night: jumlahPemain * 5,
          tribunal: Math.ceil(jumlahPemain * 7.5) + 30,
        };
  }
  // PRIVATE PROPERTY: simpan timer polling agar dapat dihentikan ketika meninggalkan lobby.
  private timerPolling?: ReturnType<typeof setInterval>;
  // Polling latar tidak memakai `busy`: aplikasi zoneless tidak menggambar ulang tombol saat polling
  // dimulai, jadi klik yang jatuh di tengah polling dulu ditolak diam-diam (tombol bot harus ditekan
  // dua kali). Nomor aksi membuang respons polling yang lebih tua dari klik terakhir.
  private sedangPolling = false;
  private nomorAksiTerakhir = 0;

  // CONSTRUCTOR: Angular menyediakan service ruangan, router, platform, dan fasilitas lifecycle.
  constructor(
    @Inject(PLATFORM_ID) private readonly platformId: object,
    private readonly router: Router,
    private readonly rooms: RoomService,
    private readonly changeDetector: ChangeDetectorRef,
    private readonly destroyRef: DestroyRef,
  ) {}

  // LIFECYCLE METHOD: baca sesi browser, ambil kembali ruangan, lalu perbarui roster tiap 3 detik.
  ngOnInit(): void {
    if (!isPlatformBrowser(this.platformId)) return;
    try {
      this.username =
        JSON.parse(localStorage.getItem(STORAGE.user) ?? '{}').username || this.username;
    } catch {}
    const kodeRoom = sessionStorage.getItem(STORAGE.room);
    // Tampilkan dulu snapshot dari Main (respons create/join barusan) agar layar room tidak
    // menunggu satu round trip; request berikutnya tetap menggantinya dengan data server.
    this.room = this.bacaSnapshotRoom(kodeRoom);
    if (localStorage.getItem(STORAGE.token)) this.restoreRoom();
    else if (kodeRoom) this.kirimPermintaanRoom('GET', '/' + encodeURIComponent(kodeRoom));
    this.timerPolling = setInterval(() => {
      if (this.room && !this.busy && !this.sedangPolling)
        this.kirimPermintaanRoom('GET', '/' + this.room.code, undefined, true);
    }, 3000);
  }

  // Nama tampilan host; username hanya cadangan untuk snapshot lama tanpa label.
  get ownerLabel(): string {
    const owner = this.room?.members.find((member) => member.name === this.room?.owner);
    return owner?.label || this.room?.owner || '';
  }

  // Foto skin pemain untuk roster; skin kosong memakai skin bawaan yang sama dengan game.
  skinUrl(skinId: string | undefined): string {
    return skinImageUrl(skinId || 'dexter');
  }

  // Snapshot room tab ini hanya dipakai bila kodenya sama dengan pointer room yang aktif.
  private bacaSnapshotRoom(code: string | null): Room | null {
    if (!code) return null;
    try {
      const room = JSON.parse(sessionStorage.getItem(STORAGE.roomSnapshot) ?? 'null');
      const valid = room?.code === code && Array.isArray(room.members) && Array.isArray(room.bots);
      return valid ? (room as Room) : null;
    } catch {
      return null;
    }
  }

  // LIFECYCLE METHOD: hentikan polling saat komponen dilepas agar tidak berjalan di belakang.
  ngOnDestroy(): void {
    if (this.timerPolling) clearInterval(this.timerPolling);
  }

  // Case File adalah overlay agar aturan lengkap tidak mengambil tinggi waiting room.
  openHelp(event?: Event): void {
    this.helpReturnFocus =
      event?.currentTarget instanceof HTMLElement ? event.currentTarget : undefined;
    this.helpOpen = true;
    queueMicrotask(() => this.helpClose?.nativeElement.focus());
  }

  closeHelp(): void {
    if (!this.helpOpen) return;
    this.helpOpen = false;
    queueMicrotask(() => this.helpReturnFocus?.focus());
  }

  @HostListener('document:keydown.escape')
  closeHelpOnEscape(): void {
    this.closeHelp();
  }

  // Case File bersifat modal: Tab dan Shift+Tab tetap berputar di dalam dialog.
  @HostListener('document:keydown', ['$event'])
  jagaFokusDalamPanduan(event: KeyboardEvent): void {
    if (event.key !== 'Tab' || !this.helpOpen || !this.helpDialog) return;
    const focusable = Array.from(
      this.helpDialog.nativeElement.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ),
    );
    if (!focusable.length) {
      event.preventDefault();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const elemenAktif = document.activeElement;
    if (event.shiftKey && elemenAktif === first) {
      event.preventDefault();
      last.focus();
    } else if (
      !event.shiftKey &&
      (elemenAktif === last || !this.helpDialog.nativeElement.contains(elemenAktif))
    ) {
      event.preventDefault();
      first.focus();
    }
  }

  // Jumlah bot yang ikut dan batasnya (BOT_MAKS di backend); snapshot lama tanpa angka ini memakai daftar bot.
  get jumlahBot(): number {
    return this.room?.bot_count ?? this.room?.bots.length ?? 0;
  }

  get batasBot(): number {
    return this.room?.bot_max ?? 5;
  }

  // Tombol bot aktif hanya untuk host di lobby dan selama tidak ada permintaan yang berjalan.
  // Alur: 1 host, lobby, tidak sibuk? -> 2.1.1 tambah: di bawah batas dan masih ada kursi kosong
  //                                   \> 2.2.1 kurangi: masih ada bot
  bisaUbahBot(aksi: 'tambah' | 'kurangi'): boolean {
    const room = this.room;
    if (!room || this.busy || room.owner !== this.username || room.phase !== 'lobby') return false;
    if (aksi === 'kurangi') return this.jumlahBot > 0;
    const kursiTerisi = room.members.length + this.jumlahBot;
    return this.jumlahBot < this.batasBot && kursiTerisi < (room.capacity ?? this.capacity);
  }

  // METHOD EVENT TOMBOL: sekali tekan menambah atau mengurangi satu bot. `busy` menahan klik kedua sampai respons
  // datang; izin host, batas, dan kursi kosong tetap dicek backend.
  // Alur: 1 tombol boleh dipakai? -> 2 POST /bot {aksi} -> 3 snapshot baru menggantikan room
  ubahBot(aksi: 'tambah' | 'kurangi'): void {
    if (!this.room || !this.bisaUbahBot(aksi)) return;
    this.memulai = false;
    this.kirimPermintaanRoom('POST', '/' + this.room.code + '/bot', { aksi });
  }

  // START: backend memeriksa host/jumlah peserta lalu mengacak role.
  startGame(): void {
    if (!this.room || this.busy) return;
    this.memulai = true;
    this.kirimPermintaanRoom('POST', '/' + this.room.code + '/start', { quick: this.modeCepat });
  }

  // Keluar hanya dari lobby atau game selesai; tidak mengeluarkan pemain lain.
  leaveRoom(): void {
    if (!this.room || this.busy) return;
    this.busy = true;
    this.rooms
      .request('POST', '/' + this.room.code + '/leave')
      .pipe(
        takeUntilDestroyed(this.destroyRef),
        finalize(() => {
          this.busy = false;
          this.changeDetector.markForCheck();
        }),
      )
      .subscribe({
        next: () => {
          this.room = null;
          this.error = '';
          this.copied = false;
          forgetRoom();
          void this.router.navigateByUrl('/main');
        },
        error: (error: HttpErrorResponse) => {
          this.error = error.error?.detail || 'Gagal keluar ruangan.';
        },
      });
  }

  // Ambil keanggotaan terbaru dari server dan pulihkan tampilan lobby setelah login ulang.
  restoreRoom(): void {
    if (this.busy) return;
    this.busy = true;
    this.rooms
      .current()
      .pipe(
        takeUntilDestroyed(this.destroyRef),
        finalize(() => {
          this.busy = false;
          this.changeDetector.markForCheck();
        }),
      )
      .subscribe({
        next: (room) => {
          this.room = room;
          this.error = '';
          if (room) saveRoomSession(room);
          else forgetRoom();
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
    this.changeDetector.markForCheck();
  }

  // METHOD EVENT TOMBOL: simpan ruangan dan tanda navigasi pada tab ini, lalu buka /game.
  // Tanda lokal bukan otorisasi backend; koneksi chat tetap memeriksa token dan keanggotaan.
  enterGame(): void {
    if (!this.room || this.busy) return;
    saveRoomSession(this.room);
    sessionStorage.setItem(STORAGE.gameEntry, 'allowed');
    void this.router.navigateByUrl('/game');
  }

  // PRIVATE METHOD: jalankan Observable dari RoomService, kelola loading dan hasil/error.
  // takeUntilDestroyed membatalkan subscription saat komponen dilepas; finalize membuka UI.
  private kirimPermintaanRoom(
    method: 'GET' | 'POST',
    path: string,
    body?: unknown,
    pollingLatar = false,
  ): void {
    const nomorAksi = pollingLatar ? this.nomorAksiTerakhir : ++this.nomorAksiTerakhir;
    if (pollingLatar) this.sedangPolling = true;
    else this.busy = true;
    this.rooms
      .request(method, path, body)
      .pipe(
        takeUntilDestroyed(this.destroyRef),
        finalize(() => {
          if (pollingLatar) this.sedangPolling = false;
          else this.busy = false;
          this.changeDetector.markForCheck();
        }),
      )
      .subscribe({
        next: (room) => {
          // Pengguna menekan tombol saat polling berjalan: snapshot polling sudah basi.
          if (nomorAksi !== this.nomorAksiTerakhir) return;
          // Tab di latar bisa melewatkan layar persiapan yang singkat: fase apa pun selain lobby berarti mulai.
          const baruDimulai = this.room?.phase === 'lobby' && room.phase !== 'lobby';
          this.room = room;
          this.error = '';
          sessionStorage.setItem(STORAGE.room, room.code);
          // Host maupun anggota lain langsung masuk ke layar persiapan begitu pertandingan dimulai.
          if (path.endsWith('/start') || baruDimulai) {
            this.busy = false;
            this.enterGame();
          }
        },
        error: (error: HttpErrorResponse) => {
          this.error = error.error?.detail || 'Server belum bisa dihubungi. Coba lagi.';
          if (error.status === 401) {
            localStorage.removeItem(STORAGE.token);
            void this.router.navigateByUrl('/login');
          }
          if (method === 'GET' && error.status === 400) {
            this.room = null;
            sessionStorage.removeItem(STORAGE.room);
          }
        },
      });
  }
}
