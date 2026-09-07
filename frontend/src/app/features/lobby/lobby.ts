import { isPlatformBrowser } from '@angular/common';
import { Component, Inject, OnInit, PLATFORM_ID } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { gameEntryStorageKey } from '../../core/flow.guard';

@Component({
  selector: 'app-lobby',
  imports: [RouterLink],
  templateUrl: './lobby.html',
  styleUrl: './lobby.css',
})
export class Lobby implements OnInit {
  username = 'Operative';

  constructor(@Inject(PLATFORM_ID) private readonly platformId: object, private readonly router: Router) {}

  ngOnInit(): void {
    if (!isPlatformBrowser(this.platformId)) return;
    try {
      const rawUser = localStorage.getItem('shadow_heist_user');
      const user = rawUser ? JSON.parse(rawUser) as { username?: string } : null;
      this.username = user?.username || this.username;
    } catch {
      // Continue with a neutral name if local storage is corrupted.
    }
  }

  enterGame(): void {
    if (!isPlatformBrowser(this.platformId)) return;
    sessionStorage.setItem(gameEntryStorageKey, 'allowed');
    void this.router.navigateByUrl('/game');
  }
}
