"""Run shell control flow locally with external services replaced by stubs."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
GIT_BASH = Path("C:/Program Files/Git/bin/bash.exe")
BASH = str(GIT_BASH) if os.name == "nt" and GIT_BASH.is_file() else shutil.which("bash")


def _bash(script, cwd, env):
    return subprocess.run([BASH, "-c", script], cwd=cwd, env={**os.environ, **env},
                          capture_output=True, text=True, timeout=30)


@pytest.mark.skipif(BASH is None, reason="bash unavailable")
def test_wiki_credentials_survive_cleanup_and_are_removed_after_push(tmp_path):
    workflow = yaml.safe_load((ROOT / ".github/workflows/wiki.yml").read_text())
    script = workflow["jobs"]["publish"]["steps"][1]["run"]
    workspace = tmp_path / "workspace"
    for lang in ("de", "en"):
        (workspace / "wiki" / lang).mkdir(parents=True)
        (workspace / "wiki" / lang / "Page.md").write_text("page")
    for name in ("Home.md", "_Sidebar.md", "_Footer.md"):
        (workspace / "wiki" / name).write_text("page")
    # The fake git checks authentication exactly when the real push would use it.
    stub = '''
git() {
  case "$1" in
    init) mkdir .git ;;
    diff) return 1 ;;
    push)
      test -x "$GIT_ASKPASS" || return 20
      test "$("$GIT_ASKPASS" Password)" = synthetic-token || return 21
      test ! -e askpass.sh || return 22
      printf '%s' "$GIT_ASKPASS" > "$PROBE_FILE" ;;
  esac
}
'''
    probe = tmp_path / "askpass-path"
    proc = _bash(stub + script, tmp_path, {
        "GITHUB_WORKSPACE": workspace.as_posix(), "GITHUB_REPOSITORY": "test/repo",
        "GITHUB_SHA": "synthetic", "GH_TOKEN": "synthetic-token", "PROBE_FILE": probe.as_posix(),
    })
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert probe.is_file(), "push was not reached"
    cleanup = _bash('test ! -e "$(cat "$PROBE_FILE")"', tmp_path, {"PROBE_FILE": probe.as_posix()})
    assert cleanup.returncode == 0


@pytest.mark.skipif(BASH is None, reason="bash unavailable")
@pytest.mark.parametrize("forced", ["0", "1"])
def test_linux_build_and_next_start_use_local_image(tmp_path, forced):
    script = '''
set -e
source "$REVIEW_ROOT/scripts/docker_common.sh"
ROOT_DIR="$PWD/project"
mkdir -p "$ROOT_DIR/.runtime"
ui_step() { :; }; ui_warn() { :; }; ui_ok() { :; }
llmbench_prepare_docker_paths() { export LLMBENCH_DOCKER_IMAGE; }
_llmbench_docker() {
  if [ "$1" = pull ]; then return 1; fi
  [ "$LLMBENCH_DOCKER_IMAGE" = llmbench-local:dev ] || return 1
  printf '%s' sha256:synthetic
}
_llmbench_compose() {
  if [ "$1" = -f ]; then
    [ "$2" = "$ROOT_DIR/compose.build.yaml" ] && [ "$3" = build ]
    [ "$LLMBENCH_DOCKER_BUILD_IMAGE" = llmbench-local:dev ]
    touch "$ROOT_DIR/built"
  fi
}
llmbench_docker_build
test -f "$ROOT_DIR/built"
test "$LLMBENCH_DOCKER_IMAGE" = llmbench-local:dev
llmbench_mark_docker_ready
# Simulate the next shell's default image, with no explicit operator override.
LLMBENCH_DOCKER_IMAGE=registry.invalid/pinned@sha256:synthetic
llmbench_resolve_docker_cmd() { :; }
llmbench_docker_ready
test "$LLMBENCH_DOCKER_IMAGE" = llmbench-local:dev
'''
    env = {"REVIEW_ROOT": ROOT.as_posix(), "LLMBENCH_DOCKER_BUILD_LOCAL": forced,
           "LLMBENCH_DOCKER_IMAGE": "", "LLMBENCH_DOCKER_BUILD_IMAGE": ""}
    proc = _bash(script, tmp_path, env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
