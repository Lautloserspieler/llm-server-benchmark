"""Summarize all SARIF results, without claiming they are new PR alerts."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def summarize(directory: Path, title: str) -> str:
    counts: Counter[str] = Counter()
    files = sorted(directory.rglob('*.sarif'))
    for path in files:
        for run in json.loads(path.read_text(encoding='utf-8')).get('runs', []):
            rules = run.get('tool', {}).get('driver', {}).get('rules', [])
            for result in run.get('results', []):
                index = result.get('ruleIndex', -1)
                rule = rules[index] if isinstance(index, int) and 0 <= index < len(rules) else {}
                counts[result.get('level', rule.get('defaultConfiguration', {}).get('level', 'warning'))] += 1
    if not files:
        return f'## {title}\n\nNo SARIF output available; check the analysis step for failures.\n'
    rows = [f'## {title}', '', 'All results in this analysis; not a count of newly introduced PR alerts.', '',
            '| SARIF level | Results |', '| --- | ---: |']
    rows.extend(f'| {level} | {counts[level]} |' for level in ('error', 'warning', 'note', 'none'))
    rows.extend(['', 'Use Code scanning / Files changed to inspect alert details and PR attribution.'])
    return '\n'.join(rows) + '\n'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--title', default='CodeQL')
    args = parser.parse_args()
    print(summarize(args.directory, args.title), end='')


if __name__ == '__main__':
    main()
