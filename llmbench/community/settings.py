"""Optional local attribution settings (never inferred from the host)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unicodedata
from pathlib import Path


class SettingsError(ValueError):
    pass


def validate_nickname(value: str) -> str:
    value = value.strip()
    if not 1 <= len(value) <= 64 or any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in value) or "/" in value or "\\" in value:
        raise SettingsError("nickname must contain 1–64 printable characters and no path separator")
    return value


def settings_path() -> Path:
    if sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(root) / "llmbench" / "community-settings.json"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "llmbench" / "community-settings.json"
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "llmbench" / "community-settings.json"


def load(path: Path | None = None) -> str | None:
    path = path or settings_path()
    if not path.exists():
        return None
    try:
        def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError("duplicate_setting")
                result[key] = value
            return result
        raw = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=pairs, parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("invalid_setting")))
    except (OSError, ValueError) as exc:
        raise SettingsError("community settings cannot be read") from exc
    if (not isinstance(raw, dict) or set(raw) - {"settings_version", "nickname"}
            or isinstance(raw.get("settings_version"), bool) or raw.get("settings_version") != 1):
        raise SettingsError("community settings have an unsupported format")
    nickname = raw.get("nickname")
    if nickname is not None and not isinstance(nickname, str):
        raise SettingsError("community settings nickname is invalid")
    return validate_nickname(nickname) if isinstance(nickname, str) else None


def save(nickname: str | None, path: Path | None = None) -> Path:
    path = path or settings_path()
    value = validate_nickname(nickname) if nickname is not None else None
    path.parent.mkdir(parents=True, exist_ok=True)
    target = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=".community-settings-", delete=False) as handle:
            target = Path(handle.name)
            json.dump({"settings_version": 1, "nickname": value}, handle, sort_keys=True)
            handle.write("\n")
        target.replace(path)
    except OSError as exc:
        if target is not None:
            target.unlink(missing_ok=True)
        raise SettingsError("community settings cannot be saved") from exc
    return path
