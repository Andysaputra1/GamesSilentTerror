import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { MainPage } from './main-page';

// TEST SUITE: kelompok pengujian otomatis, bukan logika yang dijalankan halaman production.
// Callback () => { ... } berisi setup dan skenario yang dipanggil oleh test runner.
describe('MainPage', () => {
  // INSTANCE TES: component adalah class halaman; fixture membungkus komponen untuk pengujian.
  let component: MainPage;
  let fixture: ComponentFixture<MainPage>;

  // SETUP CALLBACK: siapkan lingkungan/instance baru sebelum setiap skenario tes.
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [MainPage],
      providers: [provideRouter([])],
    }).compileComponents();

    fixture = TestBed.createComponent(MainPage);
    component = fixture.componentInstance;
    await fixture.whenStable();
  });

  // TES: pastikan komponen halaman dapat dibuat; belum menguji seluruh interaksinya.
  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
