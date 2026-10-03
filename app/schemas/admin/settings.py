"""The Settings screen."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class SurchargeOut(BaseModel):
    amount: Decimal = Field(description="Whole taka added to the delivery fee while active")
    active: bool = Field(description="Only active surcharges are charged")


class PlatformSettingsOut(BaseModel):
    """Effective values: an unset field shows the server default it falls back
    to, and is listed in `using_server_defaults`."""

    app_name: str
    support_email: str | None = None
    support_phone: str | None = None
    delivery_base_fee: Decimal = Field(description="Charged on every order, even at 0 km")
    delivery_per_km_fee: Decimal = Field(
        description="Per km of the whole distance, charged by the metre (1.43 km pays 1.43 of it)"
    )
    delivery_min_fee: Decimal = Field(description="The fee never goes below this")
    priority_delivery_fee: Decimal = Field(
        description="What Priority adds at checkout. Paid to the rider in full."
    )
    restaurant_commission_rate: float = Field(
        description="Starting commission for new RESTAURANT (Food) vendors; 0.18 == 18%"
    )
    grocery_commission_rate: float = Field(description="…for new GROCERY (Shop) vendors")
    pharmacy_commission_rate: float = Field(description="…for new PHARMACY (Medicine) vendors")
    rain_surcharge: SurchargeOut
    heatwave_fee: SurchargeOut
    high_demand_fee: SurchargeOut
    active_surcharge_total: Decimal = Field(
        description="What checkout adds to every delivery fee right now"
    )
    using_server_defaults: list[str] = Field(
        description="Fields not set here, so the server configuration applies"
    )
    updated_at: datetime
    updated_by: str | None = None
