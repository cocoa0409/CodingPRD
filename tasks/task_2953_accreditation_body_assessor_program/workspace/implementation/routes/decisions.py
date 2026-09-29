"""The independent decision panel, accredited scopes and surveillance (PRD 3.8, 3.9)."""

from flask import Blueprint

import calc
import domain
import store
from auth import ASSESSMENT_MANAGER, DECISION_PANEL_MEMBER, SCHEME_MANAGER, endpoint
from envelope import created, single
from errors import ApiError
from routes.applications import (CYCLE_TYPES, check_duplicate_active,
                                 check_notice_period, check_unannounced_authority,
                                 new_cycle, scope_lines_field)
from validators import body, enum_field, int_field, string_field, string_list_field

bp = Blueprint("decisions", __name__)

VOTES = ("GRANT", "GRANT_WITH_CONDITIONS", "REFUSE", "DEFER")
SCOPE_STATUSES = ("ACTIVE", "SUSPENDED", "WITHDRAWN")
SCOPE_TRANSITIONS = {
    ("ACTIVE", "SUSPENDED"),
    ("SUSPENDED", "ACTIVE"),
    ("ACTIVE", "WITHDRAWN"),
    ("SUSPENDED", "WITHDRAWN"),
}
CYCLE_NOT_WITHDRAWABLE = ("GRANTED", "REFUSED", "WITHDRAWN")


@bp.post("/accreditation/decisions/<decision_id>/votes")
@endpoint([DECISION_PANEL_MEMBER])
def cast_vote(user_id, role, decision_id):
    payload = body()
    vote = enum_field(payload, "vote", VOTES)
    rationale = string_field(payload, "rationale", 1)

    record = domain.find("decisions", decision_id)
    if record["status"] != "VOTING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "this record is no longer taking ballots")

    voter = store.get("assessors", user_id)
    if voter is None:
        raise ApiError("ERR_ASSESSOR_NOT_FOUND")
    if voter["qualification_status"] != "QUALIFIED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "a ballot may only be cast by an assessor in QUALIFIED standing")

    if domain.any_assignment(record["application_id"], user_id) is not None:
        raise ApiError("ERR_PANEL_INDEPENDENCE_BREACH")
    for ballot in record["votes"]:
        if ballot["voter_assessor_id"] == user_id:
            raise ApiError("ERR_DUPLICATE_PANEL_VOTE")

    record["votes"].append({
        "voter_assessor_id": user_id,
        "vote": vote,
        "rationale": rationale,
        "cast_at": store.now_iso(),
    })
    record["vote_count"] = len(record["votes"])
    store.touch(record)
    return single(store.public(record))


@bp.post("/accreditation/decisions/<decision_id>/finalize")
@endpoint([DECISION_PANEL_MEMBER])
def finalize_decision(user_id, role, decision_id):
    payload = body()
    granted_scope_lines = string_list_field(payload, "granted_scope_lines", 0, 20, 1, 80,
                                            required=False)

    record = domain.find("decisions", decision_id)
    if record["status"] != "VOTING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "this record is already terminal")

    application = store.get("applications", record["application_id"])
    if application["suspension_blocked"] or application["status"] != "DECISION_PENDING":
        raise ApiError("ERR_APPLICATION_STATE_INVALID",
                       "the cycle is not awaiting a panel decision")

    if not any(b["voter_assessor_id"] == user_id for b in record["votes"]):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the finalizing panel member must have cast a ballot on this record")

    scheme = store.get("schemes", application["scheme_id"])
    if scheme is None:
        raise ApiError("ERR_SCHEME_NOT_FOUND")
    if scheme["rule_revision"] != application["pinned_scheme_rule_revision"]:
        raise ApiError("ERR_SCHEME_VERSION_SUPERSEDED")

    outcome = calc.panel_outcome(record["votes"])
    requested = application["requested_scope_lines"]
    if outcome in ("GRANT", "GRANT_WITH_CONDITIONS"):
        supplied = granted_scope_lines if granted_scope_lines is not None else []
        for line in supplied:
            if line not in requested:
                raise ApiError("ERR_SCOPE_LINE_NOT_REQUESTED")

    if record["vote_count"] < calc.MIN_PANEL_VOTES:
        raise ApiError("ERR_PANEL_QUORUM_NOT_MET")

    if outcome == "GRANT_WITH_CONDITIONS":
        if granted_scope_lines is None or len(granted_scope_lines) >= len(requested):
            raise ApiError("ERR_CONDITIONS_REQUIRE_REDUCED_SCOPE")
    elif outcome == "GRANT":
        if granted_scope_lines is None or list(granted_scope_lines) != list(requested):
            raise ApiError("ERR_CONDITIONS_REQUIRE_REDUCED_SCOPE")

    today = store.clock_date()
    record["decided_on"] = store.iso_date(today)
    record["decided_by_user_id"] = user_id
    record["outcome"] = outcome

    if outcome == "DEFER":
        record["granted_scope_lines"] = None
        record["status"] = "DEFERRED"
        store.touch(record)
        application["status"] = "NC_OPEN"
        application["decision_round"] += 1
        store.touch(application)
        return single(store.public(record))

    record["granted_scope_lines"] = list(granted_scope_lines) \
        if outcome in ("GRANT", "GRANT_WITH_CONDITIONS") else None
    record["status"] = "DECIDED"
    store.touch(record)

    organization = store.get("organizations", application["organization_id"])
    if outcome == "REFUSE":
        application["status"] = "REFUSED"
        store.touch(application)
        if organization is not None:
            active = domain.recount_active_scopes(organization)
            if active == 0:
                organization["status"] = "APPLIED"
            else:
                organization["status"] = "ACCREDITED"
            domain.recompute_risk_at_decision(organization, application["id"])
        return single(store.public(record))

    application["status"] = "GRANTED"
    store.touch(application)

    pinned = domain.pinned(application)
    risk_at_grant = organization["risk_score"] if organization is not None else 0
    schedule = calc.surveillance_schedule(risk_at_grant, today,
                                          pinned["surveillance_interval_days"],
                                          pinned["reassessment_interval_days"])
    store.insert("scopes", {
        "application_id": application["id"],
        "organization_id": application["organization_id"],
        "scheme_id": application["scheme_id"],
        "scope_lines": list(record["granted_scope_lines"]),
        "status": "ACTIVE",
        "effective_from": store.iso_date(today),
        "risk_score_at_grant": risk_at_grant,
        "surveillance_interval_days_effective":
            schedule["surveillance_interval_days_effective"],
        "next_surveillance_due": store.iso_date(schedule["next_surveillance_due"]),
        "next_reassessment_due": store.iso_date(schedule["next_reassessment_due"]),
        "surveillance_risk_score": None,
        "suspension_reason": None,
        "withdrawn_on": None,
        "mra_notified": False,
    })

    if organization is not None:
        organization["status"] = "ACCREDITED"
        domain.recount_active_scopes(organization)
        domain.recompute_risk_at_decision(organization, application["id"])

    return single(store.public(record))


@bp.post("/accreditation/scopes/<scope_id>/status")
@endpoint([SCHEME_MANAGER])
def change_scope_status(user_id, role, scope_id):
    payload = body()
    to_status = enum_field(payload, "to_status", SCOPE_STATUSES)
    reason = string_field(payload, "reason", 1, 300, required=False)

    scope = domain.find("scopes", scope_id)
    if (scope["status"], to_status) not in SCOPE_TRANSITIONS:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "a %s scope cannot move to %s" % (scope["status"], to_status))

    if to_status == "SUSPENDED":
        domain.suspend_scope(scope, reason)
        return single(store.public(scope))

    if to_status == "ACTIVE":
        for application in store.rows("applications"):
            if application["organization_id"] != scope["organization_id"]:
                continue
            if application["id"] != scope["application_id"] \
                    and application["origin_scope_id"] != scope["id"]:
                continue
            for finding in store.rows("nonconformities"):
                if finding["application_id"] == application["id"] \
                        and finding["status"] == "ESCALATED":
                    raise ApiError("ERR_INVALID_STATE_TRANSITION",
                                   "an escalated finding still stands against this scope")
        scope["status"] = "ACTIVE"
        scope["suspension_reason"] = None
        store.touch(scope)
        organization = store.get("organizations", scope["organization_id"])
        if organization is not None:
            active = domain.recount_active_scopes(organization)
            if active >= 1:
                organization["status"] = "ACCREDITED"
                store.touch(organization)
            for application in store.ordered(store.rows("applications")):
                if application["organization_id"] != organization["id"]:
                    continue
                store.set_fields(application, suspension_blocked=False)
        return single(store.public(scope))

    scope["status"] = "WITHDRAWN"
    scope["withdrawn_on"] = store.today_iso()
    scope["mra_notified"] = True
    store.touch(scope)
    for application in store.ordered(store.rows("applications")):
        if application["origin_scope_id"] != scope["id"]:
            continue
        if application["status"] in CYCLE_NOT_WITHDRAWABLE:
            continue
        application["status"] = "WITHDRAWN"
        store.touch(application)
    organization = store.get("organizations", scope["organization_id"])
    if organization is not None:
        active = domain.recount_active_scopes(organization)
        if active == 0:
            organization["status"] = "WITHDRAWN"
            store.touch(organization)
    return single(store.public(scope))


@bp.post("/accreditation/scopes/<scope_id>/surveillance-applications")
@endpoint([SCHEME_MANAGER, ASSESSMENT_MANAGER])
def open_follow_on_cycle(user_id, role, scope_id):
    payload = body()
    cycle_type = enum_field(payload, "cycle_type", CYCLE_TYPES)
    scope_lines = scope_lines_field(payload, required=False)
    notice_days = int_field(payload, "notice_days", 0, 120, required=False, default=30)

    scope = domain.find("scopes", scope_id)
    if scope["status"] != "ACTIVE":
        raise ApiError("ERR_SCOPE_NOT_ACTIVE")

    organization = store.get("organizations", scope["organization_id"])
    scheme = store.get("schemes", scope["scheme_id"])
    granting = store.get("applications", scope["application_id"])
    granting_pinned = domain.pinned(granting) if granting is not None \
        else domain.scheme_snapshot(scheme)

    check_notice_period(cycle_type, notice_days)
    check_duplicate_active(scope["organization_id"], scope["scheme_id"])
    check_unannounced_authority(cycle_type, granting_pinned)

    lines = scope_lines if scope_lines is not None else list(scope["scope_lines"])
    application = new_cycle(organization, scheme, cycle_type, lines, notice_days, scope["id"])

    risk = domain.recompute_risk_at_surveillance_planning(
        organization, scope["application_id"], application["id"])
    scope["surveillance_risk_score"] = risk
    from validators import parse_date

    schedule = calc.surveillance_schedule(
        risk,
        parse_date(scope["effective_from"], "effective_from"),
        granting_pinned["surveillance_interval_days"],
        granting_pinned["reassessment_interval_days"],
    )
    scope["surveillance_interval_days_effective"] = \
        schedule["surveillance_interval_days_effective"]
    scope["next_surveillance_due"] = store.iso_date(schedule["next_surveillance_due"])
    store.touch(scope)

    return created(store.public(application))
