"""Prepare a bilingual release PR or validate an already reviewed release."""
from __future__ import annotations

import argparse
import re
import subprocess
from datetime import date
from pathlib import Path

VERSION = re.compile(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)')
SOURCES = {'pyproject.toml': r'(?m)^version\s*=\s*"([^"]+)"',
           'llmbench/__init__.py': r'(?m)^__version__\s*=\s*"([^"]+)"'}


def version_tuple(value: str) -> tuple[int, ...]:
    if not VERSION.fullmatch(value):
        raise ValueError('Expected a stable version such as 1.7.0 (no v prefix)')
    return tuple(map(int, value.split('.')))


def current_version(root: Path) -> str:
    value = (root / 'VERSION').read_text(encoding='utf-8').strip()
    version_tuple(value)
    for name, pattern in SOURCES.items():
        match = re.search(pattern, (root / name).read_text(encoding='utf-8'))
        if not match or match[1] != value:
            raise ValueError(f'Version mismatch in {name}')
    return value


def next_version(current: str, explicit: str, bump: str) -> str:
    parts = list(version_tuple(current))
    if explicit and bump != 'none':
        raise ValueError('Choose either version or bump, not both')
    if explicit:
        candidate = explicit
    elif bump in ('major', 'minor', 'patch'):
        index = ('major', 'minor', 'patch').index(bump)
        parts[index] += 1
        parts[index + 1:] = [0] * (2 - index)
        candidate = '.'.join(map(str, parts))
    else:
        raise ValueError('Provide version or select a bump')
    if version_tuple(candidate) <= version_tuple(current):
        raise ValueError('New version must be greater than the current version')
    return candidate


def release_notes(text: str, version: str) -> str:
    match = re.search(rf'(?m)^## {re.escape(version)}(?: — [^\n]+)?\n', text)
    if not match:
        raise ValueError(f'Missing release section for {version}')
    body = re.split(r'(?m)^## ', text[match.end():], maxsplit=1)[0].strip()
    if not body:
        raise ValueError('Release notes are empty')
    return body


def prepare(root: Path, version: str, commits: list[str]) -> dict[str, str]:
    current = current_version(root)
    next_version(current, version, 'none')
    changes = {'VERSION': version + '\n'}
    for name, pattern in SOURCES.items():
        changes[name] = re.sub(pattern, lambda m: m[0].replace(m[1], version),
                               (root / name).read_text(encoding='utf-8'), count=1)
    for name, heading in (('CHANGELOG.md', 'Weitere Commits (Originaltitel)'),
                          ('CHANGELOG.en.md', 'Additional commits (original titles)')):
        text = (root / name).read_text(encoding='utf-8')
        marker = '## Unreleased\n'
        if text.count(marker) != 1 or re.search(rf'(?m)^## {re.escape(version)}(?:\s|$)', text):
            raise ValueError(f'Unexpected changelog structure: {name}')
        before, rest = text.split(marker, 1)
        split = re.search(r'(?m)^## ', rest)
        unreleased, history = (rest[:split.start()], rest[split.start():]) if split else (rest, '')
        bullets = '\n'.join(f'- {line}' for line in commits)
        body = unreleased.strip()
        if bullets:
            body += f'\n\n### {heading}\n\n{bullets}'
        if not body.strip():
            raise ValueError(f'No release notes or commits for {name}')
        changes[name] = f'{before}{marker}\n## {version} — {date.today().isoformat()}\n\n{body.strip()}\n\n{history}'
    return changes


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['prepare', 'verify'])
    parser.add_argument('--root', type=Path, default=Path('.'))
    parser.add_argument('--version', default='')
    parser.add_argument('--bump', choices=['none', 'patch', 'minor', 'major'], default='none')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--notes', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    current = current_version(args.root)
    if args.mode == 'prepare':
        version = next_version(current, args.version, args.bump)
        # Use the nearest reachable release tag, never a tag on another branch.
        tags = git(args.root, 'tag', '--merged', 'HEAD').splitlines()
        stable = [tag for tag in tags if tag.startswith('v') and VERSION.fullmatch(tag[1:])]
        baseline = git(args.root, 'describe', '--tags', '--abbrev=0', *[x for tag in stable for x in ('--match', tag)]) if stable else ''
        revision = f'{baseline}..HEAD' if baseline else 'HEAD'
        commits = git(args.root, 'log', '--no-merges', '--format=%s (%h)', revision).splitlines()
        changes = prepare(args.root, version, commits)
        for name, content in changes.items():
            if not args.dry_run:
                (args.root / name).write_text(content, encoding='utf-8')
        notes = '\n\n'.join(release_notes(changes[name], version) for name in ('CHANGELOG.md', 'CHANGELOG.en.md'))
    else:
        if args.bump != 'none' or args.version != current:
            raise ValueError('Publication requires the exact current version and bump=none')
        version = current
        notes = '\n\n'.join(release_notes((args.root / name).read_text(encoding='utf-8'), version)
                            for name in ('CHANGELOG.md', 'CHANGELOG.en.md'))
    if args.notes:
        args.notes.write_text(notes + '\n', encoding='utf-8')
    if args.output:
        with args.output.open('a', encoding='utf-8') as stream:
            stream.write(f'version={version}\n')
    print(f'{args.mode}: v{version}' + (' (dry run, no source changes)' if args.dry_run else ''))


if __name__ == '__main__':
    main()
