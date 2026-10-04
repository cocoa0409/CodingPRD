"""Time sweep (PRD §2.4): runs on every clock advance before responding."""
from datetime import timedelta

from core import STORE, now, touch, parse_datetime
from derived import (
    reeval_formulation_coverage,
    recompute_disclosed_count,
    recompute_posture,
    secs,
)


def run_sweep():
    current = now()
    cur_s = secs(current)
    cur_date = current.date()

    # --- Market registrations: ACTIVE -> RENEWAL_DUE -> EXPIRED --------------
    for reg in STORE["registrations"].values():
        if reg["status"] not in ("ACTIVE", "RENEWAL_DUE"):
            continue
        exp = secs(parse_datetime(reg["expires_on"]))
        if cur_s >= exp:
            reg["status"] = "EXPIRED"
            touch(reg)
        elif reg["status"] == "ACTIVE" and cur_s >= exp - timedelta(days=90):
            reg["status"] = "RENEWAL_DUE"
            touch(reg)

    # --- Confidentiality grants: GRANTED / ACTIVE -> EXPIRED -----------------
    for g in STORE["grants"].values():
        if g["status"] not in ("GRANTED", "ACTIVE"):
            continue
        exp = secs(parse_datetime(g["expires_on"]))
        if cur_s >= exp:
            was_active = g["status"] == "ACTIVE"
            g["status"] = "EXPIRED"
            touch(g)
            mfr = STORE["manufacturers"].get(g["manufacturer_id"])
            if mfr is not None:
                recompute_disclosed_count(mfr)
            if was_active:
                form = STORE["formulations"].get(g["formulation_id"])
                if form is not None:
                    reeval_formulation_coverage(form)

    # --- Channel price lists: SCHEDULED -> EFFECTIVE -> EXPIRED --------------
    for pl in STORE["price_lists"].values():
        if pl["status"] not in ("SCHEDULED", "EFFECTIVE"):
            continue
        ef = secs(parse_datetime(pl["effective_from"]))
        et = secs(parse_datetime(pl["effective_to"]))
        if cur_s >= et:
            pl["status"] = "EXPIRED"
            touch(pl)
        elif pl["status"] == "SCHEDULED" and cur_s >= ef:
            pl["status"] = "EFFECTIVE"
            touch(pl)

    # --- Promotions: APPROVED -> LIVE; APPROVED / LIVE -> ENDED --------------
    for p in STORE["promotions"].values():
        if p["status"] not in ("APPROVED", "LIVE"):
            continue  # the sweep never ends a SUSPENDED promotion
        starts = parse_date_str(p["starts_on"])
        ends = parse_date_str(p["ends_on"])
        if cur_date > ends:
            p["status"] = "ENDED"
            touch(p)
        elif p["status"] == "APPROVED" and cur_date >= starts:
            p["status"] = "LIVE"
            touch(p)

    # --- Coverage assignments: ACTIVE / SUSPENDED -> CLOSED ------------------
    for a in STORE["assignments"].values():
        if a["status"] in ("ACTIVE", "SUSPENDED") and cur_date > parse_date_str(a["ends_on"]):
            a["status"] = "CLOSED"
            touch(a)

    # --- Brand protection posture recompute ----------------------------------
    for brand in STORE["brands"].values():
        recompute_posture(brand)


def parse_date_str(s):
    from core import parse_date

    return parse_date(s)
