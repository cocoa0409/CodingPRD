"""Invoice measurement: provisional vs official variants, ASA boundary
precision, the empty-set QA_AVG null rule, gross/staffing math, and the
segregation-of-duties approval gate."""
from test_helpers import (
    TEST_USERS,
    api_client,
    create_invoice_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import (
    create_contract_payload,
    create_queue_payload,
    create_service_level_payload,
)
from test_helpers.fixtures import (
    BILL,
    OPS,
    SUP,
    activate_contract,
    activate_service_level,
    answer_call,
    certify_agent,
    complete_call,
    create_agent,
    create_contract,
    create_course,
    create_draft_service_level,
    create_invoice,
    create_queue,
    create_review,
    create_surge_window,
    get_contract,
    get_invoice,
    get_surge_window,
    list_cure_periods,
    list_invoice_lines,
    make_agent_headers,
    pay_remedy,
    prepare_invoice,
    register_call,
    route_call,
    set_clock,
    setup_active_contract,
    setup_completed_call,
    setup_routable,
    staff_to_target,
    transition_review,
)
from test_helpers.test_users import make_billing_headers, make_ops_headers

QA_H = TEST_USERS["quality_analyst_headers"]
OPS_H = TEST_USERS["ops_manager_headers"]
SUP_H = TEST_USERS["supervisor_headers"]
BILL_H = TEST_USERS["billing_analyst_headers"]


def test_asa_provisional_vs_official_after_late_answer():
    """PRD §3.9: "Measurement comes in two variants. The first preparation of
    an invoice takes the **provisional** variant: the input set is taken at
    the preparation instant and stored on the line — for quality, only reviews
    already final at that instant count. Every recompute while the invoice is
    not yet `PAID` takes the **official** variant: the input set is re-taken
    at the recompute instant, so late-arriving completions shift the
    answer-speed mean, reviews that became final since preparation — a dispute
    resolved `UPHELD`, a late acceptance — enter the quality set, and the new
    value overwrites the line's `measured_value`."
    PRD §3.9: "For `ASA`, the input set is the calls of the line's contract
    and program whose status is `ANSWERED` or `COMPLETED` and whose
    `enqueued_at` falls inside the window".

    Design: Difficulty/dual_variant_calc/asa_provisional_vs_official_after_late_answer
    """
    ctx = setup_routable()
    contract_id = ctx["contract"]["id"]
    agent_id = ctx["agent"]["id"]
    agent_b = create_agent(full_name="Agent Two")
    certify_agent(agent_b["id"], ctx["course"]["id"])
    # Staff the program to its baseline target so the staffing-shortfall
    # override of PRD §3.9 does not force the line non-compliant.
    staff_to_target(ctx["course"]["id"], already=2)

    call_a = register_call(contract_id, enqueued_at="2026-09-10T09:00:00Z")
    set_clock("2026-09-10T09:00:00Z")
    call_a = route_call(call_a["id"])
    call_a = answer_call(call_a, agent_id, answer_at="2026-09-10T09:00:20Z")
    assert call_a["answer_seconds"] == 20

    call_b = register_call(contract_id, enqueued_at="2026-09-10T10:00:00Z")

    invoice = create_invoice(contract_id)
    invoice = prepare_invoice(invoice["id"])
    line = list_invoice_lines(invoice["id"])[0]
    assert line["measured_value"] == 20, "provisional: only call A's 20s counts"

    call_b = route_call(call_b["id"])
    call_b = answer_call(call_b, agent_b["id"], answer_at="2026-09-10T10:00:40Z")
    assert call_b["answer_seconds"] == 40

    version_before = get_invoice(invoice["id"])["version"]
    recomputed = validate_success(api_client.recompute_invoice(invoice["id"], BILL_H))
    assert recomputed["version"] > version_before
    line = list_invoice_lines(invoice["id"])[0]
    assert line["measured_value"] == 30, "official: (20 + 40) / 2"
    assert line["compliant"] is True, "30 <= target 30 is compliant"
    assert line["withheld_cents"] == 0


def test_asa_official_variant_overwrites_provisional_value():
    """PRD §3.9: "Every recompute while the invoice is not yet `PAID` takes
    the **official** variant: the input set is re-taken at the recompute
    instant, so late-arriving completions shift the answer-speed mean ...
    and the new value overwrites the line's `measured_value`."

    Design: Difficulty/dual_variant_calc/asa_provisional_vs_official_after_late_answer
    """
    ctx = setup_routable()
    contract_id = ctx["contract"]["id"]
    agent_id = ctx["agent"]["id"]

    call_a = register_call(contract_id, enqueued_at="2026-09-10T09:00:00Z")
    set_clock("2026-09-10T09:00:00Z")
    call_a = route_call(call_a["id"])
    answer_call(call_a, agent_id, answer_at="2026-09-10T09:00:20Z")

    invoice = create_invoice(contract_id)
    prepare_invoice(invoice["id"])
    provisional = list_invoice_lines(invoice["id"])[0]["measured_value"]
    assert provisional == 20

    # Recompute with no new calls: the official variant re-derives the same
    # value from the same set (idempotent measurement).
    validate_success(api_client.recompute_invoice(invoice["id"], BILL_H))
    official = list_invoice_lines(invoice["id"])[0]["measured_value"]
    assert official == 20


def test_qa_avg_provisional_vs_official_after_dispute_upheld():
    """PRD §3.9: "The first preparation of an invoice takes the
    **provisional** variant: the input set is taken at the preparation instant
    and stored on the line — for quality, only reviews already final at that
    instant count. Every recompute while the invoice is not yet `PAID` takes
    the **official** variant: ... reviews that became final since preparation
    — a dispute resolved `UPHELD`, a late acceptance — enter the quality set,
    and the new value overwrites the line's `measured_value`."
    PRD §3.5: "`to_status` of `UPHELD` confirms the score, sets `final` to
    true".

    Design: Difficulty/dual_variant_calc/qa_avg_provisional_vs_official_after_dispute_upheld
    """
    ctx = setup_routable(metric="QA_AVG", target=80)
    contract_id = ctx["contract"]["id"]
    agent_b = create_agent(full_name="Agent Two")
    certify_agent(agent_b["id"], ctx["course"]["id"])

    def completed(enqueued_at, agent_id):
        call = register_call(contract_id, enqueued_at=enqueued_at)
        call = route_call(call["id"])
        call = answer_call(call, agent_id)
        return complete_call(call, agent_id)

    call_1 = completed("2026-09-05T09:00:00Z", ctx["agent"]["id"])
    call_2 = completed("2026-09-05T09:05:00Z", agent_b["id"])

    r1 = create_review(call_1["id"], accuracy_score=50, compliance_score=50)
    transition_review(r1["id"], "ACCEPTED", QA_H)
    r2 = create_review(call_2["id"], accuracy_score=80, compliance_score=80)
    transition_review(r2["id"], "DISPUTED", make_agent_headers(agent_b["id"]))

    invoice = create_invoice(contract_id)
    prepare_invoice(invoice["id"])
    line = list_invoice_lines(invoice["id"])[0]
    assert line["measured_value"] == 50.0, "provisional: only the final R1 counts"

    upheld = transition_review(r2["id"], "UPHELD", QA_H)
    assert upheld["final"] is True
    validate_success(api_client.recompute_invoice(invoice["id"], BILL_H))
    line = list_invoice_lines(invoice["id"])[0]
    assert line["measured_value"] == 65.0, "official: mean of 50 and 80, 2dp"
    assert line["compliant"] is False, "65.00 < target 80"


def test_qa_avg_provisional_excludes_submitted_reviews():
    """PRD §3.9: "The first preparation of an invoice takes the
    **provisional** variant: the input set is taken at the preparation instant
    and stored on the line — for quality, only reviews already final at that
    instant count."
    PRD §3.9: "For `QA_AVG`, the input set is the reviews with `final` true —
    status `ACCEPTED` or `UPHELD`".

    Design: Difficulty/dual_variant_calc/qa_avg_provisional_vs_official_after_dispute_upheld
    """
    ctx = setup_routable(metric="QA_AVG", target=80)
    contract_id = ctx["contract"]["id"]
    call = register_call(contract_id, enqueued_at="2026-09-05T09:00:00Z")
    call = route_call(call["id"])
    call = answer_call(call, ctx["agent"]["id"])
    call = complete_call(call, ctx["agent"]["id"])
    # Review created but left SUBMITTED: not final at the prepare instant.
    create_review(call["id"], accuracy_score=95, compliance_score=95)

    invoice = create_invoice(contract_id)
    prepare_invoice(invoice["id"])
    line = list_invoice_lines(invoice["id"])[0]
    assert line["measured_value"] is None, (
        "no final review exists at preparation, so measured_value is null"
    )
    assert line["compliant"] is False


def test_asa_measured_exactly_at_target_is_compliant():
    """PRD §3.9: "For `ASA` and `ABANDON`, the line is compliant when
    `measured_value` is less than or equal to the service level's `target`".
    PRD §3.10: "A compliant line always withholds 0."

    Design: Difficulty/boundary_precision_check/asa_measured_exactly_at_target_is_compliant
    """
    ctx = setup_routable(metric="ASA", target=30)
    # Staff the program to its baseline target so the staffing-shortfall
    # override of PRD §3.9 does not force the line non-compliant.
    staff_to_target(ctx["course"]["id"])
    call = register_call(ctx["contract"]["id"], enqueued_at="2026-09-05T09:00:00Z")
    set_clock("2026-09-05T09:00:00Z")
    call = route_call(call["id"])
    answer_call(call, ctx["agent"]["id"], answer_at="2026-09-05T09:00:30Z")

    invoice = create_invoice(ctx["contract"]["id"])
    prepare_invoice(invoice["id"])
    line = list_invoice_lines(invoice["id"])[0]
    assert line["measured_value"] == 30
    assert line["compliant"] is True
    assert line["withheld_cents"] == 0
    assert list_cure_periods(line["id"]) == []


def test_asa_one_second_over_target_withholds_tier_one():
    """PRD §3.10: "The miss ratio is the miss divided by the target, and the
    tier boundaries are asymmetric by design: a ratio strictly below 0.05
    withholds 10 percent of gross; a ratio at least 0.05 and strictly below
    0.15 withholds 25 percent; a ratio of 0.15 or greater withholds 40
    percent. The raw withholding is the invoice's `gross_cents` multiplied by
    the tier rate, rounded half-up to cents."
    PRD §3.9: "For each program, count the agents with `employment_status`
    `ACTIVE` who hold at least one standing certification for the program at
    the period end ... Each such certification contributes the fixed per-agent
    monthly rate of 4000 cents ... and the fixed monthly base fee of 50000
    cents is added to produce `gross_cents`."

    Design: Difficulty/boundary_precision_check/asa_measured_exactly_at_target_is_compliant
    """
    # Answered in 31s against target 30: miss_ratio 1/30 = 0.0333 < 0.05
    # -> tier 0.10; gross 54000 (50000 + 4000 * 1 cert) -> withheld 5400.
    ctx = setup_routable(metric="ASA", target=30)
    call = register_call(ctx["contract"]["id"], enqueued_at="2026-09-05T09:00:00Z")
    set_clock("2026-09-05T09:00:00Z")
    call = route_call(call["id"])
    answer_call(call, ctx["agent"]["id"], answer_at="2026-09-05T09:00:31Z")

    invoice = create_invoice(ctx["contract"]["id"])
    invoice = prepare_invoice(invoice["id"])
    assert invoice["gross_cents"] == 54000
    line = list_invoice_lines(invoice["id"])[0]
    assert line["measured_value"] == 31
    assert line["compliant"] is False
    assert line["withheld_cents"] == 5400
    cures = list_cure_periods(line["id"])
    assert len(cures) == 1
    assert cures[0]["status"] == "PENDING"


def test_qa_avg_empty_final_set_is_null_and_noncompliant():
    """PRD §3.9: "An empty quality set yields a null `measured_value`, and a
    null `measured_value` counts as non-compliant for `QA_AVG`."
    PRD §3.10: "for `QA_AVG`, the target minus the measured score — and when
    the measured value is null, the miss is the whole target. The miss ratio
    is the miss divided by the target ... a ratio of 0.15 or greater withholds
    40 percent."
    PRD §3.11: "At preparation or recompute, the system creates a
    **CurePeriod** for each non-compliant line".

    Design: Difficulty/boundary_precision_check/qa_avg_empty_final_set_is_null_and_noncompliant
    """
    ctx = setup_routable(metric="QA_AVG", target=80)
    invoice = create_invoice(ctx["contract"]["id"])
    invoice = prepare_invoice(invoice["id"])
    # No certified agents were needed for QA measurement, but one exists from
    # the routable fixture: gross = 50000 + 4000 = 54000.
    assert invoice["gross_cents"] == 54000
    line = list_invoice_lines(invoice["id"])[0]
    assert line["measured_value"] is None, "empty final-review set is null, not 0"
    assert line["compliant"] is False
    # miss == target -> ratio 1.0 -> tier 3 -> round_half_up(54000 * 0.40)
    assert line["withheld_cents"] == 21600
    cures = list_cure_periods(line["id"])
    assert len(cures) == 1
    assert cures[0]["status"] == "PENDING"
    assert cures[0]["remedy_fee_cents"] == 1000


def test_qa_avg_null_measured_miss_ratio_is_one():
    """PRD §3.10: "for `QA_AVG`, the target minus the measured score — and
    when the measured value is null, the miss is the whole target."
    PRD §3.9: "An empty quality set yields a null `measured_value`, and a null
    `measured_value` counts as non-compliant for `QA_AVG`."

    Design: Difficulty/boundary_precision_check/qa_avg_empty_final_set_is_null_and_noncompliant
    """
    ctx = setup_routable(metric="QA_AVG", target=80)
    invoice = create_invoice(ctx["contract"]["id"])
    invoice = prepare_invoice(invoice["id"])
    line = list_invoice_lines(invoice["id"])[0]
    assert line["measured_value"] is None
    assert line["compliant"] is False
    assert invoice["withheld_cents"] == line["withheld_cents"] == 21600
    assert invoice["net_cents"] == 54000 - 21600


def test_gross_fee_evaluation_order_and_rounding():
    """PRD §3.9: "Each such certification contributes the fixed per-agent
    monthly rate of 4000 cents, scaled by the program's surge multiplier
    clamped so it never falls below 1.0. The program subtotals are computed at
    full precision, summed, and rounded half-up exactly once — never rounded
    per program — and the fixed monthly base fee of 50000 cents is added to
    produce `gross_cents`."
    PRD §3.9: "The `staffing_target` is the baseline staffing of 10 multiplied
    by the surge multiplier for the program at period end — the selector of
    §3.7 — rounded up to the next integer."
    PRD §3.9: "Overriding all three, a staffing shortfall — `staffing_actual`
    strictly less than `staffing_target` — forces the line to non-compliant
    regardless of the metric."

    Design: Difficulty/combinatorial_formula/gross_fee_evaluation_order_and_rounding
    """
    ctx = setup_routable(metric="ASA", target=30)
    window = create_surge_window(
        ctx["contract"]["id"],
        starts_on="2026-09-15T00:00:00Z",
        ends_on="2026-09-30T00:00:00Z",
        expected_volume_factor=1.25,
    )
    set_clock("2026-09-20T00:00:00Z")
    assert get_surge_window(window["id"])["status"] == "ACTIVE"

    invoice = create_invoice(ctx["contract"]["id"])
    invoice = prepare_invoice(invoice["id"])
    # 50000 + round_half_up(4000 * 1 * 1.25) = 55000
    assert invoice["gross_cents"] == 55000
    line = list_invoice_lines(invoice["id"])[0]
    assert line["staffing_target"] == 13, "ceil(10 * 1.25)"
    assert line["staffing_actual"] == 1
    assert line["compliant"] is False, "staffing shortfall forces non-compliance"


def test_gross_fee_rounds_summed_subtotal_once():
    """PRD §3.9: "The program subtotals are computed at full precision,
    summed, and rounded half-up exactly once — never rounded per program —
    and the fixed monthly base fee of 50000 cents is added to produce
    `gross_cents`."

    Design: Difficulty/combinatorial_formula/gross_fee_evaluation_order_and_rounding
    """
    # Without any surge: gross = 50000 + round_half_up(4000 * 1 * 1.0) = 54000.
    ctx = setup_routable(metric="ASA", target=30)
    invoice = create_invoice(ctx["contract"]["id"])
    invoice = prepare_invoice(invoice["id"])
    assert invoice["gross_cents"] == 54000
    line = list_invoice_lines(invoice["id"])[0]
    assert line["staffing_target"] == 10, "ceil(10 * 1.0)"
    assert line["staffing_actual"] == 1
    assert line["compliant"] is False


def test_auto_review_requires_second_approver():
    """PRD §3.12: "The segregation-of-duties gate fires when the invoice's
    `auto_review` flag is true: the approving `X-User-ID` must differ from the
    user id of the `BillingAnalyst` recorded as preparer on the invoice, or
    the approval is rejected with
    `ERR_AUTO_REVIEW_REQUIRES_SECOND_APPROVER` (HTTP 409). The `auto_review`
    flag is set by preparation whenever it recomputed any line while a
    completed cure period — `REMEDIED` or `FORFEIT` — existed for that line's
    service level."

    Design: Corner/validations/auto_review_requires_second_approver
    """
    billing1 = make_billing_headers("billing-1")
    ctx = setup_routable(metric="ASA", target=30)
    contract_id = ctx["contract"]["id"]
    call = register_call(contract_id, enqueued_at="2026-09-05T09:00:00Z")
    set_clock("2026-09-05T09:00:00Z")
    call = route_call(call["id"])
    answer_call(call, ctx["agent"]["id"], answer_at="2026-09-05T09:00:40Z")

    invoice = create_invoice(contract_id)
    invoice = prepare_invoice(invoice["id"], headers=billing1)
    line = list_invoice_lines(invoice["id"])[0]
    assert line["withheld_cents"] == 21600
    cure = list_cure_periods(line["id"])[0]
    pay_remedy(cure["id"], headers=billing1)

    recomputed = validate_success(
        api_client.recompute_invoice(invoice["id"], billing1)
    )
    assert recomputed["auto_review"] is True, (
        "recompute with a completed cure period sets auto_review"
    )
    validate_success(
        api_client.transition_invoice(
            invoice["id"], {"to_status": "SUBMITTED"}, billing1
        )
    )

    contract = get_contract(contract_id)
    same_user = api_client.transition_invoice(
        invoice["id"],
        {
            "to_status": "APPROVED",
            "expected_contract_version": contract["version"],
        },
        make_ops_headers("billing-1"),
    )
    validate_error(
        same_user, ApiErrorId.ERR_AUTO_REVIEW_REQUIRES_SECOND_APPROVER
    )

    other_user = api_client.transition_invoice(
        invoice["id"],
        {
            "to_status": "APPROVED",
            "expected_contract_version": contract["version"],
        },
        make_ops_headers("ops-9"),
    )
    approved = validate_success(other_user)
    assert approved["status"] == "APPROVED"
