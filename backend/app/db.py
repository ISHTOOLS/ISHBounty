from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.core.config import get_settings

settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, future=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def _ensure_schema_compatibility() -> None:
    """Keep existing installations compatible with additive payment fields."""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "payment_accounts" in tables:
        columns = {column["name"] for column in inspector.get_columns("payment_accounts")}
        if "destination_type" not in columns:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE payment_accounts "
                        "ADD COLUMN destination_type VARCHAR(20) NOT NULL DEFAULT 'IBAN'"
                    )
                )
    if "payments" in tables:
        columns = {column["name"] for column in inspector.get_columns("payments")}
        if "payment_destination_id" not in columns:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE payments "
                        "ADD COLUMN payment_destination_id VARCHAR(36)"
                    )
                )


def initialize_database() -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_schema_compatibility()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
