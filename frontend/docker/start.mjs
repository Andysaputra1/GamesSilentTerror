import { writeFileSync } from 'node:fs';
import { spawn } from 'node:child_process';

const url = new URL(process.env.BACKEND_URL || 'https://backendthesis.andylabs.site');
if (url.protocol !== 'https:' || url.username || url.password ||
    url.pathname !== '/' || url.search || url.hash) {
  throw new Error('BACKEND_URL harus origin HTTPS tanpa path, password, query, atau fragment.');
}
// This ignored file is also the replacement used by the hosted build.
writeFileSync('src/environments/environment.vercel.ts',
  `// Generated public Docker configuration.\nexport const environment = ${JSON.stringify({ backendUrl: url.origin, hosted: true })};\n`);
console.log(`Frontend Docker -> ${url.origin}`);
const child = spawn(process.execPath, ['node_modules/@angular/cli/bin/ng.js', 'serve',
  '--host', '0.0.0.0', '--port', '4200', '--poll', '1000',
  '--build-target', 'frontend:build:development,vercel'], { stdio: 'inherit' });
for (const signal of ['SIGTERM', 'SIGINT']) process.on(signal, () => child.kill(signal));
child.on('error', error => { console.error(error); process.exit(1); });
child.on('exit', code => process.exit(code ?? 0));
