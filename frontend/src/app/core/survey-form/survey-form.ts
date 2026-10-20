import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectorRef,
  Component,
  DestroyRef,
  EventEmitter,
  inject,
  Input,
  Output,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { finalize } from 'rxjs';
import { GameService, SurveyQuestion, SurveyStatus } from '../game.service';

// FORMULIR SURVEI AKHIR: pertanyaan, jenis jawaban, dan skala dari backend; pertanyaan wajib harus diisi
// sebelum kirim. Dipakai layar akhir pertandingan dan pengingat survei di Main; pemanggil yang
// menampilkan ucapan terima kasih setelah event `submitted`.
@Component({
  selector: 'app-survey-form',
  imports: [FormsModule],
  templateUrl: './survey-form.html',
  styleUrl: './survey-form.css',
})
export class SurveyForm {
  private readonly api = inject(GameService);
  private readonly cdr = inject(ChangeDetectorRef);
  private readonly destroy = inject(DestroyRef);

  @Input({ required: true }) code = '';
  @Input({ required: true }) survey!: SurveyStatus;
  // Survei tersimpan (atau ternyata sudah pernah dikirim dari tab lain: 409).
  @Output() readonly submitted = new EventEmitter<void>();

  answers: Record<number, { value?: number; text?: string }> = {};
  sending = false;
  error = '';

  // Skala min..maks untuk pertanyaan bintang/angka.
  scaleValues(question: SurveyQuestion): number[] {
    return Array.from(
      { length: question.scale_max - question.scale_min + 1 },
      (_, index) => question.scale_min + index,
    );
  }

  // Bintang menyala sampai nilai terpilih; skala angka hanya menandai nilai terpilih.
  isSelected(question: SurveyQuestion, value: number): boolean {
    const chosen = this.answers[question.id]?.value;
    if (chosen === undefined) return false;
    return question.kind === 'stars' ? value <= chosen : value === chosen;
  }

  setAnswer(question: SurveyQuestion, value: number): void {
    this.answers = { ...this.answers, [question.id]: { value } };
  }

  setText(question: SurveyQuestion, text: string): void {
    this.answers = { ...this.answers, [question.id]: { text } };
  }

  // Tombol kirim aktif setelah semua pertanyaan wajib dijawab.
  get complete(): boolean {
    return this.survey.questions.every((question) => {
      const answer = this.answers[question.id];
      if (!question.required) return true;
      return question.kind === 'stars' || question.kind === 'scale'
        ? answer?.value !== undefined
        : !!answer?.text?.trim();
    });
  }

  // Kirim sekali; skala dan pertanyaan wajib divalidasi ulang di backend.
  submit(): void {
    if (!this.complete || this.sending) return;
    const answers = this.survey.questions
      .filter((question) => this.answers[question.id])
      .map((question) => ({ question_id: question.id, ...this.answers[question.id] }));
    this.sending = true;
    this.error = '';
    this.api
      .submitSurvey(this.code, this.survey.match_id, answers)
      .pipe(
        takeUntilDestroyed(this.destroy),
        finalize(() => {
          this.sending = false;
          this.cdr.markForCheck();
        }),
      )
      .subscribe({
        next: () => this.submitted.emit(),
        error: (error: HttpErrorResponse) => {
          // 409 = sudah pernah dikirim dari tab lain; anggap selesai.
          if (error.status === 409) return this.submitted.emit();
          this.error =
            typeof error.error?.detail === 'string'
              ? error.error.detail
              : 'Survei gagal dikirim. Coba lagi.';
        },
      });
  }
}
