import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { PLATFORM_ID } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';

import { Auth } from './auth';

describe('Auth', () => {
  let component: Auth;
  let fixture: ComponentFixture<Auth>;
  let httpMock: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [Auth],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: PLATFORM_ID, useValue: 'browser' },
        { provide: Router, useValue: { navigateByUrl: () => Promise.resolve(true) } },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(Auth);
    component = fixture.componentInstance;
    httpMock = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
  });

  afterEach(() => httpMock.verify());

  it('creates', () => {
    expect(component).toBeTruthy();
  });

  it('keeps the form usable after an invalid-password response', () => {
    component.username = 'user1';
    component.password = 'wrong-password';
    component.submit();

    expect(component.isSubmitting).toBe(true);
    const request = httpMock.expectOne('http://localhost:8000/api/auth/login');
    expect(request.request.method).toBe('POST');
    request.flush({ detail: 'Username atau password tidak valid.' }, {
      status: 401,
      statusText: 'Unauthorized',
    });

    expect(component.isSubmitting).toBe(false);
    expect(component.errorMessage).toBe('USERNAME ATAU PASSWORD SALAH.');
  });

  it('shows validation feedback without starting a request', () => {
    component.submit();

    expect(component.isSubmitting).toBe(false);
    expect(component.errorMessage).toBe('MASUKKAN USERNAME DAN PASSWORD TERLEBIH DAHULU.');
    httpMock.expectNone('http://localhost:8000/api/auth/login');
  });
});
