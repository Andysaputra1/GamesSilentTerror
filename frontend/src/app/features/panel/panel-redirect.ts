import { Component, OnInit, PLATFORM_ID, inject } from '@angular/core';
import { isPlatformBrowser } from '@angular/common';
import { backendUrl } from '../../core/backend-url';

@Component({
  selector: 'app-panel-redirect',
  standalone: true,
  template: `
    <main class="panel-redirect" aria-live="polite">
      <section>
        <p>CONTROL ROOM</p>
        <h1>Panel administrator</h1>
        <span>{{ message }}</span>
      </section>
    </main>
  `,
  styles: `
    :host { display: block; }
    .panel-redirect {
      display: grid;
      min-height: 100vh;
      min-height: 100dvh;
      place-items: center;
      padding: 24px;
      color: #dce4ef;
      background: #0c1017;
      font-family: Inter, Segoe UI, Arial, sans-serif;
      text-align: center;
    }
    section { max-width: 30rem; }
    p { margin: 0 0 10px; color: #baf578; font-size: 11px; font-weight: 700; letter-spacing: .18em; }
    h1 { margin: 0 0 12px; font-size: clamp(28px, 5vw, 46px); letter-spacing: -.04em; }
    span { color: #9aacbf; line-height: 1.6; }
  `,
})
export class PanelRedirect implements OnInit {
  private readonly platform = inject(PLATFORM_ID);
  message = 'Membuka panel administrator...';
  // Arahkan browser ke panel yang disajikan backend; lewati proses render server.
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
