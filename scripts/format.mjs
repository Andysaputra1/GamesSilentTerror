import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = fileURLToPath(new URL('../', import.meta.url));
const mode = process.argv.includes('--check') ? '--check' : '--write';

// Gunakan daftar Git agar dependency, hasil build, dan environment lokal tidak ikut diformat.
// CSS/SCSS serta isi bahasa embedded dikecualikan oleh konfigurasi Prettier.
const files = execFileSync(
  'git',
  ['ls-files', '--cached', '--others', '--exclude-standard', '-z'],
  {
    cwd: root,
    encoding: 'utf8',
  },
)
  .split('\0')
  .filter((file) => /\.(ts|js|mjs|html|json|ya?ml)$/.test(file))
  .filter((file) => !file.endsWith('package-lock.json'));

// Jalankan versi formatter milik proyek; kegagalan pemeriksaan diteruskan ke pemanggil.
try {
  execFileSync(
    process.execPath,
    [path.join(root, 'frontend/node_modules/prettier/bin/prettier.cjs'), mode, ...files],
    { cwd: root, stdio: 'inherit' },
  );
} catch (error) {
  process.exitCode = error.status ?? 1;
}
