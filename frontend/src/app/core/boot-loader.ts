import { DOCUMENT } from '@angular/common';
import { Injectable, inject, signal } from '@angular/core';
import { NavigationEnd, NavigationError, Router } from '@angular/router';
import { filter, first } from 'rxjs';
import { AssetPreloader, MAIN_CRITICAL_IMAGES } from './asset-preloader';

// Batas tunggu layar loading: jaringan lambat/offline tetap masuk ke aplikasi setelah ini.
export const BOOT_LOADER_MAX_WAIT_MS = 4000;
// Batas tunggu layar loading sesudah login: lebih longgar karena menunggu semua gambar yang tampil di Main.
export const LOGIN_LOADER_MAX_WAIT_MS = 8000;
// Satu sapuan kaca pembesar melewati keenam karakter (boot-sweep di styles.css). Layar loading baru
// ditutup setelah sapuan itu selesai, walau halaman sudah siap lebih dulu.
export const BOOT_LOADER_SCAN_MS = 2400;
// Gerak minimal (tanpa animasi): cukup tampil sebentar agar layar tidak berkedip pada cache hangat.
const MIN_VISIBLE_MS = 450;
const FONTS = ['700 1em Fraunces', '400 1em "Patrick Hand"'];
const FALLBACK_IMAGES = ['/assets/backgrounds/backwood.jpg'];

// LAYAR LOADING AWAL: markup #boot-loader ada di index.html (di luar app-root) sehingga tampil
// pada paint pertama, baik HTML prerender maupun build statis, tanpa memengaruhi hidrasi.
// Service ini hanya berjalan di browser: tunggu halaman pertama selesai dinavigasi, font, dan
// kerangka gambar halaman tersebut (Main: latar, binder, tombol), lalu pudarkan dan hapus elemennya.
// Skin dan kartu dipreload Main sendiri setelah render, jadi tidak menahan layar loading.
// Sesudah login, layar yang sama dipasang lagi sampai Main selesai dirender (bukaSesudahLogin).
@Injectable({ providedIn: 'root' })
export class BootLoader {
  private readonly document = inject(DOCUMENT);
  private readonly router = inject(Router);
  private readonly preloader = inject(AssetPreloader);
  // true begitu layar loading mulai memudar (atau tidak ada); pop-up lain menunggu sinyal ini.
  readonly done = signal(false);
  // Elemen layar loading tetap disimpan sesudah dilepas dari halaman, supaya bisa dipasang lagi saat login.
  private loader?: HTMLElement;

  start(): void {
    const loader = this.document.getElementById('boot-loader');
    if (!loader) {
      this.done.set(true);
      return;
    }
    this.loader = loader;
    const waktuMulai = Date.now();
    const halamanSiap = this.tungguHalamanPertama().then((url) =>
      Promise.all([
        this.preloader.preload(url.startsWith('/main') ? MAIN_CRITICAL_IMAGES : FALLBACK_IMAGES),
        ...FONTS.map((font) => this.document.fonts?.load(font).catch(() => undefined)),
      ]),
    );
    const batasTunggu = new Promise((resolve) => setTimeout(resolve, BOOT_LOADER_MAX_WAIT_MS));
    const gerakDikurangi = this.document.defaultView?.matchMedia?.(
      '(prefers-reduced-motion: reduce)',
    ).matches;
    const lamaTampilMinimal = gerakDikurangi ? MIN_VISIBLE_MS : BOOT_LOADER_SCAN_MS;
    void Promise.race([halamanSiap, batasTunggu]).then(() => {
      setTimeout(
        () => this.pudarkanLoader(loader),
        Math.max(0, lamaTampilMinimal - (Date.now() - waktuMulai)),
      );
    });
  }

  // Satu frame browser; tanpa requestAnimationFrame (mis. jsdom) memakai timer setara satu frame.
  private tungguFrame(): Promise<void> {
    const jendela = this.document.defaultView;
    return new Promise((resolve) =>
      jendela?.requestAnimationFrame
        ? jendela.requestAnimationFrame(() => resolve())
        : setTimeout(resolve, 16),
    );
  }

  // LAYAR LOADING SESUDAH LOGIN: layar loading yang sama dipasang lagi, halaman tujuan dibuka di belakangnya,
  // lalu layar ditutup setelah tampilan halaman itu selesai dirender: gambar latar dan tombol, semua <img> di
  // aplikasi (kartu role, skin, props, logo), dan font siap, lalu tergambar di layar. Batas tunggu tetap
  // berlaku agar jaringan lambat tidak menahan pemain. Tanpa elemen layar loading, langsung navigasi.
  // Alur: 1 pasang lagi layar loading -> 2 navigasi -> 3 dua frame agar Angular merender halaman baru -> 4 tunggu
  //       gambar dan font -> 5 dua frame lagi (atau batas waktu), tampil minimal -> 6 pudarkan, juga bila gagal
  async bukaSesudahLogin(url: string): Promise<boolean> {
    const loader = this.loader;
    if (!loader) return this.router.navigateByUrl(url);

    // 1 dilepas lalu dipasang ulang supaya langsung tampil penuh tanpa transisi pudar
    loader.remove();
    loader.classList.remove('boot-loader--done');
    loader.removeAttribute('aria-hidden');
    this.document.body.prepend(loader);
    this.done.set(false);
    const waktuMulai = Date.now();
    let berhasil = false;
    try {
      // 2 navigasi (guard bisa mengalihkan, mis. ke /game)
      berhasil = await this.router.navigateByUrl(url);
      if (!berhasil) return false;

      const renderSelesai = (async () => {
        // 3 render halaman baru
        await this.tungguFrame();
        await this.tungguFrame();

        // 4 gambar dan font
        const gambarTampil = Array.from(
          this.document.querySelectorAll<HTMLImageElement>('app-root img'),
        );
        await Promise.all([
          this.preloader.preload(
            this.router.url.startsWith('/main') ? MAIN_CRITICAL_IMAGES : FALLBACK_IMAGES,
          ),
          ...gambarTampil.map((gambar) =>
            typeof gambar.decode === 'function'
              ? gambar.decode().catch(() => undefined)
              : undefined,
          ),
          this.document.fonts?.ready,
        ]);

        // 5 hasilnya tergambar
        await this.tungguFrame();
        await this.tungguFrame();
      })();
      const batasTunggu = new Promise((resolve) => setTimeout(resolve, LOGIN_LOADER_MAX_WAIT_MS));
      await Promise.race([renderSelesai, batasTunggu]);
      const sisaTampil = MIN_VISIBLE_MS - (Date.now() - waktuMulai);
      if (sisaTampil > 0) await new Promise((resolve) => setTimeout(resolve, sisaTampil));
      return true;
    } finally {
      // 6 pudarkan
      this.pudarkanLoader(loader);
    }
  }

  // URL halaman pertama setelah redirect/guard selesai (pembatalan karena redirect diabaikan).
  private tungguHalamanPertama(): Promise<string> {
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

  private pudarkanLoader(loader: HTMLElement): void {
    this.done.set(true);
    loader.classList.add('boot-loader--done');
    loader.setAttribute('aria-hidden', 'true');
    // Hanya dilepas bila masih dalam keadaan pudar: layar bisa sudah dipasang lagi saat login.
    const hapusLoader = () => {
      if (loader.classList.contains('boot-loader--done')) loader.remove();
    };
    loader.addEventListener('transitionend', hapusLoader, { once: true });
    // Cadangan bila transisi tidak berjalan (prefers-reduced-motion atau tab di latar).
    setTimeout(hapusLoader, 800);
  }
}
