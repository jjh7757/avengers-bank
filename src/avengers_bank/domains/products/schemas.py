from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

AccountProductType = Literal["CHECKING", "DEPOSIT", "SAVINGS"]
CardProductType = Literal["CREDIT", "DEBIT"]


class AccountProductResponse(BaseModel):
    product_id: int
    type: str
    name: str
    description: str
    interest_rate: Decimal

    model_config = ConfigDict(from_attributes=True)


class CardProductResponse(BaseModel):
    product_id: int
    type: str
    name: str
    description: str

    model_config = ConfigDict(from_attributes=True)
