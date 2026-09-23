import { Component, DestroyRef, ElementRef, HostListener, Input, ViewChild, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { SessionService } from './session.service';

@Component({
  selector: 'app-profile-menu',
  template: `
    <button #trigger class="profile-trigger" type="button" [attr.aria-expanded]="open()"
      aria-controls="profile-actions" (click)="toggle()" [disabled]="session.loggingOut()">
      <i aria-hidden="true">◈</i><b>{{ username }}</b><span aria-hidden="true">⌄</span>
    </button>
    @if (open()) {
      <section id="profile-actions" class="profile-actions" aria-label="Menu akun">
        <p>AKUN SAYA</p><strong>{{ username }}</strong>
        @if (activeMatch) {
          <small>Pertandingan tetap berjalan. Login lagi untuk kembali ke permainanmu.</small>
        }
        @if (error()) { <small class="logout-error" role="alert">{{ error() }}</small> }
        <button type="button" class="logout-button" (click)="logout()" [disabled]="session.loggingOut()">
          {{ session.loggingOut() ? 'Keluar…' : 'Logout' }} <span aria-hidden="true">↗</span>
        </button>
      </section>
    }
  `,
  styles: `
    :host { position: relative; display: block; z-index: 20; max-width: 100%; }
    button { font: inherit; cursor: pointer; }
    button:focus-visible { outline: 3px solid #34768e; outline-offset: 3px; }
    button:disabled { cursor: wait; opacity: .65; }
    .profile-trigger { display: flex; align-items: center; gap: 10px; max-width: 100%;
      border: 1px solid #817357; border-radius: 12px; padding: 8px 12px;
      background: #f5eee0; color: #28251e; }
    .profile-trigger i { font-style: normal; font-size: 24px; color: #716038; }
    .profile-trigger b { max-width: 140px; overflow: hidden; text-overflow: ellipsis; font-size: 14px; }
    .profile-actions { position: absolute; right: 0; top: calc(100% + 10px); width: min(270px, 85vw);
      padding: 18px; border: 2px solid #493b28; border-radius: 14px; background: #fff7e5;
      color: #28251e; box-shadow: 0 10px 28px #24180d33; }
    .profile-actions p { margin: 0 0 8px; font: 11px Consolas, monospace; letter-spacing: .1em; }
    .profile-actions strong { display: block; overflow-wrap: anywhere; }
    .profile-actions small { display: block; margin-top: 12px; line-height: 1.5; }
    .logout-error { color: #922e2e; }
    .logout-button { display: flex; justify-content: space-between; width: 100%; margin-top: 16px;
      padding: 12px 14px; border: 1px solid #75422e; border-radius: 9px; background: #75422e; color: #fff7e5; }
    .logout-button:hover:not(:disabled) { background: #59311f; }
  `,
})
export class ProfileMenu {
  @Input() username = 'Pemain';
  @Input() activeMatch = false;
  @ViewChild('trigger') private trigger?: ElementRef<HTMLButtonElement>;
  readonly session = inject(SessionService);
  readonly open = signal(false);
  readonly error = signal('');
  private readonly element = inject(ElementRef<HTMLElement>);
  private readonly destroy = inject(DestroyRef);

  toggle(): void { this.open.update(value => !value); }

  @HostListener('document:click', ['$event'])
  outside(event: MouseEvent): void {
    if (!this.element.nativeElement.contains(event.target as Node)) this.open.set(false);
  }

  @HostListener('keydown.escape')
  close(): void {
    this.open.set(false);
    this.trigger?.nativeElement.focus();
  }

  logout(): void {
    if (this.session.loggingOut()) return;
    this.error.set('');
    this.session.logout().pipe(takeUntilDestroyed(this.destroy)).subscribe({
      error: () => this.error.set('Logout belum berhasil. Periksa koneksi lalu coba lagi.'),
    });
  }
}
