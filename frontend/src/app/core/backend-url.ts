import { environment } from '../../environments/environment';

// API HTTP dan Socket.IO harus memakai backend yang sama, di mana pun frontend di-host.
export function backendUrl(): string {
  if (environment.backendUrl) return environment.backendUrl;
  if (typeof window === 'undefined') return '';
  if (environment.hosted) return window.location.origin;
  return `${window.location.protocol}//${window.location.hostname}:8000`;
}
