"""Background job: read an uploaded invoice (pages, QR, AI extraction)."""

import asyncio
import json
import logging
import re
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.ai.service import AIError, AIResult, InputFile, get_ai_client
from app.core import keys
from app.core.db import tenant_session
from app.core.storage import get_decrypted, put_encrypted, tenant_key
from app.invoices import files, templates
from app.invoices.fields import SYSTEM_PROMPT, TEXT_FORMAT, ai_schema, instructions
from app.invoices.models import ExtractionRun, InvoiceUpload
from app.invoices.normalize import build_document, overall_confidence
from app.invoices.service import seal

log = logging.getLogger(__name__)


def fixture_hint(file_name: str) -> str:
    stem = file_name.rsplit(".", 1)[0].lower()
    return re.sub(r"[^a-z0-9_]", "_", stem)


async def extract_invoice(_ctx: dict[str, Any], tenant_id: str, upload_id: str) -> str:
    tid, uid = uuid.UUID(tenant_id), uuid.UUID(upload_id)
    async with tenant_session(tid) as s:
        u = await s.get(InvoiceUpload, uid, with_for_update=True)
        if u is None or u.status not in ("uploaded",):
            return "skipped"
        u.status = "extracting"
        key, fmt, name = u.file_key, u.doc_format, u.file_name
    try:
        async with tenant_session(tid) as s:
            cipher = await keys.get_cipher(s, tid)
        data = await get_decrypted(cipher, key)
        det = files.detect(data)
        pages = files.page_images(data, det)
        page_keys = []
        for i, img in enumerate(pages, start=1):
            pk = tenant_key(tid, "invoices", str(uid), f"page-{i}.png")
            await put_encrypted(cipher, pk, files.png_bytes(img))
            page_keys.append(pk)
        qr = files.decode_qr(pages)
        matched = await asyncio.to_thread(templates.extract, pages)
        if matched is not None:  # a known layout: read with OCR, no AI
            tpl, out = matched
            result = AIResult(
                data=out,
                raw_text=json.dumps(out),
                model=f"template:{tpl.id}",
                mode="template",
                stop_reason=None,
            )
        else:
            # vision models read page images (a PDF is sent as its rendered pages)
            ai_files = (
                [InputFile(files.png_bytes(p), "image/png") for p in pages]
                if fmt == "pdf"
                else [InputFile(files.ai_image(data), "image/jpeg")]
            )
            client = get_ai_client()
            text = None
            if client.mode == "live" and templates.available():  # OCR text -> text model (see VisionAIClient)
                text = await asyncio.to_thread(templates.ocr_text, pages)
            result = await client.extract_json(task="invoice", system=SYSTEM_PROMPT,
                                               instructions=instructions() + (TEXT_FORMAT if text else ""),
                                               schema=ai_schema(), files=ai_files, fixture_hint=fixture_hint(name),
                                               text=text)  # fmt: skip
        if result.data is None:
            raise AIError("The AI declined to read this document.")
        doc = build_document(result.data, qr)
        if not doc["is_invoice"]:
            raise AIError("This doesn't look like an invoice.")
    except (files.UnsupportedFile, AIError) as exc:
        await _fail(tid, uid, str(exc))
        return "failed"
    except Exception:
        log.exception("invoice extraction crashed (upload %s)", uid)
        await _fail(tid, uid, "Something went wrong while reading this file. Try again.")
        return "failed"

    async with tenant_session(tid) as s:
        u = await s.get(InvoiceUpload, uid, with_for_update=True)
        assert u is not None
        cipher = await keys.get_cipher(s, tid)
        version = (await s.execute(select(ExtractionRun.version).where(ExtractionRun.upload_id == uid)
                                   .order_by(ExtractionRun.version.desc()).limit(1))).scalar_one_or_none() or 0  # fmt: skip
        s.add(ExtractionRun(upload_id=uid, version=version + 1, source="template" if matched else "model", model=result.model,
                            raw_output="enc:" + cipher.encrypt(result.raw_text, "extraction.raw").hex(),
                            data=seal(doc, cipher)))  # fmt: skip
        conf = overall_confidence(doc)
        u.page_keys, u.page_count, u.qr_data, u.ai_mode = page_keys, len(pages), qr, result.mode
        u.overall_confidence = Decimal(str(conf)) if conf is not None else None
        u.status = "needs_review"
    return "needs_review"


async def _fail(tid: uuid.UUID, uid: uuid.UUID, message: str) -> None:
    async with tenant_session(tid) as s:
        u = await s.get(InvoiceUpload, uid, with_for_update=True)
        if u is not None:
            u.status, u.error = "failed", message
