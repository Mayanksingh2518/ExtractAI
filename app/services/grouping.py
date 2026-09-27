"""Group documents by the person they belong to."""

from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass
class OwnerGroup(Generic[T]):
    ownerName: str | None  # first spelling seen; None for documents with no visible owner
    documents: list[T] = field(default_factory=list)


def owner_key(name: str | None) -> str | None:
    """Normalise a name for matching: 'JOHN  DOE' and 'John Doe' give the same key."""
    if name is None:
        return None
    key = " ".join(name.split()).casefold()
    return key or None


def group_by_owner(items: Iterable[T], owner_of: Callable[[T], str | None]) -> list[OwnerGroup[T]]:
    """Group items by normalised owner name, in first-seen order, with the no-owner group last.

    No fuzzy matching: "Jon Doe" and "John Doe" stay separate people.
    """
    groups: dict[str | None, list[T]] = defaultdict(list)
    display_names: dict[str | None, str | None] = {}
    for item in items:
        name = owner_of(item)
        key = owner_key(name)
        groups[key].append(item)
        display_names.setdefault(key, " ".join(name.split()) if key else None)

    keys = [k for k in groups if k is not None] + ([None] if None in groups else [])
    return [OwnerGroup(display_names[k], groups[k]) for k in keys]
