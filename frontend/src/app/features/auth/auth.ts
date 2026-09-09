import { isPlatformBrowser } from '@angular/common';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectorRef, Component, DestroyRef, Inject, PLATFORM_ID } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { finalize, TimeoutError, timeout } from 'rxjs';

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
  styleUrl: './auth.css',
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

  // CONSTANT MILIK INSTANCE: batas tunggu login; private berarti dipakai di dalam class.
  private readonly loginTimeoutMs = 15_000;

  // CONSTRUCTOR: Angular menyediakan HTTP, router, lifecycle, pembaruan view, dan platform.
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
    const backendUrl = `${window.location.protocol}//${window.location.hostname}:8000`;
    this.http
      .post<LoginResponse>(`${backendUrl}/api/auth/login`, {
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
