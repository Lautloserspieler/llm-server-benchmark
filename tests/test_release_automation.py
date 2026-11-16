"""Exercise release planning and summaries against isolated source files."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = load('release')
sarif = load('sarif_summary')


@pytest.fixture
def source(tmp_path):
    (tmp_path / 'llmbench').mkdir()
    (tmp_path / 'VERSION').write_text('1.6.5\n')
    (tmp_path / 'pyproject.toml').write_text('[project]\nversion = "1.6.5"\n')
    (tmp_path / 'llmbench/__init__.py').write_text('__version__ = "1.6.5"\n')
    for name in ('CHANGELOG.md', 'CHANGELOG.en.md'):
        (tmp_path / name).write_text('# Changelog\n\n## Unreleased\n\n### Reviewed notes\n\n- Existing work\n\n## 1.6.5\n\n- Old\n')
    return tmp_path


@pytest.mark.parametrize(('bump', 'expected'), [('patch', '1.6.6'), ('minor', '1.7.0'), ('major', '2.0.0')])
def test_bump_resets_lower_components(bump, expected):
    assert release.next_version('1.6.5', '', bump) == expected


@pytest.mark.parametrize('value', ['v1.7.0', '1.7', '01.7.0', '1.7.0; echo x', '1.7.0-rc1', '1.6.5', '1.0.0'])
def test_reject_invalid_or_nonincreasing_version(value):
    with pytest.raises(ValueError):
        release.next_version('1.6.5', value, 'none')


def test_reject_ambiguous_input_and_mismatched_sources(source):
    with pytest.raises(ValueError):
        release.next_version('1.6.5', '1.7.0', 'minor')
    (source / 'VERSION').write_text('1.6.6')
    with pytest.raises(ValueError, match='mismatch'):
        release.current_version(source)


def test_prepare_preserves_bilingual_notes_and_history(source):
    planned = release.prepare(source, '1.7.0', ['fix: recovery (#12)'])
    assert len(planned) == 5
    for name, text in planned.items():
        (source / name).write_text(text)
    assert release.current_version(source) == '1.7.0'
    for name in ('CHANGELOG.md', 'CHANGELOG.en.md'):
        notes = release.release_notes(planned[name], '1.7.0')
        assert 'Existing work' in notes
        assert 'fix: recovery (#12)' in notes
        assert 'Old' not in notes
        assert planned[name].count('## 1.6.5\n') == 1
    with pytest.raises(ValueError):
        release.prepare(source, '1.7.0', [])


def test_dry_run_does_not_modify_any_source(source):
    for args in (['init'], ['config', 'user.name', 'Test'], ['config', 'user.email', 'test@example.com'],
                 ['add', '.'], ['commit', '-m', 'feat: initial']):
        subprocess.run(['git', '-C', str(source), *args], check=True, capture_output=True)
    before = {str(p.relative_to(source)): p.read_bytes() for p in source.rglob('*') if p.is_file() and '.git' not in p.parts}
    subprocess.run([sys.executable, str(ROOT / 'scripts/release.py'), 'prepare', '--root', str(source),
                    '--bump', 'minor', '--dry-run'], check=True, capture_output=True)
    assert all((source / p).read_bytes() == content for p, content in before.items())


def test_summary_uses_rule_default_level_and_handles_missing_output(tmp_path):
    assert 'No SARIF output' in sarif.summarize(tmp_path, 'CodeQL')
    data = {'runs': [{'tool': {'driver': {'rules': [{'defaultConfiguration': {'level': 'error'}}]}},
                      'results': [{'ruleIndex': 0}, {'level': 'note'}, {}]}]}
    (tmp_path / 'python.sarif').write_text(json.dumps(data))
    text = sarif.summarize(tmp_path, 'CodeQL')
    assert '| error | 1 |' in text and '| warning | 1 |' in text and '| note | 1 |' in text
    assert 'not a count of newly introduced PR alerts' in text
