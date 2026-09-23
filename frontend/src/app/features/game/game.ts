import { backendUrl } from '../../core/backend-url';
import { isPlatformBrowser } from '@angular/common';
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
import { HttpErrorResponse } from '@angular/common/http';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { finalize } from 'rxjs';
import { io, Socket } from 'socket.io-client';
import { GameMessage, GameService, MatchView } from '../../core/game.service';
import { ProfileMenu } from '../../core/profile-menu';

// KOMPONEN: render snapshot privat server; tidak mengacak role atau memutuskan hasil aksi di browser.
@Component({
  selector: 'app-game',
  imports: [FormsModule, RouterLink, ProfileMenu],
  templateUrl: './game.html',
  styleUrl: './game.css',
})
export class Game implements OnInit, OnDestroy {
  game: MatchView | null = null;
  code = '';
  draft = '';
  target = '';
  error = '';
  notice = '';
  connected = false;
  busy = false;
  thinking = false;
  revealRole = false;
  seconds = 0;
  private socket?: Socket;
  private poll?: ReturnType<typeof setInterval>;
  private loadedPhase = '';
  readonly roleHelp: Record<string, string> = {
    hitman:
      'Malam: Hostage satu warga. Siang: Gag Order, lalu lewati satu ronde sebelum memakai lagi.',
    spy: 'Malam: Guard satu pemain (boleh diri sendiri). Jangan pilih target sama dua malam berturut-turut.',
    stalker:
      'Malam: Peek identitas satu pemain, sekali setiap dua ronde. Hasil hanya terlihat olehmu.',
    civilian:
      'Amati percakapan, uji alibi, dan pilih tersangka saat Tribunal. Tidak punya skill malam.',
  };
  readonly phaseNames: Record<string, string> = {
    day: 'Siang / diskusi',
    night: 'Malam / aksi rahasia',
    tribunal: 'Tribunal / voting',
    finished: 'Hasil akhir',
  };

  // Tampilkan tujuan kubu pemain berdasarkan role privat dari server.
  get objective(): string {
    return this.game?.me.role === 'hitman'
      ? 'Sandera semua anggota kubu warga yang masih hidup. Tetap lolos dari eksekusi Tribunal.'
      : 'Temukan dan eksekusi Hitman lewat Tribunal. Spy, Stalker, dan Civilian menang sebagai satu kubu.';
  }

  // Terjemahkan pemenang tim menjadi hasil pribadi, termasuk kondisi seri.
  get outcomeLabel(): string {
    if (!this.game?.winner) return '';
    if (this.game.winner === 'draw') return 'SERI';
    const team = this.game.me.role === 'hitman' ? 'hitman' : 'civilians';
    return (this.game.result?.outcome ?? (team === this.game.winner ? 'won' : 'lost')) === 'won'
      ? 'KAMU MENANG'
      : 'KAMU KALAH';
  }

  // Jelaskan alasan kemenangan server, dengan fallback untuk backend versi lama.
  get resultExplanation(): string {
    const explanations: Record<string, string> = {
      hitman_executed:
        'Hitman telah dieksekusi. Semua anggota kubu warga menang, termasuk yang menjadi Hostage atau sudah dieksekusi.',
      all_survivors_hostage:
        'Semua anggota kubu warga yang masih hidup telah menjadi Hostage. Hitman menguasai meja.',
      no_civilians_alive:
        'Seluruh anggota kubu warga telah dieksekusi. Hitman menjadi satu-satunya pemain yang masih hidup.',
      round_limit: `Batas ${this.game?.max_rounds ?? 8} ronde tercapai. Tidak ada kubu yang memenuhi syarat kemenangan.`,
    };
    if (this.game?.result) return explanations[this.game.result.reason] ?? '';
    // Kompatibel selama frontend dan backend diperbarui pada waktu berbeda.
    return this.game?.winner === 'draw'
      ? explanations['round_limit']
      : this.game?.winner === 'civilians'
        ? explanations['hitman_executed']
        : 'Tidak ada lagi warga hidup yang bebas dari Hostage.';
  }

  // Jelaskan hak pemain berdasarkan status hidup, Hostage, dan Gag Order miliknya.
  get privateStatus(): string {
    const me = this.game?.me;
    if (!me) return '';
    if (this.game?.winner)
      return `Status akhir: ${!me.alive ? 'dieksekusi' : me.hostage ? 'hidup sebagai Hostage' : 'masih hidup'}. Hasil menang/kalah mengikuti kubumu.`;
    if (!me.alive) return 'Dieksekusi: kamu menjadi penonton. Hasilmu tetap mengikuti kubumu.';
    if (me.hostage)
      return 'Hostage: kamu masih hidup, tetapi chat, voting, dan aksi terkunci sampai pertandingan berakhir. Kamu tetap bagian dari kubu warga.';
    if (me.gagged)
      return 'Gag Order: chat dan voting terkunci sampai akhir Tribunal ronde ini. Aksi malam tetap boleh dilakukan.';
    if (me.muted) return 'Chat dan voting terkunci untukmu.';
    return 'Kamu masih hidup dan bebas. Hak chat, aksi, dan voting mengikuti fase permainan.';
  }

  // Sediakan API pertandingan, navigasi, deteksi perubahan, dan lifecycle komponen.
  constructor(
    @Inject(PLATFORM_ID) private readonly platform: object,
    private readonly api: GameService,
    private readonly router: Router,
    private readonly cdr: ChangeDetectorRef,
    private readonly destroy: DestroyRef,
  ) {}

  // INIT: polling menjaga snapshot setelah reconnect; Socket.IO membawa pesan/error langsung.
  ngOnInit(): void {
    if (!isPlatformBrowser(this.platform)) return;
    this.code = sessionStorage.getItem('shadow_heist_room') ?? '';
    if (!this.code) {
      void this.router.navigateByUrl('/lobby');
      return;
    }
    this.refresh();
    this.poll = setInterval(() => this.refresh(), 1000);
    this.socket = io(`${backendUrl()}`, {
      auth: { token: localStorage.getItem('shadow_heist_access_token'), room_code: this.code },
      transports: ['websocket', 'polling'],
    });
    this.socket.on('connect', () => {
      this.connected = true;
      this.cdr.markForCheck();
    });
    this.socket.on('disconnect', () => {
      this.connected = false;
      this.thinking = false;
      this.cdr.markForCheck();
    });
    this.socket.on('connect_error', () => {
      this.connected = false;
      this.error = 'Chat belum tersambung. Periksa koneksi atau kembali ke lobby.';
      this.cdr.markForCheck();
    });
    this.socket.on('system_alert', (data: { msg: string }) => {
      this.error = data.msg;
      this.cdr.markForCheck();
    });
    this.socket.on('ai_status', (data: { pending: boolean }) => {
      this.thinking = data.pending;
      this.cdr.markForCheck();
    });
    this.socket.on('receive_chat', (message: GameMessage) => {
      if (this.game && !this.game.messages.some((item) => item.id === message.id))
        this.game.messages.push(message);
      this.cdr.markForCheck();
    });
  }

  // Putuskan socket dan hentikan polling saat meninggalkan halaman pertandingan.
  ngOnDestroy(): void {
    this.socket?.disconnect();
    if (this.poll) clearInterval(this.poll);
  }

  // SNAPSHOT: polling tidak ditumpuk; pilihan target direset saat ronde/fase berubah.
  refresh(): void {
    if (!this.busy && this.code) this.request();
  }

  // Sinkronkan snapshot/aksi server, reset pilihan fase lama, dan tampilkan kegagalan request.
  private request(body?: unknown, action = 'play'): void {
    this.busy = true;
    this.api
      .request(this.code, body, action)
      .pipe(
        takeUntilDestroyed(this.destroy),
        finalize(() => {
          this.busy = false;
          this.cdr.markForCheck();
        }),
      )
      .subscribe({
        next: (snapshot) => {
          this.game = snapshot.game;
          this.seconds = this.game.winner
            ? 0
            : Math.max(0, Math.ceil(this.game.deadline - this.game.server_time));
          if (this.game.winner) this.thinking = false;
          const phase = `${this.game.id}/${this.game.round}/${this.game.phase}`;
          if (phase !== this.loadedPhase) {
            this.target = '';
            this.notice = '';
            this.loadedPhase = phase;
          }
          if (body) {
            this.notice = 'Pilihan dikunci oleh server.';
            this.error = '';
          }
        },
        error: (error: HttpErrorResponse) => {
          this.error =
            typeof error.error?.detail === 'string'
              ? error.error.detail
              : 'Server belum bisa dihubungi.';
          if (error.status === 401) void this.router.navigateByUrl('/login');
        },
      });
  }

  // AKSI: token fase menolak tombol lama yang diklik ketika timer sudah berganti.
  act(vote = false): void {
    if (!this.game || !this.target || this.busy) return;
    this.request({
      match_id: this.game.id,
      round_number: this.game.round,
      phase: this.game.phase,
      target: this.target,
      ability: vote ? null : this.game.me.ability,
    });
  }

  // Persetujuan bukan chat/vote: manusia hidup yang dibungkam tetap boleh setuju.
  skipDiscussion(): void {
    if (!this.game?.discussion_skip.can_consent || this.busy) return;
    this.request(
      { match_id: this.game.id, round_number: this.game.round, phase: this.game.phase },
      'skip-discussion',
    );
  }

  // TARGET: bantuan UX saja; semua aturan juga diperiksa engine.
  canTarget(name: string): boolean {
    if (!this.game) return false;
    if (this.game.me.ability === 'guard' && this.game.me.can_act)
      return name !== this.game.me.last_guard;
    return name !== this.game.me.name;
  }

  // CHAT: hanya echo server ditampilkan supaya pesan yang ditolak tidak tampak terkirim.
  votersFor(name: string): string[] {
    return this.game?.tribunal_votes.find((item) => item.target === name)?.voters ?? [];
  }

  // Warna berdasarkan urutan pemain, bukan role atau status rahasia.
  voterColor(name: string): string {
    const index = this.game?.players.findIndex((player) => player.name === name) ?? 0;
    return ['#c8dfe8', '#efcfac', '#d3ddba', '#dfcce5', '#f0c8c2', '#d4d3ed'][
      Math.max(0, index) % 6
    ];
  }

  // CHAT: hanya echo server ditampilkan supaya pesan yang ditolak tidak tampak terkirim.
  sendMessage(): void {
    if (!this.game?.me.can_chat || !this.connected || !this.draft.trim() || this.thinking) return;
    this.error = '';
    this.socket?.emit('send_chat', { username: this.game.me.name, message: this.draft.trim() });
    this.draft = '';
  }
}
