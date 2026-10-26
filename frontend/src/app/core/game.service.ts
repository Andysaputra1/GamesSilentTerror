import { backendUrl } from './backend-url';
import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { map, timeout } from 'rxjs';
import { Room } from './room.service';
import { authHeaders } from './storage';

export interface GameMessage {
  id: string;
  sender: string;
  message: string;
}
// Layar persiapan sebelum ronde 1: progres AI dan hitung mundur dari server.
export interface Preparation {
  ready: boolean;
  detail: string;
  progress: number;
  starts_in: number | null;
  max_wait: number;
  agreed: number;
  required: number;
  consented: boolean;
  bots: number;
  // Status pembukaan role; tidak mempercepat countdown bersama (opsional untuk backend lama).
  elapsed?: number;
  revealed?: boolean;
  unrevealed?: number;
}
// Komposisi role room (publik); jumlah Hitman dan Spy mengikuti jumlah pemain dan ditentukan backend.
export interface RoleComposition {
  hitman: number;
  spy: number;
  stalker: number;
  civilian: number;
}
export interface MatchView {
  id: string;
  phase: 'preparing' | 'day' | 'night' | 'tribunal' | 'finished';
  round: number;
  deadline: number;
  server_time: number;
  winner: 'hitman' | 'civilians' | null;
  // Opsional: backend lama belum mengirimnya.
  composition?: RoleComposition | null;
  // Room dengan ≥ 2 Hitman: jumlah Hitman yang masih hidup, diumumkan setelah setiap eksekusi.
  hitman_remaining?: number | null;
  preparation?: Preparation | null;
  result?: {
    reason: 'hitman_executed' | 'all_survivors_hostage' | 'no_civilians_alive' | 'vote_control';
    team: 'hitman' | 'civilians';
    outcome: 'won' | 'lost';
    civilians_alive: number;
    civilians_hostage: number;
    civilians_eliminated: number;
    civilians_voters?: number;
  } | null;
  tribunal_votes: { target: string; voters: string[] }[];
  discussion_skip: { agreed: number; required: number; consented: boolean; can_consent: boolean };
  events: string[];
  players: {
    name: string;
    /** Nama tampilan akun; `name` (username) tetap dipakai untuk aksi dan vote. */
    label?: string;
    /** Metode otak bot (fuzzy, utility, bt, llm); hanya ada untuk bot setelah persiapan AI. */
    metode?: string;
    /** Bot sedang menyusun chat (lantai bicara); ditampilkan sebagai awan berpikir. */
    thinking?: boolean;
    /** Tahap langkah terakhir bot: I input diterima, L logika berjalan, O output/aksi selesai. */
    tahap?: 'I' | 'L' | 'O';
    bot?: boolean;
    alive: boolean;
    /** Keluar di tengah pertandingan: tidak hidup seperti dieksekusi, tetapi ditampilkan "Keluar". */
    left?: boolean;
    role?: string;
    hostage?: boolean;
    skin_id?: string;
  }[];
  messages: GameMessage[];
  me: {
    name: string;
    role: string;
    alive: boolean;
    muted: boolean;
    hostage?: boolean;
    gagged?: boolean;
    can_chat: boolean;
    can_vote: boolean;
    vote: string | null;
    ability: string | null;
    can_act: boolean;
    action: { ability: string; target: string } | null;
    // Cooldown Gag bersama Syndicate (sama untuk semua Hitman).
    next_gag: number;
    next_peek: number;
    last_guard: string | null;
    intel: { round: number; name: string; role: string }[];
    // Hanya untuk Hitman: rekan Syndicate dan pilihan Hostage mereka malam ini; selain itu kosong.
    allies?: string[];
    ally_actions?: { name: string; target: string }[];
    // Hanya untuk Hitman (opsional agar cocok dengan backend versi lama): target Gag ronde ini dan
    // korban Hostage tim malam ini.
    ally_gags?: string[];
    syndicate_target?: string | null;
    // Hanya untuk Hitman: hasil Hostage tim tiap malam (gagal = target dijaga Guard).
    syndicate_hostages?: { round: number; name: string; success: boolean }[];
  };
}
export interface GameSnapshot {
  room: Room;
  game: MatchView;
}
// Pertanyaan survei beserta jenis, skala, dan arti ujung skala; semuanya diatur backend.
export interface SurveyQuestion {
  id: number;
  code: string;
  prompt: string;
  kind: 'stars' | 'scale' | 'choice' | 'text';
  scale_min: number;
  scale_max: number;
  label_min: string | null;
  label_max: string | null;
  options: string[];
  required: boolean;
}
export interface SurveyStatus {
  match_id: string;
  submitted: boolean;
  questions: SurveyQuestion[];
}
// Pertandingan selesai yang surveinya belum diisi akun ini (pengingat di Main).
export interface PendingSurvey {
  match_id: string;
  room_code: string;
  role: string;
  team: 'hitman' | 'civilians';
  outcome: 'won' | 'lost';
  finished_at: string;
}
export interface SurveyAnswer {
  question_id: number;
  value?: number | null;
  text?: string | null;
}

// ADAPTER HTTP: backend memutuskan izin, role, dan hasil aksi.
@Injectable({ providedIn: 'root' })
export class GameService {
  constructor(private readonly http: HttpClient) {}

  // Kirim aksi atau ambil snapshot privat pertandingan dengan token sesi dan timeout.
  request(code: string, body?: unknown, action = 'play') {
    const base = `${backendUrl()}/api/rooms/${encodeURIComponent(code)}`;
    return this.http
      .request<GameSnapshot>(body ? 'POST' : 'GET', base + (body ? '/' + action : '/game'), {
        body,
        headers: authHeaders(),
      })
      .pipe(timeout(10000));
  }

  // Keluar dari room. Di tengah pertandingan server menganggap pemain tereliminasi (status `left`);
  // permintaan ulang tetap dijawab berhasil.
  leave(code: string) {
    return this.http
      .post<{ left: boolean }>(
        `${backendUrl()}/api/rooms/${encodeURIComponent(code)}/leave`,
        null,
        { headers: authHeaders() },
      )
      .pipe(timeout(10000));
  }

  // Survei akhir: pertanyaan aktif dan status pengiriman untuk pertandingan yang sudah selesai.
  // matchId dipakai pengingat di Main agar tepat ke pertandingan yang dimaksud.
  survey(code: string, matchId?: string) {
    return this.http
      .get<SurveyStatus>(`${backendUrl()}/api/rooms/${encodeURIComponent(code)}/survey`, {
        headers: authHeaders(),
        params: matchId ? { match_id: matchId } : {},
      })
      .pipe(timeout(10000));
  }

  // Survei pertandingan selesai yang belum diisi (terbaru dulu), untuk pengingat di Main.
  pendingSurveys() {
    return this.http
      .get<{ surveys: PendingSurvey[] }>(`${backendUrl()}/api/survey/pending`, {
        headers: authHeaders(),
      })
      .pipe(
        timeout(10000),
        map((response) => response.surveys),
      );
  }

  // Kirim jawaban survei sekali; validasi skala tetap dilakukan backend.
  submitSurvey(code: string, matchId: string, answers: SurveyAnswer[]) {
    return this.http
      .post<{
        submitted: boolean;
        answers: number;
      }>(
        `${backendUrl()}/api/rooms/${encodeURIComponent(code)}/survey`,
        { match_id: matchId, answers },
        { headers: authHeaders() },
      )
      .pipe(timeout(10000));
  }
}
