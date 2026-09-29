"""The logical clock and the Acquisition endpoints (PRD sections 2.6, 3.1, 3.3, 3.10)."""

from decimal import Decimal

import calc
import clock
import enums
import envelope
import machines
import serialize
import services
import store
import validate
from errors import ApiError
from store import set_field

CONSIDERATION_FIELDS = (
    "purchase_price_cents",
    "integration_reserve_cents",
    "gross_consideration_cents",
    "synergy_credit_bps",
    "synergy_credit_cents",
    "net_consideration_cents",
)


def set_clock():
    validate.gate(enums.ROLES_CLOCK)
    body = validate.json_body()
    instant = validate.req_instant(body, "to_iso8601")
    clock.CLOCK.set(instant)
    return envelope.object_response({"current_utc": clock.CLOCK.instant_str()})


def create_acquisition():
    validate.gate(enums.ROLES_DEAL_LEAD)
    body = validate.json_body()
    target_practice_name = validate.req_str(body, "target_practice_name")
    specialty = validate.req_enum(body, "specialty", enums.SPECIALTIES)
    structure = validate.req_enum(body, "structure", enums.STRUCTURES)
    policy_form = validate.req_enum(body, "malpractice_policy_form",
                                    enums.POLICY_FORMS)
    annual_premium = validate.req_int(body, "annual_malpractice_premium_cents",
                                      minimum=0)
    tail_months = validate.opt_int(body, "tail_coverage_months", 0,
                                   minimum=0, maximum=120)
    trailing = validate.req_int(body, "trailing_annual_collections_cents",
                                minimum=0)
    target_close_on = validate.req_date(body, "target_close_on")
    headcount = validate.req_int(body, "required_staff_headcount", minimum=1)
    retention_total = validate.req_int(body, "retention_pool_total_cents",
                                       minimum=0)
    escrow_total = validate.req_int(body, "escrow_total_cents", minimum=0)

    row = {
        "target_practice_name": target_practice_name,
        "specialty": specialty,
        "structure": structure,
        "malpractice_policy_form": policy_form,
        "annual_malpractice_premium_cents": annual_premium,
        "tail_coverage_months": tail_months,
        # Decided once and permanently at creation.
        "tail_coverage_required": policy_form == "CLAIMS_MADE",
        "tail_premium_cents": None,
        "trailing_annual_collections_cents": trailing,
        "target_close_on": clock.format_date(target_close_on),
        "required_staff_headcount": headcount,
        "retention_pool_total_cents": retention_total,
        "retention_pool_committed_cents": 0,
        "retention_pool_available_cents": retention_total,
        "escrow_total_cents": escrow_total,
        "escrow_committed_cents": 0,
        "escrow_available_cents": escrow_total,
        "deal_status": "SOURCING",
        "compliance_clearance": "PENDING",
        "readiness_posture": "BLOCKED",
        "purchase_price_cents": None,
        "integration_reserve_cents": None,
        "gross_consideration_cents": None,
        "synergy_credit_bps": None,
        "synergy_credit_cents": None,
        "net_consideration_cents": None,
        "hr_staffing_coverage_pct": calc.rhu2(Decimal(0)),
        "closed_at": None,
        "abandoned_reason": None,
    }
    store.insert("acquisitions", row)
    return services.respond_created(row)


def _no_executed_plan(acquisition, from_state, target):
    for plan in services.plans_of(acquisition):
        if plan["status"] == "EXECUTED":
            raise machines.invalid(from_state, target)


def _require_cleared(acquisition, from_state, target):
    """The clearance precondition has no dedicated code for PENDING; FLAGGED and
    SUSPENDED are reported one rank later by the freeze itself."""
    if acquisition["compliance_clearance"] == "PENDING":
        raise machines.invalid(from_state, target)


def acquisition_status(entity_id):
    user_id, role = validate.gate(enums.ROLES_DEAL_LEAD)
    body = validate.json_body()
    target = validate.req_enum(body, "target_status",
                               machines.DEAL_STATUS_VALUES)
    abandoned_reason = validate.opt_str(body, "abandoned_reason")

    acquisition = store.require("acquisitions", entity_id)
    from_state = acquisition["deal_status"]

    # Rank 14: transition legality and the preconditions with no dedicated code.
    machines.resolve(machines.DEAL_STATUS, from_state, target, role)
    if from_state == "SOURCING" and target == "DILIGENCE":
        if not services.physicians_of(acquisition):
            raise machines.invalid(from_state, target)
    if from_state == "DILIGENCE" and target == "BOARD_REVIEW":
        if len(services.accepted_fmv_opinions(acquisition)) != 1:
            raise machines.invalid(from_state, target)
    if from_state == "BOARD_REVIEW" and target in ("DILIGENCE", "ABANDONED"):
        _no_executed_plan(acquisition, from_state, target)
    if target in ("SIGNED", "CLOSED"):
        _require_cleared(acquisition, from_state, target)

    # Rank 15: the compliance-clearance freeze.
    services.check_freeze(acquisition)

    if target == "BOARD_REVIEW":
        _board_review_gates(acquisition)
    elif target == "SIGNED":
        _signing_gates(acquisition)
    elif target == "CLOSED":
        _closing_gates(acquisition)

    set_field(acquisition, "deal_status", target)

    if target == "DILIGENCE" and from_state == "SOURCING":
        services.recompute_posture(acquisition)
    elif target == "BOARD_REVIEW":
        _apply_board_review(acquisition)
    elif target == "DILIGENCE" and from_state == "BOARD_REVIEW":
        _revert_board_review(acquisition)
    elif target == "SIGNED":
        services.recompute_posture(acquisition)
    elif target == "CLOSED":
        set_field(acquisition, "closed_at", clock.CLOCK.instant_str())
        services.supersede_open_opinions(acquisition)
    elif target == "ABANDONED":
        set_field(acquisition, "abandoned_reason", abandoned_reason)
        if from_state in ("DILIGENCE", "BOARD_REVIEW"):
            services.supersede_open_opinions(acquisition)
            services.rescind_extended_offers(acquisition)

    return services.respond(acquisition)


def _board_review_gates(acquisition):
    # Rank 21, then rank 30, then rank 37.
    if (acquisition["tail_coverage_required"]
            and acquisition["tail_coverage_months"] < calc.TAIL_MIN_MONTHS):
        raise ApiError("ERR_TAIL_COVERAGE_INSUFFICIENT",
                       "tail_coverage_months must be at least %d."
                       % calc.TAIL_MIN_MONTHS)
    fmv = services.accepted_fmv_opinions(acquisition)[0]
    if services.expired_on(fmv["expires_on"]):
        raise ApiError("ERR_VALUATION_OPINION_EXPIRED",
                       "The accepted FMV opinion expired on %s."
                       % fmv["expires_on"])
    if services.accepted_reasonable_cr(acquisition) is None:
        raise ApiError("ERR_COMMERCIAL_REASONABLENESS_NOT_ESTABLISHED",
                       "No accepted REASONABLE commercial reasonableness opinion.")


def _signing_gates(acquisition):
    # Rank 38, then rank 40, then rank 47.
    plans = services.plans_of(acquisition)
    for physician in services.physicians_of(acquisition):
        if not any(p["physician_id"] == physician["id"]
                   and p["status"] in ("APPROVED", "EXECUTED") for p in plans):
            raise ApiError("ERR_COMP_PLAN_MISSING",
                           "Physician %s has no approved or executed plan."
                           % physician["id"])
    for item in store.where("liability_items",
                            acquisition_id=acquisition["id"]):
        if item["disposition"] == "UNASSIGNED":
            raise ApiError("ERR_LIABILITY_UNASSIGNED",
                           "Liability item %s is still UNASSIGNED." % item["id"])
    if acquisition["tail_coverage_required"]:
        premium = acquisition["tail_premium_cents"] or 0
        if acquisition["escrow_total_cents"] < premium:
            raise ApiError("ERR_TAIL_RESERVE_INSUFFICIENT",
                           "escrow_total_cents does not cover the tail premium.")


def _closing_gates(acquisition):
    # Rank 39, then rank 41, then rank 42, then rank 43.
    plans = services.plans_of(acquisition)
    for physician in services.physicians_of(acquisition):
        if not any(p["physician_id"] == physician["id"]
                   and p["status"] == "EXECUTED" for p in plans):
            raise ApiError("ERR_NO_EXECUTED_COMP_PLAN",
                           "Physician %s has no executed plan." % physician["id"])
    if acquisition["readiness_posture"] != "READY":
        raise ApiError("ERR_READINESS_NOT_READY",
                       "readiness_posture is %s." % acquisition["readiness_posture"])
    for contract in store.where("payer_contracts",
                                acquisition_id=acquisition["id"]):
        if contract["novation_status"] not in ("NOVATED", "TERMINATED"):
            raise ApiError("ERR_PAYER_NOVATION_INCOMPLETE",
                           "Payer contract %s is in %s."
                           % (contract["id"], contract["novation_status"]))
    for batch in store.where("ehr_migration_batches",
                             acquisition_id=acquisition["id"]):
        if batch["status"] not in ("RECONCILED", "ABORTED"):
            raise ApiError("ERR_MIGRATION_INCOMPLETE",
                           "Migration batch %s is in %s."
                           % (batch["id"], batch["status"]))


def _apply_board_review(acquisition):
    """Four side effects, in order (PRD section 3.3)."""
    fmv = services.accepted_fmv_opinions(acquisition)[0]
    set_field(fmv, "is_pinned", True)
    purchase_price = fmv["concluded_value_cents"]
    set_field(acquisition, "purchase_price_cents", purchase_price)
    premium = calc.malpractice_tail_premium(
        acquisition["tail_coverage_required"],
        acquisition["specialty"],
        acquisition["annual_malpractice_premium_cents"],
        acquisition["tail_coverage_months"],
    )
    set_field(acquisition, "tail_premium_cents", premium)
    chain = calc.deal_net_consideration(purchase_price, premium,
                                        acquisition["escrow_committed_cents"])
    for name, value in chain.items():
        set_field(acquisition, name, value)


def _revert_board_review(acquisition):
    for opinion in services.accepted_fmv_opinions(acquisition):
        if opinion["is_pinned"]:
            set_field(opinion, "is_pinned", False)
    for name in CONSIDERATION_FIELDS:
        set_field(acquisition, name, None)
    services.return_submitted_plans(acquisition)


def compliance_clearance(entity_id):
    user_id, role = validate.gate(enums.ROLES_COMPLIANCE)
    body = validate.json_body()
    target = validate.req_enum(body, "target_clearance",
                               machines.CLEARANCE_VALUES)
    validate.opt_str(body, "clearance_note")

    acquisition = store.require("acquisitions", entity_id)
    from_state = acquisition["compliance_clearance"]

    machines.resolve(machines.CLEARANCE, from_state, target, role)
    if target == "CLEARED":
        for plan in services.plans_of(acquisition):
            if plan["status"] == "COMPLIANCE_HOLD":
                raise machines.invalid(from_state, target)

    # This endpoint is exempt from the freeze -- it is the only way out of it.

    if from_state == "PENDING" and target == "CLEARED":
        for plan in services.plans_of(acquisition):
            if plan["includes_referral_credit"]:
                raise ApiError("ERR_REFERRAL_LINKED_COMPENSATION",
                               "Compensation plan %s includes referral credit."
                               % plan["id"])

    if from_state == "CLEARED" and target == "FLAGGED":
        services.flag_clearance(acquisition)
    else:
        set_field(acquisition, "compliance_clearance", target)
        if from_state == "FLAGGED" and target == "SUSPENDED":
            services.rescind_draft_offers(acquisition)

    return services.respond(acquisition)


def register(app):
    app.add_url_rule("/_clock/set_current_utc", "set_clock", set_clock,
                     methods=["POST"])
    app.add_url_rule("/acquisitions", "create_acquisition", create_acquisition,
                     methods=["POST"])
    app.add_url_rule("/acquisitions/<entity_id>/status", "acquisition_status",
                     acquisition_status, methods=["POST"])
    app.add_url_rule("/acquisitions/<entity_id>/compliance-clearance",
                     "compliance_clearance", compliance_clearance,
                     methods=["POST"])
