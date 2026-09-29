"""The logical procurement clock and its four-hop expiry cascade (PRD 2.5)."""

from flask import Blueprint

import calc
from auth import authorize
from envelope import ok
from errors import ApiError
from shapes import Field, validate
from store import ordered, store
from util import fmt_instant

bp = Blueprint("clock", __name__)

CLOCK_FIELDS = [
    Field("to_iso8601", "datetime", required=True),
]


@bp.post("/procurement/_clock/set_current_utc")
@authorize("BuyoutManager")
def set_clock():
    body = validate(CLOCK_FIELDS)
    target = body["to_iso8601"]
    if target < store.clock:
        raise ApiError("ERR_CLOCK_REWIND")
    store.clock = target

    # hop 1 -- price holds expire
    expired = []
    for quote in ordered(list(store.quotes.values())):
        if quote["status"] == "OPEN" and quote["expires_at"] <= target:
            quote["status"] = "EXPIRED"
            store.touch(quote)
            expired.append(quote)
    expired_ids = set(q["id"] for q in expired)

    # hop 2 -- negotiations lapse
    lapsed = []
    for agreement in ordered(list(store.agreements.values())):
        if agreement["quote_id"] not in expired_ids:
            continue
        if agreement["status"] not in ("DRAFT", "PROPOSED", "COUNTERED"):
            continue
        agreement["status"] = "LAPSED"
        store.touch(agreement)
        lapsed.append(agreement)
    lapsed_ids = set(a["id"] for a in lapsed)

    # hop 3 -- un-countersigned buyouts are voided
    voided = []
    for commitment in ordered(list(store.commitments.values())):
        if commitment["commitment_status"] != "PENDING":
            continue
        if commitment["escalation_agreement_id"] not in lapsed_ids:
            continue
        commitment["commitment_status"] = "VOIDED"
        store.touch(commitment)
        voided.append(commitment)

    # hop 4 -- scope returns to the market
    affected = {}
    for quote in expired:
        pkg = store.packages.get(quote["material_package_id"])
        if pkg is not None:
            affected[pkg["id"]] = pkg
    for commitment in voided:
        pkg = store.packages.get(commitment["material_package_id"])
        if pkg is None:
            continue
        affected[pkg["id"]] = pkg
        if pkg["status"] == "BOUGHT_OUT":
            pkg["status"] = "SOURCING"
            store.touch(pkg)

    # one stall sweep over every affected package
    stalled = []
    for pkg in ordered(list(affected.values())):
        if pkg["status"] != "SOURCING":
            continue
        if calc.package_open_quote_count(pkg["id"]) == 0:
            pkg["status"] = "SOURCING_STALLED"
            store.touch(pkg)
            stalled.append(pkg)

    return ok(
        {
            "current_utc": fmt_instant(store.clock),
            "expired_quote_ids": [q["id"] for q in expired],
            "lapsed_agreement_ids": [a["id"] for a in lapsed],
            "voided_commitment_ids": [c["id"] for c in voided],
            "stalled_package_ids": [p["id"] for p in stalled],
        }
    )
