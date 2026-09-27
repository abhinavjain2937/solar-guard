import os
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine, String, Float, Integer, DateTime, ForeignKey, Text, UniqueConstraint, inspect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

load_dotenv()
URL = os.getenv("DATABASE_URL", "sqlite:///./solarsurd.db")
engine = create_engine(URL, connect_args={"check_same_thread": False} if URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

class Base(DeclarativeBase): pass

class UserRow(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    google_sub: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

class LoginSessionRow(Base):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)

class SiteRow(Base):
    __tablename__ = "sites"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    timezone: Mapped[str] = mapped_column(String(80), default="UTC")
    capacity_kw: Mapped[float] = mapped_column(Float)
    performance_ratio: Mapped[float] = mapped_column(Float, default=0.8, nullable=False)
    inverter_capacity_kw: Mapped[float | None] = mapped_column(Float, nullable=True)
    tilt_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    azimuth_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    commissioned_on: Mapped[str | None] = mapped_column(String(10), nullable=True)
    inverter_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    module_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)

class TelemetryRow(Base):
    __tablename__ = "telemetry"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), index=True)
    timestamp: Mapped[str] = mapped_column(String(40), index=True)
    payload: Mapped[str] = mapped_column(Text)

class DailyGenerationRow(Base):
    __tablename__ = "daily_generation"
    __table_args__ = (UniqueConstraint("site_id", "day", name="uq_daily_generation_site_day"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), index=True)
    day: Mapped[str] = mapped_column(String(10), index=True)
    actual_kwh: Mapped[float] = mapped_column(Float, nullable=False)
    record_kind: Mapped[str] = mapped_column(String(20), default="actual", nullable=False)
    source: Mapped[str] = mapped_column(String(40), default="manual_entry", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

class MonthlyBillRow(Base):
    __tablename__ = "monthly_bills"
    __table_args__ = (UniqueConstraint("site_id", "month", name="uq_monthly_bill_site_month"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), index=True)
    month: Mapped[str] = mapped_column(String(7), index=True)
    consumed_kwh: Mapped[float] = mapped_column(Float, nullable=False)
    exported_kwh: Mapped[float] = mapped_column(Float, nullable=False)
    import_tariff: Mapped[float] = mapped_column(Float, nullable=False)
    export_tariff: Mapped[float] = mapped_column(Float, nullable=False)
    export_credit_inr: Mapped[float] = mapped_column(Float, nullable=False)
    self_use_pct: Mapped[float] = mapped_column(Float, nullable=False, default=60)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

class WarrantyPointRow(Base):
    __tablename__ = "warranty_curve_points"
    __table_args__ = (UniqueConstraint("site_id", "year", name="uq_warranty_site_year"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), index=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    guaranteed_pct: Mapped[float] = mapped_column(Float, nullable=False)

class SyntheticWarrantyRow(Base):
    __tablename__ = "synthetic_warranty_projection"
    __table_args__ = (UniqueConstraint("site_id", "year", name="uq_synthetic_warranty_site_year"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), index=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    generation_kwh: Mapped[float] = mapped_column(Float, nullable=False)
    performance_pct: Mapped[float] = mapped_column(Float, nullable=False)
    record_kind: Mapped[str] = mapped_column(String(24), default="synthetic_projection", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

Base.metadata.create_all(engine)

# Add ownership to databases created before local sign-in existed. The first
# account claims these legacy sites during signup; later accounts see only theirs.
if "owner_id" not in {col["name"] for col in inspect(engine).get_columns("sites")}:
    with engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE sites ADD COLUMN owner_id INTEGER REFERENCES users(id)")
if "performance_ratio" not in {col["name"] for col in inspect(engine).get_columns("sites")}:
    with engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE sites ADD COLUMN performance_ratio FLOAT NOT NULL DEFAULT 0.8")
with engine.begin() as connection:
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_sites_owner_id ON sites (owner_id)")
if "google_sub" not in {col["name"] for col in inspect(engine).get_columns("users")}:
    with engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE users ADD COLUMN google_sub VARCHAR(255)")
with engine.begin() as connection:
    connection.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_google_sub ON users (google_sub)")

