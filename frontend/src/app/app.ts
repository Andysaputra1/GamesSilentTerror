import { Component, OnInit, OnDestroy, Inject, PLATFORM_ID } from '@angular/core';
import { RouterOutlet, Router } from '@angular/router';
import { isPlatformBrowser } from '@angular/common';
import { catchError, exhaustMap, filter, fromEvent, merge, of, Subscription, timer } from 'rxjs';
import { ActiveMatchService } from './core/active-match.service';
import { BootLoader } from './core/boot-loader';
import { FullscreenInvite } from './core/fullscreen-invite';
import { SessionService } from './core/session.service';
import { forgetRoom, STORAGE, titipPemberitahuan } from './core/storage';

// DECORATOR: hubungkan komponen dengan selector HTML, template, dan fitur router.
@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet, FullscreenInvite],
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
    private readonly bootLoader: BootLoader,
    @Inject(PLATFORM_ID) private readonly platform: object,
  ) {}

  // Tab lain logout: sesi tab ini ikut dibersihkan. Tab lain login dengan akun lain: setiap request tab ini sudah
  // memakai token baru, padahal room dan layarnya milik akun lama. Room dilupakan, lalu Main dimuat ulang dengan akun
  // baru beserta pesannya.
  // Alur: 1 token dihapus? -> 2.1.1 bersihkan sesi -> 2.1.2 ke /login
  //                        \> 2.2.1 token berganti -> 2.2.2 lupakan room + titip pesan -> 2.2.3 muat ulang /main
  private ikutiSesiTabLain(): void {
    if (!localStorage.getItem(STORAGE.token)) {
      this.session.clearLocalSession();
      void this.router.navigateByUrl('/login', { replaceUrl: true });
      return;
    }
    forgetRoom();
    titipPemberitahuan('Akun berganti di tab lain. Halaman ini dimuat ulang dengan akun tersebut.');
    location.assign('/main');
  }

  // Host bisa memulai ketika anggota masih di main/lobby. Cek juga saat kembali ke tab.
  ngOnInit(): void {
    if (!isPlatformBrowser(this.platform)) return;
    // Layar loading index.html hilang setelah halaman pertama, font, dan gambarnya siap.
    this.bootLoader.start();
    this.storageMonitor = fromEvent<StorageEvent>(window, 'storage')
      .pipe(
        filter(
          (event) =>
            event.storageArea === localStorage &&
            (event.key === STORAGE.token || event.key === null) &&
            (!localStorage.getItem(STORAGE.token) ||
              (!!event.oldValue && event.newValue !== event.oldValue)),
        ),
      )
      .subscribe(() => this.ikutiSesiTabLain());
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
