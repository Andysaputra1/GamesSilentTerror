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
export interface MatchView {
  id: string;
  phase: 'day' | 'night' | 'tribunal' | 'finished';
  round: number;
  deadline: number;
  server_time: number;
  winner: 'hitman' | 'civilians' | null;
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

// ADAPTER HTTP: backend memutuskan izin, role, dan hasil aksi.
@Injectable({ providedIn: 'root' })
export class GameService {
  // function Object() { [native code] }
  constructor(private readonly http: HttpClient) {}
  // Kirim aksi atau ambil snapshot privat pertandingan dengan token sesi dan timeout.
  request(code: string, body?: unknown, action = 'play') {
    const base = `${backendUrl()}/api/rooms/${encodeURIComponent(code)}`;
    const headers = new HttpHeaders({
      Authorization: 'Bearer ' + (localStorage.getItem('shadow_heist_access_token') ?? ''),
    });
    return this.http
      .request<GameSnapshot>(body ? 'POST' : 'GET', base + (body ? '/' + action : '/game'), {
        body,
        headers,
      })
      .pipe(timeout(10000));
  }
}
