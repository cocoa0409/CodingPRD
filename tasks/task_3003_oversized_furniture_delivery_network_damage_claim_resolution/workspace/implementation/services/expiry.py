"""Automatic EXPIRED transition for approved return authorizations
(APPROVED -> EXPIRED when the logical clock passes approved_at + 30 days
without completion). Evaluated on every request."""
from datetime import timedelta

import clock
from db import db


def sweep_return_authorizations():
    now = clock.now()
    for ra in db.return_authorizations.values():
        if ra["status"] != "APPROVED" or ra["approved_at"] is None:
            continue
        approved = clock._parse_iso(ra["approved_at"])
        if now > approved + timedelta(days=30):
            ra["status"] = "EXPIRED"
            ra["updated_at"] = clock.now_str()
            ra["version"] += 1
