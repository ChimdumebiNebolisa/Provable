from __future__ import annotations

import re
from datetime import datetime

MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def validate_month(month: str) -> str:
    if any(token in month for token in ("..", "/", "\\")):
        raise_invalid_month()
    if not MONTH_PATTERN.fullmatch(month):
        raise_invalid_month()

    try:
        datetime.strptime(month, "%Y-%m")
    except ValueError as exc:
        raise ValueError("invalid_month") from exc

    return month


def raise_invalid_month() -> None:
    raise ValueError("invalid_month")
