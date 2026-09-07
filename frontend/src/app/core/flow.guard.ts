import { isPlatformBrowser } from '@angular/common';
import { inject, PLATFORM_ID } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

const TOKEN_KEY = 'shadow_heist_access_token';
const EXPIRY_KEY = 'shadow_heist_access_token_expires_at';
const GAME_ENTRY_KEY = 'shadow_heist_game_entry';

function hasValidSession(): boolean {
  const token = localStorage.getItem(TOKEN_KEY);
  const expiresAt = localStorage.getItem(EXPIRY_KEY);
  return Boolean(token && expiresAt && !Number.isNaN(Date.parse(expiresAt)) && Date.parse(expiresAt) > Date.now());
}

/** Logged-in players should land at Main Page instead of seeing Login again. */
export const loginRedirectGuard: CanActivateFn = () => {
  const platformId = inject(PLATFORM_ID);
  if (!isPlatformBrowser(platformId) || !hasValidSession()) return true;
  return inject(Router).createUrlTree(['/main']);
};

/** Game is intentionally entered from Lobby, never directly from a stale URL. */
export const gameEntryGuard: CanActivateFn = () => {
  const platformId = inject(PLATFORM_ID);
  if (!isPlatformBrowser(platformId)) return true;
  if (sessionStorage.getItem(GAME_ENTRY_KEY) === 'allowed') return true;
  return inject(Router).createUrlTree(['/main']);
};

export const gameEntryStorageKey = GAME_ENTRY_KEY;
