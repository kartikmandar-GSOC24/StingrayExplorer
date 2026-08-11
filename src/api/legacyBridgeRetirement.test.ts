import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const repositoryRoot = process.cwd();

function productionTypeScriptFiles(directory: string): string[] {
  return readdirSync(directory).flatMap((entry) => {
    const path = join(directory, entry);
    if (statSync(path).isDirectory()) return productionTypeScriptFiles(path);
    if (!/\.tsx?$/.test(path) || /\.test\.tsx?$/.test(path)) return [];
    return [path];
  });
}

describe('raw Electron filesystem bridge retirement', () => {
  it('exposes only grant-backed native file selection methods', () => {
    const preload = readFileSync(join(repositoryRoot, 'electron/preload.ts'), 'utf8');
    const handlers = readFileSync(join(repositoryRoot, 'electron/ipcHandlers.ts'), 'utf8');
    const declarations = readFileSync(
      join(repositoryRoot, 'src/types/electron.d.ts'),
      'utf8'
    );

    for (const rawMethod of [
      'openFile',
      'saveFile',
      'fileExists',
      'openDirectory',
      'showItemInFolder',
    ]) {
      expect(preload).not.toMatch(new RegExp(`\\b${rawMethod}\\s*:`));
      expect(declarations).not.toMatch(new RegExp(`\\b${rawMethod}\\s*:`));
    }

    for (const rawChannel of [
      'dialog:openFile',
      'dialog:saveFile',
      'dialog:openDirectory',
      'file:exists',
      'shell:showItemInFolder',
    ]) {
      expect(handlers).not.toContain(`'${rawChannel}'`);
      expect(preload).not.toContain(`'${rawChannel}'`);
    }

    expect(preload).toMatch(/\bopenGrantedFile\s*:/);
    expect(preload).toMatch(/\bsaveGrantedFile\s*:/);
  });

  it('has no production renderer call site for a retired raw method', () => {
    const rendererSources = productionTypeScriptFiles(join(repositoryRoot, 'src'));
    const rawCall = /electronAPI\.(?:openFile|saveFile|fileExists|openDirectory|showItemInFolder)\b/;

    const offenders = rendererSources.filter((source) =>
      rawCall.test(readFileSync(source, 'utf8'))
    );
    expect(offenders).toEqual([]);
  });
});
