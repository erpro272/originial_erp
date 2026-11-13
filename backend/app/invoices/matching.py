"""Match an invoice's buyer to the Customer Master: GSTIN first, then name/phone/email."""

import re
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from rapidfuzz import fuzz
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.gst import is_valid_gstin
from app.customers import service as customers
from app.invoices.normalize import v

_NOISE = {"pvt", "private", "ltd", "limited", "llp", "co", "company", "corp", "corporation", "inc", "the", "india",
          "and", "m/s", "ms"}  # fmt: skip
STRONG = 95
POSSIBLE = 80


def clean_name(name: str) -> str:
    s = re.sub(r"\bm\s*/\s*s\.?", " ", name.lower()).replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return " ".join(w for w in s.split() if w not in _NOISE)


@dataclass
class Candidate:
    customer_id: uuid.UUID
    name: str
    gstin: str | None
    score: int
    reasons: list[str] = field(default_factory=list)
    gstin_conflict: bool = False


@dataclass
class MatchResult:
    kind: Literal["existing", "new", "ambiguous"]
    customer_id: uuid.UUID | None
    candidates: list[Candidate]
    message: str
    prefill: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["customer_id"] = str(self.customer_id) if self.customer_id else None
        for c in d["candidates"]:
            c["customer_id"] = str(c["customer_id"])
        return d


def prefill(doc: dict[str, Any]) -> dict[str, Any]:
    """Values for the "Create customer" form, from the invoice's buyer section."""
    gstin = v(doc, "buyer_gstin")
    addresses = []
    if v(doc, "buyer_billing_address"):
        addresses.append({"kind": "billing", "line1": v(doc, "buyer_billing_address"),
                          "state_code": v(doc, "buyer_state_code") or v(doc, "buyer_state")})  # fmt: skip
    if v(doc, "buyer_shipping_address") and v(doc, "buyer_shipping_address") != v(
        doc, "buyer_billing_address"
    ):
        addresses.append({"kind": "shipping", "line1": v(doc, "buyer_shipping_address")})
    contacts = []
    if v(doc, "buyer_contact_person"):
        contacts.append({"name": v(doc, "buyer_contact_person"), "phone": v(doc, "buyer_phone"),
                         "email": v(doc, "buyer_email"), "is_primary": True})  # fmt: skip
    return {
        "name": v(doc, "buyer_name"),
        "gstin": gstin if gstin and is_valid_gstin(gstin) else None,
        "pan": v(doc, "buyer_pan"),
        "state_code": v(doc, "buyer_state_code") or v(doc, "buyer_state"),
        "phone": v(doc, "buyer_phone"),
        "email": v(doc, "buyer_email"),
        "addresses": addresses,
        "contacts": contacts,
    }


def digits(s: str | None) -> str:
    return re.sub(r"\D", "", s or "")[-10:]


async def match_customer(session: AsyncSession, doc: dict[str, Any]) -> MatchResult:
    name = v(doc, "buyer_name") or ""
    gstin = v(doc, "buyer_gstin")
    gstin = gstin if gstin and is_valid_gstin(gstin) else None
    phone, email = v(doc, "buyer_phone"), v(doc, "buyer_email")
    pre = prefill(doc)

    if gstin and (c := await customers.find_by_gstin(session, gstin)):
        return MatchResult("existing", c.id, [Candidate(c.id, c.name, c.gstin, 100, ["Same GSTIN"])],
                           f"Matched to {c.name} by GSTIN.", pre)  # fmt: skip

    target = clean_name(name)
    cands: list[Candidate] = []
    for c in await customers.active_customers(session):
        reasons, score = [], 0
        if target:
            score = int(fuzz.token_set_ratio(target, clean_name(c.name)))
            if score >= POSSIBLE:
                reasons.append(f"Similar name ({score}%)")
        if phone and c.phone and digits(phone) == digits(c.phone):
            reasons.append("Same phone")
            score = max(score, 96)
        if email and c.email and email.lower() == c.email.lower():
            reasons.append("Same email")
            score = max(score, 96)
        if reasons:
            conflict = bool(gstin and c.gstin and c.gstin != gstin)
            if conflict:
                reasons.append("Different GSTIN")
            cands.append(Candidate(c.id, c.name, c.gstin, score, reasons, conflict))
    cands.sort(key=lambda x: -x.score)
    cands = cands[:5]

    if not cands:
        return MatchResult(
            "new", None, [], f"No customer like '{name}' yet: a new customer will be created.", pre
        )
    top = cands[0]
    decisive = (not gstin and top.score >= STRONG and not top.gstin_conflict
                and (len(cands) == 1 or cands[1].score < POSSIBLE))  # fmt: skip
    if decisive:
        return MatchResult(
            "existing", top.customer_id, cands, f"Matched to {top.name} ({', '.join(top.reasons)}).", pre
        )
    if any(c.gstin_conflict for c in cands):
        msg = "Possible duplicate: a customer with a similar name has a different GSTIN. Choose one, or create a new customer."
    else:
        msg = "Not sure which customer this is. Choose one, or create a new customer."
    return MatchResult("ambiguous", None, cands, msg, pre)
