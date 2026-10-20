import { isPlatformBrowser } from '@angular/common';
import { inject, PLATFORM_ID } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { STORAGE } from './storage';

// FUNCTION HELPER: periksa keberadaan token dan masa berlaku lokal, bukan validasi API.
export function hasValidSession(): boolean {
  const token = localStorage.getItem(STORAGE.token);
  const expiresAt = localStorage.getItem(STORAGE.tokenExpiresAt);
  return Boolean(
    token &&
    expiresAt &&
    !Number.isNaN(Date.parse(expiresAt)) &&
    Date.parse(expiresAt) > Date.now(),
  );
}

// FUNCTION GUARD: pengguna dengan sesi lokal yang belum kedaluwarsa diarahkan ke main.
export const loginRedirectGuard: CanActivateFn = () => {
  const platformId = inject(PLATFORM_ID);
  if (!isPlatformBrowser(platformId) || !hasValidSession()) return true;
  return inject(Router).createUrlTree(['/main']);
};

// FUNCTION GUARD: periksa tanda masuk dari lobby pada tab ini sebelum membuka game.
export const gameEntryGuard: CanActivateFn = () => {
  const platformId = inject(PLATFORM_ID);
  if (!isPlatformBrowser(platformId)) return true;
  if (sessionStorage.getItem(STORAGE.gameEntry) === 'allowed') return true;
  return inject(Router).createUrlTree(['/main']);
};
