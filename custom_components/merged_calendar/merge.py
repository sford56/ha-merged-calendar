"""Duplicate matcher + merger for calendar events.

Pure Python, no Home Assistant imports, so it can be tested on its own. This is a
line-for-line port of the wall panel's merge.js; the two must stay in step.

Events are plain dicts: summary, description, location, uid, start, end, where
start/end are ISO strings: "YYYY-MM-DD" for all-day, full datetime with offset
otherwise (exactly what calendar.get_events returns).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import re
from typing import Any

FILLER = {
    "reservation", "reservations", "reserved", "booking", "booked", "confirmed",
    "confirmation", "appointment", "appt", "event", "at", "for", "the", "a", "an",
    "with", "w", "and", "to", "of", "on", "in", "your", "my", "our", "is", "from",
    "need", "acceptance", "status", "pending", "scheduled", "upcoming",
}
ADDRESS_FILLER = {
    "united", "states", "usa", "us", "mi", "michigan", "rd", "road", "st", "street",
    "ave", "avenue", "blvd", "boulevard", "dr", "drive", "ln", "lane", "ct", "court",
    "hwy", "highway", "pkwy", "parkway", "n", "s", "e", "w", "suite", "ste", "unit",
}
SYNONYMS = {
    "fly": "flight", "flying": "flight", "flights": "flight", "depart": "flight",
    "departure": "flight", "bday": "birthday", "b": "birthday", "dr": "doctor",
    "doc": "doctor", "appt": "appointment", "mtg": "meeting", "meet": "meeting",
    "practices": "practice", "games": "game", "vs": "game", "supper": "dinner",
    "bfast": "breakfast",
}
GMAIL_MARK = re.compile(r"created from an email you received in gmail", re.I)
GMAIL_BOILERPLATE = re.compile(r"^to see detailed information for automatically created events", re.I)
REF_RE = re.compile(
    r"\b(?:confirmation|reservation|registration|booking|order|ticket|record\s*locator|reference|ref|conf)\b"
    r"[\s.:#-]*(?:number|no\.?|code|id|#)?[\s.:#-]*([A-Z0-9][A-Z0-9-]{4,})",
    re.I,
)
AUTHORITATIVE_RE = re.compile(r"business name\s*:|confirmation|booked via|order #", re.I)


# ------------------------------------------------------------------ text utils
def words(s: Any) -> list[str]:
    s = str(s or "").lower()
    s = re.sub(r"['’]s\b", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return [w for w in s.split() if w]


def title_tokens(s: Any) -> list[str]:
    return [t for t in (SYNONYMS.get(w, w) for w in words(s)) if t not in FILLER]


def lev1(a: str, b: str) -> bool:
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    i = j = edits = 0
    while i < la and j < lb:
        if a[i] == b[j]:
            i += 1
            j += 1
            continue
        edits += 1
        if edits > 1:
            return False
        if la > lb:
            i += 1
        elif lb > la:
            j += 1
        else:
            i += 1
            j += 1
    return edits + (la - i) + (lb - j) <= 1


def token_match(a: str, b: str) -> bool:
    if a == b:
        return True
    if len(a) >= 4 and len(b) >= 4:
        if a.startswith(b) or b.startswith(a):
            return True
        if len(a) >= 5 and len(b) >= 5 and lev1(a, b):
            return True
    return False


def token_overlap(ta: list[str], tb: list[str]) -> float:
    if not ta or not tb:
        return 0.0
    small, big = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    uniq = list(dict.fromkeys(small))
    hit = sum(1 for t in uniq if any(token_match(t, u) for u in big))
    return hit / len(uniq)


def norm_line(s: Any) -> str:
    s = re.sub(r"\s+", " ", str(s).lower())
    return re.sub(r"[\s.,;:]+$", "", s).strip()


# ------------------------------------------------------------- event features
def is_all_day(ev: dict) -> bool:
    return len(str(ev.get("start", ""))) == 10


def day_num(s: str) -> int:
    return date.fromisoformat(s[:10]).toordinal()


def parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def refs(ev: dict) -> set[str]:
    text = "\n".join(str(x) for x in (ev.get("summary"), ev.get("description"), ev.get("location")) if x)
    out: set[str] = set()
    for m in REF_RE.finditer(text):
        v = m.group(1).upper().rstrip("-")
        if re.search(r"\d", v) and len(re.sub(r"[^A-Z0-9]", "", v)) >= 5:
            out.add(v)
    return out


@dataclass
class Address:
    num: str | None
    street: str | None
    place_tokens: list[str]
    raw: str


def address(ev: dict) -> Address | None:
    loc = str(ev.get("location") or "")
    if not loc:
        return None
    w = words(loc)
    num = street = None
    for i in range(len(w) - 1):
        if re.fullmatch(r"\d{1,6}", w[i]) and re.match(r"[a-z]", w[i + 1]) and w[i + 1] not in ADDRESS_FILLER:
            num, street = w[i], w[i + 1]
            break
    place = [t for t in w if t not in ADDRESS_FILLER and not t.isdigit()]
    return Address(num, street, place, loc)


@dataclass
class Feat:
    ev: dict
    calendar: str
    order: int
    all_day: bool
    s: float | None
    e: float | None
    s_day: int
    e_day: int
    gmail: bool
    refs: set[str]
    tokens: list[str]
    addr: Address | None
    authoritative: bool
    idx: int = field(default=0)


def features(ev: dict, calendar: str, order: int) -> Feat:
    all_day = is_all_day(ev)
    start = str(ev["start"])
    end = str(ev.get("end") or start)
    if all_day:
        s_day = day_num(start)
        e_day = day_num(end) if len(end) >= 10 else s_day + 1
        if e_day <= s_day:
            e_day = s_day + 1
        s = e = None
    else:
        s = parse_dt(start).timestamp()
        e = parse_dt(end).timestamp() if len(end) > 10 else s + 3600
        if not e > s:
            e = s + 3600
        s_day = day_num(start)
        e_day = day_num(end) + 1
    desc = str(ev.get("description") or "")
    gmail = bool(GMAIL_MARK.search(desc))
    r = refs(ev)
    return Feat(
        ev=ev, calendar=calendar, order=order, all_day=all_day, s=s, e=e,
        s_day=s_day, e_day=e_day, gmail=gmail, refs=r,
        tokens=title_tokens(ev.get("summary")), addr=address(ev),
        authoritative=gmail or bool(r) or bool(AUTHORITATIVE_RE.search(desc)),
    )


# ------------------------------------------------------------------- matching
def time_relation(a: Feat, b: Feat) -> dict:
    if not a.all_day and not b.all_day:
        ov = min(a.e, b.e) - max(a.s, b.s)
        if ov <= 0:
            return {"ok": False}
        shorter = min(a.e - a.s, b.e - b.s)
        return {"ok": True, "strong": ov / shorter >= 0.5, "starts_close": abs(a.s - b.s) <= 3 * 3600, "mixed": False}
    ov = min(a.e_day, b.e_day) - max(a.s_day, b.s_day)
    if ov <= 0:
        return {"ok": False}
    same = a.all_day and b.all_day and a.s_day == b.s_day and a.e_day == b.e_day
    return {"ok": True, "strong": same, "starts_close": False, "mixed": a.all_day != b.all_day}


def location_match(a: Feat, b: Feat) -> bool | None:
    if not a.addr or not b.addr:
        return None
    if a.addr.num and b.addr.num:
        return a.addr.num == b.addr.num and token_match(a.addr.street, b.addr.street)
    return token_overlap(a.addr.place_tokens, b.addr.place_tokens) >= 0.6


def compare(a: Feat, b: Feat) -> dict:
    shared_ref = bool(a.refs & b.refs)
    t = time_relation(a, b)
    if not t["ok"]:
        same_day = min(a.e_day, b.e_day) > max(a.s_day, b.s_day) or a.s_day == b.s_day
        if shared_ref and same_day:
            return {"match": True, "why": "shared reference # on the same day", "score": 0.0}
        return {"match": False, "why": "no time overlap", "score": 0.0}
    title = token_overlap(a.tokens, b.tokens)
    loc = location_match(a, b)
    why = [f"time {'strong' if t['strong'] else 'overlap'}", f"title {title:.2f}"]
    if loc is not None:
        why.append(f"location {'same' if loc else 'different'}")
    if shared_ref:
        why.append("shared reference #")
    if loc is False and not shared_ref:
        return {"match": False, "why": ", ".join(why), "score": title}

    match = False
    if shared_ref:
        match = True
    elif t["mixed"]:
        match = title >= 0.75 and loc is not False
    elif title >= 0.75 and (t["strong"] or t["starts_close"] or a.all_day):
        match = True
    elif title >= 0.75 and loc is True:
        match = True
    elif title >= 0.34 and loc is True:
        match = True
    elif loc is True and t["strong"] and title > 0:
        match = True
    elif loc is True and t["strong"] and (not a.tokens or not b.tokens):
        match = True

    if match and not shared_ref and loc is not True:
        min_len = min(len(set(a.tokens)), len(set(b.tokens)))
        if min_len < 2 and title < 1:
            match = False
    return {"match": match, "why": ", ".join(why), "score": title}


# -------------------------------------------------------------------- merging
def best_title(group: list[Feat]) -> Feat:
    return sorted(
        group,
        key=lambda f: (f.gmail, -len(set(f.tokens)), f.order, len(str(f.ev.get("summary") or ""))),
    )[0]


def best_location(group: list[Feat]) -> tuple[str | None, list[str]]:
    with_loc = [f for f in group if f.addr]
    if not with_loc:
        return None, []
    with_loc.sort(key=lambda f: (0 if f.addr.num else 1, -len(f.addr.raw)))
    primary = with_loc[0]
    others: list[str] = []

    def alnum_len(s: str) -> int:
        return len(re.sub(r"[^a-z0-9]", "", norm_line(s)))

    for f in with_loc[1:]:
        same = location_match(primary, f) is not False and alnum_len(f.addr.raw) <= alnum_len(primary.addr.raw)
        dup_text = any(norm_line(o) == norm_line(f.addr.raw) for o in [*others, primary.addr.raw])
        if not same and not dup_text:
            others.append(f.addr.raw)
    return re.sub(r"\s*\n\s*", ", ", primary.addr.raw), others


def _fmt_time(ts: float, ref_iso: str) -> str:
    d = datetime.fromtimestamp(ts, tz=parse_dt(ref_iso).tzinfo)
    h = d.hour % 12 or 12
    return f"{h}:{d.minute:02d} {'PM' if d.hour >= 12 else 'AM'}"


def _short(s: Any) -> str:
    s = str(s or "").strip()
    return s if len(s) <= 40 else s[:39] + "…"


def merge_times(group: list[Feat]) -> tuple[str, str, str | None]:
    timed = [f for f in group if not f.all_day]
    if not timed:
        s = min(f.s_day for f in group)
        e = max(f.e_day for f in group)
        return date.fromordinal(s).isoformat(), date.fromordinal(e).isoformat(), None
    # Scott's rule: exact time from the email/booking source when there is one,
    # otherwise the earliest start across all copies.
    auth = [f for f in timed if f.authoritative]
    basis = auth or timed
    s = min(f.s for f in basis)
    e = max(f.e for f in basis)
    ref = next(f for f in basis if f.s == s).ev["start"]
    tz = parse_dt(ref).tzinfo
    distinct: dict[str, Feat] = {}
    for f in timed:
        label = f"{_fmt_time(f.s, f.ev['start'])}–{_fmt_time(f.e, f.ev['start'])}"
        distinct.setdefault(label, f)
    note = None
    if len(distinct) > 1:
        note = "Times on the copies: " + "; ".join(
            f"{label} ({_short(f.ev.get('summary'))})" for label, f in distinct.items()
        )
    return (
        datetime.fromtimestamp(s, tz=tz).isoformat(),
        datetime.fromtimestamp(e, tz=tz).isoformat(),
        note,
    )


def merge_descriptions(group: list[Feat]) -> list[str]:
    seen: set[str] = set()
    lines: list[str] = []
    for f in group:
        for raw in str(f.ev.get("description") or "").splitlines():
            line = raw.strip()
            if not line or GMAIL_BOILERPLATE.search(line):
                continue
            key = norm_line(line)
            if not key or key in seen:
                continue
            if any(key in norm_line(l) for l in lines):
                continue
            shorter = next((i for i, l in enumerate(lines) if norm_line(l) in key), None)
            seen.add(key)
            if shorter is not None:
                lines[shorter] = line
            else:
                lines.append(line)
    return lines


def merge_group(group: list[Feat], names: dict[str, str]) -> tuple[str, dict]:
    title_src = best_title(group)
    start, end, note = merge_times(group)
    loc, other_locs = best_location(group)
    lines = merge_descriptions(group)
    if other_locs:
        lines.append("Also listed at: " + " | ".join(other_locs))
    other_titles: list[str] = []
    for f in group:
        if f is title_src:
            continue
        k = norm_line(f.ev.get("summary") or "")
        if k and k != norm_line(title_src.ev.get("summary") or "") and not any(norm_line(t) == k for t in other_titles):
            other_titles.append(f.ev.get("summary"))
    if other_titles:
        lines.append("Also titled: " + " | ".join(other_titles))
    if note:
        lines.append(note)
    cals = list(dict.fromkeys(names.get(f.calendar, f.calendar) for f in group))
    lines.append(f"Merged from {len(group)} copies ({', '.join(cals)})")
    return title_src.calendar, {
        "start": start,
        "end": end,
        "summary": title_src.ev.get("summary"),
        "description": "\n".join(lines),
        "location": loc,
        "uid": "merged:" + "+".join(sorted(str(f.ev.get("uid") or "") for f in group)),
    }


# ------------------------------------------------------------------ top level
def dedupe(by_calendar: dict[str, list[dict]], order: list[str], names: dict[str, str] | None = None,
           explain: bool = False) -> dict:
    """Collapse duplicates across (and within) calendars.

    Returns {"events": [(calendar, event), ...], "merged": [...], "decisions": [...]}.
    Each output event keeps the calendar of its primary copy.
    """
    names = names or {}
    feats: list[Feat] = []
    for ci, cal in enumerate(order):
        for i, ev in enumerate(by_calendar.get(cal) or []):
            if not ev or not ev.get("start"):
                continue
            f = features(ev, cal, ci * 10000 + i)
            f.idx = len(feats)
            feats.append(f)

    parent = list(range(len(feats)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    decisions = []
    idx = sorted(range(len(feats)), key=lambda i: feats[i].s_day)
    for x in range(len(idx)):
        for y in range(x + 1, len(idx)):
            a, b = feats[idx[x]], feats[idx[y]]
            if b.s_day >= a.e_day + 1:
                break
            r = compare(a, b)
            if explain and (r["match"] or r["score"] > 0 or re.search(r"location same|shared", r["why"])):
                decisions.append({"a": a.ev.get("summary"), "b": b.ev.get("summary"), "day": a.ev["start"][:10], **r})
            if r["match"]:
                parent[find(idx[x])] = find(idx[y])

    groups: dict[int, list[Feat]] = {}
    for i, f in enumerate(feats):
        groups.setdefault(find(i), []).append(f)

    events: list[tuple[str, dict]] = []
    merged = []
    for g in groups.values():
        if len(g) == 1:
            events.append((g[0].calendar, g[0].ev))
        else:
            g.sort(key=lambda f: f.order)
            cal, ev = merge_group(g, names)
            events.append((cal, ev))
            merged.append({"copies": [(f.calendar, f.ev.get("summary"), f.ev["start"], f.ev.get("end")) for f in g],
                           "result": ev, "calendar": cal})
    return {"events": events, "merged": merged, "decisions": decisions}
