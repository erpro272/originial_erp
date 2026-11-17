"""Writes the demo company documents used by the AI Assistant demo and tests into samples/documents/:
a costing policy and a CNC safety SOP (PDF with a real text layer), and a quality inspection procedure (Word).
Illustrative content for a fastener manufacturer, marked as demo documents.

    uv run python -m scripts.make_sample_documents
"""

from pathlib import Path

import docx

OUT = Path(__file__).resolve().parents[2] / "samples" / "documents"

COSTING = [
    [
        "DEMO DOCUMENT - Costing Policy (Rev 3, April 2026)",
        "",
        "1. Purpose",
        "This policy sets how manufacturing cost is planned, recorded and reviewed for every",
        "customer order (bolts, nuts, flange bolts and steel assemblies).",
        "",
        "2. Standard cost of an order",
        "Standard cost = material + direct labour + machine hours + overheads + packaging.",
        "Overheads are applied at 12% of material, labour and machine cost.",
        "Packaging is charged at the rate in the company rules (per order).",
        "A scrap allowance of 2% of material weight is included in every material estimate.",
        "",
        "3. Night shifts",
        "A night shift may be added to a machine only to protect a committed ship date.",
        "Night shift labour carries a premium of 25% over the day rate for the crew,",
        "plus the machine's night cost per hour. Every night shift added to a plan needs",
        "the owner's approval before it is scheduled, and is reviewed in the monthly cost meeting.",
    ],
    [
        "DEMO DOCUMENT - Costing Policy (Rev 3, April 2026) - page 2",
        "",
        "4. Material price variance",
        "Purchase prices are compared with the standard rate of each material every month.",
        "A material price variance above 5% for any material (for example steel wire rod or",
        "MS bright bar) must be explained by Purchasing with supplier quotes, and the standard",
        "rate is updated if the change is expected to last more than one quarter.",
        "Express freight is allowed only when a shortage would make an order late; its cost is",
        "booked to the order that needed it.",
        "",
        "5. Monthly cost review",
        "Each month Accounts compares planned and actual cost per order: material, labour,",
        "machine hours, scrap and rework. Any order whose margin falls below the company's",
        "minimum margin (18%) is reviewed with Planning and Sales before similar orders are quoted.",
    ],
]

SAFETY = [
    [
        "DEMO DOCUMENT - SOP-07 Safe operation of CNC machines (CNC 01, CNC 02)",
        "",
        "1. Before starting a shift",
        "Wear safety glasses, safety shoes and close-fitting clothing; no gloves near rotating parts.",
        "Test the emergency stop button at the start of every shift and record it in the machine log.",
        "Check coolant level and concentration (5 to 8 percent) and the chip conveyor.",
        "",
        "2. Lockout / tagout",
        "Before changing tools, clearing chips or opening guards, switch off the main isolator,",
        "lock it with your personal padlock and hang a DO NOT OPERATE tag. Only the person who",
        "applied the lock may remove it.",
        "",
        "3. Maintenance",
        "Preventive maintenance every 250 running hours: spindle lubrication, way-oil top-up,",
        "filter cleaning and backlash check. A machine overdue for maintenance must not be",
        "loaded beyond one shift per day until it is serviced.",
        "",
        "4. Incidents",
        "Stop the machine, make it safe, inform the shift supervisor and record the incident",
        "the same day. Near misses are recorded too.",
    ]
]

QUALITY = [
    "DEMO DOCUMENT - QP-03 Incoming material and final inspection",
    "1. Incoming material (gate entry to QC)",
    "Every lot of steel wire rod and bright bar is checked at QC before it is accepted into stock: "
    "mill test certificate, diameter, surface defects and hardness on a sample.",
    "Sampling follows IS 2500 Part 1, normal inspection, AQL 1.0. A rejected quantity stays owed by the supplier "
    "and is recorded against the purchase order.",
    "2. Final inspection of fasteners",
    "M12 bolts of property class 8.8 are tested for hardness and proof load as per ISO 898-1. "
    "Nuts are checked as per ISO 898-2. Thread gauges GO / NO-GO are used on every lot.",
    "3. Non-conforming product",
    "Non-conforming lots are tagged red, moved to the hold area and reviewed by the quality head within 24 hours: "
    "rework, use as is with customer approval, or scrap.",
]


def _pdf(pages: list[list[str]]) -> bytes:
    """A small valid PDF with Helvetica text (a real text layer, so the extractor can read it)."""

    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    objs: list[bytes] = []
    n_pages = len(pages)
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n_pages))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode())
    font_id = 3 + 2 * n_pages
    for i, lines in enumerate(pages):
        ops = ["BT", "/F1 11 Tf", "14 TL", "56 790 Td"]
        for ln in lines:
            ops.append(f"({esc(ln)}) Tj T*")
        ops.append("ET")
        stream = "\n".join(ops).encode("latin-1")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 {font_id} 0 R >> >> "
                    f"/Contents {4 + 2 * i} 0 R >>".encode())  # fmt: skip
        objs.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def build() -> dict[str, bytes]:
    d = docx.Document()
    d.add_heading(QUALITY[0], level=1)
    for line in QUALITY[1:]:
        if line[:2].rstrip(".").isdigit():
            d.add_heading(line, level=2)
        else:
            d.add_paragraph(line)
    import io

    buf = io.BytesIO()
    d.save(buf)
    return {
        "Costing Policy.pdf": _pdf(COSTING),
        "SOP-07 CNC Machine Safety.pdf": _pdf(SAFETY),
        "QP-03 Inspection Procedure.docx": buf.getvalue(),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, data in build().items():
        (OUT / name).write_bytes(data)
        print("wrote", OUT / name)


if __name__ == "__main__":
    main()
