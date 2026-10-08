import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createSimpleGit } from '/opt/node-toolchain/node_modules/renovate/dist/util/git/index.js';

const directory = await mkdtemp(join(tmpdir(), 'renovate-git-'));
try {
  const git = createSimpleGit({ config: { baseDir: directory } });
  await git.init();
  await git.addConfig('user.name', 'Devtools runtime check');
  await git.addConfig('user.email', 'devtools-check@example.invalid');
  await writeFile(join(directory, 'probe.txt'), 'Renovate Git runtime check\n');
  await git.add('probe.txt');
  await git.commit('probe');

  const status = await git.status();
  const log = await git.log({ maxCount: 1 });
  const content = await git.show(['HEAD:probe.txt']);
  if (!status.isClean() || log.total !== 1 || content !== 'Renovate Git runtime check\n') {
    throw new Error('Renovate Git operations returned unexpected results');
  }
  process.stdout.write('Renovate Git runtime check passed\n');
} finally {
  await rm(directory, { recursive: true, force: true });
}
