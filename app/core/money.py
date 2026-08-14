"""The single conversion boundary between wire money and stored money.

The database stores BIGINT minor units (paisa). The API speaks whole taka, per
the spec's worked example (``"item_total": 1059``). 1059 taka == 105900 paisa.

Business logic must operate ONLY on minor units — integers, exact, no float
rounding drift across discounts, tips, VAT and commission splits. These two
functions are the only place the two representations meet.
"""

from decimal import ROUND_HALF_UP, Decimal

from app.core.config import settings

MINOR = settings.CURRENCY_MINOR_UNITS


def to_minor(amount: float | int | str | Decimal) -> int:
    """Wire value (taka) -> stored value (paisa).

    Uses Decimal, not float: ``int(10.55 * 100)`` is 1054, not 1055.
    """
    return int((Decimal(str(amount)) * MINOR).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def to_major(minor: int) -> Decimal:
    """Stored value (paisa) -> wire value (taka)."""
    return (Decimal(minor) / MINOR).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def percentage_of(minor: int, basis_points: int) -> int:
    """Apply a percentage in basis points, exactly. 1500 bps == 15%.

    Basis points keep the whole computation in integers, so a 15% VAT on an odd
    subtotal never produces a fractional paisa that has to be floated away.
    """
    return int(
        (Decimal(minor) * basis_points / 10_000).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )
