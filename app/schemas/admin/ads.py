"""The Advertisement screen: vendor promotions as campaigns."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class AdCampaignOut(BaseModel):
    id: str
    restaurant_id: str
    restaurant_name: str
    campaign: str = Field(description='The offer, e.g. "20% OFF"')
    code: str
    budget: Decimal | None = Field(default=None, description="Discount budget cap; null = none")
    spent: Decimal = Field(description="Discount given so far")
    impressions: int = Field(description="Times its restaurant card was shown as promoted")
    clicks: int
    redemptions: int
    revenue: Decimal = Field(description="Grand total of orders that used it")
    status: str = Field(description="SCHEDULED, ACTIVE, PAUSED or ENDED")
    valid_from: datetime
    valid_until: datetime
    created_at: datetime
