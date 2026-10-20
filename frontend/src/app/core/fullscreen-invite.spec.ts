import { TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BootLoader } from './boot-loader';
import { FullscreenInvite } from './fullscreen-invite';
import { STORAGE } from './storage';

describe('FullscreenInvite', () => {
  const requestFullscreen = vi.fn<() => Promise<void>>();
  let enabled = true;

  beforeEach(() => {
    sessionStorage.clear();
    enabled = true;
    requestFullscreen.mockReset().mockResolvedValue(undefined);
    // JSDOM belum menyediakan Fullscreen API; simulasikan kemampuan browser.
    Object.defineProperties(document, {
      fullscreenEnabled: { configurable: true, get: () => enabled },
      fullscreenElement: { configurable: true, get: () => null },
    });
    Object.defineProperty(document.documentElement, 'requestFullscreen', {
      configurable: true,
      value: requestFullscreen,
    });
    TestBed.configureTestingModule({ imports: [FullscreenInvite] });
  });

  afterEach(() => {
    TestBed.resetTestingModule();
    sessionStorage.clear();
    Reflect.deleteProperty(document, 'fullscreenEnabled');
    Reflect.deleteProperty(document, 'fullscreenElement');
    Reflect.deleteProperty(document.documentElement, 'requestFullscreen');
  });

  async function render(loaderDone = true) {
    const fixture = TestBed.createComponent(FullscreenInvite);
    TestBed.inject(BootLoader).done.set(loaderDone);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    return fixture;
  }

  it('waits for the loading screen, then offers fullscreen once per tab', async () => {
    const fixture = await render(false);
    expect(fixture.nativeElement.querySelector('[role="dialog"]')).toBeNull();
    TestBed.inject(BootLoader).done.set(true);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[role="dialog"]')).toBeTruthy();

    (fixture.nativeElement.querySelector('.invite-enter') as HTMLButtonElement).click();
    fixture.detectChanges();
    expect(requestFullscreen).toHaveBeenCalledTimes(1);
    expect(fixture.nativeElement.querySelector('[role="dialog"]')).toBeNull();
    expect(sessionStorage.getItem(STORAGE.fullscreenAsked)).toBe('1');
  });

  it('stays hidden after "Nanti saja", in a new page of the same tab, or without the API', async () => {
    const fixture = await render();
    (fixture.nativeElement.querySelector('.invite-later') as HTMLButtonElement).click();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[role="dialog"]')).toBeNull();
    expect(requestFullscreen).not.toHaveBeenCalled();

    expect((await render()).nativeElement.querySelector('[role="dialog"]')).toBeNull();

    sessionStorage.clear();
    enabled = false;
    expect((await render()).nativeElement.querySelector('[role="dialog"]')).toBeNull();
  });
});
