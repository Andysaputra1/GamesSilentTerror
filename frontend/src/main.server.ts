import { BootstrapContext, bootstrapApplication } from '@angular/platform-browser';
import { App } from './app/app';
import { config } from './app/app.config.server';

// FUNCTION (arrow): mulai Angular di lingkungan server/build, bukan di browser.
// Context diberikan oleh proses rendering Angular; konfigurasi SSR tetap digunakan.
const bootstrap = (context: BootstrapContext) => bootstrapApplication(App, config, context);

// Ekspor fungsi ini agar proses rendering Angular dapat memanggilnya.
export default bootstrap;
