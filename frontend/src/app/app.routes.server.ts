import { RenderMode, ServerRoute } from '@angular/ssr';

// ARRAY KONFIGURASI RENDERING: '**' berlaku untuk semua URL.
// Prerender menyiapkan HTML saat build; interaksi halaman tetap diaktifkan di browser.
export const serverRoutes: ServerRoute[] = [
  {
    path: '**',
    renderMode: RenderMode.Prerender,
  },
];
