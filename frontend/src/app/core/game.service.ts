import { backendUrl } from './backend-url';
import { Injectable } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { timeout } from 'rxjs';
import { Room } from './room.service';

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
}
export interface MatchView {
  id: string;
  phase: 'preparing' | 'day' | 'night' | 'tribunal' | 'finished';
  round: number;
  deadline: number;
  server_time: number;
  winner: 'hitman' | 'civilians' | null;
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
  players: { name: string; bot?: boolean; alive: boolean; role?: string; hostage?: boolean }[];
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
    next_gag: number;
    next_peek: number;
    last_guard: string | null;
    intel: { round: number; name: string; role: string }[];
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
export interface SurveyAnswer {
  question_id: number;
  value?: number | null;
  text?: string | null;
}

// ADAPTER HTTP: backend memutuskan izin, role, dan hasil aksi.
@Injectable({ providedIn: 'root' })
export class GameService {
  // function Object() { [native code] }
  constructor(private readonly http: HttpClient) {}

  // Header sesi pemain untuk semua request pertandingan.
  private headers() {
    return new HttpHeaders({
      Authorization: 'Bearer ' + (localStorage.getItem('shadow_heist_access_token') ?? ''),
    });
  }

  // Kirim aksi atau ambil snapshot privat pertandingan dengan token sesi dan timeout.
  request(code: string, body?: unknown, action = 'play') {
    const base = `${backendUrl()}/api/rooms/${encodeURIComponent(code)}`;
    return this.http
      .request<GameSnapshot>(body ? 'POST' : 'GET', base + (body ? '/' + action : '/game'), {
        body,
        headers: this.headers(),
      })
      .pipe(timeout(10000));
  }

  // Survei akhir: pertanyaan aktif dan status pengiriman untuk pertandingan yang sudah selesai.
  survey(code: string) {
    return this.http
      .get<SurveyStatus>(`${backendUrl()}/api/rooms/${encodeURIComponent(code)}/survey`, {
        headers: this.headers(),
      })
      .pipe(timeout(10000));
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
        { headers: this.headers() },
      )
      .pipe(timeout(10000));
  }
}
