import { backendUrl } from '../../core/backend-url';
import { isPlatformBrowser, DatePipe, JsonPipe } from '@angular/common';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import {
  Component,
  ChangeDetectorRef,
  DestroyRef,
  Inject,
  OnInit,
  OnDestroy,
  PLATFORM_ID,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { finalize, timeout } from 'rxjs';

// INTERFACE: satu jejak proses backend; null berarti tahap belum berjalan/tidak tersedia.
interface Trace {
  id: string;
  created_at: string;
  sender: string;
  message: string;
  stage: string;
  intent: string | null;
  aggressiveness_before: number | null;
  intent_weight: number | null;
  aggressiveness: number | null;
  silence_percentage: number;
  suspicion_score: number | null;
  suspicion_status: string | null;
  provider: string | null;
  model: string | null;
  prompt: string | null;
  output: string | null;
  llm_error: string | null;
  error: string | null;
  message_id: number | null;
}

// CLASS KOMPONEN: monitor read-only untuk development; tidak memanggil AI ulang.
@Component({
  selector: 'app-checker',
  imports: [FormsModule, RouterLink, DatePipe, JsonPipe],
  templateUrl: './checker.html',
  styleUrl: './checker.css',
})
export class Checker implements OnInit, OnDestroy {
  code = '';
  activeCode = '';
  error = '';
  busy = false;
  autoRefresh = true;
  traces: Trace[] = [];
  selectedId = '';
  updatedAt: Date | null = null;
  private timer?: ReturnType<typeof setInterval>;

  // Sediakan HTTP, parameter route, dan lifecycle untuk pembacaan jejak ruangan.
  constructor(
    private readonly http: HttpClient,
    private readonly route: ActivatedRoute,
    private readonly cdr: ChangeDetectorRef,
    private readonly destroy: DestroyRef,
    @Inject(PLATFORM_ID) private readonly platformId: object,
  ) {}

  // LIFECYCLE: pilih ruangan dari query URL/storage lalu polling tanpa menumpuk request.
  ngOnInit(): void {
    if (!isPlatformBrowser(this.platformId)) return;
    this.code =
      this.route.snapshot.queryParamMap.get('room') ??
      sessionStorage.getItem('shadow_heist_room') ??
      '';
    if (this.code) this.watchRoom();
    this.timer = setInterval(() => {
      if (this.autoRefresh && this.activeCode && !this.busy) this.refresh();
    }, 2000);
  }

  // Hentikan polling ketika halaman checker dilepas.
  ngOnDestroy(): void {
    if (this.timer) clearInterval(this.timer);
  }

  // GETTER: pertahankan pesan yang dipilih meskipun pesan baru tiba lewat polling.
  get selected(): Trace | undefined {
    return this.traces.find((trace) => trace.id === this.selectedId);
  }

  // Validasi kode ruangan, reset pilihan lama, lalu ambil snapshot checker.
  watchRoom(): void {
    if (this.busy) return;
    const normalized = this.code.trim().toUpperCase();
    if (!/^[A-F0-9]{6}$/.test(normalized)) {
      this.error = 'Masukkan kode ruangan 6 karakter.';
      return;
    }
    this.activeCode = normalized;
    this.traces = [];
    this.selectedId = '';
    this.updatedAt = null;
    this.refresh();
  }

  // METHOD: baca snapshot backend saja; prompt tidak direkonstruksi oleh frontend.
  refresh(): void {
    if (!this.activeCode || this.busy) return;
    this.busy = true;
    const url = `${backendUrl()}/api/rooms/${this.activeCode}/checker`;
    this.http
      .get<{ traces: Trace[] }>(url)
      .pipe(
        timeout(10000),
        takeUntilDestroyed(this.destroy),
        finalize(() => {
          this.busy = false;
          this.cdr.markForCheck();
        }),
      )
      .subscribe({
        next: (data) => {
          this.traces = data.traces;
          this.error = '';
          this.updatedAt = new Date();
          if (!this.traces.some((trace) => trace.id === this.selectedId))
            this.selectedId = this.traces[0]?.id ?? '';
        },
        error: (error: HttpErrorResponse) => {
          this.error =
            error.error?.detail ||
            'Monitor gagal diperbarui. Data sebelumnya mungkin sudah kedaluwarsa.';
        },
      });
  }
}
