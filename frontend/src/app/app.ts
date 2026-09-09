import { Component, signal } from '@angular/core';
import { RouterOutlet } from '@angular/router';

// DECORATOR: hubungkan komponen dengan selector HTML, template, dan fitur router.
@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet],
  templateUrl: './app.html',
})
// CLASS KOMPONEN: wadah utama halaman; router-outlet di app.html menampilkan route aktif.
export class App {
  // PROPERTY SIGNAL: nilai reaktif; perubahan melalui API signal dapat memperbarui tampilan.
  protected readonly title = signal('frontend');
}
