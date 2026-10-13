import { Component } from '@angular/core';
import { PlayerAvatar } from '../../core/player-avatar/player-avatar';
import { RoleRevealCard } from '../../core/role-reveal-card/role-reveal-card';

const SKINS = ['arthur', 'dexter', 'eloise', 'jenny', 'kiera', 'sadie'];
const ROLES = ['spy', 'hitman', 'stalker', 'civilian'];

@Component({
  selector: 'app-debug-cards',
  imports: [PlayerAvatar, RoleRevealCard],
  templateUrl: './debug-cards.html',
  styleUrl: './debug-cards.css',
})
export class DebugCards {
  readonly skins = SKINS;
  readonly roles = ROLES;
}
