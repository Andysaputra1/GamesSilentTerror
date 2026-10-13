import { isPlatformBrowser } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  Component,
  DestroyRef,
  ElementRef,
  HostListener,
  Inject,
  OnDestroy,
  OnInit,
  PLATFORM_ID,
  ViewChild,
} from '@angular/core';
import { RouterLink } from '@angular/router';
import { Router } from '@angular/router';
import { finalize } from 'rxjs';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ProfileMenu } from '../../core/profile-menu';
import { RoleRevealCard } from '../../core/role-reveal-card/role-reveal-card';
import { RoomService } from '../../core/room.service';
import { validateRoomCode, saveRoomSession, DEFAULT_CAPACITY } from '../../shared/room-helpers';

type RoleId = 'hitman' | 'spy' | 'stalker' | 'civilian';

interface RoleCardPreview {
  id: RoleId;
  label: string;
  description: string;
}

interface SkinPreview {
  id: string;
  label: string;
}

type CaseFileTab = 'phases' | 'roles' | 'win';
type SkinTransitionState = 'idle' | 'out' | 'in';

interface CaseFileTabOption {
  id: CaseFileTab;
  label: string;
}

@Component({
  selector: 'app-main-page',
  imports: [RouterLink, ProfileMenu, RoleRevealCard, FormsModule],
  templateUrl: './main-page.html',
  styleUrls: ['./main-page.css', './main-page-case-file.css'],
})
export class MainPage implements OnInit, OnDestroy {
  username = 'guest';
  caseFileOpen = false;
  activeCaseTab: CaseFileTab = 'phases';

  // Room action state
  capacity = DEFAULT_CAPACITY;
  createSetupOpen = false;
  joinMode = false;
  joinCode = '';
  error = '';
  busy = false;

  roleDeck: RoleCardPreview[] = [
    {
      id: 'hitman',
      label: 'Hitman',
      description: 'Kuasai malam dengan menyandera warga, lalu bungkam mereka saat siang.',
    },
    {
      id: 'stalker',
      label: 'Stalker',
      description: 'Intai identitas pemain secara privat untuk membaca siapa yang bersembunyi.',
    },
    {
      id: 'spy',
      label: 'Spy',
      description: 'Lindungi satu pemain dari aksi malam dan pilih targetmu dengan cermat.',
    },
    {
      id: 'civilian',
      label: 'Civilian',
      description: 'Tanpa aksi malam—baca alibi, bangun kepercayaan, lalu gunakan suaramu.',
    },
  ];
  readonly previewSkins: readonly SkinPreview[] = [
    { id: 'sadie', label: 'Sadie' },
    { id: 'kiera', label: 'Kiera' },
    { id: 'eloise', label: 'Eloise' },
    { id: 'jenny', label: 'Jenny' },
    { id: 'arthur', label: 'Arthur' },
    { id: 'dexter', label: 'Dexter' },
  ];
  readonly capacities = [4, 5, 6, 7, 8, 9, 10] as const;
  deckAnnouncement = '';

  readonly caseFileTabs: readonly CaseFileTabOption[] = [
    { id: 'phases', label: 'Tiga fase' },
    { id: 'roles', label: 'Role' },
    { id: 'win', label: 'Kondisi menang' },
  ];

  private lastFocusedElement?: HTMLElement;
  private roleDeckShuffleTimer?: ReturnType<typeof setInterval>;
  private skinFadeTimer?: ReturnType<typeof setTimeout>;
  private skinRevealTimer?: ReturnType<typeof setTimeout>;
  private activeSkinIndex = 0;
  skinTransitionState: SkinTransitionState = 'idle';

  @ViewChild('caseFileDialog') private caseFileDialog?: ElementRef<HTMLElement>;

  @ViewChild('caseFileClose')
  set caseFileClose(button: ElementRef<HTMLButtonElement> | undefined) {
    if (!button || !isPlatformBrowser(this.platformId)) return;
    queueMicrotask(() => button.nativeElement.focus());
  }

  constructor(
    @Inject(PLATFORM_ID) private readonly platformId: object,
    private readonly router: Router,
    private readonly rooms: RoomService,
    private readonly destroy: DestroyRef,
  ) {}

  ngOnInit(): void {
    if (!isPlatformBrowser(this.platformId)) return;
    try {
      const storedUser = localStorage.getItem('shadow_heist_user');
      const user = storedUser ? (JSON.parse(storedUser) as { username?: string }) : null;
      this.username = user?.username || this.username;
    } catch {}
    this.startRoleDeckShuffle();
  }

  ngOnDestroy(): void {
    this.stopRoleDeckShuffle();
    this.stopSkinTransition();
  }

  get activeRole(): RoleCardPreview {
    return this.roleDeck[0]!;
  }

  get activeSkin(): SkinPreview {
    return this.previewSkins[this.activeSkinIndex]!;
  }

  cycleRoleDeckSkin(): void {
    if (this.skinTransitionState !== 'idle') return;

    if (this.prefersReducedMotion()) {
      this.advanceSkin();
      return;
    }

    this.skinTransitionState = 'out';
    this.skinFadeTimer = setTimeout(() => {
      this.skinFadeTimer = undefined;
      this.advanceSkin();
      this.skinTransitionState = 'in';
      this.skinRevealTimer = setTimeout(() => {
        this.skinRevealTimer = undefined;
        this.skinTransitionState = 'idle';
      }, 280);
    }, 160);
  }

  private advanceSkin(): void {
    this.activeSkinIndex = (this.activeSkinIndex + 1) % this.previewSkins.length;
    this.deckAnnouncement = `Skin karakter diganti ke ${this.activeSkin.label}.`;
  }

  private prefersReducedMotion(): boolean {
    return isPlatformBrowser(this.platformId) && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  private stopSkinTransition(): void {
    if (this.skinFadeTimer) clearTimeout(this.skinFadeTimer);
    if (this.skinRevealTimer) clearTimeout(this.skinRevealTimer);
    this.skinFadeTimer = undefined;
    this.skinRevealTimer = undefined;
    this.skinTransitionState = 'idle';
  }

  shuffleRoleDeck(direction: 'previous' | 'next'): void {
    this.rotateRoleDeck(direction);
    this.deckAnnouncement = `Kartu ${this.activeRole.label} sekarang di depan.`;
    this.startRoleDeckShuffle();
  }

  private rotateRoleDeck(direction: 'previous' | 'next'): void {
    if (this.roleDeck.length < 2) return;

    if (direction === 'next') {
      this.roleDeck = [...this.roleDeck.slice(1), this.roleDeck[0]!];
      return;
    }

    this.roleDeck = [this.roleDeck[this.roleDeck.length - 1]!, ...this.roleDeck.slice(0, -1)];
  }

  private startRoleDeckShuffle(): void {
    this.stopRoleDeckShuffle();
    this.roleDeckShuffleTimer = setInterval(() => {
      this.rotateRoleDeck('next');
      this.deckAnnouncement = '';
    }, 3000);
  }

  private stopRoleDeckShuffle(): void {
    if (!this.roleDeckShuffleTimer) return;
    clearInterval(this.roleDeckShuffleTimer);
    this.roleDeckShuffleTimer = undefined;
  }

  openCaseFile(event: Event): void {
    const trigger = event.currentTarget;
    if (trigger instanceof HTMLElement) this.lastFocusedElement = trigger;
    this.caseFileOpen = true;
  }

  closeCaseFile(): void {
    if (!this.caseFileOpen) return;
    this.caseFileOpen = false;

    if (isPlatformBrowser(this.platformId) && this.lastFocusedElement) {
      queueMicrotask(() => this.lastFocusedElement?.focus());
    }
  }

  openCreateSetup(): void {
    if (this.busy) return;
    this.error = '';
    this.createSetupOpen = true;
  }

  cancelCreateSetup(): void {
    if (this.busy) return;
    this.error = '';
    this.createSetupOpen = false;
  }

  selectCaseTab(tab: CaseFileTab): void {
    this.activeCaseTab = tab;
  }

  @HostListener('document:keydown.escape', ['$event'])
  closeCaseFileWithEscape(event: Event): void {
    if (!this.caseFileOpen) return;
    event.preventDefault();
    this.closeCaseFile();
  }

  onTabKeydown(event: KeyboardEvent, currentIndex: number): void {
    let nextIndex: number | undefined;

    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
      nextIndex = (currentIndex + 1) % this.caseFileTabs.length;
    } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
      nextIndex = (currentIndex - 1 + this.caseFileTabs.length) % this.caseFileTabs.length;
    } else if (event.key === 'Home') {
      nextIndex = 0;
    } else if (event.key === 'End') {
      nextIndex = this.caseFileTabs.length - 1;
    }

    if (nextIndex === undefined) return;
    event.preventDefault();
    const nextTab = this.caseFileTabs[nextIndex];
    this.selectCaseTab(nextTab.id);

    if (isPlatformBrowser(this.platformId)) {
      queueMicrotask(() => document.getElementById(`case-file-tab-${nextTab.id}`)?.focus());
    }
  }

  onDialogKeydown(event: KeyboardEvent): void {
    if (event.key !== 'Tab') return;

    const dialog = this.caseFileDialog?.nativeElement;
    if (!dialog) return;

    const focusable = Array.from(
      dialog.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [href], [tabindex]:not([tabindex="-1"]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])',
      ),
    );
    if (!focusable.length) return;

    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const target = event.target as HTMLElement | null;

    if (event.shiftKey && (target === first || !dialog.contains(target))) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && (target === last || !dialog.contains(target))) {
      event.preventDefault();
      first.focus();
    }
  }

  // Create room handler
  onCreateRoom(): void {
    if (this.busy) return;
    this.busy = true;
    this.error = '';

    this.rooms.request('POST', '', { capacity: this.capacity })
      .pipe(
        takeUntilDestroyed(this.destroy),
        finalize(() => { this.busy = false; }),
      )
      .subscribe({
        next: (room) => {
          saveRoomSession(room);
          void this.router.navigateByUrl('/lobby');
        },
        error: (err: HttpErrorResponse) => {
          this.error = err.error?.detail || 'Gagal membuat ruangan.';
        },
      });
  }

  // Join room handler
  onJoinRoom(): void {
    if (this.busy) return;

    const result = validateRoomCode(this.joinCode);
    if (!result.valid) {
      this.error = result.error;
      return;
    }

    this.busy = true;
    this.error = '';

    this.rooms.request('POST', '/join', { code: result.code })
      .pipe(
        takeUntilDestroyed(this.destroy),
        finalize(() => { this.busy = false; }),
      )
      .subscribe({
        next: (room) => {
          saveRoomSession(room);
          void this.router.navigateByUrl('/lobby');
        },
        error: (err: HttpErrorResponse) => {
          this.error = err.error?.detail || 'Gagal bergabung ke ruangan.';
        },
      });
  }

  // Toggle join mode
  toggleJoinMode(): void {
    this.joinMode = !this.joinMode;
    if (!this.joinMode) {
      this.joinCode = '';
      this.error = '';
    }
  }
}
