import { provideHttpClient } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { of, throwError } from 'rxjs';
import { describe, expect, it, vi } from 'vitest';
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
    (page().querySelector('.reminder__close') as HTMLButtonElement).click();
    expect(page().querySelector('.reminder')).toBeNull();
  });

  it('shows nothing when every survey is done', () => {
    const { page } = create([]);
    expect(page().querySelector('.reminder')).toBeNull();
  });

  // Isi survei: pertanyaan dimuat untuk match itu, setelah terkirim baris tersebut hilang.
  it('opens the survey for that match and removes it after submitting', () => {
    const { fixture, api, page } = create();
    const survey = vi.spyOn(api, 'survey').mockReturnValue(of(status));
    (page().querySelector('.reminder__fill') as HTMLButtonElement).click();
    expect(survey).toHaveBeenCalledWith('QWE456', 'm2');
    page();
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
