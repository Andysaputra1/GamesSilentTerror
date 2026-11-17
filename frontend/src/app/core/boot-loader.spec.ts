import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AssetPreloader, MAIN_CRITICAL_IMAGES } from './asset-preloader';
import {
  BOOT_LOADER_MAX_WAIT_MS,
  BOOT_LOADER_SCAN_MS,
  BootLoader,
  LOGIN_LOADER_MAX_WAIT_MS,
} from './boot-loader';

@Component({ template: '' })
class Blank {}

describe('BootLoader', () => {
  let preload: ReturnType<typeof vi.fn>;
  let loader: HTMLElement;

  beforeEach(() => {
    vi.useFakeTimers();
    loader = document.createElement('div');
    loader.id = 'boot-loader';
    document.body.append(loader);
    preload = vi.fn(() => Promise.resolve());
    TestBed.configureTestingModule({
      providers: [
        provideRouter([
          { path: 'login', component: Blank },
          { path: 'main', component: Blank },
        ]),
        { provide: AssetPreloader, useValue: { preload } },
      ],
    });
  });

  afterEach(() => {
    loader.remove();
    document.querySelector('app-root')?.remove();
    vi.useRealTimers();
  });

  // Tampilan awal di /login sampai layar loading pertama dilepas dari halaman.
  async function selesaikanLoadingAwal(): Promise<BootLoader> {
    const bootLoader = TestBed.inject(BootLoader);
    bootLoader.start();
    await TestBed.inject(Router).navigateByUrl('/login');
    await vi.advanceTimersByTimeAsync(BOOT_LOADER_SCAN_MS + 800);
    expect(loader.isConnected).toBe(false);
    return bootLoader;
  }

  // Sesudah login: layar loading tampil lagi dan baru pudar setelah semua <img> Main selesai di-decode.
  it('shows the loader again after login until every image on main is decoded', async () => {
    const bootLoader = await selesaikanLoadingAwal();
    const appRoot = document.createElement('app-root');
    const gambar = document.createElement('img');
    let gambarSiap!: () => void;
    gambar.decode = () => new Promise<void>((resolve) => (gambarSiap = resolve));
    appRoot.append(gambar);
    document.body.append(appRoot);

    const hasil = bootLoader.bukaSesudahLogin('/main');
    expect(loader.isConnected).toBe(true);
    expect(loader.classList).not.toContain('boot-loader--done');
    expect(bootLoader.done()).toBe(false);
    await vi.advanceTimersByTimeAsync(2000);
    expect(TestBed.inject(Router).url).toBe('/main');
    expect(loader.classList).not.toContain('boot-loader--done');

    gambarSiap();
    await vi.advanceTimersByTimeAsync(100);
    expect(loader.classList).toContain('boot-loader--done');
    expect(bootLoader.done()).toBe(true);
    await expect(hasil).resolves.toBe(true);
    await vi.advanceTimersByTimeAsync(800);
    expect(loader.isConnected).toBe(false);
  });

  // Gambar macet sesudah login: layar loading tetap pudar setelah batas waktu.
  it('gives up waiting for main after the login time limit', async () => {
    const bootLoader = await selesaikanLoadingAwal();
    preload.mockReturnValue(new Promise(() => {}));
    void bootLoader.bukaSesudahLogin('/main');
    await vi.advanceTimersByTimeAsync(LOGIN_LOADER_MAX_WAIT_MS - 100);
    expect(loader.classList).not.toContain('boot-loader--done');
    await vi.advanceTimersByTimeAsync(200);
    expect(loader.classList).toContain('boot-loader--done');
  });

  // Main: tunggu halaman pertama dan gambarnya, lalu pudarkan dan hapus layar loading.
  it('waits for the first page and its images before fading out', async () => {
    TestBed.inject(BootLoader).start();
    expect(preload).not.toHaveBeenCalled();
    await TestBed.inject(Router).navigateByUrl('/main');
    await vi.advanceTimersByTimeAsync(500);
    expect(preload).toHaveBeenCalledWith(MAIN_CRITICAL_IMAGES);
    // Halaman sudah siap, tetapi layar loading menunggu kaca pembesar selesai menyisir semua karakter.
    expect(loader.classList).not.toContain('boot-loader--done');
    await vi.advanceTimersByTimeAsync(BOOT_LOADER_SCAN_MS - 500);
    expect(loader.classList).toContain('boot-loader--done');
    await vi.advanceTimersByTimeAsync(800);
    expect(loader.isConnected).toBe(false);
  });

  // Jaringan macet: layar loading tetap hilang setelah batas waktu.
  it('gives up waiting after the time limit', async () => {
    preload.mockReturnValue(new Promise(() => {}));
    TestBed.inject(BootLoader).start();
    await TestBed.inject(Router).navigateByUrl('/main');
    await vi.advanceTimersByTimeAsync(BOOT_LOADER_MAX_WAIT_MS - 100);
    expect(loader.classList).not.toContain('boot-loader--done');
    await vi.advanceTimersByTimeAsync(200);
    expect(loader.classList).toContain('boot-loader--done');
  });
});
