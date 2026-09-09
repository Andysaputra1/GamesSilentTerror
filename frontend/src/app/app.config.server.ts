import { mergeApplicationConfig, ApplicationConfig } from '@angular/core';
import { provideServerRendering, withRoutes } from '@angular/ssr';
import { appConfig } from './app.config';
import { serverRoutes } from './app.routes.server';

// OBJECT KONFIGURASI: tambahkan fasilitas rendering Angular beserta aturan route server.
const serverConfig: ApplicationConfig = {
  providers: [provideServerRendering(withRoutes(serverRoutes))],
};

// CONSTANT HASIL GABUNGAN: konfigurasi umum + konfigurasi server untuk main.server.ts.
export const config = mergeApplicationConfig(appConfig, serverConfig);
