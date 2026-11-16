"""purchase lifecycle: dispatch, gate entry, QC, linked orders, PO timeline

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-16
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.rls import APP_ROLE, enable_tenant_rls

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("purchase_orders", sa.Column("order_numbers", postgresql.JSONB(), nullable=False,
                                               server_default=sa.text("'[]'::jsonb")))  # fmt: skip
    op.add_column("purchase_orders", sa.Column("priority", sa.String(8), nullable=True))
    op.add_column("purchase_orders", sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("purchase_orders", sa.Column("gate_qty", sa.Numeric(14, 3), nullable=True))
    op.add_column("purchase_orders", sa.Column("gate_ref", sa.String(100), nullable=True))
    op.add_column("purchase_orders", sa.Column("gate_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("purchase_order_lines", sa.Column("rejected_qty", sa.Numeric(14, 3), nullable=False,
                                                    server_default="0"))  # fmt: skip
    op.create_table(
        "po_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("po_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(),
                  server_default=sa.text("NULLIF(current_setting('app.tenant_id', true), '')::uuid"), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], name=op.f("fk_po_events_actor_id_users")),
        sa.ForeignKeyConstraint(["po_id"], ["purchase_orders.id"], name=op.f("fk_po_events_po_id_purchase_orders"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_po_events")),
    )  # fmt: skip
    op.create_index(op.f("ix_po_events_po_id"), "po_events", ["po_id"], unique=False)
    op.create_index(op.f("ix_po_events_tenant_id"), "po_events", ["tenant_id"], unique=False)
    enable_tenant_rls("po_events")
    op.execute(f"REVOKE UPDATE, DELETE ON po_events FROM {APP_ROLE}")
    # existing POs: their linked orders come from Planning's requests
    op.execute("""
        UPDATE purchase_orders po SET order_numbers = sub.nums
        FROM (SELECT r.tenant_id, r.po_number, jsonb_agg(DISTINCT n) AS nums
              FROM purchase_requests r, jsonb_array_elements_text(r.order_numbers) n
              WHERE r.po_number IS NOT NULL GROUP BY r.tenant_id, r.po_number) sub
        WHERE po.tenant_id = sub.tenant_id AND po.number = sub.po_number
    """)
    op.execute("""
        INSERT INTO po_events (id, tenant_id, po_id, kind, summary, data, created_at)
        SELECT gen_random_uuid(), tenant_id, id, 'raised', number || ' raised', '{}'::jsonb, created_at
        FROM purchase_orders
    """)


def downgrade() -> None:
    op.drop_table("po_events")
    op.drop_column("purchase_order_lines", "rejected_qty")
    for c in ("gate_at", "gate_ref", "gate_qty", "dispatched_at", "priority", "order_numbers"):
        op.drop_column("purchase_orders", c)
