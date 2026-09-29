"""Human review queue, reviewer decisions, certifications, notices and appeals.

The decision endpoint carries the compliance gates in the exact order PRD 2.10
fixes: prohibited category (11), political eligibility (13), disclosure (14),
licence coverage (20) and only then the retained country set's own shape (21).
"""

from decimal import Decimal

from flask import Blueprint, request

import calc
import services as svc
from core import (D, EVIDENCE_COMMON, MUTABLE_COMMON, ROLE_ADMIN, ROLE_ADVERTISER,
                  ROLE_REVIEWER, authenticate, db, fail, new_row, now, ok, ok_list,
                  oldest_first, pagination, paginate, parse_iso, plus_hours, q2,
                  require_reviewer_identity, touch, clock, fmt_ts)
from validate import (bad, body_or_empty, read_body, v_array, v_country, v_datetime,
                      v_enum, v_id, v_string, el_country, el_enum)

bp = Blueprint("review", __name__)

RESOLUTIONS = ("APPROVE", "APPROVE_WITH_LIMITS", "DISAPPROVE", "ESCALATE")
REASON_CODES = ("AUTO_SCREENING", "MANUAL_REVIEW", "DESTINATION_MISMATCH",
                "CLOAKING", "CERT_MISSING", "POLITICAL_DISCLOSURE")


def _scope_task(user_id, task_id):
    """Priority 3: the reviewer identity must resolve, and a task already held
    by somebody else is out of scope for the acting reviewer."""
    require_reviewer_identity(user_id, ROLE_REVIEWER)
    task = db.review_tasks.get(task_id)
    if task is not None and task["assigned_reviewer_id"] is not None \
            and task["assigned_reviewer_id"] != user_id:
        fail("ERR_ADVERTISER_SCOPE_VIOLATION", 403)
    return task


# ==========================================================================
# review tasks
# ==========================================================================
@bp.route("/review-tasks", methods=["GET"])
def list_review_tasks():
    authenticate()
    limit, offset = pagination()
    rows = list(db.review_tasks.values())
    for key in ("ad_creative_id", "primary_policy_rule_id", "assigned_reviewer_id",
                "status", "queue"):
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    rows.sort(key=lambda r: (-r["priority_score"], r["created_at"], r["_seq"]))
    page, total = paginate(rows, limit, offset)
    return ok_list([svc.s_review_task(r) for r in page], limit, offset, total)


@bp.route("/review-tasks/<task_id>", methods=["GET"])
def read_review_task(task_id):
    authenticate()
    return ok(svc.s_review_task(svc.get_review_task(task_id)))


@bp.route("/review-tasks/<task_id>/claim", methods=["POST"])
def claim_review_task(task_id):
    user_id, role = authenticate(ROLE_REVIEWER)
    reviewer = require_reviewer_identity(user_id, role)
    read_body(())
    task = svc.get_review_task(task_id)
    if task["status"] != "QUEUED":
        fail("ERR_INVALID_TASK_STATE", 409)
    creative = svc.get_creative(task["ad_creative_id"])
    # the four claim gates in their fixed order (PRD 3.6)
    for country in creative["target_country_codes"]:
        if country not in reviewer["country_authorizations"]:
            fail("ERR_REVIEWER_NOT_AUTHORIZED_COUNTRY", 403)
    if reviewer["status"] != "ACTIVE":
        fail("ERR_REVIEWER_OFFLINE", 409)
    if task["queue"] not in reviewer["queue_specialties"]:
        fail("ERR_REVIEWER_QUEUE_MISMATCH", 403)
    if not (reviewer["claimed_task_count"] < reviewer["max_concurrent_claims"]):
        fail("ERR_REVIEWER_CAPACITY_EXCEEDED", 409)
    task["status"] = "CLAIMED"
    task["assigned_reviewer_id"] = user_id
    task["claimed_at"] = now()
    reviewer["claimed_task_count"] += 1
    touch(reviewer)
    touch(task)
    return ok(svc.s_review_task(task))


@bp.route("/review-tasks/<task_id>/release", methods=["POST"])
def release_review_task(task_id):
    user_id, role = authenticate(ROLE_REVIEWER)
    _scope_task(user_id, task_id)
    read_body(())
    task = svc.get_review_task(task_id)
    if task["status"] != "CLAIMED":
        fail("ERR_INVALID_TASK_STATE", 409)
    reviewer = db.reviewers.get(task["assigned_reviewer_id"])
    task["status"] = "QUEUED"
    task["assigned_reviewer_id"] = None
    task["claimed_at"] = None
    if reviewer is not None:
        reviewer["claimed_task_count"] = max(0, reviewer["claimed_task_count"] - 1)
        touch(reviewer)
    # release deliberately does not recompute priority_score or sla_deadline_at
    touch(task)
    return ok(svc.s_review_task(task))


@bp.route("/review-tasks/<task_id>/requeue", methods=["POST"])
def requeue_review_task(task_id):
    authenticate(ROLE_ADMIN)
    read_body(())
    task = svc.get_review_task(task_id)
    if task["status"] != "ESCALATED":
        fail("ERR_INVALID_TASK_STATE", 409)
    creative = svc.get_creative(task["ad_creative_id"])
    if creative["review_status"] != "PENDING_MANUAL_REVIEW":
        fail("ERR_INVALID_CREATIVE_STATE", 409)
    advertiser = svc.owner_of(creative)
    rule = db.policy_rules.get(task["primary_policy_rule_id"]) \
        if task["primary_policy_rule_id"] else None
    task["status"] = "QUEUED"
    task["resolution"] = "PENDING"
    task["cycle_count"] += 1
    task["priority_score"] = calc.review_task_priority_score(
        task["queue"], rule, creative, advertiser)
    sla_hours = rule["review_sla_hours"] if rule is not None else calc.DEFAULT_SLA_HOURS
    task["sla_deadline_at"] = plus_hours(now(), sla_hours)
    touch(task)
    return ok(svc.s_review_task(task))


# ==========================================================================
# reviewer decisions and their gates (PRD 3.7)
# ==========================================================================
def _demands_disclosure(creative, retained):
    if creative["political_flag"]:
        return True
    matched = calc.rules_for(creative)
    for rule in matched:
        if rule["requires_disclaimer"]:
            return True
    for rule in matched:
        for country in retained:
            override = calc.override_for(rule, country)
            if override is not None and override["requires_disclaimer"]:
                return True
    return False


def _check_reason_codes(creative, reason_codes):
    matched = calc.rules_for(creative)
    for code in reason_codes:
        if code == "AUTO_SCREENING":
            fail("ERR_INVALID_REASON_CODE", 422)
        if code == "CLOAKING" and creative["destination_status"] != "CLOAKING_CONFIRMED":
            fail("ERR_INVALID_REASON_CODE", 422)
        if code == "DESTINATION_MISMATCH" and creative["destination_status"] != "MISMATCH_FLAGGED":
            fail("ERR_INVALID_REASON_CODE", 422)
        if code == "POLITICAL_DISCLOSURE" and not creative["political_flag"]:
            fail("ERR_INVALID_REASON_CODE", 422)
        if code == "CERT_MISSING":
            if not any(r["requires_certification"] for r in matched):
                fail("ERR_INVALID_REASON_CODE", 422)


@bp.route("/review-tasks/<task_id>/decision", methods=["POST"])
def decide_review_task(task_id):
    user_id, role = authenticate(ROLE_REVIEWER)
    _scope_task(user_id, task_id)
    data = read_body(("resolution", "reason_codes", "limited_country_codes", "note"),
                     ("resolution",))
    resolution = v_enum(data, "resolution", RESOLUTIONS)
    reason_codes = v_array(data, "reason_codes", required=False,
                           element=el_enum(REASON_CODES))
    # PRD 3.7 routes an empty or duplicated limited set to its own 422, so the
    # array is only shape-checked element by element here
    limited = v_array(data, "limited_country_codes", required=False,
                      non_empty=False, no_duplicates=False, element=el_country)
    note = v_string(data, "note", 1, 2000, required=False)
    if resolution == "DISAPPROVE" and reason_codes is None:
        bad("reason_codes is required on a DISAPPROVE decision.")
    if resolution == "APPROVE_WITH_LIMITS" and limited is None:
        bad("limited_country_codes is required on an APPROVE_WITH_LIMITS decision.")
    if resolution == "ESCALATE" and note is None:
        bad("note is required on an ESCALATE decision.")
    task = svc.get_review_task(task_id)
    if task["status"] != "CLAIMED":
        fail("ERR_INVALID_TASK_STATE", 409)
    if task["assigned_reviewer_id"] != user_id:
        fail("ERR_ADVERTISER_SCOPE_VIOLATION", 403)
    creative = svc.get_creative(task["ad_creative_id"])
    advertiser = svc.owner_of(creative)
    reviewer = db.reviewers.get(user_id)
    if resolution != "ESCALATE" and creative["review_status"] != "PENDING_MANUAL_REVIEW":
        fail("ERR_INVALID_CREATIVE_STATE", 409)
    retained = list(limited or []) if resolution == "APPROVE_WITH_LIMITS" \
        else list(creative["target_country_codes"])
    coverage_pool = []
    if resolution in ("APPROVE", "APPROVE_WITH_LIMITS"):
        # priority 11
        for decision in calc.qualifying_decisions(creative):
            rule = db.policy_rules.get(decision["policy_rule_id"])
            if rule is not None and rule["category_class"] == "PROHIBITED":
                fail("ERR_PROHIBITED_CATEGORY_BLOCKED", 422)
        for rule in calc.rules_for(creative):
            for country in retained:
                if calc.disposition(rule, country) == "BLOCKED":
                    fail("ERR_PROHIBITED_CATEGORY_BLOCKED", 422)
        # priority 13
        if creative["political_flag"] and \
                advertiser["political_eligibility_status"] != "ELIGIBLE":
            fail("ERR_POLITICAL_ELIGIBILITY_MISSING", 422)
        # priority 14
        if _demands_disclosure(creative, retained):
            text = creative["disclaimer_text"]
            if text is None or text == "":
                fail("ERR_POLITICAL_DISCLOSURE_MISSING", 422)
    if resolution == "APPROVE_WITH_LIMITS":
        # priority 20 -- coverage is judged before the country set's own shape
        instant = now()
        for country in retained:
            for rule in calc.rules_for(creative):
                if not calc.country_demands_license(rule, country):
                    continue
                candidates = calc.coverage_candidates(
                    advertiser["id"], rule["id"], country, instant)
                if not candidates:
                    fail("ERR_CERTIFICATION_MISSING", 422)
                coverage_pool.extend(candidates)
        # priority 21
        if len(retained) == 0 or len(set(retained)) != len(retained) \
                or not set(retained).issubset(set(creative["target_country_codes"])):
            fail("ERR_INVALID_LIMITED_COUNTRIES", 422)
    if resolution == "DISAPPROVE":
        # priority 29
        _check_reason_codes(creative, reason_codes)
    if resolution == "ESCALATE":
        task["status"] = "ESCALATED"
        task["resolution"] = "ESCALATE"
        task["escalation_note"] = note
        task["assigned_reviewer_id"] = None
        task["claimed_at"] = None
        if reviewer is not None:
            reviewer["claimed_task_count"] = max(0, reviewer["claimed_task_count"] - 1)
            touch(reviewer)
        touch(task)
        # escalation leaves the creative entirely alone -- no version bump
        return ok(svc.s_review_task(task))
    task["status"] = "RESOLVED"
    task["resolution"] = resolution
    task["assigned_reviewer_id"] = None
    task["claimed_at"] = None
    if reviewer is not None:
        reviewer["claimed_task_count"] = max(0, reviewer["claimed_task_count"] - 1)
        touch(reviewer)
    touch(task)
    if resolution == "APPROVE":
        creative["review_status"] = "AUTO_APPROVED"
        if creative["political_flag"]:
            svc.write_archive_entry(creative, advertiser, creative["target_country_codes"])
    elif resolution == "APPROVE_WITH_LIMITS":
        creative["review_status"] = "APPROVED_LIMITED"
        creative["limited_country_codes"] = sorted(retained)
        selection = calc.coverage_selection(coverage_pool)
        creative["approved_under_certification_id"] = \
            selection["id"] if selection is not None else None
        if creative["political_flag"]:
            svc.write_archive_entry(creative, advertiser, creative["limited_country_codes"])
    else:
        creative["review_status"] = "DISAPPROVED"
        svc.write_risk_final(creative)
        svc.issue_notice(creative, reason_codes, user_id)
    svc.write_risk_final(creative)
    svc.recompute_gate(creative, advertiser, bump=False)
    touch(creative)
    return ok(svc.s_review_task(task))


# ==========================================================================
# certifications (PRD 3.5)
# ==========================================================================
def _sec(dt):
    """Certification instants are compared at whole-second resolution."""
    return dt.replace(microsecond=0) if dt is not None else None


def _intervals_intersect(new_from, new_until, other):
    return new_from < other["valid_until"] and other["valid_from"] < new_until


@bp.route("/certifications", methods=["POST"])
def create_certification():
    user_id, role = authenticate(ROLE_ADVERTISER, ROLE_ADMIN)
    pre = body_or_empty()
    if role == ROLE_ADVERTISER and isinstance(pre.get("advertiser_id"), str) \
            and pre["advertiser_id"] != user_id:
        fail("ERR_ADVERTISER_SCOPE_VIOLATION", 403)
    data = read_body(("advertiser_id", "policy_rule_id", "license_number",
                      "issuing_country_code", "valid_from", "valid_until"),
                     ("advertiser_id", "policy_rule_id", "license_number",
                      "issuing_country_code", "valid_from", "valid_until"))
    advertiser_id = v_id(data, "advertiser_id")
    policy_rule_id = v_id(data, "policy_rule_id")
    license_number = v_string(data, "license_number", 1, 60)
    country = v_country(data, "issuing_country_code")
    valid_from = _sec(v_datetime(data, "valid_from"))
    valid_until = _sec(v_datetime(data, "valid_until"))
    advertiser = svc.get_advertiser(advertiser_id)
    rule = svc.get_policy_rule(policy_rule_id)
    if advertiser["account_status"] == "SUSPENDED":
        fail("ERR_ADVERTISER_SUSPENDED", 409)
    # priority 22 then priority 24
    if not (valid_until > valid_from):
        fail("ERR_INVALID_VALIDITY_WINDOW", 422)
    for other in db.certifications.values():
        if other["advertiser_id"] != advertiser["id"]:
            continue
        if other["policy_rule_id"] != rule["id"]:
            continue
        if other["issuing_country_code"] != country:
            continue
        if other["status"] not in ("SUBMITTED", "ACTIVE"):
            continue
        if _intervals_intersect(valid_from, valid_until, other):
            fail("ERR_CERTIFICATION_INTERVAL_OVERLAP", 409)
    row = new_row(MUTABLE_COMMON)
    instant = now()
    born_active = valid_from <= instant < valid_until
    row.update({
        "advertiser_id": advertiser["id"],
        "policy_rule_id": rule["id"],
        "license_number": license_number,
        "issuing_country_code": country,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "status": "ACTIVE" if born_active else "SUBMITTED",
        "revocation_reason": None,
    })
    db.certifications[row["id"]] = row
    return ok(svc.s_certification(row), 201)


@bp.route("/certifications", methods=["GET"])
def list_certifications():
    authenticate()
    limit, offset = pagination()
    rows = list(db.certifications.values())
    for key in ("advertiser_id", "policy_rule_id", "status"):
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    rows.sort(key=lambda r: (r["valid_from"], r["created_at"], r["_seq"]))
    page, total = paginate(rows, limit, offset)
    return ok_list([svc.s_certification(r) for r in page], limit, offset, total)


@bp.route("/certifications/<certification_id>", methods=["GET"])
def read_certification(certification_id):
    authenticate()
    return ok(svc.s_certification(svc.get_certification(certification_id)))


@bp.route("/certifications/<certification_id>/revoke", methods=["POST"])
def revoke_certification(certification_id):
    authenticate(ROLE_ADMIN)
    data = read_body(("revocation_reason",), ("revocation_reason",))
    reason = v_string(data, "revocation_reason", 1, 300)
    certification = svc.get_certification(certification_id)
    if certification["status"] not in ("SUBMITTED", "ACTIVE"):
        fail("ERR_INVALID_CERTIFICATION_STATE", 409)
    certification["status"] = "REVOKED"
    certification["revocation_reason"] = reason
    touch(certification)
    svc.reroute_after_certification_loss(certification, ("APPROVED_LIMITED",), True)
    return ok(svc.s_certification(certification))


# ==========================================================================
# disapproval notices
# ==========================================================================
@bp.route("/disapproval-notices", methods=["GET"])
def list_disapproval_notices():
    authenticate()
    limit, offset = pagination()
    rows = list(db.disapproval_notices.values())
    for key in ("ad_creative_id", "decided_by_reviewer_id", "status"):
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    page, total = paginate(oldest_first(rows), limit, offset)
    return ok_list([svc.s_disapproval_notice(r) for r in page], limit, offset, total)


@bp.route("/disapproval-notices/<notice_id>", methods=["GET"])
def read_disapproval_notice(notice_id):
    authenticate()
    return ok(svc.s_disapproval_notice(svc.get_notice(notice_id)))


@bp.route("/disapproval-notices/<notice_id>/violation-ledger-entries", methods=["GET"])
def list_notice_ledger_entries(notice_id):
    authenticate()
    limit, offset = pagination()
    notice = svc.get_notice(notice_id)
    rows = [e for e in db.violation_ledger_entries.values()
            if e["source_notice_id"] == notice["id"]]
    rows.sort(key=lambda e: e["entry_index"])
    page, total = paginate(rows, limit, offset)
    return ok_list([svc.s_violation_ledger_entry(r) for r in page], limit, offset, total)


# ==========================================================================
# appeals (PRD 3.9)
# ==========================================================================
@bp.route("/appeals", methods=["POST"])
def create_appeal():
    user_id, role = authenticate(ROLE_ADVERTISER)
    pre = body_or_empty()
    pre_notice = db.disapproval_notices.get(pre.get("disapproval_notice_id")) \
        if isinstance(pre.get("disapproval_notice_id"), str) else None
    if pre_notice is not None:
        pre_creative = db.ad_creatives.get(pre_notice["ad_creative_id"])
        if pre_creative is not None and pre_creative["advertiser_id"] != user_id:
            fail("ERR_ADVERTISER_SCOPE_VIOLATION", 403)
    data = read_body(("disapproval_notice_id", "justification", "evidence_certification_id"),
                     ("disapproval_notice_id", "justification"))
    notice_id = v_id(data, "disapproval_notice_id")
    justification = v_string(data, "justification", 10, 2000)
    evidence_id = v_id(data, "evidence_certification_id", required=False)
    notice = svc.get_notice(notice_id)
    evidence = svc.get_certification(evidence_id) if evidence_id is not None else None
    # priority 8: the duplicate check runs ahead of the notice-state check
    for appeal in db.appeals.values():
        if appeal["disapproval_notice_id"] == notice["id"]:
            fail("ERR_APPEAL_ALREADY_EXISTS", 409)
    if notice["status"] != "ISSUED":
        fail("ERR_NOTICE_NOT_APPEALABLE", 409)
    if not (now() < notice["appeal_deadline_at"]):
        fail("ERR_APPEAL_WINDOW_CLOSED", 409)
    creative = svc.get_creative(notice["ad_creative_id"])
    if evidence is not None and evidence["advertiser_id"] != creative["advertiser_id"]:
        fail("ERR_CERTIFICATION_OWNER_MISMATCH", 422)
    row = new_row(MUTABLE_COMMON)
    row.update({
        "disapproval_notice_id": notice["id"],
        "evidence_certification_id": evidence_id,
        "decided_by_reviewer_id": None,
        "justification": justification,
        "status": "SUBMITTED",
        "decided_at": None,
        "reinstated_review_status": None,
    })
    db.appeals[row["id"]] = row
    notice["status"] = "APPEALED"
    touch(notice)
    return ok(svc.s_appeal(row), 201)


@bp.route("/appeals", methods=["GET"])
def list_appeals():
    authenticate()
    limit, offset = pagination()
    rows = list(db.appeals.values())
    for key in ("disapproval_notice_id", "evidence_certification_id",
                "decided_by_reviewer_id", "status"):
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    page, total = paginate(oldest_first(rows), limit, offset)
    return ok_list([svc.s_appeal(r) for r in page], limit, offset, total)


@bp.route("/appeals/<appeal_id>", methods=["GET"])
def read_appeal(appeal_id):
    authenticate()
    return ok(svc.s_appeal(svc.get_appeal(appeal_id)))


@bp.route("/appeals/<appeal_id>/decision", methods=["POST"])
def decide_appeal(appeal_id):
    user_id, role = authenticate(ROLE_REVIEWER)
    require_reviewer_identity(user_id, role)
    data = read_body(("outcome", "note"), ("outcome",))
    outcome = v_enum(data, "outcome", ("GRANTED", "DENIED"))
    v_string(data, "note", 1, 2000, required=False, nullable=True)
    appeal = svc.get_appeal(appeal_id)
    notice = svc.get_notice(appeal["disapproval_notice_id"])
    if appeal["status"] != "SUBMITTED" or notice["status"] != "APPEALED":
        fail("ERR_APPEAL_NOT_PENDING", 409)
    # priority 15: no reviewer may sit in judgement on their own disapproval
    if notice["decided_by_reviewer_id"] is not None \
            and notice["decided_by_reviewer_id"] == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES", 403)
    creative = svc.get_creative(notice["ad_creative_id"])
    advertiser = svc.owner_of(creative)
    appeal["decided_by_reviewer_id"] = user_id
    appeal["decided_at"] = now()
    if outcome == "DENIED":
        appeal["status"] = "DENIED"
        notice["status"] = "APPEAL_UPHELD"
        touch(notice)
        touch(appeal)
        return ok(svc.s_appeal(appeal))
    appeal["status"] = "GRANTED"
    notice["status"] = "APPEAL_GRANTED"
    touch(notice)
    svc.insert_ledger_entry(advertiser, notice["id"],
                            -notice["assessed_points"], "APPEAL_REVERSAL")
    svc.lift_action_if_below_threshold(advertiser)
    if creative["review_status"] == "DISAPPROVED":
        queue, primary_rule_id = svc.replacement_task_shape(creative)
        creative["review_status"] = "PENDING_MANUAL_REVIEW"
        if creative["destination_status"] in ("MISMATCH_FLAGGED", "CLOAKING_CONFIRMED"):
            creative["destination_status"] = "DESTINATION_PENDING"
        appeal["reinstated_review_status"] = "PENDING_MANUAL_REVIEW"
        svc.create_review_task(creative, queue, primary_rule_id, 0)
        svc.write_risk_final(creative)
        svc.recompute_gate(creative, advertiser, bump=False)
        touch(creative)
    touch(appeal)
    return ok(svc.s_appeal(appeal))


# ==========================================================================
# enforcement action reads
# ==========================================================================
@bp.route("/enforcement-actions", methods=["GET"])
def list_enforcement_actions():
    authenticate()
    limit, offset = pagination()
    rows = list(db.enforcement_actions.values())
    for key in ("advertiser_id", "prior_action_id", "source_notice_id", "status"):
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    rows.sort(key=lambda r: (r["effective_from"], r["created_at"], r["_seq"]))
    page, total = paginate(rows, limit, offset)
    return ok_list([svc.s_enforcement_action(r) for r in page], limit, offset, total)


@bp.route("/enforcement-actions/<action_id>", methods=["GET"])
def read_enforcement_action(action_id):
    authenticate()
    return ok(svc.s_enforcement_action(svc.get_enforcement_action(action_id)))


# ==========================================================================
# the logical clock and the deterministic policy sweep (PRD 2.8)
# ==========================================================================
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    authenticate(ROLE_ADMIN)
    data = read_body(("to_iso8601",), ("to_iso8601",))
    raw = data.get("to_iso8601")
    if not isinstance(raw, str):
        bad("to_iso8601 must be an ISO 8601 UTC instant.")
    parsed = parse_iso(raw)
    if parsed is None or parsed < clock.current:
        fail("ERR_CLOCK_REWIND", 409)
    previous = clock.set(parsed)
    return ok({"previous_utc": fmt_ts(previous), "current_utc": fmt_ts(clock.current)})


def _has_active_suspension(advertiser_id):
    for action in calc.actions_of(advertiser_id):
        if action["status"] == "ACTIVE" and action["action_type"] == "SUSPENSION":
            return True
    return False


@bp.route("/_policy-sweeps/run", methods=["POST"])
def run_policy_sweep():
    authenticate(ROLE_ADMIN)
    read_body(())
    instant = now()
    activated_certifications = 0
    expired_certifications = 0
    expired_notices = 0
    expired_review_tasks = 0
    requeued_review_tasks = 0
    expired_enforcement_actions = 0
    lifted_enforcement_actions = 0
    released_hold_creatives = 0
    decay_refreshed_advertisers = 0

    # phase 1 -- activation of certifications whose validity now contains the clock
    for cert in oldest_first(list(db.certifications.values())):
        if cert["status"] != "SUBMITTED":
            continue
        if not (cert["valid_from"] <= instant < cert["valid_until"]):
            continue
        conflict = False
        for other in db.certifications.values():
            if other["id"] == cert["id"]:
                continue
            if other["advertiser_id"] != cert["advertiser_id"]:
                continue
            if other["policy_rule_id"] != cert["policy_rule_id"]:
                continue
            if other["issuing_country_code"] != cert["issuing_country_code"]:
                continue
            if other["status"] not in ("SUBMITTED", "ACTIVE"):
                continue
            if _intervals_intersect(cert["valid_from"], cert["valid_until"], other):
                conflict = True
                break
        if conflict:
            continue
        cert["status"] = "ACTIVE"
        touch(cert)
        activated_certifications += 1

    # phase 2 -- expiry, with the re-routing of creatives that relied on them
    for cert in oldest_first(list(db.certifications.values())):
        if cert["status"] not in ("SUBMITTED", "ACTIVE"):
            continue
        if cert["valid_until"] > instant:
            continue
        cert["status"] = "EXPIRED"
        touch(cert)
        expired_certifications += 1
        svc.reroute_after_certification_loss(
            cert, ("AUTO_APPROVED", "APPROVED_LIMITED"), False)

    # phase 3 -- expiry of notices whose appeal window has closed
    for notice in oldest_first(list(db.disapproval_notices.values())):
        if notice["status"] == "ISSUED" and notice["appeal_deadline_at"] <= instant:
            notice["status"] = "EXPIRED"
            touch(notice)
            expired_notices += 1

    # phase 4 -- SLA expiry, the one route that creates a replacement task
    for task in oldest_first(list(db.review_tasks.values())):
        if task["status"] not in ("QUEUED", "CLAIMED"):
            continue
        if task["sla_deadline_at"] > instant:
            continue
        creative = db.ad_creatives.get(task["ad_creative_id"])
        queue = task["queue"]
        primary_rule_id = task["primary_policy_rule_id"]
        cycle_count = task["cycle_count"]
        svc.expire_task(task)
        expired_review_tasks += 1
        if creative is not None:
            svc.create_review_task(creative, queue, primary_rule_id, cycle_count + 1)
            requeued_review_tasks += 1

    # phase 5 -- expiry of enforcement actions whose window has ended
    for action in oldest_first(list(db.enforcement_actions.values())):
        if action["status"] != "ACTIVE":
            continue
        if action["effective_until"] > instant:
            continue
        action["status"] = "EXPIRED"
        touch(action)
        expired_enforcement_actions += 1
        advertiser = db.advertisers.get(action["advertiser_id"])
        if advertiser is not None:
            svc.derive_account_status(advertiser)

    # phase 6 -- refresh of every advertiser's decayed balance and severity index
    advertisers = oldest_first(list(db.advertisers.values()))
    for advertiser in advertisers:
        before = (advertiser["violation_points_decayed"], advertiser["severity_index"])
        advertiser["violation_points_raw"] = calc.violation_points_raw(advertiser["id"])
        advertiser["violation_points_decayed"] = calc.violation_points_decayed(advertiser["id"])
        advertiser["ledger_entry_count"] = len(calc.ledger_of(advertiser["id"]))
        advertiser["severity_index"] = calc.enforcement_severity_index(advertiser)
        if (advertiser["violation_points_decayed"], advertiser["severity_index"]) != before:
            touch(advertiser)
            decay_refreshed_advertisers += 1

    # phase 7 -- lifting, which must follow the phase 6 refresh
    for advertiser in advertisers:
        lifted_enforcement_actions += svc.lift_action_if_below_threshold(advertiser)

    # phase 8 -- release of creatives held under a suspension that has ended
    for advertiser in advertisers:
        if _has_active_suspension(advertiser["id"]):
            continue
        for creative in oldest_first(svc.creatives_of(advertiser["id"])):
            if creative["review_status"] != "SUSPENDED_HOLD":
                continue
            queue, primary_rule_id = svc.replacement_task_shape(creative)
            creative["review_status"] = "PENDING_MANUAL_REVIEW"
            svc.create_review_task(creative, queue, primary_rule_id, 0)
            svc.write_risk_final(creative)
            svc.recompute_gate(creative, advertiser, bump=False)
            touch(creative)
            released_hold_creatives += 1

    return ok({
        "activated_certifications": activated_certifications,
        "expired_certifications": expired_certifications,
        "expired_notices": expired_notices,
        "expired_review_tasks": expired_review_tasks,
        "requeued_review_tasks": requeued_review_tasks,
        "expired_enforcement_actions": expired_enforcement_actions,
        "lifted_enforcement_actions": lifted_enforcement_actions,
        "released_hold_creatives": released_hold_creatives,
        "decay_refreshed_advertisers": decay_refreshed_advertisers,
    })
