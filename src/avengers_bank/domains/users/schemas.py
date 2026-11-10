from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

BIRTH_DATE = r"^(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])$"


class UserCreate(BaseModel):
    login_id: str = Field(min_length=4, max_length=50)
    password: str = Field(min_length=8, max_length=128, repr=False)
    name: str = Field(min_length=1, max_length=50)
    nick_name: str | None = Field(default=None, max_length=50)
    phone: str = Field(min_length=9, max_length=20)
    birth_date: str | None = Field(default=None, pattern=BIRTH_DATE, description="YYYYMMDD (선택). 다른 은행 내 계좌 불러오기에 필요")


class UserUpdate(BaseModel):
    """PATCH /users/me — 보낸 필드만 바꾼다. nick_name·birth_date는 null로 지울 수 있다."""

    name: str | None = Field(default=None, min_length=1, max_length=50)
    nick_name: str | None = Field(default=None, max_length=50)
    phone: str | None = Field(default=None, min_length=9, max_length=20)
    birth_date: str | None = Field(default=None, pattern=BIRTH_DATE, description="YYYYMMDD")


class PinUpdate(BaseModel):
    """PUT /users/me/pin — 비밀번호를 다시 확인하고 이체 PIN을 등록·변경한다."""

    password: str = Field(min_length=1, max_length=128, repr=False)
    pin: str = Field(pattern=r"^\d{6}$", repr=False, description="숫자 6자리")


class UserLogin(BaseModel):
    login_id: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128, repr=False)


class UserResponse(BaseModel):
    user_id: int
    login_id: str
    name: str
    nick_name: str | None
    phone: str
    birth_date: str | None = None
    has_pin: bool = False
    role: Literal["CUSTOMER", "ADMIN"] = Field(default="CUSTOMER", description="ADMIN이면 관리자 메뉴(자금 관리)를 보여 준다")
    created_at: datetime
    last_login_at: datetime | None = None
    previous_login_at: datetime | None = Field(default=None, description="이번 로그인 바로 전 로그인 시각 (\"지난 로그인\")")

    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
