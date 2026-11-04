# alembic/env.py
import asyncio
import selectors
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from avengers_bank.core.config import get_settings
from avengers_bank.core.database import Base
from avengers_bank.domains.accounts.models import (  # noqa: F401
    CheckingAccount,
    CheckingAccountHistory,
    DepositAccount,
    DepositAccountHistory,
    SavingsAccount,
    SavingsAccountHistory,
)
from avengers_bank.domains.cards.models import (  # noqa: F401
    CreditCard,
    CreditCardHistory,
    DebitCard,
    DebitCardHistory,
)
from avengers_bank.domains.products.models import AccountProduct, CardProduct  # noqa: F401
from avengers_bank.domains.users.models import User  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))
if config.config_file_name and config.attributes.get("configure_logging", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)
target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(
        url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata,
        literal_binds=True, dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations():
    engine = async_engine_from_config(
        config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool,
    )
    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    if sys.platform == "win32":
        asyncio.run(
            run_async_migrations(),
            loop_factory=lambda: asyncio.SelectorEventLoop(
                selectors.SelectSelector()
            ),
        )
    else:
        asyncio.run(run_async_migrations())
