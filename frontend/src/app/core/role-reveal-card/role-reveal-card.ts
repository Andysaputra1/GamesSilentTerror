import { Component, Input } from '@angular/core';

// KARTU ROLE PRATINJAU di Main: bingkai kartu role + skin pemain + properti role (mis. kacamata Spy).
@Component({
  selector: 'app-role-reveal-card',
  templateUrl: './role-reveal-card.html',
  styleUrl: './role-reveal-card.css',
})
export class RoleRevealCard {
  /** Skin pemain pada potret; kosong berarti memakai 'dexter'. */
  @Input() skinId: string | undefined = undefined;

  /** Role menentukan bingkai kartu dan properti yang tampil. */
  @Input() role: string = 'civilian';

  /** Induk mengatur pudar khusus potret saat skin di deck berganti. */
  @Input() skinTransition: 'idle' | 'out' | 'in' = 'idle';

  /** Nama berkas properti tiap role, tanpa ekstensi. */
  private readonly roleToProp: Record<string, string | null> = {
    spy: 'spy-shades',
    hitman: 'hitman-pistol',
    stalker: 'stalker-nerd-eyes',
    civilian: null, // Civilian tidak punya properti.
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

  /** URL properti role; null bila role ini tidak punya properti. */
  get propUrl(): string | null {
    const prop = this.roleToProp[this.role];
    return prop ? `/assets/props/${prop}.png` : null;
  }
}
