from __future__ import annotations

import io
import zipfile
from abc import ABC, abstractmethod
from typing import Dict, Iterable, Optional, Set

from app.services.knowledge_graph.contracts import CanonicalBundle

MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024  # 100 MB


class KnowledgeSourceAdapter(ABC):
    source_name: str

    @abstractmethod
    def parse(
        self,
        files: Dict[str, bytes],
        *,
        subjects: Optional[Set[str]] = None,
    ) -> CanonicalBundle:
        """Convert source files into QB's canonical bundle."""

    @staticmethod
    def read_zip(file_bytes: bytes, allowed_names: Iterable[str]) -> Dict[str, bytes]:
        """Read allowed files from a zip by basename.

        Only whitelisted filenames are read; directory traversal is irrelevant
        because callers never use the archive path to write to disk.
        """
        allowed = set(allowed_names)
        files: Dict[str, bytes] = {}
        total = 0
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                name = info.filename.rsplit("/", 1)[-1]
                if name not in allowed or name in files:
                    continue
                total += info.file_size
                if total > MAX_UNCOMPRESSED_BYTES:
                    raise ValueError("压缩包解压后过大")
                files[name] = archive.read(info)
        return files
