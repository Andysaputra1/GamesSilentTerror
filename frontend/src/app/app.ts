import { Component, OnInit, OnDestroy, Inject, PLATFORM_ID } from '@angular/core';
import { RouterOutlet, Router } from '@angular/router';
import { isPlatformBrowser } from '@angular/common';
import { catchError, exhaustMap, filter, fromEvent, merge, of, Subscription, timer } from 'rxjs';
import { ActiveMatchService } from './core/active-match.service';
import { SessionService } from './core/session.service';
import { FullscreenPrompt } from './core/fullscreen-prompt';

// DECORATOR: hubungkan komponen dengan selector HTML, template, dan fitur router.
@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet, FullscreenPrompt],
  templateUrl: './app.html',
})
// CLASS KOMPONEN: wadah utama halaman; router-outlet di app.html menampilkan route aktif.
export class App implements OnInit, OnDestroy {
  private monitor?: Subscription;
  private storageMonitor?: Subscription;
  // Sediakan layanan pemulihan pertandingan, sesi, router, dan identitas platform.
  constructor(
    private readonly matches: ActiveMatchService,
    private readonly router: Router,
    private readonly session: SessionService,
    @Inject(PLATFORM_ID) private readonly platform: object,
  ) {}

  // Host bisa memulai ketika anggota masih di main/lobby. Cek juga saat kembali ke tab.
  ngOnInit(): void {
    if (!isPlatformBrowser(this.platform)) return;
    this.storageMonitor = fromEvent<StorageEvent>(window, 'storage')
      .pipe(
        filter(
          (event) =>
            event.storageArea === localStorage &&
            (event.key === 'shadow_heist_access_token' || event.key === null) &&
            !localStorage.getItem('shadow_heist_access_token'),
        ),
      )
      .subscribe(() => {
        this.session.clearLocalSession();
        void this.router.navigateByUrl('/login', { replaceUrl: true });
      });
    this.monitor = merge(
      timer(0, 3000),
      fromEvent(window, 'focus'),
      fromEvent(document, 'visibilitychange'),
    )
      .pipe(
        filter(() => !document.hidden && this.router.url.split('?')[0] !== '/game'),
        exhaustMap(() => this.matches.lookup().pipe(catchError(() => of(null)))),
      )
      .subscribe((active) => {
        if (active) {
          this.matches.remember(active);
          void this.router.navigateByUrl('/game', { replaceUrl: true });
        }
      });
  }

  // Hentikan pemantauan pertandingan dan sesi antar-tab saat aplikasi dilepas.
  ngOnDestroy(): void {
    this.monitor?.unsubscribe();
    this.storageMonitor?.unsubscribe();
  }
}
