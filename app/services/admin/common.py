"""Pieces every admin list shares: the business-type badge, date windows,
search patterns and CSV export."""

import csv
import io
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import ValidationError
from app.models.vendor_application import VendorApplication

# An export is a spreadsheet, not a backup: past this many rows it should be a
# narrower date range, not a bigger file.
EXPORT_MAX_ROWS = 5000

BUSINESS_TYPES = ("RESTAURANT", "GROCERY", "PHARMACY")


def business_type_of(restaurant_id: Any) -> ColumnElement[str | None]:
    """The Food / Grocery / Medicine badge, as a correlated subquery.

    The type is asked on the partner application and nowhere else, so a
    restaurant created through the one-call fast path has none and this
    yields NULL. Read from the newest application in case one was ever
    resubmitted.
    """
    return (
        select(VendorApplication.business_type)
        .where(VendorApplication.restaurant_id == restaurant_id)
        .order_by(VendorApplication.created_at.desc())
        .limit(1)
        .correlate_except(VendorApplication)
        .scalar_subquery()
    )


def validate_business_type(raw: str | None) -> str | None:
    if not raw:
        return None
    value = raw.strip().upper()
    if value not in BUSINESS_TYPES:
        raise ValidationError(
            f"Unknown business type '{raw}'",
            details=[f"Expected one of: {', '.join(BUSINESS_TYPES)}"],
        )
    return value


def day_window(
    date_from: date | None, date_to: date | None
) -> tuple[datetime | None, datetime | None]:
    """Inclusive calendar days → a half-open UTC [start, end) range.

    Half-open so an order placed at 23:59:59.9 on the last day is counted, which
    a closed `<= 23:59:59` bound would drop.
    """
    if date_from and date_to and date_from > date_to:
        raise ValidationError("date_from must not be after date_to")
    start = datetime.combine(date_from, time.min, tzinfo=UTC) if date_from else None
    end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=UTC) if date_to else None
    return start, end


def like_pattern(q: str) -> str:
    """A case-insensitive substring pattern with LIKE wildcards escaped, so a
    search for "50%" means the text, not "50 then anything"."""
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def order_number_from(q: str) -> int | None:
    """Read an order number out of a search box: ORD-48210, #48210 and 48210
    all name the same order."""
    digits = q.strip().upper().removeprefix("ORD-").removeprefix("ORD").lstrip("#").strip()
    return int(digits) if digits.isdigit() and len(digits) < 18 else None


def parse_uuid(raw: str | None, what: str) -> uuid.UUID | None:
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise ValidationError(f"{what} is not a valid id") from None


def csv_response(rows: Sequence[BaseModel], filename: str) -> Response:
    """Rows as a CSV download, one column per field in declaration order.

    Nested objects are left out: an export is for a spreadsheet, and a cell
    holding JSON is worse than no cell.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    if rows:
        fields = [
            name
            for name, value in rows[0].model_dump().items()
            if not isinstance(value, dict | list)
        ]
        writer.writerow(fields)
        for row in rows:
            data = row.model_dump(mode="json")
            writer.writerow(["" if data[f] is None else data[f] for f in fields])
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
