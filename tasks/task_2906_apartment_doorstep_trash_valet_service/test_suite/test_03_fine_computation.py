"""Fine arithmetic: round once, then floor, then cap the monthly running total."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_fine_amounts,
    factories,
    fixtures,
    make_property_manager_headers,
    make_valet_headers,
    validate_error,
    validate_success,
)

CONTAMINATION_NIGHTS = ["2026-09-01", "2026-09-02", "2026-09-03"]


def _community_with_one_tenant(name):
    return fixtures.build_active_community(
        name=name,
        resident_units=(101,),
        resident_kwargs={101: {"move_in_date": "2026-08-01"}},
    )


def _contamination_scan(world, service_date):
    """Record one recycling-contamination scan on its own night and route."""
    night, route = fixtures.add_scan_ready_night(world, service_date)
    scan = fixtures.record_scan(
        route["id"],
        world["contractor"]["id"],
        world["residents"][101]["id"],
        scan_result="TAGGED_NOT_SERVICED",
        container_type="RECYCLING_BIN",
        non_compliance_type="RECYCLING_CONTAMINATION",
    )
    return night, route, scan


def _three_contaminations(name="Birch Row"):
    """Assess 2500, 7500 and 5000, landing the monthly total exactly on 15000."""
    world = _community_with_one_tenant(name)
    world["scans"] = []
    for service_date in CONTAMINATION_NIGHTS[:2]:
        _, _, scan = _contamination_scan(world, service_date)
        world["scans"].append(scan)
    third_night, third_route = fixtures.add_scan_ready_night(
        world, CONTAMINATION_NIGHTS[2]
    )
    world["third_night"] = third_night
    world["third_route"] = third_route
    return world


# --------------------------------------------------------------------------
# The nested clamps
# --------------------------------------------------------------------------
def test_third_contamination_is_floored_as_a_no_op_then_clamped_by_the_cap():
    """A raw 10000 survives the floor and is cut to the 5000 of headroom left.

    PRD 3.6: "Then a **monthly cap**: a resident may be assessed at most 15000
    cents — one hundred and fifty dollars — of fines within a single calendar
    month, so the remaining headroom is 15000 minus that resident's
    `fines_assessed_this_period_cents`, treated as 0 if the subtraction would go
    negative, and `amount_cents` is the smaller of the floored amount and that
    remaining headroom."

    Design: Difficulty/combinatorial_formula/fine_amount_nested_clamp_orders_round_then_floor_then_cap
    """
    world = _three_contaminations()

    scan = validate_success(
        api_client.record_scan(
            world["third_route"]["id"],
            factories.scan_payload(
                world["residents"][101]["id"],
                "TAGGED_NOT_SERVICED",
                "RECYCLING_BIN",
                "RECYCLING_CONTAMINATION",
            ),
            make_valet_headers(world["contractor"]["id"]),
        ),
        expected_status=201,
    )

    assert scan["offense_ordinal"] == 3
    assert scan["tag_status"] == "FINED"
    fines = fixtures.list_fines({"scan_id": scan["id"]})
    assert len(fines) == 1
    assert_fine_amounts(
        fines[0],
        base_cents=5000,
        escalation_multiplier=2.0,
        amount_cents=5000,
        uncapped_amount_cents=10000,
        seasonal_uplift_applied=False,
    )
    assert fines[0]["origin"] == "AUTO"
    assert fines[0]["status"] == "ASSESSED"


def test_the_capped_assessment_still_moves_the_running_period_total():
    """The clamped 5000 is what the ledger records, taking both totals to 15000.

    PRD 3.6: "`fines_assessed_this_period_cents` is the running total of
    `amount_cents` for every fine ever created for that resident within the
    current billing period, where the period is the calendar month of the
    logical clock at the moment of assessment."

    Design: Difficulty/combinatorial_formula/fine_amount_nested_clamp_orders_round_then_floor_then_cap
    """
    world = _three_contaminations()

    fixtures.record_scan(
        world["third_route"]["id"],
        world["contractor"]["id"],
        world["residents"][101]["id"],
        scan_result="TAGGED_NOT_SERVICED",
        container_type="RECYCLING_BIN",
        non_compliance_type="RECYCLING_CONTAMINATION",
    )

    resident = fixtures.read_resident(world["residents"][101]["id"])
    assert resident["fines_assessed_this_period_cents"] == 15000
    assert resident["fines_outstanding_cents"] == 15000
    amounts = sorted(
        fine["amount_cents"]
        for fine in fixtures.list_fines({"resident_id": resident["id"]})
    )
    assert amounts == [2500, 5000, 7500]


# --------------------------------------------------------------------------
# The state category outranks the fiscal category
# --------------------------------------------------------------------------
def _cap_exhausted_with_every_tag_fined(name="Birch Row"):
    """Three contaminations fined 2500 + 7500 + 5000: headroom is exactly 0."""
    world = _three_contaminations(name)
    third_scan = fixtures.record_scan(
        world["third_route"]["id"],
        world["contractor"]["id"],
        world["residents"][101]["id"],
        scan_result="TAGGED_NOT_SERVICED",
        container_type="RECYCLING_BIN",
        non_compliance_type="RECYCLING_CONTAMINATION",
    )
    world["scans"].append(third_scan)
    return world


def test_manual_fine_on_a_fined_tag_reports_the_tag_state_not_the_spent_cap():
    """Both rules are violated at once and the tag-state refusal is the answer.

    PRD 3.6: "It requires the tag to be `OPEN` — a tag reading `NONE`, `FINED`
    or `VOIDED` is refused with `ERR_TAG_NOT_FINEABLE` — the resident to have
    `fee_passthrough_enabled` true, and the monthly headroom to be positive."

    Design: Difficulty/priority_pair_validation_conflict/fined_tag_with_exhausted_cap_returns_tag_not_fineable_not_cap_exhausted
    """
    world = _cap_exhausted_with_every_tag_fined()
    first_scan = world["scans"][0]
    assert first_scan["tag_status"] == "FINED"

    response = api_client.assess_fine(
        first_scan["id"],
        factories.manual_fine_payload("manual re-assessment attempt"),
        make_property_manager_headers(world["property"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_TAG_NOT_FINEABLE.value, 409)


def test_the_refused_manual_fine_writes_nothing_at_all():
    """The tag, the fine list and both resident totals are left exactly as they were.

    PRD 2.5: "Because a single request can violate several rules at once, the
    order in which rejections are evaluated is part of the contract: the first
    rule in the ladder below that fails is the one whose error is returned, and
    no later rule is consulted."

    Design: Difficulty/priority_pair_validation_conflict/fined_tag_with_exhausted_cap_returns_tag_not_fineable_not_cap_exhausted
    """
    world = _cap_exhausted_with_every_tag_fined()
    first_scan = world["scans"][0]
    before = fixtures.read_scan(first_scan["id"])

    api_client.assess_fine(
        first_scan["id"],
        factories.manual_fine_payload("manual re-assessment attempt"),
        make_property_manager_headers(world["property"]["id"]),
    )

    after = fixtures.read_scan(first_scan["id"])
    assert after["tag_status"] == "FINED"
    assert after["version"] == before["version"]
    resident = fixtures.read_resident(world["residents"][101]["id"])
    amounts = sorted(
        fine["amount_cents"]
        for fine in fixtures.list_fines({"resident_id": resident["id"]})
    )
    assert amounts == [2500, 5000, 7500]
    assert resident["fines_assessed_this_period_cents"] == 15000
    assert resident["fines_outstanding_cents"] == 15000


# --------------------------------------------------------------------------
# Zero remaining headroom is a refusal, not a zero-cent fine
# --------------------------------------------------------------------------
def _open_tag_with_the_cap_spent(name="Alder Walk"):
    """One OPEN early-set-out tag alongside contaminations that spend the cap.

    The early set-out is a first offence of its own type, so it opens a tag and
    draws no automatic fine. Three later contaminations are fined 2500, 7500
    and then a 10000 clamped down to the 5000 of headroom left, which puts the
    running period total exactly on the 15000 ceiling.
    """
    world = _community_with_one_tenant(name)
    night, route = fixtures.add_scan_ready_night(world, "2026-09-01")
    early_scan = fixtures.record_scan(
        route["id"],
        world["contractor"]["id"],
        world["residents"][101]["id"],
        scan_result="TAGGED_NOT_SERVICED",
        container_type="TRASH_BIN",
        non_compliance_type="EARLY_SET_OUT",
    )
    for service_date in ("2026-09-02", "2026-09-03", "2026-09-06"):
        _contamination_scan(world, service_date)
    world["early_scan"] = early_scan
    return world


def test_the_clamped_contamination_lands_the_period_total_exactly_on_the_cap():
    """Two full fines plus one clamped fine sum to precisely 15000 cents.

    PRD 3.6: "Contaminated recycling costs 2500 at first offence, 7500 at
    second, and 10000 at third or beyond; a third such offence for a resident
    who has already been assessed 12500 cents this month is capped to the 2500
    cents of headroom left, with `uncapped_amount_cents` still recording
    10000."

    Design: Difficulty/boundary_precision_check/manual_fine_with_exactly_zero_remaining_cap_returns_cap_exhausted
    """
    world = _open_tag_with_the_cap_spent()

    resident = fixtures.read_resident(world["residents"][101]["id"])
    assert resident["fines_assessed_this_period_cents"] == 15000
    fines = fixtures.list_fines({"resident_id": resident["id"]})
    assert sorted(fine["amount_cents"] for fine in fines) == [2500, 5000, 7500]
    clamped = [fine for fine in fines if fine["amount_cents"] == 5000]
    assert clamped and clamped[0]["uncapped_amount_cents"] == 10000
    assert world["early_scan"]["tag_status"] == "OPEN"
    assert world["early_scan"]["offense_ordinal"] == 1


def test_manual_fine_with_zero_headroom_is_refused_rather_than_written_as_zero():
    """An OPEN tag is still unfineable once the month's ceiling is reached.

    PRD 3.6: "And crucially, **zero remaining headroom is not a zero-cent
    fine** — it is a refusal, reported as `ERR_FINE_CAP_EXHAUSTED`."

    Design: Difficulty/boundary_precision_check/manual_fine_with_exactly_zero_remaining_cap_returns_cap_exhausted
    """
    world = _open_tag_with_the_cap_spent()

    response = api_client.assess_fine(
        world["early_scan"]["id"],
        factories.manual_fine_payload("manual fine for the early set-out tag"),
        make_property_manager_headers(world["property"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_FINE_CAP_EXHAUSTED.value, 409)
    scan = fixtures.read_scan(world["early_scan"]["id"])
    assert scan["tag_status"] == "OPEN"
    assert scan["offense_ordinal"] == 1
    resident = fixtures.read_resident(world["residents"][101]["id"])
    assert len(fixtures.list_fines({"resident_id": resident["id"]})) == 3
    assert resident["fines_outstanding_cents"] == 15000
