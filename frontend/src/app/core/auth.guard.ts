import { isPlatformBrowser } from '@angular/common';
import { inject, PLATFORM_ID } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { hasValidSession } from './flow.guard';
import { STORAGE } from './storage';

// FUNCTION GUARD (arrow): izinkan navigasi jika token lokal belum kedaluwarsa;
// jika tidak, bersihkan sesi lokal dan arahkan ke login. Saat SSR, storage tidak dibaca.
// Ini pemeriksaan navigasi saja, bukan pembuktian bahwa token diterima backend.
export const authGuard: CanActivateFn = () => {
  const platformId = inject(PLATFORM_ID);
  if (!isPlatformBrowser(platformId)) return true;

  if (hasValidSession()) return true;

  localStorage.removeItem(STORAGE.token);
  localStorage.removeItem(STORAGE.tokenExpiresAt);
  localStorage.removeItem(STORAGE.user);
  sessionStorage.removeItem(STORAGE.gameEntry);
  return inject(Router).createUrlTree(['/login']);
};
