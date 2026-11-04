from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RecipientCreate(BaseModel):
    account_num: str = Field(min_length=1, max_length=20, description="받는 사람의 입출금 계좌번호")
    nickname: str = Field(min_length=1, max_length=50, description='부르는 이름 (예: "엄마")')


class RecipientUpdate(BaseModel):
    nickname: str = Field(min_length=1, max_length=50)


class RecipientResponse(BaseModel):
    recipient_id: int
    account_num: str
    holder_name: str
    nickname: str
    last_sent_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
