import { ApplicationConfig, provideBrowserGlobalErrorListeners } from '@angular/core';
import { PreloadAllModules, provideRouter, withPreloading } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';

import { routes } from './app.routes';
import { provideClientHydration, withEventReplay } from '@angular/platform-browser';

// OBJECT KONFIGURASI: fasilitas Angular yang dipasang ketika main.ts memulai aplikasi.
// Router memilih halaman; HTTP client memanggil API; hydration memakai ulang HTML awal
// dari server/build dan event replay memutar ulang interaksi yang tertangkap sebelum hidrasi.
export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    // Chunk game (lazy) diunduh di latar setelah halaman pertama tampil, sehingga lobby -> game
    // tidak menunggu unduhan JavaScript saat pertandingan dimulai.
    provideRouter(routes, withPreloading(PreloadAllModules)),
    provideClientHydration(withEventReplay()),
    provideHttpClient(),
  ],
};
