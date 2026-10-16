import { afterEach, describe, expect, it, vi } from 'vitest';

import { AssetPreloader, MAIN_PAGE_IMAGES, SKIN_IDS, skinImageUrl } from './asset-preloader';

// Image palsu: jsdom tidak mengunduh gambar, jadi decode() dikendalikan dari tes.
class FakeImage {
  static created: FakeImage[] = [];
  decoding = '';
  src = '';
  constructor() {
    FakeImage.created.push(this);
  }
  decode(): Promise<void> {
    return this.src.includes('broken') ? Promise.reject(new Error('gagal')) : Promise.resolve();
  }
}

describe('AssetPreloader', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    FakeImage.created = [];
  });

  // CACHE: setiap URL diunduh sekali per tab; gambar rusak tidak menahan halaman.
  it('downloads each image once and settles even when one fails', async () => {
    vi.stubGlobal('Image', FakeImage);
    const preloader = new AssetPreloader();
    await preloader.preload(['/a.png', '/broken.png']);
    await preloader.preload(['/a.png']);
    expect(FakeImage.created.map((image) => image.src)).toEqual(['/a.png', '/broken.png']);
    expect(FakeImage.created.every((image) => image.decoding === 'async')).toBe(true);
  });

  // DAFTAR MAIN: semua skin yang bisa dipilih ikut dipanaskan agar ganti skin instan.
  it('includes every selectable skin in the main page list', () => {
    for (const id of SKIN_IDS) expect(MAIN_PAGE_IMAGES).toContain(skinImageUrl(id));
  });
});
