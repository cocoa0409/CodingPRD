"""Funding and disbursement request gates: deposit accumulation and cap, the
fund-status precondition, the remaining-cents bound, and the use-code rule.
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_disbursement_payload,
    deposit_funds,
    deposit_payload,
    disburse_line_in_full,
    file_finding,
    fund_world,
    get_allocation_line,
    get_settlement,
    make_lead_state_ag_headers,
    make_participating_state_ag_headers,
    open_monitoring_period,
    request_disbursement,
    setup_executed_world,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

CHAIR = TEST_USERS["committee_chair_headers"]
COUNSEL = TEST_USERS["defendant_counsel_headers"]
FUND_ADMIN = TEST_USERS["fund_administrator_headers"]


def _line(world, code):
    return {l["state_code"]: l for l in world["lines"]}[code]


def test_deposit_partial_then_exact_total_funding():
    """PRD section 3.5: "Each accepted deposit is added to `deposited_cents`
    and drives the fund dimension: the first deposit that leaves the fund
    short of the total moves `UNFUNDED` → `PARTIALLY_FUNDED`, and the deposit
    that brings cumulative funding to exactly the total moves the fund to
    `FUNDED`."

    Design: Corner/endpoints/deposit_partial_then_exact_total_funding
    """
    world = setup_executed_world()
    stl_id = world["settlement"]["id"]
    first = deposit_funds(stl_id, 40000000)
    assert first["fund_status"] == "PARTIALLY_FUNDED"
    assert first["deposited_cents"] == 40000000
    second = deposit_funds(stl_id, 60000000)
    assert second["deposited_cents"] == 100000000
    assert second["deposited_cents"] == second["monetary_total_cents"]
    assert second["fund_status"] == "FUNDED", (
        "landing exactly on the total is the inclusive FUNDED boundary"
    )


def test_deposit_overshoot_rejected():
    """PRD section 3.5: "no deposit may push the cumulative `deposited_cents`
    past the settlement's `monetary_total_cents` — an overshooting deposit is
    rejected with `ERR_DEPOSIT_EXCEEDS_TOTAL` (HTTP 422)."

    Design: Corner/errors/deposit_overshoot_rejected
    """
    world = setup_executed_world()
    stl_id = world["settlement"]["id"]
    deposit_funds(stl_id, 60000000)
    resp = api_client.deposit_settlement(stl_id, deposit_payload(50000000), COUNSEL)
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_EXCEEDS_TOTAL)
    settlement = get_settlement(stl_id)
    assert settlement["deposited_cents"] == 60000000
    assert settlement["fund_status"] == "PARTIALLY_FUNDED"


def test_disbursement_request_requires_funded_settlement():
    """PRD section 3.5: "the settlement's fund must be at least partially
    funded — `PARTIALLY_FUNDED`, `FUNDED`, or `DISBURSING` — since partial
    funding permits release up to the available balance (else
    `ERR_SETTLEMENT_NOT_FUNDED`, HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/disbursement_request_requires_funded_settlement
    """
    world = setup_executed_world()
    ca_line = _line(world, "CA")
    assert world["settlement"]["fund_status"] == "UNFUNDED"
    resp = api_client.create_disbursement(
        ca_line["id"],
        create_disbursement_payload(amount_cents=1000, use_code="PROGRAM"),
        make_lead_state_ag_headers(world["offices"]["CA"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SETTLEMENT_NOT_FUNDED)
    disbs, meta = validate_paginated(
        api_client.list_allocation_line_disbursements(ca_line["id"], CHAIR)
    )
    assert disbs == [] and meta["total_count"] == 0


def test_amount_exceeds_remaining_rejected():
    """PRD section 3.5: "the `amount_cents` must be greater than zero and no
    more than the line's `remaining_cents` (else `ERR_AMOUNT_EXCEEDS_REMAINING`,
    HTTP 422)."

    Design: Corner/errors/amount_exceeds_remaining_rejected
    """
    world = setup_executed_world()
    stl_id = world["settlement"]["id"]
    ca_line = _line(world, "CA")
    assert ca_line["status"] == "ELIGIBLE"
    assert ca_line["gross_share_cents"] == 12937500
    deposit_funds(stl_id, 1000000)  # PARTIALLY_FUNDED: the fund gate passes
    resp = api_client.create_disbursement(
        ca_line["id"],
        create_disbursement_payload(amount_cents=12937501, use_code="PROGRAM"),
        make_lead_state_ag_headers(world["offices"]["CA"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_AMOUNT_EXCEEDS_REMAINING)
    disbs, _ = validate_paginated(
        api_client.list_allocation_line_disbursements(ca_line["id"], CHAIR)
    )
    assert disbs == [], "no disbursement may be persisted"


def test_insufficient_fund_balance_on_release():
    """PRD section 3.5: "For a `PREAPPROPRIATED` office the disbursement is
    created already `CERTIFIED` — certification is automatic."
    PRD section 3.5: "A `FundAdministrator` releases a disbursement ... only
    while the settlement's undisbursed balance covers it — `deposited_cents`
    minus `released_cents` must be at least the disbursement's amount, else
    `ERR_INSUFFICIENT_FUND_BALANCE` (HTTP 422)."

    Design: Corner/errors/insufficient_fund_balance_on_release
    """
    world = setup_executed_world()
    stl_id = world["settlement"]["id"]
    ca_line = _line(world, "CA")
    deposit_funds(stl_id, 5000000)
    disb = request_disbursement(
        ca_line, world["offices"]["CA"], True,
        amount_cents=6000000, use_code="PROGRAM",
    )
    assert disb["status"] == "CERTIFIED", (
        "CA is PREAPPROPRIATED, so certification is automatic at creation"
    )
    resp = api_client.release_disbursement(disb["id"], FUND_ADMIN)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FUND_BALANCE)
    disbs, _ = validate_paginated(
        api_client.list_allocation_line_disbursements(ca_line["id"], CHAIR)
    )
    assert disbs[0]["status"] == "CERTIFIED", "the failed release mutates nothing"


def test_use_code_restricted_for_general_fund_only():
    """PRD section 3.5: "an office whose `appropriation_rule` is
    `GENERAL_FUND_ONLY` may request only `use_code` `GENERAL_FUND` (else
    `ERR_USE_CODE_NOT_PERMITTED`, HTTP 422)."
    PRD section 3.5: "For offices under `CERTIFICATION_REQUIRED` or
    `GENERAL_FUND_ONLY`, the disbursement is created in `REQUESTED`."
    PRD section 3.4: "The lead cost pool is split equally among locked lines
    whose offices hold `committee_role` `LEAD`."

    Design: Corner/errors/use_code_restricted_for_general_fund_only
    """
    world = setup_executed_world(decisions={
        "CA": "DECLINED", "TX": "SIGNED", "NY": "SIGNED", "FL": "SIGNED",
    })
    stl_id = world["settlement"]["id"]
    lines = {l["state_code"]: l for l in world["lines"]}
    # Locked populations 300/400/200 (sum 900): TX 3333 / NY 4445 / FL 2222
    # bps; CA declined, so sole signed lead TX takes the whole lead pool.
    assert lines["FL"]["gross_share_cents"] == 18998100
    assert lines["TX"]["lead_bonus_cents"] == 4500000
    deposit_funds(stl_id, 1000000)
    fl_headers = make_participating_state_ag_headers(world["offices"]["FL"]["id"])
    resp_bad = api_client.create_disbursement(
        lines["FL"]["id"],
        create_disbursement_payload(amount_cents=500000, use_code="PROGRAM"),
        fl_headers,
    )
    validate_error(resp_bad, ApiErrorId.ERR_USE_CODE_NOT_PERMITTED)
    resp_ok = api_client.create_disbursement(
        lines["FL"]["id"],
        create_disbursement_payload(amount_cents=500000, use_code="GENERAL_FUND"),
        fl_headers,
    )
    disb = validate_success(resp_ok, 201)
    assert disb["status"] == "REQUESTED", (
        "GENERAL_FUND_ONLY offices are not auto-certified"
    )


def test_state_beats_fiscal_on_disbursed_line():
    """PRD section 3.5: "The request is guarded in ladder order: the line must
    be `ELIGIBLE` or `DISBURSING` (else `ERR_LINE_NOT_DISBURSABLE`, HTTP
    409)" and "the `amount_cents` must be greater than zero and no more
    than the line's `remaining_cents` (else `ERR_AMOUNT_EXCEEDS_REMAINING`,
    HTTP 422)."
    PRD section 2.8: "Every request is evaluated against a fixed ladder of
    checks, and the first failure wins."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_disbursed_line
    """
    world = setup_executed_world()
    fund_world(world)
    ca_line = _line(world, "CA")
    disburse_line_in_full(world, ca_line)
    fresh = get_allocation_line(ca_line["id"])
    assert fresh["status"] == "DISBURSED" and fresh["remaining_cents"] == 0
    # The 1-cent request violates both the line-state gate (DISBURSED) and the
    # remaining-cents bound (0); the state gate wins the ladder.
    resp = api_client.create_disbursement(
        ca_line["id"],
        create_disbursement_payload(amount_cents=1, use_code="PROGRAM"),
        make_lead_state_ag_headers(world["offices"]["CA"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_LINE_NOT_DISBURSABLE)


def test_compliance_hold_blocks_new_disbursement():
    """PRD section 3.5: "the settlement's `compliance_hold` must be false
    (else `ERR_COMPLIANCE_HOLD_ACTIVE`, HTTP 409)."
    PRD section 3.7: "If `breach_count` is at least 2, the period closes
    `CLOSED_BREACH` and escalates: the settlement's `compliance_hold` is set
    true, and every `CERTIFIED` disbursement on the settlement's lines moves
    to `HELD`."

    Design: Corner/errors/compliance_hold_blocks_new_disbursement
    """
    world = setup_executed_world()
    stl_id = world["settlement"]["id"]
    ca_line = _line(world, "CA")
    deposit_funds(stl_id, 10000000)
    period = open_monitoring_period(stl_id)
    file_finding(period["id"], 0, "BREACH")
    file_finding(period["id"], 1, "BREACH")
    file_finding(period["id"], 2, "COMPLIANT")  # auto-closes CLOSED_BREACH
    assert get_settlement(stl_id)["compliance_hold"] is True
    resp = api_client.create_disbursement(
        ca_line["id"],
        create_disbursement_payload(amount_cents=1000, use_code="PROGRAM"),
        make_lead_state_ag_headers(world["offices"]["CA"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_COMPLIANCE_HOLD_ACTIVE)
