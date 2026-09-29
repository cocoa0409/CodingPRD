"""Pretext templates, campaign governance, scheduling and the scorecard."""
from flask import Blueprint

import calc
import cascades
import derive
import guards
import lookups
from envelope import created, ok, ok_list, paginate
from errors import fail
from store import add_days, new_row, now, ordered, store, touch

bp = Blueprint("campaigns", __name__)


# --------------------------------------------------------------- templates
@bp.post("/awareness/phishing-templates")
def create_template():
    guards.authorize("ProgramAdmin", "CampaignAuthor")
    data = guards.body()
    name = guards.req_str(data, "name")
    pretext_category = guards.req_enum(data, "pretext_category", calc.PRETEXT_CATEGORIES)
    difficulty_tier = guards.req_enum(data, "difficulty_tier", calc.DIFFICULTY_TIERS)
    theme_tags = guards.opt_enum_array(data, "theme_tags", calc.THEME_TAGS, [])
    capture = guards.opt_bool(data, "credential_capture_enabled", False)

    row = new_row()
    row.update({
        "name": name,
        "pretext_category": pretext_category,
        "difficulty_tier": difficulty_tier,
        "theme_tags": theme_tags,
        "credential_capture_enabled": capture,
        "review_state": "DRAFT",
        "harmful_flag_hits": calc.harmful_flag_hits(theme_tags),
        "blocked_reason": None,
    })
    store.templates[row["id"]] = row
    return created(derive.template_json(row))


@bp.get("/awareness/phishing-templates/<template_id>")
def read_template(template_id):
    guards.authorize("ProgramAdmin", "CampaignAuthor", "CampaignApprover", "SecurityAnalyst")
    return ok(derive.template_json(lookups.get_template(template_id)))


@bp.post("/awareness/phishing-templates/<template_id>/approve-for-use")
def approve_template(template_id):
    guards.authorize("CampaignApprover")
    row = lookups.get_template(template_id)
    if row["review_state"] != "DRAFT":
        fail("ERR_TEMPLATE_STATE_INVALID", "only a DRAFT template can be approved for use")
    if row["harmful_flag_hits"]:
        fail("ERR_HARMFUL_PRETEXT_THEME", "the pretext carries prohibited theme tags")
    row["review_state"] = "APPROVED_FOR_USE"
    touch(row)
    return ok(derive.template_json(row))


@bp.post("/awareness/phishing-templates/<template_id>/block")
def block_template(template_id):
    guards.authorize("ProgramAdmin")
    data = guards.body()
    blocked_reason = guards.req_str(data, "blocked_reason")
    row = lookups.get_template(template_id)
    if row["review_state"] == "BLOCKED":
        fail("ERR_TEMPLATE_STATE_INVALID", "template is already BLOCKED")
    row["review_state"] = "BLOCKED"
    row["blocked_reason"] = blocked_reason
    touch(row)
    return ok(derive.template_json(row))


# ---------------------------------------------------------------- campaigns
@bp.post("/awareness/campaigns")
def create_campaign():
    actor = guards.authorize("CampaignAuthor")
    data = guards.body()
    name = guards.req_str(data, "name")
    template_id = guards.req_str(data, "template_id")
    difficulty_tier = guards.req_enum(data, "difficulty_tier", calc.DIFFICULTY_TIERS)
    target_departments = guards.opt_enum_array(data, "target_departments", calc.DEPARTMENTS, [])
    target_tenure_bands = guards.opt_enum_array(data, "target_tenure_bands", calc.TENURE_BANDS, [])
    min_tier = guards.opt_int(data, "target_min_repeat_tier", 0, 0, 3)
    ack = guards.opt_bool(data, "communication_policy_ack", False)

    template = lookups.get_template(template_id)
    if calc.TIER_RANK[difficulty_tier] > calc.TIER_RANK[template["difficulty_tier"]]:
        fail("ERR_CAMPAIGN_TIER_EXCEEDS_TEMPLATE",
             "the campaign tier exceeds the template's tier")

    row = new_row()
    row.update({
        "name": name,
        "template_id": template_id,
        "difficulty_tier": difficulty_tier,
        "target_departments": target_departments,
        "target_tenure_bands": target_tenure_bands,
        "target_min_repeat_tier": min_tier,
        "communication_policy_ack": ack,
        "author_user_id": actor.user_id,
        "reviewer_user_id": None,
        "state": "DRAFT",
        "rejection_reason": None,
        "scheduled_send_at": None,
        "launched_at": None,
        "closed_at": None,
        "cancelled_at": None,
        "debrief_note": None,
        "target_count": 0,
        "evaluable_count": 0,
        "click_rate": None,
        "report_rate": None,
        "credential_rate": None,
        "resilience_ratio": None,
    })
    store.campaigns[row["id"]] = row
    return created(derive.campaign_json(row))


@bp.get("/awareness/campaigns/<campaign_id>")
def read_campaign(campaign_id):
    guards.authorize("ProgramAdmin", "CampaignAuthor", "CampaignApprover", "SecurityAnalyst")
    return ok(derive.campaign_json(lookups.get_campaign(campaign_id)))


@bp.get("/awareness/campaigns")
def list_campaigns():
    guards.authorize("ProgramAdmin", "CampaignAuthor", "CampaignApprover", "SecurityAnalyst")
    limit, offset = guards.pagination()
    template_id = guards.query_str("template_id")
    state = guards.query_enum("state", calc.CAMPAIGN_STATES)
    difficulty_tier = guards.query_enum("difficulty_tier", calc.DIFFICULTY_TIERS)

    rows = []
    for row in ordered(list(store.campaigns.values())):
        if template_id is not None and row["template_id"] != template_id:
            continue
        if state is not None and row["state"] != state:
            continue
        if difficulty_tier is not None and row["difficulty_tier"] != difficulty_tier:
            continue
        rows.append(row)
    page, total = paginate(rows, limit, offset)
    return ok_list([derive.campaign_json(r) for r in page], limit, offset, total)


def _author_owned(actor, campaign):
    if campaign["author_user_id"] != actor.user_id:
        fail("ERR_NOT_CAMPAIGN_AUTHOR", "the acting author does not own this campaign")


@bp.post("/awareness/campaigns/<campaign_id>/submit-for-review")
def submit_for_review(campaign_id):
    actor = guards.authorize("CampaignAuthor")
    campaign = lookups.get_campaign(campaign_id)
    _author_owned(actor, campaign)
    if campaign["state"] not in ("DRAFT", "REJECTED"):
        fail("ERR_CAMPAIGN_STATE_INVALID", "cannot submit from state %s" % campaign["state"])
    if not campaign["communication_policy_ack"]:
        fail("ERR_COMMUNICATION_POLICY_NOT_ACKNOWLEDGED",
             "communication_policy_ack must be true before review")
    campaign["state"] = "IN_REVIEW"
    campaign["rejection_reason"] = None
    touch(campaign)
    return ok(derive.campaign_json(campaign))


@bp.post("/awareness/campaigns/<campaign_id>/approve")
def approve_campaign(campaign_id):
    actor = guards.authorize("CampaignApprover")
    campaign = lookups.get_campaign(campaign_id)
    if campaign["state"] != "IN_REVIEW":
        fail("ERR_CAMPAIGN_STATE_INVALID", "cannot approve from state %s" % campaign["state"])
    template = store.templates.get(campaign["template_id"])
    if template is not None and template["harmful_flag_hits"]:
        fail("ERR_HARMFUL_PRETEXT_THEME", "the referenced pretext carries prohibited themes")
    if campaign["author_user_id"] == actor.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES_VIOLATION", "an approver may not approve their own campaign")
    if template is None or template["review_state"] != "APPROVED_FOR_USE":
        fail("ERR_TEMPLATE_NOT_APPROVED", "the referenced template is not APPROVED_FOR_USE")
    campaign["state"] = "APPROVED"
    campaign["reviewer_user_id"] = actor.user_id
    touch(campaign)
    return ok(derive.campaign_json(campaign))


@bp.post("/awareness/campaigns/<campaign_id>/reject")
def reject_campaign(campaign_id):
    actor = guards.authorize("CampaignApprover")
    data = guards.body()
    rejection_reason = guards.req_str(data, "rejection_reason")
    campaign = lookups.get_campaign(campaign_id)
    if campaign["state"] != "IN_REVIEW":
        fail("ERR_CAMPAIGN_STATE_INVALID", "cannot reject from state %s" % campaign["state"])
    if campaign["author_user_id"] == actor.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES_VIOLATION", "an approver may not reject their own campaign")
    campaign["state"] = "REJECTED"
    campaign["reviewer_user_id"] = actor.user_id
    campaign["rejection_reason"] = rejection_reason
    touch(campaign)
    return ok(derive.campaign_json(campaign))


# ------------------------------------------------------------ cohort resolution
def _resolve_cohort(campaign):
    """calculations.cohort_resolution -- pure, ordered by ascending created_at."""
    clock = now()
    departments = campaign["target_departments"]
    bands = campaign["target_tenure_bands"]
    min_tier = campaign["target_min_repeat_tier"]
    cohort = []
    for emp in ordered(list(store.employees.values())):
        if emp["employment_status"] != "ACTIVE":
            continue
        if departments and emp["department"] not in departments:
            continue
        if bands and calc.tenure_band(emp, clock) not in bands:
            continue
        if calc.repeat_clicker_tier(emp, clock) < min_tier:
            continue
        cohort.append(emp)
    return cohort


def _blackout_conflict(cohort, send_at):
    departments = set(emp["department"] for emp in cohort)
    for window in ordered(list(store.windows.values())):
        if window["window_type"] != "SIMULATION_BLACKOUT":
            continue
        scope = window["scope_department"]
        if scope is not None and scope not in departments:
            continue
        if window["start_at"] <= send_at <= window["end_at"]:
            return window
    return None


def _quiet_conflict(campaign, cohort, send_at):
    """Half-open [reference, reference + 5d); this campaign's own QUEUED rows ignored."""
    for emp in cohort:
        for delivery in calc.deliveries_of_employee(emp["id"]):
            if delivery["state"] == "EXCLUDED":
                continue
            if delivery["campaign_id"] == campaign["id"] and delivery["state"] == "QUEUED":
                continue
            reference = calc.quiet_reference_instant(delivery)
            if reference is None:
                continue
            until = add_days(reference, calc.QUIET_PERIOD_DAYS)
            if reference <= send_at < until:
                return delivery
    return None


@bp.post("/awareness/campaigns/<campaign_id>/schedule")
def schedule_campaign(campaign_id):
    actor = guards.authorize("CampaignAuthor")
    data = guards.body()
    send_at = guards.req_instant(data, "scheduled_send_at")
    expected = guards.req_int(data, "expected_campaign_version")

    campaign = lookups.get_campaign(campaign_id)
    _author_owned(actor, campaign)
    if expected != campaign["version"]:
        fail("ERR_STALE_CAMPAIGN_VERSION",
             "expected_campaign_version %s does not match %s" % (expected, campaign["version"]))
    if campaign["state"] not in ("APPROVED", "SCHEDULED"):
        fail("ERR_CAMPAIGN_STATE_INVALID", "cannot schedule from state %s" % campaign["state"])

    clock = now()
    if send_at <= clock:
        fail("ERR_SCHEDULE_IN_PAST", "scheduled_send_at must be strictly later than the clock")

    cohort = _resolve_cohort(campaign)
    if _blackout_conflict(cohort, send_at) is not None:
        fail("ERR_COMMUNICATION_BLACKOUT_CONFLICT",
             "scheduled_send_at falls inside a SIMULATION_BLACKOUT window")
    if _quiet_conflict(campaign, cohort, send_at) is not None:
        fail("ERR_SIMULATION_QUIET_PERIOD_CONFLICT",
             "a cohort member is still inside their simulation quiet period")

    evaluable = [emp for emp in cohort if calc.access_posture(emp["id"]) != "SUSPENDED"]
    if not evaluable:
        fail("ERR_EMPTY_TARGET_COHORT", "the resolved cohort has no evaluable member")

    # Release the prior reservation set (reschedule only).
    cascades.release_queued_deliveries(campaign, "CAMPAIGN_RESCHEDULED")

    for emp in cohort:
        suspended = calc.access_posture(emp["id"]) == "SUSPENDED"
        row = new_row()
        row.update({
            "campaign_id": campaign["id"],
            "employee_id": emp["id"],
            "base_difficulty_tier": campaign["difficulty_tier"],
            "effective_difficulty_tier": calc.effective_tier_for(campaign, emp, clock),
            "state": "EXCLUDED" if suspended else "QUEUED",
            "queued_at": clock,
            "delivered_at": None,
            "first_click_at": None,
            "first_report_at": None,
            "credential_submitted_at": None,
            "excluded_reason": "ACCESS_SUSPENDED" if suspended else None,
            "_tenure_band": calc.tenure_band(emp, clock),
        })
        store.deliveries[row["id"]] = row
        if not suspended:
            # The reservation is what bumps the employee.
            cascades.bump_employee(emp)

    campaign["state"] = "SCHEDULED"
    campaign["scheduled_send_at"] = send_at
    campaign["target_count"] = len(cohort)
    campaign["evaluable_count"] = len(evaluable)
    touch(campaign)
    return ok(derive.campaign_json(campaign))


@bp.post("/awareness/campaigns/<campaign_id>/launch")
def launch_campaign(campaign_id):
    guards.authorize("ProgramAdmin")
    campaign = lookups.get_campaign(campaign_id)
    if campaign["state"] != "SCHEDULED":
        fail("ERR_CAMPAIGN_STATE_INVALID", "cannot launch from state %s" % campaign["state"])
    clock = now()
    if campaign["scheduled_send_at"] is not None and clock < campaign["scheduled_send_at"]:
        fail("ERR_LAUNCH_BEFORE_SCHEDULE", "the logical clock has not reached scheduled_send_at")

    for delivery in calc.deliveries_of_campaign(campaign["id"]):
        if delivery["state"] != "QUEUED":
            continue
        emp = cascades.employee_of(delivery)
        if emp is not None and emp["employment_status"] == "ACTIVE":
            delivery["state"] = "DELIVERED"
            delivery["delivered_at"] = clock
        else:
            delivery["state"] = "EXCLUDED"
            delivery["excluded_reason"] = "EMPLOYEE_OFFBOARDED"
        touch(delivery)
        cascades.bump_employee(emp)

    campaign["state"] = "RUNNING"
    campaign["launched_at"] = clock
    campaign["evaluable_count"] = len([d for d in calc.deliveries_of_campaign(campaign["id"])
                                       if d["state"] != "EXCLUDED"])
    touch(campaign)
    return ok(derive.campaign_json(campaign))


@bp.post("/awareness/campaigns/<campaign_id>/close")
def close_campaign(campaign_id):
    guards.authorize("ProgramAdmin")
    data = guards.body()
    raw_note = data.get("debrief_note")
    if raw_note is not None and not isinstance(raw_note, str):
        fail("ERR_INVALID_REQUEST", "field 'debrief_note' must be a string")

    campaign = lookups.get_campaign(campaign_id)
    if campaign["state"] != "RUNNING":
        fail("ERR_CAMPAIGN_STATE_INVALID", "cannot close from state %s" % campaign["state"])
    if raw_note is None or not raw_note.strip():
        fail("ERR_COMMUNICATION_POLICY_NOT_ACKNOWLEDGED", "a non-empty debrief_note is required")

    clock = now()
    cohort_ids = []
    for delivery in calc.deliveries_of_campaign(campaign["id"]):
        if delivery["state"] == "EXCLUDED":
            continue
        if delivery["employee_id"] not in cohort_ids:
            cohort_ids.append(delivery["employee_id"])
        if delivery["state"] == "DELIVERED":
            delivery["state"] = "NO_INTERACTION"
            touch(delivery)

    bundle = calc.campaign_rates(campaign["id"])
    campaign["click_rate"] = bundle["click_rate"]
    campaign["report_rate"] = bundle["report_rate"]
    campaign["credential_rate"] = bundle["credential_rate"]
    campaign["resilience_ratio"] = bundle["resilience_ratio"]
    campaign["evaluable_count"] = bundle["evaluable_count"]
    campaign["state"] = "CLOSED"
    campaign["closed_at"] = clock
    campaign["debrief_note"] = raw_note
    touch(campaign)

    # Every cohort member settles exactly once; the derived metrics recompute on read.
    for employee_id in cohort_ids:
        cascades.bump_employee(store.employees.get(employee_id))
    return ok(derive.campaign_json(campaign))


@bp.post("/awareness/campaigns/<campaign_id>/cancel")
def cancel_campaign(campaign_id):
    actor = guards.authorize("CampaignAuthor")
    campaign = lookups.get_campaign(campaign_id)
    _author_owned(actor, campaign)
    if campaign["state"] not in ("DRAFT", "IN_REVIEW", "REJECTED", "APPROVED", "SCHEDULED"):
        fail("ERR_CAMPAIGN_STATE_INVALID", "cannot cancel from state %s" % campaign["state"])
    cascades.release_queued_deliveries(campaign, "CAMPAIGN_CANCELLED")
    campaign["state"] = "CANCELLED"
    campaign["cancelled_at"] = now()
    campaign["evaluable_count"] = 0
    touch(campaign)
    return ok(derive.campaign_json(campaign))


# ---------------------------------------------------------------- scorecard
def _segment_rows(deliveries, kind):
    """Groups every delivery by its key, then rates the evaluable subset."""
    groups = {}
    order = []
    for delivery in deliveries:
        if kind == "DEPARTMENT":
            emp = store.employees.get(delivery["employee_id"])
            key = emp["department"] if emp is not None else None
        else:
            key = delivery.get("_tenure_band")
        if key is None:
            continue
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(delivery)

    rows = []
    for key in order:
        bundle = calc.rate_bundle(groups[key])
        row = {
            "segment_type": kind,
            "segment_by": kind,
            "segment_key": key,
            "segment_value": key,
            "evaluable_count": bundle["evaluable_count"],
            "click_rate": bundle["click_rate"],
            "report_rate": bundle["report_rate"],
            "credential_rate": bundle["credential_rate"],
            "resilience_ratio": bundle["resilience_ratio"],
        }
        if kind == "DEPARTMENT":
            row["department"] = key
        else:
            row["tenure_band"] = key
        rows.append(row)
    return rows


@bp.get("/awareness/campaigns/<campaign_id>/scorecard")
def campaign_scorecard(campaign_id):
    guards.authorize("ProgramAdmin", "SecurityAnalyst")
    raw = guards.query_str("segment_by")
    if raw is None:
        selectors = ["DEPARTMENT", "TENURE_BAND"]
    else:
        normalised = raw.strip().upper()
        if normalised not in ("DEPARTMENT", "TENURE_BAND"):
            fail("ERR_INVALID_REQUEST", "segment_by must be DEPARTMENT or TENURE_BAND")
        selectors = [normalised]

    campaign = lookups.get_campaign(campaign_id)
    deliveries = calc.deliveries_of_campaign(campaign["id"])
    bundle = calc.rate_bundle(deliveries)
    segments = []
    for kind in selectors:
        segments.extend(_segment_rows(deliveries, kind))

    return ok({
        "campaign_id": campaign["id"],
        "evaluable_count": bundle["evaluable_count"],
        "excluded_count": len([d for d in deliveries if d["state"] == "EXCLUDED"]),
        "click_rate": bundle["click_rate"],
        "report_rate": bundle["report_rate"],
        "credential_rate": bundle["credential_rate"],
        "resilience_ratio": bundle["resilience_ratio"],
        "segments": segments,
    })
