import { backendUrl } from '../../core/backend-url';
import { isPlatformBrowser, NgTemplateOutlet } from '@angular/common';
import {
  ChangeDetectorRef,
  Component,
  DestroyRef,
  ElementRef,
  Inject,
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
  SurveyQuestion,
  SurveyStatus,
} from '../../core/game.service';
import { gameEntryStorageKey } from '../../core/flow.guard';
import { ProfileMenu } from '../../core/profile-menu';
import { PhaseDurations } from '../../core/room.service';

// Karakter meja dan warna label pemain: berdasarkan urutan kursi, bukan role atau status rahasia.
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

// KOMPONEN: render snapshot privat server; tidak mengacak role atau memutuskan hasil aksi di browser.
@Component({
  selector: 'app-game',
  imports: [FormsModule, RouterLink, ProfileMenu, NgTemplateOutlet],
  templateUrl: './game.html',
  styleUrls: [
    './game.css',
    './game-table.css',
    './game-screens.css',
    './game-end.css',
    './game-motion.css',
  ],
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
  // Tampilan: tab di HP, panel aturan, dan layar akhir (pengumuman → kuesioner → meja akhir).
  mobileTab: 'table' | 'chat' | 'info' = 'table';
  unread = 0;
  showRules = false;
  endView: 'reveal' | 'survey' | 'board' = 'reveal';
  durations: PhaseDurations | null = null;
  @ViewChild('messageList') private messageList?: ElementRef<HTMLElement>;
  private lastMessageId = '';
  private messagesLoaded = false;
  private feltSize = { width: 0, height: 0 };
  private feltObserver?: ResizeObserver;
  private endMatch = '';
  private endTimer?: ReturnType<typeof setTimeout>;
  readonly phaseSteps = [
    { key: 'day', label: 'Diskusi', icon: '☀' },
    { key: 'night', label: 'Malam', icon: '☾' },
    { key: 'tribunal', label: 'Tribunal', icon: '⚖' },
  ];
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
  // Survei akhir: pertanyaan, jawaban lokal, dan status pengiriman.
  survey: SurveyStatus | null = null;
  surveyAnswers: Record<number, { value?: number; text?: string }> = {};
  surveyState: 'idle' | 'loading' | 'ready' | 'sending' | 'done' | 'unavailable' = 'idle';
  surveyError = '';
  readonly confetti = Array.from({ length: 28 }, (_, index) => ({
    x: (index * 37) % 100,
    delay: (index % 7) * 0.35,
    color: ['#e3b448', '#36564b', '#c8553d', '#6c8ea4', '#efcfac'][index % 5],
  }));
  private socket?: Socket;
  private poll?: ReturnType<typeof setInterval>;
  private loadedPhase = '';
  private shownPhase = '';
  private surveyMatch = '';
  private transitionTimer?: ReturnType<typeof setTimeout>;
  readonly phaseIcons: Record<string, string> = {
    day: '☀',
    night: '☾',
    tribunal: '⚖',
    finished: '★',
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

  // Panduan singkat di layar persiapan sebelum ronde 1 (juga dipakai modal aturan).
  get guide(): { icon: string; title: string; text: string }[] {
    const banyak = this.multiHitman;
    return [
      {
        icon: '🎭',
        title: 'Tujuan',
        text: 'Warga (Civilian, Spy, Stalker) menang jika semua Hitman dieksekusi. Hitman menang jika warga yang masih bebas bersuara tidak lebih banyak dari Hitman yang masih hidup. Jumlah Hitman dan Spy mengikuti jumlah pemain.',
      },
      {
        icon: '☀',
        title: 'Siang',
        text: banyak
          ? 'Diskusi bebas. Tanyakan alibi, tuduh dengan alasan, dan bela pemain yang kamu percaya. Hitman bisa membungkam satu pemain (Gag Order, dipakai bersama seluruh Hitman).'
          : 'Diskusi bebas. Tanyakan alibi, tuduh dengan alasan, dan bela pemain yang kamu percaya. Hitman bisa membungkam satu pemain (Gag).',
      },
      {
        icon: '☾',
        title: 'Malam',
        text: banyak
          ? 'Layar meredup dan chat dikunci. Para Hitman menyandera satu pemain (pilihan terbanyak mereka), setiap Spy menjaga satu pemain, Stalker mengintip role seseorang.'
          : 'Layar meredup dan chat dikunci. Hitman menyandera satu pemain, Spy menjaga satu pemain, Stalker mengintip role seseorang.',
      },
      {
        icon: '⚖',
        title: 'Tribunal',
        text: 'Pemain yang masih punya suara memilih tersangka. Suara terbanyak tunggal dieksekusi; seri berarti tidak ada eksekusi.',
      },
      {
        icon: '◆',
        title: 'Bot AI',
        text: 'Sebagian kursi diisi bot. Mereka membaca chat, menimbang bukti, dan bisa berbohong jika menjadi Hitman. Perlakukan seperti pemain lain.',
      },
      {
        icon: '💡',
        title: 'Tips',
        text: banyak
          ? 'Diam bukan bukti. Para Hitman saling mengenal: perhatikan siapa yang kompak saling membela atau mendorong vote bersama.'
          : 'Diam bukan bukti. Perhatikan siapa yang mendorong vote ke pemain yang ternyata bukan Hitman.',
      },
    ];
  }

  get roleHelp(): Record<string, string> {
    return {
      hitman: this.multiHitman
        ? 'Malam: pilih satu warga untuk disandera; Syndicate hanya menyandera satu orang per malam (pilihan terbanyak para Hitman). Siang: Gag Order dipakai bersama, lalu jeda satu ronde.'
        : 'Malam: Hostage satu warga. Siang: Gag Order, lalu lewati satu ronde sebelum memakai lagi.',
      spy:
        'Malam: Guard satu pemain (boleh diri sendiri). Jangan pilih target sama dua malam berturut-turut.' +
        ((this.game?.composition?.spy ?? 1) > 1 ? ' Spy lain berjaga sendiri-sendiri.' : ''),
      stalker:
        'Malam: Peek identitas satu pemain, sekali setiap dua ronde. Hasil hanya terlihat olehmu.',
      civilian:
        'Amati percakapan, uji alibi, dan pilih tersangka saat Tribunal. Tidak punya skill malam.',
    };
  }
  readonly phaseNames: Record<string, string> = {
    preparing: 'Persiapan',
    day: 'Siang / diskusi',
    night: 'Malam / aksi rahasia',
    tribunal: 'Tribunal / voting',
    finished: 'Hasil akhir',
  };

  // Tampilkan tujuan kubu pemain berdasarkan role privat dari server.
  get objective(): string {
    if (this.game?.me.role === 'hitman')
      return `${this.allies.length ? 'Bersama rekan Syndicate, kurangi' : 'Kurangi'} warga hidup yang masih punya suara sampai tidak lebih banyak dari Hitman yang masih hidup. Hindari eksekusi Tribunal.`;
    const hitmen = this.hitmanCount > 1 ? `semua ${this.hitmanCount} Hitman` : 'Hitman';
    return `Temukan dan eksekusi ${hitmen} lewat Tribunal. Spy, Stalker, dan Civilian menang sebagai satu kubu.`;
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
  hitmanLeft(item: { role: string }, place: string): number | null {
    return item.role === 'hitman' && place === 'felt-composition' ? this.hitmanRemaining : null;
  }

  // Kalimat pembuka layar persiapan.
  get threatLine(): string {
    if (this.hitmanCount > 1)
      return `${this.hitmanCount} Hitman bersembunyi di antara kalian dan saling mengenal.`;
    return this.hitmanCount === 1
      ? 'Satu Hitman bersembunyi di antara kalian.'
      : 'Hitman bersembunyi di antara kalian.';
  }

  // REKAN SYNDICATE: server hanya mengirim daftar ini kepada Hitman; role lain selalu kosong.
  get allies(): string[] {
    return this.game?.me.role === 'hitman' ? (this.game.me.allies ?? []) : [];
  }

  isAlly(name: string): boolean {
    return this.allies.includes(name);
  }

  // Pilihan Hostage rekan yang masih hidup malam ini (null = belum memilih).
  get allyPlan(): { name: string; target: string | null }[] {
    const game = this.game;
    if (!game || game.phase !== 'night') return [];
    const actions = game.me.ally_actions ?? [];
    return this.allies
      .filter((name) => game.players.some((player) => player.name === name && player.alive))
      .map((name) => ({
        name,
        target: actions.find((action) => action.name === name)?.target ?? null,
      }));
  }

  // Target terbanyak dari pilihan rekan; seri → pilihan yang masuk lebih dulu (sama dengan engine).
  get allyTarget(): string {
    const game = this.game;
    if (!game || game.phase !== 'night') return '';
    const counts = new Map<string, number>();
    for (const action of game.me.ally_actions ?? [])
      counts.set(action.target, (counts.get(action.target) ?? 0) + 1);
    let best = '';
    for (const [target, count] of counts) if (count > (counts.get(best) ?? 0)) best = target;
    return best;
  }

  // Rekan yang memilih pemain ini sebagai target Hostage malam ini (penanda di kartu meja).
  allyPicks(name: string): string[] {
    const game = this.game;
    if (!game || game.phase !== 'night') return [];
    return (game.me.ally_actions ?? [])
      .filter((action) => action.target === name)
      .map((action) => action.name);
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
    const hitmen = this.hitmanCount > 1 ? 'Semua Hitman' : 'Hitman';
    const explanations: Record<string, string> = {
      vote_control:
        'Warga hidup yang masih punya hak voting tidak lebih banyak dari Hitman yang masih hidup. Suara warga tidak lagi bisa mengalahkan suara Hitman.',
      hitman_executed: `${hitmen} telah dieksekusi. Semua anggota kubu warga menang, termasuk yang menjadi Hostage atau sudah dieksekusi.`,
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

  // Skala 1..N untuk pertanyaan bintang/angka dari backend.
  scaleValues(question: SurveyQuestion): number[] {
    return Array.from(
      { length: question.scale_max - question.scale_min + 1 },
      (_, index) => question.scale_min + index,
    );
  }

  // Bintang menyala sampai nilai terpilih; skala angka hanya menandai nilai terpilih.
  isSelected(question: SurveyQuestion, value: number): boolean {
    const chosen = this.surveyAnswers[question.id]?.value;
    if (chosen === undefined) return false;
    return question.kind === 'stars' ? value <= chosen : value === chosen;
  }

  setAnswer(question: SurveyQuestion, value: number): void {
    this.surveyAnswers = { ...this.surveyAnswers, [question.id]: { value } };
  }

  setText(question: SurveyQuestion, text: string): void {
    this.surveyAnswers = { ...this.surveyAnswers, [question.id]: { text } };
  }

  // Tombol kirim aktif setelah semua pertanyaan wajib dijawab.
  get surveyComplete(): boolean {
    return (this.survey?.questions ?? []).every((question) => {
      const answer = this.surveyAnswers[question.id];
      if (!question.required) return true;
      return question.kind === 'stars' || question.kind === 'scale'
        ? answer?.value !== undefined
        : !!answer?.text?.trim();
    });
  }

  readonly phaseShort: Record<string, string> = {
    preparing: 'Persiapan',
    day: 'Siang',
    night: 'Malam',
    tribunal: 'Tribunal',
    finished: 'Selesai',
  };

  // Judul dan penjelasan baki aksi sesuai fase dan hak pemain.
  get actionTitle(): string {
    const state = this.game;
    if (!state) return '';
    if (state.me.can_vote) return 'Tribunal · satu suara final';
    if (state.me.can_act)
      return `Aksi rahasia · ${this.abilityNames[state.me.ability ?? ''] ?? state.me.ability}`;
    return (
      ({ day: 'Diskusi siang', night: 'Malam', tribunal: 'Tribunal' } as Record<string, string>)[
        state.phase
      ] ?? ''
    );
  }

  get actionHint(): string {
    const state = this.game;
    if (!state) return '';
    if (state.me.can_vote)
      return 'Pilih tersangka di meja, lalu kunci suaramu. Suara terbanyak tunggal dieksekusi; seri berarti tidak ada eksekusi.';
    if (state.me.can_act && this.allies.length && state.me.ability === 'hostage')
      return 'Pilih satu warga di meja. Syndicate hanya menyandera satu orang: target terbanyak dari pilihan para Hitman; seri → pilihan yang masuk lebih dulu.';
    if (state.me.can_act && this.allies.length && state.me.ability === 'gag')
      return 'Pilih pemain yang dibungkam. Gag Order dipakai bersama rekan: satu kali per siang, lalu jeda satu ronde penuh.';
    if (state.me.can_act)
      return 'Pilih target di meja. Pilihan tidak dapat diubah setelah dikunci.';
    if (state.phase === 'night')
      return 'Tunggu aksi malam diselesaikan. Skill mungkin sudah dipakai, cooldown, atau tidak tersedia untuk role/statusmu.';
    if (state.phase === 'day')
      return 'Bicara di chat: tanya alibi, tuduh dengan alasan, dan bela pemain yang kamu percaya.';
    return 'Tidak ada aksi tersedia saat ini. Amati percakapan dan tunggu fase berikutnya.';
  }

  get chatHint(): string {
    if (!this.game) return '';
    if (this.game.winner) return 'Pertandingan selesai. Riwayat diskusi tetap bisa dibaca.';
    if (this.game.phase === 'night') return 'Malam: semua chat terkunci.';
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

  skinFor(name: string): string {
    return `/assets/characters/skin_${SKINS[this.playerIndex(name) % SKINS.length]}.png`;
  }

  colorFor(name: string): string {
    return TAG_COLORS[this.playerIndex(name) % TAG_COLORS.length];
  }

  // Warna chip pemilih sama dengan label nama pemilih di meja dan chat.
  voterColor(name: string): string {
    return this.colorFor(name);
  }

  roleCard(role?: string | null): string {
    return `/assets/cards/card_${role && ROLES.includes(role) ? role : 'blank'}.png`;
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
    const tally = (this.game?.tribunal_votes ?? []).filter((item) => item.voters.length > 0);
    if (!tally.length) return '';
    const top = Math.max(...tally.map((item) => item.voters.length));
    const leaders = tally.filter((item) => item.voters.length === top);
    return leaders.length === 1 ? leaders[0].target : '';
  }

  // Susunan meja: jumlah kolom yang membuat kartu (rasio 4:5) paling besar di papan yang tersedia.
  // Tanpa ukuran papan (render awal/test): satu baris sampai 5 pemain, selebihnya dua baris.
  get tableColumns(): number {
    const count = this.game?.players.length ?? 0;
    const { width, height } = this.feltSize;
    if (!count || !width || !height) return count <= 5 ? Math.max(1, count) : Math.ceil(count / 2);
    const gap = 16;
    let best = 1;
    let bestSize = 0;
    for (let cols = 1; cols <= count; cols++) {
      const rows = Math.ceil(count / cols);
      const size = Math.min(
        200,
        (width - (cols - 1) * gap) / cols,
        ((height - (rows - 1) * gap) / rows) * 0.8,
      );
      if (size >= bestSize - 0.5) {
        best = cols;
        bestSize = size;
      }
    }
    return best;
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
      this.cdr.markForCheck();
    });
    this.feltObserver.observe(ref.nativeElement);
  }

  // Sisa waktu fase (0–1) untuk cincin timer; durasi fase berasal dari room snapshot.
  get timerFraction(): number {
    const phase = this.game?.phase;
    if (!this.game || this.game.winner || !this.durations || !phase || !(phase in this.durations))
      return 1;
    const total = this.durations[phase as keyof PhaseDurations];
    return total > 0 ? Math.max(0, Math.min(1, this.seconds / total)) : 1;
  }

  get timerUrgent(): boolean {
    return (
      !!this.game && !this.game.winner && this.game.phase !== 'preparing' && this.seconds <= 10
    );
  }

  // TAB HP: meja, chat, atau info; membuka chat menghapus penanda pesan baru.
  selectTab(tab: 'table' | 'chat' | 'info'): void {
    this.mobileTab = tab;
    if (tab === 'chat') {
      this.unread = 0;
      this.scrollChat();
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
      return 'Hostage: kamu masih hidup, tetapi chat dan voting terkunci sampai pertandingan berakhir. Skill malam tetap tersedia sesuai role dan cooldown. Kamu tetap bagian dari kubu warga.';
    if (me.gagged)
      return 'Gag Order: chat terkunci sampai akhir Tribunal ronde ini. Voting dan aksi malam tetap boleh dilakukan.';
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
        this.game.messages = [...this.game.messages, message].slice(-100);
      this.afterMessages();
      this.cdr.markForCheck();
    });
  }

  // Putuskan socket dan hentikan polling saat meninggalkan halaman pertandingan.
  ngOnDestroy(): void {
    this.socket?.disconnect();
    if (this.poll) clearInterval(this.poll);
    if (this.transitionTimer) clearTimeout(this.transitionTimer);
    if (this.endTimer) clearTimeout(this.endTimer);
    this.feltObserver?.disconnect();
  }

  // CHAT: gulir ke pesan terbaru bila pemain sedang di bawah; hitung pesan belum dibaca untuk tab HP.
  private afterMessages(): void {
    const messages = this.game?.messages ?? [];
    const last = messages[messages.length - 1]?.id ?? '';
    const firstLoad = !this.messagesLoaded;
    this.messagesLoaded = true;
    if (!firstLoad && last === this.lastMessageId) return;
    // Riwayat saat halaman dibuka tidak dihitung sebagai pesan baru.
    const index = this.lastMessageId
      ? messages.findIndex((message) => message.id === this.lastMessageId)
      : -1;
    const added = firstLoad ? 0 : index >= 0 ? messages.length - index - 1 : messages.length;
    this.lastMessageId = last;
    if (added && this.mobileTab !== 'chat') this.unread = Math.min(99, this.unread + added);
    const list = this.messageList?.nativeElement;
    if (firstLoad || !list || list.scrollHeight - list.scrollTop - list.clientHeight < 140)
      this.scrollChat();
  }

  private scrollChat(): void {
    if (!isPlatformBrowser(this.platform)) return;
    setTimeout(() => {
      const list = this.messageList?.nativeElement;
      if (list) list.scrollTop = list.scrollHeight;
    });
  }

  // AKHIR: pengumuman pemenang tampil dulu, lalu otomatis lanjut ke kuesioner bila belum diisi.
  private startEnding(): void {
    if (!this.game?.winner || this.endMatch === this.game.id) return;
    this.endMatch = this.game.id;
    this.endView = 'reveal';
    if (this.endTimer) clearTimeout(this.endTimer);
    this.endTimer = setTimeout(() => {
      if (this.endView === 'reveal' && this.surveyState === 'ready') this.endView = 'survey';
      this.cdr.markForCheck();
    }, 10000);
  }

  // TRANSISI FASE: overlay singkat (malam meredup, pagi terang) setiap kali fase berganti.
  private showTransition(phase: string): void {
    const info = this.transitions[phase];
    if (!info) return;
    this.transition = { phase, ...info };
    if (this.transitionTimer) clearTimeout(this.transitionTimer);
    this.transitionTimer = setTimeout(() => {
      this.transition = null;
      this.cdr.markForCheck();
    }, 2600);
  }

  // PERSIAPAN: pemain menandai sudah membaca panduan; ronde 1 tetap menunggu AI siap.
  readyUp(): void {
    const state = this.game;
    if (!state || state.phase !== 'preparing' || this.busy || state.preparation?.consented) return;
    this.request({ match_id: state.id }, 'ready');
  }

  // SURVEI: muat pertanyaan sekali per pertandingan setelah ada pemenang.
  private loadSurvey(): void {
    if (!this.game?.winner || this.surveyMatch === this.game.id || !this.code) return;
    this.surveyMatch = this.game.id;
    this.surveyState = 'loading';
    this.api
      .survey(this.code)
      .pipe(
        takeUntilDestroyed(this.destroy),
        finalize(() => this.cdr.markForCheck()),
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

  // SURVEI: kirim jawaban; skala dan pertanyaan wajib divalidasi ulang di backend.
  submitSurvey(): void {
    if (!this.survey || !this.surveyComplete || this.surveyState === 'sending') return;
    const answers = this.survey.questions
      .filter((question) => this.surveyAnswers[question.id])
      .map((question) => ({ question_id: question.id, ...this.surveyAnswers[question.id] }));
    this.surveyState = 'sending';
    this.surveyError = '';
    this.api
      .submitSurvey(this.code, this.survey.match_id, answers)
      .pipe(
        takeUntilDestroyed(this.destroy),
        finalize(() => this.cdr.markForCheck()),
      )
      .subscribe({
        next: () => (this.surveyState = 'done'),
        error: (error: HttpErrorResponse) => {
          // 409 = sudah pernah dikirim dari tab lain; anggap selesai.
          this.surveyState = error.status === 409 ? 'done' : 'ready';
          this.surveyError =
            error.status === 409
              ? ''
              : typeof error.error?.detail === 'string'
                ? error.error.detail
                : 'Survei gagal dikirim. Coba lagi.';
        },
      });
  }

  // SNAPSHOT: polling tidak ditumpuk; pilihan target direset saat ronde/fase berubah.
  refresh(): void {
    if (!this.busy && this.code) this.request();
  }

  // Sinkronkan snapshot/aksi server, reset pilihan fase lama, dan tampilkan kegagalan request.
  private request(body?: unknown, action = 'play'): void {
    this.busy = true;
    const messagesAtRequest = new Set(this.game?.messages.map((message) => message.id));
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
          // Echo socket dapat tiba sesudah snapshot server dibuat tetapi sebelum HTTP selesai.
          // Pertahankan pesan baru itu, tanpa menghidupkan lagi riwayat lama yang sudah dipangkas.
          const receivedDuringRequest =
            this.game?.id === snapshot.game.id
              ? this.game.messages.filter((message) => !messagesAtRequest.has(message.id))
              : [];
          const snapshotIds = new Set(snapshot.game.messages.map((message) => message.id));
          snapshot.game.messages = [
            ...snapshot.game.messages,
            ...receivedDuringRequest.filter((message) => !snapshotIds.has(message.id)),
          ].slice(-100);
          this.game = snapshot.game;
          this.durations = snapshot.room?.match_durations ?? this.durations;
          this.afterMessages();
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
          // Overlay transisi hanya saat fase berganti di pertandingan yang sama (bukan saat halaman dibuka).
          const shown = `${this.game.id}/${this.game.phase}`;
          if (this.shownPhase.startsWith(this.game.id + '/') && this.shownPhase !== shown)
            this.showTransition(this.game.phase);
          this.shownPhase = shown;
          if (this.game.winner) {
            this.loadSurvey();
            this.startEnding();
          }
          if (body) {
            this.notice = 'Pilihan dikunci oleh server.';
            this.error = '';
          }
        },
        error: (error: HttpErrorResponse) => {
          // GET /game menolak room hilang, keanggotaan lama, atau match belum dimulai.
          // Pulihkan lewat lobby; kesalahan aksi dan jaringan tidak boleh mengeluarkan pemain.
          if (!body && error.status === 400) {
            if (this.poll) clearInterval(this.poll);
            this.socket?.disconnect();
            this.game = null;
            this.code = '';
            sessionStorage.removeItem('shadow_heist_room');
            sessionStorage.removeItem('shadow_heist_room_snapshot');
            sessionStorage.removeItem(gameEntryStorageKey);
            void this.router.navigateByUrl('/lobby');
            return;
          }
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
    const me = this.game?.me;
    if (!me) return false;
    // Rekan Syndicate tidak bisa disandera atau dibungkam; vote ke rekan tetap boleh.
    if (me.can_act && (me.ability === 'hostage' || me.ability === 'gag') && this.isAlly(name))
      return false;
    if (me.ability === 'guard' && me.can_act) return name !== me.last_guard;
    return name !== me.name;
  }

  // CHAT: hanya echo server ditampilkan supaya pesan yang ditolak tidak tampak terkirim.
  votersFor(name: string): string[] {
    return this.game?.tribunal_votes.find((item) => item.target === name)?.voters ?? [];
  }

  // CHAT: hanya echo server ditampilkan supaya pesan yang ditolak tidak tampak terkirim.
  sendMessage(): void {
    if (!this.game?.me.can_chat || !this.connected || !this.draft.trim() || this.thinking) return;
    this.error = '';
    this.socket?.emit('send_chat', { username: this.game.me.name, message: this.draft.trim() });
    this.draft = '';
  }
}
