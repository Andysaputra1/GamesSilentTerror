import { Room } from '../core/room.service';
import { STORAGE } from '../core/storage';

export const ROOM_CODE_REGEX = /^[A-F0-9]{6}$/;
export const ROOM_CODE_ERROR = 'Masukkan kode ruangan 6 karakter.';
export const DEFAULT_CAPACITY = 6;

/**
 * Validasi dan normalisasi kode ruangan.
 * @returns { valid: true, code: string } jika kode valid (sudah di-trim & uppercase)
 * @returns { valid: false, error: string } jika kode tidak valid
 */
export function validateRoomCode(
  code: string,
): { valid: true; code: string } | { valid: false; error: string } {
  const trimmed = code.trim().toUpperCase();
  if (!ROOM_CODE_REGEX.test(trimmed)) {
    return { valid: false, error: ROOM_CODE_ERROR };
  }
  return { valid: true, code: trimmed };
}

export function saveRoomSession(room: Room): void {
  sessionStorage.setItem(STORAGE.room, room.code);
  sessionStorage.setItem(STORAGE.roomSnapshot, JSON.stringify(room));
}
