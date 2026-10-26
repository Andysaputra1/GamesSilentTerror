import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import { of, Subject } from 'rxjs';
import { RoomService } from '../../core/room.service';

import { Lobby } from './lobby';

// TEST SUITE: kelompok pengujian otomatis, bukan logika yang dijalankan halaman production.
// Callback () => { ... } berisi setup dan skenario yang dipanggil oleh test runner.
describe('Lobby', () => {
  // INSTANCE TES: component adalah class halaman; fixture membungkus komponen untuk pengujian.
  let component: Lobby;
  let fixture: ComponentFixture<Lobby>;
  const member = (name: string) => ({ name, skin_id: 'dexter' });

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
  afterEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  // TES: pastikan komponen halaman dapat dibuat; belum menguji seluruh interaksinya.
  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('renders the binder room page and opens rules in a dismissible case file', () => {
    expect(fixture.nativeElement.querySelector('.room-binder')).toBeTruthy();
    expect(fixture.nativeElement.querySelector('.room-code-block')).toBeNull();

    fixture.nativeElement.querySelector('.room-guide-trigger').click();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[role="dialog"]')).toBeTruthy();

    fixture.nativeElement.querySelector('[aria-label="Tutup panduan"]').click();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[role="dialog"]')).toBeNull();
  });

  it('enables start at four players and previews roster timing', () => {
    component.room = {
      code: 'ABC123',
      owner: component.username,
      members: [member(component.username)],
      bots: ['NOX', 'ECHO', 'VEIL'],
      bot_enabled: true,
      phase: 'lobby',
      capacity: 4,
    };
    fixture.componentRef.changeDetectorRef.markForCheck();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.room-primary').disabled).toBe(false);
    expect(fixture.nativeElement.querySelector('.room-roster')).toBeTruthy();
    expect(fixture.nativeElement.querySelector('.room-controls')).toBeTruthy();
    expect(component.durations).toEqual({ day: 80, night: 20, tribunal: 60 });
    component.quick = true;
    expect(component.durations).toEqual({ day: 14, night: 10, tribunal: 10 });
  });

  // Room penuh manusia: bot yang sudah aktif tetap bisa dimatikan; menambah bot yang terkunci.
  it('lets the host remove bots from a full room and names the host by display name', () => {
    const humans = ['host', 'b', 'c', 'd'].map((name) => ({
      ...member(name),
      label: `Nama ${name}`,
    }));
    component.username = 'host';
    component.room = {
      code: 'ABC123',
      owner: 'host',
      members: humans,
      bots: [],
      bot_enabled: true,
      phase: 'lobby',
      capacity: 4,
    };
    fixture.componentRef.changeDetectorRef.markForCheck();
    fixture.detectChanges();
    const toggle = fixture.nativeElement.querySelector('.room-secondary') as HTMLButtonElement;
    expect(toggle.disabled).toBe(false);
    component.room = { ...component.room, bot_enabled: false };
    fixture.componentRef.changeDetectorRef.markForCheck();
    fixture.detectChanges();
    expect(toggle.disabled).toBe(true);
    expect(component.ownerLabel).toBe('Nama host');
  });

  it('renders the capacity of the restored room', () => {
    vi.spyOn(TestBed.inject(RoomService), 'current').mockReturnValue(
      of({
        code: 'ABC123',
        owner: 'alice',
        members: [member('alice')],
        bots: [],
        bot_enabled: false,
        phase: 'lobby',
        capacity: 10,
      }),
    );
    component.restoreRoom();
    fixture.componentRef.changeDetectorRef.markForCheck();
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('1 / 10');
    expect(fixture.nativeElement.querySelector('.room-code-block')).toBeTruthy();
  });

  it('restores the server room in a new tab', () => {
    sessionStorage.setItem('shadow_heist_game_entry', 'allowed');
    const room = {
      code: 'ABC123',
      owner: 'alice',
      members: [member('alice')],
      bots: [],
      bot_enabled: false,
      phase: 'lobby',
    };
    vi.spyOn(TestBed.inject(RoomService), 'current').mockReturnValue(of(room));
    component.restoreRoom();
    expect(sessionStorage.getItem('shadow_heist_room')).toBe('ABC123');
    expect(sessionStorage.getItem('shadow_heist_game_entry')).toBeNull();
    fixture.componentRef.changeDetectorRef.markForCheck();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.room-code-block')).toBeTruthy();
  });

  it('clears stale room and game pointers when the server no longer has a room', () => {
    for (const key of [
      'shadow_heist_room',
      'shadow_heist_room_snapshot',
      'shadow_heist_game_entry',
    ])
      sessionStorage.setItem(key, 'stale');
    vi.spyOn(TestBed.inject(RoomService), 'current').mockReturnValue(of(null));
    component.restoreRoom();
    expect(component.room).toBeNull();
    expect(sessionStorage.length).toBe(0);
  });

  // Anggota non-host otomatis ikut ke layar persiapan saat polling melihat pertandingan dimulai.
  it('enters the preparation screen when the host starts the match', () => {
    const room = {
      code: 'ABC123',
      owner: 'alice',
      members: [member('alice'), member('bob')],
      bots: ['NOX'],
      bot_enabled: true,
      phase: 'lobby',
    };
    component.room = room;
    const navigate = vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);
    vi.spyOn(TestBed.inject(RoomService), 'request').mockReturnValue(
      of({ ...room, phase: 'preparing' }),
    );
    (component as unknown as { load: (m: string, p: string) => void }).load('GET', '/ABC123');
    expect(navigate).toHaveBeenCalledWith('/game');
    expect(sessionStorage.getItem('shadow_heist_game_entry')).toBe('allowed');
  });

  // Tab di latar bisa melewatkan layar persiapan: polling berikutnya sudah melihat siang.
  it('still enters the game when polling skips the short preparation phase', () => {
    const room = {
      code: 'ABC123',
      owner: 'alice',
      members: [member('alice'), member('bob')],
      bots: [],
      bot_enabled: false,
      phase: 'lobby',
    };
    component.room = room;
    const navigate = vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);
    vi.spyOn(TestBed.inject(RoomService), 'request').mockReturnValue(of({ ...room, phase: 'day' }));
    (component as unknown as { load: (m: string, p: string) => void }).load('GET', '/ABC123');
    expect(navigate).toHaveBeenCalledWith('/game');
  });

  // Regresi: klik "+ Bots" saat polling latar berjalan dulu ditolak diam-diam (harus klik dua kali).
  it('adds bots on the first click even while a background poll is pending', () => {
    const room = {
      code: 'ABC123',
      owner: component.username,
      members: [member(component.username)],
      bots: [] as string[],
      bot_enabled: false,
      phase: 'lobby',
      capacity: 6,
    };
    component.room = room;
    const polling = new Subject<typeof room>();
    const request = vi
      .spyOn(TestBed.inject(RoomService), 'request')
      .mockImplementation((method: string) =>
        method === 'GET' ? polling : of({ ...room, bot_enabled: true, bots: ['NOX', 'ECHO'] }),
      );
    const load = (
      component as unknown as {
        load: (m: string, p: string, b?: unknown, latar?: boolean) => void;
      }
    ).load.bind(component);
    load('GET', '/ABC123', undefined, true);

    component.toggleBot();
    expect(request).toHaveBeenLastCalledWith('POST', '/ABC123/bot', { enabled: true });
    expect(component.room?.bots).toEqual(['NOX', 'ECHO']);
    // Snapshot polling yang dimulai sebelum klik tidak boleh menghapus bot yang baru masuk.
    polling.next(room);
    polling.complete();
    expect(component.room?.bots).toEqual(['NOX', 'ECHO']);
  });
});
