import { provideHttpClient } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { of, throwError } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { GameService, PendingSurvey, SurveyStatus } from '../../../core/game.service';
import { SurveyForm } from '../../../core/survey-form/survey-form';
import { SurveyReminder } from './survey-reminder';

const pending: PendingSurvey[] = [
  {
    match_id: 'm2',
    room_code: 'QWE456',
    role: 'hitman',
    team: 'hitman',
    outcome: 'won',
    finished_at: '2026-10-20T10:00:00',
  },
  {
    match_id: 'm1',
    room_code: 'ABC123',
    role: 'spy',
    team: 'civilians',
    outcome: 'lost',
    finished_at: '2026-10-20T09:00:00',
  },
];

const status: SurveyStatus = {
  match_id: 'm2',
  submitted: false,
  questions: [
    {
      id: 1,
      code: 'seru',
      prompt: 'Seberapa seru?',
      kind: 'stars',
      scale_min: 1,
      scale_max: 6,
      label_min: null,
      label_max: null,
      options: [],
      required: true,
    },
  ],
};

describe('SurveyReminder', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-10-21T00:00:00Z'));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  function create(list = pending): {
    fixture: ComponentFixture<SurveyReminder>;
    api: GameService;
    page: () => HTMLElement;
  } {
    TestBed.configureTestingModule({ imports: [SurveyReminder], providers: [provideHttpClient()] });
    const api = TestBed.inject(GameService);
    vi.spyOn(api, 'pendingSurveys').mockReturnValue(of(list));
    const fixture = TestBed.createComponent(SurveyReminder);
    fixture.detectChanges();
    const page = () => {
      fixture.changeDetectorRef.markForCheck();
      fixture.detectChanges();
      return fixture.nativeElement as HTMLElement;
    };
    return { fixture, api, page };
  }

  // Satu baris per pertandingan; X hanya menyembunyikan (kunjungan berikutnya mengambil ulang daftar).
  it('lists every unfinished survey and hides on close', () => {
    const { page } = create();
    const items = page().querySelectorAll('.reminder__list li');
    expect(items.length).toBe(2);
    expect(items[0].textContent).toContain('Ayo isi survei untuk game ruangan QWE456');
    expect(items[0].textContent).toContain('Hitman · Menang');
    expect(items[1].textContent).toContain('Spy · Kalah');
    expect(items[0].querySelector('time')?.textContent).toBe('20 Okt 2026, 17.00 WIB');
    expect(items[0].querySelector('time')?.getAttribute('datetime')).toBe(
      '2026-10-20T10:00:00.000Z',
    );
    (page().querySelector('.reminder__close') as HTMLButtonElement).click();
    expect(page().querySelector('.reminder')).toBeNull();
  });

  it('shows nothing when every survey is done', () => {
    const { page } = create([]);
    expect(page().querySelector('.reminder')).toBeNull();
  });

  it('keeps exactly seven days but hides older reminders', () => {
    vi.setSystemTime(new Date('2026-10-27T10:00:00Z'));
    const { page } = create();
    const items = page().querySelectorAll('.reminder__list li');
    expect(items.length).toBe(1);
    expect(items[0].textContent).toContain('QWE456');
    expect(page().querySelector('.reminder__intro p')?.textContent).toContain('1 pertandingan');
  });

  it('hides the whole reminder when all matches are older than seven days', () => {
    vi.setSystemTime(new Date('2026-10-28T00:00:00Z'));
    const { page } = create();
    expect(page().querySelector('.reminder')).toBeNull();
  });

  it('expires reminders and an open survey while the page stays open', () => {
    vi.setSystemTime(new Date('2026-10-27T09:00:00Z'));
    const { api, page } = create();
    vi.spyOn(api, 'survey').mockReturnValue(of({ ...status, match_id: 'm1' }));
    (page().querySelectorAll('.reminder__fill')[1] as HTMLButtonElement).click();
    expect(page().querySelector('.survey-dialog')).toBeTruthy();

    vi.advanceTimersByTime(1);
    expect(page().querySelectorAll('.reminder__list li').length).toBe(1);
    expect(page().querySelector('.reminder__list')?.textContent).toContain('QWE456');
    expect(page().querySelector('.survey-dialog')).toBeNull();

    vi.advanceTimersByTime(60 * 60 * 1000);
    expect(page().querySelector('.reminder')).toBeNull();
  });

  it('does not open an expired reminder after the browser clock advances', () => {
    const { api, page } = create();
    const survey = vi.spyOn(api, 'survey');
    const button = page().querySelector('.reminder__fill') as HTMLButtonElement;
    vi.setSystemTime(new Date('2026-10-28T00:00:00Z'));
    button.click();
    expect(survey).not.toHaveBeenCalled();
    expect(page().querySelector('.reminder')).toBeNull();
    expect(page().querySelector('.survey-dialog')).toBeNull();
  });

  it.each(['2026-10-20T18:00:00', '2026-10-20T18:00:00Z', '2026-10-21T01:00:00+07:00'])(
    'displays %s in WIB, including the local date change',
    (finished_at) => {
      const { page } = create([{ ...pending[0], finished_at }]);
      expect(page().querySelector('time')?.textContent).toBe('21 Okt 2026, 01.00 WIB');
      expect(page().querySelector('time')?.getAttribute('datetime')).toBe(
        '2026-10-20T18:00:00.000Z',
      );
    },
  );

  it('ignores missing or invalid completion dates', () => {
    const { page } = create([
      { ...pending[0], finished_at: '' },
      { ...pending[1], finished_at: 'invalid' },
    ]);
    expect(page().querySelector('.reminder')).toBeNull();
  });

  // Isi survei: pertanyaan dimuat untuk match itu, setelah terkirim baris tersebut hilang.
  it('opens the survey for that match and removes it after submitting', () => {
    const { fixture, api, page } = create();
    const survey = vi.spyOn(api, 'survey').mockReturnValue(of(status));
    (page().querySelector('.reminder__fill') as HTMLButtonElement).click();
    expect(survey).toHaveBeenCalledWith('QWE456', 'm2');
    expect(page().querySelector('.survey-dialog time')?.textContent).toBe('20 Okt 2026, 17.00 WIB');
    const form = fixture.debugElement.query(By.directive(SurveyForm));
    expect(form.nativeElement.textContent).toContain('Seberapa seru?');
    (form.componentInstance as SurveyForm).submitted.emit();
    expect(page().querySelector('.survey-dialog__done')?.textContent).toContain('Terima kasih');
    expect(page().querySelectorAll('.reminder__list li').length).toBe(1);
    (page().querySelector('.survey-dialog__close') as HTMLButtonElement).click();
    expect(page().querySelector('.survey-dialog')).toBeNull();
  });

  // Sudah dikirim dari tempat lain: langsung dianggap selesai; galat server tampil di pop-up.
  it('treats an already submitted survey as done and shows load errors', () => {
    const { api, page } = create();
    vi.spyOn(api, 'survey').mockReturnValue(of({ ...status, submitted: true }));
    (page().querySelector('.reminder__fill') as HTMLButtonElement).click();
    expect(page().querySelectorAll('.reminder__list li').length).toBe(1);
    vi.spyOn(api, 'survey').mockReturnValue(
      throwError(() => ({ status: 404, error: { detail: 'Ruangan tidak ditemukan.' } })),
    );
    (page().querySelector('.reminder__fill') as HTMLButtonElement).click();
    expect(page().querySelector('.survey-dialog [role="alert"]')?.textContent).toContain(
      'Ruangan tidak ditemukan.',
    );
  });
});
