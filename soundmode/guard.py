"""Overlap guard: one shaping layer per playback device.

Policy "auto" (default): when another layer (Spatial sound / Dolby, an enhancement, a processing app) starts shaping
the default device while our Equalizer APO mode is on, switch OUR layer off and remember that we did it; when the
other layer goes away again, switch ours back on. We never touch other apps' settings.
Policy "warn": only report.
"""
from dataclasses import dataclass
from . import detect, engine

FOREIGN = {"spatial", "sysfx", "app"}   # vendor APOs: warn only (they may be idle pass-through)


@dataclass
class Event:
    level: str   # info | warn
    text: str


class Guard:
    def __init__(self, policy="auto"):
        self.policy = policy
        st = engine.state()
        self.paused_by_us = st.get("paused_by_guard", False)

    def _remember(self, v):
        self.paused_by_us = v
        engine._save_state(paused_by_guard=v)

    def _follow(self, ep):
        """New headphones became the default output (another user, re-paired, swapped): move the mode onto them,
        with the mode that pair used last time. Needs Equalizer APO on that device; otherwise just say so."""
        if ep.surround != "virtual" or ep.bus == "virtual" or ep.guid == (engine.device_guid() or "").lower():
            return []
        if not any(l.kind == "eapo" for l in ep.layers):
            return [Event("warn", f"{ep.label} chua co Equalizer APO: mo DeviceSelector.exe (admin), tick thiet bi nay, "
                                  "khoi dong lai may de dung che do cua app.")]
        try:
            engine.retarget(ep.guid)
            return [Event("info", f"Da chuyen che do sang {ep.label} ({engine.current()}).")]
        except Exception as e:
            return [Event("warn", f"Khong chuyen duoc che do sang {ep.label}: {e}")]

    def check(self, res=None):
        """Run once. Returns (scan result, list of Event)."""
        res = res or detect.scan()
        self.paused_by_us = engine.state().get("paused_by_guard", False)   # shared with the background guard / GUI
        ev = []
        ep = next((e for e in res["endpoints"] if e.default and e.state == 1), None)
        if not ep: return res, ev
        ev += self._follow(ep)
        foreign = [l for l in ep.shaping if l.kind in FOREIGN]
        vendor = [l for l in ep.shaping if l.kind == "vendor"]
        ours = next((l for l in ep.layers if l.kind == "eapo"), None)
        ours_on = bool(ours and ours.active)
        if ours_on and foreign:
            names = ", ".join(l.name for l in foreign)
            if self.policy == "auto":
                engine.set_active(False); self._remember(True)
                ev.append(Event("warn", f"Phat hien {names} dang xu ly {ep.name}. Da tam TAT che do cua app de tranh chong. "
                                        f"Tat {names} thi app tu bat lai."))
            else:
                ev.append(Event("warn", f"CHONG CHEO tren {ep.name}: Equalizer APO + {names}"))
        elif self.paused_by_us and not foreign and ours:
            engine.set_active(True); self._remember(False)
            ev.append(Event("info", f"{ep.name}: khong con lop xu ly khac, da BAT lai che do cua app."))
        if ours_on and vendor:
            ev.append(Event("warn", f"{ep.name} con co APO cua hang ({', '.join(l.name for l in vendor)}). "
                                    "Neu nghe thay xu ly hai lop, tat Enhancements trong Sound settings."))
        return res, ev
