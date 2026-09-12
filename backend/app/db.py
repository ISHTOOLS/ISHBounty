from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import get_settings

settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, future=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def ensure_payment_destination_schema() -> None:
    """Add KOLAS destination metadata without requiring an external migration service."""
    inspector = inspect(engine)
    if "payment_accounts" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("payment_accounts")}
    additions = {
        "destination_type": "VARCHAR(16)",
        "destination_fingerprint": "VARCHAR(64)",
        "destination_masked": "VARCHAR(128)",
    }
    with engine.begin() as connection:
        for name, sql_type in additions.items():
            if name not in columns:
                connection.execute(text(f"ALTER TABLE payment_accounts ADD COLUMN {name} {sql_type}"))
        connection.execute(
            text(
                "UPDATE payment_accounts "
                "SET destination_type = 'IBAN', "
                "destination_fingerprint = COALESCE(destination_fingerprint, iban_fingerprint), "
                "destination_masked = COALESCE(destination_masked, iban_masked) "
                "WHERE destination_type IS NULL"
            )
        )


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
