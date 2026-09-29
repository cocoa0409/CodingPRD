"""Derived counters and the cascades of PRD 2.8.  Every helper here mutates the
rows it is handed and bumps `updated_at`/`version` on each carrying row exactly
once per request, as PRD 2.5 requires."""

import calc
import store
from auth import ROLE_OWNER
from common import ZERO, add_days, clock_now, fmt_instant, parse_instant
from errors import ApiError
from store import touch

OPEN_APPLICATION_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED")
UNIT_STATUS_TRANSITIONS = {
    "OPERATING": ("SUSPENDED", "TERMINATED"),
    "SUSPENDED": ("OPERATING", "TERMINATED"),
    "TERMINATED": (),
}
ONBOARDING_RUNGS = {
    ("TRAINING", "COMPLETED"): ("training_status", None, None),
    ("SYSTEMS", "PROVISIONED"): ("systems_status", "training_status", "COMPLETED"),
    ("SYSTEMS", "VALIDATED"): ("systems_status", "systems_status", "PROVISIONED"),
    ("CHANNEL", "TESTING"): ("channel_status", "systems_status", "VALIDATED"),
    ("CHANNEL", "CONNECTED"): ("channel_status", "channel_status", "TESTING"),
}
BLOCKING_COMPLIANCE = ("DEFAULT_NOTICE", "TERMINATION_ELIGIBLE")


def now():
    return fmt_instant(clock_now())


# ---------------------------------------------------------------------------
# Graph helpers
# ---------------------------------------------------------------------------


def brand_of_application(application):
    return store.brands.get(application["brand_id"])


def owner_of_application(application):
    return store.owners.get(application["owner_id"])


def application_of_agreement(agreement):
    return store.applications.get(agreement["application_id"])


def owner_id_of_agreement(agreement):
    application = application_of_agreement(agreement)
    return application["owner_id"] if application else None


def room_count_of_agreement(agreement):
    application = application_of_agreement(agreement)
    return application["room_count"] if application else 0


def require_agreement_owner(principal, agreement):
    if principal.role != ROLE_OWNER:
        return
    if principal.user_id != owner_id_of_agreement(agreement):
        raise ApiError("ERR_FORBIDDEN_RESOURCE_OWNER")


def require_application_owner(principal, application):
    if principal.role != ROLE_OWNER:
        return
    if principal.user_id != application["owner_id"]:
        raise ApiError("ERR_FORBIDDEN_RESOURCE_OWNER")


# ---------------------------------------------------------------------------
# Brand counters
# ---------------------------------------------------------------------------


def brand_recount(brand):
    if brand is None:
        return
    brand["operating_unit_count"] = len(
        [
            u
            for u in store.existing_units.values()
            if u["brand_id"] == brand["id"] and u["status"] == "OPERATING"
        ]
    )
    brand["open_application_count"] = len(
        [
            a
            for a in store.applications.values()
            if a["brand_id"] == brand["id"]
            and a["status"] in OPEN_APPLICATION_STATUSES
        ]
    )
    touch(brand)


# ---------------------------------------------------------------------------
# Improvement plan counters and deadlines
# ---------------------------------------------------------------------------


def pip_recount(pip):
    items = store.items_of_pip(pip)
    pip["items_total_count"] = len(items)
    pip["items_pending_count"] = len([i for i in items if i["status"] == "PENDING"])
    pip["items_submitted_count"] = len([i for i in items if i["status"] == "SUBMITTED"])
    pip["items_verified_count"] = len([i for i in items if i["status"] == "VERIFIED"])
    pip["items_overdue_count"] = len([i for i in items if i["status"] == "OVERDUE"])


def pip_refresh_deadline(pip):
    stamps = [i["due_date"] for i in store.items_of_pip(pip) if i["due_date"]]
    pip["overall_deadline"] = max(stamps) if stamps else None


def pip_refresh_extension_total(pip):
    pip["extension_granted_days_total"] = sum(
        int(i["extension_granted_days_total"]) for i in store.items_of_pip(pip)
    )


def pip_recost(pip):
    pip["total_estimated_cost"] = calc.pip_total_cost(store.items_of_pip(pip))


def item_stamp_due_dates(item, accepted_at):
    anchor = parse_instant(accepted_at)
    base = add_days(anchor, calc.item_allowance_days(item))
    item["base_due_date"] = fmt_instant(base)
    item["due_date"] = fmt_instant(
        add_days(base, int(item["extension_granted_days_total"]))
    )


def item_recompute_due_date(item):
    if not item["base_due_date"]:
        return
    item["due_date"] = fmt_instant(
        add_days(
            parse_instant(item["base_due_date"]),
            int(item["extension_granted_days_total"]),
        )
    )


def blocking_overdue_items(pip):
    return [
        i
        for i in store.items_of_pip(pip)
        if i["status"] == "OVERDUE"
        and (i["priority"] == "CRITICAL" or i["category"] == "LIFE_SAFETY")
    ]


# ---------------------------------------------------------------------------
# Compliance axis and the cascades that drive it
# ---------------------------------------------------------------------------


def set_compliance(agreement, status):
    agreement["compliance_status"] = status
    agreement["transfer_consent_blocked"] = status in BLOCKING_COMPLIANCE


def refuse_open_transfer_requests(agreement):
    """The DEFAULT_NOTICE cascade: open consent requests are refused without an
    acting human, which is why decision_user_id stays null."""
    stamp = now()
    for request in store.ordered(
        store.transfer_requests,
        lambda r: r["agreement_id"] == agreement["id"] and r["status"] == "SUBMITTED",
    ):
        request["status"] = "REFUSED"
        request["refusal_reason"] = "DEFAULT_NOTICE"
        request["decided_at"] = stamp
        request["decision_user_id"] = None
        touch(request)


def raise_pip_default_notice(agreement):
    stamp = now()
    set_compliance(agreement, "DEFAULT_NOTICE")
    agreement["default_notice_issued_at"] = stamp
    agreement["pip_cure_deadline"] = fmt_instant(
        add_days(parse_instant(stamp), calc.PIP_DEFAULT_CURE_DAYS)
    )
    touch(agreement)
    refuse_open_transfer_requests(agreement)


def refresh_last_inspection(agreement):
    rows = [
        i for i in store.inspections.values() if i["agreement_id"] == agreement["id"]
    ]
    if not rows:
        agreement["last_inspection_at"] = None
        return
    rows.sort(key=lambda r: (r["inspection_at"], r["created_at"], r["_seq"]))
    agreement["last_inspection_at"] = rows[-1]["inspection_at"]


# ---------------------------------------------------------------------------
# Fresh-row templates
# ---------------------------------------------------------------------------


def new_agreement_row():
    row = store.new_row("agreement")
    row.update(
        {
            "status": "DRAFT",
            "compliance_status": "COMPLIANT",
            "training_status": "NOT_STARTED",
            "systems_status": "NOT_STARTED",
            "channel_status": "NOT_CONNECTED",
            "de_identification_status": "NOT_REQUIRED",
            "de_identification_deadline": None,
            "de_identification_items_completed": [],
            "de_identification_breach_penalty": ZERO,
            "consecutive_qa_failure_count": 0,
            "revenue_periods": [],
            "royalty_fee_to_date": ZERO,
            "marketing_fund_contributed_total": ZERO,
            "reservation_fee_to_date": ZERO,
            "total_fees_assessed": ZERO,
            "reported_period_count": 0,
            "default_notice_issued_at": None,
            "pip_cure_deadline": None,
            "transfer_consent_blocked": False,
            "transfer_consent_count": 0,
            "termination_cause": None,
            "liquidated_damages_formula": None,
            "liquidated_damages_amount": None,
            "liquidated_damages_paid_amount": ZERO,
            "remaining_term_months_at_termination": None,
            "trailing_avg_monthly_fee": None,
            "post_termination_status": "NOT_APPLICABLE",
            "executed_at": None,
            "opened_at": None,
            "last_inspection_at": None,
            "terminated_at": None,
            "closed_out_at": None,
            "liquidated_damages_cap_months": calc.LD_CAP_MONTHS,
        }
    )
    return row


def new_pip_row(agreement):
    row = store.new_row("pip")
    row.update(
        {
            "agreement_id": agreement["id"],
            "status": "SCOPED",
            "items_total_count": 0,
            "items_pending_count": 0,
            "items_submitted_count": 0,
            "items_verified_count": 0,
            "items_overdue_count": 0,
            "total_estimated_cost": ZERO,
            "cost_per_room": ZERO,
            "key_money_pct": 0,
            "franchisor_key_money": ZERO,
            "owner_net_cost": ZERO,
            "owner_net_cost_per_room": ZERO,
            "escalation_required": False,
            "accepted_at": None,
            "overall_deadline": None,
            "extension_granted_days_total": 0,
            "acknowledgement": None,
        }
    )
    return row


def new_item_row(pip):
    row = store.new_row("pip_item")
    row.update(
        {
            "pip_id": pip["id"],
            "status": "PENDING",
            "base_due_date": None,
            "due_date": None,
            "extension_status": "NONE",
            "extension_requested_days": 0,
            "extension_granted_days_total": 0,
            "extension_request_count": 0,
            "extension_reason": None,
            "rejection_count": 0,
            "completion_evidence": None,
            "completed_at": None,
            "verified_at": None,
            "overdue_at": None,
        }
    )
    return row


def new_application_row():
    row = store.new_row("application")
    row.update(
        {
            "status": "SUBMITTED",
            "revision_round": 0,
            "financial_review_status": "NOT_STARTED",
            "capacity_basis": None,
            "capacity_score_at_review": None,
            "capacity_band_at_review": None,
            "financial_reviewer_user_id": None,
            "impact_study_status": "NOT_STARTED",
            "preliminary_impact_score": None,
            "impact_unit_count_preliminary": None,
            "base_impact_score": None,
            "final_impact_score": None,
            "impact_unit_count_final": None,
            "sustained_claim_count": 0,
            "encroachment_verdict": None,
            "claim_window_closes_at": None,
            "encroachment_waiver_granted": False,
            "decision_outcome": None,
            "decision_user_id": None,
            "decided_at": None,
            "decision_notes": None,
            "revision_notes": None,
            "revision_response": None,
        }
    )
    return row
