import {
  Component,
  DestroyRef,
  ElementRef,
  HostListener,
  Input,
  ViewChild,
  inject,
  signal,
  OnInit,
  PLATFORM_ID,
  Output,
  EventEmitter,
} from '@angular/core';
import { isPlatformBrowser } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { finalize } from 'rxjs';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { SessionService, UserProfile } from './session.service';

@Component({
  selector: 'app-profile-menu',
  imports: [FormsModule],
  template: `
    <button #trigger class="profile-trigger" type="button" [attr.aria-expanded]="open()"
      aria-controls="profile-actions" (click)="toggle()" [disabled]="session.loggingOut()">
      <i aria-hidden="true">◈</i><b>{{ displayName }}</b><span aria-hidden="true">⌄</span>
    </button>
    @if (open()) {
      <section id="profile-actions" class="profile-actions" aria-label="Menu akun">
        <p>AKUN SAYA</p>
        <div class="profile-name">
          <strong>{{ displayName }}</strong>
          <button type="button" class="edit-name" aria-label="Ubah nama tampilan"
            (click)="editName()" [disabled]="saving() || session.loggingOut()">
            <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="m15 5 4 4M4 20l4-1L20 7a2.8 2.8 0 0 0-4-4L4 15z" />
            </svg>
          </button>
        </div>
        @if (editing()) {
          <form class="name-form" (ngSubmit)="saveName()">
            <label for="profile-display-name">Nama tampilan</label>
            <input #nameInput id="profile-display-name" name="displayName" [(ngModel)]="draftName"
              maxlength="100" required autocomplete="nickname" [disabled]="saving()" />
            <small>Nama tampilan: 1–100 karakter.</small>
            <label for="profile-username">Username</label>
            <input id="profile-username" name="username" [(ngModel)]="draftUsername"
              maxlength="40" autocomplete="username" [disabled]="saving() || activeMatch" />
            <small>3–40 huruf, angka, atau underscore. Keluar dari ruangan sebelum mengganti username.</small>
            <div class="name-actions">
              <button type="submit" [disabled]="saving() || !draftName.trim()">
                {{ saving() ? 'Menyimpan…' : 'Simpan' }}
              </button>
              <button type="button" (click)="cancelEdit()" [disabled]="saving()">Batal</button>
            </div>
          </form>
        }
        @if (saved()) { <small role="status">Nama berhasil disimpan.</small> }
        @if (activeMatch) {
          <small>Pertandingan tetap berjalan. Login lagi untuk kembali ke permainanmu.</small>
        }
        @if (error()) { <small class="logout-error" role="alert">{{ error() }}</small> }
        <button type="button" class="logout-button" (click)="logout()" [disabled]="saving() || session.loggingOut()">
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
    .profile-name { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
    .profile-name strong { min-width: 0; }
    .edit-name { display: grid; place-items: center; flex: none; padding: 8px; border: 1px solid #817357;
      border-radius: 8px; background: #f5eee0; color: #493b28; }
    .name-form { margin-top: 14px; }
    .name-form label { display: block; margin-bottom: 6px; }
    .name-form input { box-sizing: border-box; width: 100%; min-width: 0; padding: 9px;
      font: inherit; border: 1px solid #817357; border-radius: 7px; background: #fffdf8; color: #28251e; }
    .name-form input:focus-visible { outline: 3px solid #34768e; outline-offset: 2px; }
    .name-actions { display: flex; gap: 8px; margin-top: 12px; }
    .name-actions button { padding: 8px 12px; border: 1px solid #493b28; border-radius: 7px;
      background: #f5eee0; color: #28251e; }
    .name-actions button[type=submit] { background: #344c3d; color: #fff7e5; }
  `,
})
export class ProfileMenu implements OnInit {
  @Input() username = 'Pemain';
  @Input() activeMatch = false;
  @Output() profileChanged = new EventEmitter<UserProfile>();
  @ViewChild('trigger') private trigger?: ElementRef<HTMLButtonElement>;
  readonly session = inject(SessionService);
  readonly open = signal(false);
  readonly error = signal('');
  readonly editing = signal(false);
  readonly saving = signal(false);
  readonly saved = signal(false);
  private readonly profileName = signal('');
  private readonly profileUsername = signal('');
  draftName = '';
  draftUsername = '';
  private readonly platform = inject(PLATFORM_ID);
  private readonly element = inject(ElementRef<HTMLElement>);
  private readonly destroy = inject(DestroyRef);

  // Fokuskan nama saat form muncul agar pengguna langsung dapat mengetik dan menekan Enter.
  @ViewChild('nameInput') set nameInput(input: ElementRef<HTMLInputElement> | undefined) {
    if (input)
      queueMicrotask(() => {
        if (!this.destroy.destroyed) {
          input.nativeElement.focus();
          input.nativeElement.select();
        }
      });
  }

  // Muat cache profil hasil login/update; render SSR tidak mengakses storage browser.
  ngOnInit(): void {
    this.readProfile();
  }

  // Nama tampilan dapat berubah tanpa mengganti identifier yang dipakai lobby dan pertandingan.
  get displayName(): string {
    return this.profileName() || this.username;
  }

  // Baca nama dan username terbaru dari sesi yang tersimpan di browser.
  readProfile(): void {
    if (!isPlatformBrowser(this.platform)) return;
    try {
      const profile = JSON.parse(localStorage.getItem('shadow_heist_user') ?? '{}');
      this.profileName.set(typeof profile.display_name === 'string' ? profile.display_name : '');
      this.profileUsername.set(typeof profile.username === 'string' ? profile.username : '');
    } catch {
      this.profileName.set('');
      this.profileUsername.set('');
    }
  }

  // Sinkronkan username halaman induk setelah profil diubah dari tab lain.
  @HostListener('window:storage', ['$event'])
  profileStorageChanged(event: StorageEvent): void {
    if (event.key !== 'shadow_heist_user') return;
    this.readProfile();
    if (this.profileUsername())
      this.profileChanged.emit({
        username: this.profileUsername(),
        display_name: this.displayName,
      });
  }

  // Buka editor dengan nama terbaru; tidak mengirim request sebelum pengguna menyimpan.
  editName(): void {
    if (this.saving() || this.session.loggingOut()) return;
    this.draftName = this.displayName;
    this.draftUsername = this.profileUsername() || this.username;
    this.error.set('');
    this.saved.set(false);
    this.editing.set(true);
  }

  // Batalkan draft tanpa mengubah profil yang tersimpan.
  cancelEdit(): void {
    if (this.saving()) return;
    this.editing.set(false);
    this.error.set('');
  }

  // Simpan lewat submit form (Enter atau tombol); hanya tampilkan nama baru setelah server berhasil.
  saveName(): void {
    if (this.saving() || this.session.loggingOut()) return;
    const name = this.draftName.trim();
    const username = this.draftUsername.trim();
    const changingUsername = username !== (this.profileUsername() || this.username);
    if (changingUsername && !/^[A-Za-z0-9_]{3,40}$/.test(username)) {
      this.error.set('Username harus 3–40 huruf, angka, atau underscore.');
      return;
    }
    if (!name || Array.from(name).length > 100 || /[\p{Cc}\p{Cf}\p{Cs}]/u.test(name)) {
      this.error.set('Isi nama 1–100 karakter tanpa karakter kontrol.');
      return;
    }
    this.saving.set(true);
    this.error.set('');
    this.session
      .updateProfile(name, changingUsername ? username : undefined)
      .pipe(
        takeUntilDestroyed(this.destroy),
        finalize(() => this.saving.set(false)),
      )
      .subscribe({
        next: (profile) => {
          this.profileName.set(profile.display_name);
          this.profileUsername.set(profile.username);
          this.profileChanged.emit(profile);
          this.editing.set(false);
          this.saved.set(true);
        },
        error: (error: unknown) =>
          this.error.set(
            error instanceof HttpErrorResponse &&
              error.status === 409 &&
              typeof error.error?.detail === 'string'
              ? error.error.detail
              : error instanceof HttpErrorResponse && error.status === 401
                ? 'Sesi berakhir. Silakan login kembali.'
                : 'Nama belum berhasil disimpan. Periksa koneksi lalu coba lagi.',
          ),
      });
  }

  // Buka atau tutup pilihan akun dari tombol profil.
  toggle(): void {
    this.open.update((value) => !value);
  }

  // Tutup menu saat klik berasal dari luar komponen profil.
  @HostListener('document:click', ['$event'])
  outside(event: MouseEvent): void {
    if (!this.element.nativeElement.contains(event.target as Node)) this.open.set(false);
  }

  // Tutup menu lewat Escape dan kembalikan fokus ke tombol profil.
  @HostListener('keydown.escape')
  close(): void {
    this.open.set(false);
    this.trigger?.nativeElement.focus();
  }

  // Cegah klik ganda, jalankan logout, dan tampilkan error agar pengguna bisa mencoba lagi.
  logout(): void {
    if (this.saving() || this.session.loggingOut()) return;
    this.error.set('');
    this.session
      .logout()
      .pipe(takeUntilDestroyed(this.destroy))
      .subscribe({
        error: () => this.error.set('Logout belum berhasil. Periksa koneksi lalu coba lagi.'),
      });
  }
}
