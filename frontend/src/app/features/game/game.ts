import { isPlatformBrowser } from '@angular/common';
import { Component, Inject, NgZone, OnDestroy, OnInit, PLATFORM_ID } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { io, Socket } from 'socket.io-client';

interface ChatMessage { sender: string; message: string; }
interface Role { name: string; icon: string; objective: string; action: string; }

@Component({ selector: 'app-game', standalone: true, imports: [FormsModule], templateUrl: './game.html', styleUrl: './game.css' })
export class Game implements OnInit, OnDestroy {
  readonly botName = 'NOX';
  readonly roles: Role[] = [
    { name: 'CIVILIAN', icon: '◉', objective: 'Bertahan hidup dan temukan Hitman.', action: 'OBSERVE' },
    { name: 'DETECTIVE', icon: '⌕', objective: 'Baca pola dan lindungi tim.', action: 'INVESTIGATE' },
    { name: 'SPY', icon: '◈', objective: 'Kumpulkan petunjuk tanpa terdeteksi.', action: 'LISTEN' },
  ];
  playerName = 'Operative'; draftMessage = ''; isGagged = false; isShuffling = true; isRoleRevealed = false; gameReady = false; isChatConnected = false;
  assignedRole: Role = this.roles[0];
  messages: ChatMessage[] = [{ sender: 'SYSTEM', message: 'Koneksi aman. NOX telah memasuki ruangan.' }];
  private socket?: Socket; private shuffleInterval?: ReturnType<typeof setInterval>; private revealTimeout?: ReturnType<typeof setTimeout>; private readyTimeout?: ReturnType<typeof setTimeout>; private accessToken = '';

  constructor(@Inject(PLATFORM_ID) private readonly platformId: object, private readonly zone: NgZone, private readonly router: Router) {}
  ngOnInit(): void {
    if (!isPlatformBrowser(this.platformId)) return;
    const storedUser = localStorage.getItem('shadow_heist_user'); this.accessToken = localStorage.getItem('shadow_heist_access_token') ?? '';
    try { const user = storedUser ? JSON.parse(storedUser) as { username?: string } : null; this.playerName = user?.username || this.playerName; }
    catch { this.addSystemMessage('Data login tidak dapat dibaca. Silakan masuk kembali.'); }
    this.startRoleShuffle();
    if (!this.accessToken) { this.addSystemMessage('Sesi tidak ditemukan. Kembali ke login untuk menyambungkan chat.'); return; }
    const backendUrl = `${window.location.protocol}//${window.location.hostname}:8000`;
    this.socket = io(backendUrl, { transports: ['websocket', 'polling'], auth: { token: this.accessToken } });
    this.socket.on('connect', () => this.zone.run(() => { this.isChatConnected = true; this.socket?.emit('register_player', { username: this.playerName }); }));
    this.socket.on('receive_chat', (chat: ChatMessage) => this.zone.run(() => this.receiveChat(chat)));
    this.socket.on('system_alert', (data: { msg: string }) => this.zone.run(() => this.addSystemMessage(data.msg)));
    this.socket.on('server_ready', (data: { message: string }) => this.zone.run(() => this.addSystemMessage(data.message)));
    this.socket.on('disconnect', () => this.zone.run(() => this.isChatConnected = false));
    this.socket.on('connect_error', () => this.zone.run(() => this.expireSession()));
    this.socket.on('status_changed', (data: { status: string }) => { if (data.status === 'gagged' || data.status === 'hostage') this.zone.run(() => { this.isGagged = true; this.addSystemMessage('Suara Anda tiba-tiba hilang.'); }); });
  }
  ngOnDestroy(): void { this.socket?.disconnect(); if (this.shuffleInterval) clearInterval(this.shuffleInterval); if (this.revealTimeout) clearTimeout(this.revealTimeout); if (this.readyTimeout) clearTimeout(this.readyTimeout); }
  get roleClass(): string { return this.assignedRole.name.toLowerCase(); }
  sendMessage(): void {
    const message = this.draftMessage.trim();
    if (!message || this.isGagged || !this.gameReady) return;
    if (!this.socket?.connected || !this.isChatConnected) {
      this.addSystemMessage('Chat belum tersambung. Silakan tunggu koneksi aman atau masuk ulang.');
      return;
    }
    this.messages.push({ sender: this.playerName, message });
    this.socket.emit('send_chat', { username: this.playerName, message });
    this.draftMessage = '';
  }
  onAction(): void { this.addSystemMessage(`${this.assignedRole.action}: ${this.assignedRole.objective}`); }
  private startRoleShuffle(): void { this.assignedRole = this.randomRole(); this.shuffleInterval = setInterval(() => this.assignedRole = this.randomRole(), 130); this.revealTimeout = setTimeout(() => { if (this.shuffleInterval) clearInterval(this.shuffleInterval); this.assignedRole = this.randomRole(); this.isShuffling = false; this.isRoleRevealed = true; }, 1600); this.readyTimeout = setTimeout(() => { this.gameReady = true; }, 3200); }
  private randomRole(): Role { return this.roles[Math.floor(Math.random() * this.roles.length)]; }
  private receiveChat(chat: ChatMessage): void {
    const previous = this.messages.at(-1);
    if (chat.sender === this.playerName && previous?.sender === chat.sender && previous.message === chat.message) return;
    this.messages.push(chat);
  }
  private expireSession(): void {
    this.isChatConnected = false;
    localStorage.removeItem('shadow_heist_access_token');
    localStorage.removeItem('shadow_heist_access_token_expires_at');
    localStorage.removeItem('shadow_heist_user');
    sessionStorage.removeItem('shadow_heist_game_entry');
    this.addSystemMessage('Sesi login berakhir. Mengarahkan ke halaman login…');
    setTimeout(() => void this.router.navigateByUrl('/login'), 900);
  }
  private addSystemMessage(message: string): void { this.messages.push({ sender: 'SYSTEM', message }); }
}
