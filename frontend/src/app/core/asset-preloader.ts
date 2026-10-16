import { Injectable } from '@angular/core';

// Skin karakter yang bisa dipilih di Main; urutannya dipakai tombol gantungan.
export const SKIN_IDS = ['sadie', 'kiera', 'eloise', 'jenny', 'arthur', 'dexter'] as const;

export function skinImageUrl(id: string): string {
  return `/assets/characters/skin_${id}.png`;
}

// Kerangka halaman utama (latar, binder, tombol). Hanya ini yang ditunggu layar loading;
// kartu, props, dan skin menyusul di latar belakang agar loading tidak menunggu ±3,8 MB.
export const MAIN_CRITICAL_IMAGES: readonly string[] = [
  '/assets/backgrounds/backwood.jpg',
  '/assets/backgrounds/binder-cropped.png',
  '/assets/buttons/btn-wood.png',
  '/assets/buttons/btn-leather.png',
];

// Semua gambar halaman utama, termasuk skin untuk tombol gantungan; dipreload Main setelah render.
export const MAIN_PAGE_IMAGES: readonly string[] = [
  ...MAIN_CRITICAL_IMAGES,
  '/assets/decorations/icons/hanger.png',
  ...['hitman', 'stalker', 'spy', 'civilian'].map((role) => `/assets/cards/card_${role}.png`),
  ...['hitman-pistol', 'spy-shades', 'stalker-nerd-eyes'].map(
    (prop) => `/assets/props/${prop}.png`,
  ),
  ...SKIN_IDS.map(skinImageUrl),
];

// PRELOADER: unduh dan decode gambar sekali per sesi tab, hanya di browser.
// Elemen Image disimpan agar browser tetap memegang bitmap hasil decode di memory cache,
// sehingga <img> dengan URL yang sama (mis. saat ganti skin) tampil tanpa request/decode ulang.
@Injectable({ providedIn: 'root' })
export class AssetPreloader {
  private readonly loading = new Map<string, Promise<void>>();
  private readonly images: HTMLImageElement[] = [];

  // Selesai ketika semua gambar siap atau gagal; gambar rusak/offline tidak menahan halaman.
  preload(urls: readonly string[]): Promise<void> {
    if (typeof Image === 'undefined') return Promise.resolve();
    return Promise.all(urls.map((url) => this.load(url))).then(() => undefined);
  }

  private load(url: string): Promise<void> {
    let pending = this.loading.get(url);
    if (!pending) {
      const image = new Image();
      image.decoding = 'async';
      image.src = url;
      this.images.push(image);
      // decode() menunggu unduh + decode; fallback onload untuk browser/jsdom tanpa decode().
      pending =
        typeof image.decode === 'function'
          ? image.decode().catch(() => undefined)
          : new Promise<void>((resolve) => {
              image.onload = image.onerror = () => resolve();
            });
      this.loading.set(url, pending);
    }
    return pending;
  }
}
