import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
  TestRequest,
} from '@angular/common/http/testing';
import { PLATFORM_ID } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';

import { Auth } from './auth';

// TEST SUITE: kelompok pengujian otomatis, bukan logika yang dijalankan halaman production.
// Callback () => { ... } berisi setup dan skenario yang dipanggil oleh test runner.
describe('Auth', () => {
  // INSTANCE TES: component adalah class halaman; fixture membungkus komponen untuk pengujian.
  let component: Auth;
  let fixture: ComponentFixture<Auth>;
  let httpMock: HttpTestingController;
  let readiness: TestRequest;

  // SETUP CALLBACK: siapkan lingkungan/instance baru sebelum setiap skenario tes.
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [Auth],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: PLATFORM_ID, useValue: 'browser' },
        { provide: Router, useValue: { navigateByUrl: () => Promise.resolve(true) } },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(Auth);
    component = fixture.componentInstance;
    httpMock = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    readiness = httpMock.expectOne((request) => request.url === 'http://localhost:8000/ready');
  });

  // CLEANUP CALLBACK: pastikan tidak ada request HTTP mock yang belum ditangani setelah tes.
  afterEach(() => {
    fixture.destroy();
    httpMock.verify();
    vi.useRealTimers();
  });

  // Status awal tidak mengklaim online sebelum backend menjawab readiness.
  it('reports online only after a successful readiness response', () => {
    expect(component.statusLabel).toBe('MEMERIKSA SERVER…');
    readiness.flush({ ready: true });
    expect(component.statusLabel).toBe('SYSTEM ONLINE');
    component.errorMessage = 'Password salah';
    expect(component.statusLabel).toBe('SYSTEM ONLINE');
  });

  it('treats an unexpected successful response as offline', () => {
    readiness.flush({ status: 'OK' });
    expect(component.backendStatus).toBe('offline');
  });

  // Gangguan jaringan menampilkan kontak; fokus berikutnya bisa memulihkan status tanpa reload.
  it('shows the WhatsApp contact when unreachable and recovers on focus', () => {
    readiness.error(new ProgressEvent('error'));
    fixture.detectChanges();
    expect(component.statusLabel).toBe('SYSTEM OFFLINE');
    const link = fixture.nativeElement.querySelector('a[href*="wa.me"]') as HTMLAnchorElement;
    expect(link.textContent).toContain('Andy Saputra');
    expect(link.href).toContain('https://wa.me/6281995247372?text=');
    expect(decodeURIComponent(link.href)).toContain('tolong nyalakan server Silent Terror');
    expect(fixture.nativeElement.textContent).toContain('Janice Tiffany Wijono');
    expect(fixture.nativeElement.textContent).toContain('Kimberly Joseph Wirawan');
    window.dispatchEvent(new Event('focus'));
    httpMock.expectOne((request) => request.url.endsWith('/ready')).flush({ ready: true });
    fixture.detectChanges();
    expect(component.backendStatus).toBe('online');
    expect(fixture.nativeElement.querySelector('a[href*="wa.me"]')).toBeNull();
  });

  it('reports a not-ready backend as offline', () => {
    readiness.flush({ ready: false }, { status: 503, statusText: 'Unavailable' });
    expect(component.backendStatus).toBe('offline');
  });

  it('times out a stalled check and cancels pending requests on destroy', () => {
    readiness.flush({ ready: true });
    vi.useFakeTimers();
    window.dispatchEvent(new Event('focus'));
    const stalled = httpMock.expectOne((request) => request.url.endsWith('/ready'));
    vi.advanceTimersByTime(8_000);
    expect(stalled.cancelled).toBe(true);
    expect(component.backendStatus).toBe('offline');
    window.dispatchEvent(new Event('focus'));
    const pending = httpMock.expectOne((request) => request.url.endsWith('/ready'));
    fixture.destroy();
    expect(pending.cancelled).toBe(true);
  });

  // TES: pastikan komponen login berhasil dibuat.
  it('creates', () => {
    expect(component).toBeTruthy();
  });

  it('rejects a blank display name without a request', () => {
    component.registerName = 'detective';
    component.registerDisplayName = '   ';
    component.register();
    expect(component.registerError).toContain('nama lengkap');
    expect(component.isSubmitting).toBe(false);
    httpMock.expectNone('http://localhost:8000/api/auth/register');
  });

  it('unlocks registration after an existing-account response', () => {
    component.registerName = 'detective';
    component.registerDisplayName = 'Detective Test';
    component.registerPassword = component.registerPasswordVerify = 'strong-password';
    component.register();
    const request = httpMock.expectOne('http://localhost:8000/api/auth/register');
    expect(request.request.body.display_name).toBe('Detective Test');
    expect(request.request.body.email).toBeUndefined();
    expect(request.request.body.email_confirmation).toBeUndefined();
    request.flush({}, { status: 409, statusText: 'Conflict' });
    expect(component.isSubmitting).toBe(false);
    expect(component.registerError).toContain('sudah digunakan');
  });

  it('explains Google configuration missing without loading Google', async () => {
    const pending = component.prepareGoogle();
    httpMock.expectOne('http://localhost:8000/api/auth/google/config').flush({ client_id: '' });
    await pending;
    expect(component.googleError).toContain('belum diaktifkan');
    expect(component.googleLoading).toBe(false);
  });

  // TES: simulasikan HTTP 401 untuk memastikan form tidak macet setelah password salah.
  it('keeps the form usable after an invalid-password response', () => {
    component.username = 'user1';
    component.password = 'wrong-password';
    component.submit();

    expect(component.isSubmitting).toBe(true);
    const request = httpMock.expectOne('http://localhost:8000/api/auth/login');
    expect(request.request.method).toBe('POST');
    request.flush(
      { detail: 'Username atau password tidak valid.' },
      {
        status: 401,
        statusText: 'Unauthorized',
      },
    );

    expect(component.isSubmitting).toBe(false);
    expect(component.errorMessage).toBe('USERNAME ATAU PASSWORD SALAH.');
  });

  // TES: input kosong harus menghasilkan pesan validasi tanpa mengirim request API.
  it('shows validation feedback without starting a request', () => {
    component.submit();

    expect(component.isSubmitting).toBe(false);
    expect(component.errorMessage).toBe('MASUKKAN USERNAME DAN PASSWORD TERLEBIH DAHULU.');
    httpMock.expectNone('http://localhost:8000/api/auth/login');
  });
});
