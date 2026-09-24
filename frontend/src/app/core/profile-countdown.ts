// Target absolut WIB: sama pada perangkat dengan zona waktu berbeda.
export const PROFILE_COUNTDOWN_TARGET = Date.parse('2027-01-08T23:59:00+07:00');
const WIB_OFFSET = 7 * 60 * 60 * 1000;

export function profileCountdown(now: number): string[] {
  if (now >= PROFILE_COUNTDOWN_TARGET) return ['00', '00', '00', '00', '00'];
  const current = new Date(now + WIB_OFFSET);
  const target = new Date(PROFILE_COUNTDOWN_TARGET + WIB_OFFSET);
  let months =
    (target.getUTCFullYear() - current.getUTCFullYear()) * 12 +
    target.getUTCMonth() -
    current.getUTCMonth();
  // Bulan kalender, bukan asumsi setiap bulan selalu 30 hari; tanggal akhir dijepit bila perlu.
  const addMonths = (count: number) => {
    const year = current.getUTCFullYear(),
      month = current.getUTCMonth() + count;
    const lastDay = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
    return Date.UTC(
      year,
      month,
      Math.min(current.getUTCDate(), lastDay),
      current.getUTCHours(),
      current.getUTCMinutes(),
      current.getUTCSeconds(),
      current.getUTCMilliseconds(),
    );
  };
  if (addMonths(months) > target.getTime()) months--;
  let remaining = Math.max(0, Math.ceil((target.getTime() - addMonths(months)) / 1000));
  const days = Math.floor(remaining / 86400);
  remaining %= 86400;
  const hours = Math.floor(remaining / 3600);
  remaining %= 3600;
  return [months, days, hours, Math.floor(remaining / 60), remaining % 60].map((value) =>
    String(value).padStart(2, '0'),
  );
}
