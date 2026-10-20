import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { of, throwError } from 'rxjs';
import { describe, expect, it, vi } from 'vitest';
import { GameService, SurveyStatus } from '../game.service';
import { SurveyForm } from './survey-form';

const status: SurveyStatus = {
  match_id: 'match-1',
  submitted: false,
  questions: [
    {
      id: 1,
      code: 'seru',
      prompt: 'Seberapa seru?',
      kind: 'stars',
      scale_min: 1,
      scale_max: 6,
      label_min: 'Bosan',
      label_max: 'Seru',
      options: [],
      required: true,
    },
    {
      id: 2,
      code: 'komentar',
      prompt: 'Komentar',
      kind: 'text',
      scale_min: 1,
      scale_max: 6,
      label_min: null,
      label_max: null,
      options: [],
      required: false,
    },
  ],
};

describe('SurveyForm', () => {
  function create(): { fixture: ComponentFixture<SurveyForm>; form: SurveyForm } {
    TestBed.configureTestingModule({ imports: [SurveyForm], providers: [provideHttpClient()] });
    const fixture = TestBed.createComponent(SurveyForm);
    fixture.componentRef.setInput('code', 'ABC123');
    fixture.componentRef.setInput('survey', status);
    fixture.detectChanges();
    return { fixture, form: fixture.componentInstance };
  }

  // Pertanyaan wajib harus dijawab dulu; jawaban dikirim sekali lalu event submitted dipancarkan.
  it('requires mandatory answers, then submits once and reports success', () => {
    const { fixture, form } = create();
    const submit = vi
      .spyOn(TestBed.inject(GameService), 'submitSurvey')
      .mockReturnValue(of({ submitted: true, answers: 1 }));
    const done = vi.fn();
    form.submitted.subscribe(done);
    expect(form.complete).toBe(false);
    const [stars] = status.questions;
    form.setAnswer(stars, 5);
    expect(form.isSelected(stars, 4)).toBe(true);
    expect(form.isSelected(stars, 6)).toBe(false);
    expect(form.complete).toBe(true);
    form.submit();
    expect(submit).toHaveBeenCalledWith('ABC123', 'match-1', [{ question_id: 1, value: 5 }]);
    expect(done).toHaveBeenCalledTimes(1);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelectorAll('.survey-question').length).toBe(2);
  });

  // 409 = sudah dikirim dari tab lain: dianggap selesai; galat lain tampil dan boleh dicoba lagi.
  it('treats an already submitted survey as done and shows other errors', () => {
    const { form } = create();
    const api = TestBed.inject(GameService);
    const done = vi.fn();
    form.submitted.subscribe(done);
    form.setAnswer(status.questions[0], 3);
    vi.spyOn(api, 'submitSurvey').mockReturnValue(
      throwError(() => ({ status: 409, error: { detail: 'Sudah dikirim.' } })),
    );
    form.submit();
    expect(done).toHaveBeenCalledTimes(1);
    vi.spyOn(api, 'submitSurvey').mockReturnValue(throwError(() => ({ status: 0, error: null })));
    form.submit();
    expect(done).toHaveBeenCalledTimes(1);
    expect(form.error).toBe('Survei gagal dikirim. Coba lagi.');
    expect(form.sending).toBe(false);
  });
});
