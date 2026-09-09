import {
  AngularNodeAppEngine,
  createNodeRequestHandler,
  isMainModule,
  writeResponseToNodeResponse,
} from '@angular/ssr/node';
import express from 'express';
import { join } from 'node:path';

// CONSTANT: lokasi HTML, JavaScript, CSS, dan aset hasil build browser.
const browserDistFolder = join(import.meta.dirname, '../browser');

// INSTANCE: server Express untuk menyajikan frontend; API game tetap di Python.
const app = express();
// INSTANCE: mesin Angular yang menangani permintaan halaman sesuai aturan rendering.
const angularApp = new AngularNodeAppEngine();

/**
 * BATAS TANGGUNG JAWAB: Express di file ini menyajikan frontend Angular.
 * Endpoint login, ruangan, database, dan AI tetap berada di backend Python.
 */

/**
 * MIDDLEWARE: sajikan aset hasil build browser sebelum memproses route halaman.
 */
app.use(
  express.static(browserDistFolder, {
    maxAge: '1y',
    index: false,
    redirect: false,
  }),
);

/**
 * CALLBACK MIDDLEWARE: serahkan request halaman kepada mesin Angular.
 * Kirim respons ke browser, atau teruskan ke middleware berikutnya jika tidak ditangani.
 */
app.use((req, res, next) => {
  angularApp
    .handle(req)
    .then((response) => (response ? writeResponseToNodeResponse(response, res) : next()))
    .catch(next);
});

/**
 * STARTUP KONDISIONAL: buka port jika file ini dijalankan langsung atau melalui PM2.
 * Gunakan environment PORT, default 4000. Ini berbeda dari ng serve development pada 4200.
 */
if (isMainModule(import.meta.url) || process.env['pm_id']) {
  const port = process.env['PORT'] || 4000;
  app.listen(port, (error) => {
    if (error) {
      throw error;
    }

    console.log(`Node Express server listening on http://localhost:${port}`);
  });
}

/**
 * FUNCTION HANDLER EKSPOR: adapter request Express yang dapat dipakai Angular CLI
 * saat development/build atau oleh lingkungan hosting yang mengimpor modul ini.
 */
export const reqHandler = createNodeRequestHandler(app);
