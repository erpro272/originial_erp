"""The assistant's built-in ERP guide (`guide.md`): how screens work, how to do things, and the logic behind the
numbers. Pure keyword search (no DB, no model): the guide is small and its words are known."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

GUIDE = Path(__file__).with_name("guide.md")

STOP = set(["a", "an", "and", "are", "as", "at", "be", "by", "can", "could", "do", "does", "did", "for", "from", "has", "have", "how", "i", "if", "in", "is", "it", "its", "me", "my", "of", "on", "or", "our", "please", "should", "so", "tell", "that", "the", "this", "to", "us", "was", "we", "what", "when", "where", "which", "who", "why", "will", "with", "would", "you", "your", "there", "their", "them", "they", "then", "than", "any", "some", "about", "into"])  # fmt: skip


@dataclass(frozen=True)
class Section:
    title: str
    keywords: tuple[str, ...]
    needs: str | None
    screen: str | None
    setting: str | None
    body: str


def stem(w: str) -> str:
    for suf in ("ation", "al", "ing", "ed", "es", "s"):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            w = w[: -len(suf)]
            break
    return w[:-1] if len(w) > 4 and w.endswith("e") else w


def words(text: str) -> set[str]:
    return {stem(w) for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP and len(w) > 1}


@lru_cache
def sections() -> list[Section]:
    out: list[Section] = []
    for block in GUIDE.read_text(encoding="utf-8").split("\n## ")[1:]:
        title, _, rest = block.partition("\n")
        meta: dict[str, str] = {}
        body: list[str] = []
        for line in rest.splitlines():
            m = re.match(r"^(keywords|needs|screen|setting):\s*(.*)$", line)
            if m and not body:
                meta[m.group(1)] = m.group(2).strip()
            else:
                body.append(line)
        kws = tuple(k.strip().lower() for k in meta.get("keywords", "").split(",") if k.strip())
        out.append(Section(title.strip(), kws, meta.get("needs"), meta.get("screen"), meta.get("setting"),
                           "\n".join(body).strip()))  # fmt: skip
    return out


def search(question: str, k: int = 3) -> list[Section]:
    """Best sections for a question: title words weigh most, then keywords, then body; a whole keyword phrase in the
    question is a strong signal."""
    q = words(question)
    ql = " " + re.sub(r"[^a-z0-9]+", " ", question.lower()) + " "
    scored: list[tuple[float, int, Section]] = []
    for i, s in enumerate(sections()):
        title, kw, body = words(s.title), words(" ".join(s.keywords)), words(s.body)
        score = sum(3 if w in title else 2 if w in kw else 0.5 if w in body else 0 for w in q)
        score += sum(4 for p in s.keywords if " " in p and f" {p} " in ql)
        if score > 0:
            scored.append((score, -i, s))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    best = scored[0][0] if scored else 0
    return [s for sc, _, s in scored[:k] if sc >= max(1.5, best * 0.4)]


def brief(question: str, can: Callable[[str], bool | None], k: int = 3, limit: int = 3200) -> str:
    """The guide sections that match a question, as notes for the system prompt (so every answer is grounded in how
    the ERP really works, without an extra model round). Empty when nothing matches well."""
    q = words(question)
    if len(q) < 2 and not any(p in question.lower() for s in sections() for p in s.keywords if " " in p):
        return ""
    parts = []
    for s in search(question, k):
        allowed = can(s.needs) if s.needs else None
        who = (
            ""
            if allowed is None
            else " · the user's role CAN do this"
            if allowed
            else " · the user's role CANNOT do this"
        )
        parts.append(f"### {s.title} ({s.screen or 'ERP'}{who})\n{s.body}")
    text = "\n\n".join(parts)
    return text[:limit]
