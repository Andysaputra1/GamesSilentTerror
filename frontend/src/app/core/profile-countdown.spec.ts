import { profileCountdown, PROFILE_COUNTDOWN_TARGET } from './profile-countdown';

describe('profile countdown in WIB', () => {
  it('uses calendar months and the exact January deadline', () => {
    expect(profileCountdown(Date.parse('2026-09-24T23:59:00+07:00'))).toEqual([
      '03',
      '14',
      '00',
      '00',
      '00',
    ]);
    expect(profileCountdown(Date.parse('2026-12-07T23:59:00+07:00'))).toEqual([
      '01',
      '00',
      '00',
      '00',
      '00',
    ]);
  });
  it('counts the last seconds and clamps to zero at and after the target', () => {
    expect(profileCountdown(PROFILE_COUNTDOWN_TARGET - 61000)).toEqual([
      '00',
      '00',
      '00',
      '01',
      '01',
    ]);
    expect(profileCountdown(PROFILE_COUNTDOWN_TARGET - 1)).toEqual(['00', '00', '00', '00', '01']);
    for (const now of [PROFILE_COUNTDOWN_TARGET, PROFILE_COUNTDOWN_TARGET + 86400000])
      expect(profileCountdown(now)).toEqual(['00', '00', '00', '00', '00']);
  });
  it('does not depend on the timezone notation of the same instant', () => {
    expect(profileCountdown(Date.parse('2027-01-07T16:58:00Z'))).toEqual(
      profileCountdown(Date.parse('2027-01-07T23:58:00+07:00')),
    );
  });
});
