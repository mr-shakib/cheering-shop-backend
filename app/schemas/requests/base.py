"""Shared building blocks for request bodies."""

from decimal import Decimal
from typing import Annotated

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

Money = Annotated[Decimal, Field(ge=0, description="Whole taka; stored as paisa")]


# The account identifier. Named `email` because that is what it holds today and
# what a client developer expects to see — but `identifier` is still accepted so
# nothing breaks for a client already sending it.
#
# When SMS delivery lands, `phone` joins this list rather than replacing it: a
# breaking rename on already-shipped mobile clients is far more expensive than
# carrying three aliases for one value.
_IDENTIFIER_ALIASES = AliasChoices("email", "identifier", "phone")


class _IdentifierBody(BaseModel):
    """Base for every request that names an account."""

    model_config = ConfigDict(populate_by_name=True)

    email: str = Field(
        validation_alias=_IDENTIFIER_ALIASES,
        description="Account email address (the `identifier` alias is also accepted)",
    )
