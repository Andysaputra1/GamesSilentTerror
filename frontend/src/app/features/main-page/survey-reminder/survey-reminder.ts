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

const REMINDER_LIFETIME_MS = 7 * 24 * 60 * 60 * 1000;
const FINISHED_DATE_FORMAT = new Intl.DateTimeFormat('id-ID', {
  dateStyle: 'medium',
  timeStyle: 'short',
  timeZone: 'Asia/Jakarta',
});

interface DatedSurvey extends PendingSurvey {
  finishedLabel: string;
  expiresAt: number;
}

// PENGINGAT SURVEI di atas binder Main: satu baris per pertandingan selesai yang surveinya belum diisi.
// Tombol X hanya menyembunyikan untuk kunjungan ini; setiap kali Main dibuka daftar diambil ulang dari
// server. Pengingat berhenti setelah survei terkirim atau pertandingan lewat tujuh hari.
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

  private expiryTimer?: ReturnType<typeof setTimeout>;

  pending: DatedSurvey[] = [];
  dismissed = false;

  // Pop-up survei untuk satu pertandingan.
  active: DatedSurvey | null = null;
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
    this.destroy.onDestroy(() => clearTimeout(this.expiryTimer));
    afterNextRender(() =>
      this.api
        .pendingSurveys()
        .pipe(takeUntilDestroyed(this.destroy))
        .subscribe({
          next: (pending) => {
            this.pending = pending.flatMap((item) => {
              // MySQL menyimpan UTC; respons lama belum menyertakan penanda zona waktunya.
              const raw = item.finished_at.trim();
              const finishedAt = Date.parse(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw) ? raw : raw + 'Z');
              if (!Number.isFinite(finishedAt)) return [];
              return [
                {
                  ...item,
                  finished_at: new Date(finishedAt).toISOString(),
                  finishedLabel: FINISHED_DATE_FORMAT.format(finishedAt) + ' WIB',
                  expiresAt: finishedAt + REMINDER_LIFETIME_MS,
                },
              ];
            });
            this.expireReminders();
          },
          error: () => {},
        }),
    );
  }

  // Timer mengikuti pengingat terdekat agar daftar ikut hilang tanpa perlu memuat ulang halaman.
  private expireReminders(): void {
    clearTimeout(this.expiryTimer);
    const now = Date.now();
    this.pending = this.pending.filter((item) => now <= item.expiresAt);
    if (this.active && now > this.active.expiresAt) this.close();
    if (this.pending.length) {
      const nextExpiry = Math.min(...this.pending.map((item) => item.expiresAt));
      this.expiryTimer = setTimeout(
        () => this.expireReminders(),
        Math.min(nextExpiry - now + 1, 2_147_483_647),
      );
    }
    this.cdr.markForCheck();
  }

  open(item: DatedSurvey): void {
    this.expireReminders();
    if (Date.now() > item.expiresAt) return;
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
    this.expireReminders();
  }

  @HostListener('document:keydown.escape')
  close(): void {
    this.active = null;
    this.survey = null;
  }
}
