"""The validation ladder, part two: business constraints and referential
coherence (PRD §2.7 rungs 7 through 13).

Every test here drives one request that violates exactly one rung and asserts
the error the ladder's internal ordering makes reachable. The rules exercised
live in §3.1 (area code uniqueness and reopening), §3.2 (the downgrade sweep
that condemns an area), §3.3 (rainfall closure and the road back to OPEN),
§3.4 (lease submission on a prohibited area), §3.6 (plot and gear membership on
deployment, husbandry currency), §3.7 (dealer category, deployment reuse and
vessel concurrency at issue), §3.8 (the harvest projection, lot-code uniqueness
and the settlement of the lot that fits) and §3.9 (tag cross-checks, shipment
roster membership, suspension and the two listing rungs).
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_draft_lease,
    create_growing_area,
    create_listed_dealer,
    dealer_renewal_payload,
    design_world,
    DW_AREA_CODE,
    DW_CLOCK,
    DW_DEALER_CERT_NO,
    DW_FIRST_OUT,
    DW_HARVEST_CLOCK,
    DW_LAST_OUT,
    DW_PLACED_IN_CONTROL,
    DW_WINDOW_END,
    DW_WINDOW_START,
    dw_area_payload,
    dw_dealer_payload,
    dw_deploy_unit,
    dw_land_lot,
    dw_lease_payload_overrides,
    dw_unit_payload_overrides,
    get_success_data,
    growing_area_payload,
    growout_unit_payload,
    harvest_authorization_payload,
    harvest_lot_payload,
    iso,
    make_seafood_dealer_headers,
    reopen_payload,
    set_clock,
    ship_payload,
    shipment_payload,
    submit_lease_payload,
    suspend_payload,
    tag_payload,
    TEST_USERS,
    to_millis,
    trigger_rainfall_closure,
    validate_error,
    validate_paginated,
    validate_success,
)

AUTHORITY = TEST_USERS["authority_headers"]
OPERATOR = TEST_USERS["operator_headers"]

SHIP_AT = iso(2026, 8, 10, 10, 50)
LAPSED_LISTING_THROUGH = "2026-07-31"


def _land(world, lot_code, bushels, first_out=DW_FIRST_OUT,
          last_out=DW_LAST_OUT, placed=DW_PLACED_IN_CONTROL):
    """Attempt one landing under the world's authorization, returning the raw
    response so a refusal can be inspected."""
    return api_client.create_harvest_lot(
        world["authorization"]["id"],
        harvest_lot_payload(first_out, last_out, placed, lot_code=lot_code,
                            bushels=bushels, water_temp_c=24.0),
        world["operator_headers"],
    )


def _issue(world, unit, window_start, window_end, projected_bushels):
    """Attempt one authorization issue, returning the raw response."""
    return api_client.create_harvest_authorization(
        harvest_authorization_payload(
            world["lease"]["id"], unit["id"], world["vessel"]["id"],
            world["dealer"]["id"], window_start, window_end,
            projected_bushels=projected_bushels),
        world["operator_headers"],
    )


def _lapse_interstate_listing(world):
    """Renew the reference dealer so its `icssl_listed_through` ends
    2026-07-31 while `certified_through` stays 2027-06-30.

    Per §3.9 a renewal on a `LISTED` dealer leaves it `LISTED`, and the renewal
    itself is legal: 2026-07-31 is at or before `certified_through`, and
    2027-06-30 is strictly after the logical clock's calendar date. The dealer
    therefore ends up `LISTED` with a lapsed interstate window, which is the
    only state that isolates the interstate rung.
    """
    dealer = get_success_data(
        api_client.get_dealer(world["dealer"]["id"], AUTHORITY))
    return get_success_data(api_client.renew_dealer_certification(
        dealer["id"],
        dealer_renewal_payload(
            dealer["version"], "2027-06-30",
            icssl_listed_through=LAPSED_LISTING_THROUGH),
        AUTHORITY,
    ))


# --------------------------------------------------------------------------
# §3.8 — the projection ceiling and lot-code uniqueness
# --------------------------------------------------------------------------
def test_landing_one_bushel_over_the_projection_is_refused():
    """On a 10-bushel projection an 11-bushel landing is refused with
    ERR_HARVEST_EXCEEDS_PROJECTION, because §3.8 compares the season-inclusive
    running total against `projected_bushels` with an inclusive test: 0 + 11 is
    over, 0 + 10 is not. The refusal consumes nothing, so the immediately
    following 10-bushel landing succeeds at HTTP 201 and settles to 3760 cents
    -- 115 cents per bushel at tier 1 gives 1150 royalty, which is under the
    50000-cent waiver so the 2500-cent inspection fee applies, and the 3 per
    cent surcharge on 3650 rounds half-up to 110. The lot is COMPLIANT: the
    month-8 plan's 300-minute baseline loses 60 minutes to 24.0C water at the
    plan's 23.0C threshold and 30 more to BOTTOM gear, then gains 60 back for
    the vessel's MECHANICAL refrigeration, giving a 270-minute allowance that
    the 06:00-to-10:30 first-harvest basis exactly meets.

    Design: Corner/validations/landing_beyond_the_projection_is_refused_at_one_bushel_over
    """
    world = design_world(stage="active", auth_overrides={"projected_bushels": 10})
    set_clock(DW_HARVEST_CLOCK)

    over = _land(world, "LOT-OVER", 11)
    validate_error(over, ApiErrorId.ERR_HARVEST_EXCEEDS_PROJECTION, 409)

    lot = validate_success(_land(world, "LOT-OK", 10), 201)
    assert lot["bushels"] == 10
    assert lot["compliance_status"] == "COMPLIANT"
    assert lot["lot_settlement_cents"] == 3760

    auth = get_success_data(api_client.get_harvest_authorization(
        world["authorization"]["id"], AUTHORITY))
    rows, meta = validate_paginated(api_client.list_authorization_harvest_lots(
        world["authorization"]["id"], AUTHORITY))

    assert auth["harvested_bushels"] == 10
    assert auth["projected_bushels"] == 10
    assert meta["total_count"] == 1
    assert [row["lot_code"] for row in rows] == ["LOT-OK"]


def test_duplicate_area_code_and_duplicate_lot_code_are_both_refused():
    """Both uniqueness scopes in §2.7 rung 12 are global. Re-registering the
    code GA-114 under a different water body is ERR_DUPLICATE_AREA_CODE, and
    re-using the lot code LOT-A is ERR_DUPLICATE_LOT_CODE even under the very
    authorization that already carries it -- the scope is all lots, not the
    authorization's roster. The second request clears every earlier rung on the
    landing path: the area is OPEN, the month-8 plan is ACTIVE, 09:00 is inside
    the half-open window and behind the 11:00 clock, the three instants are
    ordered, and 10 + 5 bushels sits far under the 600-bushel projection. Both
    refusals are complete no-ops.

    Design: Corner/validations/duplicate_area_and_lot_codes_are_refused
    """
    world = design_world(stage="landed", lot_overrides={"lot_code": "LOT-A"})

    dup_area = api_client.create_growing_area(
        growing_area_payload(code=DW_AREA_CODE, water_body="Core Sound"),
        AUTHORITY)
    validate_error(dup_area, ApiErrorId.ERR_DUPLICATE_AREA_CODE, 409)

    dup_lot = _land(world, "LOT-A", 5, iso(2026, 8, 10, 9),
                    iso(2026, 8, 10, 9, 30), iso(2026, 8, 10, 10, 45))
    validate_error(dup_lot, ApiErrorId.ERR_DUPLICATE_LOT_CODE, 409)

    _areas, meta = validate_paginated(api_client.list_growing_areas(AUTHORITY))
    auth = get_success_data(api_client.get_harvest_authorization(
        world["authorization"]["id"], AUTHORITY))

    assert meta["total_count"] == 1
    assert auth["harvested_bushels"] == 10


# --------------------------------------------------------------------------
# §3.7 — the dealer category rung
# --------------------------------------------------------------------------
def test_a_repacker_dealer_cannot_receive_shellstock_from_a_harvest():
    """Only SHELLSTOCK_SHIPPER and SHUCKER_PACKER may be named on an
    authorization, so a REPACKER is refused with
    ERR_DEALER_CATEGORY_NOT_PERMITTED even though it is fully certified through
    2027-06-30 and interstate-LISTED. Every rung ahead of the category check
    passes: the lease is APPROVED with rent paid through 2026-12-31, the gear is
    DEPLOYED and husbandry-current at the 2026-08-01 clock, the area is
    APPROVED and OPEN, the 12-hour window is inside the 24-hour ceiling, the
    vessel's capacity of 2 is untouched and the deployment backs no other
    authorization. The refusal is therefore about the category alone, and it is
    not the expired-certification, suspension or rent rung.

    Design: Corner/validations/a_repacker_dealer_cannot_receive_shellstock_from_a_harvest
    """
    world = design_world(stage="unit", dealer_overrides={
        "name": "Inland Repack",
        "certification_category": "REPACKER",
        "certification_no": "NC-7777-RP",
    })

    response = _issue(world, world["unit"], DW_WINDOW_START, DW_WINDOW_END, 600)

    body = validate_error(
        response, ApiErrorId.ERR_DEALER_CATEGORY_NOT_PERMITTED, 409)
    assert body["error_id"] != ApiErrorId.ERR_DEALER_CERTIFICATION_EXPIRED
    assert body["error_id"] != ApiErrorId.ERR_DEALER_SUSPENDED
    assert body["error_id"] != ApiErrorId.ERR_LEASE_RENT_DELINQUENT
    assert response.status_code != 402

    dealer = get_success_data(
        api_client.get_dealer(world["dealer"]["id"], AUTHORITY))
    vessel = get_success_data(
        api_client.get_harvest_vessel(world["vessel"]["id"], AUTHORITY))

    assert dealer["certification_category"] == "REPACKER"
    assert dealer["listing_status"] == "LISTED"
    assert vessel["active_authorization_count"] == 0


# --------------------------------------------------------------------------
# §3.9 — the two listing rungs, conditional on is_interstate
# --------------------------------------------------------------------------
def test_interstate_shipment_without_a_current_listing_is_refused():
    """`listing_status` LISTED is not sufficient for an interstate release: the
    `icssl_listed_through` date must also cover the logical clock. With the
    listing lapsed on 2026-07-31 and the clock at 2026-08-10T11:00:00Z, an
    NC-to-VA shipment is refused with ERR_DEALER_NOT_LISTED_FOR_INTERSTATE, and
    notably not with ERR_DEALER_NOT_LISTED -- the dealer really is LISTED --
    nor with ERR_DEALER_CERTIFICATION_EXPIRED, since `certified_through`
    2027-06-30 is current. The shipment stays CREATED and its lot stays TAGGED.

    Design: Corner/validations/interstate_shipment_without_a_current_listing_is_refused
    """
    world = design_world(stage="tagged")
    _lapse_interstate_listing(world)
    shipment = get_success_data(api_client.create_shipment(
        shipment_payload(world["dealer"]["id"], [world["lot"]["id"]],
                         destination_state="VA"),
        world["dealer_headers"]))

    response = api_client.ship_shipment(
        shipment["id"], ship_payload(SHIP_AT), world["dealer_headers"])

    body = validate_error(
        response, ApiErrorId.ERR_DEALER_NOT_LISTED_FOR_INTERSTATE, 409)
    assert body["error_id"] != ApiErrorId.ERR_DEALER_NOT_LISTED
    assert body["error_id"] != ApiErrorId.ERR_DEALER_CERTIFICATION_EXPIRED

    stored = get_success_data(
        api_client.get_shipment(shipment["id"], world["dealer_headers"]))
    lot = get_success_data(
        api_client.get_harvest_lot(world["lot"]["id"], AUTHORITY))

    assert stored["status"] == "CREATED"
    assert stored["is_interstate"] is True
    assert stored["shipped_at"] is None
    assert stored["lot_count"] == 1
    assert stored["total_bushels"] == 10
    assert lot["status"] == "TAGGED"


def test_intrastate_shipment_ships_without_a_current_interstate_listing():
    """The interstate rung is conditional, not merely lenient: §3.9 says an
    intrastate shipment ignores the listing window entirely. The same dealer
    with the same lapsed `icssl_listed_through` 2026-07-31 releases an NC-to-NC
    shipment at HTTP 200, because `is_interstate` is false when
    `destination_state` equals the dealer's own `state_code`. The release also
    satisfies the last shipping check: 10:50 is at or after the greatest
    `placed_in_temperature_control_at` of 10:30 and not after the 11:00 clock.
    No renewal was needed to make this pass, which the re-read dealer proves.

    Design: Corner/validations/intrastate_shipment_ships_without_a_current_interstate_listing
    """
    world = design_world(stage="tagged")
    dealer = _lapse_interstate_listing(world)
    assert dealer["icssl_listed_through"] == LAPSED_LISTING_THROUGH
    assert dealer["listing_status"] == "LISTED"
    shipment = get_success_data(api_client.create_shipment(
        shipment_payload(world["dealer"]["id"], [world["lot"]["id"]],
                         destination_state="NC"),
        world["dealer_headers"]))

    response = api_client.ship_shipment(
        shipment["id"], ship_payload(SHIP_AT), world["dealer_headers"])

    shipped = validate_success(response, 200)
    assert shipped["status"] == "SHIPPED"
    assert shipped["shipped_at"] == to_millis(SHIP_AT)
    assert shipped["is_interstate"] is False
    assert shipped["lot_count"] == 1
    assert shipped["total_bushels"] == 10

    lot = get_success_data(
        api_client.get_harvest_lot(world["lot"]["id"], AUTHORITY))
    final_dealer = get_success_data(
        api_client.get_dealer(world["dealer"]["id"], AUTHORITY))

    assert lot["status"] == "SHIPPED"
    assert lot["shipment_id"] == shipment["id"]
    assert final_dealer["icssl_listed_through"] == LAPSED_LISTING_THROUGH
    assert final_dealer["listing_status"] == "LISTED"


def test_shipment_roster_membership_rules_are_enforced():
    """A roster may only carry lots that are TAGGED and that belong to the
    shipping dealer. Assembling around the untagged HARVESTED LOT-B is refused
    with ERR_LOT_NOT_TAGGED, and a second listed dealer D2 assembling around
    D1's correctly tagged LOT-A is refused with ERR_LOT_DEALER_MISMATCH -- not
    with ERR_DEALER_OWNERSHIP_VIOLATION, because D2 names itself as the
    shipment's `dealer_id`, so the ownership rung is satisfied and the roster
    rung is the first one violated. Both refusals leave the world untouched: no
    shipment row exists, LOT-A is still TAGGED with a null `shipment_id`, and
    LOT-B is still HARVESTED.

    Design: Corner/validations/shipment_roster_membership_rules_are_enforced
    """
    world = design_world(stage="tagged", lot_overrides={"lot_code": "LOT-A"})
    lot_a = world["lot"]
    lot_b = dw_land_lot(world, lot_code="LOT-B", bushels=20)
    dealer_b = create_listed_dealer(dw_dealer_payload(
        name="Sound Packers", certification_no="NC-5678-SS"))
    dealer_b_headers = make_seafood_dealer_headers(dealer_b["id"])

    untagged = api_client.create_shipment(
        shipment_payload(world["dealer"]["id"], [lot_b["id"]],
                         destination_state="VA"),
        world["dealer_headers"])
    validate_error(untagged, ApiErrorId.ERR_LOT_NOT_TAGGED, 409)

    foreign = api_client.create_shipment(
        shipment_payload(dealer_b["id"], [lot_a["id"]],
                         destination_state="VA"),
        dealer_b_headers)
    body = validate_error(foreign, ApiErrorId.ERR_LOT_DEALER_MISMATCH, 409)
    assert body["error_id"] != ApiErrorId.ERR_DEALER_OWNERSHIP_VIOLATION
    assert foreign.status_code != 403

    _rows, meta = validate_paginated(api_client.list_shipments(AUTHORITY))
    stored_a = get_success_data(api_client.get_harvest_lot(lot_a["id"], AUTHORITY))
    stored_b = get_success_data(api_client.get_harvest_lot(lot_b["id"], AUTHORITY))

    assert meta["total_count"] == 0
    assert stored_a["status"] == "TAGGED"
    assert stored_a["shipment_id"] is None
    assert stored_b["status"] == "HARVESTED"


def test_tag_field_mismatches_are_refused():
    """The tag payload is cross-checked against stored state, not merely against
    the schema. A `harvest_date` of 2026-08-09 is refused with
    ERR_TAG_HARVEST_DATE_MISMATCH because §3.9 requires it to equal the UTC
    calendar date of the lot's own `first_out_of_water_at`, which is
    2026-08-10T06:00:00Z, and a `dealer_certification_no` of NC-9999-SS is
    refused with ERR_TAG_DEALER_CERT_MISMATCH because the lot's dealer carries
    NC-1234-SS. Neither answer is ERR_TIME_TEMPERATURE_EXCEEDED: the compliance
    check sits ahead of both, and this lot is COMPLIANT at 270 governing minutes
    against a 270-minute allowance. After both refusals the lot is still
    HARVESTED with all four tag fields null.

    Design: Corner/validations/tag_field_mismatches_are_refused
    """
    world = design_world(stage="landed", lot_overrides={"lot_code": "LOT-A"})
    lot_id = world["lot"]["id"]
    assert world["lot"]["compliance_status"] == "COMPLIANT"

    wrong_date = api_client.tag_harvest_lot(
        lot_id, tag_payload("2026-08-09", DW_DEALER_CERT_NO),
        world["operator_headers"])
    first = validate_error(
        wrong_date, ApiErrorId.ERR_TAG_HARVEST_DATE_MISMATCH, 409)

    wrong_cert = api_client.tag_harvest_lot(
        lot_id, tag_payload("2026-08-10", "NC-9999-SS"),
        world["operator_headers"])
    second = validate_error(
        wrong_cert, ApiErrorId.ERR_TAG_DEALER_CERT_MISMATCH, 409)

    assert first["error_id"] != ApiErrorId.ERR_TIME_TEMPERATURE_EXCEEDED
    assert second["error_id"] != ApiErrorId.ERR_TIME_TEMPERATURE_EXCEEDED

    stored = get_success_data(api_client.get_harvest_lot(lot_id, AUTHORITY))
    assert stored["status"] == "HARVESTED"
    assert stored["tag_harvest_date"] is None
    assert stored["tag_area_code"] is None
    assert stored["tag_lease_code"] is None
    assert stored["tag_dealer_certification_no"] is None


# --------------------------------------------------------------------------
# §3.6 — the lease footprint on deployment
# --------------------------------------------------------------------------
def test_plot_and_gear_membership_are_enforced_on_deployment():
    """§3.6 enforces the lease footprint on two independent arrays, and in this
    order: `plot_code` must be a member of the lease's `plot_codes`, so P9
    against [P1, P2, P3] is ERR_PLOT_NOT_IN_LEASE, and only then must
    `gear_type` be a member of `gear_types_permitted`, so FLOATING_BAG against
    [BOTTOM, RACK_AND_BAG] is ERR_GEAR_TYPE_NOT_PERMITTED. Neither answer is
    ERR_INVALID_REQUEST: both payloads are schema-valid, FLOATING_BAG included,
    which is exactly why the refusals land on the referential rung at HTTP 409
    rather than the request-shape rung at HTTP 400. Both refusals leave the
    lease's `deployed_gear_units` at 0. The deployment list is read with the
    `lease_id` filter §4 declares for that endpoint.

    Design: Corner/validations/plot_and_gear_membership_are_enforced_on_deployment
    """
    world = design_world(stage="seed")
    lease, seed_lot = world["lease"], world["seed_lot"]

    off_plot = api_client.create_growout_unit(
        growout_unit_payload(lease["id"], seed_lot["id"],
                             **dw_unit_payload_overrides(plot_code="P9")),
        OPERATOR)
    first = validate_error(off_plot, ApiErrorId.ERR_PLOT_NOT_IN_LEASE, 409)

    wrong_gear = api_client.create_growout_unit(
        growout_unit_payload(lease["id"], seed_lot["id"],
                             **dw_unit_payload_overrides(
                                 gear_type="FLOATING_BAG")),
        OPERATOR)
    second = validate_error(
        wrong_gear, ApiErrorId.ERR_GEAR_TYPE_NOT_PERMITTED, 409)

    assert first["error_id"] != ApiErrorId.ERR_INVALID_REQUEST
    assert second["error_id"] != ApiErrorId.ERR_INVALID_REQUEST

    _rows, meta = validate_paginated(api_client.list_growout_units(
        AUTHORITY, {"lease_id": lease["id"]}))
    stored_lease = get_success_data(api_client.get_lease(lease["id"], AUTHORITY))

    assert meta["total_count"] == 0
    assert stored_lease["deployed_gear_units"] == 0


# --------------------------------------------------------------------------
# §3.1 and §3.3 — the two reopen guards
# --------------------------------------------------------------------------
def test_reopen_guards_reject_an_open_area_and_a_closure_without_clean_samples():
    """The four reopen grounds sit on different rungs, and the ladder decides
    which one answers. Reopening GA-114, which was never closed, is
    ERR_AREA_ALREADY_OPEN from the state-precondition rung. Reopening GA-220,
    closed by a 1.50-inch event at 2026-08-05T12:00:00Z and therefore eligible
    from 2026-08-09T12:00:00Z, is ERR_INSUFFICIENT_CLEAN_SAMPLES and not
    ERR_REOPEN_TOO_EARLY: the 2026-08-10T00:00:00Z clock is past the eligible
    instant, so the temporal rung passes and the business rung answers on 0
    consecutive clean samples against the 3 required. A rainfall closure never
    touches `classification`, so GA-220 is still APPROVED, which is what keeps
    the ERR_AREA_PROHIBITED ground out of the way. The clock is advanced to the
    accumulation instant before the event is recorded so the ingest itself is
    never future-dated.

    Design: Corner/validations/reopen_guards_reject_an_open_area_and_a_closure_without_clean_samples
    """
    set_clock(DW_CLOCK)
    open_area = create_growing_area(dw_area_payload())
    closed_area = create_growing_area(dw_area_payload(code="GA-220"))
    set_clock(iso(2026, 8, 5, 12))
    trigger_rainfall_closure(closed_area["id"], iso(2026, 8, 5, 12), 1.50)
    set_clock(iso(2026, 8, 10))

    already_open = api_client.reopen_growing_area(
        open_area["id"], reopen_payload(reopen_note="nothing to reopen"),
        AUTHORITY)
    validate_error(already_open, ApiErrorId.ERR_AREA_ALREADY_OPEN, 409)

    too_few = api_client.reopen_growing_area(
        closed_area["id"], reopen_payload(reopen_note="duration has elapsed"),
        AUTHORITY)
    body = validate_error(
        too_few, ApiErrorId.ERR_INSUFFICIENT_CLEAN_SAMPLES, 409)
    assert body["error_id"] != ApiErrorId.ERR_REOPEN_TOO_EARLY

    stored_closed = get_success_data(
        api_client.get_growing_area(closed_area["id"], AUTHORITY))
    stored_open = get_success_data(
        api_client.get_growing_area(open_area["id"], AUTHORITY))

    assert stored_closed["harvest_status"] == "CLOSED_RAINFALL"
    assert stored_closed["consecutive_clean_samples"] == 0
    assert stored_closed["reopen_sample_count_required"] == 3
    assert stored_closed["classification"] == "APPROVED"
    assert stored_closed["closure_reopen_eligible_at"] == to_millis(
        iso(2026, 8, 9, 12))
    assert stored_open["harvest_status"] == "OPEN"


# --------------------------------------------------------------------------
# §3.2 and §3.4 — a condemned area blocks the siting package
# --------------------------------------------------------------------------
def test_lease_submit_on_a_prohibited_area_is_refused():
    """Five accepted 200-MPN samples on five distinct July days fire the §3.2
    downgrade sweep on the fifth ingest: the count reaches 5, the geometric mean
    of 200.0 is strictly above 14.0, and PROHIBITED outranks the area's standing
    APPROVED, so the system condemns the area itself and sets `harvest_status`
    to CLOSED_SAMPLE_FAILURE. Drafting a lease over that area is still
    permitted, but §3.4 gates submission, so the submit is refused with
    ERR_AREA_PROHIBITED from the sanitary rung and the lease stays exactly as
    drafted. The computed summary confirms the statistics the sweep read. The
    design's `navigation_cleared == false` is asserted in the PRD's own field
    vocabulary: §3.4 names the clearance legs `navigation_clearance` and
    `environmental_clearance`, both PENDING on a DRAFT lease.

    Design: Corner/validations/lease_submit_on_a_prohibited_area_is_refused
    """
    world = design_world(stage="area", sample_mpns=[200, 200, 200, 200, 200])
    area_id = world["area"]["id"]
    lease = create_draft_lease(area_id, OPERATOR, dw_lease_payload_overrides())

    response = api_client.submit_lease(
        lease["id"],
        submit_lease_payload(submission_note="initial siting package"),
        OPERATOR)

    validate_error(response, ApiErrorId.ERR_AREA_PROHIBITED, 409)

    area = get_success_data(api_client.get_growing_area(area_id, AUTHORITY))
    stored_lease = get_success_data(api_client.get_lease(lease["id"], AUTHORITY))
    summary = get_success_data(api_client.get_classification_summary(
        area_id, AUTHORITY, {"variant": "SYSTEMATIC_RANDOM"}))

    assert area["classification"] == "PROHIBITED"
    assert area["harvest_status"] == "CLOSED_SAMPLE_FAILURE"
    assert stored_lease["status"] == "DRAFT"
    assert stored_lease["navigation_clearance"] == "PENDING"
    assert stored_lease["environmental_clearance"] == "PENDING"
    assert stored_lease["revision_round"] == 0
    assert summary["sample_count"] == 5
    assert summary["geometric_mean_mpn"] == 200.0
    assert summary["eligible_classification"] == "PROHIBITED"


# --------------------------------------------------------------------------
# §3.7 — one deployment, one live authorization; and husbandry currency
# --------------------------------------------------------------------------
def test_unit_reauthorization_and_lapsed_inspection_are_refused():
    """Re-issuing over the very same deployment is ERR_UNIT_ALREADY_AUTHORIZED,
    and it is reached because the vessel-capacity rung sits ahead of it and
    passes: one existing overlapping authorization plus this one is 2, which does
    not strictly exceed the vessel's capacity of 2, so the answer is not
    ERR_VESSEL_CAPACITY_CONFLICT (the PRD's spelling of the member the design
    calls ERR_VESSEL_CAPACITY_EXCEEDED). A second deployment U2 on P2, whose
    inspection and predator-control logs both sit at 2026-06-01 and are
    therefore more than 30 and more than 60 days behind the 2026-08-01 clock, is
    refused with ERR_HUSBANDRY_LAPSED rather than ERR_PREDATOR_CONTROL_LAPSED,
    because §3.7 checks the inspection test first. U2's own request clears the
    earlier rungs: its window on 2026-08-11 does not overlap U1's, P2 is a
    member of the lease and unoccupied, 40 + 20 gear units stay under the
    lease's 200, and 25000 + 15000 seed stays under the 60000 survivors.

    Design: Corner/validations/unit_reauthorization_and_lapsed_inspection_are_refused
    """
    world = design_world(stage="issued", activate_clock=None)

    reissue = _issue(world, world["unit"], DW_WINDOW_START, DW_WINDOW_END, 600)
    body = validate_error(reissue, ApiErrorId.ERR_UNIT_ALREADY_AUTHORIZED, 409)
    assert body["error_id"] != ApiErrorId.ERR_VESSEL_CAPACITY_CONFLICT

    stale_unit = dw_deploy_unit(
        world["lease"], world["seed_lot"], OPERATOR,
        {"plot_code": "P2", "gear_units": 20, "seed_count_planted": 15000},
        True, iso(2026, 6, 1, 12), iso(2026, 6, 1, 13))
    assert stale_unit["husbandry_current"] is False

    lapsed = _issue(world, stale_unit, iso(2026, 8, 11, 6),
                    iso(2026, 8, 11, 18), 300)
    second = validate_error(lapsed, ApiErrorId.ERR_HUSBANDRY_LAPSED, 409)
    assert second["error_id"] != ApiErrorId.ERR_PREDATOR_CONTROL_LAPSED

    vessel = get_success_data(
        api_client.get_harvest_vessel(world["vessel"]["id"], AUTHORITY))
    rows, meta = validate_paginated(api_client.list_harvest_authorizations(
        AUTHORITY, {"lease_id": world["lease"]["id"]}))

    assert vessel["active_authorization_count"] == 1
    assert meta["total_count"] == 1
    assert rows[0]["status"] == "ISSUED"
    assert rows[0]["growout_unit_id"] == world["unit"]["id"]


# --------------------------------------------------------------------------
# §3.9 — suspension at tag time, and the never-listed dealer at the dock
# --------------------------------------------------------------------------
def test_tagging_a_lot_for_a_suspended_dealer_is_refused():
    """Suspending the dealer after the lot is landed makes the fourth and last
    tag check bite: the tag is refused with ERR_DEALER_SUSPENDED. That refusal
    is only reachable because the two checks ahead of it pass -- the submitted
    `harvest_date` 2026-08-10 is the UTC date of `first_out_of_water_at` and
    NC-1234-SS is genuinely the dealer's `certification_no` -- so the answer is
    neither ERR_TAG_HARVEST_DATE_MISMATCH nor ERR_TAG_DEALER_CERT_MISMATCH. The
    lot stays HARVESTED with no tag stamped, and the suspension itself is an
    authority action that leaves `recall_strike_count` at 0.

    Design: Corner/validations/tagging_a_lot_for_a_suspended_dealer_is_refused
    """
    world = design_world(stage="landed", lot_overrides={"lot_code": "LOT-A"})
    suspended = get_success_data(api_client.suspend_dealer(
        world["dealer"]["id"],
        suspend_payload(suspension_note="pending sanitation review"),
        AUTHORITY))
    assert suspended["listing_status"] == "SUSPENDED"

    response = api_client.tag_harvest_lot(
        world["lot"]["id"], tag_payload("2026-08-10", DW_DEALER_CERT_NO),
        world["operator_headers"])

    body = validate_error(response, ApiErrorId.ERR_DEALER_SUSPENDED, 409)
    assert body["error_id"] != ApiErrorId.ERR_TAG_HARVEST_DATE_MISMATCH
    assert body["error_id"] != ApiErrorId.ERR_TAG_DEALER_CERT_MISMATCH

    lot = get_success_data(
        api_client.get_harvest_lot(world["lot"]["id"], AUTHORITY))
    dealer = get_success_data(
        api_client.get_dealer(world["dealer"]["id"], AUTHORITY))

    assert lot["status"] == "HARVESTED"
    assert lot["tag_harvest_date"] is None
    assert dealer["listing_status"] == "SUSPENDED"
    assert dealer["recall_strike_count"] == 0


def test_shipping_for_a_never_listed_dealer_returns_dealer_not_listed():
    """A dealer that was certified but never renewed with an
    `icssl_listed_through` stays NOT_LISTED, and §3.9 requires the shipping
    dealer's `listing_status` to be exactly LISTED at the dock, so the release is
    refused with ERR_DEALER_NOT_LISTED. It is not
    ERR_DEALER_NOT_LISTED_FOR_INTERSTATE, because the NC-to-NC destination makes
    `is_interstate` false and §3.9 says an intrastate shipment ignores the
    listing window entirely, and it is not ERR_DEALER_SUSPENDED, because
    NOT_LISTED is not SUSPENDED. Assembly earlier succeeded on the same dealer:
    §3.9 gates assembly on `certified_through` and suspension only, never on the
    listing dimension, which is why an unlistable dealer can hold a CREATED
    shipment it can never release.

    Design: Corner/validations/shipping_for_a_never_listed_dealer_returns_dealer_not_listed
    """
    world = design_world(stage="shipment", list_dealer=False)

    response = api_client.ship_shipment(
        world["shipment"]["id"], ship_payload(SHIP_AT), world["dealer_headers"])

    body = validate_error(response, ApiErrorId.ERR_DEALER_NOT_LISTED, 409)
    assert body["error_id"] != ApiErrorId.ERR_DEALER_NOT_LISTED_FOR_INTERSTATE
    assert body["error_id"] != ApiErrorId.ERR_DEALER_SUSPENDED

    dealer = get_success_data(
        api_client.get_dealer(world["dealer"]["id"], AUTHORITY))
    shipment = get_success_data(api_client.get_shipment(
        world["shipment"]["id"], world["dealer_headers"]))
    lot = get_success_data(
        api_client.get_harvest_lot(world["lot"]["id"], AUTHORITY))

    assert dealer["listing_status"] == "NOT_LISTED"
    assert dealer["icssl_listed_through"] is None
    assert shipment["status"] == "CREATED"
    assert shipment["shipped_at"] is None
    assert shipment["is_interstate"] is False
    assert lot["status"] == "TAGGED"
