"""Read an exported Windows Event Trace XML file into a timeline.

Each event contains metadata, named fields, and optional task and opcode labels.
The importer classifies events by those labels, the provider and opcode, or the
shape of the fields. The streaming reader processes exported XML incrementally.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from ..events import BlackboxEvent, EventType
from ..timeline import Timeline

# Classic NT-kernel MOF class GUIDs (lower-case, no braces) + per-class opcode maps.
# Used only when RenderingInfo text is absent; EventData-shape is the final fallback.
_KERNEL = {
    "3d6fa8d0-fe05-11d0-9dda-00c04fd7ba7c": ("process", {1: EventType.PROCESS_START,
        3: EventType.PROCESS_START, 2: EventType.PROCESS_EXIT, 4: EventType.PROCESS_EXIT}),
    "3d6fa8d1-fe05-11d0-9dda-00c04fd7ba7c": ("thread", {1: EventType.THREAD_START,
        3: EventType.THREAD_START, 2: EventType.THREAD_EXIT, 4: EventType.THREAD_EXIT}),
    "2cb15d1d-5fc1-11d2-abe1-00a0c911f518": ("image", {10: EventType.IMAGE_LOAD,
        3: EventType.IMAGE_LOAD, 2: EventType.IMAGE_UNLOAD}),
    "90cbdc39-4a3e-11d1-84f4-0000f80464e3": ("fileio", {64: EventType.FILE_OPEN,
        67: EventType.FILE_READ, 68: EventType.FILE_WRITE}),
    "ae53722e-c863-11d2-8659-00c04fa321a1": ("registry", {}),   # opcodes vary -> heuristic
    "9a280ac0-c8e0-11d1-84e2-00c04fb998a2": ("tcpip", {}),      # any -> TCP_CONNECT
}
_OBJECT_FIELDS = {
    EventType.IMAGE_LOAD: ("ImageFileName", "FileName", "ImageName"),
    EventType.IMAGE_UNLOAD: ("ImageFileName", "FileName", "ImageName"),
    EventType.PROCESS_START: ("ImageFileName", "ProcessName", "FileName"),
    EventType.PROCESS_EXIT: ("ImageFileName", "ProcessName", "FileName"),
    EventType.REG_OPEN: ("KeyName", "RelativeName", "ValueName", "Name"),
    EventType.REG_QUERY: ("KeyName", "RelativeName", "ValueName", "Name"),
    EventType.REG_WRITE: ("KeyName", "RelativeName", "ValueName", "Name"),
    EventType.FILE_OPEN: ("FileName", "OpenPath", "Name"),
    EventType.FILE_READ: ("FileName", "OpenPath", "Name"),
    EventType.FILE_WRITE: ("FileName", "OpenPath", "Name"),
    EventType.IPC: ("FileName", "OpenPath", "Name"),
}
_STATUS_FIELDS = ("Status", "NtStatus", "ExitStatus", "ReturnValue")
_SUCCESS_STATUS = {"0", "0x0", "0x00000000", ""}


def _local(tag) -> str:
    """Local tag name, ignoring any XML namespace (``{ns}Event`` -> ``Event``)."""
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


def _child(el, name):
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


def _iter_events(root):
    for el in root.iter():
        if _local(el.tag) == "Event":
            yield el


def _event_data(ev_el) -> dict:
    out = {}
    ed = _child(ev_el, "EventData")
    if ed is None:
        return out
    for d in ed:
        if _local(d.tag) != "Data":
            continue
        name = d.get("Name") or d.get("name")
        if name:
            out[name] = (d.text or "").strip()
    return out


def _parse_iso(s: str):
    """ISO-8601 SystemTime -> epoch seconds (float), or None. Tolerates the trailing
    ``Z`` and 100-ns (7-digit) fractional seconds that ``tracerpt`` emits."""
    if not s:
        return None
    import datetime
    t = s.strip().replace("Z", "+00:00")
    if "." in t:
        head, frac = t.split(".", 1)
        off = ""
        for sign in ("+", "-"):
            if sign in frac:
                frac, off = frac.split(sign, 1)
                off = sign + off
                break
        frac = "".join(ch for ch in frac if ch.isdigit())[:6].ljust(6, "0")
        t = f"{head}.{frac}{off}"
    try:
        dt = datetime.datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


def _status_to_result(data: dict) -> str:
    for k in _STATUS_FIELDS:
        if k in data:
            v = str(data[k]).strip()
            if v.lower() in _SUCCESS_STATUS:
                return "SUCCESS"
            if v.lower().startswith("0x"):
                return v
            try:
                n = int(v)
                return "SUCCESS" if n == 0 else ("0x%X" % (n & 0xFFFFFFFF))
            except ValueError:
                return v
    return ""


def _classify_text(task: str, opcode: str) -> EventType | None:
    t, o = (task or "").strip().lower(), (opcode or "").strip().lower()
    if t == "process":
        return EventType.PROCESS_EXIT if o in ("end", "stop", "dcend") else EventType.PROCESS_START
    if t == "thread":
        return EventType.THREAD_EXIT if o in ("end", "stop") else EventType.THREAD_START
    if t == "image":
        return EventType.IMAGE_UNLOAD if o in ("unload",) else EventType.IMAGE_LOAD
    if t in ("fileio", "file"):
        if o == "read":
            return EventType.FILE_READ
        if o in ("write",):
            return EventType.FILE_WRITE
        return EventType.FILE_OPEN
    if t in ("registry", "reg"):
        if any(k in o for k in ("setvalue", "setinformation", "create", "delete", "setsecurity")):
            return EventType.REG_WRITE
        if "open" in o:
            return EventType.REG_OPEN
        return EventType.REG_QUERY
    if t.startswith("tcp") or t.startswith("udp"):
        return EventType.TCP_CONNECT
    return None


def _classify_shape(data: dict) -> EventType:
    if "ExitStatus" in data:
        return EventType.PROCESS_EXIT
    if "ImageBase" in data and (data.get("ImageFileName") or data.get("FileName")):
        return EventType.IMAGE_LOAD
    if ("daddr" in data or "dport" in data) or ("saddr" in data and "sport" in data):
        return EventType.TCP_CONNECT
    if "KeyName" in data or "KeyHandle" in data or (data.get("ValueName") is not None and "Status" in data):
        return EventType.REG_QUERY
    if ("ParentId" in data or "CommandLine" in data) and "ImageFileName" in data:
        return EventType.PROCESS_START
    if data.get("FileName") or data.get("OpenPath") or "IrpPtr" in data or "FileObject" in data:
        return EventType.FILE_OPEN
    if "TThreadId" in data or ("StackBase" in data and "ProcessId" in data):
        return EventType.THREAD_START
    return EventType.UNKNOWN


def _resolve_object(etype: EventType, data: dict) -> str:
    if etype == EventType.TCP_CONNECT:
        addr = data.get("daddr") or data.get("saddr") or ""
        port = data.get("dport") or data.get("sport") or ""
        return f"{addr}:{port}" if (addr or port) else ""
    for k in _OBJECT_FIELDS.get(etype, ()):
        if data.get(k):
            return data[k]
    for k in ("FileName", "ImageFileName", "KeyName", "Name", "OpenPath"):
        if data.get(k):
            return data[k]
    return ""


def _is_pipe(path: str) -> bool:
    p = (path or "").lower().replace("/", "\\")
    return "\\device\\namedpipe" in p or "\\pipe\\" in p or "mailslot" in p


def _int(v):
    try:
        return int(str(v).strip(), 0)
    except (ValueError, TypeError):
        return None


def _event_from_el(ev_el) -> tuple[BlackboxEvent, float | None]:
    """Turn one ``<Event>`` element into ``(event, raw_ts)``. ``ts`` is left un-rebased
    (0.0); the caller rebases. Shared by the whole-DOM and streaming paths."""
    system = _child(ev_el, "System")
    if system is None or len(system) == 0:
        system = ev_el
    prov = _child(system, "Provider")
    guid = ((prov.get("Guid") or prov.get("guid")) if prov is not None else "") or ""
    guid = guid.strip().strip("{}").lower()
    opcode_el = _child(system, "Opcode")
    opcode_num = (opcode_el.text or "").strip() if opcode_el is not None else ""
    tc = _child(system, "TimeCreated")
    ts = _parse_iso(tc.get("SystemTime")) if tc is not None else None
    exe = _child(system, "Execution")
    exe_pid = exe.get("ProcessID") if exe is not None else None
    exe_tid = exe.get("ThreadID") if exe is not None else None

    # human-readable task/opcode live in RenderingInfo
    rtask = ropcode = ""
    ri = _child(ev_el, "RenderingInfo")
    if ri is not None:
        ro, rt = _child(ri, "Opcode"), _child(ri, "Task")
        ropcode = (ro.text or "").strip() if ro is not None else ""
        rtask = (rt.text or "").strip() if rt is not None else ""

    data = _event_data(ev_el)

    # classify: rendering text -> kernel GUID+opcode -> EventData shape
    etype = _classify_text(rtask, ropcode)
    cls = "rendering"
    if etype is None and guid in _KERNEL:
        klass, opmap = _KERNEL[guid]
        try:
            etype = opmap.get(int(opcode_num))
        except ValueError:
            etype = None
        if etype is None:
            etype = _classify_text(klass, ropcode) or _classify_shape(data)
        cls = "guid"
    if etype is None:
        etype = _classify_shape(data)
        cls = "shape"

    obj = _resolve_object(etype, data)
    if etype in (EventType.FILE_OPEN, EventType.FILE_READ, EventType.FILE_WRITE) and _is_pipe(obj):
        etype = EventType.IPC
    module = None
    if etype in (EventType.IMAGE_LOAD, EventType.IMAGE_UNLOAD,
                 EventType.PROCESS_START, EventType.PROCESS_EXIT) and obj:
        module = obj.replace("/", "\\").rsplit("\\", 1)[-1]

    pid = _int(data.get("ProcessId")) if data.get("ProcessId") else _int(exe_pid)
    tid = _int(exe_tid) if exe_tid else _int(data.get("TThreadId") or data.get("ThreadId"))

    ev = BlackboxEvent(
        type=etype, source="etw", ts=0.0,
        operation=ropcode or (rtask and f"{rtask}/{opcode_num}") or opcode_num,
        object=obj, result=_status_to_result(data),
        module=module, pid=pid, tid=tid,
        detail=(rtask or _KERNEL.get(guid, ("",))[0]),
        meta={"provider": guid, "classified_by": cls} if guid else {"classified_by": cls},
    )
    return ev, ts


def from_tracerpt_xml(text: str, label: str = "etw", outcome: str = "") -> Timeline:
    """Parse a ``tracerpt`` XML export **string** into a :class:`Timeline` (whole-DOM;
    for large traces prefer :func:`iter_tracerpt_file` + the reducer)."""
    tl = Timeline(label=label, outcome=outcome, meta={"sensor": "etw-tracerpt-xml"})
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return tl
    parsed = [_event_from_el(el) for el in _iter_events(root)]
    reals = [t for _, t in parsed if t is not None]
    base = min(reals) if reals else 0.0
    for i, (ev, ts) in enumerate(parsed):
        ev.ts = (ts - base) if ts is not None else float(i) * 1e-6
        tl.add(ev)
    return tl


def iter_tracerpt_file(path: str):
    """Yield events from a tracerpt XML **without building the whole DOM**, via
    ``iterparse`` with element pruning -- memory stays bounded on huge traces. Reads
    bytes so the XML's own declared encoding (often UTF-16) is honoured; timestamps are
    rebased to the first timed event (traces are chronological)."""
    base = None
    idx = 0
    with open(path, "rb") as fh:
        context = ET.iterparse(fh, events=("start", "end"))
        _, root = next(context)                      # the wrapping <Events> root
        for evt, elem in context:
            if evt != "end" or _local(elem.tag) != "Event":
                continue
            ev, ts = _event_from_el(elem)
            if ts is not None and base is None:
                base = ts
            ev.ts = (ts - base) if (ts is not None and base is not None) else float(idx) * 1e-6
            idx += 1
            yield ev
            elem.clear()
            del root[:]                              # drop processed <Event> shells


def _read_text_any(path: str) -> str:
    """Read a file that may be UTF-16 (with BOM), UTF-8-BOM or UTF-8 -- tracerpt XML
    is commonly UTF-16LE."""
    with open(path, "rb") as f:
        raw = f.read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        enc = "utf-16"
    elif raw[:3] == b"\xef\xbb\xbf":
        enc = "utf-8-sig"
    else:
        enc = "utf-8"
    return raw.decode(enc, "replace")


def from_file(path: str, label: str = "etw", outcome: str = "") -> Timeline:
    return from_tracerpt_xml(_read_text_any(path), label=label, outcome=outcome)
