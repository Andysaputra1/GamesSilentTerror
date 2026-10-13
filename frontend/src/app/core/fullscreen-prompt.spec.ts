import { TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FullscreenPrompt } from './fullscreen-prompt';

describe('FullscreenPrompt', () => {
  const requestFullscreen = vi.fn<() => Promise<void>>();
  const exitFullscreen = vi.fn<() => Promise<void>>();
  let fullscreenElement: Element | null = null;

  beforeEach(() => {
    requestFullscreen.mockReset().mockImplementation(async () => {
      fullscreenElement = document.documentElement;
    });
    exitFullscreen.mockReset().mockImplementation(async () => {
      fullscreenElement = null;
    });
    fullscreenElement = null;
    // JSDOM belum menyediakan Fullscreen API; simulasikan kemampuan browser.
    Object.defineProperties(document, {
      fullscreenEnabled: { configurable: true, get: () => true },
      fullscreenElement: { configurable: true, get: () => fullscreenElement },
    });
    Object.defineProperty(document.documentElement, 'requestFullscreen', {
      configurable: true,
      value: requestFullscreen,
    });
    Object.defineProperty(document, 'exitFullscreen', {
      configurable: true,
      value: exitFullscreen,
    });
    TestBed.configureTestingModule({ imports: [FullscreenPrompt] });
  });

  afterEach(() => {
    TestBed.resetTestingModule();
    vi.restoreAllMocks();
    Reflect.deleteProperty(document, 'fullscreenEnabled');
    Reflect.deleteProperty(document, 'fullscreenElement');
    Reflect.deleteProperty(document.documentElement, 'requestFullscreen');
    Reflect.deleteProperty(document, 'exitFullscreen');
  });

  it('waits for an explicit click before requesting fullscreen on the persistent root', async () => {
    const fixture = TestBed.createComponent(FullscreenPrompt);
    fixture.detectChanges();
    await fixture.whenStable();
    expect(requestFullscreen).not.toHaveBeenCalled();
    const button: HTMLButtonElement = fixture.nativeElement.querySelector('.fullscreen-toggle');
    expect(button).not.toBeNull();
    button.click();
    await fixture.whenStable();
    expect(requestFullscreen).toHaveBeenCalledTimes(1);
    expect(fixture.componentInstance.active()).toBe(true);
    document.dispatchEvent(new Event('fullscreenchange'));
    expect(fixture.componentInstance.active()).toBe(true);
  });

  it('leaves fullscreen from the same optional control', async () => {
    const fixture = TestBed.createComponent(FullscreenPrompt);
    fixture.detectChanges();
    await fixture.whenStable();
    await fixture.componentInstance.toggleFullscreen();
    expect(fixture.componentInstance.active()).toBe(true);
    await fixture.componentInstance.toggleFullscreen();
    expect(exitFullscreen).toHaveBeenCalledTimes(1);
    expect(fixture.componentInstance.active()).toBe(false);
  });

  it('keeps the page usable and allows retry when the browser rejects fullscreen', async () => {
    requestFullscreen.mockRejectedValueOnce(new Error('Permission denied'));
    const fixture = TestBed.createComponent(FullscreenPrompt);
    fixture.detectChanges();
    await fixture.whenStable();
    await fixture.componentInstance.toggleFullscreen();
    expect(fixture.componentInstance.active()).toBe(false);
    expect(fixture.componentInstance.pending()).toBe(false);
    expect(fixture.componentInstance.error()).toContain('Coba lagi');
    await fixture.componentInstance.toggleFullscreen();
    expect(requestFullscreen).toHaveBeenCalledTimes(2);
    expect(fixture.componentInstance.active()).toBe(true);
  });

  it('does not offer fullscreen when the browser does not support it', async () => {
    vi.spyOn(document, 'fullscreenEnabled', 'get').mockReturnValue(false);
    const fixture = TestBed.createComponent(FullscreenPrompt);
    fixture.detectChanges();
    await fixture.whenStable();
    expect(fixture.nativeElement.querySelector('.fullscreen-toggle')).toBeNull();
    expect(requestFullscreen).not.toHaveBeenCalled();
  });
});
