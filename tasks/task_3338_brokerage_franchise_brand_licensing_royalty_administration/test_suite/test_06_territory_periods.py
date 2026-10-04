"""Territory exclusivity and per-period occupancy rules."""
from test_helpers import (
    validate_error, get_success_data,
    setup_active_agreement,
    open_default, submit_gci_report, assess_period,
    create_agreement_payload, create_conversion_plan_payload, create_brokerage,
    ApiErrorId, TEST_USERS,
)

OPS = TEST_USERS["franchisor_ops_headers"]


def _make_ready_plan(api, agreement_id):
    plan = get_success_data(
        api.create_conversion_plan(agreement_id, create_conversion_plan_payload(), OPS)
    )
    get_success_data(
        api.complete_milestone(plan["id"], {"sequence": plan["milestones"][0]["sequence"]}, OPS)
    )
    return plan


def test_deidentifying_agreement_still_blocks_territory_regrant(api):
    """PRD §3.3: "Because a `TERMINATED` agreement hops into `DEIDENTIFYING`
    within the same request that terminates it, a terminated-but-not-yet-closed
    grant still blocks re-grant of its territory; only `DRAFT`, `EXPIRED`, and
    `CLOSED` agreements leave a market free."
    PRD §3.3: "A conflicting live grant is rejected with `ERR_TERRITORY_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/brand_market_regrant_blocked_until_deidentified
    """
    ctx = setup_active_agreement()
    brand_id = ctx["brand"]["id"]
    market_id = ctx["market"]["id"]

    default = open_default(ctx["agreement"]["id"], "PAYMENT")
    get_success_data(api.escalate_default_case(default["id"], OPS))
    terminated = get_success_data(api.terminate_agreement(ctx["agreement"]["id"], OPS))
    assert terminated["status"] == "DEIDENTIFYING"

    other = create_brokerage(market_id)
    draft = get_success_data(
        api.create_agreement(
            create_agreement_payload(other["id"], brand_id, market_id), OPS
        )
    )
    _make_ready_plan(api, draft["id"])
    resp = api.activate_agreement(
        draft["id"], {"expected_agreement_version": draft["version"]}, OPS
    )
    validate_error(resp, ApiErrorId.ERR_TERRITORY_CONFLICT)


def test_two_live_agreements_in_same_brand_and_market_conflict(api):
    """PRD §3.3: "no other agreement sharing the same `brand_id` and `market_id`
    may currently stand in `ACTIVE`, `SUSPENDED`, or `DEIDENTIFYING` status. A
    conflicting live grant is rejected with `ERR_TERRITORY_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/brand_market_regrant_blocked_until_deidentified
    """
    ctx = setup_active_agreement()
    brand_id = ctx["brand"]["id"]
    market_id = ctx["market"]["id"]

    other = create_brokerage(market_id)
    draft = get_success_data(
        api.create_agreement(
            create_agreement_payload(other["id"], brand_id, market_id), OPS
        )
    )
    _make_ready_plan(api, draft["id"])
    resp = api.activate_agreement(
        draft["id"], {"expected_agreement_version": draft["version"]}, OPS
    )
    validate_error(resp, ApiErrorId.ERR_TERRITORY_CONFLICT)


def test_second_assessment_of_same_month_rejected(api):
    """PRD §3.5: "a month may be assessed at most once per agreement, a second
    assessment being rejected with `ERR_DUPLICATE_PERIOD`."

    Design: Difficulty/resource_temporal_overlap/duplicate_period_month_rejected_as_occupancy
    """
    ctx = setup_active_agreement()
    ag_id = ctx["agreement"]["id"]
    submit_gci_report(ag_id, "2027-01", 100_000_000)
    assess_period(ag_id, "2027-01")

    resp = api.assess_royalty_period(ag_id, {"period_month": "2027-01"}, OPS)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PERIOD)


def test_duplicate_period_rejected_regardless_of_amount(api):
    """PRD §3.5: "a month may be assessed at most once per agreement, a second
    assessment being rejected with `ERR_DUPLICATE_PERIOD`."

    Design: Difficulty/resource_temporal_overlap/duplicate_period_month_rejected_as_occupancy
    """
    ctx = setup_active_agreement()
    ag_id = ctx["agreement"]["id"]
    submit_gci_report(ag_id, "2027-01", 1)
    first = assess_period(ag_id, "2027-01")
    assert first["royalty_due_cents"] == 0

    resp = api.assess_royalty_period(ag_id, {"period_month": "2027-01"}, OPS)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PERIOD)
