import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import { of, throwError } from 'rxjs';
import { RoomService } from '../../core/room.service';

import { Lobby } from './lobby';

// TEST SUITE: kelompok pengujian otomatis, bukan logika yang dijalankan halaman production.
// Callback () => { ... } berisi setup dan skenario yang dipanggil oleh test runner.
describe('Lobby', () => {
  // INSTANCE TES: component adalah class halaman; fixture membungkus komponen untuk pengujian.
  let component: Lobby;
  let fixture: ComponentFixture<Lobby>;

  // SETUP CALLBACK: siapkan lingkungan/instance baru sebelum setiap skenario tes.
  beforeEach(async () => {
    localStorage.clear();
    sessionStorage.clear();
    await TestBed.configureTestingModule({
      imports: [Lobby],
      providers: [provideRouter([]), provideHttpClient()],
    }).compileComponents();

    fixture = TestBed.createComponent(Lobby);
    component = fixture.componentInstance;
    await fixture.whenStable();
  });
  afterEach(() => { localStorage.clear(); sessionStorage.clear(); });

  // TES: pastikan komponen halaman dapat dibuat; belum menguji seluruh interaksinya.
  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('keeps typed room code and submits the normalized code', () => {
    const input = fixture.nativeElement.querySelector('#room-code') as HTMLInputElement;
    input.value = 'abc123';
    input.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    expect(component.joinCode).toBe('abc123');
    expect(input.value).toBe('abc123');
    const request = vi.spyOn(TestBed.inject(RoomService), 'request').mockReturnValue(
      of({
        code: 'ABC123',
        owner: 'alice',
        members: ['alice'],
        bots: [],
        bot_enabled: false,
        phase: 'lobby',
      }),
    );
    component.joinRoom();
    expect(request).toHaveBeenCalledWith('POST', '/join', { code: 'ABC123' });
    expect(component.busy).toBe(false);
    sessionStorage.clear();
  });

  it('rejects invalid codes before HTTP and unlocks after server failure', () => {
    const request = vi
      .spyOn(TestBed.inject(RoomService), 'request')
      .mockReturnValue(throwError(() => ({ status: 503 })));
    component.joinCode = 'xx';
    component.joinRoom();
    expect(request).not.toHaveBeenCalled();
    component.joinCode = 'ABC123';
    component.joinRoom();
    expect(component.busy).toBe(false);
    expect(component.error).toContain('Server');
  });

  it('restores the server room in a new tab and prevents joining another lobby', () => {
    const room = {code: 'ABC123', owner: 'alice', members: ['alice'], bots: [], bot_enabled: false, phase: 'lobby'};
    vi.spyOn(TestBed.inject(RoomService), 'current').mockReturnValue(of(room));
    const request = vi.spyOn(TestBed.inject(RoomService), 'request');
    component.restoreRoom();
    component.joinCode = 'DEF456';
    component.joinRoom();
    component.createRoom();
    expect(request).not.toHaveBeenCalled();
    expect(sessionStorage.getItem('shadow_heist_room')).toBe('ABC123');
    fixture.componentRef.changeDetectorRef.markForCheck();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('#room-code')).toBeNull();
  });

  it('clears stale room and game pointers when the server no longer has a room', () => {
    for (const key of ['shadow_heist_room', 'shadow_heist_room_snapshot', 'shadow_heist_game_entry']) sessionStorage.setItem(key, 'stale');
    vi.spyOn(TestBed.inject(RoomService), 'current').mockReturnValue(of(null));
    component.restoreRoom();
    expect(component.room).toBeNull();
    expect(sessionStorage.length).toBe(0);
  });
});
