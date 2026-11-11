"""보안 MCP 서버: 이상거래 탐지(FDS) 판정 기록 (조회 전용)"""

from mcp.types import ToolAnnotations
from pydantic import Field

from avengers_bank.domains.fds.schemas import FdsLogResponse
from avengers_bank.domains.fds.service import fds_service
from avengers_bank.mcp_servers.common import bank_tool, mask, new_server

READ = ToolAnnotations(readOnlyHint=True)

server = new_server("avengers-security", "AvengersBank 보안: 내 이체의 이상거래 탐지 판정 기록")


@bank_tool(server, annotations=READ)
async def get_fds_logs(db, user, limit: int = Field(default=10, ge=1, le=50)) -> dict:
    """최근 이체의 이상거래 탐지 판정 (통과·PIN 요구·차단과 그 이유)"""
    logs = [FdsLogResponse.model_validate(log).model_dump(mode="json") for log in await fds_service.get_my_logs(db, user.user_id, limit)]
    for log in logs:
        log["from_account"], log["to_account"] = mask(log["from_account"]), mask(log["to_account"])
    return {"logs": logs}

