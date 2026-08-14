"""Custom column types.

`CIText` is defined here rather than pulled from the `sqlalchemy-citext` package:
that package is a thin wrapper with an uncertain maintenance story, and this is
a dozen lines with no dependency risk on new CPython releases.
"""

from typing import Any

from sqlalchemy.types import UserDefinedType


class CIText(UserDefinedType):
    """PostgreSQL ``citext`` — case-insensitive text.

    Used for email and promo codes so ``User@x.com`` and ``user@x.com`` cannot
    both register, without every query having to remember ``lower()``.
    """

    cache_ok = True

    def get_col_spec(self, **kw: Any) -> str:
        return "CITEXT"

    def bind_processor(self, dialect: Any) -> None:
        return None

    def result_processor(self, dialect: Any, coltype: Any) -> None:
        return None

    @property
    def python_type(self) -> type:
        return str
