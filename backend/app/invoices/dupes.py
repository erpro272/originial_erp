"""Duplicate invoice detection (Section 9 "Duplicate invoice flag")."""

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.gst import financial_year
from app.invoices.models import Invoice
from app.invoices.normalize import v


@dataclass
class Duplicate:
    flag: Literal["none", "possible", "exact"]
    invoice_id: uuid.UUID | None = None
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "flag": self.flag,
            "invoice_id": str(self.invoice_id) if self.invoice_id else None,
            "message": self.message,
        }


def _label(inv: Invoice) -> str:
    return (
        f"{inv.invoice_number or 'invoice'} of {inv.invoice_date:%d %b %Y}"
        if inv.invoice_date
        else (inv.invoice_number or "an invoice")
    )


async def find_duplicate(
    session: AsyncSession, doc: dict[str, Any], customer_id: uuid.UUID | None
) -> Duplicate:
    """exact: same seller GSTIN + number + FY, or same IRN. possible: same customer, date and total."""
    number, irn, seller = v(doc, "invoice_number"), v(doc, "irn"), v(doc, "seller_gstin")
    inv_date = date.fromisoformat(v(doc, "invoice_date")) if v(doc, "invoice_date") else None
    total = v(doc, "grand_total")
    if irn:
        hit = (await session.execute(select(Invoice).where(Invoice.irn == irn))).scalars().first()
        if hit:
            return Duplicate("exact", hit.id, f"Already saved: {_label(hit)} has the same IRN.")
    if seller and number and inv_date:
        hit = (
            (
                await session.execute(
                    select(Invoice).where(
                        Invoice.seller_gstin == seller,
                        Invoice.invoice_number == number,
                        Invoice.financial_year == financial_year(inv_date),
                    )
                )
            )
            .scalars()
            .first()
        )
        if hit:
            return Duplicate(
                "exact",
                hit.id,
                f"Already saved: {_label(hit)} (same seller GSTIN, number and financial year).",
            )
    if customer_id and inv_date and total is not None:
        hit = (
            (
                await session.execute(
                    select(Invoice).where(
                        Invoice.customer_id == customer_id,
                        Invoice.invoice_date == inv_date,
                        Invoice.grand_total_paise == total,
                    )
                )
            )
            .scalars()
            .first()
        )
        if hit:
            return Duplicate("possible", hit.id,
                             f"Possible duplicate of {_label(hit)}: same customer, date and grand total.")  # fmt: skip
    return Duplicate("none")
