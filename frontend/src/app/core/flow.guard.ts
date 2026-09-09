import { isPlatformBrowser } from '@angular/common';
import { inject, PLATFORM_ID } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

// CONSTANT: kunci storage untuk sesi login dan izin masuk game dari lobby.
const TOKEN_KEY = 'shadow_heist_access_token';
const EXPIRY_KEY = 'shadow_heist_access_token_expires_at';
const GAME_ENTRY_KEY = 'shadow_heist_game_entry';

// FUNCTION HELPER: periksa keberadaan token dan masa berlaku lokal, bukan validasi API.
function hasValidSession(): boolean {
  const token = localStorage.getItem(TOKEN_KEY);
  const expiresAt = localStorage.getItem(EXPIRY_KEY);
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
  if (sessionStorage.getItem(GAME_ENTRY_KEY) === 'allowed') return true;
  return inject(Router).createUrlTree(['/main']);
};

// CONSTANT EKSPOR: kunci yang sama dipakai Lobby ketika memberi tanda masuk game.
export const gameEntryStorageKey = GAME_ENTRY_KEY;
