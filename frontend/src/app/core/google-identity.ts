// ADAPTER GIS: muat library resmi hanya saat pengguna memilih login Google.
export interface GoogleIdentity {
  initialize(options: { client_id: string; nonce: string; auto_select: boolean;
    callback: (result: {credential: string}) => void }): void;
  renderButton(element: HTMLElement, options: {theme: string; size: string; type: string}): void;
}
type GoogleWindow = Window & {google?: {accounts: {id: GoogleIdentity}}};

export function loadGoogleIdentity(): Promise<GoogleIdentity> {
  const identity = (window as GoogleWindow).google?.accounts.id;
  if (identity) return Promise.resolve(identity);
  return new Promise((resolve, reject) => {
    const script = document.createElement('script');
    const timer = setTimeout(() => {
      script.remove();
      reject(new Error('Google terlalu lama merespons. Coba lagi.'));
    }, 12000);
    script.src = 'https://accounts.google.com/gsi/client';
    script.async = true;
    script.onload = () => {
      clearTimeout(timer);
      const loaded = (window as GoogleWindow).google?.accounts.id;
      if (loaded) resolve(loaded);
      else { script.remove(); reject(new Error('Library Google gagal dimuat.')); }
    };
    script.onerror = () => {
      clearTimeout(timer); script.remove();
      reject(new Error('Tidak bisa memuat Google. Periksa koneksi atau pemblokir browser.'));
    };
    document.head.append(script);
  });
}
