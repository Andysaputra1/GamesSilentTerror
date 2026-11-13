import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import { of, Subject } from 'rxjs';
import { Room, RoomService } from '../../core/room.service';

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
      bot_count: 3,
      bot_max: 5,
      phase: 'lobby',
      capacity: 4,
    };
    fixture.componentRef.changeDetectorRef.markForCheck();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.room-primary').disabled).toBe(false);
    expect(fixture.nativeElement.querySelector('.room-roster')).toBeTruthy();
    expect(fixture.nativeElement.querySelector('.room-controls')).toBeTruthy();
    expect(component.durations).toEqual({ day: 80, night: 20, tribunal: 60 });
    component.modeCepat = true;
    expect(component.durations).toEqual({ day: 14, night: 10, tribunal: 10 });
  });

  // Tombol bot di bawah daftar: jumlah dan batas, nonaktif bila kursi penuh, sudah 5, atau sudah 0.
  it('shows the bot count and disables bot buttons at the limits', () => {
    const humans = ['host', 'b', 'c', 'd'].map((name) => ({
      ...member(name),
      label: `Nama ${name}`,
    }));
    component.username = 'host';
    const tampilkan = (room: Partial<Room>) => {
      component.room = { ...component.room!, ...room };
      fixture.componentRef.changeDetectorRef.markForCheck();
      fixture.detectChanges();
      const [kurangi, tambah] = Array.from(
        fixture.nativeElement.querySelectorAll('.room-bot-buttons button'),
      ) as HTMLButtonElement[];
      return { kurangi: kurangi.disabled, tambah: tambah.disabled };
    };
    component.room = {
      code: 'ABC123',
      owner: 'host',
      members: humans,
      bots: [],
      bot_count: 0,
      bot_max: 5,
      phase: 'lobby',
      capacity: 4,
    };
    // Kursi penuh manusia dan belum ada bot: dua tombol mati.
    expect(tampilkan({})).toEqual({ kurangi: true, tambah: true });
    expect(fixture.nativeElement.textContent).toContain('Bot 0/5');
    expect(component.ownerLabel).toBe('Nama host');
    // Masih ada kursi: tambah hidup, kurangi mati karena belum ada bot.
    expect(tampilkan({ members: humans.slice(0, 1), capacity: 10 })).toEqual({
      kurangi: true,
      tambah: false,
    });
    // Sudah 5 bot walau kursi masih kosong: hanya kurangi yang hidup.
    const limaBot = ['NOX', 'ECHO', 'VEIL', 'RAVEN', 'ASH'];
    expect(tampilkan({ bots: limaBot, bot_count: 5 })).toEqual({ kurangi: false, tambah: true });
    expect(fixture.nativeElement.textContent).toContain('Bot 5/5');
    expect(fixture.nativeElement.textContent).toContain('NOX, ECHO, VEIL, RAVEN, ASH');
    // Anggota selain host melihat jumlahnya, tetapi tombolnya mati.
    component.username = 'b';
    expect(tampilkan({ bots: ['NOX'], bot_count: 1 })).toEqual({ kurangi: true, tambah: true });
    expect(fixture.nativeElement.textContent).toContain('Bot 1/5');
  });

  it('renders the capacity of the restored room', () => {
    vi.spyOn(TestBed.inject(RoomService), 'current').mockReturnValue(
      of({
        code: 'ABC123',
        owner: 'alice',
        members: [member('alice')],
        bots: [],
        bot_count: 0,
        bot_max: 5,
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
      bot_count: 1,
      bot_max: 5,
      phase: 'lobby',
    };
    component.room = room;
    const navigate = vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);
    vi.spyOn(TestBed.inject(RoomService), 'request').mockReturnValue(
      of({ ...room, phase: 'preparing' }),
    );
    (
      component as unknown as { kirimPermintaanRoom: (m: string, p: string) => void }
    ).kirimPermintaanRoom('GET', '/ABC123');
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
      phase: 'lobby',
    };
    component.room = room;
    const navigate = vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);
    vi.spyOn(TestBed.inject(RoomService), 'request').mockReturnValue(of({ ...room, phase: 'day' }));
    (
      component as unknown as { kirimPermintaanRoom: (m: string, p: string) => void }
    ).kirimPermintaanRoom('GET', '/ABC123');
    expect(navigate).toHaveBeenCalledWith('/game');
  });

  // Regresi: klik tombol bot saat polling latar berjalan dulu ditolak diam-diam (harus klik dua kali).
  it('adds a bot on the first click even while a background poll is pending', () => {
    const room = {
      code: 'ABC123',
      owner: component.username,
      members: [member(component.username)],
      bots: [] as string[],
      bot_count: 0,
      bot_max: 5,
      phase: 'lobby',
      capacity: 6,
    };
    component.room = room;
    const polling = new Subject<typeof room>();
    const request = vi
      .spyOn(TestBed.inject(RoomService), 'request')
      .mockImplementation((method: string) =>
        method === 'GET' ? polling : of({ ...room, bots: ['NOX'], bot_count: 1 }),
      );
    const load = (
      component as unknown as {
        kirimPermintaanRoom: (m: string, p: string, b?: unknown, pollingLatar?: boolean) => void;
      }
    ).kirimPermintaanRoom.bind(component);
    load('GET', '/ABC123', undefined, true);

    component.ubahBot('tambah');
    expect(request).toHaveBeenLastCalledWith('POST', '/ABC123/bot', { aksi: 'tambah' });
    expect(component.room?.bots).toEqual(['NOX']);
    // Snapshot polling yang dimulai sebelum klik tidak boleh menghapus bot yang baru masuk.
    polling.next(room);
    polling.complete();
    expect(component.room?.bots).toEqual(['NOX']);
  });

  // Satu tekan = satu bot: klik kedua selama permintaan pertama belum dijawab tidak dikirim.
  it('sends one bot request per press and ignores clicks while it is pending', () => {
    const room = {
      code: 'ABC123',
      owner: component.username,
      members: [member(component.username)],
      bots: ['NOX'],
      bot_count: 1,
      bot_max: 5,
      phase: 'lobby',
      capacity: 6,
    };
    component.room = room;
    const jawaban = new Subject<typeof room>();
    const request = vi.spyOn(TestBed.inject(RoomService), 'request').mockReturnValue(jawaban);
    component.ubahBot('tambah');
    component.ubahBot('tambah');
    component.ubahBot('kurangi');
    expect(request).toHaveBeenCalledTimes(1);
    expect(component.bisaUbahBot('tambah')).toBe(false);
    jawaban.next({ ...room, bots: ['NOX', 'ECHO'], bot_count: 2 });
    jawaban.complete();
    expect(component.jumlahBot).toBe(2);
    expect(component.busy).toBe(false);
    request.mockReturnValue(of({ ...room, bots: ['NOX'], bot_count: 1 }));
    component.ubahBot('kurangi');
    expect(request).toHaveBeenLastCalledWith('POST', '/ABC123/bot', { aksi: 'kurangi' });
    expect(component.room?.bots).toEqual(['NOX']);
  });
});
