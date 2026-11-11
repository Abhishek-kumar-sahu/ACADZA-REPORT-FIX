"""taxonomy.json is the only source of verdict/repair vocabularies (RULES R-01)."""
import json
from functools import lru_cache
from pathlib import Path

from .config import settings

ROUTES = ("auto_apply", "faculty_review", "no_change")


@lru_cache
def load(data_dir: Path | None = None) -> dict:
    with open((data_dir or settings.data_dir) / "taxonomy.json", encoding="utf-8") as f:
        tax = json.load(f)
    if not tax.get("verdicts") or not tax.get("repairs"):
        raise ValueError("taxonomy.json missing verdicts or repairs")
    for key, rep in tax["repairs"].items():
        if not isinstance(rep.get("fields"), list) or not isinstance(rep.get("auto"), bool):
            raise ValueError(f"taxonomy repair {key!r} malformed")
    return tax


def verdicts() -> tuple[str, ...]:
    return tuple(load()["verdicts"])


def repairs() -> tuple[str, ...]:
    return tuple(load()["repairs"])


def repair_fields(repair: str) -> list[str]:
    return list(load()["repairs"][repair]["fields"])
