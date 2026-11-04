from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from avengers_bank.core.database import engine
from avengers_bank.core.exception_handlers import register_exception_handlers
from avengers_bank.core.responses import SuccessResponse, error_responses
from avengers_bank.domains.accounts.router import router as account_router
from avengers_bank.domains.cards.router import router as card_router
from avengers_bank.domains.products.router import router as product_router
from avengers_bank.domains.transfers.router import router as transfer_router
from avengers_bank.domains.users.router import router as user_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(title="AvengersBank", lifespan=lifespan, responses=error_responses(500))
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)
register_exception_handlers(app)
app.include_router(user_router)
app.include_router(product_router)
app.include_router(account_router)
app.include_router(transfer_router)
app.include_router(card_router)


@app.get("/", response_model=SuccessResponse[dict[str, str]])
async def get_root():
    return SuccessResponse[dict[str, str]](data={"Hello": "AvengersBank"})
