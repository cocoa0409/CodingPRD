"""Difficulty queue: PT fail cascade to credit hold; distributability gates."""
from test_helpers import (
    ApiErrorId, create_draft_certificate, get_lot,
    make_accreditation_officer_headers, make_customer, make_customer_headers,
    make_inventory_manager_headers, make_pt_round, place_order,
    publish_certificate, run_failing_pt_round, set_clock,
    setup_lot_in_distribution, setup_value_assignment_lot, validate_error,
    validate_success,
)

_AO = make_accreditation_officer_headers()
_INV = make_inventory_manager_headers()


def _setup_cascade(validity_days=365, program_code="NIST-RM-07"):
    """Lot IN_DISTRIBUTION with UNWEIGHTED cert (certified 102.0, expanded
    uncertainty 4.0); ACCREDITED_LAB participant customer."""
    ctx = setup_lot_in_distribution(total=10, material_code="SRM-G",
                                    variant="UNWEIGHTED_MEAN",
                                    validity_days=validity_days,
                                    program_overrides={"program_code": program_code})
    customer = make_customer(name="Participant Lab", tier="ACCREDITED_LAB")
    return ctx, customer


def test_two_fails_probation_still_allows_orders(api):
    """PRD §3.7: "at exactly the `PT_PROBATION_FAIL_COUNT` of two failures
    `accreditation_standing` drops to `PROBATION`, still without a credit hold".
    PRD §3.7: "Every `FAIL` increments the customer's `pt_fail_count` by one and
    recomputes standing".

    Design: Difficulty/transitive_cascade/pt_evaluation_fail_cascade_to_credit_hold
    """
    ctx, customer = _setup_cascade()
    run_failing_pt_round(ctx["lot"]["id"], "PT-1", customer["id"])
    run_failing_pt_round(ctx["lot"]["id"], "PT-2", customer["id"])
    probe = place_order(ctx["lot"]["id"], customer["id"], 1)
    assert probe["status"] == "ALLOCATED"


def test_third_fail_suspends_and_blocks_orders(api):
    """PRD §3.7: "at or beyond the `PT_SUSPENSION_FAIL_COUNT` of three — the
    boundary at exactly three included — the customer is `SUSPENDED` and
    `credit_hold` becomes true, which the order gate of §3.5 enforces as
    `ERR_CREDIT_LIMIT_EXCEEDED`."

    Design: Difficulty/transitive_cascade/pt_evaluation_fail_cascade_to_credit_hold
    """
    ctx, customer = _setup_cascade()
    run_failing_pt_round(ctx["lot"]["id"], "PT-1", customer["id"])
    run_failing_pt_round(ctx["lot"]["id"], "PT-2", customer["id"])
    run_failing_pt_round(ctx["lot"]["id"], "PT-3", customer["id"], close=False)
    resp = api.create_sales_order({"lot_id": ctx["lot"]["id"], "quantity": 1},
                                  make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)


def _setup_certified_lot_with_round():
    """Lot CERTIFIED (published cert, not yet IN_DISTRIBUTION) + PLANNING round."""
    ctx = setup_value_assignment_lot(total=10, material_code="SRM-M",
                                     program_overrides={"program_code": "NIST-RM-14"})
    cert = create_draft_certificate(ctx["lot"]["id"], certificate_code="CERT-M")
    publish_certificate(cert["id"])
    rnd = make_pt_round(ctx["lot"]["id"], round_code="PT-M1", sample_units_reserved=2)
    return ctx, rnd


def test_pt_distribution_rejected_before_lot_in_distribution(api):
    """PRD §3.7: "Moving it to `SAMPLE_DISTRIBUTION` requires the lot to be
    `IN_DISTRIBUTION` (`ERR_LOT_NOT_DISTRIBUTABLE`)".

    Design: Difficulty/cross_entity_state_dependency/pt_distribution_requires_lot_in_distribution
    """
    ctx, rnd = _setup_certified_lot_with_round()
    assert get_lot(ctx["lot"]["id"])["status"] == "CERTIFIED"
    resp = api.transition_pt_round(rnd["id"], {"to": "SAMPLE_DISTRIBUTION"}, _AO)
    validate_error(resp, ApiErrorId.ERR_LOT_NOT_DISTRIBUTABLE)


def test_pt_distribution_succeeds_after_entering_distribution(api):
    """PRD §3.7: "Moving it to `SAMPLE_DISTRIBUTION` requires the lot to be
    `IN_DISTRIBUTION` (`ERR_LOT_NOT_DISTRIBUTABLE`) and its `units_available` to
    cover `sample_units_reserved` (`ERR_INSUFFICIENT_UNITS`); those units are
    then added to the lot's `units_reserved`".

    Design: Difficulty/cross_entity_state_dependency/pt_distribution_requires_lot_in_distribution
    """
    ctx, rnd = _setup_certified_lot_with_round()
    validate_success(api.transition_material_lot(ctx["lot"]["id"],
                                                 {"to": "IN_DISTRIBUTION"}, _INV))
    rnd = validate_success(api.transition_pt_round(rnd["id"],
                                                   {"to": "SAMPLE_DISTRIBUTION"}, _AO))
    assert rnd["status"] == "SAMPLE_DISTRIBUTION"
    assert get_lot(ctx["lot"]["id"])["units_reserved"] == 2


def _three_fails_then_hold():
    """Lot with validity-30 cert; customer accumulates 3 PT FAILs; clock then
    advanced to expiration so the lot lands in DISTRIBUTION_HOLD."""
    ctx, customer = _setup_cascade(validity_days=30, program_code="NIST-RM-09")
    for code in ("PT-I1", "PT-I2", "PT-I3"):
        run_failing_pt_round(ctx["lot"]["id"], code, customer["id"], close=False)
    set_clock("2026-10-01T00:00:00Z")
    assert get_lot(ctx["lot"]["id"])["status"] == "DISTRIBUTION_HOLD"
    return ctx, customer


def test_lot_state_precedes_credit_fiscal(api):
    """PRD §2.8: "A request that fails an earlier stage is rejected immediately
    with that stage's error and never reaches later stages; where several stages
    apply to the same request, the relative order below is authoritative." —
    distributability (stage 10) precedes credit standing (stage 22).

    Design: Difficulty/priority_pair_validation_conflict/lot_state_precedes_credit_fiscal
    """
    ctx, customer = _three_fails_then_hold()
    resp = api.create_sales_order({"lot_id": ctx["lot"]["id"], "quantity": 1},
                                  make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_LOT_NOT_DISTRIBUTABLE)


def test_credit_hold_fires_when_lot_distributable(api):
    """PRD §2.8: "A customer under credit hold cannot place sales orders
    (`ERR_CREDIT_LIMIT_EXCEEDED`, 402)."
    PRD §3.7: "at or beyond the `PT_SUSPENSION_FAIL_COUNT` of three — the
    boundary at exactly three included — the customer is `SUSPENDED` and
    `credit_hold` becomes true".

    Design: Difficulty/priority_pair_validation_conflict/lot_state_precedes_credit_fiscal
    """
    ctx, customer = _setup_cascade()
    for code in ("PT-J1", "PT-J2", "PT-J3"):
        run_failing_pt_round(ctx["lot"]["id"], code, customer["id"], close=False)
    assert get_lot(ctx["lot"]["id"])["status"] == "IN_DISTRIBUTION"
    resp = api.create_sales_order({"lot_id": ctx["lot"]["id"], "quantity": 1},
                                  make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
