"""Cascade propagation and derived-field recomputation (PRD 2.8).

Every cascade named in section 3 is immediate and observable on the very next
read, and a row that a cascade rewrites has its ``updated_at`` refreshed and
its ``version`` incremented exactly once per operation.  Rows are therefore
marked dirty as the operation runs and reconciled once, at the end, by
``flush()``.
"""
import calc
import db
from db import store
from timeutil import parse_instant

# Dirty sets for the operation currently in flight, keyed by row id so that a
# row touched twice by one operation still moves its version by exactly one.
_rows = {}
_reps = {}
_cases = {}
_vendors = {}


def reset():
    _rows.clear()
    _reps.clear()
    _cases.clear()
    _vendors.clear()


# --------------------------------------------------------------------------
# Marking
# --------------------------------------------------------------------------
def mark(row):
    """A plain row that this operation rewrote."""
    if row is not None:
        _rows[row["id"]] = row
    return row


def mark_rep(rep):
    if rep is not None:
        _reps[rep["id"]] = rep
    return rep


def mark_case(case):
    if case is not None:
        _cases[case["id"]] = case
    return case


def mark_vendor(vendor):
    if vendor is not None:
        _vendors[vendor["id"]] = vendor
    return vendor


def mark_vendor_id(vendor_id):
    return mark_vendor(store.vendors.get(vendor_id))


def mark_case_id(case_id):
    return mark_case(store.surgical_cases.get(case_id))


# --------------------------------------------------------------------------
# Reconciliation
# --------------------------------------------------------------------------
def flush():
    """Recompute derived state, then stamp every rewritten row exactly once."""
    for row in db.in_creation_order(list(_rows.values())):
        db.touch(row)
    for rep in db.in_creation_order(list(_reps.values())):
        db.touch(rep)
    for case in db.in_creation_order(list(_cases.values())):
        case["implant_readiness_status"] = calc.compute_readiness_status(case)
        case["vendor_coverage_status"] = calc.compute_coverage_status(case)
        db.touch(case)
    for vendor in db.in_creation_order(list(_vendors.values())):
        vendor["late_fee_balance_cents"] = calc.compute_fee_balance(vendor["id"])
        provisional, adjudicated = calc.compute_scores(vendor)
        vendor["provisional_compliance_score"] = provisional
        vendor["adjudicated_compliance_score"] = adjudicated
        db.touch(vendor)
    reset()


# --------------------------------------------------------------------------
# Credential posture (PRD 3.2)
# --------------------------------------------------------------------------
def recompute_posture(rep):
    """Recompute posture from the whole credential collection and propagate."""
    posture = calc.compute_credential_posture(rep)
    changed = False
    if posture != rep["credential_posture"]:
        rep["credential_posture"] = posture
        changed = True
        # A covering representative's posture feeds every case it covers.
        for auth in calc.authorizations_of_rep(rep["id"]):
            if auth["status"] == "APPROVED":
                mark_case_id(auth["surgical_case_id"])
    if posture in ("COMPLIANT", "EXPIRING_SOON") and not rep["ever_credentialed"]:
        rep["ever_credentialed"] = True
        changed = True
    if changed:
        mark_rep(rep)
    return posture


# --------------------------------------------------------------------------
# Authorization revocation (PRD 3.4)
# --------------------------------------------------------------------------
def void_issued_badges(auth):
    """Every ISSUED badge of a newly revoked authorization moves to VOIDED."""
    voided = 0
    for check_in in db.in_creation_order(calc.check_ins_of_authorization(auth["id"])):
        if check_in["badge_status"] == "ISSUED":
            check_in["badge_status"] = "VOIDED"
            mark(check_in)
            voided += 1
    return voided


def revoke_authorization(auth, reason):
    """APPROVED -> REVOKED with the counter, badge and posture cascade."""
    auth["status"] = "REVOKED"
    auth["revoked_reason"] = reason
    mark(auth)

    rep = store.vendor_reps.get(auth["vendor_rep_id"])
    if rep is not None:
        rep["open_authorization_count"] = max(0, rep["open_authorization_count"] - 1)
        mark_rep(rep)
        vendor = store.vendors.get(rep["vendor_id"])
        if vendor is not None:
            vendor["authorizations_used_epoch"] = max(
                0, vendor["authorizations_used_epoch"] - 1
            )
            mark_vendor(vendor)

    case = store.surgical_cases.get(auth["surgical_case_id"])
    if case is not None:
        case["approved_rep_count"] = max(0, case["approved_rep_count"] - 1)
        case["revoked_authorization_count"] = case["revoked_authorization_count"] + 1
        mark_case(case)

    return void_issued_badges(auth)


def case_starts_at_or_after_now(case):
    if case is None:
        return False
    return parse_instant(case["scheduled_start_utc"]) >= db.now()


def rep_access_cascade(rep, reason):
    """Revoke the representative's APPROVED authorizations for future cases.

    Authorizations for cases that have already started are deliberately left
    APPROVED, because historical access is a matter of record.
    """
    revoked = 0
    badges = 0
    auths = db.in_creation_order(calc.authorizations_of_rep(rep["id"]))
    for auth in auths:
        if auth["status"] != "APPROVED":
            continue
        case = store.surgical_cases.get(auth["surgical_case_id"])
        if not case_starts_at_or_after_now(case):
            continue
        badges += revoke_authorization(auth, reason)
        revoked += 1
    return revoked, badges


# --------------------------------------------------------------------------
# Loaner-set holds and their release (PRD 3.7, 3.8)
# --------------------------------------------------------------------------
def hold_sets_of_product(product):
    """Every set referencing a newly suspended product is held."""
    for loaner_set in db.in_creation_order(calc.loaner_sets_of_product(product["id"])):
        if loaner_set["status"] not in ("EXPECTED", "DELIVERED_ON_TIME", "DELIVERED_LATE"):
            continue
        loaner_set["status"] = "HELD"
        mark(loaner_set)
        mark_case_id(loaner_set["surgical_case_id"])
        mark_vendor_id(calc.loaner_set_vendor_id(loaner_set))


def release_holds_of_product(product):
    """A held set returns to whichever branch its own history implies."""
    for loaner_set in db.in_creation_order(calc.loaner_sets_of_product(product["id"])):
        if loaner_set["status"] != "HELD":
            continue
        if not loaner_set["delivered_at_utc"]:
            loaner_set["status"] = "EXPECTED"
        elif loaner_set["late_minutes_current_basis"] > 0:
            loaner_set["status"] = "DELIVERED_LATE"
        else:
            loaner_set["status"] = "DELIVERED_ON_TIME"
        mark(loaner_set)
        mark_case_id(loaner_set["surgical_case_id"])
        mark_vendor_id(calc.loaner_set_vendor_id(loaner_set))


def suspend_product(product, reason):
    if product is None or product["status"] != "ACTIVE":
        return False
    product["status"] = "SUSPENDED"
    product["suspended_reason"] = reason
    mark(product)
    return True


# --------------------------------------------------------------------------
# Representative suspension driven by a substantiated incident (PRD 3.8)
# --------------------------------------------------------------------------
def suspend_rep_for_incident(rep):
    if rep is None or rep["access_status"] != "CREDENTIALED":
        return False
    rep["access_status"] = "SUSPENDED"
    rep["suspension_reason"] = "INCIDENT_SUBSTANTIATED"
    mark_rep(rep)
    rep_access_cascade(rep, "REP_SUSPENDED")
    return True
