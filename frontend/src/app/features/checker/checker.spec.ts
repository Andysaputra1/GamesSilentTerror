import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { Checker } from './checker';

// TEST SUITE: checker development membaca data tanpa mengirim token atau memanggil AI.
describe('Checker', () => {
  let component: Checker;
  let http: HttpTestingController;
  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [Checker],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    component = TestBed.createComponent(Checker).componentInstance;
    http = TestBed.inject(HttpTestingController);
  });
  afterEach(() => http.verify());

  it('rejects invalid room codes without making a request', () => {
    component.code = 'bad';
    component.watchRoom();
    expect(component.error).toContain('6 karakter');
    http.expectNone(() => true);
  });

  it('loads a room without an authorization header', () => {
    component.code = 'abc123';
    component.watchRoom();
    const request = http.expectOne('http://localhost:8000/api/rooms/ABC123/checker');
    expect(request.request.headers.has('Authorization')).toBe(false);
    request.flush({ traces: [] });
    expect(component.busy).toBe(false);
    expect(component.activeCode).toBe('ABC123');
    expect(component.updatedAt).not.toBeNull();
  });

  it('unlocks refresh and reports server failures', () => {
    component.code = 'ABC123';
    component.watchRoom();
    http
      .expectOne('http://localhost:8000/api/rooms/ABC123/checker')
      .flush({}, { status: 500, statusText: 'Error' });
    expect(component.busy).toBe(false);
    expect(component.error).toContain('gagal diperbarui');
  });
});
