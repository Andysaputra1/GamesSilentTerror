import { isPlatformBrowser } from '@angular/common';
import { Component, Inject, OnInit, PLATFORM_ID } from '@angular/core';
import { RouterLink } from '@angular/router';
import { ProfileMenu } from '../../core/profile-menu';
import { RoleRevealCard } from '../../core/role-reveal-card/role-reveal-card';

interface RoleCardPreview {
  id: 'hitman' | 'spy' | 'stalker';
  skinId: string;
}

// DECORATOR: hubungkan MainPage dengan HTML/CSS dan aktifkan link navigasi Angular.
@Component({
  selector: 'app-main-page',
  imports: [RouterLink, ProfileMenu, RoleRevealCard],
  templateUrl: './main-page.html',
  styleUrl: './main-page.css',
})
// CLASS KOMPONEN: mengatur nama pengguna pada menu utama setelah login.
export class MainPage implements OnInit {
  // PROPERTY: nama yang ditampilkan; gunakan nilai awal jika storage tidak tersedia.
  username: string = 'guest';

  // Tiga kartu hanya menjadi ilustrasi deck; detail seluruh role tetap tersedia di field guide.
  readonly roleDeck: readonly RoleCardPreview[] = [
    { id: 'hitman', skinId: 'dexter' },
    { id: 'spy', skinId: 'kiera' },
    { id: 'stalker', skinId: 'arthur' },
  ];

  // CONSTRUCTOR: terima identitas platform untuk membedakan browser dan proses SSR.
  constructor(@Inject(PLATFORM_ID) private readonly platformId: object) {}

  // LIFECYCLE METHOD: dipanggil Angular setelah inisialisasi; baca profil hanya di browser.
  ngOnInit(): void {
    if (!isPlatformBrowser(this.platformId)) return;
    try {
      const storedUser = localStorage.getItem('shadow_heist_user');
      const user = storedUser ? (JSON.parse(storedUser) as { username?: string }) : null;
      this.username = user?.username || this.username;
    } catch {}
  }
}
