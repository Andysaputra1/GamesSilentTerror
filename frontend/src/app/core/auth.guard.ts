import { isPlatformBrowser } from '@angular/common';
import { inject, PLATFORM_ID } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

// CONSTANT: nama penyimpanan token dan waktu kedaluwarsa pada browser.
const TOKEN_KEY = 'shadow_heist_access_token';
const EXPIRY_KEY = 'shadow_heist_access_token_expires_at';

// FUNCTION GUARD (arrow): izinkan navigasi jika token lokal belum kedaluwarsa;
// jika tidak, bersihkan sesi lokal dan arahkan ke login. Saat SSR, storage tidak dibaca.
// Ini pemeriksaan navigasi saja, bukan pembuktian bahwa token diterima backend.
export const authGuard: CanActivateFn = () => {
  const platformId = inject(PLATFORM_ID);
  if (!isPlatformBrowser(platformId)) return true;

  const token = localStorage.getItem(TOKEN_KEY);
  const expiresAt = localStorage.getItem(EXPIRY_KEY);
  const isExpired =
    !expiresAt || Number.isNaN(Date.parse(expiresAt)) || Date.parse(expiresAt) <= Date.now();
  if (token && !isExpired) return true;

  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(EXPIRY_KEY);
  localStorage.removeItem('shadow_heist_user');
  sessionStorage.removeItem('shadow_heist_game_entry');
  return inject(Router).createUrlTree(['/login']);
};
