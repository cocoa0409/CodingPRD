"""Serializers, resource lookups and the cascade layer (PRD sections 2.9, 3.4-3.9).

Every derived field here is recomputed by replaying its defining rule over
current data rather than incrementally patched, and every row a cascade reaches
refreshes its own `updated_at` and increments its own `version` by exactly 1.
"""

from decimal import Decimal

import calc
from core import (D, EVIDENCE_COMMON, MUTABLE_COMMON, db, fail, fmt_ts, new_row,
                  newest_first, now, num, oldest_first, plus_days, plus_hours, q2,
                  touch)


# ==========================================================================
# serializers
# ==========================================================================
def s_policy_rule(row):
    return {
        "id": row["id"],
        "code": row["code"],
        "title": row["title"],
        "category_class": row["category_class"],
        "base_severity_weight": num(row["base_severity_weight"]),
        "requires_certification": row["requires_certification"],
        "requires_disclaimer": row["requires_disclaimer"],
        "confidence_auto_disapprove_threshold": num(row["confidence_auto_disapprove_threshold"]),
        "confidence_manual_threshold": num(row["confidence_manual_threshold"]),
        "review_sla_hours": row["review_sla_hours"],
        "default_queue": row["default_queue"],
        "country_override_count": row["country_override_count"],
        "created_at": fmt_ts(row["created_at"]),
        "updated_at": fmt_ts(row["updated_at"]),
        "version": row["version"],
    }


def s_country_override(row):
    return {
        "id": row["id"],
        "policy_rule_id": row["policy_rule_id"],
        "country_code": row["country_code"],
        "disposition": row["disposition"],
        "requires_license": row["requires_license"],
        "requires_disclaimer": row["requires_disclaimer"],
        "severity_multiplier": num(row["severity_multiplier"]),
        "created_at": fmt_ts(row["created_at"]),
        "updated_at": fmt_ts(row["updated_at"]),
        "version": row["version"],
    }


def s_advertiser(row):
    return {
        "id": row["id"],
        "legal_name": row["legal_name"],
        "country_code": row["country_code"],
        "industry_code": row["industry_code"],
        "identity_status": row["identity_status"],
        "business_standing_status": row["business_standing_status"],
        "industry_authorization_status": row["industry_authorization_status"],
        "political_eligibility_status": row["political_eligibility_status"],
        "account_status": row["account_status"],
        "violation_points_raw": num(row["violation_points_raw"]),
        "violation_points_decayed": num(row["violation_points_decayed"]),
        "severity_index": num(row["severity_index"]),
        "ledger_entry_count": row["ledger_entry_count"],
        "created_at": fmt_ts(row["created_at"]),
        "updated_at": fmt_ts(row["updated_at"]),
        "version": row["version"],
    }


def s_reviewer(row):
    return {
        "id": row["id"],
        "display_name": row["display_name"],
        "queue_specialties": list(row["queue_specialties"]),
        "country_authorizations": list(row["country_authorizations"]),
        "max_concurrent_claims": row["max_concurrent_claims"],
        "claimed_task_count": row["claimed_task_count"],
        "status": row["status"],
        "created_at": fmt_ts(row["created_at"]),
        "updated_at": fmt_ts(row["updated_at"]),
        "version": row["version"],
    }


def s_ad_creative(row):
    return {
        "id": row["id"],
        "advertiser_id": row["advertiser_id"],
        "headline": row["headline"],
        "body_text": row["body_text"],
        "declared_category_codes": list(row["declared_category_codes"]),
        "target_country_codes": list(row["target_country_codes"]),
        "landing_page_url": row["landing_page_url"],
        "display_url": row["display_url"],
        "political_flag": row["political_flag"],
        "disclaimer_text": row["disclaimer_text"],
        "review_status": row["review_status"],
        "destination_status": row["destination_status"],
        "risk_score_provisional": num(row["risk_score_provisional"]),
        "risk_score_final": num(row["risk_score_final"]),
        "serving_eligible": row["serving_eligible"],
        "blocking_reason_codes": list(row["blocking_reason_codes"]),
        "limited_country_codes": list(row["limited_country_codes"]),
        "approved_under_certification_id": row["approved_under_certification_id"],
        "screening_run_count": row["screening_run_count"],
        "created_at": fmt_ts(row["created_at"]),
        "updated_at": fmt_ts(row["updated_at"]),
        "version": row["version"],
    }


def s_screening_run(row):
    return {
        "id": row["id"],
        "ad_creative_id": row["ad_creative_id"],
        "classifier_version": row["classifier_version"],
        "sequence_index": row["sequence_index"],
        "outcome": row["outcome"],
        "decision_count": row["decision_count"],
        "max_confidence": num(row["max_confidence"]),
        "provisional_risk_score": num(row["provisional_risk_score"]),
        "creative_version_at_run": row["creative_version_at_run"],
        "created_at": fmt_ts(row["created_at"]),
    }


def s_classifier_decision(row):
    return {
        "id": row["id"],
        "screening_run_id": row["screening_run_id"],
        "policy_rule_id": row["policy_rule_id"],
        "confidence": num(row["confidence"]),
        "matched_snippet": row["matched_snippet"],
        "disposition": row["disposition"],
        "country_multiplier_applied": num(row["country_multiplier_applied"]),
        "assessed_points": num(row["assessed_points"]),
        "created_at": fmt_ts(row["created_at"]),
    }


def s_review_task(row):
    return {
        "id": row["id"],
        "ad_creative_id": row["ad_creative_id"],
        "primary_policy_rule_id": row["primary_policy_rule_id"],
        "assigned_reviewer_id": row["assigned_reviewer_id"],
        "queue": row["queue"],
        "status": row["status"],
        "resolution": row["resolution"],
        "priority_score": num(row["priority_score"]),
        "sla_deadline_at": fmt_ts(row["sla_deadline_at"]),
        "cycle_count": row["cycle_count"],
        "claimed_at": fmt_ts(row["claimed_at"]),
        "escalation_note": row["escalation_note"],
        "created_at": fmt_ts(row["created_at"]),
        "updated_at": fmt_ts(row["updated_at"]),
        "version": row["version"],
    }


def s_certification(row):
    return {
        "id": row["id"],
        "advertiser_id": row["advertiser_id"],
        "policy_rule_id": row["policy_rule_id"],
        "license_number": row["license_number"],
        "issuing_country_code": row["issuing_country_code"],
        "valid_from": fmt_ts(row["valid_from"]),
        "valid_until": fmt_ts(row["valid_until"]),
        "status": row["status"],
        "revocation_reason": row["revocation_reason"],
        "created_at": fmt_ts(row["created_at"]),
        "updated_at": fmt_ts(row["updated_at"]),
        "version": row["version"],
    }


def s_destination_check(row):
    return {
        "id": row["id"],
        "ad_creative_id": row["ad_creative_id"],
        "check_type": row["check_type"],
        "user_agent_variant": row["user_agent_variant"],
        "fetched_final_url": row["fetched_final_url"],
        "fetched_content_category": row["fetched_content_category"],
        "http_status": row["http_status"],
        "result": row["result"],
        "mismatch_detail": row["mismatch_detail"],
        "created_at": fmt_ts(row["created_at"]),
    }


def s_disapproval_notice(row):
    return {
        "id": row["id"],
        "ad_creative_id": row["ad_creative_id"],
        "decided_by_reviewer_id": row["decided_by_reviewer_id"],
        "reason_codes": list(row["reason_codes"]),
        "policy_rule_codes": list(row["policy_rule_codes"]),
        "assessment_lines": [
            {
                "policy_rule_code": line["policy_rule_code"],
                "reason_code": line["reason_code"],
                "line_points": num(line["line_points"]),
            }
            for line in row["assessment_lines"]
        ],
        "assessed_points": num(row["assessed_points"]),
        "disclosed_points_total": num(row["disclosed_points_total"]),
        "appeal_window_hours": row["appeal_window_hours"],
        "appeal_deadline_at": fmt_ts(row["appeal_deadline_at"]),
        "status": row["status"],
        "political_at_issue": row["political_at_issue"],
        "created_at": fmt_ts(row["created_at"]),
        "updated_at": fmt_ts(row["updated_at"]),
        "version": row["version"],
    }


def s_appeal(row):
    return {
        "id": row["id"],
        "disapproval_notice_id": row["disapproval_notice_id"],
        "evidence_certification_id": row["evidence_certification_id"],
        "decided_by_reviewer_id": row["decided_by_reviewer_id"],
        "justification": row["justification"],
        "status": row["status"],
        "decided_at": fmt_ts(row["decided_at"]),
        "reinstated_review_status": row["reinstated_review_status"],
        "created_at": fmt_ts(row["created_at"]),
        "updated_at": fmt_ts(row["updated_at"]),
        "version": row["version"],
    }


def s_enforcement_action(row):
    return {
        "id": row["id"],
        "advertiser_id": row["advertiser_id"],
        "prior_action_id": row["prior_action_id"],
        "source_notice_id": row["source_notice_id"],
        "action_type": row["action_type"],
        "origin": row["origin"],
        "trigger_reason": row["trigger_reason"],
        "severity_index_at_issue": num(row["severity_index_at_issue"]),
        "effective_from": fmt_ts(row["effective_from"]),
        "effective_until": fmt_ts(row["effective_until"]),
        "status": row["status"],
        "created_at": fmt_ts(row["created_at"]),
        "updated_at": fmt_ts(row["updated_at"]),
        "version": row["version"],
    }


def s_political_archive_entry(row):
    return {
        "id": row["id"],
        "ad_creative_id": row["ad_creative_id"],
        "advertiser_id": row["advertiser_id"],
        "disclosure_text": row["disclosure_text"],
        "payer_name": row["payer_name"],
        "headline_snapshot": row["headline_snapshot"],
        "target_country_codes_snapshot": list(row["target_country_codes_snapshot"]),
        "archived_at": fmt_ts(row["archived_at"]),
        "retention_until": fmt_ts(row["retention_until"]),
        "searchable": row["searchable"],
        "created_at": fmt_ts(row["created_at"]),
    }


def s_violation_ledger_entry(row):
    return {
        "id": row["id"],
        "advertiser_id": row["advertiser_id"],
        "source_notice_id": row["source_notice_id"],
        "delta_points": num(row["delta_points"]),
        "reason": row["reason"],
        "balance_after": num(row["balance_after"]),
        "entry_index": row["entry_index"],
        "created_at": fmt_ts(row["created_at"]),
    }


# ==========================================================================
# lookups (PRD 2.5: left-to-right, one dedicated 404 per identifier position)
# ==========================================================================
def get_policy_rule(rule_id):
    row = db.policy_rules.get(rule_id)
    if row is None:
        fail("ERR_POLICY_RULE_NOT_FOUND", 404)
    return row


def get_advertiser(advertiser_id):
    row = db.advertisers.get(advertiser_id)
    if row is None:
        fail("ERR_ADVERTISER_NOT_FOUND", 404)
    return row


def get_reviewer(reviewer_id):
    row = db.reviewers.get(reviewer_id)
    if row is None:
        fail("ERR_REVIEWER_NOT_FOUND", 404)
    return row


def get_creative(creative_id):
    row = db.ad_creatives.get(creative_id)
    if row is None:
        fail("ERR_AD_CREATIVE_NOT_FOUND", 404)
    return row


def get_screening_run(run_id):
    row = db.screening_runs.get(run_id)
    if row is None:
        fail("ERR_SCREENING_RUN_NOT_FOUND", 404)
    return row


def get_review_task(task_id):
    row = db.review_tasks.get(task_id)
    if row is None:
        fail("ERR_REVIEW_TASK_NOT_FOUND", 404)
    return row


def get_certification(certification_id):
    row = db.certifications.get(certification_id)
    if row is None:
        fail("ERR_CERTIFICATION_NOT_FOUND", 404)
    return row


def get_notice(notice_id):
    row = db.disapproval_notices.get(notice_id)
    if row is None:
        fail("ERR_DISAPPROVAL_NOTICE_NOT_FOUND", 404)
    return row


def get_appeal(appeal_id):
    row = db.appeals.get(appeal_id)
    if row is None:
        fail("ERR_APPEAL_NOT_FOUND", 404)
    return row


def get_enforcement_action(action_id):
    row = db.enforcement_actions.get(action_id)
    if row is None:
        fail("ERR_ENFORCEMENT_ACTION_NOT_FOUND", 404)
    return row


def rule_by_code_or_404(code):
    row = calc.rule_by_code(code)
    if row is None:
        fail("ERR_POLICY_RULE_NOT_FOUND", 404)
    return row


def owner_of(creative):
    return db.advertisers.get(creative["advertiser_id"])


def creatives_of(advertiser_id):
    return [c for c in db.ad_creatives.values() if c["advertiser_id"] == advertiser_id]


def tasks_of(creative_id):
    return [t for t in db.review_tasks.values() if t["ad_creative_id"] == creative_id]


def latest_task(creative):
    """PRD 3.7/3.9: the creative's most recently created task whatever its
    status, ranked by created_at descending."""
    rows = tasks_of(creative["id"])
    if not rows:
        return None
    return newest_first(rows)[0]


# ==========================================================================
# derived creative fields (PRD 2.11, 3.4)
# ==========================================================================
def recompute_gate(creative, advertiser=None, bump=True):
    """Recompute serving_eligible and blocking_reason_codes. Returns True when
    the derived output actually changed."""
    advertiser = advertiser or owner_of(creative)
    eligible, codes = calc.serving_gate(creative, advertiser)
    changed = (creative.get("serving_eligible") != eligible
               or list(creative.get("blocking_reason_codes") or []) != codes)
    creative["serving_eligible"] = eligible
    creative["blocking_reason_codes"] = codes
    if changed and bump:
        touch(creative)
    return changed


def write_risk_final(creative):
    creative["risk_score_final"] = calc.final_risk_score(creative)


def write_both_risk_scores(creative):
    creative["risk_score_provisional"] = calc.provisional_risk_score(creative)
    write_risk_final(creative)


# ==========================================================================
# advertiser posture, points and enforcement (PRD 3.2, 3.9)
# ==========================================================================
def derive_account_status(advertiser):
    """PRD 3.2: a pure function of the actions currently in force."""
    worst = None
    for action in calc.actions_of(advertiser["id"]):
        if action["status"] != "ACTIVE":
            continue
        rank = calc.ACTION_SEVERITY[action["action_type"]]
        if worst is None or rank > worst:
            worst = rank
    if worst is None:
        posture = "ACTIVE"
    elif worst == 1:
        posture = "WARNED"
    elif worst == 2:
        posture = "RESTRICTED"
    else:
        posture = "SUSPENDED"
    previous = advertiser.get("account_status")
    advertiser["account_status"] = posture
    touch(advertiser)
    if previous != posture:
        for creative in creatives_of(advertiser["id"]):
            recompute_gate(creative, advertiser)
    return posture


def recompute_advertiser_points(advertiser):
    """PRD 3.9: replay the whole ledger, then re-derive the severity index."""
    advertiser["violation_points_raw"] = calc.violation_points_raw(advertiser["id"])
    advertiser["violation_points_decayed"] = calc.violation_points_decayed(advertiser["id"])
    advertiser["ledger_entry_count"] = len(calc.ledger_of(advertiser["id"]))
    advertiser["severity_index"] = calc.enforcement_severity_index(advertiser)
    touch(advertiser)


def insert_ledger_entry(advertiser, notice_id, delta_points, reason):
    row = new_row(EVIDENCE_COMMON)
    existing = calc.ledger_of(advertiser["id"])
    row.update({
        "advertiser_id": advertiser["id"],
        "source_notice_id": notice_id,
        "delta_points": q2(delta_points),
        "reason": reason,
        "balance_after": Decimal("0.00"),
        "entry_index": len(existing) + 1,
    })
    db.violation_ledger_entries[row["id"]] = row
    recompute_advertiser_points(advertiser)
    row["balance_after"] = advertiser["violation_points_raw"]
    return row


def suspend_creatives(advertiser):
    """PRD 3.7/3.9: a suspension sweeps the advertiser's creatives to
    SUSPENDED_HOLD and expires their queued or claimed review tasks."""
    held = 0
    for creative in creatives_of(advertiser["id"]):
        if creative["review_status"] not in ("SCREENING", "AUTO_APPROVED",
                                            "PENDING_MANUAL_REVIEW", "APPROVED_LIMITED"):
            continue
        creative["review_status"] = "SUSPENDED_HOLD"
        expire_open_tasks(creative)
        recompute_gate(creative, advertiser, bump=False)
        write_risk_final(creative)
        touch(creative)
        held += 1
    return held


def create_enforcement_action(advertiser, action_type, origin, trigger_reason,
                              severity_index_at_issue, effective_until=None,
                              prior_action_id=None, source_notice_id=None):
    """PRD 3.9: creating an action supersedes whatever was in force, points
    prior_action_id at it, re-derives account_status, and a SUSPENSION
    additionally sweeps the advertiser's creatives to SUSPENDED_HOLD."""
    current = calc.active_action(advertiser["id"])
    row = new_row(MUTABLE_COMMON)
    effective_from = row["created_at"]
    if effective_until is None:
        effective_until = plus_days(effective_from,
                                    calc.ENFORCEMENT_DURATION_DAYS[action_type])
    row.update({
        "advertiser_id": advertiser["id"],
        "prior_action_id": prior_action_id if prior_action_id is not None else (
            current["id"] if current is not None else None),
        "source_notice_id": source_notice_id,
        "action_type": action_type,
        "origin": origin,
        "trigger_reason": trigger_reason,
        "severity_index_at_issue": q2(severity_index_at_issue),
        "effective_from": effective_from,
        "effective_until": effective_until,
        "status": "ACTIVE",
    })
    if current is not None:
        current["status"] = "SUPERSEDED"
        touch(current)
    db.enforcement_actions[row["id"]] = row
    posture = derive_account_status(advertiser)
    if posture == "SUSPENDED":
        suspend_creatives(advertiser)
    return row


def maybe_create_enforcement(advertiser, source_notice_id):
    """PRD 3.9 hop five: the refreshed severity index may raise an action."""
    action_type = calc.select_action_type(advertiser["severity_index"])
    if action_type is None:
        return None
    current = calc.active_action(advertiser["id"])
    if current is not None and \
            calc.ACTION_SEVERITY[action_type] <= calc.ACTION_SEVERITY[current["action_type"]]:
        return None
    return create_enforcement_action(
        advertiser, action_type, "SYSTEM_CASCADE",
        "Severity index %s reached the %s threshold." % (
            num(advertiser["severity_index"]), action_type),
        advertiser["severity_index"], source_notice_id=source_notice_id)


def lift_action_if_below_threshold(advertiser):
    """PRD 3.9: an action leaves force when the severity index has fallen
    strictly below the threshold for its own action_type."""
    lifted = 0
    for action in calc.actions_of(advertiser["id"]):
        if action["status"] != "ACTIVE":
            continue
        if advertiser["severity_index"] < calc.ACTION_THRESHOLDS[action["action_type"]]:
            action["status"] = "LIFTED"
            touch(action)
            lifted += 1
    if lifted:
        derive_account_status(advertiser)
    return lifted


# ==========================================================================
# review tasks (PRD 3.6)
# ==========================================================================
def _release_holder(task):
    reviewer = db.reviewers.get(task.get("assigned_reviewer_id"))
    if reviewer is not None:
        reviewer["claimed_task_count"] = max(0, reviewer["claimed_task_count"] - 1)
        touch(reviewer)


def expire_task(task):
    if task["status"] == "CLAIMED":
        _release_holder(task)
    task["status"] = "EXPIRED"
    task["assigned_reviewer_id"] = None
    touch(task)


def expire_open_tasks(creative):
    """Expire every QUEUED or CLAIMED task on the creative, with no replacement."""
    count = 0
    for task in oldest_first(tasks_of(creative["id"])):
        if task["status"] in ("QUEUED", "CLAIMED"):
            expire_task(task)
            count += 1
    return count


def expire_queued_tasks(creative):
    """PRD 3.3: a revision expires any queued task standing on this creative."""
    count = 0
    for task in oldest_first(tasks_of(creative["id"])):
        if task["status"] == "QUEUED":
            expire_task(task)
            count += 1
    return count


def create_review_task(creative, queue, primary_policy_rule_id, cycle_count=0):
    """A review task is never created by a client -- always a by-product of
    routing, re-routing, reinstatement or replacement (PRD 3.6)."""
    advertiser = owner_of(creative)
    rule = db.policy_rules.get(primary_policy_rule_id) if primary_policy_rule_id else None
    row = new_row(MUTABLE_COMMON)
    sla_hours = rule["review_sla_hours"] if rule is not None else calc.DEFAULT_SLA_HOURS
    row.update({
        "ad_creative_id": creative["id"],
        "primary_policy_rule_id": primary_policy_rule_id,
        "assigned_reviewer_id": None,
        "queue": queue,
        "status": "QUEUED",
        "resolution": "PENDING",
        "priority_score": calc.review_task_priority_score(queue, rule, creative, advertiser),
        "sla_deadline_at": plus_hours(row["created_at"], sla_hours),
        "cycle_count": cycle_count,
        "claimed_at": None,
        "escalation_note": None,
    })
    db.review_tasks[row["id"]] = row
    return row


def replacement_task_shape(creative):
    """PRD 3.7/3.9: copy queue and primary rule from the most recently created
    task whatever its status, defaulting to STANDARD with a null primary rule."""
    previous = latest_task(creative)
    if previous is None:
        return "STANDARD", None
    return previous["queue"], previous["primary_policy_rule_id"]


# ==========================================================================
# disapproval notices and their cascade (PRD 3.9)
# ==========================================================================
def issue_notice(creative, reason_codes, decided_by_reviewer_id):
    """Hop two onward of every disapproval cascade: the notice, its ledger
    entry, the advertiser refresh, and the enforcement it may raise."""
    advertiser = owner_of(creative)
    lines, assessed, rule_codes = calc.disapproval_assessment(
        creative, reason_codes, decided_by_reviewer_id)
    political = bool(creative["political_flag"])
    window = (calc.APPEAL_WINDOW_HOURS_POLITICAL if political
              else calc.APPEAL_WINDOW_HOURS_STANDARD)
    notice = new_row(MUTABLE_COMMON)
    notice.update({
        "ad_creative_id": creative["id"],
        "decided_by_reviewer_id": decided_by_reviewer_id,
        "reason_codes": list(reason_codes),
        "policy_rule_codes": rule_codes,
        "assessment_lines": lines,
        "assessed_points": assessed,
        "disclosed_points_total": Decimal("0.00"),
        "appeal_window_hours": window,
        "appeal_deadline_at": plus_hours(notice["created_at"], window),
        "status": "ISSUED",
        "political_at_issue": political,
    })
    db.disapproval_notices[notice["id"]] = notice
    insert_ledger_entry(advertiser, notice["id"], assessed, "DISAPPROVAL_ASSESSED")
    notice["disclosed_points_total"] = advertiser["violation_points_raw"]
    maybe_create_enforcement(advertiser, notice["id"])
    return notice


def write_archive_entry(creative, advertiser, countries):
    """PRD 3.7: approving a political creative writes an append-only entry."""
    row = new_row(EVIDENCE_COMMON)
    row.update({
        "ad_creative_id": creative["id"],
        "advertiser_id": advertiser["id"],
        "disclosure_text": creative["disclaimer_text"],
        "payer_name": advertiser["legal_name"],
        "headline_snapshot": creative["headline"],
        "target_country_codes_snapshot": list(countries),
        "archived_at": row["created_at"],
        "retention_until": plus_days(row["created_at"], calc.ARCHIVE_RETENTION_DAYS),
        "searchable": True,
    })
    db.political_archive_entries[row["id"]] = row
    return row


# ==========================================================================
# certification loss re-routing (PRD 3.5)
# ==========================================================================
def reroute_after_certification_loss(certification, statuses, clear_limited):
    """Every creative that leaned on the lost licence is re-routed to
    PENDING_MANUAL_REVIEW with a fresh QUEUED task in the REGULATED_CERT queue."""
    touched = 0
    for creative in oldest_first(list(db.ad_creatives.values())):
        if creative["approved_under_certification_id"] != certification["id"]:
            continue
        if creative["review_status"] not in statuses:
            continue
        creative["review_status"] = "PENDING_MANUAL_REVIEW"
        creative["approved_under_certification_id"] = None
        if clear_limited:
            creative["limited_country_codes"] = []
        create_review_task(creative, "REGULATED_CERT", None, 0)
        write_risk_final(creative)
        recompute_gate(creative, owner_of(creative), bump=False)
        touch(creative)
        touched += 1
    return touched
