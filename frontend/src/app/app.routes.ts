import { Routes } from '@angular/router';

import { MainPage } from './features/main-page/main-page';
import { Auth } from './features/auth/auth';
import { Lobby } from './features/lobby/lobby';
import { Game } from './features/game/game';
import { Checker } from './features/checker/checker';
import { authGuard } from './core/auth.guard';
import { loginRedirectGuard } from './core/flow.guard';
import { activeMatchGuard } from './core/active-match.service';

export const routes: Routes = [
  // Halaman debug sengaja tanpa guard untuk development lokal.
  { path: 'games/checker', component: Checker, canActivate: [activeMatchGuard] },
  { path: '', redirectTo: '/login', pathMatch: 'full' },
  { path: 'login', component: Auth, canActivate: [activeMatchGuard, loginRedirectGuard] },
  { path: 'main', component: MainPage, canActivate: [authGuard, activeMatchGuard] },
  { path: 'lobby', component: Lobby, canActivate: [authGuard, activeMatchGuard] },
  { path: 'game', component: Game, canActivate: [authGuard, activeMatchGuard] },
  { path: '**', redirectTo: '/login' },
];
