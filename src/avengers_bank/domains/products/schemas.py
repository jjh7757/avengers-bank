from decimal import Decimal

from pydantic import BaseModel, ConfigDict


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
