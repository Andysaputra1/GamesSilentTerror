import { isPlatformBrowser } from '@angular/common';
import {
  ChangeDetectorRef,
  Component,
  Inject,
  NgZone,
  OnDestroy,
  OnInit,
  PLATFORM_ID,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { io, Socket } from 'socket.io-client';
import { Room } from '../../core/room.service';

// INTERFACE: bentuk satu pesan yang ditampilkan dalam daftar chat.
interface ChatMessage {
  sender: string;
  message: string;
}
// INTERFACE: bentuk kartu role untuk pratinjau tampilan, bukan state role resmi dari server.
interface Role {
  name: string;
  icon: string;
  objective: string;
  action: string;
}

// DECORATOR: hubungkan Game dengan HTML/CSS dan aktifkan binding input pesan.
@Component({
  selector: 'app-game',
  standalone: true,
  imports: [FormsModule, RouterLink],
  templateUrl: './game.html',
  styleUrl: './game.css',
})
// CLASS KOMPONEN: mengatur pratinjau kartu, koneksi Socket.IO, dan tampilan chat.
export class Game implements OnInit, OnDestroy {
  // PROPERTY KONFIGURASI: nama bot dan katalog kartu warga untuk mode latihan.
  readonly botName = 'NOX';
  readonly roles: Role[] = [
    {
      name: 'CIVILIAN',
      icon: '◉',
      objective: 'Bertahan hidup dan temukan Hitman.',
      action: 'OBSERVE',
    },
    {
      name: 'STALKER',
      icon: '⌕',
      objective: 'Peek: intip identitas satu pemain, sekali setiap dua ronde.',
      action: 'PEEK',
    },
    {
      name: 'SPY',
      icon: '◈',
      objective: 'Guard: lindungi satu warga; jangan pilih target sama dua malam berurutan.',
      action: 'GUARD',
    },
  ];
  // STATE/PROPERTY: status animasi, koneksi, ruangan, dan pesan yang dibaca template.
  playerName = 'Operative';
  draftMessage = '';
  isGagged = false;
  isShuffling = true;
  isRoleRevealed = false;
  gameReady = false;
  isChatConnected = false;
  isAiThinking = false;
  assignedRole: Role = this.roles[0];
  room: Room | null = null;
  messages: ChatMessage[] = [
    {
      sender: 'SYSTEM',
      message:
        'Mode latihan chat. Kartu peran adalah pratinjau; aksi malam dan voting belum aktif.',
    },
  ];
  // PRIVATE PROPERTY: koneksi dan timer internal; dibersihkan ketika keluar halaman.
  private socket?: Socket;
  private shuffleInterval?: ReturnType<typeof setInterval>;
  private revealTimeout?: ReturnType<typeof setTimeout>;
  private readyTimeout?: ReturnType<typeof setTimeout>;
  private accessToken = '';

  // CONSTRUCTOR: Angular menyediakan platform, zone, router, dan pembaruan tampilan.
  constructor(
    @Inject(PLATFORM_ID) private readonly platformId: object,
    private readonly zone: NgZone,
    private readonly router: Router,
    private readonly changeDetector: ChangeDetectorRef,
  ) {}
  // LIFECYCLE METHOD: di browser, baca sesi/ruangan, mulai kartu, dan pasang listener Socket.IO.
  // Callback socket menerima event backend; updateView meminta Angular memperbarui HTML.
  ngOnInit(): void {
    if (!isPlatformBrowser(this.platformId)) return;
    const storedUser = localStorage.getItem('shadow_heist_user');
    this.accessToken = localStorage.getItem('shadow_heist_access_token') ?? '';
    try {
      const user = storedUser ? (JSON.parse(storedUser) as { username?: string }) : null;
      this.playerName = user?.username || this.playerName;
    } catch {
      this.addSystemMessage('Data login tidak dapat dibaca. Silakan masuk kembali.');
    }
    const roomCode = sessionStorage.getItem('shadow_heist_room');
    if (!roomCode) {
      void this.router.navigateByUrl('/lobby');
      return;
    }
    this.startRoleShuffle();
    if (!this.accessToken) {
      this.addSystemMessage('Sesi tidak ditemukan. Kembali ke login untuk menyambungkan chat.');
      return;
    }
    const backendUrl = `${window.location.protocol}//${window.location.hostname}:8000`;
    this.socket = io(backendUrl, {
      transports: ['websocket', 'polling'],
      auth: { token: this.accessToken, room_code: roomCode },
    });
    this.socket.on('room_state', (room: Room) => this.updateView(() => (this.room = room)));
    // CALLBACK: tampilkan status proses dari backend, bukan simulasi balasan bot.
    this.socket.on('ai_status', (status: { pending: boolean }) =>
      this.updateView(() => (this.isAiThinking = status.pending)),
    );
    this.socket.on('connect', () =>
      this.updateView(() => {
        this.isChatConnected = true;
        this.socket?.emit('register_player', { username: this.playerName });
      }),
    );
    this.socket.on('receive_chat', (chat: ChatMessage) =>
      this.updateView(() => this.receiveChat(chat)),
    );
    this.socket.on('system_alert', (data: { msg: string }) =>
      this.updateView(() => this.addSystemMessage(data.msg)),
    );
    this.socket.on('server_ready', (data: { message: string }) =>
      this.updateView(() => this.addSystemMessage(data.message)),
    );
    this.socket.on('disconnect', () =>
      this.updateView(() => {
        this.isChatConnected = false;
        this.isAiThinking = false;
      }),
    );
    this.socket.on('connect_error', (error: Error) =>
      this.updateView(() => {
        this.isChatConnected = false;
        if (error.message === 'Login diperlukan.') {
          this.expireSession();
          return;
        }
        if (error.message === 'Ruangan tidak valid.') {
          sessionStorage.removeItem('shadow_heist_room');
          void this.router.navigateByUrl('/lobby');
          return;
        }
        this.addSystemMessage('Koneksi terputus. Mencoba menyambungkan kembali…');
      }),
    );
    this.socket.on('status_changed', (data: { status: string }) => {
      if (data.status === 'gagged' || data.status === 'hostage')
        this.updateView(() => {
          this.isGagged = true;
          this.addSystemMessage('Suara Anda tiba-tiba hilang.');
        });
    });
  }

  // LIFECYCLE METHOD: putuskan socket dan hentikan timer animasi saat komponen dilepas.
  ngOnDestroy(): void {
    this.socket?.disconnect();
    if (this.shuffleInterval) clearInterval(this.shuffleInterval);
    if (this.revealTimeout) clearTimeout(this.revealTimeout);
    if (this.readyTimeout) clearTimeout(this.readyTimeout);
  }

  // GETTER: ubah nama role menjadi nama class CSS, misalnya SPY menjadi spy.
  get roleClass(): string {
    return this.assignedRole.name.toLowerCase();
  }

  // METHOD EVENT FORM: periksa kesiapan chat, tampilkan pesan lokal, lalu emit ke backend.
  // Pesan lokal bersifat optimistis: tampil lebih dulu, bukan bukti sudah tersimpan di MySQL.
  sendMessage(): void {
    // TAHAP 1 (browser): tampilkan pesan sendiri, lalu emit send_chat ke backend.
    const message = this.draftMessage.trim();
    if (!message || this.isGagged || !this.gameReady || this.isAiThinking) return;
    if (!this.socket?.connected || !this.isChatConnected) {
      this.addSystemMessage('Chat belum tersambung. Silakan tunggu koneksi aman atau masuk ulang.');
      return;
    }
    this.messages.push({ sender: this.playerName, message });
    this.socket.emit('send_chat', { username: this.playerName, message });
    this.draftMessage = '';
  }

  // METHOD EVENT TOMBOL: jelaskan bahwa skill belum aktif; tidak menjalankan aksi role.
  onAction(): void {
    this.addSystemMessage('Aksi peran belum tersedia. Saat ini kamu bisa mencoba diskusi di chat.');
  }

  // PRIVATE METHOD: jalankan animasi kartu dan buka mode chat setelah animasi selesai.
  private startRoleShuffle(): void {
    this.assignedRole = this.randomRole();
    this.shuffleInterval = setInterval(
      () => this.updateView(() => (this.assignedRole = this.randomRole())),
      130,
    );
    this.revealTimeout = setTimeout(() => {
      if (this.shuffleInterval) clearInterval(this.shuffleInterval);
      this.assignedRole = this.randomRole();
      this.isShuffling = false;
      this.isRoleRevealed = true;
      this.changeDetector.markForCheck();
    }, 1600);
    this.readyTimeout = setTimeout(() => {
      this.gameReady = true;
      this.changeDetector.markForCheck();
    }, 3200);
  }

  // PRIVATE METHOD: jalankan callback pembaruan state dan tandai view agar diperiksa Angular.
  private updateView(update: () => void): void {
    this.zone.run(() => {
      update();
      this.changeDetector.markForCheck();
    });
  }

  // PRIVATE METHOD: pilih kartu acak lokal untuk pratinjau, bukan pembagian role otoritatif.
  private randomRole(): Role {
    return this.roles[Math.floor(Math.random() * this.roles.length)];
  }

  // PRIVATE METHOD: masukkan pesan socket; lewati echo sendiri jika sama dengan pesan terakhir.
  private receiveChat(chat: ChatMessage): void {
    // TAHAP 5/9 (browser): terima echo pemain atau balasan NOX dan isi daftar chat.
    const previous = this.messages.at(-1);
    if (
      chat.sender === this.playerName &&
      previous?.sender === chat.sender &&
      previous.message === chat.message
    )
      return;
    this.messages.push(chat);
  }

  // PRIVATE METHOD: bersihkan sesi browser yang ditolak server dan arahkan ke halaman login.
  private expireSession(): void {
    this.isChatConnected = false;
    localStorage.removeItem('shadow_heist_access_token');
    localStorage.removeItem('shadow_heist_access_token_expires_at');
    localStorage.removeItem('shadow_heist_user');
    sessionStorage.removeItem('shadow_heist_game_entry');
    this.addSystemMessage('Sesi login berakhir. Mengarahkan ke halaman login…');
    setTimeout(() => void this.router.navigateByUrl('/login'), 900);
  }

  // PRIVATE METHOD: tambahkan pemberitahuan lokal berlabel SYSTEM ke daftar chat.
  private addSystemMessage(message: string): void {
    this.messages.push({ sender: 'SYSTEM', message });
  }
}
