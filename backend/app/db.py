from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.core.config import get_settings

settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, future=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def _ensure_payment_destination_column() -> None:
    """Keep existing installations compatible with the destination-type feature."""
    inspector = inspect(engine)
    if "payment_accounts" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("payment_accounts")}
    if "destination_type" in columns:
        return
    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE payment_accounts "
                "ADD COLUMN destination_type VARCHAR(20) NOT NULL DEFAULT 'IBAN'"
            )
        )


def initialize_database() -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_payment_destination_column()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
