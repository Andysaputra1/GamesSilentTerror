import { bootstrapApplication } from '@angular/platform-browser';
import { appConfig } from './app/app.config';
import { App } from './app/app';

// ENTRY POINT BROWSER: mulai komponen App di <app-root> dengan fasilitas dari appConfig.
bootstrapApplication(App, appConfig).catch((err) => console.error(err));
