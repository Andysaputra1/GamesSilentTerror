import { TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FullscreenPrompt } from './fullscreen-prompt';

describe('FullscreenPrompt', () => {
  const requestFullscreen = vi.fn<() => Promise<void>>();

  beforeEach(() => {
    requestFullscreen.mockReset().mockResolvedValue(undefined);
    // JSDOM belum menyediakan Fullscreen API; simulasikan kemampuan browser.
    Object.defineProperties(document, {
      fullscreenEnabled: { configurable: true, get: () => true },
      fullscreenElement: { configurable: true, get: () => null },
    });
    Object.defineProperty(document.documentElement, 'requestFullscreen', {
      configurable: true,
      value: requestFullscreen,
    });
    TestBed.configureTestingModule({ imports: [FullscreenPrompt] });
  });

  afterEach(() => {
    TestBed.resetTestingModule();
    vi.restoreAllMocks();
    Reflect.deleteProperty(document, 'fullscreenEnabled');
    Reflect.deleteProperty(document, 'fullscreenElement');
    Reflect.deleteProperty(document.documentElement, 'requestFullscreen');
  });

  it('waits for an explicit click and requests fullscreen on the persistent root', async () => {
    const fixture = TestBed.createComponent(FullscreenPrompt);
    fixture.detectChanges();
    await fixture.whenStable();
    expect(requestFullscreen).not.toHaveBeenCalled();
    const button: HTMLButtonElement = fixture.nativeElement.querySelector('.fullscreen-enter');
    expect(button).not.toBeNull();
    button.click();
    expect(requestFullscreen).toHaveBeenCalledTimes(1);
    await fixture.whenStable();
    expect(fixture.componentInstance.visible()).toBe(false);
    document.dispatchEvent(new Event('fullscreenchange'));
    expect(fixture.componentInstance.visible()).toBe(false);
  });

  it('lets the user dismiss the prompt without entering fullscreen', async () => {
    const fixture = TestBed.createComponent(FullscreenPrompt);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.nativeElement.querySelector('.fullscreen-later').click();
    expect(fixture.componentInstance.visible()).toBe(false);
    expect(requestFullscreen).not.toHaveBeenCalled();
  });

  it('keeps the page usable and allows retry when the browser rejects fullscreen', async () => {
    requestFullscreen.mockRejectedValueOnce(new Error('Permission denied'));
    const fixture = TestBed.createComponent(FullscreenPrompt);
    fixture.detectChanges();
    await fixture.whenStable();
    await fixture.componentInstance.enterFullscreen();
    expect(fixture.componentInstance.visible()).toBe(true);
    expect(fixture.componentInstance.pending()).toBe(false);
    expect(fixture.componentInstance.error()).toContain('Coba lagi');
    await fixture.componentInstance.enterFullscreen();
    expect(requestFullscreen).toHaveBeenCalledTimes(2);
    expect(fixture.componentInstance.visible()).toBe(false);
  });

  it('does not offer fullscreen when the browser does not support it', async () => {
    vi.spyOn(document, 'fullscreenEnabled', 'get').mockReturnValue(false);
    const fixture = TestBed.createComponent(FullscreenPrompt);
    fixture.detectChanges();
    await fixture.whenStable();
    expect(fixture.nativeElement.querySelector('aside')).toBeNull();
    expect(requestFullscreen).not.toHaveBeenCalled();
  });
});
