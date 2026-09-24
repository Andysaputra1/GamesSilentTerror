import { DOCUMENT } from '@angular/common';
import { afterNextRender, Component, DestroyRef, inject, signal } from '@angular/core';

@Component({
  selector: 'app-fullscreen-prompt',
  templateUrl: './fullscreen-prompt.html',
  styleUrl: './fullscreen-prompt.css',
})
export class FullscreenPrompt {
  private readonly document = inject(DOCUMENT);
  private readonly destroyRef = inject(DestroyRef);
  readonly visible = signal(false);
  readonly pending = signal(false);
  readonly error = signal('');

  constructor() {
    // Tunggu render browser agar SSR tetap aman dan markup hidrasi konsisten.
    afterNextRender(() => {
      this.visible.set(
        this.document.fullscreenEnabled &&
          typeof this.document.documentElement.requestFullscreen === 'function' &&
          !this.document.fullscreenElement,
      );
      const onFullscreenChange = () => {
        if (this.document.fullscreenElement) this.dismiss();
      };
      this.document.addEventListener('fullscreenchange', onFullscreenChange);
      this.destroyRef.onDestroy(() =>
        this.document.removeEventListener('fullscreenchange', onFullscreenChange),
      );
    });
  }

  dismiss(): void {
    this.visible.set(false);
  }

  async enterFullscreen(): Promise<void> {
    if (this.pending()) return;
    if (this.document.fullscreenElement) {
      this.dismiss();
      return;
    }
    this.pending.set(true);
    this.error.set('');
    try {
      // Harus langsung dari klik, sebelum await lain menghabiskan aktivasi pengguna.
      // Elemen root menjaga fullscreen saat pengguna berpindah halaman aplikasi.
      await this.document.documentElement.requestFullscreen();
      this.dismiss();
    } catch {
      this.error.set('Layar penuh belum bisa dibuka. Coba lagi atau pilih Nanti.');
    } finally {
      this.pending.set(false);
    }
  }
}
