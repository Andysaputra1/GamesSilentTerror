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

// Jawaban yang sedang diisi, per id pertanyaan: nilai skala/bintang atau teks (termasuk pilihan).
export type JawabanSurvei = Record<number, { value?: number; text?: string }>;

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
  private readonly changeDetector = inject(ChangeDetectorRef);
  private readonly destroyRef = inject(DestroyRef);

  @Input({ required: true }) code = '';
  @Input({ required: true }) survey!: SurveyStatus;
  // Survei tersimpan (atau ternyata sudah pernah dikirim dari tab lain: 409).
  @Output() readonly submitted = new EventEmitter<void>();
  // Jawaban bisa dipegang pemanggil lewat [(answers)], supaya isian tidak hilang saat formulir dilepas dan dibuat
  // lagi (layar akhir pindah ke "Lihat meja" lalu kembali).
  @Input() answers: JawabanSurvei = {};
  @Output() readonly answersChange = new EventEmitter<JawabanSurvei>();
  sending = false;
  error = '';
  // Pilihan yang membuka isian bebas (sama dengan PILIHAN_LAINNYA di backend). Jawabannya dikirim
  // sebagai "Lainnya: <isian>", jadi isian maksimal 1000 karakter dikurangi awalan itu.
  readonly otherOption = 'Lainnya';
  readonly otherPrefix = `${this.otherOption}: `;
  readonly otherMaxLength = 1000 - this.otherPrefix.length;

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

  private simpanJawaban(answers: JawabanSurvei): void {
    this.answers = answers;
    this.answersChange.emit(answers);
  }

  setAnswer(question: SurveyQuestion, value: number): void {
    this.simpanJawaban({ ...this.answers, [question.id]: { value } });
  }

  setText(question: SurveyQuestion, text: string): void {
    this.simpanJawaban({ ...this.answers, [question.id]: { text } });
  }

  // Pertanyaan opsional bisa dikosongkan lagi; radio dan skala tidak punya cara bawaan untuk itu.
  kosongkanJawaban(question: SurveyQuestion): void {
    const sisa = { ...this.answers };
    delete sisa[question.id];
    this.simpanJawaban(sisa);
  }

  // Opsi Lainnya memakai kolom teks yang sama, termasuk saat disimpan dan diekspor.
  setChoice(question: SurveyQuestion, option: string): void {
    this.setText(question, option === this.otherOption ? this.otherPrefix : option);
  }

  // Lainnya terpilih bila jawaban diawali "Lainnya: " dan pertanyaannya memang punya opsi itu.
  isOtherSelected(question: SurveyQuestion): boolean {
    return (
      question.kind === 'choice' &&
      question.options.includes(this.otherOption) &&
      !!this.answers[question.id]?.text?.startsWith(this.otherPrefix)
    );
  }

  // Isian bebas tanpa awalan "Lainnya: ", untuk textarea dan penghitung karakter.
  otherText(question: SurveyQuestion): string {
    return this.answers[question.id]?.text?.slice(this.otherPrefix.length) ?? '';
  }

  setOtherText(question: SurveyQuestion, text: string): void {
    this.setText(question, this.otherPrefix + text);
  }

  // Pertanyaan wajib harus dijawab. Lainnya yang isiannya masih kosong ditolak backend, jadi dianggap belum lengkap,
  // termasuk di pertanyaan opsional.
  private lengkap(question: SurveyQuestion): boolean {
    const answer = this.answers[question.id];
    if (this.isOtherSelected(question)) return !!this.otherText(question).trim();
    if (!question.required) return true;
    return question.kind === 'stars' || question.kind === 'scale'
      ? answer?.value !== undefined
      : !!answer?.text?.trim();
  }

  // Tombol kirim aktif setelah semua pertanyaan lengkap.
  get complete(): boolean {
    return this.survey.questions.every((question) => this.lengkap(question));
  }

  // Nomor urut pertanyaan yang belum lengkap, ditampilkan di dekat tombol kirim.
  get nomorBelumLengkap(): number[] {
    return this.survey.questions.flatMap((question, indeks) =>
      this.lengkap(question) ? [] : [indeks + 1],
    );
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
        takeUntilDestroyed(this.destroyRef),
        finalize(() => {
          this.sending = false;
          this.changeDetector.markForCheck();
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
