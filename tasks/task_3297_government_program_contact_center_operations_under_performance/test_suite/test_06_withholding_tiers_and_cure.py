"""Withholding tiers, per-line caps, cure-period remedy cascades, and the
gross-minus-withheld fiscal invariant."""
from test_helpers import (
    TEST_USERS,
    api_client,
    create_invoice_payload,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    OPS,
    SUP,
    activate_contract,
    activate_service_level,
    answer_call,
    certify_agent,
    create_agent,
    create_contract,
    create_draft_service_level,
    create_invoice,
    create_queue,
    get_call,
    get_contract,
    get_invoice,
    get_invoice_line,
    list_cure_periods,
    list_invoice_lines,
    pay_remedy,
    prepare_invoice,
    register_call,
    route_call,
    set_clock,
    setup_breach_invoice,
    setup_routable,
)

BILL_H = TEST_USERS["billing_analyst_headers"]


def _answered_contract(answer_seconds, cap_absolutes=False, cap_pct_of_gross=1.0,
                       target=30, agency="State Benefits Agency",
                       program_code="MEDICAID"):
    """ACTIVE contract, one certified agent, one queue, one call answered in
    `answer_seconds`, invoice prepared. Returns (contract, invoice, line)."""
    ctx = setup_routable(
        metric="ASA", target=target, cap_absolutes=cap_absolutes,
        cap_pct_of_gross=cap_pct_of_gross, agency_name=agency,
        program_code=program_code,
    )
    contract_id = ctx["contract"]["id"]
    call = register_call(contract_id, enqueued_at="2026-09-05T09:00:00Z",
                         program_code=program_code)
    set_clock("2026-09-05T09:00:00Z")
    call = route_call(call["id"])
    hh, mm, ss = 9, 0, answer_seconds
    mm += ss // 60
    ss = ss % 60
    answer_at = f"2026-09-05T{hh:02d}:{mm:02d}:{ss:02d}Z"
    answer_call(call, ctx["agent"]["id"], answer_at=answer_at)
    invoice = create_invoice(contract_id)
    invoice = prepare_invoice(invoice["id"])
    line = list_invoice_lines(invoice["id"])[0]
    return ctx, invoice, line


def test_remedy_payment_releases_withholding_resyncs_invoice_and_contract():
    """PRD §3.11: "A `BillingAnalyst` may pay the remedy on a `PENDING` cure
    period, which moves it to `REMEDIED` and cures the breach: the line's
    `withheld_cents` is set to 0, the invoice's `withheld_cents` and
    `net_cents` are recomputed, the contract's `withheld_cents_cum` is
    decremented by the released amount, and the contract's
    `cure_periods_used` is incremented by 1."

    Design: Difficulty/transitive_cascade/remedy_payment_releases_withholding_resyncs_invoice_and_contract
    """
    ctx, invoice, line = _answered_contract(40)
    # ASA target 30, answered in 40s: ratio 1/3 >= 0.15 -> tier 0.40.
    assert line["withheld_cents"] == 21600
    contract = get_contract(ctx["contract"]["id"])
    assert contract["withheld_cents_cum"] == 21600

    cure = list_cure_periods(line["id"])[0]
    remedied = pay_remedy(cure["id"])
    assert remedied["status"] == "REMEDIED"
    assert remedied["remedy_fee_cents"] == 1000

    line_after = get_invoice_line(line["id"])
    assert line_after["withheld_cents"] == 0

    invoice_after = get_invoice(invoice["id"])
    assert invoice_after["withheld_cents"] == 0
    assert invoice_after["net_cents"] == invoice_after["gross_cents"] == 54000

    contract_after = get_contract(ctx["contract"]["id"])
    assert contract_after["withheld_cents_cum"] == 0
    assert contract_after["cure_periods_used"] == 1


def test_remedy_payment_copies_service_level_remedy_fee():
    """PRD §3.11: "a `deadline` exactly 72 hours after `opened_at`, and
    `remedy_fee_cents` copied from the line's service level at creation."
    PRD §3.11: "A `BillingAnalyst` may pay the remedy on a `PENDING` cure
    period, which moves it to `REMEDIED` and cures the breach".

    Design: Difficulty/transitive_cascade/remedy_payment_releases_withholding_resyncs_invoice_and_contract
    """
    ctx, invoice, line = _answered_contract(40)
    cure = list_cure_periods(line["id"])[0]
    assert cure["status"] == "PENDING"
    assert cure["remedy_fee_cents"] == 1000
    remedied = pay_remedy(cure["id"])
    assert remedied["status"] == "REMEDIED"
    assert get_contract(ctx["contract"]["id"])["cure_periods_used"] == 1


def test_recompute_conserves_gross_minus_withheld_equals_net():
    """PRD §3.10: "The invoice's `withheld_cents` is the sum of its lines'
    withholdings, and `net_cents` is `gross_cents` minus `withheld_cents`.
    Preparation also resyncs the contract's `withheld_cents_cum` to reflect
    the new lines."
    PRD §3.11: "When an invoice is recomputed, existing `PENDING` cure periods
    whose line is now compliant are removed, and newly detected breaches open
    new `PENDING` cure periods; the contract's `withheld_cents_cum` is
    resynced to match."

    Design: Difficulty/compensating_invariant/recompute_conserves_gross_minus_withheld_equals_net
    """
    ctx, invoice, line = _answered_contract(40)
    assert (
        invoice["gross_cents"] - invoice["withheld_cents"] == invoice["net_cents"]
    )
    cure = list_cure_periods(line["id"])[0]
    pay_remedy(cure["id"])

    recomputed = validate_success(api_client.recompute_invoice(invoice["id"], BILL_H))
    assert recomputed["gross_cents"] - recomputed["withheld_cents"] == recomputed["net_cents"]
    assert recomputed["gross_cents"] == 54000
    assert recomputed["withheld_cents"] == 0
    assert recomputed["net_cents"] == 54000

    line_after = list_invoice_lines(invoice["id"])[0]
    assert line_after["withheld_cents"] == 0
    contract_after = get_contract(ctx["contract"]["id"])
    assert contract_after["withheld_cents_cum"] == 0


def test_recompute_resyncs_contract_withheld_cum_after_cure():
    """PRD §3.11: "A `BillingAnalyst` may pay the remedy on a `PENDING` cure
    period, which moves it to `REMEDIED` and cures the breach: the line's
    `withheld_cents` is set to 0, the invoice's `withheld_cents` and
    `net_cents` are recomputed, the contract's `withheld_cents_cum` is
    decremented by the released amount, and the contract's
    `cure_periods_used` is incremented by 1."
    PRD §3.11: "When an invoice is recomputed, existing `PENDING` cure periods
    whose line is now compliant are removed, and newly detected breaches open
    new `PENDING` cure periods; the contract's `withheld_cents_cum` is
    resynced to match."

    Design: Difficulty/compensating_invariant/recompute_conserves_gross_minus_withheld_equals_net
    """
    ctx, invoice, line = _answered_contract(40)
    assert get_contract(ctx["contract"]["id"])["withheld_cents_cum"] == 21600
    cure = list_cure_periods(line["id"])[0]
    pay_remedy(cure["id"])
    validate_success(api_client.recompute_invoice(invoice["id"], BILL_H))
    contract = get_contract(ctx["contract"]["id"])
    assert contract["withheld_cents_cum"] == 0
    assert contract["cure_periods_used"] == 1
    assert get_invoice(invoice["id"])["net_cents"] == 54000


def test_withholding_tier_boundaries():
    """PRD §3.10: "The miss ratio is the miss divided by the target, and the
    tier boundaries are asymmetric by design: a ratio strictly below 0.05
    withholds 10 percent of gross; a ratio at least 0.05 and strictly below
    0.15 withholds 25 percent; a ratio of 0.15 or greater withholds 40
    percent. The raw withholding is the invoice's `gross_cents` multiplied by
    the tier rate, rounded half-up to cents."

    Design: Corner/calculations/withholding_tier_boundaries
    """
    # Target 100; gross is 54000 for every contract (one certified agent).
    # Distinct program codes per contract keep program-scoped staffing and
    # gross counts (PRD §3.9) isolated between the three contracts.
    _, inv_a, line_a = _answered_contract(
        104, target=100, agency="Tier Agency A", program_code="MEDICAID"
    )
    assert line_a["measured_value"] == 104
    assert line_a["withheld_cents"] == 5400, "ratio 0.04 < 0.05 -> tier 0.10"

    _, inv_b, line_b = _answered_contract(
        105, target=100, agency="Tier Agency B", program_code="SNAP"
    )
    assert line_b["measured_value"] == 105
    assert line_b["withheld_cents"] == 13500, "ratio 0.05 exactly -> tier 0.25"

    _, inv_c, line_c = _answered_contract(
        115, target=100, agency="Tier Agency C", program_code="TANF"
    )
    assert line_c["measured_value"] == 115
    assert line_c["withheld_cents"] == 21600, "ratio 0.15 exactly -> tier 0.40"


def test_per_line_absolute_cap_applies_in_cap_absolutes_mode():
    """PRD §3.10: "The per-line absolute cap always applies, in both cap
    modes: the line's withholding may not exceed the service level's
    `cap_pct_of_gross` times the invoice `gross_cents`, rounded half-up to
    cents. The cumulative cap applies only when the contract's `cap_absolutes`
    is false ... under the absolutes regime, the cumulative check is skipped
    entirely and a month-1 line may withhold more than month-1 gross."

    Design: Corner/calculations/per_line_absolute_cap_applies_in_cap_absolutes_mode
    """
    ctx, invoice, line = _answered_contract(
        40, cap_absolutes=True, cap_pct_of_gross=0.30
    )
    # raw tier-3 = 0.40 * 54000 = 21600, clipped to round_half_up(0.30 * 54000)
    assert line["withheld_cents"] == 16200
    invoice_after = get_invoice(invoice["id"])
    assert invoice_after["net_cents"] == 54000 - 16200 == 37800
    assert get_contract(ctx["contract"]["id"])["withheld_cents_cum"] == 16200


def test_cure_window_closed_on_remedied_and_no_eligible_queue_uncertified():
    """PRD §3.11: "Payment is only possible inside the cure window — after
    the deadline, or on a cure period no longer `PENDING`, the attempt is
    rejected with `ERR_CURE_WINDOW_CLOSED` (HTTP 409)."
    PRD §3.3: "the agent holds a standing certification for P (per §3.2)" and
    "If no eligible queue exists even after the fallback, the route attempt
    fails with `ERR_NO_ELIGIBLE_QUEUE` (HTTP 409)."

    Design: Corner/errors/cure_window_closed_on_remedied_and_no_eligible_queue_uncertified
    """
    ctx, invoice, line = _answered_contract(40)
    cure = list_cure_periods(line["id"])[0]
    pay_remedy(cure["id"])
    second = api_client.pay_cure_remedy(cure["id"], BILL_H)
    validate_error(second, ApiErrorId.ERR_CURE_WINDOW_CLOSED)

    # Setup B: ACTIVE contract with a queue but no certifications at all.
    contract = create_contract(agency_name="Empty Pool Agency")
    sl = create_draft_service_level(contract["id"], metric="ASA", target=30)
    activate_service_level(contract, sl["id"])
    create_queue(contract["id"])
    call = register_call(contract["id"], enqueued_at="2026-09-05T10:00:00Z")
    resp = api_client.transition_call(call["id"], {"to_status": "ASSIGNED"}, SUP)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_QUEUE)
    assert get_call(call["id"])["status"] == "WAITING"
