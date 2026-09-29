"""Patron scoring, the two status dimensions and the card cascades (PRD 3.7)."""

import calculations as calc
import constants as C
import derive
from db import clock_now, db, touch

_RECOMPUTED_FIELDS = (
    "resale_risk_score",
    "recent_sales_risk_score",
    "restricted_units_30d",
    "flagged_sale_count_30d",
    "resale_watch_status",
    "card_status",
    "suspension_reason",
    "manual_strike_count",
)


def _snapshot(patron):
    return dict((key, patron[key]) for key in _RECOMPUTED_FIELDS)


def _changed(patron, snapshot):
    return any(patron[key] != snapshot[key] for key in _RECOMPUTED_FIELDS)


def recompute_risk(patron, bump=True):
    """Rescore both variants, re-derive both axes, and fire the threshold
    suspension when the card axis crosses.  A REVOKED card is frozen: no
    further risk recomputation is applied to it."""
    if patron["card_status"] == "REVOKED":
        return
    snapshot = _snapshot(patron)
    sales = list(db.sales.values())
    lines_by_sale = derive.lines_by_sale_map()
    now = clock_now()

    rolling = calc.rolling_30d_set(sales, patron["id"], now)
    rolling_score, rolling_units, rolling_flagged = calc.risk_score(
        rolling, lines_by_sale, patron["manual_strike_count"]
    )
    recent = calc.last_5_sales_set(sales, patron["id"])
    recent_score, _units, _flagged = calc.risk_score(
        recent, lines_by_sale, patron["manual_strike_count"]
    )

    patron["resale_risk_score"] = rolling_score
    patron["recent_sales_risk_score"] = recent_score
    patron["restricted_units_30d"] = rolling_units
    patron["flagged_sale_count_30d"] = rolling_flagged
    patron["resale_watch_status"] = calc.derive_watch_status(rolling_score)

    fire_suspension = (
        recent_score >= C.CARD_SUSPEND_THRESHOLD and patron["card_status"] == "VALID"
    )
    if fire_suspension:
        patron["card_status"] = "SUSPENDED"
        patron["suspension_reason"] = "RISK_THRESHOLD"

    if bump and _changed(patron, snapshot):
        touch(patron)

    if fire_suspension:
        cascade_suspension(patron)


# --------------------------------------------------------------------------
# card cascades
# --------------------------------------------------------------------------


def cascade_suspension(patron):
    """Three ordered hops: dependents -> their delegations -> those open sales."""
    dependents = [
        p
        for p in db.patrons.values()
        if p["sponsor_patron_id"] == patron["id"] and p["card_status"] == "VALID"
    ]
    dependents.sort(key=lambda p: (p["created_at"], p["_seq"]))
    for dependent in dependents:
        dependent["card_status"] = "SUSPENDED"
        dependent["suspension_reason"] = "SPONSOR_SUSPENDED"
        touch(dependent)

    dependent_ids = set(p["id"] for p in dependents)
    delegations = [
        g
        for g in db.delegations.values()
        if g["delegate_patron_id"] in dependent_ids and g["status"] == "ACTIVE"
    ]
    delegations.sort(key=lambda g: (g["created_at"], g["_seq"]))
    for delegation in delegations:
        delegation["status"] = "SUSPENDED_BY_SPONSOR"
        touch(delegation)

    delegation_ids = set(g["id"] for g in delegations)
    flag_open_sales_of_delegations(delegation_ids)


def cascade_reinstatement(patron):
    """Three compensating hops mirroring the suspension precisely."""
    dependents = [
        p
        for p in db.patrons.values()
        if p["sponsor_patron_id"] == patron["id"]
        and p["card_status"] == "SUSPENDED"
        and p["suspension_reason"] == "SPONSOR_SUSPENDED"
    ]
    dependents.sort(key=lambda p: (p["created_at"], p["_seq"]))
    for dependent in dependents:
        dependent["card_status"] = "VALID"
        dependent["suspension_reason"] = None
        touch(dependent)

    dependent_ids = set(p["id"] for p in dependents)
    delegations = [
        g
        for g in db.delegations.values()
        if g["delegate_patron_id"] in dependent_ids and g["status"] == "SUSPENDED_BY_SPONSOR"
    ]
    delegations.sort(key=lambda g: (g["created_at"], g["_seq"]))
    for delegation in delegations:
        delegation["status"] = "ACTIVE"
        touch(delegation)

    delegation_ids = set(g["id"] for g in delegations)
    for sale in _sorted_sales():
        if (
            sale["acting_delegation_id"] in delegation_ids
            and sale["tender_state"] == "OPEN"
            and sale["compliance_state"] == "FLAGGED"
        ):
            sale["compliance_state"] = "CLEARED"
            touch(sale)


def cascade_revocation(patron):
    """Every delegation naming this patron as sponsor OR delegate is revoked."""
    for delegation in _sorted_delegations():
        if (
            delegation["sponsor_patron_id"] == patron["id"]
            or delegation["delegate_patron_id"] == patron["id"]
        ) and delegation["status"] in ("ACTIVE", "SUSPENDED_BY_SPONSOR"):
            delegation["status"] = "REVOKED"
            touch(delegation)


def flag_open_sales_of_delegations(delegation_ids):
    for sale in _sorted_sales():
        if (
            sale["acting_delegation_id"] in delegation_ids
            and sale["tender_state"] == "OPEN"
            and sale["compliance_state"] == "CLEARED"
        ):
            sale["compliance_state"] = "FLAGGED"
            touch(sale)


def flag_open_sales_of_patron(patron_id):
    for sale in _sorted_sales():
        if (
            sale["patron_id"] == patron_id
            and sale["tender_state"] == "OPEN"
            and sale["compliance_state"] == "CLEARED"
        ):
            sale["compliance_state"] = "FLAGGED"
            touch(sale)


def clear_open_sales_of_patron(patron_id):
    for sale in _sorted_sales():
        if (
            sale["patron_id"] == patron_id
            and sale["tender_state"] == "OPEN"
            and sale["compliance_state"] == "FLAGGED"
        ):
            sale["compliance_state"] = "CLEARED"
            touch(sale)


snapshot_state = _snapshot
state_changed = _changed


def _sorted_sales():
    rows = list(db.sales.values())
    rows.sort(key=lambda s: (s["created_at"], s["_seq"]))
    return rows


def _sorted_delegations():
    rows = list(db.delegations.values())
    rows.sort(key=lambda g: (g["created_at"], g["_seq"]))
    return rows
