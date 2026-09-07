import { isPlatformBrowser } from '@angular/common';
import { Component, Inject, OnInit, PLATFORM_ID } from '@angular/core';
import { RouterLink } from '@angular/router';

@Component({
  selector: 'app-main-page',
  imports: [RouterLink],
  templateUrl: './main-page.html',
  styleUrl: './main-page.css',
})
export class MainPage implements OnInit {
  username: string = 'guest';

  constructor(@Inject(PLATFORM_ID) private readonly platformId: object) {}

  ngOnInit(): void {
    if (!isPlatformBrowser(this.platformId)) return;
    try {
      const storedUser = localStorage.getItem('shadow_heist_user');
      const user = storedUser ? JSON.parse(storedUser) as { username?: string } : null;
      this.username = user?.username || this.username;
    } catch {
      // A malformed local session must not break the main page.
    }
  }
}
