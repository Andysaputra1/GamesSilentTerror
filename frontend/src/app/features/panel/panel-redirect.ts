import { Component, OnInit, PLATFORM_ID, inject } from '@angular/core';
import { isPlatformBrowser } from '@angular/common';
import { backendUrl } from '../../core/backend-url';

@Component({
  selector: 'app-panel-redirect',
  standalone: true,
  template: '<main style="padding:3rem"><h1>Panel administrator</h1><p>{{ message }}</p></main>',
})
export class PanelRedirect implements OnInit {
  private readonly platform = inject(PLATFORM_ID);
  message = 'Membuka panel administrator...';
  ngOnInit(): void {
    if (!isPlatformBrowser(this.platform)) return;
    const target = new URL(backendUrl() + '/panel', window.location.origin);
    if (target.origin === window.location.origin) {
      this.message =
        'Backend belum terhubung. Atur BACKEND_URL pada deployment frontend untuk membuka panel.';
      return;
    }
    window.location.replace(target.href);
  }
}
