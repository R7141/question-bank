from __future__ import annotations

from typing import Set

from slugify import slugify


def domain_key(name: str) -> str:
    return f"domain:{name.strip()}"


def chapter_key(domain: str | None, name: str) -> str:
    return f"chapter:{(domain or '').strip()}:{name.strip()}"


def category_external_id(key: str) -> str:
    return key


def unique_slug(name: str, used: Set[str]) -> str:
    base = slugify(name) or "kp"
    candidate = base
    counter = 2
    while candidate in used:
        candidate = f"{base}-{counter}"
        counter += 1
    used.add(candidate)
    return candidate
