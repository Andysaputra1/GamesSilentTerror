import { afterEach, describe, expect, it, vi } from 'vitest';
import { environment } from '../../environments/environment';
import { backendUrl } from './backend-url';

describe('backendUrl', () => {
  afterEach(() => {
    environment.backendUrl = '';
    environment.hosted = false;
    vi.unstubAllGlobals();
  });

  it('keeps LAN development connected to the backend on port 8000', () => {
    vi.stubGlobal('window', { location: { protocol: 'http:', hostname: '192.168.1.20' } });
    expect(backendUrl()).toBe('http://192.168.1.20:8000');
  });

  it('uses the configured backend independently of the frontend domain', () => {
    environment.hosted = true;
    environment.backendUrl = 'https://api.example.com';
    vi.stubGlobal('window', { location: { origin: 'https://game.vercel.app' } });
    expect(backendUrl()).toBe('https://api.example.com');
  });

  it('does not append a development port to a frontend-only deployment', () => {
    environment.hosted = true;
    vi.stubGlobal('window', { location: { origin: 'https://game.vercel.app' } });
    expect(backendUrl()).toBe('https://game.vercel.app');
  });

  it('can be evaluated during prerendering without browser globals', () => {
    vi.stubGlobal('window', undefined);
    expect(backendUrl()).toBe('');
  });
});
