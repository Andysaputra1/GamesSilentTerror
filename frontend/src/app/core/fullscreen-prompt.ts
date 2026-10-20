import { DOCUMENT } from '@angular/common';
import { afterNextRender, Component, DestroyRef, inject, signal } from '@angular/core';

// TOMBOL LAYAR PENUH di HUD game (masuk/keluar); pop-up undangan di awal ada di FullscreenInvite.
@Component({
  selector: 'app-fullscreen-control',
  templateUrl: './fullscreen-prompt.html',
  styleUrl: './fullscreen-prompt.css',
})
export class FullscreenPrompt {
  private readonly document = inject(DOCUMENT);
  private readonly destroyRef = inject(DestroyRef);
  readonly available = signal(false);
  readonly active = signal(false);
  readonly pending = signal(false);
  readonly error = signal('');

  constructor() {
    // Tunggu render browser agar SSR tetap aman dan markup hidrasi konsisten.
    afterNextRender(() => {
      this.available.set(
        !!this.document.fullscreenEnabled &&
          typeof this.document.documentElement.requestFullscreen === 'function',
      );
      const onFullscreenChange = () => this.active.set(!!this.document.fullscreenElement);
      onFullscreenChange();
      this.document.addEventListener('fullscreenchange', onFullscreenChange);
      this.destroyRef.onDestroy(() =>
        this.document.removeEventListener('fullscreenchange', onFullscreenChange),
      );
    });
  }

  // Browser fullscreen tetap opsional dan hanya dipasang di layar game. Layout
  // aplikasi harus sudah muat satu viewport tanpa API ini.
  async toggleFullscreen(): Promise<void> {
    if (this.pending()) return;
    this.pending.set(true);
    this.error.set('');
    try {
      if (this.document.fullscreenElement) {
        await this.document.exitFullscreen();
        this.active.set(false);
      } else {
        // Harus langsung dari klik, sebelum await lain menghabiskan aktivasi pengguna.
        await this.document.documentElement.requestFullscreen();
        this.active.set(true);
      }
    } catch {
      this.error.set('Layar penuh belum bisa diubah. Coba lagi.');
    } finally {
      this.pending.set(false);
    }
  }
}
