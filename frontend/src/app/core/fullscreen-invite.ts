import { DOCUMENT } from '@angular/common';
import {
  afterNextRender,
  Component,
  computed,
  ElementRef,
  HostListener,
  inject,
  signal,
  ViewChild,
} from '@angular/core';
import { BootLoader } from './boot-loader';
import { STORAGE } from './storage';

// UNDANGAN LAYAR PENUH: muncul sekali per sesi tab setelah layar loading memudar, hanya bila browser
// mendukung Fullscreen API dan halaman belum layar penuh. Permintaan layar penuh harus langsung dari
// klik tombol (aturan browser), jadi pop-up ini hanya menawarkan, tidak memaksa.
@Component({
  selector: 'app-fullscreen-invite',
  templateUrl: './fullscreen-invite.html',
  styleUrl: './fullscreen-invite.css',
})
export class FullscreenInvite {
  private readonly document = inject(DOCUMENT);
  private readonly bootLoader = inject(BootLoader);
  private readonly perluDitawarkan = signal(false);
  readonly open = computed(() => this.perluDitawarkan() && this.bootLoader.done());

  // Fokus pindah ke tombol utama begitu dialog tampil (pengguna keyboard langsung bisa memilih).
  @ViewChild('enterButton') set enterButton(button: ElementRef<HTMLButtonElement> | undefined) {
    if (button) queueMicrotask(() => button.nativeElement.focus());
  }

  constructor() {
    afterNextRender(() => {
      const supported =
        !!this.document.fullscreenEnabled &&
        typeof this.document.documentElement.requestFullscreen === 'function';
      this.perluDitawarkan.set(
        supported && !this.document.fullscreenElement && !this.sudahPernahDitanya(),
      );
    });
  }

  async masukLayarPenuh(): Promise<void> {
    this.tutupUndangan();
    try {
      await this.document.documentElement.requestFullscreen();
    } catch {
      // Browser menolak (mis. kebijakan perangkat): permainan tetap jalan di jendela biasa.
    }
  }

  @HostListener('document:keydown.escape')
  tutupUndangan(): void {
    if (!this.perluDitawarkan()) return;
    this.perluDitawarkan.set(false);
    try {
      sessionStorage.setItem(STORAGE.fullscreenAsked, '1');
    } catch {}
  }

  // Storage yang diblokir dianggap sudah ditanya agar pop-up tidak muncul di setiap halaman.
  private sudahPernahDitanya(): boolean {
    try {
      return sessionStorage.getItem(STORAGE.fullscreenAsked) === '1';
    } catch {
      return true;
    }
  }
}
