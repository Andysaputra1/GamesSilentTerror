import { DOCUMENT } from '@angular/common';
import { Injectable, inject, signal } from '@angular/core';
import { NavigationEnd, NavigationError, Router } from '@angular/router';
import { filter, first } from 'rxjs';
import { AssetPreloader, MAIN_CRITICAL_IMAGES } from './asset-preloader';

// Batas tunggu layar loading: jaringan lambat/offline tetap masuk ke aplikasi setelah ini.
export const BOOT_LOADER_MAX_WAIT_MS = 4000;
// Waktu tampil minimum agar layar tidak berkedip pada cache hangat.
const MIN_VISIBLE_MS = 450;
const FONTS = ['700 1em Fraunces', '400 1em "Patrick Hand"'];
const FALLBACK_IMAGES = ['/assets/backgrounds/backwood.jpg'];

// LAYAR LOADING AWAL: markup #boot-loader ada di index.html (di luar app-root) sehingga tampil
// pada paint pertama, baik HTML prerender maupun build statis, tanpa memengaruhi hidrasi.
// Service ini hanya berjalan di browser: tunggu halaman pertama selesai dinavigasi, font, dan
// kerangka gambar halaman tersebut (Main: latar, binder, tombol), lalu pudarkan dan hapus elemennya.
// Skin dan kartu dipreload Main sendiri setelah render, jadi tidak menahan layar loading.
@Injectable({ providedIn: 'root' })
export class BootLoader {
  private readonly document = inject(DOCUMENT);
  private readonly router = inject(Router);
  private readonly preloader = inject(AssetPreloader);
  // true begitu layar loading mulai memudar (atau tidak ada); pop-up lain menunggu sinyal ini.
  readonly done = signal(false);

  start(): void {
    const loader = this.document.getElementById('boot-loader');
    if (!loader) {
      this.done.set(true);
      return;
    }
    const startedAt = Date.now();
    const ready = this.firstPage().then((url) =>
      Promise.all([
        this.preloader.preload(url.startsWith('/main') ? MAIN_CRITICAL_IMAGES : FALLBACK_IMAGES),
        ...FONTS.map((font) => this.document.fonts?.load(font).catch(() => undefined)),
      ]),
    );
    const cap = new Promise((resolve) => setTimeout(resolve, BOOT_LOADER_MAX_WAIT_MS));
    void Promise.race([ready, cap]).then(() => {
      setTimeout(() => this.hide(loader), Math.max(0, MIN_VISIBLE_MS - (Date.now() - startedAt)));
    });
  }

  // URL halaman pertama setelah redirect/guard selesai (pembatalan karena redirect diabaikan).
  private firstPage(): Promise<string> {
    if (this.router.navigated) return Promise.resolve(this.router.url);
    return new Promise((resolve) =>
      this.router.events
        .pipe(
          filter((event) => event instanceof NavigationEnd || event instanceof NavigationError),
          first(),
        )
        .subscribe(() => resolve(this.router.url)),
    );
  }

  private hide(loader: HTMLElement): void {
    this.done.set(true);
    loader.classList.add('boot-loader--done');
    loader.setAttribute('aria-hidden', 'true');
    const remove = () => loader.remove();
    loader.addEventListener('transitionend', remove, { once: true });
    // Cadangan bila transisi tidak berjalan (prefers-reduced-motion atau tab di latar).
    setTimeout(remove, 800);
  }
}
