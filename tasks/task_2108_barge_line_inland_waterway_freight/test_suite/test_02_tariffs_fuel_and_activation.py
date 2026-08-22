"""Publishing rates, posting the diesel index, and the road to an ACTIVE contract."""
from test_helpers import (
    ApiErrorId,
    RATE_AUTHORITY_USER_ID,
    activate_contract,
    assert_same_instant,
    book_contract,
    create_commodity,
    create_contract,
    create_effective_tariff,
    create_fuel_posting,
    create_river_reading,
    create_shipper,
    draft_tariff,
    effectuate_tariff,
    file_tariff,
    make_contract_manager_headers,
    make_rate_authority_headers,
    read_breakdown,
    read_contract,
    read_shipper,
    read_tariff,
    seal_tow,
    set_clock,
    setup_grain_movement,
    setup_grain_reference,
    setup_invoiced_movement,
    validate_error,
    validate_paginated,
    validate_success,
)

BILLER = make_contract_manager_headers()
RATE = make_rate_authority_headers()


def test_supersession_truncates_the_incumbent_window(api):
    """PRD §3.2: "When `supersedes_tariff_filing_id` is set, effectuation also
    drives the named filing from `EFFECTIVE` to `SUPERSEDED` and truncates that
    older filing's `effective_to` to the new filing's `effective_from`, so the
    two windows abut instead of overlapping."
    PRD §3.2: "Filings may be listed narrowed by `status`, by `commodity_group`,
    or by `supersedes_tariff_filing_id`, the last of which finds the successors
    of a given filing."

    Design: Corner/state_machines/tariff_filing_supersession_truncates_the_incumbent_window
    """
    incumbent = create_effective_tariff(tariff_code="T-GRAIN-2026")
    successor = draft_tariff(
        tariff_code="T-GRAIN-2026B", base_rate_cents_per_ton_mile=1.4,
        min_charge_cents=260_000, demurrage_rate_cents_per_hour=35_000,
        effective_from="2026-10-01T00:00:00Z", effective_to="2027-03-31T23:59:59Z",
        supersedes_tariff_filing_id=incumbent["id"])
    file_tariff(successor["id"])

    effectuated = validate_success(
        api.effectuate_tariff_filing(successor["id"], RATE))
    assert effectuated["status"] == "EFFECTIVE"
    assert effectuated["effectuated_by_user_id"] == RATE_AUTHORITY_USER_ID, (
        "the acting operator is written to effectuated_by_user_id")

    displaced = read_tariff(incumbent["id"])
    assert displaced["status"] == "SUPERSEDED", (
        f"the incumbent must be driven to SUPERSEDED, got {displaced['status']}")
    assert_same_instant(displaced["effective_to"], "2026-10-01T00:00:00Z",
                        "the incumbent's truncated effective_to")

    rows, meta = validate_paginated(api.list_tariff_filings(
        BILLER, params={"supersedes_tariff_filing_id": incumbent["id"]}))
    assert meta["total_count"] == 1, "the successor filter finds exactly one filing"
    assert rows[0]["id"] == successor["id"]


def test_effectuate_from_draft_is_refused(api):
    """PRD §3.2: "The filing must stand in `FILED`, or the call is refused with
    `ERR_TARIFF_FILING_INVALID_STATE`."
    PRD §3.2: "A new filing is born in status `DRAFT`, with `filed_by_user_id`
    and `effectuated_by_user_id` both null."

    Design: Corner/state_machines/effectuate_from_draft_returns_tariff_filing_invalid_state
    """
    filing = draft_tariff(tariff_code="T-GRAIN-DRAFT")
    validate_error(api.effectuate_tariff_filing(filing["id"], RATE),
                   ApiErrorId.ERR_TARIFF_FILING_INVALID_STATE.value)
    stored = read_tariff(filing["id"])
    assert stored["status"] == "DRAFT", "the refused call leaves the filing DRAFT"
    assert stored.get("filed_by_user_id") is None
    assert stored.get("effectuated_by_user_id") is None


def test_second_overlapping_grain_tariff_is_refused(api):
    """PRD §3.2: "And no *other* filing for the same `commodity_group` that
    already stands in `EFFECTIVE` may have an effective window overlapping this
    one's window, with a single exception: the filing named by
    `supersedes_tariff_filing_id` is excluded from that overlap test, since it
    is precisely the filing being displaced."
    PRD §3.2: "An overlap that is not excused this way is refused with
    `ERR_TARIFF_WINDOW_OVERLAP`."

    Design: Corner/validations/effectuating_a_second_overlapping_grain_tariff_returns_window_overlap
    """
    incumbent = create_effective_tariff(tariff_code="T-GRAIN-A")
    challenger = draft_tariff(
        tariff_code="T-GRAIN-B", base_rate_cents_per_ton_mile=1.4,
        effective_from="2026-09-01T00:00:00Z", effective_to="2027-01-31T23:59:59Z")
    file_tariff(challenger["id"])

    validate_error(api.effectuate_tariff_filing(challenger["id"], RATE),
                   ApiErrorId.ERR_TARIFF_WINDOW_OVERLAP.value)
    stored = read_tariff(challenger["id"])
    assert stored["status"] == "FILED", "the refused challenger stays FILED"
    assert stored.get("effectuated_by_user_id") is None
    incumbent_now = read_tariff(incumbent["id"])
    assert incumbent_now["status"] == "EFFECTIVE"
    assert_same_instant(incumbent_now["effective_to"], "2026-12-31T23:59:59Z",
                        "the incumbent's window is untouched")


def test_fuel_tier_selected_at_the_threshold_and_one_cent_below(api):
    """PRD §3.3: "The `pinned_fuel_price_cents_per_gallon` records the diesel
    price from the controlling posting, chosen by a pinned selector: among the
    postings whose `posting_date` is at or before the logical clock's calendar
    date, order by `posting_date` descending with ties broken by `created_at`
    descending and take the first."
    PRD §3.3: "The `pinned_fuel_surcharge_pct` records the percentage read from
    the pinned filing's `fuel_surcharge_table` at that price: the applicable
    tier is the **highest** tier whose `threshold_cents_per_gallon` is less than
    or equal to the pinned price, and a price exactly equal to a threshold
    selects that tier rather than the one below it."

    Design: Corner/calculations/fuel_tier_selected_at_the_exact_threshold_and_one_cent_below
    """
    set_clock("2026-08-02T00:00:00Z")
    corn = create_commodity(code="CORN", commodity_group="GRAIN")
    tariff = create_effective_tariff()
    create_fuel_posting(posting_date="2026-08-03", diesel_price_cents_per_gallon=299)
    create_fuel_posting(posting_date="2026-08-06", diesel_price_cents_per_gallon=300)
    shipper = create_shipper()

    set_clock("2026-08-05T00:00:00Z")
    contract_a = create_contract(shipper["id"], corn["id"], contracted_tons=1700)
    book_contract(contract_a["id"])
    contract_b = create_contract(shipper["id"], corn["id"], contracted_tons=1700)
    book_contract(contract_b["id"])

    activated_a = activate_contract(contract_a["id"])
    assert activated_a["pinned_fuel_price_cents_per_gallon"] == 299, (
        "the 2026-08-06 posting is still in the future and must be excluded")
    assert float(activated_a["pinned_fuel_surcharge_pct"]) == 0.0, (
        "299 cents falls in the 200-cent tier at 0.000")

    set_clock("2026-08-07T00:00:00Z")
    activated_b = activate_contract(contract_b["id"])
    assert activated_b["pinned_fuel_price_cents_per_gallon"] == 300, (
        "the newest posting at or before the clock controls")
    assert float(activated_b["pinned_fuel_surcharge_pct"]) == 0.045, (
        "a price exactly on the 300-cent threshold selects that tier")
    assert activated_a["pinned_tariff_filing_id"] == tariff["id"]
    assert activated_b["pinned_tariff_filing_id"] == tariff["id"]
    assert float(activated_a["distance_miles"]) == 400.0
    assert float(activated_b["distance_miles"]) == 400.0


def test_activation_guards_reject_missing_tariff_then_missing_fuel_posting(api):
    """PRD §3.3: "It moves `movement_status` from `BOOKED` to `ACTIVE` and
    requires, in the ladder order of §2.7, that the contract stands in `BOOKED`;
    that the owning shipper's `status` is `ACTIVE` rather than `CREDIT_HOLD`,
    failing which the call is refused with `ERR_SHIPPER_ON_CREDIT_HOLD`; that an
    `EFFECTIVE` tariff filing for the contract's commodity group covers the
    current logical clock, meaning its `effective_from` is at or before the
    clock and its `effective_to` is at or after it, failing which the call is
    refused with `ERR_NO_EFFECTIVE_TARIFF`; that at least one fuel index posting
    exists whose `posting_date` is at or before the logical clock's calendar
    date, failing which the call is refused with `ERR_NO_FUEL_INDEX_POSTING`;
    and finally that the shipper has credit headroom."

    Design: Corner/validations/activation_guards_reject_missing_tariff_then_missing_fuel_posting
    """
    set_clock("2026-08-05T00:00:00Z")
    corn = create_commodity(code="CORN", commodity_group="GRAIN")
    filing = draft_tariff()
    file_tariff(filing["id"])
    shipper = create_shipper()
    contract = create_contract(shipper["id"], corn["id"], contracted_tons=1700)
    book_contract(contract["id"])

    validate_error(api.activate_freight_contract(contract["id"], BILLER),
                   ApiErrorId.ERR_NO_EFFECTIVE_TARIFF.value)
    assert read_contract(contract["id"])["movement_status"] == "BOOKED"

    effectuate_tariff(filing["id"])
    validate_error(api.activate_freight_contract(contract["id"], BILLER),
                   ApiErrorId.ERR_NO_FUEL_INDEX_POSTING.value)
    assert read_contract(contract["id"])["movement_status"] == "BOOKED"

    create_fuel_posting(posting_date="2026-08-03", diesel_price_cents_per_gallon=300)
    activated = validate_success(api.activate_freight_contract(contract["id"], BILLER))
    assert activated["movement_status"] == "ACTIVE"
    assert activated["pinned_tariff_filing_id"] == filing["id"]
    assert activated["pinned_fuel_price_cents_per_gallon"] == 300
    assert float(activated["pinned_fuel_surcharge_pct"]) == 0.045


def test_credit_projection_boundary_is_inclusive_at_the_limit(api):
    """PRD §3.3: "Then the projected charge is `contracted_tons` multiplied by
    `distance_miles` multiplied by the pinned filing's
    `base_rate_cents_per_ton_mile`, rounded half up to whole cents."
    PRD §3.3: "If the shipper's current `outstanding_balance_cents` plus that
    projected charge exceeds the shipper's `credit_limit_cents`, activation is
    refused with `ERR_SHIPPER_CREDIT_EXCEEDED` (HTTP 402); the comparison is
    inclusive, so a projection that lands exactly on the credit limit passes."

    Design: Corner/calculations/contract_credit_projection_boundary_is_inclusive_at_the_limit
    """
    set_clock("2026-08-02T00:00:00Z")
    corn = create_commodity(code="CORN", commodity_group="GRAIN")
    create_effective_tariff()
    create_fuel_posting(posting_date="2026-08-03", diesel_price_cents_per_gallon=300)
    exact = create_shipper(name="Exact Limit Co", credit_limit_cents=1_683_408)
    short = create_shipper(name="One Cent Short Co", credit_limit_cents=1_683_407)

    set_clock("2026-08-05T00:00:00Z")
    contract_ok = create_contract(exact["id"], corn["id"], contracted_tons=3400)
    book_contract(contract_ok["id"])
    contract_short = create_contract(short["id"], corn["id"], contracted_tons=3400)
    book_contract(contract_short["id"])

    activated = validate_success(api.activate_freight_contract(contract_ok["id"], BILLER))
    assert activated["movement_status"] == "ACTIVE", (
        "a 1683408-cent projection lands exactly on the limit and passes")

    validate_error(api.activate_freight_contract(contract_short["id"], BILLER),
                   ApiErrorId.ERR_SHIPPER_CREDIT_EXCEEDED.value)
    refused = read_contract(contract_short["id"])
    assert refused["movement_status"] == "BOOKED"
    assert read_shipper(exact["id"])["outstanding_balance_cents"] == 0, (
        "activation projects the charge but never posts it to the balance")


def test_shipper_on_credit_hold_cannot_activate_a_further_contract(api):
    """PRD §3.8: "It then increases the shipper's `outstanding_balance_cents` by
    `total_cents`, and if that balance now exceeds the shipper's
    `credit_limit_cents` the shipper moves `status` `ACTIVE → CREDIT_HOLD`,
    which will block that customer's next contract activation until the balance
    comes down."
    PRD §3.3: "that the owning shipper's `status` is `ACTIVE` rather than
    `CREDIT_HOLD`, failing which the call is refused with
    `ERR_SHIPPER_ON_CREDIT_HOLD`"

    Design: Corner/validations/shipper_on_credit_hold_cannot_activate_a_further_contract
    """
    movement = setup_invoiced_movement(
        ref_kwargs={"credit_limit_cents": 1_100_000, "shipper_name": "Thin Credit Co"})
    shipper = read_shipper(movement["shipper_id"])
    assert shipper["status"] == "CREDIT_HOLD", (
        "the 1307936-cent bill pushes the balance past the 1100000-cent limit")
    assert shipper["outstanding_balance_cents"] == 1_307_936

    second = create_contract(
        movement["shipper_id"], movement["commodity_id"], contracted_tons=100)
    book_contract(second["id"])
    validate_error(api.activate_freight_contract(second["id"], BILLER),
                   ApiErrorId.ERR_SHIPPER_ON_CREDIT_HOLD.value)
    assert read_contract(second["id"])["movement_status"] == "BOOKED"


def test_pinned_tariff_survives_supersession_by_a_newer_filing(api):
    """PRD §3.2: "Crucially, freight contracts that already pinned the
    superseded filing keep pointing at it — pinning is never re-resolved, and a
    later rate change can never retroactively re-price a contract that was
    already activated."
    PRD §3.3: "The `pinned_tariff_filing_id` records the `EFFECTIVE` filing that
    satisfied the tariff test, and every later charge computation reads its
    rates from that filing and no other."

    Design: Corner/cross_cutting_layers/pinned_tariff_survives_supersession_by_a_newer_filing
    """
    movement = setup_grain_movement(loads=(1700,), stage="UNDERWAY")
    incumbent = movement["tariff"]

    successor = draft_tariff(
        tariff_code="T-GRAIN-2026B", base_rate_cents_per_ton_mile=1.4,
        demurrage_rate_cents_per_hour=35_000,
        effective_from="2026-09-01T00:00:00Z", effective_to="2027-03-31T23:59:59Z",
        supersedes_tariff_filing_id=incumbent["id"])
    file_tariff(successor["id"])
    effectuate_tariff(successor["id"])

    assert read_tariff(incumbent["id"])["status"] == "SUPERSEDED"
    assert read_tariff(successor["id"])["status"] == "EFFECTIVE"

    contract = read_contract(movement["contract_id"])
    assert contract["pinned_tariff_filing_id"] == incumbent["id"], (
        "pinning is never re-resolved")
    assert float(contract["pinned_fuel_surcharge_pct"]) == 0.045

    breakdown = read_breakdown(movement["contract_id"], "PROVISIONAL")
    assert breakdown["linehaul_cents"] == 841_704, (
        f"the 1.2378-cent pinned rate still prices the line, "
        f"got {breakdown['linehaul_cents']}")
    assert breakdown["fuel_surcharge_cents"] == 37_877

    rows, meta = validate_paginated(api.list_freight_contracts(
        BILLER, params={"pinned_tariff_filing_id": incumbent["id"]}))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == movement["contract_id"]


def test_logical_clock_defaults_to_2026_08_01_before_any_set_call(api):
    """PRD §2.5: "Before any client repositions it, the logical clock reads
    exactly `2026-08-01T00:00:00Z`, and it never falls back to real wall-clock
    time under any circumstance."
    PRD §3.2: "The candidates are the readings whose `gauge_station` equals the
    tow's `controlling_gauge_station` and whose `reading_at` is at or before the
    current logical clock; readings dated in the future are excluded entirely."

    Design: Corner/endpoints/logical_clock_defaults_to_2026_08_01_before_any_set_call
    """
    reference = setup_grain_reference(
        reference_clock=None, activation_clock=None,
        effective_from="2026-07-01T00:00:00Z",
        posting_date="2026-07-27", diesel_price=420,
        reading_at="2026-08-01T00:00:00Z", stage_feet=18.0)
    create_river_reading(gauge_station="MEMPHIS",
                         reading_at="2026-08-02T00:00:00Z", stage_feet=7.5)

    movement = setup_grain_movement(
        loads=(1700,), stage="BUILDING", reference=reference,
        tow_kwargs={"towboat_name": "M/V Papa"})

    contract = read_contract(movement["contract_id"])
    assert contract["pinned_fuel_price_cents_per_gallon"] == 420, (
        "the 2026-07-27 posting is the only one at or before the default clock")
    assert float(contract["pinned_fuel_surcharge_pct"]) == 0.09, (
        "420 cents selects the 400-cent tier")

    tow = seal_tow(movement["tow_id"])
    assert tow["draft_restriction_band"] == "NORMAL", (
        "the 2026-08-02 reading of 7.5 feet is in the future and never controls")
    assert float(tow["allowed_draft_feet"]) == 12.0
    assert float(tow["max_draft_feet"]) == 9.83
    assert tow["status"] == "SEALED"
