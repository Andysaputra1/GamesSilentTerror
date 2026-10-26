import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import { HttpRequest } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { MainPage } from './main-page';

// TEST SUITE: kelompok pengujian otomatis, bukan logika yang dijalankan halaman production.
// Callback () => { ... } berisi setup dan skenario yang dipanggil oleh test runner.
describe('MainPage', () => {
  // INSTANCE TES: component adalah class halaman; fixture membungkus komponen untuk pengujian.
  let component: MainPage;
  let fixture: ComponentFixture<MainPage>;
  let http: HttpTestingController;
  const me = (r: HttpRequest<unknown>) => r.url.endsWith('/api/auth/me');
  const skin = (r: HttpRequest<unknown>) => r.url.endsWith('/api/auth/skin');
  const storedSkin = () => JSON.parse(localStorage.getItem('shadow_heist_user') ?? '{}').skinId;

  // SETUP CALLBACK: siapkan lingkungan/instance baru sebelum setiap skenario tes.
  beforeEach(async () => {
    sessionStorage.clear();
    localStorage.setItem('shadow_heist_access_token', 'token-a');
    localStorage.setItem(
      'shadow_heist_user',
      JSON.stringify({ username: 'andy', displayName: 'Andy', skinId: 'kiera' }),
    );
    // Gerak dikurangi: skin berganti langsung tanpa animasi.
    window.matchMedia = vi
      .fn()
      .mockReturnValue({ matches: true }) as unknown as typeof window.matchMedia;
    await TestBed.configureTestingModule({
      imports: [MainPage],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();

    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(MainPage);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  afterEach(() => {
    // Pengingat survei diuji di survey-reminder.spec.ts.
    http.match((r) => r.url.endsWith('/api/survey/pending'));
    http.verify();
    vi.useRealTimers();
    localStorage.clear();
    sessionStorage.clear();
  });

  it('creates a room with the capacity selected on the main page', () => {
    sessionStorage.setItem('shadow_heist_game_entry', 'allowed');
    http.expectOne(me).flush({ username: 'andy', display_name: 'Andy', skin_id: 'kiera' });
    const navigate = vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);
    fixture.nativeElement.querySelector('.room-entry > .leather-button').click();
    fixture.detectChanges();
    const slider = fixture.nativeElement.querySelector('#room-capacity-slider') as HTMLInputElement;
    slider.value = '10';
    slider.dispatchEvent(new Event('input', { bubbles: true }));
    fixture.nativeElement.querySelector('.capacity-picker .leather-button').click();

    const request = http.expectOne((r) => r.url.endsWith('/api/rooms'));
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({ capacity: 10 });
    const room = {
      code: 'ABC123',
      owner: 'andy',
      members: [{ name: 'andy', skin_id: 'kiera' }],
      bots: [],
      bot_enabled: false,
      phase: 'lobby',
      capacity: 10,
    };
    request.flush(room);
    expect(sessionStorage.getItem('shadow_heist_room')).toBe('ABC123');
    expect(JSON.parse(sessionStorage.getItem('shadow_heist_room_snapshot')!)).toEqual(room);
    expect(navigate).toHaveBeenCalledWith('/lobby');
    expect(sessionStorage.getItem('shadow_heist_game_entry')).toBeNull();
    expect(component.busy).toBe(false);
  });

  it('normalizes the room code submitted from the main page', () => {
    sessionStorage.setItem('shadow_heist_game_entry', 'allowed');
    http.expectOne(me).flush({ username: 'andy', display_name: 'Andy', skin_id: 'kiera' });
    const navigate = vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);
    const input = fixture.nativeElement.querySelector('.join-input') as HTMLInputElement;
    input.value = 'abc123';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    fixture.nativeElement
      .querySelector('.join-form')
      .dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));

    const request = http.expectOne((r) => r.url.endsWith('/api/rooms/join'));
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({ code: 'ABC123' });
    request.flush({
      code: 'ABC123',
      owner: 'alice',
      members: [{ name: 'andy', skin_id: 'kiera' }],
      bots: [],
      bot_enabled: false,
      phase: 'lobby',
    });
    expect(sessionStorage.getItem('shadow_heist_room')).toBe('ABC123');
    expect(navigate).toHaveBeenCalledWith('/lobby');
    expect(sessionStorage.getItem('shadow_heist_game_entry')).toBeNull();
    expect(component.busy).toBe(false);
  });

  it('rejects invalid join codes before HTTP and unlocks the form after server failure', () => {
    http.expectOne(me).flush({ username: 'andy', display_name: 'Andy', skin_id: 'kiera' });
    const input = fixture.nativeElement.querySelector('.join-input') as HTMLInputElement;
    const form = fixture.nativeElement.querySelector('.join-form') as HTMLFormElement;
    input.value = 'xx';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    http.expectNone((r) => r.url.endsWith('/api/rooms/join'));
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[role="alert"]').textContent).toContain(
      '6 karakter',
    );

    input.value = 'ABC123';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    http
      .expectOne((r) => r.url.endsWith('/api/rooms/join'))
      .flush(
        { detail: 'Server belum bisa dihubungi.' },
        { status: 503, statusText: 'Service Unavailable' },
      );
    fixture.detectChanges();
    expect((form.querySelector('button') as HTMLButtonElement).disabled).toBe(false);
    expect(fixture.nativeElement.querySelector('[role="alert"]').textContent).toContain('Server');
    expect(sessionStorage.getItem('shadow_heist_room')).toBeNull();
  });

  // SKIN: tampilan awal memakai skin akun, lalu disamakan dengan server.
  it('shows the skin saved on the account', () => {
    expect(component.activeSkin.id).toBe('kiera');
    http.expectOne(me).flush({ username: 'andy', display_name: 'Andy', skin_id: 'jenny' });
    expect(component.activeSkin.id).toBe('jenny');
    expect(storedSkin()).toBe('jenny');
  });

  // SKIN: klik gantungan beruntun hanya mengirim satu request berisi pilihan terakhir.
  it('saves the chosen skin once after rapid clicks', () => {
    http.expectOne(me).flush({ username: 'andy', display_name: 'Andy', skin_id: 'kiera' });
    vi.useFakeTimers();
    component.cycleRoleDeckSkin();
    component.cycleRoleDeckSkin();
    expect(component.activeSkin.id).toBe('jenny');
    http.expectNone(skin);

    vi.advanceTimersByTime(600);
    const request = http.expectOne(skin);
    expect(request.request.method).toBe('PUT');
    expect(request.request.body).toEqual({ skin_id: 'jenny' });
    expect(request.request.headers.get('Authorization')).toBe('Bearer token-a');
    request.flush({ skin_id: 'jenny' });
    expect(storedSkin()).toBe('jenny');
    expect(component.deckAnnouncement).toContain('tersimpan');
  });

  // SKIN (zoneless): timer animasi harus memicu render sendiri; dulu potret tetap pudar
  // sampai ada event lain sehingga ganti skin terasa lambat.
  it('renders the next skin when the fade timer ends without any other event', async () => {
    http.expectOne(me).flush({ username: 'andy', display_name: 'Andy', skin_id: 'kiera' });
    window.matchMedia = vi
      .fn()
      .mockReturnValue({ matches: false }) as unknown as typeof window.matchMedia;
    vi.useFakeTimers();
    const frontSkin = () =>
      (fixture.nativeElement as HTMLElement)
        .querySelector('.role-deck__card--front .skin-img')
        ?.getAttribute('src');
    expect(frontSkin()).toContain('skin_kiera');
    component.cycleRoleDeckSkin();
    await vi.advanceTimersByTimeAsync(200);
    expect(frontSkin()).toContain('skin_eloise');
    await vi.advanceTimersByTimeAsync(300);
    const hanger = fixture.nativeElement.querySelector('.skin-cycle') as HTMLButtonElement;
    expect(hanger.disabled).toBe(false);
    await vi.advanceTimersByTimeAsync(300); // simpan 600 ms setelah skin berganti
    http.expectOne(skin).flush({ skin_id: 'eloise' });
  });

  // SKIN: gagal simpan mengembalikan tampilan ke skin yang benar-benar tersimpan.
  it('reverts the skin when saving fails', () => {
    http.expectOne(me).flush({ username: 'andy', display_name: 'Andy', skin_id: 'kiera' });
    vi.useFakeTimers();
    component.cycleRoleDeckSkin();
    expect(component.activeSkin.id).toBe('eloise');

    vi.advanceTimersByTime(600);
    http
      .expectOne(skin)
      .flush({ detail: 'down' }, { status: 503, statusText: 'Service Unavailable' });
    expect(component.activeSkin.id).toBe('kiera');
    expect(storedSkin()).toBe('kiera');
    expect(component.deckAnnouncement).toContain('gagal');
  });
});
