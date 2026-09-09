import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
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
  });

  // CLEANUP CALLBACK: pastikan tidak ada request HTTP mock yang belum ditangani setelah tes.
  afterEach(() => httpMock.verify());

  // TES: pastikan komponen login berhasil dibuat.
  it('creates', () => {
    expect(component).toBeTruthy();
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
