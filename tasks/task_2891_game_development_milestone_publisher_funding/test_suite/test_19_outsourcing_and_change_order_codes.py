"""The outsourcing lifecycle codes and the three change-order caps, each with its
own error_id and each enforced at the moment the PRD says it is.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import factories as f
from test_helpers.assertions import assert_budget_summary, assert_fields_equal, assert_ledger
from test_helpers.fixtures import (
    approve_invoice,
    create_engagement,
    setup_aurora_drift,
    setup_twinpeak,
    submit_invoice,
)


def test_corner_engagement_and_invoice_lifecycle_codes_are_all_reachable(api):
    """A mixed invoice portfolio reaches all six outsourcing codes, and the two
    engagement exits are blocked by two different codes.

    PRD §3.8 says invoice-number "Uniqueness is absolute rather than
    status-scoped: a number already used by an invoice of that engagement in
    *any* status, including a `VOIDED` one, is `ERR_INVOICE_NUMBER_TAKEN`";
    "Only a `SUBMITTED` invoice can be decided; one already `APPROVED`,
    `REJECTED` or `VOIDED` is `ERR_INVOICE_NOT_SUBMITTED`"; approval is "bounded
    by a tolerance ... the engagement's `approved_invoice_total_cents` plus this
    invoice's `amount_cents` must not exceed 12500 basis points of the
    engagement's `committed_cents` ... and a breach is
    `ERR_INVOICE_EXCEEDS_ENGAGEMENT`"; "a completion attempted from any other
    status is `ERR_ENGAGEMENT_STATE_INVALID`, and a completion attempted while
    any invoice of the engagement is still `SUBMITTED` is
    `ERR_ENGAGEMENT_HAS_OPEN_INVOICES`"; and cancellation "is only lawful while
    no money has been incurred: an `approved_invoice_total_cents` greater than
    zero is `ERR_ENGAGEMENT_HAS_APPROVED_INVOICES`".

    Design: Corner/errors/corner_engagement_and_invoice_lifecycle_codes_are_all_reachable
    """
    scenario = setup_twinpeak(api)
    reg = scenario.reg
    quill = create_engagement(
        reg, scenario.m1["id"], "ART-QUILL", 400000, "2026-08-05", "2026-09-30",
        "Character art pass",
    )
    lark = create_engagement(
        reg, scenario.m2["id"], "AUDIO-LARK", 300000, "2026-10-01", "2026-11-30",
        "Adaptive music",
    )
    assert quill["status"] == "ACTIVE", quill
    assert lark["status"] == "PROPOSED", lark
    first = submit_invoice(reg, quill["id"], "QUILL-001", 150000, "2026-08-31")
    approved = approve_invoice(reg, first["id"])
    assert approved["status"] == "APPROVED", approved
    decided_at = approved["decided_at"]

    validate_error(
        api.create_invoice(
            f.invoice_payload(quill["id"], "QUILL-001", 100000, "2026-09-15"), reg.dev
        ),
        "ERR_INVOICE_NUMBER_TAKEN",
        409,
    )

    validate_error(
        api.decide_invoice(
            first["id"], f.reject_invoice_payload("Changed our mind"), reg.finance
        ),
        "ERR_INVOICE_NOT_SUBMITTED",
        409,
    )
    unchanged = validate_success(api.get_invoice(first["id"], reg.dev))
    assert_fields_equal(
        unchanged, {"status": "APPROVED", "decided_at": decided_at}, "approved invoice"
    )

    validate_error(
        api.complete_engagement(lark["id"], reg.dev), "ERR_ENGAGEMENT_STATE_INVALID", 409
    )
    assert validate_success(api.get_engagement(lark["id"], reg.dev))["status"] == "PROPOSED"

    validate_error(
        api.cancel_engagement(quill["id"], reg.dev, {"reason": "Vendor swap"}),
        "ERR_ENGAGEMENT_HAS_APPROVED_INVOICES",
        409,
    )
    assert validate_success(api.get_engagement(quill["id"], reg.dev))["status"] == "ACTIVE"

    # Creation is never budget-checked; only the decision is.
    second = validate_success(
        api.create_invoice(
            f.invoice_payload(quill["id"], "QUILL-002", 400000, "2026-09-30"), reg.dev
        ),
        expected_status=201,
    )
    assert second["status"] == "SUBMITTED", second

    # 150000 + 400000 == 550000 exceeds 12500 bps of 400000, which is 500000.
    validate_error(
        api.decide_invoice(second["id"], f.approve_invoice_payload(), reg.finance),
        "ERR_INVOICE_EXCEEDS_ENGAGEMENT",
        422,
    )
    still = validate_success(api.get_engagement(quill["id"], reg.dev))
    assert still["approved_invoice_total_cents"] == 150000, still

    # The still-SUBMITTED QUILL-002 blocks completion, with its own code.
    validate_error(
        api.complete_engagement(quill["id"], reg.dev), "ERR_ENGAGEMENT_HAS_OPEN_INVOICES", 409
    )

    summary = validate_success(api.get_budget_summary(scenario.m1["id"], reg.dev))
    assert_budget_summary(summary, scenario.m1["id"], 800000, 400000, 150000, 400000, 0)
    invoices = get_success_data(api.list_engagement_invoices(quill["id"], reg.dev))
    assert len(invoices) == 2, invoices


def test_corner_change_order_fiscal_and_schedule_caps_each_report_their_own_code(api):
    """All three change-order caps are enforced at decision time, each with its own
    code, each leaving the offending order `PROPOSED`.

    PRD §3.7 branch A: "the agreement's existing `uplift_funded_cents` plus this
    order's `requested_amount_cents` must not exceed twenty-five percent of
    `advance_total_cents` ... Breaching the cap is `ERR_UPLIFT_CAP_EXCEEDED`, and
    nothing is written." Branch B: "`requested_amount_cents` must not exceed the
    target milestone's `funded_amount_cents` plus its current `uplift_cents`, and
    an over-large cut is `ERR_CUT_EXCEEDS_MILESTONE_FUNDING`." On the schedule:
    "an approval whose resulting `schedule_slip_days` would exceed 45 days of
    slip, or 45 days of acceleration, is refused with
    `ERR_SHIP_DATE_SLIP_EXCEEDED` and no field is written." And on identity: "any
    other change order with the same `target_milestone_id` still sitting in
    `PROPOSED` is moved to `SUPERSEDED` immediately. A superseded proposal can
    never be decided — attempting to decide one, or to decide an order already
    resolved, is `ERR_CHANGE_ORDER_NOT_PROPOSED`."

    Design: Corner/errors/corner_change_order_fiscal_and_schedule_caps_each_report_their_own_code
    """
    scenario = setup_aurora_drift(
        api, ship_date_original="2027-09-30", live_ops_quarterly_funding_cents=100000
    )
    reg = scenario.reg

    over_cap = validate_success(
        api.create_change_order(
            f.change_order_payload(
                scenario.agreement_id, scenario.m1["id"], "FUNDING_UPLIFT",
                scenario.version(), "One cent past the uplift ceiling",
                requested_amount_cents=3000001, ship_date_delta_days=0,
            ),
            reg.dev,
        ),
        expected_status=201,
    )
    assert over_cap["state"] == "PROPOSED", over_cap
    validate_error(
        api.decide_change_order(
            over_cap["id"], f.approve_payload("Trying the ceiling"), reg.finance
        ),
        "ERR_UPLIFT_CAP_EXCEEDED",
        422,
    )
    refused = validate_success(api.get_change_order(over_cap["id"], reg.dev))
    assert_fields_equal(refused, {"state": "PROPOSED", "decided_at": None}, "refused uplift")

    over_slip = validate_success(
        api.create_change_order(
            f.change_order_payload(
                scenario.agreement_id, scenario.m2["id"], "FUNDING_UPLIFT",
                scenario.version(), "Forty-six days of slip",
                requested_amount_cents=100000, ship_date_delta_days=46,
            ),
            reg.dev,
        ),
        expected_status=201,
    )
    assert over_slip["state"] == "PROPOSED", over_slip
    validate_error(
        api.decide_change_order(over_slip["id"], f.approve_payload(), reg.finance),
        "ERR_SHIP_DATE_SLIP_EXCEEDED",
        422,
    )
    agreement = scenario.read_agreement()
    assert agreement["ship_date_current"] == "2027-09-30", agreement
    assert agreement["schedule_slip_days"] == 0, agreement

    over_cut = validate_success(
        api.create_change_order(
            f.change_order_payload(
                scenario.agreement_id, scenario.m3["id"], "FEATURE_CUT",
                scenario.version(), "Cutting more than the milestone holds",
                requested_amount_cents=3000001, ship_date_delta_days=0,
                content_threshold_relief_pct=5.00,
            ),
            reg.dev,
        ),
        expected_status=201,
    )
    assert over_cut["state"] == "PROPOSED", over_cut
    validate_error(
        api.decide_change_order(over_cut["id"], f.approve_payload(), reg.finance),
        "ERR_CUT_EXCEEDS_MILESTONE_FUNDING",
        422,
    )
    gold = scenario.read_milestone(scenario.m3["id"])
    assert float(gold["content_threshold_relief_pct"]) == 0.0, gold
    assert gold["funded_amount_cents"] == 3000000, gold

    # A lawful uplift on the same target supersedes the stale proposal at creation.
    lawful = validate_success(
        api.create_change_order(
            f.change_order_payload(
                scenario.agreement_id, scenario.m1["id"], "FUNDING_UPLIFT",
                scenario.version(), "A legal uplift that supersedes the stale proposal",
                requested_amount_cents=500000, ship_date_delta_days=0,
            ),
            reg.dev,
        ),
        expected_status=201,
    )
    assert validate_success(api.get_change_order(over_cap["id"], reg.dev))["state"] == (
        "SUPERSEDED"
    )
    decided = validate_success(
        api.decide_change_order(lawful["id"], f.approve_payload(), reg.finance)
    )
    assert decided["state"] == "APPROVED_UPLIFT", decided
    assert scenario.read_milestone(scenario.m1["id"])["uplift_cents"] == 500000
    assert_ledger(
        scenario.read_agreement(),
        uplift_funded_cents=500000,
        funding_pool_cents=12500000,
        committed_cents=12500000,
        available_funding_cents=0,
    )

    validate_error(
        api.decide_change_order(over_cap["id"], f.approve_payload(), reg.finance),
        "ERR_CHANGE_ORDER_NOT_PROPOSED",
        409,
    )
    assert scenario.read_agreement()["uplift_funded_cents"] == 500000
