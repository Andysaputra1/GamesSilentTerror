import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { of } from 'rxjs';
import { App } from './app';
import { ActiveMatchService } from './core/active-match.service';
import { BootLoader } from './core/boot-loader';
import { provideHttpClient } from '@angular/common/http';

// TEST SUITE: kelompok pengujian otomatis, bukan logika yang dijalankan halaman production.
// Callback () => { ... } berisi setup dan skenario yang dipanggil oleh test runner.
describe('App', () => {
  // SETUP CALLBACK: siapkan lingkungan/instance baru sebelum setiap skenario tes.
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [provideRouter([]), provideHttpClient()],
    }).compileComponents();
  });

  // TES: pastikan Angular dapat membuat komponen utama.
  it('should create the app', () => {
    const fixture = TestBed.createComponent(App);
    const app = fixture.componentInstance;
    expect(app).toBeTruthy();
  });

  // Tab lain login dengan akun lain: room tab ini dilupakan dan pesan dititipkan sebelum Main dimuat ulang.
  // Logout di tab lain tetap membawa tab ini ke /login.
  it('follows a login or logout made in another tab', () => {
    const navigate = vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);
    vi.spyOn(TestBed.inject(ActiveMatchService), 'lookup').mockReturnValue(of(null));
    vi.spyOn(TestBed.inject(BootLoader), 'start').mockImplementation(() => {});
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    const kirimStorage = (oldValue: string | null, newValue: string | null) =>
      window.dispatchEvent(
        new StorageEvent('storage', {
          key: 'shadow_heist_access_token',
          oldValue,
          newValue,
          storageArea: localStorage,
        }),
      );
    sessionStorage.setItem('shadow_heist_room', 'ABC123');
    localStorage.setItem('shadow_heist_access_token', 'token-b');
    kirimStorage('token-a', 'token-b');
    expect(sessionStorage.getItem('shadow_heist_room')).toBeNull();
    expect(sessionStorage.getItem('shadow_heist_notice')).toContain('Akun berganti di tab lain');

    localStorage.removeItem('shadow_heist_access_token');
    kirimStorage('token-b', null);
    expect(navigate).toHaveBeenCalledWith('/login', { replaceUrl: true });
    fixture.destroy();
    sessionStorage.clear();
  });
});
