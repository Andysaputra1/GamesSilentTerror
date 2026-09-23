import { environment } from '../../environments/environment';

// HTTP API and Socket.IO must use the same backend, independently of the frontend host.
export function backendUrl(): string {
  if (environment.backendUrl) return environment.backendUrl;
  if (typeof window === 'undefined') return '';
  if (environment.hosted) return window.location.origin;
  return `${window.location.protocol}//${window.location.hostname}:8000`;
}
