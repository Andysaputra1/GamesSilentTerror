import { Component, signal, OnInit, OnDestroy, Inject, PLATFORM_ID } from '@angular/core';
import { RouterOutlet, Router } from '@angular/router';
import { isPlatformBrowser } from '@angular/common';
import { catchError, exhaustMap, filter, fromEvent, merge, of, Subscription, timer } from 'rxjs';
import { ActiveMatchService } from './core/active-match.service';

// DECORATOR: hubungkan komponen dengan selector HTML, template, dan fitur router.
@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet],
  templateUrl: './app.html',
})
// CLASS KOMPONEN: wadah utama halaman; router-outlet di app.html menampilkan route aktif.
export class App implements OnInit, OnDestroy {
  private monitor?: Subscription;
  constructor(
    private readonly matches: ActiveMatchService,
    private readonly router: Router,
    @Inject(PLATFORM_ID) private readonly platform: object,
  ) {}

  // Host bisa memulai ketika anggota masih di main/lobby. Cek juga saat kembali ke tab.
  ngOnInit(): void {
    if (!isPlatformBrowser(this.platform)) return;
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

  ngOnDestroy(): void {
    this.monitor?.unsubscribe();
  }
  // PROPERTY SIGNAL: nilai reaktif; perubahan melalui API signal dapat memperbarui tampilan.
  protected readonly title = signal('frontend');
}
