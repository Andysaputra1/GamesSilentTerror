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
  private readonly changeDetector = inject(ChangeDetectorRef);
  private readonly destroyRef = inject(DestroyRef);

  private expiryTimer?: ReturnType<typeof setTimeout>;

  pending: DatedSurvey[] = [];
  dismissed = false;

  // Pop-up survei untuk satu pertandingan.
  surveiDibuka: DatedSurvey | null = null;
  survey: SurveyStatus | null = null;
  statusDialog: 'loading' | 'ready' | 'done' | 'error' = 'loading';
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
    this.destroyRef.onDestroy(() => clearTimeout(this.expiryTimer));
    afterNextRender(() =>
      this.api
        .pendingSurveys()
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: (daftarSurvei) => {
            this.pending = daftarSurvei.flatMap((item) => {
              // MySQL menyimpan UTC; respons lama belum menyertakan penanda zona waktunya.
              const waktuServer = item.finished_at.trim();
              const finishedAt = Date.parse(
                /(?:Z|[+-]\d{2}:?\d{2})$/i.test(waktuServer) ? waktuServer : waktuServer + 'Z',
              );
              // Tanggal yang tidak terbaca: baris ini dilewati.
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
    if (this.surveiDibuka && now > this.surveiDibuka.expiresAt) this.tutupSurvei();
    if (this.pending.length) {
      const nextExpiry = Math.min(...this.pending.map((item) => item.expiresAt));
      // 2_147_483_647 ms adalah batas setTimeout; nilai yang lebih besar akan langsung berjalan.
      this.expiryTimer = setTimeout(
        () => this.expireReminders(),
        Math.min(nextExpiry - now + 1, 2_147_483_647),
      );
    }
    this.changeDetector.markForCheck();
  }

  bukaSurvei(item: DatedSurvey): void {
    this.expireReminders();
    if (Date.now() > item.expiresAt) return;
    this.surveiDibuka = item;
    this.survey = null;
    this.statusDialog = 'loading';
    this.error = '';
    this.api
      .survey(item.room_code, item.match_id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (survey) => {
          if (survey.submitted || !survey.questions.length) {
            this.tandaiSurveiSelesai();
          } else {
            this.survey = survey;
            this.statusDialog = 'ready';
          }
          this.changeDetector.markForCheck();
        },
        error: (error: HttpErrorResponse) => {
          this.statusDialog = 'error';
          this.error =
            typeof error.error?.detail === 'string'
              ? error.error.detail
              : 'Survei belum bisa dimuat. Coba lagi nanti.';
          this.changeDetector.markForCheck();
        },
      });
  }

  // Survei terkirim (atau ternyata sudah pernah dikirim): pertandingan itu hilang dari daftar.
  tandaiSurveiSelesai(): void {
    const surveiSelesai = this.surveiDibuka;
    this.pending = this.pending.filter((item) => item.match_id !== surveiSelesai?.match_id);
    this.statusDialog = 'done';
    this.expireReminders();
  }

  @HostListener('document:keydown.escape')
  tutupSurvei(): void {
    this.surveiDibuka = null;
    this.survey = null;
  }
}
