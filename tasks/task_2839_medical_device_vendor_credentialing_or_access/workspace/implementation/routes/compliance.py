"""Incidents, revocation appeals and the nine-phase compliance sweep
(PRD 3.8, 3.9).
"""
from flask import Blueprint

import calc
import cascades
import db
from db import store
from envelope import respond_object
from errors import ApiError
from reqval import (
    authenticate,
    pagination_params,
    query_enum,
    query_string,
    read_body,
)
from routes import common
from timeutil import add_days, fmt_instant, parse_instant

bp = Blueprint("compliance", __name__, url_prefix="/vendor-access")


# ---------------------------------------------------------------- Incident
@bp.post("/incidents")
def report_incident():
    user_id, _role = authenticate(("ORCoordinator", "SterileProcessingTech", "ComplianceAdmin"))
    body = read_body()
    surgical_case_id = body.string("surgical_case_id")
    vendor_rep_id = body.string("vendor_rep_id")
    approved_product_id = body.string("approved_product_id", required=False)
    incident_type = body.enum("incident_type", db.INCIDENT_TYPES)
    severity = body.enum("severity", db.SEVERITIES)
    narrative = body.string("narrative")

    case = common.surgical_case(surgical_case_id)
    rep = common.vendor_rep(vendor_rep_id)
    if approved_product_id is not None:
        common.approved_product(approved_product_id)

    row = db.stamp_common(
        {
            "surgical_case_id": case["id"],
            "vendor_rep_id": rep["id"],
            "approved_product_id": approved_product_id,
            "incident_type": incident_type,
            "severity": severity,
            "narrative": narrative,
            "reported_by_user_id": user_id,
            "reported_at_utc": db.now_str(),
            "status": "REPORTED",
            "adjudicated_outcome": "NONE",
            "adjudicated_by_user_id": None,
            "adjudicated_at_utc": None,
            # Frozen from the severity at creation.
            "score_weight": db.SEVERITY_WEIGHT[severity],
        }
    )
    store.incidents[row["id"]] = row

    # The report immediately depresses the provisional score while leaving the
    # adjudicated score exactly where it was.
    cascades.mark_vendor_id(rep["vendor_id"])
    cascades.flush()
    return common.created(row)


@bp.get("/incidents/<row_id>")
def read_incident(row_id):
    authenticate(common.ALL_ROLES)
    return common.ok(common.incident(row_id))


@bp.get("/incidents")
def list_incidents():
    authenticate(common.ALL_ROLES)
    limit, offset = pagination_params()
    surgical_case_id = query_string("surgical_case_id")
    vendor_rep_id = query_string("vendor_rep_id")
    approved_product_id = query_string("approved_product_id")
    status = query_enum("status", db.INCIDENT_STATUSES)
    severity = query_enum("severity", db.SEVERITIES)
    rows = [
        row
        for row in store.incidents.values()
        if common.matches(row, "surgical_case_id", surgical_case_id)
        and common.matches(row, "vendor_rep_id", vendor_rep_id)
        and common.matches(row, "approved_product_id", approved_product_id)
        and common.matches(row, "status", status)
        and common.matches(row, "severity", severity)
    ]
    return common.listing(rows, limit, offset)


@bp.post("/incidents/<row_id>/investigate")
def investigate_incident(row_id):
    authenticate(("ComplianceAdmin",))
    read_body()
    incident = common.incident(row_id)
    if incident["status"] != "REPORTED":
        raise ApiError("ERR_INCIDENT_INVALID_STATE")

    incident["status"] = "UNDER_INVESTIGATION"
    # Deliberately score-neutral in both variants, so no vendor row moves.
    cascades.mark(incident)
    cascades.flush()
    return common.ok(incident)


def _substantiation_cascade(incident, rep):
    """The deepest cascade in the domain (PRD 3.8): each hop exists because the
    previous one happened.
    """
    product = store.approved_products.get(incident["approved_product_id"])
    if product is not None and cascades.suspend_product(product, "INCIDENT_SUBSTANTIATED"):
        cascades.hold_sets_of_product(product)
    if incident["incident_type"] == "UNAPPROVED_PRODUCT_USE" and incident["severity"] == "CRITICAL":
        cascades.suspend_rep_for_incident(rep)


def _unsubstantiation_cascade(incident):
    """Unsubstantiation unwinds what substantiation built, but not the
    representative's suspension.
    """
    product = store.approved_products.get(incident["approved_product_id"])
    if (
        product is not None
        and product["status"] == "SUSPENDED"
        and product["suspended_reason"] == "INCIDENT_SUBSTANTIATED"
    ):
        product["status"] = "ACTIVE"
        product["suspended_reason"] = "NONE"
        cascades.mark(product)
        cascades.release_holds_of_product(product)


@bp.post("/incidents/<row_id>/adjudicate")
def adjudicate_incident(row_id):
    user_id, _role = authenticate(("ComplianceAdmin",))
    body = read_body()
    outcome = body.enum("outcome", ("SUBSTANTIATED", "UNSUBSTANTIATED"))
    body.string("adjudication_note", required=False)

    incident = common.incident(row_id)
    admissible = incident["status"] in db.INCIDENT_OPEN_STATUSES or (
        incident["status"] == "SUBSTANTIATED" and outcome == "UNSUBSTANTIATED"
    )
    if not admissible:
        raise ApiError("ERR_INCIDENT_INVALID_STATE")
    if user_id == incident["reported_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    incident["status"] = outcome
    incident["adjudicated_outcome"] = outcome
    incident["adjudicated_by_user_id"] = user_id
    incident["adjudicated_at_utc"] = db.now_str()
    cascades.mark(incident)

    rep = store.vendor_reps.get(incident["vendor_rep_id"])
    if outcome == "SUBSTANTIATED":
        _substantiation_cascade(incident, rep)
    else:
        _unsubstantiation_cascade(incident)

    # Both score variants are recomputed on either outcome.
    if rep is not None:
        cascades.mark_vendor_id(rep["vendor_id"])
    cascades.flush()
    return common.ok(incident)


# ------------------------------------------------------------ AccessAppeal
@bp.post("/access-appeals")
def file_appeal():
    user_id, role = authenticate(("VendorAdmin", "VendorRepUser"))
    body = read_body()
    vendor_rep_id = body.string("vendor_rep_id")
    grounds = body.string("grounds")

    rep = common.vendor_rep(vendor_rep_id)
    common.require_rep_or_vendor_scope(role, user_id, rep)

    if rep["access_status"] != "REVOKED":
        raise ApiError("ERR_REP_NOT_REVOKED")

    deadline = fmt_instant(add_days(parse_instant(rep["revoked_at_utc"]), db.APPEAL_WINDOW_DAYS))
    # Filing at exactly the deadline is still accepted.
    if db.now() > parse_instant(deadline):
        raise ApiError("ERR_APPEAL_WINDOW_CLOSED")

    for existing in calc.appeals_of_rep(rep["id"]):
        if existing["filed_for_revoked_at_utc"] == rep["revoked_at_utc"]:
            raise ApiError("ERR_APPEAL_ALREADY_FILED")

    row = db.stamp_common(
        {
            "vendor_rep_id": rep["id"],
            "grounds": grounds,
            # A stored copy rather than a live lookup: it pins the appeal to one
            # specific revocation event.
            "filed_for_revoked_at_utc": rep["revoked_at_utc"],
            "filed_at_utc": db.now_str(),
            "appeal_deadline_utc": deadline,
            "status": "SUBMITTED",
            "decided_by_user_id": None,
            "decided_at_utc": None,
            "decision_rationale": None,
        }
    )
    store.appeals[row["id"]] = row
    return common.created(row)


@bp.get("/access-appeals/<row_id>")
def read_appeal(row_id):
    authenticate(common.ALL_ROLES)
    return common.ok(common.appeal(row_id))


@bp.post("/access-appeals/<row_id>/decide")
def decide_appeal(row_id):
    user_id, _role = authenticate(("ComplianceAdmin", "CredentialingOfficer"))
    body = read_body()
    decision = body.enum("decision", ("UPHOLD", "OVERTURN"))
    decision_rationale = body.string("decision_rationale")

    appeal = common.appeal(row_id)
    if appeal["status"] != "SUBMITTED":
        raise ApiError("ERR_APPEAL_INVALID_STATE")

    rep = store.vendor_reps.get(appeal["vendor_rep_id"])
    if rep is not None and user_id == rep["revoked_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    moment = db.now_str()
    appeal["status"] = "UPHELD" if decision == "UPHOLD" else "OVERTURNED"
    appeal["decided_by_user_id"] = user_id
    appeal["decided_at_utc"] = moment
    appeal["decision_rationale"] = decision_rationale
    cascades.mark(appeal)

    if decision == "OVERTURN" and rep is not None:
        # The posture is recomputed first, against the credentials as they
        # stand at this instant.
        posture = cascades.recompute_posture(rep)
        if posture in ("COMPLIANT", "EXPIRING_SOON"):
            rep["access_status"] = "CREDENTIALED"
            rep["suspension_reason"] = "NONE"
        else:
            rep["access_status"] = "SUSPENDED"
            rep["suspension_reason"] = "CREDENTIAL_LAPSED"
        rep["reinstated_at_utc"] = moment
        cascades.mark_rep(rep)

    cascades.flush()
    return common.ok(appeal)


# --------------------------------------------------------- ComplianceSweep
def _phase_2_age_credentials(swept_at, counters):
    """Every VERIFIED credential at or past the boundary expires; equality
    expires.  Everything inside the fourteen-day horizon is warned.
    """
    warning_boundary = add_days(swept_at, db.EXPIRY_WARNING_DAYS)
    for credential in db.in_creation_order(list(store.credentials.values())):
        if credential["status"] not in ("VERIFIED", "EXPIRING_SOON"):
            continue
        expires = parse_instant(credential["expires_at_utc"])
        if expires is None:
            continue
        if expires <= swept_at:
            credential["status"] = "EXPIRED"
            counters["credentials_expired_count"] += 1
            cascades.mark(credential)
        elif credential["status"] == "VERIFIED" and expires <= warning_boundary:
            credential["status"] = "EXPIRING_SOON"
            counters["credentials_warned_count"] += 1
            cascades.mark(credential)


def _phase_3_refresh_postures(counters):
    """Posture is recomputed from the credentials as phase 2 left them, and the
    two posture-driven access transitions are applied.
    """
    newly_suspended = []
    for rep in db.in_creation_order(list(store.vendor_reps.values())):
        if rep["access_status"] == "REVOKED":
            # A REVOKED representative is untouched by this phase entirely.
            continue
        posture = cascades.recompute_posture(rep)
        if rep["access_status"] == "CREDENTIALED" and posture == "LAPSED":
            rep["access_status"] = "SUSPENDED"
            rep["suspension_reason"] = "CREDENTIAL_LAPSED"
            counters["reps_suspended_count"] += 1
            cascades.mark_rep(rep)
            newly_suspended.append(rep)
        elif (
            rep["access_status"] == "SUSPENDED"
            and rep["suspension_reason"] == "CREDENTIAL_LAPSED"
            and posture in ("COMPLIANT", "EXPIRING_SOON")
        ):
            rep["access_status"] = "CREDENTIALED"
            rep["suspension_reason"] = "NONE"
            rep["reinstated_at_utc"] = db.now_str()
            counters["reps_reinstated_count"] += 1
            cascades.mark_rep(rep)
    return newly_suspended


def _phase_4_propagate_suspensions(swept_at, newly_suspended, counters):
    """Only cases starting at or after the sweep instant are rewritten; the
    sweep does not rewrite history.
    """
    for rep in newly_suspended:
        for auth in db.in_creation_order(calc.authorizations_of_rep(rep["id"])):
            if auth["status"] != "APPROVED":
                continue
            case = store.surgical_cases.get(auth["surgical_case_id"])
            if case is None or parse_instant(case["scheduled_start_utc"]) < swept_at:
                continue
            counters["badges_voided_count"] += cascades.revoke_authorization(
                auth, "REP_SUSPENDED"
            )
            counters["authorizations_revoked_count"] += 1


def _phase_5_expire_badges(swept_at, counters):
    for check_in in db.in_creation_order(list(store.check_ins.values())):
        if check_in["badge_status"] != "ISSUED":
            continue
        valid_until = parse_instant(check_in["valid_until_utc"])
        if valid_until is not None and valid_until <= swept_at:
            check_in["badge_status"] = "EXPIRED"
            counters["badges_expired_count"] += 1
            cascades.mark(check_in)


def _phase_6_expire_approvals(swept_at, counters):
    """Expiry places no hold on any loaner set; it is felt at release time."""
    for product in db.in_creation_order(list(store.approved_products.values())):
        if product["status"] not in ("ACTIVE", "SUSPENDED"):
            continue
        expires = parse_instant(product["approval_expires_at_utc"])
        if expires is None or expires > swept_at:
            continue
        was_active = product["status"] == "ACTIVE"
        product["status"] = "EXPIRED"
        if was_active:
            # A product suspended for another cause keeps that cause on record.
            product["suspended_reason"] = "APPROVAL_EXPIRED"
        counters["approvals_expired_count"] += 1
        cascades.mark(product)


def _phase_7_close_findings(swept_at, counters):
    """Closure is bookkeeping only: adjudicated_outcome is retained."""
    for incident in db.in_creation_order(list(store.incidents.values())):
        if incident["status"] not in ("SUBSTANTIATED", "UNSUBSTANTIATED"):
            continue
        adjudicated = parse_instant(incident["adjudicated_at_utc"])
        if adjudicated is None:
            continue
        if add_days(adjudicated, db.INCIDENT_CLOSE_DAYS) <= swept_at:
            incident["status"] = "CLOSED"
            counters["incidents_closed_count"] += 1
            cascades.mark(incident)


def _phase_8_rescore(epoch_number, counters):
    """The eight normative steps, in order; any other order yields a different
    observable score.
    """
    for vendor in db.in_creation_order(list(store.vendors.values())):
        # 1. the pre-sweep quota, never the value step 6 is about to write.
        quota_in_effect = vendor["access_quota_in_effect"]
        # 2. the utilization ratio, taken before the epoch counter is reset.
        ratio = calc.compute_utilization_ratio(
            vendor["authorizations_used_epoch"], quota_in_effect
        )
        # 3. the over-utilization penalty.
        overage = db.W_UTILIZATION_OVERAGE if ratio > 1 else 0
        # 4. the adjudicated score, with the lapsed count taken after phase 3.
        lapsed = calc.compute_lapsed_rep_count(vendor["id"])
        vendor["_lapsed_rep_count_at_last_sweep"] = lapsed
        vendor["_overage_penalty_at_last_sweep"] = overage
        provisional, adjudicated = calc.compute_scores(vendor, lapsed, overage)
        vendor["provisional_compliance_score"] = provisional
        vendor["adjudicated_compliance_score"] = adjudicated
        # 5. the tier.
        tier = calc.derive_tier(adjudicated)
        vendor["scorecard_tier"] = tier
        # 6. the new quota.
        vendor["access_quota_in_effect"] = calc.next_quota(quota_in_effect, tier)
        # 7. and only now, the epoch counter reset.
        vendor["authorizations_used_epoch"] = 0
        # 8. the compliance band and the epoch stamp.
        vendor["compliance_status"] = calc.derive_compliance_status(adjudicated)
        vendor["last_sweep_epoch"] = epoch_number
        cascades.mark_vendor(vendor)
        counters["vendors_rescored_count"] += 1


@bp.post("/compliance-sweeps")
def run_compliance_sweep():
    authenticate(("ComplianceAdmin",))
    read_body()

    # Phase 1 opens the epoch.  Every comparison in every phase uses this one
    # captured value rather than a per-phase re-read of the clock.
    previous_epoch_number = max(
        [row["epoch_number"] for row in store.sweeps.values()] or [0]
    )
    epoch_number = previous_epoch_number + 1
    swept_at = db.now()
    swept_at_utc = db.now_str()

    counters = {
        "credentials_expired_count": 0,
        "credentials_warned_count": 0,
        "reps_suspended_count": 0,
        "reps_reinstated_count": 0,
        "authorizations_revoked_count": 0,
        "badges_voided_count": 0,
        "badges_expired_count": 0,
        "approvals_expired_count": 0,
        "incidents_closed_count": 0,
        "vendors_rescored_count": 0,
    }

    _phase_2_age_credentials(swept_at, counters)
    newly_suspended = _phase_3_refresh_postures(counters)
    _phase_4_propagate_suspensions(swept_at, newly_suspended, counters)
    _phase_5_expire_badges(swept_at, counters)
    _phase_6_expire_approvals(swept_at, counters)
    _phase_7_close_findings(swept_at, counters)
    _phase_8_rescore(epoch_number, counters)

    # Phase 9 writes the record.  A sweep carries only id and created_at: it has
    # no updated_at and no version, and is never updated once written.
    row = {
        "id": db.new_id(),
        "created_at": swept_at_utc,
        "epoch_number": epoch_number,
        "previous_epoch_number": previous_epoch_number,
        "swept_at_utc": swept_at_utc,
        "_seq": db.next_seq(),
    }
    row.update(counters)
    store.sweeps[row["id"]] = row

    cascades.flush()
    return respond_object(db.public(row), 201)
