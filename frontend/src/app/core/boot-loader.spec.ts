import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AssetPreloader, MAIN_PAGE_IMAGES } from './asset-preloader';
import { BOOT_LOADER_MAX_WAIT_MS, BootLoader } from './boot-loader';

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
        provideRouter([{ path: 'main', component: Blank }]),
        { provide: AssetPreloader, useValue: { preload } },
      ],
    });
  });

  afterEach(() => {
    loader.remove();
    vi.useRealTimers();
  });

  // Main: tunggu halaman pertama dan gambarnya, lalu pudarkan dan hapus layar loading.
  it('waits for the first page and its images before fading out', async () => {
    TestBed.inject(BootLoader).start();
    expect(preload).not.toHaveBeenCalled();
    await TestBed.inject(Router).navigateByUrl('/main');
    await vi.advanceTimersByTimeAsync(500);
    expect(preload).toHaveBeenCalledWith(MAIN_PAGE_IMAGES);
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
