import { Component, Input, computed } from '@angular/core';

@Component({
  selector: 'app-player-avatar',
  templateUrl: './player-avatar.html',
  styleUrl: './player-avatar.css',
})
export class PlayerAvatar {
  /** Skin identifier for the avatar image. Falls back to 'dexter' if undefined. */
  @Input() skinId: string | undefined = undefined;

  /** Optional size class for styling. Default is 'medium'. */
  @Input() size: 'small' | 'medium' | 'large' = 'medium';

  private getSafeSkinId(): string {
    return this.skinId || 'dexter';
  }

  readonly skinUrl = computed(() => `/assets/characters/skin_${this.getSafeSkinId()}.png`);
}
