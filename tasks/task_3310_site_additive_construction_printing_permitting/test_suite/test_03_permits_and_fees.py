"""Permit fee calculation and alternative-means review tests (PRD §3.10)."""
from test_helpers import (
    ApiErrorId,
    JURIS_REVIEWER,
    PERMIT_COORD,
    assert_permit_application,
    create_approved_plan_revision,
    create_jurisdiction,
    create_permit_application_payload,
    create_site,
    get_success_data,
    set_clock,
    validate_error,
    validate_success,
)


def _open_application(api, site_id, revision_id, requested_path):
    return get_success_data(
        api.create_permit_application(
            site_id,
            create_permit_application_payload(revision_id, requested_path=requested_path),
            PERMIT_COORD,
        )
    )


def test_permit_fee_prescriptive_path_fee_and_routing(api):
    """PRD §3.10: "The base is 250000 cents; an area component adds the floor of
    the plan's `plan_area_m2` (the floor is taken before any multiplication)
    times 4500 cents per square meter; and an alternative-means surcharge of
    175000 cents applies when the application is routed to `ALTERNATIVE_MEANS`
    (the surcharge is zero on the prescriptive path). On a first submission the
    sum is the fee." Also: "if `requested_path` is `PRESCRIPTIVE` and the
    jurisdiction's `permits_prescriptive_printed_path` is true, the application
    lands in `SUBMITTED`."

    Design: Difficulty/dual_variant_calc/permit_fee_prescriptive_vs_alternative_means
    """
    set_clock("2026-09-01T00:00:00Z")
    jurisdiction = create_jurisdiction(permits_prescriptive=True, code="J1")
    _plan, revision = create_approved_plan_revision(plan_area_m2=100)
    site = create_site(jurisdiction["id"], address="1 A St")
    app = _open_application(api, site["id"], revision["id"], "PRESCRIPTIVE")
    data = validate_success(
        api.permit_application_action(site["id"], app["id"], {"action": "SUBMIT"}, PERMIT_COORD)
    )
    assert_permit_application(data)
    assert data["status"] == "SUBMITTED"
    # floor(100) * 4500 = 450000; 250000 + 450000 + 0 = 700000.
    assert data["fee_due_cents"] == 700000


def test_permit_fee_alternative_means_path_fee_and_routing(api):
    """PRD §3.10: "an alternative-means surcharge of 175000 cents applies when
    the application is routed to `ALTERNATIVE_MEANS`" and "A request with
    `requested_path` `ALTERNATIVE_MEANS` goes to `AM_REVIEW` directly."

    Design: Difficulty/dual_variant_calc/permit_fee_prescriptive_vs_alternative_means
    """
    set_clock("2026-09-01T00:00:00Z")
    jurisdiction = create_jurisdiction(permits_prescriptive=False, code="J2")
    _plan, revision = create_approved_plan_revision(plan_area_m2=100)
    site = create_site(jurisdiction["id"], address="2 B St")
    app = _open_application(api, site["id"], revision["id"], "ALTERNATIVE_MEANS")
    data = validate_success(
        api.permit_application_action(site["id"], app["id"], {"action": "SUBMIT"}, PERMIT_COORD)
    )
    assert data["status"] == "AM_REVIEW"
    # floor(100) * 4500 = 450000; 250000 + 450000 + 175000 = 875000.
    assert data["fee_due_cents"] == 875000
    assert data["am_submitted_at"] is not None
    assert data["am_decision_due_at"] is not None


def test_permit_fee_resubmit_multiplier_nested(api):
    """PRD §3.10: "On resubmission, the entire sum — including the surcharge —
    is multiplied by one plus 0.10 times `review_round`, and the result is
    rounded half-up to zero decimal places."

    After two resubmits (review_round = 2) on a 137 m2 AM-routed application:
    round_half_up((250000 + 137*4500 + 175000) * 1.20) = 1249800.

    Design: Difficulty/combinatorial_formula/permit_fee_resubmit_multiplier_nested
    """
    set_clock("2026-09-01T00:00:00Z")
    jurisdiction = create_jurisdiction(
        permits_prescriptive=False, am_review_days=1, code="JM"
    )
    _plan, revision = create_approved_plan_revision(
        plan_area_m2=137, required_code_path="ALTERNATIVE_MEANS"
    )
    site = create_site(jurisdiction["id"], address="3 C St")
    app = _open_application(api, site["id"], revision["id"], "ALTERNATIVE_MEANS")
    get_success_data(
        api.permit_application_action(site["id"], app["id"], {"action": "SUBMIT"}, PERMIT_COORD)
    )
    # Round 1: let the AM review expire, then resubmit.
    set_clock("2026-09-03T00:00:00Z")
    get_success_data(api.get_permit_application(site["id"], app["id"], PERMIT_COORD))
    get_success_data(
        api.permit_application_action(site["id"], app["id"], {"action": "RESUBMIT"}, PERMIT_COORD)
    )
    # Round 2: expire again, then resubmit.
    set_clock("2026-09-05T00:00:00Z")
    get_success_data(api.get_permit_application(site["id"], app["id"], PERMIT_COORD))
    data = validate_success(
        api.permit_application_action(site["id"], app["id"], {"action": "RESUBMIT"}, PERMIT_COORD)
    )
    assert data["review_round"] == 2
    assert data["status"] == "AM_REVIEW"
    assert data["fee_due_cents"] == 1249800


def test_permit_fee_first_resubmission_markup(api):
    """PRD §3.10: "On resubmission, the entire sum — including the surcharge —
    is multiplied by one plus 0.10 times `review_round`, and the result is
    rounded half-up to zero decimal places."

    On a 100 m2 AM-routed application, the first resubmit (review_round = 1)
    prices at round_half_up(875000 * 1.1) = 962500.

    Design: Difficulty/combinatorial_formula/permit_fee_resubmit_multiplier_nested
    """
    set_clock("2026-09-01T00:00:00Z")
    jurisdiction = create_jurisdiction(
        permits_prescriptive=False, am_review_days=1, code="JM1"
    )
    _plan, revision = create_approved_plan_revision(
        plan_area_m2=100, required_code_path="ALTERNATIVE_MEANS"
    )
    site = create_site(jurisdiction["id"], address="3 C1 St")
    app = _open_application(api, site["id"], revision["id"], "ALTERNATIVE_MEANS")
    get_success_data(
        api.permit_application_action(site["id"], app["id"], {"action": "SUBMIT"}, PERMIT_COORD)
    )
    set_clock("2026-09-03T00:00:00Z")
    get_success_data(api.get_permit_application(site["id"], app["id"], PERMIT_COORD))
    data = validate_success(
        api.permit_application_action(site["id"], app["id"], {"action": "RESUBMIT"}, PERMIT_COORD)
    )
    assert data["review_round"] == 1
    assert data["fee_due_cents"] == 962500


def test_permit_application_am_resubmit_cycle(api):
    """PRD §3.10: "If the logical clock passes `am_decision_due_at` without a
    decision, the application auto-transitions from `AM_REVIEW` to
    `RESUBMIT_REQUIRED` on the first read or write that touches it. A
    `PermitCoordinator` may then resubmit ... resubmission increments
    `review_round` by 1, recomputes `fee_due_cents` under the resubmission
    multiplier, and re-stamps `am_submitted_at` and `am_decision_due_at`."

    Design: Difficulty/non_linear_state_machine/permit_application_am_resubmit_cycle
    """
    set_clock("2026-09-01T00:00:00Z")
    jurisdiction = create_jurisdiction(
        permits_prescriptive=False, am_review_days=1, code="JC2"
    )
    _plan, revision = create_approved_plan_revision(
        plan_area_m2=80, required_code_path="ALTERNATIVE_MEANS"
    )
    site = create_site(jurisdiction["id"], address="9 E St")
    app = _open_application(api, site["id"], revision["id"], "ALTERNATIVE_MEANS")
    submitted = get_success_data(
        api.permit_application_action(site["id"], app["id"], {"action": "SUBMIT"}, PERMIT_COORD)
    )
    assert submitted["status"] == "AM_REVIEW"
    first_due = submitted["am_decision_due_at"]
    set_clock("2026-09-05T00:00:00Z")
    expired = get_success_data(api.get_permit_application(site["id"], app["id"], PERMIT_COORD))
    assert expired["status"] == "RESUBMIT_REQUIRED"
    resubmitted = validate_success(
        api.permit_application_action(site["id"], app["id"], {"action": "RESUBMIT"}, PERMIT_COORD)
    )
    assert resubmitted["status"] == "AM_REVIEW"
    assert resubmitted["review_round"] == 1
    assert resubmitted["am_submitted_at"] != submitted["am_submitted_at"]
    assert resubmitted["am_decision_due_at"] != first_due


def test_am_review_expiry_blocks_late_approval(api):
    """PRD §3.10: "approving from `AM_REVIEW` additionally requires the logical
    clock to be at or before `am_decision_due_at`, otherwise
    `ERR_AM_REVIEW_EXPIRED`."

    Design: Difficulty/non_linear_state_machine/permit_application_am_resubmit_cycle
    """
    set_clock("2026-09-01T00:00:00Z")
    jurisdiction = create_jurisdiction(
        permits_prescriptive=False, am_review_days=1, code="JC2B"
    )
    _plan, revision = create_approved_plan_revision(
        plan_area_m2=80, required_code_path="ALTERNATIVE_MEANS"
    )
    site = create_site(jurisdiction["id"], address="9 EB St")
    app = _open_application(api, site["id"], revision["id"], "ALTERNATIVE_MEANS")
    get_success_data(
        api.permit_application_action(site["id"], app["id"], {"action": "SUBMIT"}, PERMIT_COORD)
    )
    get_success_data(
        api.permit_application_action(
            site["id"], app["id"], {"action": "PAY_FEE", "amount_cents": 99999999}, PERMIT_COORD
        )
    )
    set_clock("2026-09-05T00:00:00Z")
    resp = api.permit_application_action(
        site["id"], app["id"], {"action": "DECIDE", "decision": "APPROVE"}, JURIS_REVIEWER
    )
    validate_error(resp, ApiErrorId.ERR_AM_REVIEW_EXPIRED)


def test_fee_payment_plus_refund_conserves_outstanding(api):
    """PRD §3.10: "Fee payment is recorded by the `PermitCoordinator` posting an
    `amount_cents`, which increments `fee_paid_cents`; fees already paid are
    non-refundable on withdrawal." And: "On resubmission, the entire sum —
    including the surcharge — is multiplied by one plus 0.10 times
    `review_round`".

    Paying the full 875000 fee leaves outstanding zero; the resubmit re-prices
    to 962500 while the payment is preserved, so outstanding reopens to 87500.

    Design: Difficulty/compensating_invariant/fee_payment_plus_refund_conserves_outstanding
    """
    set_clock("2026-09-01T00:00:00Z")
    jurisdiction = create_jurisdiction(
        permits_prescriptive=False, am_review_days=1, code="JZ"
    )
    _plan, revision = create_approved_plan_revision(
        plan_area_m2=100, required_code_path="ALTERNATIVE_MEANS"
    )
    site = create_site(jurisdiction["id"], address="801 T St")
    app = _open_application(api, site["id"], revision["id"], "ALTERNATIVE_MEANS")
    submitted = get_success_data(
        api.permit_application_action(site["id"], app["id"], {"action": "SUBMIT"}, PERMIT_COORD)
    )
    assert submitted["fee_due_cents"] == 875000
    paid = get_success_data(
        api.permit_application_action(
            site["id"], app["id"], {"action": "PAY_FEE", "amount_cents": 875000}, PERMIT_COORD
        )
    )
    assert paid["fee_paid_cents"] == 875000
    set_clock("2026-09-05T00:00:00Z")
    get_success_data(api.get_permit_application(site["id"], app["id"], PERMIT_COORD))
    resubmitted = validate_success(
        api.permit_application_action(site["id"], app["id"], {"action": "RESUBMIT"}, PERMIT_COORD)
    )
    assert resubmitted["review_round"] == 1
    assert resubmitted["fee_paid_cents"] == 875000, "payment preserved across resubmit"
    assert resubmitted["fee_due_cents"] == 962500
    outstanding = resubmitted["fee_due_cents"] - resubmitted["fee_paid_cents"]
    assert outstanding == 87500


def test_fee_partial_payments_accumulate_toward_due(api):
    """PRD §3.10: "Fee payment is recorded by the `PermitCoordinator` posting an
    `amount_cents`, which increments `fee_paid_cents`".

    Design: Difficulty/compensating_invariant/fee_payment_plus_refund_conserves_outstanding
    """
    set_clock("2026-09-01T00:00:00Z")
    jurisdiction = create_jurisdiction(permits_prescriptive=True, code="JZ2")
    _plan, revision = create_approved_plan_revision(plan_area_m2=100)
    site = create_site(jurisdiction["id"], address="801 T2 St")
    app = _open_application(api, site["id"], revision["id"], "PRESCRIPTIVE")
    submitted = get_success_data(
        api.permit_application_action(site["id"], app["id"], {"action": "SUBMIT"}, PERMIT_COORD)
    )
    assert submitted["fee_due_cents"] == 700000
    get_success_data(
        api.permit_application_action(
            site["id"], app["id"], {"action": "PAY_FEE", "amount_cents": 300000}, PERMIT_COORD
        )
    )
    paid = get_success_data(
        api.permit_application_action(
            site["id"], app["id"], {"action": "PAY_FEE", "amount_cents": 400000}, PERMIT_COORD
        )
    )
    assert paid["fee_paid_cents"] == 700000
    assert paid["fee_due_cents"] == 700000, "due is unchanged by payments"


def test_permit_decide_blocked_when_fee_unpaid(api):
    """PRD §3.10: "Approving requires `fee_paid_cents` to be at least
    `fee_due_cents`, otherwise the decision is rejected with
    `ERR_PERMIT_FEE_OUTSTANDING`."

    Design: Corner/endpoints/permit_decide_blocked_when_fee_unpaid
    """
    set_clock("2026-09-01T00:00:00Z")
    jurisdiction = create_jurisdiction(permits_prescriptive=True, code="JT2")
    _plan, revision = create_approved_plan_revision(plan_area_m2=80)
    site = create_site(jurisdiction["id"], address="19 L")
    app = _open_application(api, site["id"], revision["id"], "PRESCRIPTIVE")
    get_success_data(
        api.permit_application_action(site["id"], app["id"], {"action": "SUBMIT"}, PERMIT_COORD)
    )
    resp = api.permit_application_action(
        site["id"], app["id"], {"action": "DECIDE", "decision": "APPROVE"}, JURIS_REVIEWER
    )
    validate_error(resp, ApiErrorId.ERR_PERMIT_FEE_OUTSTANDING)
    current = get_success_data(api.get_permit_application(site["id"], app["id"], PERMIT_COORD))
    assert current["status"] == "SUBMITTED", "rejected decide must leave the application SUBMITTED"


def test_permit_decide_blocked_when_fee_partially_paid(api):
    """PRD §3.10: "Approving requires `fee_paid_cents` to be at least
    `fee_due_cents`, otherwise the decision is rejected with
    `ERR_PERMIT_FEE_OUTSTANDING`."

    Design: Corner/endpoints/permit_decide_blocked_when_fee_unpaid
    """
    set_clock("2026-09-01T00:00:00Z")
    jurisdiction = create_jurisdiction(permits_prescriptive=True, code="JT2B")
    _plan, revision = create_approved_plan_revision(plan_area_m2=80)
    site = create_site(jurisdiction["id"], address="19 LB")
    app = _open_application(api, site["id"], revision["id"], "PRESCRIPTIVE")
    submitted = get_success_data(
        api.permit_application_action(site["id"], app["id"], {"action": "SUBMIT"}, PERMIT_COORD)
    )
    get_success_data(
        api.permit_application_action(
            site["id"],
            app["id"],
            {"action": "PAY_FEE", "amount_cents": submitted["fee_due_cents"] - 1},
            PERMIT_COORD,
        )
    )
    resp = api.permit_application_action(
        site["id"], app["id"], {"action": "DECIDE", "decision": "APPROVE"}, JURIS_REVIEWER
    )
    validate_error(resp, ApiErrorId.ERR_PERMIT_FEE_OUTSTANDING)


def test_permit_application_terminal_approved_lockdown(api):
    """PRD §3.10: "Withdrawal is available from `DRAFT`, `SUBMITTED`, or
    `AM_REVIEW` and is final." PRD §2.11 item 8: "the source state is in the transition's
    from-set (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/permit_application_terminal_approved_lockdown
    """
    from test_helpers import create_approved_permit

    set_clock("2026-09-01T00:00:00Z")
    jurisdiction = create_jurisdiction(permits_prescriptive=True, code="JK")
    _plan, revision = create_approved_plan_revision(plan_area_m2=80)
    site = create_site(jurisdiction["id"], address="13 I")
    app = create_approved_permit(site["id"], revision["id"])
    assert app["status"] == "APPROVED"
    resp = api.permit_application_action(
        site["id"], app["id"], {"action": "WITHDRAW"}, PERMIT_COORD
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_permit_application_denied_is_terminal(api):
    """PRD §3.10: "Withdrawal is available from `DRAFT`, `SUBMITTED`, or
    `AM_REVIEW` and is final." and "Denial moves the application to `DENIED`
    from either status." A later withdraw from `DENIED` is not in any from-set
    (PRD §2.11 item 8: `ERR_INVALID_STATE`).

    Design: Corner/state_machines/permit_application_terminal_approved_lockdown
    """
    set_clock("2026-09-01T00:00:00Z")
    jurisdiction = create_jurisdiction(permits_prescriptive=True, code="JK2C")
    _plan, revision = create_approved_plan_revision(plan_area_m2=80)
    site = create_site(jurisdiction["id"], address="13 IC")
    app = _open_application(api, site["id"], revision["id"], "PRESCRIPTIVE")
    get_success_data(
        api.permit_application_action(site["id"], app["id"], {"action": "SUBMIT"}, PERMIT_COORD)
    )
    denied = get_success_data(
        api.permit_application_action(
            site["id"], app["id"], {"action": "DECIDE", "decision": "DENY"}, JURIS_REVIEWER
        )
    )
    assert denied["status"] == "DENIED"
    resp = api.permit_application_action(
        site["id"], app["id"], {"action": "WITHDRAW"}, PERMIT_COORD
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
