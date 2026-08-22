"""The crush pad: weigh-in, sampling, acceptance, brix-adjusted yield and the
marginally-tiered crush fee."""
import pytest

from test_helpers import (
    ApiErrorId,
    accept_intake,
    assert_harvest_intake,
    create_harvest_intake_payload,
    new_accepted_intake,
    sample_intake,
    set_clock,
    setup_active_contract,
    validate_error,
    validate_paginated,
    validate_success,
    weigh_in,
)

# 14000 - 4000 = 10000 lb = 5.0 tons
FIVE_TON_LOAD = {"gross_weight_lbs": 14000, "tare_weight_lbs": 4000}


def test_weigh_in_derives_net_weight_and_ignores_server_managed_fields(
    api, cellar_supervisor_headers
):
    """PRD 3.3: "The intake is stored in `WEIGHED` with `net_weight_lbs` set to
    the gross weight less the tare weight, `received_at` stamped from the
    logical clock, and `brix`, `ph` and `rejection_reason` all null, `lot_id`
    null, and `estimated_gallons` and `crush_fee_cents` both at 0."
    PRD 2.5: "Unknown body fields are ignored rather than rejected, and fields
    that the server itself derives or stamps are likewise ignored when a client
    supplies them."

    Design: Corner/entities/corner_harvest_intake_net_weight_computed_client_value_input_ignored
    """
    scenario = setup_active_contract()

    payload = create_harvest_intake_payload(
        scenario["contract"]["id"],
        net_weight_lbs=99999,
        estimated_gallons=5000,
        status="ACCEPTED",
    )
    data = validate_success(
        api.create_harvest_intake(payload, cellar_supervisor_headers), 201
    )

    assert_harvest_intake(data)
    assert data["net_weight_lbs"] == pytest.approx(38000, abs=0.01), (
        f"net_weight_lbs must be 42000 - 4000, got {data['net_weight_lbs']}"
    )
    assert data["status"] == "WEIGHED", (
        f"a client-supplied status is ignored, got {data['status']}"
    )
    assert data["estimated_gallons"] == pytest.approx(0, abs=0.01)
    assert data["crush_fee_cents"] == 0
    assert data["brix"] is None
    assert data["ph"] is None


def test_a_load_can_be_rejected_before_the_lab_samples_it(api, cellar_supervisor_headers,
                                                          facility_admin_headers):
    """PRD 3.3: "A load may instead be rejected outright from either `WEIGHED`
    or `SAMPLED`, which stores the supplied `rejection_reason`, sets the status
    to `REJECTED`, and moves no contract counter whatsoever."

    Design: Corner/state_machines/corner_intake_reject_straight_from_weighed
    """
    scenario = setup_active_contract()
    intake = weigh_in(
        scenario["contract"]["id"],
        "DT-1001",
        varietal="ZINFANDEL",
        appellation="HOWELL_MOUNTAIN",
        block_code="Z01",
        gross_weight_lbs=20000,
        tare_weight_lbs=4000,
    )

    data = validate_success(
        api.harvest_intake_transition(
            intake["id"],
            {
                "action": "REJECT",
                "rejection_reason": "Sour rot above tolerance on the crush pad.",
            },
            cellar_supervisor_headers,
        )
    )

    assert data["status"] == "REJECTED"
    assert data["rejection_reason"] == "Sour rot above tolerance on the crush pad."
    assert data["brix"] is None
    assert data["estimated_gallons"] == pytest.approx(0, abs=0.01)
    assert data["crush_fee_cents"] == 0

    contract = validate_success(
        api.get_contract(scenario["contract"]["id"], facility_admin_headers)
    )
    assert contract["tons_received"] == pytest.approx(0.0000, abs=0.0001)
    assert contract["billed_total_cents"] == 0


def test_second_accept_on_an_accepted_load_never_double_posts_the_crush_fee(
    api, cellar_supervisor_headers, facility_admin_headers
):
    """PRD 2.5: "The requested action must be a transition declared out of the
    target's current state. Repeating a trigger that has already fired, and any
    action attempted out of a terminal state, both fail here with
    `ERR_INVALID_STATE` (409)."
    PRD 3.3: "Acceptance then posts both figures. The contract's `tons_received`
    advances by this load's net weight divided by 2000, its `billed_total_cents`
    advances by the computed `crush_fee_cents`, and its `version` increments by
    1."

    Design: Corner/state_machines/corner_intake_accept_twice_rejected_as_invalid_state
    """
    scenario = setup_active_contract()
    intake = new_accepted_intake(scenario["contract"]["id"], "DT-1001")

    response = api.harvest_intake_transition(
        intake["id"], {"action": "ACCEPT"}, cellar_supervisor_headers
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

    contract = validate_success(
        api.get_contract(scenario["contract"]["id"], facility_admin_headers)
    )
    assert contract["tons_received"] == pytest.approx(19.0000, abs=0.0001), (
        "the repeated ACCEPT must not advance the tonnage accumulator twice"
    )
    assert contract["billed_total_cents"] == 950000, (
        f"expected 950000 cents, got {contract['billed_total_cents']}"
    )

    stored = validate_success(
        api.get_harvest_intake(intake["id"], facility_admin_headers)
    )
    assert stored["crush_fee_cents"] == 950000


def test_low_brix_bonus_applies_at_exactly_twenty_two_degrees(
    api, cellar_supervisor_headers
):
    """PRD 3.3: "Otherwise, when `brix` is at most 22.00, the yield per ton is
    increased by 3.0 gallons."
    PRD 3.3: "Between those bounds — above 22.00 and below 25.00 — there is no
    adjustment at all."

    Design: Corner/calculations/corner_intake_yield_low_brix_bonus_at_exactly_22_00
    """
    scenario = setup_active_contract()
    contract_id = scenario["contract"]["id"]

    low = weigh_in(contract_id, "DT-D1", varietal="CHARDONNAY",
                   appellation="NAPA_VALLEY", block_code="C01", **FIVE_TON_LOAD)
    sample_intake(low["id"], 22.00, 3.20)
    mid = weigh_in(contract_id, "DT-D2", varietal="CHARDONNAY",
                   appellation="NAPA_VALLEY", block_code="C02", **FIVE_TON_LOAD)
    sample_intake(mid["id"], 22.01, 3.21)

    low_accepted = validate_success(
        api.harvest_intake_transition(low["id"], {"action": "ACCEPT"}, cellar_supervisor_headers)
    )
    mid_accepted = validate_success(
        api.harvest_intake_transition(mid["id"], {"action": "ACCEPT"}, cellar_supervisor_headers)
    )

    assert low_accepted["estimated_gallons"] == pytest.approx(840.00, abs=0.01), (
        f"5.0 tons at exactly 22.00 Brix earns the bonus, got "
        f"{low_accepted['estimated_gallons']}"
    )
    assert mid_accepted["estimated_gallons"] == pytest.approx(825.00, abs=0.01), (
        f"5.0 tons at 22.01 Brix earns no bonus, got "
        f"{mid_accepted['estimated_gallons']}"
    )
    assert low_accepted["estimated_gallons"] - mid_accepted["estimated_gallons"] == (
        pytest.approx(15.00, abs=0.01)
    )


def test_a_single_load_spanning_all_three_tonnage_bands_prices_marginally(
    api, cellar_supervisor_headers, facility_admin_headers
):
    """PRD 3.3: "The contract's tonnage runs through three bands: the first 25
    tons of the harvest year price at the full `crush_rate_cents_per_ton`, the
    tons from 25 up to 75 price at nine tenths of that rate, and every ton
    beyond 75 prices at eight tenths of it."
    PRD 3.3: "The second figure is `crush_fee_cents`, and it is priced
    **marginally** against the contract's running tonnage rather than at a
    single average rate."

    Design: Corner/calculations/corner_crush_fee_reaches_tier_three_beyond_75_tons
    """
    scenario = setup_active_contract(
        client_overrides={
            "name": "Pritchard Hill Partners",
            "ttb_permit_number": "BW-CA-15002",
            "contact_email": "cellar@pritchard.example",
        },
        tank_gallons_entitled=40000,
        crush_rate_cents_per_ton=45000,
    )
    contract_id = scenario["contract"]["id"]
    intake = weigh_in(
        contract_id, "DT-E1", varietal="ZINFANDEL", appellation="NAPA_VALLEY",
        block_code="Z09", gross_weight_lbs=156000, tare_weight_lbs=4000,
    )
    sample_intake(intake["id"], 23.50, 3.60)

    data = validate_success(
        api.harvest_intake_transition(
            intake["id"], {"action": "ACCEPT"}, cellar_supervisor_headers
        )
    )

    assert data["crush_fee_cents"] == 3186000, (
        f"25 t at 45000 + 50 t at 40500 + 1 t at 36000 is 3186000 cents, got "
        f"{data['crush_fee_cents']}"
    )
    assert data["estimated_gallons"] == pytest.approx(12540.00, abs=0.01)

    contract = validate_success(api.get_contract(contract_id, facility_admin_headers))
    assert contract["tons_received"] == pytest.approx(76.0000, abs=0.0001)
    assert contract["billed_total_cents"] == 3186000


def test_acceptance_outside_the_contract_effective_window_is_refused(
    api, cellar_supervisor_headers, facility_admin_headers
):
    """PRD 3.3: "It requires the governing contract to be `ACTIVE`, failing
    otherwise with `ERR_CONTRACT_NOT_ACTIVE`, and it requires the load's
    `received_at` to fall inside the contract's effective window — at or after
    `effective_from` and strictly before `effective_to` — failing otherwise with
    `ERR_OUTSIDE_CONTRACT_WINDOW`."

    Design: Corner/validations/corner_intake_accept_outside_contract_window_rejected
    """
    scenario = setup_active_contract(
        clock="2026-08-15T00:00:00Z", effective_to="2026-09-01T00:00:00Z"
    )
    set_clock("2026-09-15T00:00:00Z")
    intake = weigh_in(scenario["contract"]["id"], "DT-P1", **FIVE_TON_LOAD)
    assert intake["received_at"] == "2026-09-15T00:00:00.000Z"
    sample_intake(intake["id"], 23.50, 3.62)

    response = api.harvest_intake_transition(
        intake["id"], {"action": "ACCEPT"}, cellar_supervisor_headers
    )
    validate_error(response, ApiErrorId.ERR_OUTSIDE_CONTRACT_WINDOW.value, 422)

    contract = validate_success(
        api.get_contract(scenario["contract"]["id"], facility_admin_headers)
    )
    assert contract["status"] == "ACTIVE"
    assert contract["tons_received"] == pytest.approx(0.0000, abs=0.0001)

    stored = validate_success(api.get_harvest_intake(intake["id"], facility_admin_headers))
    assert stored["status"] == "SAMPLED"
    assert stored["crush_fee_cents"] == 0


def test_a_repeated_delivery_ticket_is_refused_facility_wide(
    api, cellar_supervisor_headers
):
    """PRD 3.3: "Delivery tickets are unique facility-wide; a repeated one is
    refused with `ERR_DUPLICATE_DELIVERY_TICKET`."

    Design: Corner/validations/corner_duplicate_delivery_ticket_rejected
    """
    scenario = setup_active_contract()
    contract_id = scenario["contract"]["id"]
    first = weigh_in(contract_id, "DT-R1", **FIVE_TON_LOAD)

    response = api.create_harvest_intake(
        create_harvest_intake_payload(
            contract_id,
            delivery_ticket="DT-R1",
            varietal="MERLOT",
            appellation="RUTHERFORD",
            block_code="R04",
            gross_weight_lbs=16000,
            tare_weight_lbs=4000,
        ),
        cellar_supervisor_headers,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_DELIVERY_TICKET.value, 409)

    rows, meta = validate_paginated(
        api.list_harvest_intakes(cellar_supervisor_headers, params={"contract_id": contract_id})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [first["id"]]


def test_tons_received_counts_only_accepted_loads(api, cellar_supervisor_headers,
                                                  facility_admin_headers):
    """PRD 3.1: "`tons_received` is the running total of `net_weight_lbs`
    divided by 2000 across that contract's intakes standing in `ACCEPTED` or
    `ASSIGNED`, advanced at the moment an intake is accepted and carried to four
    decimal places."

    Design: Corner/cross_cutting_layers/corner_contract_tons_received_reconciles_after_two_accepts
    """
    scenario = setup_active_contract()
    contract_id = scenario["contract"]["id"]

    nineteen = weigh_in(contract_id, "DT-AK1", gross_weight_lbs=42000, tare_weight_lbs=4000)
    sample_intake(nineteen["id"], 23.50, 3.62)
    five = weigh_in(contract_id, "DT-AK2", varietal="MERLOT", appellation="OAKVILLE",
                    block_code="B07", **FIVE_TON_LOAD)
    sample_intake(five["id"], 23.50, 3.55)
    ten = weigh_in(contract_id, "DT-AK3", varietal="ZINFANDEL",
                   appellation="HOWELL_MOUNTAIN", block_code="Z01",
                   gross_weight_lbs=24000, tare_weight_lbs=4000)
    sample_intake(ten["id"], 23.50, 3.70)

    first_fee = accept_intake(nineteen["id"])["crush_fee_cents"]
    second_fee = accept_intake(five["id"])["crush_fee_cents"]
    rejected = validate_success(
        api.harvest_intake_transition(
            ten["id"],
            {"action": "REJECT", "rejection_reason": "Excessive MOG in the load."},
            cellar_supervisor_headers,
        )
    )

    assert first_fee == 950000
    assert second_fee == 250000
    assert rejected["status"] == "REJECTED"
    assert rejected["crush_fee_cents"] == 0

    contract = validate_success(api.get_contract(contract_id, facility_admin_headers))
    assert contract["tons_received"] == pytest.approx(24.0000, abs=0.0001), (
        "the rejected 10.0 tons must never enter the accumulator"
    )
    assert contract["billed_total_cents"] == 1200000

    rows, _ = validate_paginated(
        api.list_harvest_intakes(
            facility_admin_headers,
            params={"contract_id": contract_id, "status": "ACCEPTED"},
        )
    )
    assert sorted(row["id"] for row in rows) == sorted([nineteen["id"], five["id"]])


# ── The discontinuous yield step at exactly 25.00 Brix ───────────────


def _setup_two_five_ton_loads_astride_the_brix_step():
    """Two SAMPLED 5.0-ton loads differing only by 0.01 Brix around 25.00."""
    scenario = setup_active_contract(clock="2026-09-15T00:00:00Z")
    contract_id = scenario["contract"]["id"]
    high = weigh_in(contract_id, "DT-8001", varietal="ZINFANDEL",
                    appellation="HOWELL_MOUNTAIN", block_code="Z01", **FIVE_TON_LOAD)
    sample_intake(high["id"], 25.00, 3.70)
    low = weigh_in(contract_id, "DT-8002", varietal="ZINFANDEL",
                   appellation="HOWELL_MOUNTAIN", block_code="Z02", **FIVE_TON_LOAD)
    sample_intake(low["id"], 24.99, 3.69)
    scenario["high"] = high
    scenario["low"] = low
    return scenario


def test_yield_steps_down_by_the_flat_penalty_at_exactly_twenty_five_brix(
    api, cellar_supervisor_headers
):
    """PRD 3.3: "When `brix` is at least 25.00, the yield per ton is reduced —
    and the curve steps down discontinuously at exactly 25.00, because crossing
    that line costs a flat 5.0 gallons per ton before any per-degree penalty
    accrues, and a further 2.5 gallons per ton is then lost for each degree of
    Brix by which the reading exceeds 25.00, fractional degrees counting
    proportionally."
    PRD 3.3: "The load's `estimated_gallons` is its tonnage multiplied by the
    adjusted gallons-per-ton figure, rounded half up to two decimal places."

    Design: Difficulty/boundary_precision_check/intake_yield_step_fires_at_exactly_25_00_brix
    """
    scenario = _setup_two_five_ton_loads_astride_the_brix_step()

    high = validate_success(
        api.harvest_intake_transition(
            scenario["high"]["id"], {"action": "ACCEPT"}, cellar_supervisor_headers
        )
    )
    low = validate_success(
        api.harvest_intake_transition(
            scenario["low"]["id"], {"action": "ACCEPT"}, cellar_supervisor_headers
        )
    )

    assert high["estimated_gallons"] == pytest.approx(800.00, abs=0.01), (
        f"5.0 tons at exactly 25.00 Brix yields 5.0 x (165.0 - 5.0), got "
        f"{high['estimated_gallons']}"
    )
    assert low["estimated_gallons"] == pytest.approx(825.00, abs=0.01), (
        f"5.0 tons at 24.99 Brix yields 5.0 x 165.0, got {low['estimated_gallons']}"
    )
    assert low["estimated_gallons"] - high["estimated_gallons"] == pytest.approx(
        25.00, abs=0.01
    ), "a 0.01 Brix difference must move the yield by a whole 25.00 gallons"


def test_the_brix_step_leaves_the_crush_fee_and_tonnage_ledger_untouched(
    api, cellar_supervisor_headers, facility_admin_headers
):
    """PRD 3.3: "Read the contract's `tons_received` as it stands immediately
    **before** this acceptance and call that the starting point; the ending
    point is that starting figure plus this load's own tonnage."
    PRD 3.3: "Acceptance then posts both figures. The contract's `tons_received`
    advances by this load's net weight divided by 2000, its `billed_total_cents`
    advances by the computed `crush_fee_cents`, and its `version` increments by
    1."

    Design: Difficulty/boundary_precision_check/intake_yield_step_fires_at_exactly_25_00_brix
    """
    scenario = _setup_two_five_ton_loads_astride_the_brix_step()

    high = validate_success(
        api.harvest_intake_transition(
            scenario["high"]["id"], {"action": "ACCEPT"}, cellar_supervisor_headers
        )
    )
    assert high["crush_fee_cents"] == 250000, (
        f"5.0 tons wholly inside tier one at 50000 cents, got {high['crush_fee_cents']}"
    )

    validate_success(
        api.harvest_intake_transition(
            scenario["low"]["id"], {"action": "ACCEPT"}, cellar_supervisor_headers
        )
    )

    contract = validate_success(
        api.get_contract(scenario["contract"]["id"], facility_admin_headers)
    )
    assert contract["tons_received"] == pytest.approx(10.0000, abs=0.0001), (
        "the yield step never moves the tonnage accumulator"
    )
    assert contract["billed_total_cents"] == 500000


# ── Per-band rounding inside the marginal crush fee ──────────────────


def _setup_contract_straddling_the_first_tonnage_band():
    """A 22.4375-ton load already accepted at 45000 cents per ton, plus a second
    5.25-ton load sampled and waiting, whose acceptance crosses 25 tons."""
    scenario = setup_active_contract(
        clock="2026-09-05T00:00:00Z",
        client_overrides={
            "name": "Pritchard Hill Partners",
            "ttb_permit_number": "BW-CA-15002",
            "contact_email": "cellar@pritchard.example",
        },
        crush_rate_cents_per_ton=45000,
    )
    contract_id = scenario["contract"]["id"]
    first = weigh_in(contract_id, "DT-2001", varietal="CABERNET_SAUVIGNON",
                     appellation="STAGS_LEAP", block_code="H01",
                     gross_weight_lbs=48875, tare_weight_lbs=4000)
    sample_intake(first["id"], 23.50, 3.60)
    scenario["first"] = accept_intake(first["id"])

    second = weigh_in(contract_id, "DT-2002", varietal="CABERNET_SAUVIGNON",
                      appellation="STAGS_LEAP", block_code="H02",
                      gross_weight_lbs=14500, tare_weight_lbs=4000)
    sample_intake(second["id"], 23.00, 3.58)
    scenario["second"] = second
    return scenario


def test_crush_fee_rounds_each_tonnage_band_before_it_is_summed(
    api, cellar_supervisor_headers
):
    """PRD 3.3: "For each band, take the portion of the interval from the
    starting point to the ending point that falls inside that band; where that
    portion is greater than zero, multiply its tonnage — carried to four decimal
    places — by the contract's `crush_rate_cents_per_ton` and by that band's
    multiplier, round the result half up to whole cents, and only then add it to
    the running fee."
    PRD 3.3: "The per-band rounding happens before summation, never after:
    summing unrounded band amounts and rounding once at the end is a different
    answer on a load that straddles a band boundary, and is not the reading this
    system uses."

    Design: Difficulty/combinatorial_formula/crush_fee_rounds_each_tier_segment_before_summing
    """
    scenario = _setup_contract_straddling_the_first_tonnage_band()
    assert scenario["first"]["crush_fee_cents"] == 1009688, (
        "22.4375 tons wholly inside band one rounds 1009687.5 half up"
    )

    data = validate_success(
        api.harvest_intake_transition(
            scenario["second"]["id"], {"action": "ACCEPT"}, cellar_supervisor_headers
        )
    )

    assert data["crush_fee_cents"] == 224157, (
        f"2.5625 t at 45000 rounds to 115313 and 2.6875 t at 40500 rounds to "
        f"108844, summing to 224157 rather than the sum-then-round 224156; got "
        f"{data['crush_fee_cents']}"
    )
    assert data["estimated_gallons"] == pytest.approx(866.25, abs=0.01)
    assert scenario["first"]["estimated_gallons"] == pytest.approx(3702.19, abs=0.01)


def test_straddling_load_posts_its_rounded_fee_and_tonnage_to_the_contract(
    api, cellar_supervisor_headers, facility_admin_headers
):
    """PRD 3.3: "Acceptance then posts both figures. The contract's
    `tons_received` advances by this load's net weight divided by 2000, its
    `billed_total_cents` advances by the computed `crush_fee_cents`, and its
    `version` increments by 1."
    PRD 2.7: "Volumes are carried in gallons to two decimal places, rounded half
    up, with two documented exceptions: a contract's `tons_received` is carried
    to four decimal places, and the per-tier tonnage segments used in crush
    pricing are likewise carried to four decimal places before being priced."

    Design: Difficulty/combinatorial_formula/crush_fee_rounds_each_tier_segment_before_summing
    """
    scenario = _setup_contract_straddling_the_first_tonnage_band()

    accepted = validate_success(
        api.harvest_intake_transition(
            scenario["second"]["id"], {"action": "ACCEPT"}, cellar_supervisor_headers
        )
    )
    assert_harvest_intake(accepted)
    assert accepted["net_weight_lbs"] == pytest.approx(10500, abs=0.01)
    assert accepted["status"] == "ACCEPTED"

    contract = validate_success(
        api.get_contract(scenario["contract"]["id"], facility_admin_headers)
    )
    assert contract["tons_received"] == pytest.approx(27.6875, abs=0.0001), (
        f"22.4375 + 5.25 tons, got {contract['tons_received']}"
    )
    assert contract["billed_total_cents"] == 1233845, (
        f"1009688 + 224157 cents, got {contract['billed_total_cents']}"
    )
