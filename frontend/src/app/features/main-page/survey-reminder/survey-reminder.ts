import { HttpErrorResponse } from '@angular/common/http';
import {
  afterNextRender,
  ChangeDetectorRef,
  Component,
  DestroyRef,
  ElementRef,
  HostListener,
  inject,
  ViewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { GameService, PendingSurvey, SurveyStatus } from '../../../core/game.service';
import { SurveyForm } from '../../../core/survey-form/survey-form';

// PENGINGAT SURVEI di atas binder Main: satu baris per pertandingan selesai yang surveinya belum diisi.
// Tombol X hanya menyembunyikan untuk kunjungan ini; setiap kali Main dibuka daftar diambil ulang dari
// server, jadi pengingat muncul lagi sampai semua survei terkirim.
@Component({
  selector: 'app-survey-reminder',
  imports: [SurveyForm],
  templateUrl: './survey-reminder.html',
  styleUrl: './survey-reminder.css',
})
export class SurveyReminder {
  private readonly api = inject(GameService);
  private readonly cdr = inject(ChangeDetectorRef);
  private readonly destroy = inject(DestroyRef);

  pending: PendingSurvey[] = [];
  dismissed = false;

  // Pop-up survei untuk satu pertandingan.
  active: PendingSurvey | null = null;
  survey: SurveyStatus | null = null;
  state: 'loading' | 'ready' | 'done' | 'error' = 'loading';
  error = '';

  readonly roleLabel: Partial<Record<string, string>> = {
    hitman: 'Hitman',
    spy: 'Spy',
    stalker: 'Stalker',
    civilian: 'Civilian',
  };

  @ViewChild('closeButton') set closeButton(button: ElementRef<HTMLButtonElement> | undefined) {
    if (button) queueMicrotask(() => button.nativeElement.focus());
  }

  // Hanya di browser (token ada di localStorage, tidak tersedia saat prerender). Gagal memuat
  // (mis. server lama tanpa endpoint ini) cukup tanpa pengingat.
  constructor() {
    afterNextRender(() =>
      this.api
        .pendingSurveys()
        .pipe(takeUntilDestroyed(this.destroy))
        .subscribe({
          next: (pending) => {
            this.pending = pending;
            this.cdr.markForCheck();
          },
          error: () => {},
        }),
    );
  }

  open(item: PendingSurvey): void {
    this.active = item;
    this.survey = null;
    this.state = 'loading';
    this.error = '';
    this.api
      .survey(item.room_code, item.match_id)
      .pipe(takeUntilDestroyed(this.destroy))
      .subscribe({
        next: (survey) => {
          if (survey.submitted || !survey.questions.length) {
            this.finish();
          } else {
            this.survey = survey;
            this.state = 'ready';
          }
          this.cdr.markForCheck();
        },
        error: (error: HttpErrorResponse) => {
          this.state = 'error';
          this.error =
            typeof error.error?.detail === 'string'
              ? error.error.detail
              : 'Survei belum bisa dimuat. Coba lagi nanti.';
          this.cdr.markForCheck();
        },
      });
  }

  // Survei terkirim (atau ternyata sudah pernah dikirim): pertandingan itu hilang dari daftar.
  finish(): void {
    const done = this.active;
    this.pending = this.pending.filter((item) => item.match_id !== done?.match_id);
    this.state = 'done';
  }

  @HostListener('document:keydown.escape')
  close(): void {
    this.active = null;
    this.survey = null;
  }
}
