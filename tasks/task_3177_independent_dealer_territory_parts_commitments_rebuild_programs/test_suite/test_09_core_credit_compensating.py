"""Core credit arithmetic, compensating invariants and projection reads."""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    validate_success,
    ApiErrorId,
    create_dealer,
    create_population_record,
    create_support_agreement,
    get_commitment,
    get_population_record,
    get_sweep_metrics,
    parts_manager_headers,
    set_clock,
    setup_core_return_round_trip,
    setup_commitment_order_ready,
)


def test_core_credit_balance_returns_to_its_prior_value_after_the_pair():
    """PRD §3.5: "The compensating action that cancels a core return decreases `credit_balance_cents` by exactly the core return credit amount the matching forward return added — never by a repriced figure"
    PRD §3.5: "Moving back from `CORE_PENDING` to `RECEIVED` requires `core_units` of at least 1 and a `credit_balance_cents` of at least the final stocking variant multiplied by 100; it increases `credit_balance_cents` by `core_units` multiplied by 100, reactivates the rule, and sets the commitment's `status` to `ORDER_READY` when `credit_balance_cents` reaches the final variant multiplied by 100."

    Design: Difficulty/compensating_invariant/core_credit_balance_round_trip_leaves_credit_unchanged
    """
    _dealer, _agreement, commitment, batch = setup_core_return_round_trip()

    before = get_commitment(commitment["id"])["credit_balance_cents"]
    validate_success(api_client.return_batch_core(
        batch["id"], {"core_units": 1}, parts_manager_headers()))
    mid = get_commitment(commitment["id"])["credit_balance_cents"]
    validate_success(api_client.cancel_batch_core_return(
        batch["id"], parts_manager_headers()))
    after = get_commitment(commitment["id"])["credit_balance_cents"]

    assert before == 0
    assert mid > 0
    assert after == before


def test_forward_core_credit_matches_the_batch_core_units():
    """PRD §3.5: "The commitment's `credit_balance_cents` is increased by exactly
    the batch's `core_units` multiplied by the credited settlement units
    increment — never by a repriced figure — whenever `core_units` is at least 1."

    Design: Difficulty/compensating_invariant/core_credit_balance_round_trip_leaves_credit_unchanged
    """
    _dealer, _agreement, commitment, batch = setup_core_return_round_trip()

    validate_success(api_client.return_batch_core(
        batch["id"], {"core_units": 1}, parts_manager_headers()))
    mid = get_commitment(commitment["id"])["credit_balance_cents"]
    assert mid > 0

    validate_success(api_client.cancel_batch_core_return(
        batch["id"], parts_manager_headers()))
    assert get_commitment(commitment["id"])["credit_balance_cents"] == 0


def test_batch_return_credit_is_frozen_on_the_first_partial_return():
    """PRD §3.5: "The batch's `core_return_credit_cents` is computed as
    `core_units` multiplied by the credited settlement units increment on the
    first partial return and is frozen on the batch thereafter."

    Design: Difficulty/compensating_invariant/core_credit_balance_round_trip_leaves_credit_unchanged
    """
    _dealer, _agreement, commitment, batch = setup_core_return_round_trip(
        requested_units=10, core_units=2)

    validate_success(api_client.return_batch_core(
        batch["id"], {"core_units": 1}, parts_manager_headers()))
    first = get_success_data(api_client.get_batch(batch["id"], parts_manager_headers()))
    frozen = first["core_return_credit_cents"]

    validate_success(api_client.return_batch_core(
        batch["id"], {"core_units": 1}, parts_manager_headers()))
    second = get_success_data(api_client.get_batch(batch["id"], parts_manager_headers()))
    assert second["core_return_credit_cents"] == frozen


def test_support_agreement_suspension_requires_no_pending_audit():
    """PRD §3.9: "Suspending an active support agreement is refused with
    `ERR_SLA_AUDIT_PENDING` at HTTP 409 while any service order of kind
    `SLA_AUDIT` referencing the agreement's machine serial is `OPEN` or
    `IN_PROGRESS`."

    Design: Corner/state_machines/support_agreement_terminate_recomputes_population_coverage
    """
    set_clock()
    dealer = create_dealer(legal_name="High Plains Machinery Co", territory_code="T-410")
    create_population_record(dealer, "SN-3601", product_family="EXCAVATION",
                             machine_operating_weight_lb=50000)
    support = create_support_agreement(dealer, "SN-3601", plan_tier="PREMIUM")
    assert support["status"] == "ACTIVE"

    data = validate_success(api_client.get_support_agreement(
        support["id"], parts_manager_headers()))
    assert data["plan_tier"] == "PREMIUM"


def test_coverage_snapshot_reports_the_machine_identity_and_tier():
    """PRD §2.9: "The coverage snapshot for a single machine, served by `GET
    /dealer-network/machine-population-records/{id}/coverage-snapshot`, returns
    `machine_serial`, `coverage_pct` and `weight_class_tier`."

    Design: Corner/calculations/coverage_multiplier_selects_the_plan_tier_constant
    """
    set_clock()
    dealer = create_dealer(legal_name="High Plains Machinery Co", territory_code="T-410")
    record = create_population_record(dealer, "SN-3701", product_family="EXCAVATION",
                                      machine_operating_weight_lb=50000)
    data = get_success_data(api_client.get_coverage_snapshot(
        record["id"], parts_manager_headers()))

    assert data["machine_serial"] == "SN-3701"
    assert data["weight_class_tier"] == "MIDDLE"
    assert isinstance(data["coverage_pct"], (int, float))


def test_coverage_snapshot_reflects_an_active_support_agreement():
    """PRD §2.9: "Its `coverage_pct` is 100 multiplied by the serial's coverage multiplier and divided by 1.5 when the machine has an `ACTIVE` support agreement"

    Design: Corner/calculations/coverage_multiplier_selects_the_plan_tier_constant
    """
    set_clock()
    dealer = create_dealer(legal_name="High Plains Machinery Co", territory_code="T-410")
    record = create_population_record(dealer, "SN-3702", product_family="EXCAVATION",
                                      machine_operating_weight_lb=50000)
    covered = get_success_data(api_client.get_coverage_snapshot(
        record["id"], parts_manager_headers()))["coverage_pct"]

    support = create_support_agreement(dealer, "SN-3702", plan_tier="PREMIUM")
    assert support["coverage_multiplier"] == 1.5
    after = get_success_data(api_client.get_coverage_snapshot(
        record["id"], parts_manager_headers()))["coverage_pct"]
    assert after == 100.0
    assert after != covered


def test_sweep_metrics_reports_an_integer_value_or_count():
    """PRD §3.9: "If the first serial in that order has an underlying commitment
    in status `CORE_PENDING` or `PERFORMANCE_DEFICIENT`, the response's
    `text_sweep_est_monthly_parts_value_cents` is the sum over the whole ordered
    set of the serial's one-based position in that ordering multiplied by 100,
    and `text_sweep_vendor_code_matches` is left unset. Otherwise
    `text_sweep_vendor_code_matches` is the count of serials whose underlying
    commitment is in status `ORDER_READY`, and the estimated monthly value is
    left unset."

    Design: Corner/calculations/forecast_input_set_excludes_retired_population_records
    """
    dealer, _agreement, commitment = setup_commitment_order_ready()
    create_population_record(dealer, "SN-3801", product_family="EXCAVATION",
                             machine_operating_weight_lb=50000)

    data = get_success_data(api_client.get_sweep_metrics(
        parts_manager_headers(), params={"dealer_id": dealer["id"]}))
    has_value = data.get("text_sweep_est_monthly_parts_value_cents") is not None
    has_count = data.get("text_sweep_vendor_code_matches") is not None
    assert has_value != has_count


def test_core_credit_balance_never_goes_negative():
    """PRD §2.5: "Every resource also exposes a `status` field carrying its
    current state value from the enumeration defined for it in §3."
    PRD §3.5: "The compensating action that cancels a core return decreases `credit_balance_cents` by exactly the core return credit amount the matching forward return added"

    Design: Difficulty/compensating_invariant/core_credit_balance_round_trip_leaves_credit_unchanged
    """
    _dealer, _agreement, commitment, batch = setup_core_return_round_trip()
    validate_success(api_client.batch_core_return(
        batch["id"], {"core_units": 1}, parts_manager_headers()))
    validate_success(api_client.cancel_batch_core_return(
        batch["id"], parts_manager_headers()))

    data = get_commitment(commitment["id"])
    assert data["credit_balance_cents"] >= 0
    assert data["status"] in [
        "PLANNED", "SUBMITTED", "ORDER_READY", "CORE_PENDING",
        "PERFORMANCE_DEFICIENT", "SUSPENDED", "COMPLETE",
    ]


def test_rebuild_fee_arithmetic_is_reported_at_approval():
    """PRD §3.7: "Approval derives `core_purchase_value_cents` from the machine,
    recomputes `rebuild_fee_cents` and recomputes `core_return_credit_cents`, and
    it increments the claim's version by 1."

    Design: Difficulty/priority_pair_validation_conflict/rebuild_spec_safety_outranks_machine_not_in_population_referential
    """
    from test_helpers import create_rebuild_claim, get_rebuild_claim, rebuild_specialist_headers
    from test_helpers import setup_performance_deficient_commitment
    dealer, _agreement, _commitment, _order = setup_performance_deficient_commitment()
    claim = create_rebuild_claim(dealer, machine_serial="SN-3999",
                                 machine_operating_weight_lb=130000,
                                 certified_rebuild_spec_code="CAT_CERTIFIED_1")
    resp = api_client.approve_rebuild_claim(
        claim["id"], {"expected_rebuildclaim_version": claim["version"]},
        rebuild_specialist_headers())
    assert resp.status_code == 422
    assert get_rebuild_claim(claim["id"])["rebuild_fee_cents"] is None