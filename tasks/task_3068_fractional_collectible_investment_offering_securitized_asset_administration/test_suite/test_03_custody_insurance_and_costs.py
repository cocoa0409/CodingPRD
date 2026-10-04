"""Custody, insurance and cost pass-through.

The physical object lives somewhere, is insured, and its running cost reaches
the ledger through lots. The exclusivity rules here make overlapping coverage
and custody intervals structurally impossible, and the pass-through amount is
zero unless every gate of the five-clause chain holds at once.
"""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    assert_lot, assert_offering, assert_offering_invariants,
    TEST_USERS,
)
from test_helpers.fixtures import (
    set_clock, create_artist, create_artwork, create_investor, create_offering,
    create_screened_subscription, create_custody_record, create_insurance_policy,
    create_cost_lot, file_appraisal, file_verified_authentication,
    file_verified_provenance, file_circular, allocate_offering, receive_custody,
    release_custody, bind_policy, lapse_policy, get_offering, get_artwork,
    offering_version, setup_held_offering, setup_held_offering_with_policy,
    setup_authenticated_artwork, setup_filed_offering,
)
from test_helpers.assertions import assert_custody_record, assert_insurance_policy

ISSUER = TEST_USERS["issuer_ops_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]

FREEUSER_CUSTODIAN = {
    "custodian_name": "Delaware Freeport Holdings", "facility_code": "DFH-A",
    "is_freeport": True, "custodian_dea_registered": True,
}
OTHER_VAULT = {
    "custodian_name": "Geneva Freeport Vaults", "facility_code": "GFV-B",
    "is_freeport": True, "custodian_dea_registered": True,
}


# ── Custody receipt and release ──────────────────────────────────────────────

def test_receiving_custody_starts_the_holding_clock_and_moves_to_held(api):
    """PRD 3.6: "On receipt the record's `custody_started_at` is stamped from the
    logical clock, the record becomes `IN_CUSTODY`, and the offering starts its holding
    clock: `holding_clock_started_at` is set if it was null, `holding_period_end_at` is
    computed as that instant plus `hold_period_days`, and the offering moves to `HELD`."

    Design: Difficulty/resource_temporal_overlap/custody_intervals_may_not_overlap_and_release_reopens_the_window
    """
    set_clock("2026-09-01T00:00:00Z")
    artwork, offering = setup_filed_offering(start_clock="2026-09-01T00:00:00Z")
    investor = create_investor()
    create_screened_subscription(offering["id"], investor["id"], requested_shares=20000)
    validate_success(allocate_offering(offering["id"]), 200)

    custody = create_custody_record(offering["id"], **FREEUSER_CUSTODIAN)
    set_clock("2027-01-05T00:00:00Z")
    validate_success(receive_custody(custody["id"], offering["id"]), 200)

    record = validate_success(api_client.get_custody_record(custody["id"], ISSUER), 200)
    assert record["status"] == "IN_CUSTODY"
    assert record["custody_started_at"] == "2027-01-05T00:00:00Z"
    assert_custody_record(record)

    after = get_offering(offering["id"])
    assert after["status"] == "HELD"
    assert after["holding_clock_started_at"] == "2027-01-05T00:00:00Z"
    assert after["holding_period_end_at"] == "2027-06-30T00:00:00Z"


def test_receiving_into_custody_is_refused_while_another_record_is_in_custody(api):
    """PRD 3.6: "the record may only be received when the offering carries no other
    record already in `IN_CUSTODY` — otherwise the two custody periods would intersect
    and the attempt is refused with `ERR_CUSTODY_INTERVAL_OVERLAP`".

    Design: Difficulty/resource_temporal_overlap/custody_intervals_may_not_overlap_and_release_reopens_the_window
    """
    artwork, offering, investor, sub, custody_a = setup_held_offering()
    custody_b = create_custody_record(offering["id"], **OTHER_VAULT)

    res = receive_custody(custody_b["id"], offering["id"])
    validate_error(res, "ERR_CUSTODY_INTERVAL_OVERLAP", expected_status=409)

    record_b = validate_success(api_client.get_custody_record(custody_b["id"], ISSUER), 200)
    assert record_b["status"] == "PENDING"
    assert record_b["custody_started_at"] is None

    record_a = validate_success(api_client.get_custody_record(custody_a["id"], ISSUER), 200)
    assert record_a["status"] == "IN_CUSTODY"
    assert get_offering(offering["id"])["holding_clock_started_at"] == "2027-01-05T00:00:00Z"


def test_release_clears_the_holding_clock_and_reopens_the_secondary_window(api):
    """PRD 3.6: "A record in `IN_CUSTODY` may be released only while the offering is
    `HELD`; the record becomes `RELEASED`, its `custody_ended_at` is stamped, and the
    offering's holding clock is cleared — `holding_clock_started_at` and
    `holding_period_end_at` both return to null, and the offering drops back to
    `ALLOCATED`".

        Design: Difficulty/resource_temporal_overlap/custody_intervals_may_not_overlap_and_release_reopens_the_window
    """
    artwork, offering, investor, sub, custody_a = setup_held_offering()
    set_clock("2027-04-01T00:00:00Z")
    validate_success(release_custody(custody_a["id"], offering["id"]), 200)

    record = validate_success(api_client.get_custody_record(custody_a["id"], ISSUER), 200)
    assert record["status"] == "RELEASED"
    assert record["custody_ended_at"] == "2027-04-01T00:00:00Z"

    after = get_offering(offering["id"])
    assert after["status"] == "ALLOCATED"
    assert after["holding_clock_started_at"] is None
    assert after["holding_period_end_at"] is None


def test_a_zero_gap_release_then_receipt_is_admissible(api):
    """PRD 3.6: "A released record can be re-received, and that re-receipt is the
    revision loop by which a work moving between vaults restarts its hold clock." PRD
    3.6: "No other record of the offering may already be `IN_CUSTODY`, on pain of
    `ERR_CUSTODY_INTERVAL_OVERLAP`."

    Design: Corner/state_machines/a_second_custody_receipt_on_the_same_tick_as_a_release_is_admissible
    """
    set_clock("2026-08-01T00:00:00Z")
    _, artwork = setup_authenticated_artwork(start_clock="2026-08-01T00:00:00Z")
    validate_success(file_appraisal(artwork["id"], 90_000_000), 201)
    offering = create_offering(artwork["id"], total_shares=40_000,
                               price_per_share_cents=1_500, registration_cap_pct=5_000,
                               liquidity_ratio_bps=1_000, hold_period_days=176)
    investor = create_investor()
    create_screened_subscription(offering["id"], investor["id"], requested_shares=20000)
    validate_success(file_circular(offering["id"]), 200)
    validate_success(allocate_offering(offering["id"]), 200)

    custody_a = create_custody_record(offering["id"], **FREEUSER_CUSTODIAN)
    set_clock("2027-01-05T00:00:00Z")
    validate_success(receive_custody(custody_a["id"], offering["id"]), 200)
    custody_b = create_custody_record(offering["id"], **OTHER_VAULT)

    set_clock("2027-04-01T00:00:00Z")
    validate_success(release_custody(custody_a["id"], offering["id"]), 200)
    # Re-receipt of the second record requires a selected appraisal filed strictly
    # after the first record's custody_ended_at.
    validate_success(file_appraisal(artwork["id"], 95_000_000), 201)
    validate_success(receive_custody(custody_b["id"], offering["id"]), 200)

    record_b = validate_success(api_client.get_custody_record(custody_b["id"], ISSUER), 200)
    assert record_b["status"] == "IN_CUSTODY"
    record_a = validate_success(api_client.get_custody_record(custody_a["id"], ISSUER), 200)
    assert record_a["status"] == "RELEASED"

    after = get_offering(offering["id"])
    assert after["holding_clock_started_at"] == "2027-04-01T00:00:00Z"
    assert after["holding_period_end_at"] is not None


def test_re_receipt_restamps_the_holding_clock_and_keeps_the_record_count(api):
    """PRD 3.6: "When all four pass, `custody_ended_at` is reset to null,
    `custody_started_at` is re-stamped, the offering's `holding_clock_started_at` is
    re-stamped and `holding_period_end_at` recomputed from it, and the offering returns
    to `HELD`."

    Design: Corner/state_machines/a_second_custody_receipt_on_the_same_tick_as_a_release_is_admissible
    """
    set_clock("2026-08-01T00:00:00Z")
    _, artwork = setup_authenticated_artwork(start_clock="2026-08-01T00:00:00Z")
    validate_success(file_appraisal(artwork["id"], 90_000_000), 201)
    offering = create_offering(artwork["id"], total_shares=40_000,
                               price_per_share_cents=1_500, registration_cap_pct=5_000,
                               liquidity_ratio_bps=1_000, hold_period_days=176)
    investor = create_investor()
    create_screened_subscription(offering["id"], investor["id"], requested_shares=20000)
    validate_success(file_circular(offering["id"]), 200)
    validate_success(allocate_offering(offering["id"]), 200)

    custody_a = create_custody_record(offering["id"], **FREEUSER_CUSTODIAN)
    set_clock("2027-01-05T00:00:00Z")
    validate_success(receive_custody(custody_a["id"], offering["id"]), 200)
    custody_b = create_custody_record(offering["id"], **OTHER_VAULT)
    set_clock("2027-04-01T00:00:00Z")
    validate_success(release_custody(custody_a["id"], offering["id"]), 200)
    validate_success(file_appraisal(artwork["id"], 95_000_000), 201)
    validate_success(receive_custody(custody_b["id"], offering["id"]), 200)

    records = get_success_data(api_client.list_custody_records(offering["id"], ISSUER))
    assert len(records) == 2, "the revision loop adds no record"
    assert get_offering(offering["id"])["status"] == "HELD"


def test_re_receipt_without_a_fresh_appraisal_is_refused_as_stale(api):
    """PRD 3.6: "The artwork must carry a selected appraisal filed strictly after the
    record's `custody_ended_at`; without one the attempt is refused with
    `ERR_APPRAISAL_STALE`."

    Design: Corner/state_machines/a_second_custody_receipt_on_the_same_tick_as_a_release_is_admissible
    """
    set_clock("2026-08-01T00:00:00Z")
    _, artwork = setup_authenticated_artwork(start_clock="2026-08-01T00:00:00Z")
    validate_success(file_appraisal(artwork["id"], 90_000_000), 201)
    offering = create_offering(artwork["id"], total_shares=40_000,
                               price_per_share_cents=1_500, registration_cap_pct=5_000,
                               liquidity_ratio_bps=1_000, hold_period_days=176)
    investor = create_investor()
    create_screened_subscription(offering["id"], investor["id"], requested_shares=20000)
    validate_success(file_circular(offering["id"]), 200)
    validate_success(allocate_offering(offering["id"]), 200)

    custody_a = create_custody_record(offering["id"], **FREEUSER_CUSTODIAN)
    set_clock("2027-01-05T00:00:00Z")
    validate_success(receive_custody(custody_a["id"], offering["id"]), 200)
    set_clock("2027-04-01T00:00:00Z")
    validate_success(release_custody(custody_a["id"], offering["id"]), 200)

    # Re-receiving the released record requires a selected appraisal filed
    # strictly after its own custody_ended_at; the only appraisal on file
    # predates the release, so the attempt is refused.
    res = receive_custody(custody_a["id"], offering["id"])
    validate_error(res, "ERR_APPRAISAL_STALE", expected_status=409)


# ── Insurance exclusivity ────────────────────────────────────────────────────

def test_binding_a_second_policy_while_one_is_in_force_is_refused(api):
    """PRD 3.6: "no sibling policy of the same offering may already be in force, or the
    bind is refused with `ERR_POLICY_INTERVAL_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/insurance_coverage_intervals_may_not_overlap_at_binding
    """
    artwork, offering, investor, sub, custody, incumbent = setup_held_offering_with_policy()
    replacement = create_insurance_policy(offering["id"],
                                          carrier_name="Bracken Mutual Specialty",
                                          coverage_cents=95_000_000,
                                          annual_premium_cents=410_000)

    res = bind_policy(replacement["id"])
    validate_error(res, "ERR_POLICY_INTERVAL_OVERLAP", expected_status=409)

    assert validate_success(
        api_client.get_insurance_policy(replacement["id"], ISSUER), 200)["status"] == "PENDING"
    assert validate_success(
        api_client.get_insurance_policy(incumbent["id"], ISSUER), 200)["status"] == "FORCE"
    force_rows = get_success_data(api_client.list_insurance_policies(
        offering["id"], ISSUER, params={"status": "FORCE"}))
    assert len(force_rows) == 1


def test_binding_a_second_policy_is_refused_as_an_overlap_not_a_uniqueness_error(api):
    """PRD 2.9: "An insurance policy may not be bound while another policy of the same
    offering is already in force; the attempt is refused with
    `ERR_POLICY_INTERVAL_OVERLAP` because the two coverage periods would intersect."

    Design: Corner/validations/a_second_policy_binding_while_one_is_in_force_is_refused_as_an_overlap
    """
    artwork, offering, investor, sub, custody, incumbent = setup_held_offering_with_policy()
    replacement = create_insurance_policy(offering["id"],
                                          carrier_name="Bracken Mutual Specialty",
                                          coverage_cents=95_000_000,
                                          annual_premium_cents=410_000)

    res = bind_policy(replacement["id"])
    validate_error(res, "ERR_POLICY_INTERVAL_OVERLAP", expected_status=409)

    rows = get_success_data(api_client.list_insurance_policies(offering["id"], ISSUER))
    assert len(rows) == 2, "the two policies are distinct rows"
    assert {r["status"] for r in rows} == {"FORCE", "PENDING"}


def test_lapsing_the_sole_policy_is_refused(api):
    """PRD 3.6: "A policy in force may be lapsed only when another policy of the same
    offering is already on file in `FORCE` or `PENDING`; lapsing the sole policy is
    refused with `ERR_SOLE_POLICY_CANNOT_LAPSE`."

    Design: Difficulty/transitive_cascade/lapsing_the_incumbent_policy_cascades_through_every_lot_into_the_cost_ledger
    """
    artwork, offering, investor, sub, custody, policy = setup_held_offering_with_policy()
    res = lapse_policy(policy["id"])
    validate_error(res, "ERR_SOLE_POLICY_CANNOT_LAPSE", expected_status=409)
    assert validate_success(
        api_client.get_insurance_policy(policy["id"], ISSUER), 200)["status"] == "FORCE"


def test_lapsing_the_incumbent_clears_every_lot_and_the_cost_ledger(api):
    """PRD 3.6: "When the lapse is allowed, the policy becomes `LAPSED`, and every cost
    lot of the offering is recomputed in the knowledge that an offering without cover
    in force can no longer charge operating cost to investors: each lot's
    `pass_through_allowed` becomes false and its `pass_through_amount_cents` becomes
    zero, and the offering's `custody_cost_ledger_cents` is recomputed as the sum of the
    recomputed pass-through amounts across every lot of the offering."

    Design: Difficulty/transitive_cascade/lapsing_the_incumbent_policy_cascades_through_every_lot_into_the_cost_ledger
    """
    artwork, offering, investor, sub, custody, policy_a = setup_held_offering_with_policy()
    lot_1 = create_cost_lot(offering["id"], lot_type="STORAGE",
                            cost_amount_cents=6_000_000,
                            incurred_on="2027-01-10T00:00:00Z")
    lot_2 = create_cost_lot(offering["id"], lot_type="STORAGE",
                            cost_amount_cents=6_000_000,
                            incurred_on="2027-02-01T00:00:00Z")
    assert lot_1["pass_through_allowed"] is True
    policy_b = create_insurance_policy(offering["id"],
                                       carrier_name="Bracken Mutual Specialty",
                                       coverage_cents=90_000_000,
                                       annual_premium_cents=400_000)
    assert get_offering(offering["id"])["custody_cost_ledger_cents"] == 12_000_000

    validate_success(lapse_policy(policy_a["id"]), 200)

    assert validate_success(
        api_client.get_insurance_policy(policy_a["id"], ISSUER), 200)["status"] == "LAPSED"
    assert validate_success(
        api_client.get_insurance_policy(policy_b["id"], ISSUER), 200)["status"] == "PENDING"

    lots = {lot["id"]: lot for lot in get_success_data(
        api_client.list_cost_lots(offering["id"], ISSUER))}
    assert lots[lot_1["id"]]["pass_through_allowed"] is False
    assert lots[lot_1["id"]]["pass_through_amount_cents"] == 0
    assert lots[lot_2["id"]]["pass_through_allowed"] is False
    assert lots[lot_2["id"]]["pass_through_amount_cents"] == 0
    assert get_offering(offering["id"])["custody_cost_ledger_cents"] == 0

    # The replacement is on file but not yet in force, so the ledger stays at zero.
    assert validate_success(
        api_client.get_insurance_policy(policy_b["id"], ISSUER), 200)["status"] != "FORCE"


# ── Cost pass-through gates ──────────────────────────────────────────────────

def test_cost_lot_passes_through_when_every_gate_holds(api):
    """PRD 3.6: "Only when every gate passes does `pass_through_allowed` come out true
    ... When the lot is allowed, its `pass_through_amount_cents` is the
    `cost_amount_cents` multiplied by the offering's `cost_pass_through_bps` and
    divided by 10000, floored to whole cents".

        Design: Difficulty/combinatorial_formula/cost_pass_through_amount_is_gated_by_a_five_clause_chain_on_offering_state
    """
    set_clock("2026-08-01T00:00:00Z")
    _, artwork = setup_authenticated_artwork(start_clock="2026-08-01T00:00:00Z")
    validate_success(file_appraisal(artwork["id"], 90_000_000), 201)
    offering = create_offering(artwork["id"], total_shares=40_000,
                               price_per_share_cents=1_500, registration_cap_pct=6_000,
                               liquidity_ratio_bps=1_000, hold_period_days=176,
                               cost_pass_through_bps=5_000)
    investor = create_investor()
    create_screened_subscription(offering["id"], investor["id"], requested_shares=8000)
    validate_success(file_circular(offering["id"]), 200)
    validate_success(allocate_offering(offering["id"]), 200)
    custody = create_custody_record(offering["id"], **FREEUSER_CUSTODIAN)
    set_clock("2027-01-05T00:00:00Z")
    validate_success(receive_custody(custody["id"], offering["id"]), 200)
    policy = create_insurance_policy(offering["id"], coverage_cents=90_000_000)
    validate_success(bind_policy(policy["id"]), 200)

    set_clock("2027-03-01T00:00:00Z")
    lot = create_cost_lot(offering["id"], lot_type="STORAGE",
                          cost_amount_cents=6_000_000,
                          incurred_on="2027-02-01T00:00:00Z")
    assert_lot(lot)
    assert lot["pass_through_allowed"] is True
    assert lot["pass_through_amount_cents"] == 6_000_000 * 5_000 // 10_000


def test_cost_lot_outside_the_declared_types_is_refused(api):
    """PRD 2.4: "Enum membership — every enum-typed body field carries a declared
    member. Failure: `ERR_VALUE_REJECTED`". The `Lot` entity declares `lot_type` as an
    enum of `STORAGE | INSURANCE | CONSERVATION`, so an undeclared value is refused at
    the payload layer and never reaches the pass-through gate chain.

    Design: Difficulty/combinatorial_formula/cost_pass_through_amount_is_gated_by_a_five_clause_chain_on_offering_state
    """
    offering, _holder = _held_offering_for_cost_lots()
    res = api_client.create_cost_lot(
        offering["id"], {"lot_type": "BROKERAGE", "cost_amount_cents": 6_000_000,
                         "incurred_on": "2027-02-01T00:00:00Z"}, ISSUER)
    validate_error(res, "ERR_VALUE_REJECTED", expected_status=400)

    assert get_success_data(api_client.list_cost_lots(offering["id"], ISSUER)) == []


def test_cost_lot_incurred_before_the_holding_clock_passes_through_zero(api):
    """PRD 3.6: "the offering's `holding_clock_started_at` must be set, with the lot's
    `incurred_on` falling at or after it."

    Design: Difficulty/combinatorial_formula/cost_pass_through_amount_is_gated_by_a_five_clause_chain_on_offering_state
    """
    offering, _holder = _held_offering_for_cost_lots()
    lot_date_fail = create_cost_lot(
        offering["id"], lot_type="CONSERVATION", cost_amount_cents=6_000_000,
        incurred_on="2026-12-01T00:00:00Z")
    assert lot_date_fail["pass_through_allowed"] is False
    assert lot_date_fail["pass_through_amount_cents"] == 0

    lot_pass = create_cost_lot(
        offering["id"], lot_type="STORAGE", cost_amount_cents=6_000_000,
        incurred_on="2027-02-01T00:00:00Z")
    assert lot_pass["pass_through_allowed"] is True

    offering_after = get_offering(offering["id"])
    assert offering_after["custody_cost_ledger_cents"] == \
        lot_pass["pass_through_amount_cents"]


def test_the_cost_ledger_is_the_sum_of_the_recomputed_pass_through_amounts(api):
    """PRD 3.6: "Either way, the resulting pass-through amount is added to the
    offering's `custody_cost_ledger_cents`."

    Design: Difficulty/combinatorial_formula/cost_pass_through_amount_is_gated_by_a_five_clause_chain_on_offering_state
    """
    offering, _holder = _held_offering_for_cost_lots()
    lot_pass = create_cost_lot(offering["id"], lot_type="STORAGE",
                               cost_amount_cents=6_000_000,
                               incurred_on="2027-02-01T00:00:00Z")
    create_cost_lot(offering["id"], lot_type="CONSERVATION", cost_amount_cents=6_000_000,
                    incurred_on="2026-12-01T00:00:00Z")

    assert get_offering(offering["id"])["custody_cost_ledger_cents"] == \
        lot_pass["pass_through_amount_cents"]

    zero_rows = get_success_data(api_client.list_cost_lots(
        offering["id"], ISSUER, params={"pass_through_allowed": "false"}))
    assert len(zero_rows) == 1


def test_posting_an_open_transfer_order_suspends_pass_through_for_the_offering(api):
    """PRD 3.6: "no `TransferOrder` of the offering may be in `OPEN` status ... Posting
    a fresh open transfer order against an offering therefore actively suspends
    pass-through for the whole offering for as long as that order rests".

    Design: Difficulty/combinatorial_formula/cost_pass_through_amount_is_gated_by_a_five_clause_chain_on_offering_state
    """
    offering, seller = _held_offering_for_cost_lots()
    lot = create_cost_lot(offering["id"], lot_type="STORAGE",
                          cost_amount_cents=6_000_000,
                          incurred_on="2027-02-01T00:00:00Z")
    assert lot["pass_through_allowed"] is True

    from test_helpers.fixtures import create_transfer_order_payload
    from test_helpers import make_investor_headers
    validate_success(api_client.create_transfer_order(
        create_transfer_order_payload(offering["id"], seller["id"],
                                      shares=2_000, limit_price_cents=12_000_000),
        make_investor_headers(seller["id"])), 201)

    lots = {row["id"]: row for row in get_success_data(
        api_client.list_cost_lots(offering["id"], ISSUER))}
    assert lots[lot["id"]]["pass_through_allowed"] is False
    assert lots[lot["id"]]["pass_through_amount_cents"] == 0
    assert get_offering(offering["id"])["custody_cost_ledger_cents"] == 0


def test_an_open_order_fan_out_recomputes_every_lot_and_reverses_on_cancel(api):
    """PRD 3.6: "Posting a fresh open transfer order against an offering therefore
    actively suspends pass-through for the whole offering for as long as that order
    rests, which is the intent: cost is not charged to investors while the offering is
    in play on the secondary market."

    Design: Corner/cross_cutting_complexity_layers/an_open_secondary_order_recomputes_every_cost_lot_of_the_offering
    """
    offering, seller = _held_offering_for_cost_lots()
    lot_a = create_cost_lot(offering["id"], lot_type="STORAGE",
                            cost_amount_cents=6_000_000,
                            incurred_on="2027-01-10T00:00:00Z")
    lot_b = create_cost_lot(offering["id"], lot_type="INSURANCE",
                            cost_amount_cents=4_000_000,
                            incurred_on="2027-01-10T00:00:00Z")
    assert lot_a["pass_through_amount_cents"] == 3_000_000
    assert lot_b["pass_through_amount_cents"] == 2_000_000
    assert get_offering(offering["id"])["custody_cost_ledger_cents"] == 5_000_000

    from test_helpers.fixtures import create_transfer_order_payload
    from test_helpers import make_investor_headers
    order = validate_success(api_client.create_transfer_order(
        create_transfer_order_payload(offering["id"], seller["id"],
                                      shares=2_000, limit_price_cents=12_000_000),
        make_investor_headers(seller["id"])), 201)

    lots = {row["id"]: row for row in get_success_data(
        api_client.list_cost_lots(offering["id"], ISSUER))}
    assert lots[lot_a["id"]]["pass_through_amount_cents"] == 0
    assert lots[lot_b["id"]]["pass_through_amount_cents"] == 0
    assert get_offering(offering["id"])["custody_cost_ledger_cents"] == 0

    validate_success(api_client.cancel_transfer_order(
        order["id"], {}, make_investor_headers(seller["id"])), 200)

    restored = {row["id"]: row for row in get_success_data(
        api_client.list_cost_lots(offering["id"], ISSUER))}
    assert restored[lot_a["id"]]["pass_through_amount_cents"] == 3_000_000
    assert restored[lot_b["id"]]["pass_through_amount_cents"] == 2_000_000
    assert get_offering(offering["id"])["custody_cost_ledger_cents"] == 5_000_000


# ── The coverage band ────────────────────────────────────────────────────────

def _uninsured_held_offering(appraised_value_cents=90_000_000):
    """A HELD offering with a selected appraised value and no policy yet."""
    set_clock("2026-08-01T00:00:00Z")
    artist = create_artist()
    artwork = create_artwork(artist["id"], acquisition_cost_cents=60_000_000,
                             reserve_price_cents=100_000_000)
    file_verified_provenance(artwork["id"])
    file_verified_authentication(artwork["id"])
    validate_success(file_appraisal(artwork["id"], appraised_value_cents), 201)
    offering = create_offering(artwork["id"], total_shares=40_000,
                               price_per_share_cents=1_500, registration_cap_pct=6_000,
                               liquidity_ratio_bps=1_000, hold_period_days=176)
    investor = create_investor()
    create_screened_subscription(offering["id"], investor["id"], requested_shares=20_000)
    validate_success(file_circular(offering["id"]), 200)
    validate_success(allocate_offering(offering["id"]), 200)
    custody = create_custody_record(offering["id"])
    set_clock("2027-01-05T00:00:00Z")
    validate_success(receive_custody(custody["id"], offering["id"]), 200)
    set_clock("2027-03-01T00:00:00Z")
    return get_offering(offering["id"])


def test_binding_at_exactly_the_appraised_value_is_admitted(api):
    """PRD 3.6: "the coverage must be at least that value, or the bind is refused with
    `ERR_INSUFFICIENT_COVERAGE`".

    Design: Difficulty/resource_temporal_overlap/insurance_coverage_intervals_may_not_overlap_at_binding
    """
    offering = _uninsured_held_offering(appraised_value_cents=90_000_000)
    policy = create_insurance_policy(offering["id"], coverage_cents=90_000_000)

    bound = validate_success(bind_policy(policy["id"]), 200)
    assert bound["status"] == "FORCE"

    force_rows = get_success_data(api_client.list_insurance_policies(
        offering["id"], ISSUER, params={"status": "FORCE"}))
    assert [row["id"] for row in force_rows] == [policy["id"]]


def test_binding_below_the_appraised_value_is_refused(api):
    """PRD 3.6: "the coverage must be at least that value, or the bind is refused with
    `ERR_INSUFFICIENT_COVERAGE`".

    Design: Difficulty/resource_temporal_overlap/insurance_coverage_intervals_may_not_overlap_at_binding
    """
    offering = _uninsured_held_offering(appraised_value_cents=90_000_000)
    policy = create_insurance_policy(offering["id"], coverage_cents=89_999_999)

    res = bind_policy(policy["id"])
    validate_error(res, "ERR_INSUFFICIENT_COVERAGE", expected_status=422)
    assert validate_success(
        api_client.get_insurance_policy(policy["id"], ISSUER), 200)["status"] == "PENDING"


# ── helpers ──────────────────────────────────────────────────────────────────

def _held_offering_for_cost_lots():
    """A HELD offering with a started holding clock, a FORCE policy, and
    cost_pass_through_bps of 5000, so a gate-passing lot passes half its cost.

    Returns (offering, first_holder_investor).
    """
    set_clock("2026-08-01T00:00:00Z")
    artist = create_artist()
    artwork = create_artwork(artist["id"], acquisition_cost_cents=60_000_000,
                             reserve_price_cents=100_000_000)
    file_verified_provenance(artwork["id"])
    file_verified_authentication(artwork["id"])
    validate_success(file_appraisal(artwork["id"], 90_000_000), 201)
    offering = create_offering(artwork["id"], total_shares=40_000,
                               price_per_share_cents=1_500, registration_cap_pct=6_000,
                               liquidity_ratio_bps=1_000, hold_period_days=176,
                               cost_pass_through_bps=5_000)
    investor = create_investor(email="holder@x.com", legal_name="Marek Dvorak")
    create_screened_subscription(offering["id"], investor["id"], requested_shares=12_000)
    validate_success(file_circular(offering["id"]), 200)
    validate_success(allocate_offering(offering["id"]), 200)
    custody = create_custody_record(offering["id"], **FREEUSER_CUSTODIAN)
    set_clock("2027-01-05T00:00:00Z")
    validate_success(receive_custody(custody["id"], offering["id"]), 200)
    policy = create_insurance_policy(offering["id"], coverage_cents=90_000_000)
    validate_success(bind_policy(policy["id"]), 200)
    set_clock("2027-03-01T00:00:00Z")
    return get_offering(offering["id"]), investor