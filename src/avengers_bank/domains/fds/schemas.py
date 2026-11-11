from datetime import datetime

from pydantic import BaseModel, ConfigDict


class FdsLogResponse(BaseModel):
    fds_log_id: int
    session_id: str | None
    tx_type: str
    from_account: str
    to_account: str
    amount: int
    rule_hits: list[dict]
    ml_score: float | None
    top_factors: list[dict]
    risk_level: str
    decision: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
