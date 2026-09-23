import { existsSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';

// Resolve from this script, so npm start works from the repository root.
const rootEnv = fileURLToPath(new URL('../../.env', import.meta.url));
// Only public frontend values are copied into the generated browser config.
if (existsSync(rootEnv)) process.loadEnvFile(rootEnv);
process.chdir(fileURLToPath(new URL('../', import.meta.url)));
const port = process.env.FRONTEND_PORT || '4200';
if (!/^\d+$/.test(port) || Number(port) < 1 || Number(port) > 65535) {
  throw new Error('FRONTEND_PORT harus angka 1 sampai 65535.');
}
const url = new URL(process.env.BACKEND_URL || 'https://backendthesis.andylabs.site');
if (
  url.protocol !== 'https:' ||
  url.username ||
  url.password ||
  url.pathname !== '/' ||
  url.search ||
  url.hash
) {
  throw new Error('BACKEND_URL harus origin HTTPS tanpa path, password, query, atau fragment.');
}
// This ignored file is also the replacement used by the hosted build.
writeFileSync(
  'src/environments/environment.vercel.ts',
  `// Generated public Docker configuration.\nexport const environment = ${JSON.stringify({ backendUrl: url.origin, hosted: true })};\n`,
);
console.log(`Frontend -> ${url.origin}`);
const child = spawn(
  process.execPath,
  [
    'node_modules/@angular/cli/bin/ng.js',
    'serve',
    '--host',
    '0.0.0.0',
    '--port',
    port,
    '--poll',
    '1000',
    '--build-target',
    'frontend:build:development,vercel',
  ],
  { stdio: 'inherit' },
);
for (const signal of ['SIGTERM', 'SIGINT']) process.on(signal, () => child.kill(signal));
child.on('error', (error) => {
  console.error(error);
  process.exit(1);
});
child.on('exit', (code) => process.exit(code ?? 0));
