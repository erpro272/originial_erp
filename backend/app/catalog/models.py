import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import BigInteger, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TenantScoped, TimestampMixin


class Product(Base, TenantScoped, TimestampMixin):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("tenant_id", "sku"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    sku: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    unit: Mapped[str] = mapped_column(String(16), default="pcs")
    hsn: Mapped[str | None] = mapped_column(String(16))
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("18"))
    processing_days: Mapped[int] = mapped_column(default=3)
    unit_price_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    unit_cost_paise: Mapped[int] = mapped_column(BigInteger, default=0)


class Material(Base, TenantScoped, TimestampMixin):
    __tablename__ = "materials"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    unit: Mapped[str] = mapped_column(String(16), default="t")


class ProductMaterial(Base, TenantScoped):
    """Bill of materials: how much of a material one unit of a product consumes."""

    __tablename__ = "product_materials"
    __table_args__ = (UniqueConstraint("product_id", "material_id"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    material_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("materials.id"))
    qty_per_unit: Mapped[Decimal] = mapped_column(Numeric(18, 9))


class MaterialStock(Base, TenantScoped, TimestampMixin):
    __tablename__ = "material_stock"
    __table_args__ = (UniqueConstraint("tenant_id", "material_id"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    material_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("materials.id"))
    on_hand: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal("0"))
    next_arrival_date: Mapped[date | None]
    next_arrival_qty: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
