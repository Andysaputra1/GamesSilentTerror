import { Routes } from '@angular/router';

import { MainPage } from './features/main-page/main-page';
import { Auth } from './features/auth/auth';
import { Lobby } from './features/lobby/lobby';
import { Game } from './features/game/game';
import { Checker } from './features/checker/checker';
import { authGuard } from './core/auth.guard';
import { gameEntryGuard, loginRedirectGuard } from './core/flow.guard';

export const routes: Routes = [
  // Halaman debug sengaja tanpa guard untuk development lokal.
  { path: 'games/checker', component: Checker },
  { path: '', redirectTo: '/login', pathMatch: 'full' },
  { path: 'login', component: Auth, canActivate: [loginRedirectGuard] },
  { path: 'main', component: MainPage, canActivate: [authGuard] },
  { path: 'lobby', component: Lobby, canActivate: [authGuard] },
  { path: 'game', component: Game, canActivate: [authGuard, gameEntryGuard] },
  { path: '**', redirectTo: '/login' },
];
