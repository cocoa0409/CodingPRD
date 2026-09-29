"""Requests that break two rules at once, where only the earlier rung answers.

The validation ladder is a total order, so each pair below is tested twice: once
with both rungs violated, and once with only the later rung violated, which
proves the later rung is genuinely implemented and that the first result is
precedence rather than the absence of a check.
"""
from test_helpers import ApiErrorId, validate_error, validate_paginated
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    BILLING_1,
    COUNSELOR_1,
    make_billing_clerk_headers,
    make_enrollment_counselor_headers,
)


R2_MEDICARE = {"other_group_coverage_employer_size": 25, "active_employment_flag": True}


def _january_invoice_at_2027_01_05(api):
    """R1 active on PRE65-CORE with an ISSUED January invoice of 15422 cents and
    the clock at 2027-01-05, before due_date, so the invoice is not PAST_DUE.

    Returns the invoice row.
    """
    program = fx.standard_program(api)
    plan_year_id = program["plan_year"]["id"]
    certified = fx.make_certified_retiree(api, plan_year_id, f.retiree_r1_payload())
    enrollment = fx.make_enrollment(
        api,
        certified["retiree"]["id"],
        plan_year_id,
        program["pre65_core"]["id"],
    )["enrollment"]

    fx.set_clock(api, "2027-01-01T00:00:00Z")
    fx.run_daily(api)
    invoice = fx.make_invoice(
        api, enrollment["id"], "2027-01-01T00:00:00Z", "2027-01-31T00:00:00Z"
    )
    assert invoice["net_due_cents"] == 15422
    assert invoice["status"] == "ISSUED"
    assert invoice["paid_cents"] == 0

    fx.set_clock(api, "2027-01-05T00:00:00Z")
    return invoice


def test_settled_invoice_state_error_beats_the_payment_balance_error(api):
    """A 500-cent payment on a PAID invoice answers 409, not 422.

    The invoice is already settled and the tender also exceeds its zero remaining
    balance, so PRD 2.8 rungs 24 and 47 are both violated. PRD 2.8: "The invoice's
    `status` is `ISSUED`, `PARTIALLY_PAID` or `PAST_DUE`; a `PAID` or
    `WRITTEN_OFF` invoice accepts no further payment → `ERR_INVOICE_ALREADY_SETTLED`
    (409)." sits above "`amount_cents` does not exceed the invoice's remaining
    balance → `ERR_PAYMENT_EXCEEDS_BALANCE` (422), on payment posting.", and PRD
    2.8 makes the ordering binding: "When a single request violates more than one
    rule, the rule that appears earliest in the following ladder produces the
    response, and no later rule is evaluated or reported."

    Design: Difficulty/priority_pair_validation_conflict/settled_invoice_state_beats_payment_exceeds_balance_fiscal
    """
    invoice = _january_invoice_at_2027_01_05(api)
    paid = fx.pay_invoice(api, invoice["id"], 15422)
    assert paid["status"] == "PAID"
    assert paid["paid_cents"] == 15422

    response = api.pay_invoice(
        invoice["id"], f.payment_payload(500), make_billing_clerk_headers(BILLING_1)
    )

    error = validate_error(
        response, ApiErrorId.ERR_INVOICE_ALREADY_SETTLED.value, expected_status=409
    )
    assert error["error_id"] != ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE.value

    unchanged = fx.reload_invoice(api, invoice["id"])
    assert unchanged["status"] == "PAID"
    assert unchanged["paid_cents"] == 15422
    assert unchanged["version"] == paid["version"]


def test_payment_balance_error_still_surfaces_on_a_payable_invoice(api):
    """With the state rung satisfied, the money rung answers 422.

    PRD 2.8: "`amount_cents` does not exceed the invoice's remaining balance →
    `ERR_PAYMENT_EXCEEDS_BALANCE` (422), on payment posting." The invoice is
    ISSUED, so rung 24 passes and the tender of one cent above net_due_cents
    reaches the fiscal rung — the very rung the settled-invoice case must
    suppress. PRD 2.8: "Money is deliberately checked last: a request that is
    unauthorized, malformed or aimed at the wrong state never reaches a balance
    test."

    Design: Difficulty/priority_pair_validation_conflict/settled_invoice_state_beats_payment_exceeds_balance_fiscal
    """
    invoice = _january_invoice_at_2027_01_05(api)

    response = api.pay_invoice(
        invoice["id"], f.payment_payload(15423), make_billing_clerk_headers(BILLING_1)
    )

    validate_error(
        response, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE.value, expected_status=422
    )

    unchanged = fx.reload_invoice(api, invoice["id"])
    assert unchanged["status"] == "ISSUED"
    assert unchanged["paid_cents"] == 0
    assert unchanged["version"] == invoice["version"]


def _certified_medicare_retiree_on_a_pre_medicare_year(api):
    """An OPEN plan year with an ACTIVE PRE_MEDICARE_GROUP option and a certified,
    eligible MEDICARE_ENROLLED retiree.

    Returns {"plan_year_id", "pre65_core_id", "retiree_id"}. The clock is left at
    2026-10-20, inside the annual election window.
    """
    program = fx.standard_program(api)
    plan_year_id = program["plan_year"]["id"]
    certified = fx.make_certified_retiree(
        api, plan_year_id, f.retiree_r2_payload(R2_MEDICARE)
    )
    assert certified["retiree"]["medicare_status"] == "MEDICARE_ENROLLED"
    assert certified["determination"]["status"] == "CERTIFIED"
    assert certified["determination"]["outcome"] == "ELIGIBLE"
    return {
        "plan_year_id": plan_year_id,
        "pre65_core_id": program["pre65_core"]["id"],
        "retiree_id": certified["retiree"]["id"],
    }


def test_election_window_temporal_error_beats_the_plan_class_error(api):
    """Five days past the window, the temporal rung answers before the class rung.

    PRD 2.8: "For an `ANNUAL_OPEN` election the logical clock lies inside the
    annual window → `ERR_ELECTION_WINDOW_CLOSED` (422), on election-event
    creation." precedes "The requested option's `coverage_class` matches the
    retiree's `medicare_status` → `ERR_PLAN_CLASS_MISMATCH` (422), on
    election-event creation." Both are violated here, and every earlier rung is
    deliberately satisfied: the plan year is still OPEN, the option is ACTIVE and
    the determination is CERTIFIED and ELIGIBLE, so only the clock moved past
    open_enrollment_end. Nothing is written, so no election row exists.

    Design: Difficulty/priority_pair_validation_conflict/election_window_temporal_beats_plan_class_referential
    """
    state = _certified_medicare_retiree_on_a_pre_medicare_year(api)
    fx.set_clock(api, "2026-11-20T00:00:00Z")

    response = api.create_election_event(
        f.election_event_payload(
            state["retiree_id"],
            state["plan_year_id"],
            state["pre65_core_id"],
            "ANNUAL_OPEN",
            "2026-11-20",
        ),
        make_enrollment_counselor_headers(COUNSELOR_1),
    )

    error = validate_error(
        response, ApiErrorId.ERR_ELECTION_WINDOW_CLOSED.value, expected_status=422
    )
    assert error["error_id"] != ApiErrorId.ERR_PLAN_CLASS_MISMATCH.value
    assert error["error_id"] != ApiErrorId.ERR_PLAN_YEAR_NOT_OPEN.value

    assert fx.reload_plan_year(api, state["plan_year_id"])["status"] == "OPEN"

    rows, _meta = validate_paginated(
        api.list_election_events(
            make_enrollment_counselor_headers(COUNSELOR_1),
            {"retiree_id": state["retiree_id"]},
        )
    )
    assert rows == []


def test_plan_class_error_still_surfaces_inside_the_election_window(api):
    """Inside the window, the same mismatched request answers the class rung.

    PRD 2.8: "The requested option's `coverage_class` matches the retiree's
    `medicare_status` → `ERR_PLAN_CLASS_MISMATCH` (422), on election-event
    creation." The clock stays at 2026-10-20, which lies inside the annual
    window, so the temporal rung passes and the referential rung the earlier case
    suppressed becomes the reported failure for a MEDICARE_ENROLLED retiree
    asking for PRE_MEDICARE_GROUP coverage.

    Design: Difficulty/priority_pair_validation_conflict/election_window_temporal_beats_plan_class_referential
    """
    state = _certified_medicare_retiree_on_a_pre_medicare_year(api)

    response = api.create_election_event(
        f.election_event_payload(
            state["retiree_id"],
            state["plan_year_id"],
            state["pre65_core_id"],
            "ANNUAL_OPEN",
            "2026-10-20",
        ),
        make_enrollment_counselor_headers(COUNSELOR_1),
    )

    validate_error(
        response, ApiErrorId.ERR_PLAN_CLASS_MISMATCH.value, expected_status=422
    )

    rows, _meta = validate_paginated(
        api.list_election_events(
            make_enrollment_counselor_headers(COUNSELOR_1),
            {"retiree_id": state["retiree_id"]},
        )
    )
    assert rows == []
