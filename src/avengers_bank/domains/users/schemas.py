from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class UserCreate(BaseModel):
    login_id: str = Field(min_length=4, max_length=50)
    password: str = Field(min_length=8, max_length=128, repr=False)
    name: str = Field(min_length=1, max_length=50)
    nick_name: str | None = Field(default=None, max_length=50)
    phone: str = Field(min_length=9, max_length=20)


class UserLogin(BaseModel):
    login_id: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128, repr=False)


class UserResponse(BaseModel):
    user_id: int
    login_id: str
    name: str
    nick_name: str | None
    phone: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
