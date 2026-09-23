import { backendUrl } from '../../core/backend-url';
import { isPlatformBrowser } from '@angular/common';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectorRef,
  Component,
  DestroyRef,
  Inject,
  PLATFORM_ID,
  ElementRef,
  ViewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { finalize, TimeoutError, timeout, firstValueFrom } from 'rxjs';
import { loadGoogleIdentity } from '../../core/google-identity';

// INTERFACE: bentuk respons login yang diharapkan dari API Python.
interface LoginResponse {
  access_token: string;
  expires_at: string;
  user: { username: string; display_name: string };
}

// DECORATOR: sambungkan class Auth ke HTML/CSS login dan aktifkan binding form.
@Component({
  selector: 'app-auth',
  imports: [FormsModule],
  templateUrl: './auth.html',
  styleUrl: './auth.scss',
})
// CLASS KOMPONEN: mengatur perilaku halaman login, bukan memeriksa password di database.
export class Auth {
  // STATE/PROPERTY: data input dan status UI yang dibaca oleh auth.html.
  username = '';
  password = '';
  errorMessage = '';
  hasAttemptedSubmit = false;
  isSubmitting = false;
  passwordVisible = false;
  registerName = '';
  registerEmail = '';
  registerEmailVerify = '';
  registerPassword = '';
  registerPasswordVerify = '';
  registerError = '';
  googleError = '';
  googleLoading = false;
  googleReady = false;
  @ViewChild('googleButton') googleButton!: ElementRef<HTMLElement>;

  // REGISTER: validasi konfirmasi; backend tetap memvalidasi dan menangani duplikat.
  register(): void {
    if (!isPlatformBrowser(this.platformId) || this.isSubmitting) return;
    this.registerError = '';
    const username = this.registerName.trim();
    const email = this.registerEmail.trim().toLowerCase();
    if (!/^[A-Za-z0-9_]{3,40}$/.test(username)) {
      this.registerError = 'Username harus 3–40 huruf, angka, atau underscore.';
      return;
    }
    if (
      !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) ||
      email !== this.registerEmailVerify.trim().toLowerCase()
    ) {
      this.registerError = 'Email tidak valid atau konfirmasinya berbeda.';
      return;
    }
    if (
      this.registerPassword.length < 10 ||
      this.registerPassword.length > 128 ||
      this.registerPassword !== this.registerPasswordVerify
    ) {
      this.registerError = 'Password 10–128 karakter dan konfirmasinya harus sama.';
      return;
    }
    this.isSubmitting = true;
    this.http
      .post<LoginResponse>(this.backendUrl + '/api/auth/register', {
        username,
        email,
        email_confirmation: this.registerEmailVerify.trim(),
        password: this.registerPassword,
        password_confirmation: this.registerPasswordVerify,
      })
      .pipe(
        timeout(15000),
        takeUntilDestroyed(this.destroyRef),
        finalize(() => {
          this.isSubmitting = false;
          this.changeDetector.markForCheck();
        }),
      )
      .subscribe({
        next: (response) => {
          this.registerPassword = this.registerPasswordVerify = '';
          this.completeLogin(response);
        },
        error: (error: unknown) => {
          this.registerError =
            error instanceof HttpErrorResponse && error.status === 409
              ? 'Username atau email sudah digunakan. Silakan login.'
              : this.describeLoginError(error);
        },
      });
  }

  // Gunakan resolver URL bersama untuk request login biasa dan Google.
  private get backendUrl(): string {
    return backendUrl();
  }

  // GIS memverifikasi identitas di Google; backend memverifikasi token + nonce lagi.
  async prepareGoogle(): Promise<void> {
    if (!isPlatformBrowser(this.platformId) || this.googleLoading || this.isSubmitting) return;
    this.googleError = '';
    this.googleLoading = true;
    try {
      if (
        location.protocol !== 'https:' &&
        !['localhost', '127.0.0.1'].includes(location.hostname)
      ) {
        throw new Error(
          'Login Google perlu localhost atau domain HTTPS. Untuk LAN HTTP gunakan login biasa.',
        );
      }
      const config = await firstValueFrom(
        this.http
          .get<{ client_id: string }>(this.backendUrl + '/api/auth/google/config')
          .pipe(timeout(15000)),
      );
      if (!config.client_id) throw new Error('Login Google belum diaktifkan pengelola.');
      const challenge = await firstValueFrom(
        this.http
          .post<{ nonce: string }>(this.backendUrl + '/api/auth/google/challenge', {})
          .pipe(timeout(15000)),
      );
      const identity = await loadGoogleIdentity();
      if (this.destroyRef.destroyed) return;
      identity.initialize({
        client_id: config.client_id,
        nonce: challenge.nonce,
        auto_select: false,
        callback: (result) => this.submitGoogle(result.credential, challenge.nonce),
      });
      // Icon resmi Google tidak memaksa binder kecil menjadi lebih lebar.
      identity.renderButton(this.googleButton.nativeElement, {
        theme: 'outline',
        size: 'large',
        type: 'icon',
      });
      this.googleReady = true;
    } catch (error) {
      this.googleError =
        error instanceof HttpErrorResponse
          ? this.describeLoginError(error)
          : error instanceof Error
            ? error.message
            : 'Login Google gagal disiapkan.';
    } finally {
      this.googleLoading = false;
      this.changeDetector.markForCheck();
    }
  }

  // Tukar credential dan nonce Google menjadi sesi aplikasi, lalu bersihkan tombol login.
  private submitGoogle(credential: string, nonce: string): void {
    if (this.destroyRef.destroyed || this.isSubmitting) return;
    this.isSubmitting = true;
    this.http
      .post<LoginResponse>(this.backendUrl + '/api/auth/google', { credential, nonce })
      .pipe(
        timeout(20000),
        takeUntilDestroyed(this.destroyRef),
        finalize(() => {
          this.isSubmitting = false;
          this.googleReady = false;
          this.googleButton?.nativeElement.replaceChildren();
          this.changeDetector.markForCheck();
        }),
      )
      .subscribe({
        next: (response) => this.completeLogin(response),
        error: (error: unknown) => {
          this.googleError =
            error instanceof HttpErrorResponse && error.status === 409
              ? 'Email sudah terdaftar. Gunakan metode login awal.'
              : 'Login Google gagal atau kedaluwarsa. Silakan coba lagi.';
        },
      });
  }

  // CONSTANT MILIK INSTANCE: batas tunggu login; private berarti dipakai di dalam class.
  private readonly loginTimeoutMs = 15_000;

  // CONSTRUCTOR: Angular menyediakan HTTP, router, lifecycle, pembaruan view, dan platform.
  // function Object() { [native code] }
  constructor(
    private readonly http: HttpClient,
    private readonly router: Router,
    private readonly destroyRef: DestroyRef,
    private readonly changeDetector: ChangeDetectorRef,
    @Inject(PLATFORM_ID) private readonly platformId: object,
  ) {}

  // GETTER: menghasilkan label dari state saat ini; template membacanya seperti property.
  get statusLabel(): string {
    if (this.isSubmitting) return 'VERIFYING IDENTITY';
    if (this.errorMessage) return 'ACCESS CHECK FAILED';
    return 'SYSTEM ONLINE';
  }

  // METHOD EVENT FORM: validasi input, kirim POST login, lalu tangani sukses/gagal.
  // Form dikunci selama request dan selalu dibuka kembali melalui finalize.
  submit(): void {
    if (!isPlatformBrowser(this.platformId) || this.isSubmitting) return;

    this.hasAttemptedSubmit = true;
    this.username = this.username.trim();
    this.errorMessage = this.validateCredentials();
    if (this.errorMessage) return;

    this.isSubmitting = true;
    const baseUrl = backendUrl();
    this.http
      .post<LoginResponse>(`${baseUrl}/api/auth/login`, {
        username: this.username,
        password: this.password,
      })
      .pipe(
        timeout({ first: this.loginTimeoutMs }),
        takeUntilDestroyed(this.destroyRef),
        // FINALIZER CALLBACK: buka kembali form saat sukses, error, timeout,
        // maupun pembatalan subscription ketika komponen dilepas.
        finalize(() => {
          this.isSubmitting = false;
          this.changeDetector.markForCheck();
        }),
      )
      .subscribe({
        next: (response) => this.completeLogin(response),
        error: (error: unknown) => (this.errorMessage = this.describeLoginError(error)),
      });
  }

  // METHOD EVENT TOMBOL: isi akun demo untuk development; belum mengirim login.
  useDevelopmentCredentials(): void {
    if (this.isSubmitting) return;
    this.username = 'user1';
    this.password = 'user132';
    this.hasAttemptedSubmit = false;
    this.errorMessage = '';
  }

  // METHOD EVENT TOMBOL: tampilkan atau sembunyikan teks password.
  togglePasswordVisibility(): void {
    this.passwordVisible = !this.passwordVisible;
  }

  // METHOD EVENT INPUT: hapus pesan error lama ketika pengguna mengubah input.
  clearError(): void {
    if (this.errorMessage) this.errorMessage = '';
  }

  // PRIVATE METHOD: periksa input wajib di browser; keabsahan akun diperiksa backend.
  private validateCredentials(): string {
    if (!this.username && !this.password) return 'MASUKKAN USERNAME DAN PASSWORD TERLEBIH DAHULU.';
    if (!this.username) return 'USERNAME WAJIB DIISI.';
    if (!this.password) return 'PASSWORD WAJIB DIISI.';
    return '';
  }

  // PRIVATE METHOD: periksa respons, simpan sesi lokal, lalu buka main page.
  private completeLogin(response: LoginResponse): void {
    if (!response.access_token || !response.expires_at || !response.user?.username) {
      this.errorMessage = 'RESPONS LOGIN TIDAK LENGKAP. COBA LAGI.';
      return;
    }

    try {
      localStorage.setItem('shadow_heist_access_token', response.access_token);
      localStorage.setItem('shadow_heist_access_token_expires_at', response.expires_at);
      localStorage.setItem('shadow_heist_user', JSON.stringify(response.user));
      sessionStorage.removeItem('shadow_heist_game_entry');
    } catch {
      this.errorMessage = 'BROWSER MENOLAK PENYIMPANAN SESI. IZINKAN STORAGE LALU COBA LAGI.';
      return;
    }

    this.password = '';
    void this.router.navigateByUrl('/main').catch(() => {
      this.errorMessage = 'LOGIN BERHASIL, NAMUN MAIN PAGE GAGAL DIBUKA.';
    });
  }

  // PRIVATE METHOD: ubah jenis error HTTP/timeout menjadi pesan yang bisa dipahami pengguna.
  private describeLoginError(error: unknown): string {
    if (error instanceof TimeoutError) return 'SERVER TERLALU LAMA MERESPONS. COBA LAGI.';
    if (!(error instanceof HttpErrorResponse)) return 'TERJADI GANGGUAN TAK TERDUGA. COBA LAGI.';
    if (error.status === 0) return 'TIDAK BISA TERHUBUNG KE SERVER. CEK KONEKSI LALU COBA LAGI.';
    if (error.status === 400 || error.status === 422)
      return 'DATA LOGIN BELUM VALID. PERIKSA KEMBALI.';
    if (error.status === 401) return 'USERNAME ATAU PASSWORD SALAH.';
    if (error.status === 429) return 'TERLALU BANYAK PERCOBAAN. TUNGGU SEBENTAR LALU COBA LAGI.';
    if (error.status >= 500) return 'SERVER SEDANG BERMASALAH. COBA LAGI SEBENTAR LAGI.';
    return 'LOGIN GAGAL. SILAKAN COBA LAGI.';
  }
}
