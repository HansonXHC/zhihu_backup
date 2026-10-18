"""Manifest bookkeeping and on-disk layout."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Iterable, Optional

from .config import content_dir_name, now_iso, safe_component
from .models import ContentItem, ManifestEntry


def atomic_write_json(path: Path, data: object) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def read_json(path: Path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


class Manifest:
    """Tracks the state of every item under one output base directory."""

    VERSION = 1

    def __init__(self, base_dir: Path, path: Optional[Path] = None):
        self.base_dir = Path(base_dir)
        self.path = Path(path) if path else self.base_dir / "manifest.json"
        self.data: Dict[str, object] = {"version": self.VERSION, "updated_at": "", "items": {}}
        self.load()

    def load(self) -> None:
        data = read_json(self.path, None)
        if isinstance(data, dict) and isinstance(data.get("items"), dict):
            self.data = data
            self.data.setdefault("version", self.VERSION)

    def save(self) -> None:
        self.data["version"] = self.VERSION
        self.data["updated_at"] = now_iso()
        atomic_write_json(self.path, self.data)

    @property
    def items(self) -> Dict[str, dict]:
        return self.data["items"]  # type: ignore[return-value]

    @staticmethod
    def key(kind: str, item_id: str) -> str:
        return f"{kind}:{item_id}"

    def get(self, kind: str, item_id: str) -> Optional[ManifestEntry]:
        raw = self.items.get(self.key(kind, item_id))
        if not isinstance(raw, dict):
            return None
        return ManifestEntry.from_dict(raw)

    def _put(self, entry: ManifestEntry) -> None:
        self.items[self.key(entry.type, entry.id)] = entry.to_dict()

    def mark_ok(
        self,
        item: ContentItem,
        dir_relative: str,
        files: Iterable[str],
        saved_at: Optional[str] = None,
    ) -> None:
        self._put(
            ManifestEntry(
                type=item.type,
                id=item.id,
                status="ok",
                dir=dir_relative,
                updated=item.updated,
                saved_at=saved_at or now_iso(),
                files=list(files),
            )
        )
        self.save()

    def mark_failed(self, item: ContentItem, error: str, dir_relative: str = "") -> None:
        previous = self.get(item.type, item.id)
        self._put(
            ManifestEntry(
                type=item.type,
                id=item.id,
                status="failed",
                dir=previous.dir if previous else dir_relative,
                updated=item.updated or (previous.updated if previous else 0),
                saved_at=now_iso(),
                files=previous.files if previous else [],
                error=str(error)[:2000],
            )
        )
        self.save()

    def should_skip(
        self,
        item: ContentItem,
        force: bool = False,
        update: bool = False,
        existing_dirs: Optional[Dict[str, Path]] = None,
    ) -> bool:
        if force:
            return False

        entry = self.get(item.type, item.id)
        if entry is None:
            # A manifest may have been deleted; fall back to the directory index.
            if existing_dirs and item.id in existing_dirs:
                content_md = existing_dirs[item.id] / "content.md"
                return content_md.exists()
            return False

        if entry.status != "ok":
            return False

        content_md = self.base_dir / entry.dir / "content.md"
        if not content_md.exists():
            return False

        if update and item.updated and entry.updated and item.updated > entry.updated:
            return False
        return True


class Storage:
    """Resolves output paths for users and single-item backups."""

    def __init__(self, output: Path):
        self.output = Path(output).resolve()

    def user_dir(self, url_token: str) -> Path:
        return self.output / "users" / safe_component(url_token, 100)

    def singles_dir(self) -> Path:
        return self.output / "singles"

    def item_dir(self, base_dir: Path, kind: str, item: ContentItem) -> Path:
        base_dir = Path(base_dir)
        return base_dir / kind / content_dir_name(item.created, item.id, item.title)

    @staticmethod
    def relative_to(base_dir: Path, path: Path) -> str:
        return Path(path).resolve().relative_to(Path(base_dir).resolve()).as_posix()

    @staticmethod
    def index_existing(base_dir: Path, kind: str) -> Dict[str, Path]:
        """Map content id -> directory for a kind, tolerating a missing manifest."""
        index: Dict[str, Path] = {}
        directory = Path(base_dir) / kind
        if not directory.is_dir():
            return index
        for child in directory.iterdir():
            if not child.is_dir():
                continue
            parts = child.name.split("-", 2)
            if len(parts) >= 2 and parts[1].isdigit():
                index.setdefault(parts[1], child)
        return index

    def build_content_index(self) -> Dict[tuple, Path]:
        """Index every locally backed-up item across users/ and singles/."""
        index: Dict[tuple, Path] = {}
        bases = []
        if self.singles_dir().is_dir():
            bases.append(self.singles_dir())
        users_dir = self.output / "users"
        if users_dir.is_dir():
            bases.extend(child for child in users_dir.iterdir() if child.is_dir())

        for base in bases:
            for kind in ("answers", "articles", "pins", "zvideos"):
                for item_id, path in self.index_existing(base, kind).items():
                    if (path / "content.md").exists():
                        index.setdefault((kind, item_id), path)
        return index
