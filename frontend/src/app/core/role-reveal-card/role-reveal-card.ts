import { Component, Input } from '@angular/core';

// KARTU ROLE PRATINJAU di Main: bingkai kartu role + skin pemain + properti role (mis. kacamata Spy).
@Component({
  selector: 'app-role-reveal-card',
  templateUrl: './role-reveal-card.html',
  styleUrl: './role-reveal-card.css',
})
export class RoleRevealCard {
  /** Skin identifier for the avatar. Falls back to 'dexter' if undefined. */
  @Input() skinId: string | undefined = undefined;

  /** Role determines which card frame and prop to display. */
  @Input() role: string = 'civilian';

  /** Parent controls the portrait-only fade when the deck skin changes. */
  @Input() skinTransition: 'idle' | 'out' | 'in' = 'idle';

  /** Mapping from role to prop asset filename (without extension). */
  private readonly roleToProp: Record<string, string | null> = {
    spy: 'spy-shades',
    hitman: 'hitman-pistol',
    stalker: 'stalker-nerd-eyes',
    civilian: null, // Civilian has no prop
  };

  private getSafeSkinId(): string {
    return this.skinId || 'dexter';
  }

  get skinUrl(): string {
    return `/assets/characters/skin_${this.getSafeSkinId()}.png`;
  }

  get frameUrl(): string {
    return `/assets/cards/card_${this.role}.png`;
  }

  /** Returns prop URL if the role has one, null otherwise. */
  get propUrl(): string | null {
    const prop = this.roleToProp[this.role];
    return prop ? `/assets/props/${prop}.png` : null;
  }
}
