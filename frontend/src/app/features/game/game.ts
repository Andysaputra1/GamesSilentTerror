import { backendUrl } from '../../core/backend-url';
import { isPlatformBrowser, NgTemplateOutlet } from '@angular/common';
import {
  afterNextRender,
  ChangeDetectorRef,
  Component,
  DestroyRef,
  ElementRef,
  Inject,
  Injector,
  OnDestroy,
  OnInit,
  PLATFORM_ID,
  ViewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { finalize } from 'rxjs';
import { io, Socket } from 'socket.io-client';
import {
  GameMessage,
  GameService,
  MatchView,
  RoleComposition,
  SurveyStatus,
} from '../../core/game.service';
import { ProfileMenu } from '../../core/profile-menu';
import { PhaseDurations } from '../../core/room.service';
import { FullscreenPrompt } from '../../core/fullscreen-prompt';
import { forgetRoom, STORAGE } from '../../core/storage';
import { SurveyForm } from '../../core/survey-form/survey-form';
import { RoleRevealCard } from '../../core/role-reveal-card/role-reveal-card';

// Karakter cadangan dan warna label pemain: berdasarkan urutan kursi, bukan role atau status rahasia.
const SKINS = ['arthur', 'jenny', 'dexter', 'eloise', 'kiera', 'sadie'];
const TAG_COLORS = [
  '#b8452f',
  '#34688a',
  '#4f7f35',
  '#a8741f',
  '#6f4a93',
  '#2c7a74',
  '#9c4467',
  '#6d6a2a',
  '#435aa0',
  '#8a5530',
];
const ROLES = ['hitman', 'spy', 'stalker', 'civilian'];
const ROLE_REVEAL_READ_MS = 3000;

// KOMPONEN: render snapshot privat server; tidak mengacak role atau memutuskan hasil aksi di browser.
@Component({
  selector: 'app-game',
  imports: [
    FormsModule,
    RouterLink,
    ProfileMenu,
    FullscreenPrompt,
    NgTemplateOutlet,
    SurveyForm,
    RoleRevealCard,
  ],
  templateUrl: './game.html',
  styleUrls: [
    './game.css',
    './game-table.css',
    './game-cards.css',
    './game-screens.css',
    './game-preparation.css',
    './game-end.css',
    './game-motion.css',
  ],
})
export class Game implements OnInit, OnDestroy {
  game: MatchView | null = null;
  code = '';
  draft = '';
  teamDraft = '';
  target = '';
  error = '';
  connected = false;
  busy = false;
  // Permintaan keluar sedang dikirim; polling ditahan agar tidak berebut dengan pembersihan room.
  leaving = false;
  // Pop-up konfirmasi keluar sedang terbuka.
  popupKeluarTerbuka = false;
  // Fokus awal pop-up keluar di "Tetap bermain" agar Enter tidak langsung mengeluarkan pemain.
  @ViewChild('stayButton') set stayButton(button: ElementRef<HTMLButtonElement> | undefined) {
    if (button) queueMicrotask(() => button.nativeElement.focus());
  }
  kartuRoleTerbuka = false;
  readingRole = false;
  private membacaLewatPengingat = false;
  private idPertandinganRoleDibaca = '';
  private roleReadTimer?: ReturnType<typeof setTimeout>;
  sisaDetik = 0;
  // Tampilan: tab di HP, panel aturan, dan layar akhir (pengumuman → kuesioner → meja akhir).
  mobileTab: 'table' | 'chat' | 'info' = 'table';
  unread = 0;
  showRules = false;
  endView: 'reveal' | 'survey' | 'board' = 'reveal';
  durations: PhaseDurations | null = null;
  @ViewChild('messageList') private messageList?: ElementRef<HTMLElement>;
  // CHAT: pemain di dasar daftar ikut turun ke pesan baru; yang sedang membaca riwayat tidak ditarik.
  chatAtBottom = true;
  jumlahPesanBaruDiBawah = 0;
  private lastMessageId = '';
  private lastRevealTry = 0;
  private messagesLoaded = false;
  private feltSize = { width: 0, height: 0 };
  private feltObserver?: ResizeObserver;
  private idPertandinganBerakhir = '';
  private endTimer?: ReturnType<typeof setTimeout>;
  readonly phaseSteps = [
    { key: 'day', label: 'Diskusi', icon: '☀' },
    { key: 'tribunal', label: 'Tribunal', icon: '⚖' },
    { key: 'night', label: 'Malam', icon: '☾' },
  ];
  // Huruf tahap langkah bot di kiri bawah kartu, untuk memantau bot benar-benar menerima dan mengolah input.
  readonly tahapBot: Record<string, string> = {
    I: 'Input diterima',
    L: 'Logika berjalan',
    O: 'Output/aksi selesai',
  };
  readonly roleNames: Record<string, string> = {
    hitman: 'Hitman',
    spy: 'Spy',
    stalker: 'Stalker',
    civilian: 'Civilian',
  };
  readonly abilityNames: Record<string, string> = {
    gag: 'Gag Order',
    hostage: 'Sandera',
    guard: 'Jaga',
    peek: 'Intip',
  };
  // Ikon chip komposisi room (akhiran U+FE0F memaksa tampilan emoji berwarna, bukan simbol teks).
  readonly roleIcons: Record<string, string> = {
    hitman: '🗡️',
    spy: '🛡️',
    stalker: '👁️',
    civilian: '👤',
  };
  // Overlay pergantian fase (meredup saat malam, terang saat pagi).
  transition: { phase: string; title: string; subtitle: string } | null = null;
  // Survei akhir: pertanyaan dari server dan status tampilannya (jawaban diurus SurveyForm).
  survey: SurveyStatus | null = null;
  surveyState: 'idle' | 'loading' | 'ready' | 'done' | 'unavailable' = 'idle';
  surveyError = '';
  readonly confetti = Array.from({ length: 28 }, (_, index) => ({
    x: (index * 37) % 100,
    delay: (index % 7) * 0.35,
    color: ['#e3b448', '#36564b', '#c8553d', '#6c8ea4', '#efcfac'][index % 5],
  }));
  private socket?: Socket;
  private timerPolling?: ReturnType<typeof setInterval>;
  // Polling latar tidak memakai `busy`: aplikasi zoneless tidak menggambar ulang tombol saat polling
  // dimulai, jadi klik yang jatuh di tengah polling (tiap detik) dulu ditolak diam-diam dan tombol
  // harus ditekan berkali-kali. Nomor aksi membuang respons polling yang lebih tua dari klik terakhir.
  private sedangPolling = false;
  private nomorAksiTerakhir = 0;
  // Batas fase menurut jam browser (deadline server dikoreksi selisih jam). Timer dihitung dari sini tiap
  // setengah detik, jadi tetap berjalan walau satu polling tersendat di jaringan (dulu layar tampak membeku).
  private batasFaseLokal = 0;
  private timerSisaDetik?: ReturnType<typeof setInterval>;
  // Pesan error dari polling latar dihapus lagi oleh polling berikutnya yang berhasil.
  private errorDariPollingLatar = false;
  // Format `id/ronde/fase`: bila berganti, pilihan target dan draf chat tim direset.
  private kunciFaseTerakhir = '';
  // Format `id/fase`: bila berganti, overlay transisi fase ditampilkan.
  private kunciFaseTampil = '';
  private idPertandinganSurvei = '';
  private transitionTimer?: ReturnType<typeof setTimeout>;
  readonly phaseIcons: Record<string, string> = {
    day: '☀',
    night: '☾',
    tribunal: '⚖',
    finished: '★',
    start: '◆',
  };
  // Lima detik terakhir tiap fase: angka besar di tengah layar (tidak menghalangi klik).
  readonly finalLabels: Record<string, string> = {
    day: 'Diskusi segera berakhir',
    night: 'Malam segera berakhir',
    tribunal: 'Vote segera ditutup',
  };
  readonly transitions: Record<string, { title: string; subtitle: string }> = {
    day: { title: 'Pagi tiba', subtitle: 'Diskusi dibuka. Baca alibi dan cari kejanggalan.' },
    night: {
      title: 'Malam tiba…',
      subtitle: 'Lampu meredup dan chat dikunci. Aksi rahasia dimulai.',
    },
    tribunal: {
      title: 'Tribunal dimulai',
      subtitle: 'Pilih tersangka. Suara terbanyak tunggal dieksekusi.',
    },
    finished: { title: 'Permainan selesai', subtitle: 'Identitas semua pemain dibuka.' },
  };
  // Room dengan lebih dari satu Hitman memakai aturan Syndicate (Hostage dan Gag bersama).
  get multiHitman(): boolean {
    return this.hitmanCount > 1;
  }

  get roleHelp(): Record<string, string> {
    return {
      hitman: this.multiHitman
        ? 'Malam: pilih satu warga untuk disandera; Syndicate hanya menyandera satu orang per malam (pilihan terbanyak para Hitman), dan rekan bisa berdiskusi lewat chat tim. Siang: Gag Order dipakai bersama, lalu jeda satu ronde.'
        : 'Malam: Hostage satu warga. Siang: Gag Order, lalu lewati satu ronde sebelum memakai lagi.',
      spy:
        'Malam: Guard satu pemain (boleh diri sendiri), boleh target yang sama dengan malam sebelumnya.' +
        ((this.game?.composition?.spy ?? 1) > 1
          ? ' Kamu tahu rekan Spy dan pilihan Guard mereka; atur penjagaan lewat chat tim saat malam.'
          : ''),
      stalker:
        'Malam: Peek identitas satu pemain, sekali setiap dua ronde. Hasil hanya terlihat olehmu.',
      civilian:
        'Amati percakapan, uji alibi, dan pilih tersangka saat Tribunal. Tidak punya skill malam.',
    };
  }

  // KOMPOSISI: jumlah tiap role di room (publik, dari server); urutan chip mengikuti ROLES.
  get composition(): { role: string; count: number }[] {
    const counts = this.game?.composition;
    if (!counts) return [];
    return ROLES.map((role) => ({
      role,
      count: counts[role as keyof RoleComposition] ?? 0,
    })).filter((item) => item.count > 0);
  }

  get compositionLabel(): string {
    return this.composition
      .map((item) => `${item.count} ${this.roleNames[item.role] ?? item.role}`)
      .join(' · ');
  }

  // Jumlah Hitman: dari komposisi server, atau dari role yang dibuka setelah pertandingan selesai.
  get hitmanCount(): number {
    const game = this.game;
    if (!game) return 0;
    return (
      game.composition?.hitman ?? game.players.filter((player) => player.role === 'hitman').length
    );
  }

  // Hitman yang masih hidup (publik, hanya room dengan ≥ 2 Hitman); null bila server tidak mengumumkan.
  get hitmanRemaining(): number | null {
    const remaining = this.game?.hitman_remaining;
    return typeof remaining === 'number' ? remaining : null;
  }

  // Chip Hitman di tepi meja menampilkan "tersisa/total"; chip lain dan layar persiapan: null.
  hitmanTersisaDiChip(item: { role: string }, kelasTambahan: string): number | null {
    return item.role === 'hitman' && kelasTambahan === 'felt-composition'
      ? this.hitmanRemaining
      : null;
  }

  // REKAN SYNDICATE: server hanya mengirim daftar ini kepada Hitman; role lain selalu kosong.
  get allies(): string[] {
    return this.game?.me.role === 'hitman' ? (this.game.me.allies ?? []) : [];
  }

  isAlly(name: string): boolean {
    return this.allies.includes(name);
  }

  // REKAN SPY: server hanya mengirim daftar ini kepada Spy di room yang sejak awal punya ≥ 2 Spy.
  get spyAllies(): string[] {
    return this.game?.me.spy_allies ?? [];
  }

  isSpyAlly(name: string): boolean {
    return this.spyAllies.includes(name);
  }

  // Rekan Spy yang menjaga pemain ini malam ini (penanda di kartu meja).
  spyPicks(name: string): string[] {
    const game = this.game;
    if (!game || game.phase !== 'night') return [];
    return (game.me.spy_actions ?? [])
      .filter((action) => action.target === name)
      .map((action) => action.name);
  }

  // Target terbanyak dari pilihan rekan; seri → pilihan yang masuk lebih dulu. Korban tim yang sebenarnya
  // dihitung server (syndicate_target), termasuk aturan seri manusia lawan bot.
  get allyTarget(): string {
    const game = this.game;
    if (!game || game.phase !== 'night') return '';
    const counts = new Map<string, number>();
    for (const action of game.me.ally_actions ?? [])
      counts.set(action.target, (counts.get(action.target) ?? 0) + 1);
    let targetTerbanyak = '';
    for (const [target, count] of counts)
      if (count > (counts.get(targetTerbanyak) ?? 0)) targetTerbanyak = target;
    return targetTerbanyak;
  }

  // Rekan yang memilih pemain ini sebagai target Hostage malam ini (penanda di kartu meja).
  allyPicks(name: string): string[] {
    const game = this.game;
    if (!game || game.phase !== 'night') return [];
    return (game.me.ally_actions ?? [])
      .filter((action) => action.target === name)
      .map((action) => action.name);
  }

  // INTIP: role hasil Peek dari intel privat Stalker, jadi tetap di kartu lintas ronde dan setelah refresh.
  // Target yang baru dikunci malam ini bertanda "?" sampai server menyelesaikan malam.
  peekLabel(name: string): string {
    const me = this.game?.me;
    if (!me || me.role !== 'stalker' || this.game?.winner) return '';
    for (let indeks = me.intel.length - 1; indeks >= 0; indeks--)
      if (me.intel[indeks].name === name) return me.intel[indeks].role;
    return me.action?.ability === 'peek' && me.action.target === name ? '?' : '';
  }

  // JAGA: target Guard milik Spy malam ini; server hanya mengirim aksi milik pemain sendiri.
  get guardTarget(): string {
    const action = this.game?.phase === 'night' ? this.game.me.action : null;
    return action?.ability === 'guard' ? action.target : '';
  }

  // GAG: korban melihatnya di kartunya sendiri (me.gagged); Syndicate melihat target Gag ronde ini
  // (me.ally_gags, hanya dikirim ke Hitman). Pemain lain tidak pernah tahu siapa yang dibungkam.
  isGagged(name: string): boolean {
    const game = this.game;
    if (!game || game.winner) return false;
    if (name === game.me.name) return !!game.me.gagged;
    return !!game.me.ally_gags?.includes(name);
  }

  // SANDERA: korban yang berhasil diumumkan ke semua pemain saat malam selesai (players[].hostage) dan
  // bercap sampai akhir. Selama malam, Syndicate juga melihat korban tim malam ini (satu per malam:
  // pilihan terbanyak) sebelum diselesaikan.
  isHostage(name: string): boolean {
    const game = this.game;
    if (!game) return false;
    if (game.players.find((player) => player.name === name)?.hostage) return true;
    if (name === game.me.name && game.me.hostage) return true;
    if (game.me.role !== 'hitman' || game.phase !== 'night') return false;
    // Backend lama tanpa syndicate_target: pakai pilihan sendiri.
    const action = game.me.action?.ability === 'hostage' ? game.me.action.target : null;
    return (game.me.syndicate_target ?? action) === name;
  }

  // GAGAL SANDERA: pada siang sesudah malamnya, Syndicate melihat cap "Disandera" dicap GAGAL lalu memudar
  // di kartu target yang dijaga Guard. Dipasang sesudah tirai siang hilang; kalau ikut muncul bersama
  // tirai, animasinya sudah memudar sebelum kartu terlihat.
  failedHostage(name: string): boolean {
    const game = this.game;
    if (!game || game.winner || this.transition) return false;
    if (game.phase !== 'day' || game.me.role !== 'hitman') return false;
    return !!game.me.syndicate_hostages?.some(
      (sandera) => !sandera.success && sandera.name === name && sandera.round === game.round - 1,
    );
  }

  // Terjemahkan pemenang tim menjadi hasil pribadi.
  get outcomeLabel(): string {
    if (!this.game?.winner) return '';
    const team = this.game.me.role === 'hitman' ? 'hitman' : 'civilians';
    return (this.game.result?.outcome ?? (team === this.game.winner ? 'won' : 'lost')) === 'won'
      ? 'KAMU MENANG'
      : 'KAMU KALAH';
  }

  // Jelaskan alasan kemenangan server, dengan fallback untuk backend versi lama.
  get resultExplanation(): string {
    const sebutanHitman = this.hitmanCount > 1 ? 'Semua Hitman' : 'Hitman';
    // Hitman yang keluar di tengah pertandingan tersingkir seperti dieksekusi.
    const nasibHitman = this.game?.players.some((player) => player.role === 'hitman' && player.left)
      ? 'tersingkir'
      : 'dieksekusi';
    const explanations: Record<string, string> = {
      vote_control:
        'Warga hidup yang masih punya hak voting tidak lebih banyak dari Hitman yang masih hidup. Suara warga tidak lagi bisa mengalahkan suara Hitman.',
      hitman_executed: `${sebutanHitman} telah ${nasibHitman}. Semua anggota kubu warga menang, termasuk yang menjadi Hostage atau sudah dieksekusi.`,
      all_survivors_hostage:
        'Semua anggota kubu warga yang masih hidup telah menjadi Hostage. Hitman menguasai meja.',
      no_civilians_alive:
        'Seluruh anggota kubu warga telah dieksekusi. Hanya Hitman yang masih hidup.',
    };
    if (this.game?.result) return explanations[this.game.result.reason] ?? '';
    // Kompatibel selama frontend dan backend diperbarui pada waktu berbeda.
    return this.game?.winner === 'civilians'
      ? explanations['hitman_executed']
      : 'Suara warga hidup yang bebas tidak lagi melampaui suara Hitman.';
  }

  // Pemain kubu pemenang (role terbuka setelah pertandingan selesai).
  get winners(): MatchView['players'] {
    if (!this.game?.winner) return [];
    return this.game.players.filter((player) =>
      this.game?.winner === 'hitman' ? player.role === 'hitman' : player.role !== 'hitman',
    );
  }

  // Judul ucapan selamat: untuk pemenang pribadi atau untuk kubu yang menang.
  get congratsTitle(): string {
    if (!this.game?.winner) return '';
    if (this.outcomeLabel === 'KAMU MENANG') return 'Selamat, kamu menang!';
    if (this.game.winner === 'civilians') return 'Selamat untuk kubu warga!';
    // Syndicate bisa menang walau salah satu Hitman sudah dieksekusi, jadi tidak disebut "lolos".
    return this.winners.length > 1
      ? 'Selamat untuk Syndicate!'
      : 'Selamat untuk Hitman yang lolos!';
  }

  // Label singkat pemenang: role, penanda bot, dan penanda akun sendiri.
  winnerLabel(player: MatchView['players'][number]): string {
    return [
      player.role?.toUpperCase(),
      player.bot ? 'BOT' : '',
      player.name === this.game?.me.name ? 'KAMU' : '',
    ]
      .filter(Boolean)
      .join(' · ');
  }

  readonly phaseShort: Record<string, string> = {
    preparing: 'Persiapan',
    day: 'Siang',
    night: 'Malam',
    tribunal: 'Tribunal',
    finished: 'Selesai',
  };

  // SERI: server menambah waktu Tribunal sekali; timer mengikuti deadline baru.
  readonly tribunalExtraNote =
    'Suara seri: waktu ditambah sekali. Masih seri saat waktu habis berarti tidak ada eksekusi.';

  get tribunalExtra(): boolean {
    return this.game?.phase === 'tribunal' && !!this.game.tribunal_extra;
  }

  get chatHint(): string {
    if (!this.game) return '';
    if (this.game.winner) return 'Pertandingan selesai. Riwayat diskusi tetap bisa dibaca.';
    if (this.game.phase === 'night')
      return this.game.me.can_team_chat
        ? 'Malam: diskusi meja terkunci. Chat tim hanya terlihat oleh rekanmu.'
        : 'Malam: semua chat terkunci.';
    if (this.tribunalExtra) return this.tribunalExtraNote;
    return 'Baca alibi. Amati siapa yang menjawab, bukan sekadar siapa yang diam.';
  }

  // Judul panggung akhir, seperti layar kemenangan Among Us.
  get victoryTitle(): string {
    return this.game?.winner === 'hitman' ? 'Hitman menang!' : 'Warga menang!';
  }

  // Urutan kursi pemain dari server; dipakai untuk karakter dan warna label, bukan untuk role.
  private playerIndex(name: string): number {
    return Math.max(0, this.game?.players.findIndex((player) => player.name === name) ?? 0);
  }

  // Nama tampilan pemain dari snapshot; username tetap dipakai untuk aksi dan vote.
  ambilNamaTampilan(name: string | null | undefined): string {
    if (!name) return '';
    return this.game?.players.find((player) => player.name === name)?.label ?? name;
  }

  gabungNamaTampilan(names: string[]): string {
    return names.map((name) => this.ambilNamaTampilan(name)).join(', ');
  }

  // Skin pilihan akun (dibagikan server tanpa kembar); urutan kursi hanya cadangan snapshot lama.
  skinFor(name: string): string {
    const chosen = this.game?.players.find((player) => player.name === name)?.skin_id;
    const skin =
      chosen && SKINS.includes(chosen) ? chosen : SKINS[this.playerIndex(name) % SKINS.length];
    return `/assets/characters/skin_${skin}.png`;
  }

  colorFor(name: string): string {
    return TAG_COLORS[this.playerIndex(name) % TAG_COLORS.length];
  }

  // Warna chip pemilih sama dengan label nama pemilih di meja dan chat.
  voterColor(name: string): string {
    return this.colorFor(name);
  }

  // PANAS VOTE: 0 = tanpa suara, 1 = suara sudah mencapai mayoritas pemain hidup (bingkai paling merah).
  voteHeat(name: string): number {
    const votes = this.votersFor(name).length;
    if (!votes || !this.game) return 0;
    const alive = this.game.players.filter((player) => player.alive).length;
    return Math.min(1, votes / Math.max(2, Math.floor(alive / 2) + 1));
  }

  // Suara terbanyak tunggal: pemain ini dieksekusi jika Tribunal berakhir sekarang.
  get leadingTarget(): string {
    const suaraMasuk = (this.game?.tribunal_votes ?? []).filter((item) => item.voters.length > 0);
    if (!suaraMasuk.length) return '';
    const suaraTerbanyak = Math.max(...suaraMasuk.map((item) => item.voters.length));
    const targetTeratas = suaraMasuk.filter((item) => item.voters.length === suaraTerbanyak);
    return targetTeratas.length === 1 ? targetTeratas[0].target : '';
  }

  // Susunan meja: jumlah kolom yang membuat kartu (rasio 4:5) paling besar di papan yang tersedia.
  // Tanpa ukuran papan (render awal/test): satu baris sampai 5 pemain, selebihnya dua baris.
  get tableColumns(): number {
    const jumlahPemain = this.game?.players.length ?? 0;
    const { width, height } = this.feltSize;
    if (!jumlahPemain || !width || !height)
      return jumlahPemain <= 5 ? Math.max(1, jumlahPemain) : Math.ceil(jumlahPemain / 2);
    const jarakKartu = 16;
    let kolomTerbaik = 1;
    let lebarKartuTerbesar = 0;
    for (let jumlahKolom = 1; jumlahKolom <= jumlahPemain; jumlahKolom++) {
      const jumlahBaris = Math.ceil(jumlahPemain / jumlahKolom);
      // Lebar kartu paling besar 200 px; 0.8 mengubah tinggi sel menjadi lebar (rasio kartu 4:5).
      const lebarKartu = Math.min(
        200,
        (width - (jumlahKolom - 1) * jarakKartu) / jumlahKolom,
        ((height - (jumlahBaris - 1) * jarakKartu) / jumlahBaris) * 0.8,
      );
      // Selisih di bawah 0,5 px dianggap sama: pilih kolom yang lebih banyak.
      if (lebarKartu >= lebarKartuTerbesar - 0.5) {
        kolomTerbaik = jumlahKolom;
        lebarKartuTerbesar = lebarKartu;
      }
    }
    return kolomTerbaik;
  }

  get tableRows(): number {
    return Math.max(1, Math.ceil((this.game?.players.length ?? 0) / this.tableColumns));
  }

  // Ukuran papan diamati agar kartu tetap muat satu layar di laptop, tablet, maupun HP.
  @ViewChild('felt') set feltElement(ref: ElementRef<HTMLElement> | undefined) {
    this.feltObserver?.disconnect();
    if (!ref || typeof ResizeObserver === 'undefined') return;
    this.feltObserver = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      if (Math.abs(width - this.feltSize.width) < 1 && Math.abs(height - this.feltSize.height) < 1)
        return;
      this.feltSize = { width, height };
      this.changeDetector.markForCheck();
    });
    this.feltObserver.observe(ref.nativeElement);
  }

  // Sisa waktu fase (0–1) untuk cincin timer; durasi fase berasal dari room snapshot.
  get timerFraction(): number {
    const phase = this.game?.phase;
    if (!this.game || this.game.winner || !this.durations || !phase || !(phase in this.durations))
      return 1;
    const total = this.durations[phase as keyof PhaseDurations];
    return total > 0 ? Math.max(0, Math.min(1, this.sisaDetik / total)) : 1;
  }

  get finalCountdown(): boolean {
    const state = this.game;
    return (
      !!state &&
      !state.winner &&
      !this.transition &&
      state.phase in this.finalLabels &&
      this.sisaDetik > 0 &&
      this.sisaDetik <= 5
    );
  }

  // Countdown server juga mencakup batas tunggu AI bila model belum siap.
  get preparationSeconds(): number {
    const persiapan = this.game?.preparation;
    return persiapan ? (persiapan.starts_in ?? persiapan.max_wait) : 0;
  }

  get mySkinId(): string {
    return this.game
      ? this.skinFor(this.game.me.name).split('skin_')[1].replace('.png', '')
      : 'arthur';
  }

  readonly roleSummary: Record<string, string> = {
    hitman: 'Penyusup yang menyamar sebagai warga. Rahasiakan identitasmu.',
    spy: 'Pelindung warga. Jaga pemain dari sandera saat malam.',
    stalker: 'Pencari informasi. Intip role pemain secara diam-diam.',
    civilian: 'Warga biasa. Baca alibi, cari bukti, lalu tentukan suara.',
  };

  get preparationActions(): { label: string; text: string }[] {
    const shared = [
      { label: 'Chat', text: 'Siang: diskusikan alibi.' },
      { label: 'Vote', text: 'Tribunal mulai ronde 2: pilih tersangka.' },
    ];
    if (!this.kartuRoleTerbuka) return shared;
    const special: Record<string, { label: string; text: string }[]> = {
      hitman: [
        { label: 'Gag Order', text: 'Siang: bungkam chat; jeda satu ronde.' },
        { label: 'Sandera', text: 'Malam: hilangkan suara satu warga.' },
      ],
      spy: [
        {
          label: 'Jaga',
          text: 'Malam: lindungi satu pemain, boleh diri sendiri dan boleh target yang sama tiap malam.',
        },
      ],
      stalker: [{ label: 'Intip', text: 'Malam: lihat role satu pemain; jeda satu ronde.' }],
    };
    const role = this.game?.me.role ?? '';
    const punyaTim =
      (role === 'hitman' && this.multiHitman) ||
      (role === 'spy' && (this.game?.composition?.spy ?? 1) > 1);
    const aksiChatTim = {
      label: 'Chat tim',
      text: 'Malam: berdiskusi rahasia dengan rekan setim.',
    };
    return [...shared, ...(special[role] ?? []), ...(punyaTim ? [aksiChatTim] : [])];
  }

  get preparationTarget(): string {
    if (!this.kartuRoleTerbuka) return 'Buka kartu role untuk melihat target kemenanganmu.';
    return this.game?.me.role === 'hitman'
      ? 'Buat jumlah warga yang bebas bersuara tidak melebihi Hitman yang masih hidup.'
      : 'Temukan dan eksekusi semua Hitman lewat voting Tribunal.';
  }

  // Pengingat muncul pada 10 detik terakhir; pembukaan otomatis pada 5 detik terakhir.
  get revealPrompt(): boolean {
    if (this.readingRole && this.membacaLewatPengingat) return true;
    const persiapan = this.game?.phase === 'preparing' ? this.game.preparation : null;
    return (
      !!persiapan && !this.kartuRoleTerbuka && !persiapan.revealed && this.preparationSeconds <= 10
    );
  }

  // Snapshot tetap mengikuti server; layar persiapan memberi waktu membaca kartu sebelum berpindah.
  get showPreparation(): boolean {
    return this.game?.phase === 'preparing' || this.readingRole;
  }

  // Buka/tutup kartu role; pembukaan pertama dilaporkan tanpa mempercepat countdown server.
  toggleRole(): void {
    if (this.readingRole) return;
    const dariPengingat = this.revealPrompt;
    this.kartuRoleTerbuka = !this.kartuRoleTerbuka;
    if (
      this.kartuRoleTerbuka &&
      this.game?.phase === 'preparing' &&
      this.idPertandinganRoleDibaca !== this.game.id
    ) {
      this.startRoleReading(dariPengingat);
    }
    if (this.kartuRoleTerbuka) this.refresh();
  }

  private startRoleReading(dariPengingat: boolean): void {
    this.idPertandinganRoleDibaca = this.game!.id;
    this.readingRole = true;
    this.membacaLewatPengingat = dariPengingat;
    this.roleReadTimer = setTimeout(() => {
      this.stopRoleReading();
      this.updatePhaseTransition();
      this.changeDetector.markForCheck();
    }, ROLE_REVEAL_READ_MS);
  }

  private stopRoleReading(): void {
    clearTimeout(this.roleReadTimer);
    this.roleReadTimer = undefined;
    this.readingRole = false;
    this.membacaLewatPengingat = false;
  }

  // Kartu sudah dibuka di layar ini, tetapi server belum mencatatnya.
  private get revealPending(): boolean {
    const state = this.game;
    return this.kartuRoleTerbuka && state?.phase === 'preparing' && !state.preparation?.revealed;
  }

  get timerUrgent(): boolean {
    return (
      !!this.game && !this.game.winner && this.game.phase !== 'preparing' && this.sisaDetik <= 10
    );
  }

  // TAB HP: meja, chat, atau info; membuka chat menghapus penanda pesan baru.
  selectTab(tab: 'table' | 'chat' | 'info'): void {
    this.mobileTab = tab;
    if (tab === 'chat') {
      this.unread = 0;
      this.jumpToLatest();
    }
  }

  // LAYAR AKHIR: pengumuman pemenang → kuesioner, dengan opsi melihat meja dan role akhir.
  goToSurvey(): void {
    this.endView = 'survey';
  }

  showBoard(): void {
    this.endView = 'board';
  }

  showResult(): void {
    this.endView = 'reveal';
  }

  // Jelaskan hak pemain berdasarkan status hidup, Hostage, dan Gag Order miliknya.
  get privateStatus(): string {
    const me = this.game?.me;
    if (!me) return '';
    if (this.game?.winner)
      return `Status akhir: ${!me.alive ? 'dieksekusi' : me.hostage ? 'hidup sebagai Hostage' : 'masih hidup'}. Hasil menang/kalah mengikuti kubumu.`;
    if (!me.alive) return 'Dieksekusi: kamu menjadi penonton. Hasilmu tetap mengikuti kubumu.';
    if (me.hostage)
      return 'Hostage: kamu masih hidup, tetapi chat, voting, dan skill malam terkunci sampai pertandingan berakhir. Semua pemain tahu kamu disandera. Kamu tetap bagian dari kubu warga.';
    if (me.gagged)
      return 'Gag Order: chat terkunci sampai siang berikutnya. Voting dan aksi malam tetap boleh dilakukan.';
    if (me.muted) return 'Chat dan voting terkunci untukmu.';
    return 'Kamu masih hidup dan bebas. Hak chat, aksi, dan voting mengikuti fase permainan.';
  }

  // Sediakan API pertandingan, navigasi, deteksi perubahan, dan lifecycle komponen.
  constructor(
    @Inject(PLATFORM_ID) private readonly platform: object,
    private readonly api: GameService,
    private readonly router: Router,
    private readonly changeDetector: ChangeDetectorRef,
    private readonly destroyRef: DestroyRef,
    private readonly injector: Injector,
  ) {}

  // INIT: polling menjaga snapshot setelah reconnect; Socket.IO membawa pesan/error langsung.
  ngOnInit(): void {
    if (!isPlatformBrowser(this.platform)) return;

    // INPUT: kode room yang tersimpan di tab ini
    this.code = sessionStorage.getItem(STORAGE.room) ?? '';
    if (!this.code) {
      void this.router.navigateByUrl('/lobby');
      return;
    }

    // PROSES: ambil snapshot sekarang, ulangi tiap detik, dan jalankan timer dari jam browser
    this.refresh();
    this.timerPolling = setInterval(() => this.refresh(), 1000);
    this.timerSisaDetik = setInterval(() => this.perbaruiSisaDetik(), 500);

    // OUTPUT: status koneksi, peringatan, dan chat dari server lewat socket
    this.socket = io(`${backendUrl()}`, {
      auth: { token: localStorage.getItem(STORAGE.token), room_code: this.code },
      transports: ['websocket', 'polling'],
    });
    this.socket.on('connect', () => {
      this.connected = true;
      this.changeDetector.markForCheck();
    });
    this.socket.on('disconnect', () => {
      this.connected = false;
      this.changeDetector.markForCheck();
    });
    this.socket.on('connect_error', () => {
      this.connected = false;
      this.error = 'Chat belum tersambung. Periksa koneksi atau kembali ke lobby.';
      this.changeDetector.markForCheck();
    });
    this.socket.on('system_alert', (data: { msg: string }) => {
      this.error = data.msg;
      this.changeDetector.markForCheck();
    });
    this.socket.on('receive_chat', (message: GameMessage) => {
      if (this.game && !this.game.messages.some((item) => item.id === message.id))
        this.game.messages = [...this.game.messages, message].slice(-100);
      // Kalimat bot sudah tiba: awan berpikirnya hilang tanpa menunggu polling berikutnya.
      const sender = this.game?.players.find((player) => player.name === message.sender);
      if (sender?.thinking) sender.thinking = false;
      this.perbaruiPenandaPesan();
      this.changeDetector.markForCheck();
    });
  }

  // Putuskan socket dan hentikan polling saat meninggalkan halaman pertandingan.
  ngOnDestroy(): void {
    this.stopRoleReading();
    this.socket?.disconnect();
    if (this.timerPolling) clearInterval(this.timerPolling);
    if (this.timerSisaDetik) clearInterval(this.timerSisaDetik);
    if (this.transitionTimer) clearTimeout(this.transitionTimer);
    if (this.endTimer) clearTimeout(this.endTimer);
    this.feltObserver?.disconnect();
  }

  // TIMER: sisa detik dari jam browser, tidak menunggu snapshot polling berikutnya.
  private perbaruiSisaDetik(): void {
    if (!this.game || this.game.winner) return;
    const sisaTerbaru = Math.max(0, Math.ceil((this.batasFaseLokal - Date.now()) / 1000));
    if (sisaTerbaru === this.sisaDetik) return;
    this.sisaDetik = sisaTerbaru;
    this.changeDetector.markForCheck();
  }

  // CHAT: posisi gulir dicatat saat pemain menggulir; di dasar = ikut turun saat ada pesan baru.
  onChatScroll(): void {
    const list = this.messageList?.nativeElement;
    if (!list) return;
    this.chatAtBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 48;
    if (this.chatAtBottom) this.jumlahPesanBaruDiBawah = 0;
  }

  jumpToLatest(): void {
    this.jumlahPesanBaruDiBawah = 0;
    this.chatAtBottom = true;
    this.scrollChat();
  }

  // CHAT: gulir ke pesan terbaru bila pemain sedang di bawah atau baru mengirim pesan; selain itu
  // tampilkan tombol "pesan baru". Hitung pesan belum dibaca untuk tab HP.
  private perbaruiPenandaPesan(): void {
    const messages = this.game?.messages ?? [];
    const idPesanTerbaru = messages[messages.length - 1]?.id ?? '';
    const pemuatanPertama = !this.messagesLoaded;
    this.messagesLoaded = true;
    if (!pemuatanPertama && idPesanTerbaru === this.lastMessageId) return;
    // Riwayat saat halaman dibuka tidak dihitung sebagai pesan baru.
    const posisiPesanLama = this.lastMessageId
      ? messages.findIndex((message) => message.id === this.lastMessageId)
      : -1;
    const jumlahPesanBaru = pemuatanPertama
      ? 0
      : posisiPesanLama >= 0
        ? messages.length - posisiPesanLama - 1
        : messages.length;
    this.lastMessageId = idPesanTerbaru;
    if (jumlahPesanBaru && this.mobileTab !== 'chat')
      this.unread = Math.min(99, this.unread + jumlahPesanBaru);
    const adaPesanSendiri = messages
      .slice(-jumlahPesanBaru || messages.length)
      .some((message) => message.sender === this.game?.me.name);
    if (pemuatanPertama || this.chatAtBottom || (jumlahPesanBaru && adaPesanSendiri))
      this.jumpToLatest();
    else if (jumlahPesanBaru)
      this.jumlahPesanBaruDiBawah = Math.min(99, this.jumlahPesanBaruDiBawah + jumlahPesanBaru);
  }

  // Gulir setelah Angular merender pesan baru; setTimeout bisa jalan sebelum render (aplikasi zoneless),
  // sehingga daftar berhenti setinggi satu pesan di atas dasar.
  private scrollChat(): void {
    if (!isPlatformBrowser(this.platform)) return;
    afterNextRender(
      () => {
        const list = this.messageList?.nativeElement;
        if (list) list.scrollTop = list.scrollHeight;
      },
      { injector: this.injector },
    );
    this.changeDetector.markForCheck();
  }

  // AKHIR: pengumuman pemenang tampil dulu, lalu otomatis lanjut ke kuesioner bila belum diisi.
  private mulaiLayarAkhir(): void {
    if (!this.game?.winner || this.idPertandinganBerakhir === this.game.id) return;
    this.idPertandinganBerakhir = this.game.id;
    this.endView = 'reveal';
    if (this.endTimer) clearTimeout(this.endTimer);
    this.endTimer = setTimeout(() => {
      if (this.endView === 'reveal' && this.surveyState === 'ready') this.endView = 'survey';
      this.changeDetector.markForCheck();
    }, 10000);
  }

  // TRANSISI FASE: overlay singkat (malam meredup, pagi terang) setiap kali fase berganti. Dari layar
  // persiapan, tirai tembus pandang menaungi splash yang memudar dan meja yang muncul (cross-fade).
  // Malam sesudah Tribunal membawa hasil vote dan pagi membawa hasil malam (siapa yang disandera, atau
  // tidak ada); keduanya pengumuman publik server, jadi tampil lebih lama. Malam ronde 1 belum punya
  // hasil Tribunal, jadi lastVerdict kosong dan subjudul biasa yang tampil.
  private showTransition(phase: string, fromSplash = false): void {
    const teksFase = this.transitions[phase];
    if (!teksFase) return;
    const hasilFaseSebelumnya = fromSplash
      ? ''
      : phase === 'night'
        ? this.lastVerdict
        : phase === 'day'
          ? this.lastNightResult
          : '';
    this.transition = fromSplash
      ? { phase: 'start', title: 'Ronde 1 dimulai', subtitle: teksFase.subtitle }
      : { phase, ...teksFase, subtitle: hasilFaseSebelumnya || teksFase.subtitle };
    if (this.transitionTimer) clearTimeout(this.transitionTimer);
    this.transitionTimer = setTimeout(
      () => {
        this.transition = null;
        this.changeDetector.markForCheck();
      },
      fromSplash ? 3000 : hasilFaseSebelumnya ? 3400 : 2600,
    );
  }

  private updatePhaseTransition(): void {
    if (!this.game || this.readingRole) return;
    const kunciFase = `${this.game.id}/${this.game.phase}`;
    // Hanya saat fase berganti di pertandingan yang sama, setelah jeda membaca role selesai.
    if (this.kunciFaseTampil.startsWith(this.game.id + '/') && this.kunciFaseTampil !== kunciFase)
      this.showTransition(this.game.phase, this.kunciFaseTampil.endsWith('/preparing'));
    this.kunciFaseTampil = kunciFase;
  }

  // Pengumuman Tribunal terakhir dari server ("Tribunal mengeksekusi …" atau "… tanpa eksekusi").
  private get lastVerdict(): string {
    const events = this.game?.events ?? [];
    for (let indeks = events.length - 1; indeks >= 0; indeks--)
      if (events[indeks].startsWith('Tribunal')) return events[indeks];
    return '';
  }

  // Hasil malam terakhir dari server tanpa awalan "Malam selesai." ("X disandera: …" atau
  // "Malam ini tidak ada yang disandera.").
  private get lastNightResult(): string {
    const events = this.game?.events ?? [];
    for (let indeks = events.length - 1; indeks >= 0; indeks--)
      if (events[indeks].startsWith('Malam selesai.'))
        return events[indeks].slice('Malam selesai.'.length).trim();
    return '';
  }

  // PERSIAPAN: pemain menandai sudah membaca panduan; ronde 1 tetap menunggu AI siap.
  readyUp(): void {
    const state = this.game;
    if (!state || state.phase !== 'preparing' || this.busy || state.preparation?.consented) return;
    this.kirimPermintaanGame({ match_id: state.id }, 'ready');
  }

  // SURVEI: muat pertanyaan sekali per pertandingan setelah ada pemenang.
  private loadSurvey(): void {
    if (!this.game?.winner || this.idPertandinganSurvei === this.game.id || !this.code) return;
    this.idPertandinganSurvei = this.game.id;
    this.surveyState = 'loading';
    this.api
      .survey(this.code)
      .pipe(
        takeUntilDestroyed(this.destroyRef),
        finalize(() => this.changeDetector.markForCheck()),
      )
      .subscribe({
        next: (status) => {
          this.survey = status;
          this.surveyState = status.submitted ? 'done' : 'ready';
        },
        error: (error: HttpErrorResponse) => {
          this.surveyState = 'unavailable';
          this.surveyError =
            typeof error.error?.detail === 'string'
              ? error.error.detail
              : 'Survei belum bisa dimuat.';
        },
      });
  }

  // SNAPSHOT: polling tidak ditumpuk; pilihan target direset saat ronde/fase berubah. Kartu yang sudah
  // dibuka tetapi belum tercatat dikirim ulang paling cepat tiap 4 detik; di sela itu tetap polling,
  // jadi layar tidak macet bila backend belum mengenal /reveal.
  refresh(): void {
    if (this.busy || this.sedangPolling || this.leaving || !this.code) return;
    if (this.revealPending && this.game && Date.now() - this.lastRevealTry >= 4000) {
      this.lastRevealTry = Date.now();
      this.kirimPermintaanGame({ match_id: this.game.id }, 'reveal', true);
    } else this.kirimPermintaanGame(undefined, 'play', true);
  }

  // Sinkronkan snapshot/aksi server, reset pilihan fase lama, dan tampilkan kegagalan request.
  private kirimPermintaanGame(body?: unknown, action = 'play', pollingLatar = false): void {
    const nomorAksi = pollingLatar ? this.nomorAksiTerakhir : ++this.nomorAksiTerakhir;
    if (pollingLatar) this.sedangPolling = true;
    else this.busy = true;
    const idPesanSaatDikirim = new Set(this.game?.messages.map((message) => message.id));
    this.api
      // Polling yang tersendat di jaringan dilepas sesudah 4 detik agar polling berikutnya bisa jalan.
      .request(this.code, body, action, pollingLatar ? 4000 : 10000)
      .pipe(
        takeUntilDestroyed(this.destroyRef),
        finalize(() => {
          if (pollingLatar) this.sedangPolling = false;
          else this.busy = false;
          this.changeDetector.markForCheck();
        }),
      )
      .subscribe({
        next: (snapshot) => {
          // Pemain menekan tombol saat polling berjalan: snapshot polling sudah basi.
          if (nomorAksi !== this.nomorAksiTerakhir) return;

          // INPUT: bandingkan snapshot baru dengan yang masih tampil, sebelum diganti
          const kartuTerlewat =
            this.game?.phase === 'preparing' &&
            this.game.id === snapshot.game.id &&
            !this.kartuRoleTerbuka &&
            !this.game.preparation?.revealed &&
            snapshot.game.phase !== 'preparing' &&
            !snapshot.game.winner;
          if (this.readingRole && (snapshot.game.id !== this.game?.id || snapshot.game.winner))
            this.stopRoleReading();
          if (this.game && this.game.id !== snapshot.game.id) {
            this.kartuRoleTerbuka = false;
            this.idPertandinganRoleDibaca = '';
          }
          // Echo socket dapat tiba sesudah snapshot server dibuat tetapi sebelum HTTP selesai.
          // Pertahankan pesan baru itu, tanpa menghidupkan lagi riwayat lama yang sudah dipangkas.
          const pesanSelamaPermintaan =
            this.game?.id === snapshot.game.id
              ? this.game.messages.filter((message) => !idPesanSaatDikirim.has(message.id))
              : [];
          const idPesanSnapshot = new Set(snapshot.game.messages.map((message) => message.id));
          snapshot.game.messages = [
            ...snapshot.game.messages,
            ...pesanSelamaPermintaan.filter((message) => !idPesanSnapshot.has(message.id)),
          ].slice(-100);

          // PROSES: ganti snapshot, lalu sesuaikan kartu role, pesan, timer, dan pilihan fase
          this.game = snapshot.game;
          if (kartuTerlewat) {
            // Reconnect/tab tidur bisa melewati lima detik terakhir: tetap beri waktu melihat role.
            this.kartuRoleTerbuka = true;
            this.startRoleReading(true);
          } else if (
            this.game.phase === 'preparing' &&
            this.preparationSeconds <= 5 &&
            !this.kartuRoleTerbuka &&
            !this.game.preparation?.revealed &&
            this.idPertandinganRoleDibaca !== this.game.id
          ) {
            this.toggleRole();
          }
          this.durations = snapshot.room?.match_durations ?? this.durations;
          this.perbaruiPenandaPesan();
          this.batasFaseLokal = Date.now() + (this.game.deadline - this.game.server_time) * 1000;
          this.sisaDetik = this.game.winner
            ? 0
            : Math.max(0, Math.ceil(this.game.deadline - this.game.server_time));
          const kunciFase = `${this.game.id}/${this.game.round}/${this.game.phase}`;
          if (kunciFase !== this.kunciFaseTerakhir) {
            this.target = '';
            this.teamDraft = '';
            this.kunciFaseTerakhir = kunciFase;
          }

          // OUTPUT: transisi fase, layar akhir, dan pembersihan pesan error
          this.updatePhaseTransition();
          if (this.game.winner) {
            this.loadSurvey();
            this.mulaiLayarAkhir();
          }
          // Aksi berhasil, atau polling pulih dari gangguan jaringan: hapus pesan error sebelumnya.
          if ((body && action !== 'reveal') || this.errorDariPollingLatar) {
            this.error = '';
            this.errorDariPollingLatar = false;
          }
        },
        error: (error: HttpErrorResponse) => {
          // Pembukaan kartu dikirim ulang oleh polling; backend lama belum punya /reveal (404).
          // Polling yang sudah dilewati klik pemain juga tidak boleh menimpa hasil klik itu.
          if (action === 'reveal' || nomorAksi !== this.nomorAksiTerakhir) return;
          // GET /game menolak room hilang, keanggotaan lama, atau match belum dimulai.
          // Pulihkan lewat lobby; kesalahan aksi dan jaringan tidak boleh mengeluarkan pemain.
          if (!body && error.status === 400) {
            this.exitRoom('/lobby');
            return;
          }
          this.error =
            typeof error.error?.detail === 'string'
              ? error.error.detail
              : 'Server belum bisa dihubungi.';
          this.errorDariPollingLatar = pollingLatar;
          if (error.status === 401) void this.router.navigateByUrl('/login');
          // Aksi ditolak, mis. fase berganti tepat saat pilihan dikirim: ambil snapshot baru tanpa menunggu.
          else if (!pollingLatar && error.status === 400) setTimeout(() => this.refresh());
        },
      });
  }

  // AKSI: token fase menolak tombol lama yang diklik ketika timer sudah berganti.
  kirimPilihanTarget(adalahVote = false): void {
    if (!this.game || !this.target || this.busy) return;
    this.kirimPermintaanGame({
      match_id: this.game.id,
      round_number: this.game.round,
      phase: this.game.phase,
      target: this.target,
      ability: adalahVote ? null : this.game.me.ability,
    });
  }

  // BATAL VOTE: tarik suara Tribunal sendiri; tombol Kunci vote muncul lagi untuk memilih ulang.
  cancelVote(): void {
    if (!this.game?.me.can_cancel_vote || this.busy) return;
    this.kirimPermintaanGame(
      { match_id: this.game.id, round_number: this.game.round, phase: this.game.phase },
      'cancel-vote',
    );
  }

  // BATAL AKSI MALAM: tarik Hostage/Guard/Peek sendiri; tombol aksi muncul lagi untuk memilih ulang.
  cancelAction(): void {
    if (!this.game?.me.can_cancel_action || this.busy) return;
    this.kirimPermintaanGame(
      { match_id: this.game.id, round_number: this.game.round, phase: this.game.phase },
      'cancel-action',
    );
  }

  // Persetujuan bukan chat/vote: manusia hidup yang dibungkam tetap boleh setuju.
  skipDiscussion(): void {
    if (!this.game?.discussion_skip.can_consent || this.busy) return;
    this.kirimPermintaanGame(
      { match_id: this.game.id, round_number: this.game.round, phase: this.game.phase },
      'skip-discussion',
    );
  }

  // KELUAR: tombol Keluar membuka pop-up konfirmasi bergaya game (bukan dialog bawaan browser).
  leaveMatch(): void {
    if (this.code && !this.leaving) this.popupKeluarTerbuka = true;
  }

  // Setelah dikonfirmasi, server menganggap pemain tereliminasi seperti dieksekusi (status "Keluar")
  // dan tidak bisa kembali ke pertandingan ini; lalu pemain dibawa ke menu utama.
  confirmLeaveMatch(): void {
    if (!this.code || this.leaving) return;
    this.popupKeluarTerbuka = false;
    this.leaving = true;
    this.api
      .leave(this.code)
      .pipe(
        takeUntilDestroyed(this.destroyRef),
        finalize(() => {
          this.leaving = false;
          this.changeDetector.markForCheck();
        }),
      )
      .subscribe({
        next: () => this.exitRoom('/main'),
        error: (error: HttpErrorResponse) => {
          // 400 = sudah bukan anggota room (mis. room sudah dibersihkan): tetap tinggalkan layar ini.
          if (error.status === 400) return this.exitRoom('/main');
          this.error =
            typeof error.error?.detail === 'string'
              ? error.error.detail
              : 'Gagal keluar dari permainan. Coba lagi.';
          if (error.status === 401) void this.router.navigateByUrl('/login');
        },
      });
  }

  // Lepas room di tab ini: hentikan polling/socket, hapus pointer room, lalu pindah halaman.
  private exitRoom(url: string): void {
    this.stopRoleReading();
    if (this.timerPolling) clearInterval(this.timerPolling);
    if (this.timerSisaDetik) clearInterval(this.timerSisaDetik);
    this.socket?.disconnect();
    this.game = null;
    this.code = '';
    forgetRoom();
    void this.router.navigateByUrl(url);
  }

  // TARGET: bantuan UX saja; semua aturan juga diperiksa engine.
  canTarget(name: string): boolean {
    const me = this.game?.me;
    if (!me) return false;
    // Rekan Syndicate dan korban Hostage tidak bisa disandera atau dibungkam; vote ke mereka tetap boleh.
    if (
      me.can_act &&
      (me.ability === 'hostage' || me.ability === 'gag') &&
      (this.isAlly(name) || !!this.game?.players.find((player) => player.name === name)?.hostage)
    )
      return false;
    // Guard boleh ke siapa saja yang hidup, termasuk diri sendiri dan target malam sebelumnya.
    if (me.ability === 'guard' && me.can_act) return true;
    return name !== me.name;
  }

  // TRIBUNAL: pemilih yang sudah mengunci suara ke pemain ini (publik selama Tribunal).
  votersFor(name: string): string[] {
    return this.game?.tribunal_votes.find((item) => item.target === name)?.voters ?? [];
  }

  // CHAT: hanya echo server ditampilkan supaya pesan yang ditolak tidak tampak terkirim.
  sendMessage(): void {
    if (!this.game?.me.can_chat || !this.connected || !this.draft.trim()) return;
    this.error = '';
    this.socket?.emit('send_chat', { username: this.game.me.name, message: this.draft.trim() });
    this.draft = '';
  }

  // CHAT TIM: lewat HTTP dengan token fase, bukan socket ruangan, jadi pesan tidak pernah disiarkan.
  // Pesan kembali lewat snapshot privat pengirim dan rekan setim.
  sendTeamMessage(): void {
    const state = this.game;
    const message = this.teamDraft.trim();
    if (!state?.me.can_team_chat || !message || this.busy) return;
    this.kirimPermintaanGame(
      { match_id: state.id, round_number: state.round, phase: state.phase, message },
      'team-chat',
    );
    this.teamDraft = '';
  }
}
