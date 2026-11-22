"""Read an exported Process Monitor CSV or XML file into a timeline.

The importer reads CSV columns by their header names. XML captures may also
contain stack frames, which travel with the corresponding events in the timeline.
"""
from __future__ import annotations

import csv
import io
import xml.etree.ElementTree as ET

from ..events import BlackboxEvent, EventType
from ..timeline import Timeline


def classify_operation(op: str, path: str = "") -> EventType:
    """Map a ProcMon operation (+ its target path) onto an :class:`EventType`."""
    o = (op or "").strip().lower()
    p = (path or "").lower()
    if ("\\pipe\\" in p or "/pipe/" in p or "namedpipe" in p or "mailslot" in p
            or "sharedmem" in p or "pipe" in o or "mailslot" in o):
        return EventType.IPC
    if o.startswith("process start") or o == "process create":
        return EventType.PROCESS_START
    if o.startswith("process exit"):
        return EventType.PROCESS_EXIT
    if o.startswith("thread create"):
        return EventType.THREAD_START
    if o.startswith("thread exit"):
        return EventType.THREAD_EXIT
    if o == "load image" or o == "image load":
        return EventType.IMAGE_LOAD
    if o.startswith("tcp") or o.startswith("udp"):
        return EventType.TCP_CONNECT
    if o.startswith("reg"):
        if any(k in o for k in ("setvalue", "createkey", "setinfo", "deletevalue",
                                "deletekey", "setkeysecurity", "renamekey")):
            return EventType.REG_WRITE
        if "openkey" in o:
            return EventType.REG_OPEN
        return EventType.REG_QUERY
    if o == "createfile":
        return EventType.FILE_OPEN
    if o == "readfile":
        return EventType.FILE_READ
    if o == "writefile":
        return EventType.FILE_WRITE
    if "file" in o:
        return EventType.FILE_OPEN
    return EventType.UNKNOWN


def _parse_time_of_day(s: str) -> float | None:
    """ProcMon 'Time of Day' -> seconds-of-day float. Returns None if unparseable."""
    if not s:
        return None
    s = s.strip()
    ampm = 0
    up = s.upper()
    if up.endswith("AM") or up.endswith("PM"):
        ampm = 1 if up.endswith("AM") else 2
        s = s[:-2].strip()
    try:
        h, m, rest = s.split(":")
        sec = float(rest)
        hh = int(h)
        if ampm == 2 and hh != 12:
            hh += 12
        elif ampm == 1 and hh == 12:
            hh = 0
        return hh * 3600 + int(m) * 60 + sec
    except (ValueError, IndexError):
        return None


def _int(v) -> int | None:
    try:
        return int(str(v).strip())
    except (ValueError, TypeError):
        return None


def _lower_keys(row: dict) -> dict:
    return {(k or "").strip().lower(): v for k, v in row.items()}


def _row_to_event(r: dict) -> tuple[BlackboxEvent, float | None]:
    """One lower-keyed CSV row -> (event, raw time-of-day). ``ts`` is left un-rebased
    (0.0); the caller rebases. Shared by the whole-string and streaming paths."""
    op = r.get("operation", "")
    path = r.get("path", "")
    ev = BlackboxEvent(
        type=classify_operation(op, path), source="procmon", ts=0.0,
        operation=op, object=path, result=r.get("result", ""),
        detail=r.get("detail", ""), pid=_int(r.get("pid")), tid=_int(r.get("tid")),
    )
    return ev, _parse_time_of_day(r.get("time of day", ""))


def from_csv(text: str, label: str = "procmon", outcome: str = "") -> Timeline:
    """Parse a ProcMon CSV export **string** into a :class:`Timeline`. Holds the whole
    input in memory -- for large captures prefer :func:`stream_file` (+ the reducer)."""
    tl = Timeline(label=label, outcome=outcome, meta={"sensor": "procmon-csv"})
    rows = [_row_to_event(_lower_keys(raw)) for raw in csv.DictReader(io.StringIO(text))]
    base = min((t for _, t in rows if t is not None), default=0.0)
    for idx, (ev, tod) in enumerate(rows):
        ev.ts = (tod - base) if tod is not None else float(idx)
        tl.add(ev)
    return tl


def stream_file(path: str, encoding: str = "utf-8-sig"):
    """Yield events from a ProcMon CSV **without loading the file into memory**.

    ``csv.DictReader`` over the open file streams row by row; timestamps are rebased to
    the first timed row (ProcMon captures are chronological), so the working set stays
    bounded no matter how large the capture. Feed this straight into the reducer."""
    with open(path, encoding=encoding, errors="replace", newline="") as fh:
        base = None
        for idx, raw in enumerate(csv.DictReader(fh)):
            ev, tod = _row_to_event(_lower_keys(raw))
            if tod is not None and base is None:
                base = tod
            ev.ts = (tod - base) if (tod is not None and base is not None) else float(idx)
            yield ev


def from_xml(text: str, label: str = "procmon", outcome: str = "") -> Timeline:
    """Best-effort parse of a ProcMon XML export (stacks included when present)."""
    tl = Timeline(label=label, outcome=outcome, meta={"sensor": "procmon-xml"})
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return tl

    def child(el, *names):
        for n in names:
            found = el.find(n)
            if found is not None and found.text is not None:
                return found.text.strip()
        return ""

    events = root.iter("event")
    parsed = []
    for el in events:
        tod = _parse_time_of_day(child(el, "Time_of_Day", "Time_Of_Day", "TimeOfDay"))
        parsed.append((el, tod))
    base = min((t for _, t in parsed if t is not None), default=0.0)
    for idx, (el, tod) in enumerate(parsed):
        op = child(el, "Operation")
        path = child(el, "Path")
        stack = []
        st = el.find("stack")
        if st is not None:
            for fr in st.findall("frame"):
                loc = child(fr, "location", "module", "path")
                if loc:
                    stack.append(loc)
        ev = BlackboxEvent(
            type=classify_operation(op, path),
            source="procmon",
            ts=(tod - base) if tod is not None else float(idx),
            operation=op,
            object=path,
            result=child(el, "Result"),
            detail=child(el, "Detail"),
            pid=_int(child(el, "PID", "ProcessId")),
            tid=_int(child(el, "TID", "ThreadId")),
            stack=stack,
        )
        tl.add(ev)
    return tl


def from_file(path: str, label: str = "procmon", outcome: str = "") -> Timeline:
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        text = f.read()
    if path.lower().endswith(".xml"):
        return from_xml(text, label=label, outcome=outcome)
    return from_csv(text, label=label, outcome=outcome)
