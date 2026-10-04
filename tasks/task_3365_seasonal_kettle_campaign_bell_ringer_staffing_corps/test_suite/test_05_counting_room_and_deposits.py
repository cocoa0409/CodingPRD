"""Counting room controls: variance, handling fees, deposits and reconciliation."""
from test_helpers import (
    ApiErrorId,
    activate_kettle_location_ok,
    close_kettle_location,
    count_collections_for_location,
    create_collection,
    create_kettle_location,
    deposit_collection_ok,
    get_collection,
    reconcile_collection,
    recount_collection,
    setup_kettle_network,
    validate_error,
    validate_success,
    verify_collection,
    verify_collection_ok,
)

TELLER_COUNTS = {"coin_cents": 12345, "currency_cents": 50000, "check_cents": 10000}


def test_provisional_variance_at_verify(api, counting_room_teller_headers):
    """PRD §3.4: "the platform computes the provisional variance as the counted
    total minus the ringer's declared slip amount."
    PRD §3.4: "When the absolute value of that variance is 500 cents or less,
    the collection moves to `VERIFIED`."

    Design: Difficulty/dual_variant_calc/collection_variance_provisional_vs_final_variant
    """
    network = setup_kettle_network()
    collection = create_collection(network.location["id"], "2026-11-14T18:00:00Z",
                                   declared_cents=72000, **TELLER_COUNTS)

    verified = verify_collection_ok(collection["id"])
    assert verified["counted_total_cents"] == 72345
    assert verified["handling_fee_cents"] == 384
    assert verified["variance_cents"] == 345, "72345 counted less the 72000 declared slip"
    assert verified["deposit_status"] == "VERIFIED"


def test_final_variance_at_reconcile_differs_from_provisional(api):
    """PRD §3.4: "its final `variance_cents` is computed as the bank-confirmed
    deposit minus the counted total net of the handling fee".
    PRD §3.4: "The two variance figures are deliberately different numbers
    computed from the same row."

    Design: Difficulty/dual_variant_calc/collection_variance_provisional_vs_final_variant
    """
    network = setup_kettle_network()
    collection = create_collection(network.location["id"], "2026-11-14T18:00:00Z",
                                   declared_cents=72000, **TELLER_COUNTS)
    verified = verify_collection_ok(collection["id"])
    provisional_variance = verified["variance_cents"]
    assert provisional_variance == 345

    deposit_collection_ok(collection["id"], 71961)
    resp = reconcile_collection(collection["id"], matched=True, bank_confirmed_cents=71961)
    reconciled = validate_success(resp)

    assert reconciled["deposit_status"] == "RECONCILED"
    assert reconciled["variance_cents"] == 0, "71961 deposited against 72345 net of 384"
    assert reconciled["variance_cents"] != provisional_variance


def test_handling_fee_floors_each_denomination_before_summing(api):
    """PRD §2.8: "each component is floored to a whole cent on its own, and only
    then are the components summed. The sum itself is never re-rounded."
    PRD §3.4: "The `handling_fee_cents` is the sum of those six separately
    floored components, and that sum is not rounded again."

    Design: Difficulty/combinatorial_formula/deposit_fee_per_denomination_rounding_order
    """
    network = setup_kettle_network()
    collection = create_collection(network.location["id"], "2026-11-14T18:00:00Z",
                                   declared_cents=72000, **TELLER_COUNTS)

    verified = verify_collection_ok(collection["id"])
    assert verified["handling_fee_cents"] == 384, "per-denomination floor then sum"
    assert verified["handling_fee_cents"] != 386, "summing first then flooring is not the rule"


def test_counted_total_and_verified_status_at_verify(api):
    """PRD §3.4: "The collection's `counted_total_cents` is the sum of the coin,
    currency and cheque counts".
    PRD §3.4: "Both paths recompute `counted_total_cents`, recompute
    `handling_fee_cents`, and record the provisional `variance_cents`".

    Design: Difficulty/combinatorial_formula/deposit_fee_per_denomination_rounding_order
    """
    network = setup_kettle_network()
    collection = create_collection(network.location["id"], "2026-11-14T18:00:00Z",
                                   declared_cents=72000, **TELLER_COUNTS)

    verified = verify_collection_ok(collection["id"])
    assert verified["counted_total_cents"] == 72345
    assert verified["variance_cents"] == 345
    assert verified["deposit_status"] == "VERIFIED"


def test_variance_beyond_tolerance_moves_collection_to_hold(api):
    """PRD §3.4: "When it is greater than 500 cents, the collection moves to
    `VARIANCE_HOLD` instead — the money is not rejected, it is quarantined".

    Design: Difficulty/non_linear_state_machine/collection_cycle_variance_hold_recount_back_to_submitted
    """
    network = setup_kettle_network()
    collection = create_collection(network.location["id"], "2026-11-14T18:00:00Z",
                                   declared_cents=70000, **TELLER_COUNTS)

    held = verify_collection_ok(collection["id"])
    assert held["deposit_status"] == "VARIANCE_HOLD"
    assert held["variance_cents"] == 2345, "72345 counted less the 70000 declared slip"


def test_recount_returns_collection_to_submitted_then_verifies(api):
    """PRD §3.4: "The recount route accepts fresh `coin_cents`, `currency_cents`
    and `check_cents` values, each of which must be zero or greater, replaces
    the stored counts with them, and returns the collection to `SUBMITTED` so
    that it can be verified again from scratch."

    Design: Difficulty/non_linear_state_machine/collection_cycle_variance_hold_recount_back_to_submitted
    """
    network = setup_kettle_network()
    collection = create_collection(network.location["id"], "2026-11-14T18:00:00Z",
                                   declared_cents=70000, **TELLER_COUNTS)
    verify_collection_ok(collection["id"])

    recounted = recount_collection(collection["id"], coin_cents=12345,
                                   currency_cents=47655, check_cents=10000)
    assert recounted["deposit_status"] == "SUBMITTED"
    assert recounted["counted_total_cents"] == 70000

    reverified = verify_collection_ok(collection["id"])
    assert reverified["deposit_status"] == "VERIFIED"
    assert reverified["variance_cents"] == 0


def test_collection_create_reports_location_state_before_placement_window(api,
                                                                          counting_room_teller_headers):
    """PRD §2.9: "The order matters because when two checks would both fail,
    only the earlier one is reported".
    PRD §2.9: "The kettle location referenced by the request is `ACTIVE`;
    otherwise `ERR_LOCATION_NOT_ACTIVE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_temporal_on_collection_create
    """
    network = setup_kettle_network()
    location_b = create_kettle_location(network.host_site["id"], network.campaign["id"],
                                        location_code="K-114-B", placement="INDOOR")
    location_b = activate_kettle_location_ok(location_b["id"])

    closed = close_kettle_location(network.location["id"])
    assert closed["status"] == "CLOSED"

    # Both the CLOSED location and the out-of-window collected_on fail here,
    # so the state rule must be the one reported.
    resp = api.create_collection(
        {"kettle_location_id": network.location["id"],
         "collected_on": "2026-12-30T18:00:00Z", "declared_cents": 10000,
         "coin_cents": 10000, "currency_cents": 0, "check_cents": 0},
        counting_room_teller_headers)
    validate_error(resp, ApiErrorId.ERR_LOCATION_NOT_ACTIVE)
    assert count_collections_for_location(network.location["id"]) == 0
    assert location_b["status"] == "ACTIVE"


def test_collection_create_reports_placement_window_when_state_passes(api,
                                                                      counting_room_teller_headers):
    """PRD §3.4: "The `collected_on` date must fall inside the kettle location's
    placement window, and a collection recorded for a date outside that window —
    even a single instant outside it — is refused with
    `ERR_COLLECTION_OUTSIDE_PLACEMENT_WINDOW` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_temporal_on_collection_create
    """
    network = setup_kettle_network()
    resp = api.create_collection(
        {"kettle_location_id": network.location["id"],
         "collected_on": "2026-12-30T18:00:00Z", "declared_cents": 10000,
         "coin_cents": 10000, "currency_cents": 0, "check_cents": 0},
        counting_room_teller_headers)
    validate_error(resp, ApiErrorId.ERR_COLLECTION_OUTSIDE_PLACEMENT_WINDOW)
    assert count_collections_for_location(network.location["id"]) == 0


def test_collection_verify_twice_rejected(api):
    """PRD §2.9: "The target resource is in a state that permits the requested
    operation; otherwise `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."
    PRD §3.4: "When the absolute value of that variance is 500 cents or less,
    the collection moves to `VERIFIED`."

    Design: Corner/state_machines/collection_verify_twice_rejected
    """
    network = setup_kettle_network()
    collection = create_collection(network.location["id"], "2026-11-14T18:00:00Z",
                                   declared_cents=70000, currency_cents=70000)

    first = verify_collection_ok(collection["id"])
    assert first["deposit_status"] == "VERIFIED"

    replay = verify_collection(collection["id"], expected_version=first["version"])
    validate_error(replay, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    after = get_collection(collection["id"])
    assert after["deposit_status"] == "VERIFIED"
    assert after["version"] == first["version"], "the rejected replay must not advance the version"
