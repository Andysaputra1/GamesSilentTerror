import { HttpErrorResponse } from '@angular/common/http';

// Syarat lokal nama tampilan yang sama dengan server: wajib memuat huruf atau angka (mis. bukan hanya emoji).
// Daftar kata ganti dan istilah game yang dilarang hanya ada di server (schemas/auth.py), jadi tidak disalin ke sini.
export function namaTampilanBerhuruf(nama: string): boolean {
  return /[\p{L}\p{N}]/u.test(nama);
}

// Pesan penolakan nama tampilan dari server: respons 422 dengan `detail[].msg` untuk kolom display_name, tanpa awalan
// "Value error, " dari Pydantic. Null bila error bukan penolakan nama tampilan.
export function pesanNamaTampilanDitolak(error: unknown): string | null {
  if (!(error instanceof HttpErrorResponse) || error.status !== 422) return null;
  const daftarGalat: unknown = error.error?.detail;
  if (!Array.isArray(daftarGalat)) return null;
  const galat = daftarGalat.find(
    (item) => Array.isArray(item?.loc) && item.loc.includes('display_name'),
  );
  return typeof galat?.msg === 'string' ? galat.msg.replace(/^Value error, /, '') : null;
}
