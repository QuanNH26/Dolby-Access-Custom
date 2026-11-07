"""Edit TDR Nova state chunks ("VC2!" + uint32 length + XML) inside EAPO VSTPlugin lines.
Both the display attributes and the numeric copies of a parameter are rewritten (they must agree)."""
import base64, re


def decode(b64):
    b = base64.b64decode(b64); assert b[:4] == b"VC2!"
    return b[8:].decode("utf-8")


def encode(xml):
    raw = xml.encode("utf-8"); n = len(raw.rstrip(b"\x00"))
    return base64.b64encode(b"VC2!" + n.to_bytes(4, "little") + raw).decode()


def get(xml, name):
    return re.findall(rf'\b{name}="([^"]*)"', xml)


def set_params(line, **params):
    """line: an EAPO 'VSTPlugin: ... ChunkData "..."' line. params: e.g. bandGain_wide=10.4, or a
    (display, numeric) pair where the two copies differ, e.g. bandActive_4=("On", "1.0")"""
    m = re.search(r'ChunkData "([^"]+)"', line); xml = decode(m.group(1))
    for k, v in params.items():
        vals = iter(v if isinstance(v, tuple) else (v, v))
        xml, n = re.subn(rf'\b{k}="[^"]*"', lambda _, k=k, vals=vals: f'{k}="{next(vals)}"', xml)
        if n == 0: raise KeyError(k)
    return line[:m.start(1)] + encode(xml) + line[m.end(1):]
