"""Test-driving logical clock and the season rollover ops checkpoint."""
from flask import Blueprint

import calculations as calc
import clock
import helpers
from helpers import auth, body, ok, req, require_role
import storage
from storage import STORES, touch

bp = Blueprint("admin", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    role, uid = auth()
    require_role(role, ("CorporateAdmin",))
    b = body()
    raw = req(b, "to_iso8601")
    helpers.as_iso_dt(raw, "to_iso8601")
    clock.set_clock(raw)
    return ok({"current_utc": clock.now_str()})


@bp.post("/admin/run_season_rollover")
def run_season_rollover():
    role, uid = auth()
    require_role(role, ("CorporateAdmin",))
    now = clock.now()
    today = now.date()
    transitions = 0

    # 1. Monthly billing progression on every ACTIVE lease.
    for lease in list(STORES["leases"].values()):
        if lease["status"] != "ACTIVE":
            continue
        billed, remaining = calc.lease_billing(lease, today)
        if billed != lease["billed_to_date_cents"]:
            lease["billed_to_date_cents"] = billed
            lease["remaining_balance_cents"] = remaining
            touch(lease)

    # 2. Fleet turnover: ACTIVE leases whose end_date has been reached move to
    #    TURNOVER_IN_PROGRESS and their IN_SERVICE units to RETURN_REQUESTED.
    for lease in list(STORES["leases"].values()):
        if lease["status"] == "ACTIVE" and today >= lease["_end_date"]:
            lease["status"] = "TURNOVER_IN_PROGRESS"
            touch(lease)
            transitions += 1
            for u in STORES["units"].values():
                if u["lease_id"] == lease["id"] and u["status"] == "IN_SERVICE":
                    u["status"] = "RETURN_REQUESTED"
                    touch(u)
                    transitions += 1

    # 3. Technician certification expiry.
    for t in list(STORES["technicians"].values()):
        if t["cert_status"] == "CERT_ACTIVE" and t.get("_cert_expires_dt") is not None \
                and t["_cert_expires_dt"] < now:
            t["cert_status"] = "CERT_EXPIRED"
            touch(t)
            transitions += 1

    # 4. Reservation expiry: release the hold, leave the ask untouched.
    released_this_run = set()
    for u in list(STORES["units"].values()):
        if u["status"] == "RESERVED" and u.get("_res_expires_dt") is not None \
                and u["_res_expires_dt"] < now:
            u["status"] = "REMARKET_LISTED"
            u["reserved_by_course_id"] = None
            u["reservation_expires_at"] = None
            u["_res_expires_dt"] = None
            touch(u)
            transitions += 1
            released_this_run.add(u["id"])

    # 5. Exactly one price-decay step per unit sitting in REMARKET_LISTED.
    #    Units whose reservation expired in this same run are excluded:
    #    reservation expiry is not a decay step and leaves the ask untouched.
    for u in list(STORES["units"].values()):
        if u["status"] == "REMARKET_LISTED" and u["id"] not in released_this_run:
            new_ask = calc.remarketing_decay(u["asking_price_cents"], u["floor_price_cents"])
            if new_ask != u["asking_price_cents"]:
                u["asking_price_cents"] = new_ask
                touch(u)

    # 6. Catalog aging: models strictly older than the 240-month sales window.
    for m in list(STORES["models"].values()):
        if m["lifecycle_status"] == "CATALOG_ACTIVE" and calc.model_is_aged_out(m):
            m["lifecycle_status"] = "DISCONTINUED"
            touch(m)
            transitions += 1

    return ok({"advanced_to": clock.now_str(), "transitions_applied": transitions})
