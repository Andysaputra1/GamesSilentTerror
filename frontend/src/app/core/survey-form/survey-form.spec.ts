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
  function create(survey = status): { fixture: ComponentFixture<SurveyForm>; form: SurveyForm } {
    TestBed.configureTestingModule({ imports: [SurveyForm], providers: [provideHttpClient()] });
    const fixture = TestBed.createComponent(SurveyForm);
    fixture.componentRef.setInput('code', 'ABC123');
    fixture.componentRef.setInput('survey', survey);
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

  it('collects other-choice details and clears them when a preset is chosen', async () => {
    const choice = {
      ...status.questions[1],
      kind: 'choice' as const,
      options: ['Lebih cepat', 'Lebih berempati', 'Lainnya'],
    };
    const { fixture, form } = create({ ...status, questions: [choice] });
    const submit = vi
      .spyOn(TestBed.inject(GameService), 'submitSurvey')
      .mockReturnValue(of({ submitted: true, answers: 1 }));
    const buttons = fixture.nativeElement.querySelectorAll('input[type="radio"]');
    const send = fixture.nativeElement.querySelector('.submit-survey') as HTMLButtonElement;
    expect(send.disabled).toBe(false); // Harapan Bot NPC boleh dilewati.

    buttons[2].click();
    fixture.detectChanges();
    await fixture.whenStable();
    const details = fixture.nativeElement.querySelector('textarea') as HTMLTextAreaElement;
    expect(details.maxLength).toBe(991);
    expect(buttons[2].checked).toBe(true);
    expect(send.disabled).toBe(true);
    form.submit();
    expect(submit).not.toHaveBeenCalled();

    details.value = '   ';
    details.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    expect(send.disabled).toBe(true);

    details.value = 'Lebih pintar membaca situasi';
    details.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    expect(send.disabled).toBe(false);
    form.submit();
    expect(submit).toHaveBeenLastCalledWith('ABC123', 'match-1', [
      { question_id: choice.id, text: 'Lainnya: Lebih pintar membaca situasi' },
    ]);

    buttons[0].click();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('textarea')).toBeNull();
    expect(buttons[2].checked).toBe(false);
    form.submit();
    expect(submit).toHaveBeenLastCalledWith('ABC123', 'match-1', [
      { question_id: choice.id, text: 'Lebih cepat' },
    ]);
  });

  // Pertanyaan wajib: Lainnya tanpa isian belum dianggap menjawab. Pilihan biasa tanpa opsi Lainnya
  // tidak pernah membuka isian, walau teksnya kebetulan diawali "Lainnya: ".
  it('requires other-choice details on mandatory questions only when the option exists', async () => {
    const base = { ...status.questions[1], kind: 'choice' as const, required: true };
    const withOther = { ...base, id: 7, options: ['Ya', 'Lainnya'] };
    const withoutOther = { ...base, id: 8, options: ['Ya', 'Tidak'] };
    const { fixture, form } = create({ ...status, questions: [withOther, withoutOther] });
    const radios = fixture.nativeElement.querySelectorAll('input[type="radio"]');
    const send = fixture.nativeElement.querySelector('.submit-survey') as HTMLButtonElement;
    radios[1].click(); // Lainnya
    radios[3].click(); // Tidak
    fixture.detectChanges();
    await fixture.whenStable();
    expect(send.disabled).toBe(true);
    const details = fixture.nativeElement.querySelectorAll('textarea');
    expect(details.length).toBe(1);
    details[0].value = 'Kadang-kadang';
    details[0].dispatchEvent(new Event('input'));
    fixture.detectChanges();
    expect(send.disabled).toBe(false);
    form.setText(withoutOther, 'Lainnya: bukan opsi');
    expect(form.isOtherSelected(withoutOther)).toBe(false);
  });
});
