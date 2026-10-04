"""Time-driven auto-transitions and small cross-cutting helpers."""

from datetime import timedelta

import db
from clock import now, isoformat, parse_iso
from models import touch


def fire_auto_transitions():
    """Apply surge-window and cure-period auto transitions against the current clock."""
    n = now()
    for w in db.surge_windows.values():
        if w["status"] == "DECLARED" and parse_iso(w["starts_on"]) <= n:
            w["status"] = "ACTIVE"
            touch(w)
        if w["status"] == "ACTIVE" and parse_iso(w["ends_on"]) < n:
            w["status"] = "EXPIRED"
            touch(w)
    for cp in db.cure_periods.values():
        if cp["status"] == "PENDING" and parse_iso(cp["deadline"]) < n:
            cp["status"] = "FORFEIT"
            touch(cp)
            line = db.invoice_lines.get(cp["invoice_line_id"])
            if line is not None:
                inv = db.invoices.get(line["invoice_id"])
                if inv is not None:
                    contract = db.contracts.get(inv["contract_id"])
                    if contract is not None:
                        contract["cure_periods_used"] = int(contract.get("cure_periods_used", 0)) + 1
