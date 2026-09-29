"""Endpoint, error-envelope and concurrency contracts (PRD §2.2, §2.3, §2.6,
§2.7, §2.8, §3.1, §3.2, §3.3, §3.9).

Four contracts meet here. Computed reads and roster-derived writes must return
exactly what the endpoint table promises; every refusal must arrive in the
uniform error envelope with the entity-specific code its own family owns; a
closure cascade must already be visible in the response that caused it; and the
two optimistic-concurrency guards must refuse a stale replay and then accept the
same payload once the client has re-read the row.
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    classification_decision_payload,
    create_approved_lease,
    create_dealer,
    create_growing_area,
    date_of,
    dealer_renewal_payload,
    DEFAULT_OFFSET,
    design_world,
    DW_AREA_CODE,
    dw_area_payload,
    dw_assemble_shipment,
    DW_CLOCK,
    dw_dealer_payload,
    DW_DEALER_CERT_NO,
    dw_deploy_unit,
    DW_FIRST_OUT,
    dw_ingest_clean_samples,
    dw_land_lot,
    dw_lease_payload_overrides,
    dw_tag_lot,
    get_success_data,
    harvest_authorization_payload,
    ingest_water_sample,
    iso,
    MAX_LIMIT,
    NON_EXISTENT_UUID,
    rainfall_event_payload,
    reinstate_payload,
    reopen_payload,
    set_clock,
    ship_payload,
    shipment_payload,
    tag_payload,
    TEST_USERS,
    to_millis,
    validate_error,
    validate_paginated,
    validate_success,
    void_payload,
    water_sample_payload,
)

AUTHORITY = TEST_USERS["authority_headers"]
OPERATOR = TEST_USERS["operator_headers"]

CLEAN_SAMPLE_DATES = ("2026-07-05", "2026-07-12", "2026-07-19", "2026-07-26",
                      "2026-07-31")
WINDOW_START_AT = iso(2026, 7, 5, 9)
WINDOW_END_AT = iso(2026, 7, 31, 9)
SHIPPED_AT = iso(2026, 8, 10, 10, 55)


def _area_with_five_clean_samples(**area_overrides):
    """GA-114 on the reference calendar carrying five accepted 2-MPN samples,
    one per distinct collection date so no ingest supersedes an earlier row
    (PRD §3.2). log10(2) rounds to 0.3010, so the window's mean logarithm is
    0.3010 and both statistics land on 2.0."""
    set_clock(DW_CLOCK)
    area = create_growing_area(dw_area_payload(**area_overrides))
    dw_ingest_clean_samples(area["id"], list(CLEAN_SAMPLE_DATES), mpn=2)
    return get_success_data(api_client.get_growing_area(area["id"], AUTHORITY))


def _two_tagged_lots_world():
    """The reference active-authorization world taken to a tagged LOT-A of 10
    bushels, plus a second COMPLIANT tagged LOT-B of 20 bushels landed under the
    same authorization later on the same harvest day."""
    world = design_world(stage="tagged", lot_overrides={"lot_code": "LOT-A"})
    lot_b = dw_land_lot(
        world,
        iso(2026, 8, 10, 9), iso(2026, 8, 10, 9, 30), iso(2026, 8, 10, 10, 45),
        lot_code="LOT-B", bushels=20,
    )
    return world, world["lot"], dw_tag_lot(world, lot_b)


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------
def test_classification_summary_is_a_side_effect_free_computed_read():
    """The summary endpoint computes, it does not write. Read under
    `SYSTEMATIC_RANDOM` it reports the five-sample window and its 0.3010 mean
    logarithm; read again under `ADVERSE_CONDITION` by the operator it reports a
    genuinely different window over the same stored rows; and the growing-area
    row afterwards is identical to the row before, field for field.

    Two deviations from the recipe, both forced by the PRD. First, no rainfall
    event exists here, so no sample is `is_adverse_condition` and §3.2's
    empty-window clause uniquely derives `sample_count` 0 with five nulls and
    `INSUFFICIENT_DATA` rather than "its own window pair". Second, the recipe's
    literal `version == 1` is unreachable: §3.2 advances the area's `version`
    on every ingest that changes a growing-area field, and each of the five
    ingests moves `accepted_sample_count`. The side-effect-freedom the instance
    is really about is asserted as before-equals-after on the whole row.

    Design: Corner/endpoints/classification_summary_is_a_side_effect_free_computed_read
    """
    before = _area_with_five_clean_samples()

    systematic_response = api_client.get_classification_summary(
        before["id"], AUTHORITY, {"variant": "SYSTEMATIC_RANDOM"})
    systematic = validate_success(systematic_response, 200)
    assert systematic_response.json()["response_type"] == "object"
    assert "error_id" not in systematic
    assert systematic["variant"] == "SYSTEMATIC_RANDOM"
    assert systematic["sample_count"] == 5
    assert systematic["mean_log10"] == 0.3010
    assert systematic["geometric_mean_mpn"] == 2.0
    assert systematic["p90_mpn"] == 2.0
    assert systematic["eligible_classification"] == "APPROVED"
    assert systematic["window_start_at"] == to_millis(WINDOW_START_AT)
    assert systematic["window_end_at"] == to_millis(WINDOW_END_AT)

    adverse_response = api_client.get_classification_summary(
        before["id"], OPERATOR, {"variant": "ADVERSE_CONDITION"})
    adverse = validate_success(adverse_response, 200)
    assert adverse_response.json()["response_type"] == "object"
    assert "error_id" not in adverse
    assert adverse["variant"] == "ADVERSE_CONDITION"
    assert adverse["sample_count"] == 0
    for field in ("mean_log10", "geometric_mean_mpn", "p90_mpn",
                  "window_start_at", "window_end_at"):
        assert adverse[field] is None, f"empty window must null {field}"
    assert adverse["eligible_classification"] == "INSUFFICIENT_DATA"

    after = get_success_data(api_client.get_growing_area(before["id"], AUTHORITY))
    assert after == before, "a computed read must not touch the area row"
    assert after["classification"] == "APPROVED"
    assert after["harvest_status"] == "OPEN"
    assert after["accepted_sample_count"] == 5
    assert after["version"] == before["version"]


def test_shipment_assembly_links_two_tagged_lots_and_derives_the_roster_totals():
    """Assembly is a many-to-one link whose counters are derived, not supplied:
    `lot_count` 2 and `total_bushels` 30 come from the two referenced lots, and
    `is_interstate` comes from comparing the requested `destination_state` VA
    against the dealer's own `state_code` NC. The same call back-fills
    `shipment_id` on both lots while leaving them in `TAGGED`, because only
    shipping moves a lot on.

    Design: Corner/endpoints/shipment_assembly_links_two_tagged_lots_and_derives_the_roster_totals
    """
    world, lot_a, lot_b = _two_tagged_lots_world()

    response = api_client.create_shipment(
        shipment_payload(
            world["dealer"]["id"], [lot_a["id"], lot_b["id"]],
            destination_state="VA", carrier="Coastal Freight"),
        world["dealer_headers"])

    shipment = validate_success(response, 201)
    assert shipment["status"] == "CREATED"
    assert shipment["lot_count"] == 2
    assert shipment["total_bushels"] == 30
    assert shipment["is_interstate"] is True
    assert shipment["dealer_id"] == world["dealer"]["id"]
    assert shipment["shipped_at"] is None

    for lot in (lot_a, lot_b):
        fresh = get_success_data(api_client.get_harvest_lot(lot["id"], OPERATOR))
        assert fresh["shipment_id"] == shipment["id"]
        assert fresh["status"] == "TAGGED"

    rows, meta = validate_paginated(api_client.list_shipments(
        AUTHORITY,
        {"dealer_id": world["dealer"]["id"], "is_interstate": "true"}))
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [shipment["id"]]


def test_ship_moves_every_lot_on_the_roster_in_one_call():
    """Shipping is a bulk act on the roster: one call stamps the shipment and
    moves both lots from `TAGGED` to `SHIPPED`. 10:55 is admissible because it
    is at or after the greatest `placed_in_temperature_control_at` on the roster
    (LOT-B's 10:45) and not after the 11:00 clock. A second ship then finds the
    shipment in `SHIPPED` rather than `CREATED`, so the state rung refuses it
    with `ERR_INVALID_SHIPMENT_STATE` and the original stamp survives.

    Design: Corner/endpoints/ship_moves_every_lot_on_the_roster_in_one_call
    """
    world, lot_a, lot_b = _two_tagged_lots_world()
    shipment = dw_assemble_shipment(
        world, [lot_a["id"], lot_b["id"]],
        destination_state="VA", carrier="Coastal Freight")

    first = api_client.ship_shipment(
        shipment["id"], ship_payload(SHIPPED_AT), world["dealer_headers"])

    shipped = validate_success(first, 200)
    assert shipped["status"] == "SHIPPED"
    assert shipped["shipped_at"] == to_millis(SHIPPED_AT)
    assert shipped["lot_count"] == 2
    assert shipped["total_bushels"] == 30
    for lot in (lot_a, lot_b):
        fresh = get_success_data(api_client.get_harvest_lot(lot["id"], OPERATOR))
        assert fresh["status"] == "SHIPPED"

    second = api_client.ship_shipment(
        shipment["id"], ship_payload(iso(2026, 8, 10, 10, 56)),
        world["dealer_headers"])
    validate_error(second, ApiErrorId.ERR_INVALID_SHIPMENT_STATE, 409)

    again = get_success_data(api_client.get_shipment(shipment["id"], AUTHORITY))
    assert again["shipped_at"] == to_millis(SHIPPED_AT)
    assert again["status"] == "SHIPPED"


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------
def test_pagination_limit_above_the_maximum_returns_invalid_request():
    """The declared maximum of 100 is a hard validation, not a clamp. `limit=101`
    and `limit=0` are both request-shape failures answered with
    `ERR_INVALID_REQUEST` at HTTP 400, while `limit=100` succeeds and echoes the
    applied window. An implementation that silently truncated 101 to 100 would
    return a 200 for the first call and fail here.

    Design: Corner/errors/pagination_limit_above_the_maximum_returns_invalid_request
    """
    set_clock(DW_CLOCK)
    for code in (DW_AREA_CODE, "GA-220", "GA-331"):
        create_growing_area(dw_area_payload(code=code))

    above = validate_error(
        api_client.list_growing_areas(AUTHORITY, {"limit": MAX_LIMIT + 1}),
        ApiErrorId.ERR_INVALID_REQUEST, 400)
    assert above["message"].strip(), "a refusal must explain itself"

    below = validate_error(
        api_client.list_growing_areas(AUTHORITY, {"limit": 0}),
        ApiErrorId.ERR_INVALID_REQUEST, 400)
    assert below["message"].strip()

    at_maximum = api_client.list_growing_areas(AUTHORITY, {"limit": MAX_LIMIT})
    rows, meta = validate_paginated(at_maximum)
    assert at_maximum.json()["response_type"] == "array"
    assert len(rows) == 3
    assert meta["limit"] == MAX_LIMIT
    assert meta["offset"] == DEFAULT_OFFSET
    assert meta["total_count"] == 3
    assert meta["has_more"] is False


def test_every_failure_response_carries_an_error_id_and_a_message():
    """The failure envelope is uniform across HTTP families. A 404 lookup miss
    and a 409 business refusal both carry `meta.api_request_id`,
    `meta.api_request_timestamp`, a machine-readable `data.error_id` and a
    non-empty `data.message`, and the two request ids differ because each is
    minted per request. The success envelope for the very same area carries no
    `error_id` key at all.

    Design: Corner/errors/every_failure_response_carries_an_error_id_and_a_message
    """
    set_clock(DW_CLOCK)
    area = create_growing_area(dw_area_payload())

    missing = api_client.get_growing_area(NON_EXISTENT_UUID, AUTHORITY)
    not_found = validate_error(
        missing, ApiErrorId.ERR_GROWING_AREA_NOT_FOUND, 404)
    assert not_found["message"].strip()

    reopened = api_client.reopen_growing_area(
        area["id"], reopen_payload(reopen_note="already open"), AUTHORITY)
    conflict = validate_error(reopened, ApiErrorId.ERR_AREA_ALREADY_OPEN, 409)
    assert conflict["message"].strip()

    metas = [missing.json()["meta"], reopened.json()["meta"]]
    for meta in metas:
        assert isinstance(meta["api_request_id"], str) and meta["api_request_id"]
        assert isinstance(meta["api_request_timestamp"], str)
        assert meta["api_request_timestamp"].strip()
    assert metas[0]["api_request_id"] != metas[1]["api_request_id"]

    success = api_client.get_growing_area(area["id"], AUTHORITY)
    data = validate_success(success, 200)
    assert success.json()["response_type"] == "object"
    assert data["code"] == DW_AREA_CODE
    assert "error_id" not in data


def test_every_not_found_code_is_triggerable_from_an_unknown_id():
    """Each resource family owns a DISTINCT 404 code rather than sharing a
    generic one, so one syntactically valid but unknown id produces a different
    `error_id` for every collection addressed. The recipe listed nine reads; the
    §5 table declares twelve 404 codes, so the sweep is extended to all twelve —
    growing area, deployment and vibrio plan included — each probed through the
    authority-readable GET-by-id its own family declares in §4. None answers
    `ERR_INVALID_REQUEST`: a well-formed id that matches nothing is a lookup
    miss, and §2.7 puts the existence rung after the shape rung, not instead
    of it.

    Design: Corner/errors/every_not_found_code_is_triggerable_from_an_unknown_id
    """
    set_clock(DW_CLOCK)
    probes = (
        (ApiErrorId.ERR_GROWING_AREA_NOT_FOUND, api_client.get_growing_area),
        (ApiErrorId.ERR_LEASE_NOT_FOUND, api_client.get_lease),
        (ApiErrorId.ERR_HATCHERY_NOT_FOUND, api_client.get_hatchery),
        (ApiErrorId.ERR_SEED_LOT_NOT_FOUND, api_client.get_seed_lot),
        (ApiErrorId.ERR_GROWOUT_UNIT_NOT_FOUND, api_client.get_growout_unit),
        (ApiErrorId.ERR_VESSEL_NOT_FOUND, api_client.get_harvest_vessel),
        (ApiErrorId.ERR_AUTHORIZATION_NOT_FOUND,
         api_client.get_harvest_authorization),
        (ApiErrorId.ERR_HARVEST_LOT_NOT_FOUND, api_client.get_harvest_lot),
        (ApiErrorId.ERR_DEALER_NOT_FOUND, api_client.get_dealer),
        (ApiErrorId.ERR_SHIPMENT_NOT_FOUND, api_client.get_shipment),
        (ApiErrorId.ERR_INVESTIGATION_NOT_FOUND,
         api_client.get_illness_investigation),
        (ApiErrorId.ERR_VIBRIO_PLAN_NOT_FOUND,
         api_client.get_vibrio_control_plan),
    )

    seen = []
    for expected, read_by_id in probes:
        body = validate_error(
            read_by_id(NON_EXISTENT_UUID, AUTHORITY), expected, 404)
        assert body["message"].strip(), f"{expected} must carry a message"
        assert body["error_id"] != ApiErrorId.ERR_INVALID_REQUEST
        seen.append(body["error_id"])

    assert seen == [expected for expected, _ in probes]
    assert len(set(seen)) == len(probes), "each family owns a distinct 404 code"


def _world_with_a_second_lease_and_an_idle_unit():
    """The reference world taken to a TAGGED LOT-A — so U1 sits in `HARVESTING`
    under an ACTIVE authorization and the clock reads 2026-08-10T11:00:00Z —
    plus a second APPROVED lease L-2988-02 on the same area and a second, idle
    `DEPLOYED` unit U2 on L-2988-01's plot P2 with current husbandry logs."""
    world = design_world(stage="tagged", lot_overrides={"lot_code": "LOT-A"})
    world["lease2"] = create_approved_lease(
        world["area"]["id"], world["operator_headers"], "2026-12-31",
        dw_lease_payload_overrides(
            lease_code="L-2988-02", plot_codes=["P4", "P5", "P6"]))
    world["unit2"] = dw_deploy_unit(
        world["lease"], world["seed_lot"], world["operator_headers"],
        {"plot_code": "P2", "gear_units": 20, "seed_count_planted": 15000})
    return world


def test_wrong_from_state_transitions_return_the_matching_invalid_state_code():
    """Each state machine reports its own from-state violation with its own code,
    and the §2.7 state rung pre-empts the later coherence and business rungs on
    the same endpoints. Voiding a `HARVESTING` deployment is
    `ERR_INVALID_GROWOUT_UNIT_STATE`; re-tagging an already-`TAGGED` lot is
    `ERR_INVALID_LOT_STATE` rather than the tag-date mismatch it would otherwise
    reach; reinstating a `LISTED` dealer is `ERR_INVALID_DEALER_LISTING_STATE`.
    The authorization naming L-2988-02 over a unit belonging to L-2988-01 gets
    all the way down to `ERR_UNIT_LEASE_MISMATCH` precisely because U2 is idle
    and its husbandry is current, so neither `ERR_UNIT_ALREADY_AUTHORIZED` nor
    `ERR_HUSBANDRY_LAPSED` answers first. Nothing is written by any refusal.

    Design: Corner/errors/wrong_from_state_transitions_return_the_matching_invalid_state_code
    """
    world = _world_with_a_second_lease_and_an_idle_unit()

    mismatch = validate_error(
        api_client.create_harvest_authorization(
            harvest_authorization_payload(
                world["lease2"]["id"], world["unit2"]["id"],
                world["vessel"]["id"], world["dealer"]["id"],
                iso(2026, 8, 11, 6), iso(2026, 8, 11, 18),
                projected_bushels=300),
            world["operator_headers"]),
        ApiErrorId.ERR_UNIT_LEASE_MISMATCH, 409)
    assert mismatch["error_id"] != ApiErrorId.ERR_UNIT_ALREADY_AUTHORIZED
    assert mismatch["error_id"] != ApiErrorId.ERR_HUSBANDRY_LAPSED

    validate_error(
        api_client.void_growout_unit(
            world["unit"]["id"], void_payload(void_note="recorded in error"),
            world["operator_headers"]),
        ApiErrorId.ERR_INVALID_GROWOUT_UNIT_STATE, 409)

    retag = validate_error(
        api_client.tag_harvest_lot(
            world["lot"]["id"],
            tag_payload(date_of(DW_FIRST_OUT), DW_DEALER_CERT_NO),
            world["operator_headers"]),
        ApiErrorId.ERR_INVALID_LOT_STATE, 409)
    assert retag["error_id"] != ApiErrorId.ERR_TAG_HARVEST_DATE_MISMATCH

    validate_error(
        api_client.reinstate_dealer(
            world["dealer"]["id"],
            reinstate_payload(icssl_listed_through="2027-06-30"), AUTHORITY),
        ApiErrorId.ERR_INVALID_DEALER_LISTING_STATE, 409)

    unit = get_success_data(
        api_client.get_growout_unit(world["unit"]["id"], OPERATOR))
    assert unit["status"] == "HARVESTING"
    lot = get_success_data(
        api_client.get_harvest_lot(world["lot"]["id"], OPERATOR))
    assert lot["status"] == "TAGGED"


# --------------------------------------------------------------------------
# Consistency model
# --------------------------------------------------------------------------
def test_closure_effects_are_visible_in_the_same_response_that_causes_them():
    """The consistency model is immediate (§2.10), so the ingest response itself
    already reports `triggered_closure` true and `voided_authorization_count` 1 —
    an implementation that computed the cascade lazily on the next read would
    return a null or a zero here even though the follow-up GETs eventually
    agree. The closure clock is anchored on the event's own `observed_at` of
    10:00 rather than on the 11:00 logical clock, so the reopen eligibility
    lands 96 hours later at 2026-08-14T10:00:00Z, and `classification` is left
    untouched at APPROVED because a rainfall event moves only the other
    dimension.

    Design: Corner/consistency_model/closure_effects_are_visible_in_the_same_response_that_causes_them
    """
    world = design_world(stage="landed", lot_overrides={"lot_code": "LOT-A"})

    response = api_client.create_rainfall_event(
        world["area"]["id"],
        rainfall_event_payload(
            gauge_code="RG-7", observed_at=iso(2026, 8, 10, 10), inches_24h=1.5),
        AUTHORITY)

    event = validate_success(response, 201)
    assert event["triggered_closure"] is True
    assert event["voided_authorization_count"] == 1

    area = get_success_data(
        api_client.get_growing_area(world["area"]["id"], AUTHORITY))
    assert area["harvest_status"] == "CLOSED_RAINFALL"
    assert area["last_closure_started_at"] == to_millis(iso(2026, 8, 10, 10))
    assert area["closure_reopen_eligible_at"] == to_millis(iso(2026, 8, 14, 10))
    assert area["consecutive_clean_samples"] == 0
    assert area["open_authorization_count"] == 0
    assert area["classification"] == "APPROVED"

    authorization = get_success_data(api_client.get_harvest_authorization(
        world["authorization"]["id"], OPERATOR))
    assert authorization["status"] == "VOIDED"
    assert authorization["void_reason"] == "AREA_CLOSURE"

    lot = get_success_data(
        api_client.get_harvest_lot(world["lot"]["id"], OPERATOR))
    assert lot["status"] == "EMBARGOED"
    assert lot["embargo_reason"] == "AREA_CLOSURE"


# --------------------------------------------------------------------------
# Cross-cutting complexity layers
# --------------------------------------------------------------------------
def test_stale_area_version_is_refused_then_the_reread_retry_succeeds():
    """The OCC token is the whole-row `version`, not a per-field one. The first
    decision advances the area by one, a second decision replaying the older
    number is refused with `ERR_STALE_AREA_VERSION` at 412 and writes nothing,
    and the identical payload re-sent with the freshly read number succeeds — so
    `version` moves on every accepted write and never on a refused one.

    Two deviations from the recipe, both forced by the PRD. §3.1 states the
    decision response is the updated area at HTTP 200, not 201. And §3.2 advances
    the area's `version` on every sample ingest that changes a growing-area
    field, so after five ingests the row is not at version 1 and the literal
    2-then-3 pair is unreachable; the increments are therefore asserted relative
    to the version the area actually holds once its samples are on file.

    Design: Corner/cross_cutting_complexity_layers/stale_area_version_is_refused_then_the_reread_retry_succeeds
    """
    area = _area_with_five_clean_samples(conditional_management_plan_on_file=True)
    baseline = area["version"]
    assert area["classification"] == "APPROVED"
    assert area["eligible_classification"] == "APPROVED"

    downgraded = validate_success(api_client.create_classification_decision(
        area["id"],
        classification_decision_payload(
            "RESTRICTED", baseline, decision_note="first downgrade"),
        AUTHORITY), 200)
    assert downgraded["classification"] == "RESTRICTED"
    assert downgraded["version"] == baseline + 1

    stale = validate_error(api_client.create_classification_decision(
        area["id"],
        classification_decision_payload(
            "CONDITIONALLY_APPROVED", baseline,
            decision_note="replay of a stale read"),
        AUTHORITY), ApiErrorId.ERR_STALE_AREA_VERSION, 412)
    assert stale["message"].strip()

    between = get_success_data(api_client.get_growing_area(area["id"], AUTHORITY))
    assert between["version"] == baseline + 1, "a refused write moves nothing"
    assert between["classification"] == "RESTRICTED"

    retried = validate_success(api_client.create_classification_decision(
        area["id"],
        classification_decision_payload(
            "CONDITIONALLY_APPROVED", between["version"],
            decision_note="retry after re-reading"),
        AUTHORITY), 200)
    assert retried["classification"] == "CONDITIONALLY_APPROVED"
    assert retried["version"] == baseline + 2
    assert retried["harvest_status"] == "OPEN"
    assert retried["eligible_classification"] == "APPROVED"


def test_stale_dealer_version_is_refused_then_the_reread_retry_succeeds():
    """The second OCC rule guards a different entity through a differently named
    field and a different error id. Replaying `expected_dealer_version` 1 after a
    renewal has already advanced the dealer to version 2 is refused with
    `ERR_STALE_DEALER_VERSION`, never with `ERR_STALE_AREA_VERSION`, so an
    implementation honouring only `expected_area_version` fails here. The refused
    renewal leaves the incumbent certification untouched, the re-read retry
    replaces both dates, and `recall_strike_count` never moves because renewals
    do not touch strikes.

    Design: Corner/cross_cutting_complexity_layers/stale_dealer_version_is_refused_then_the_reread_retry_succeeds
    """
    dealer = create_dealer(dw_dealer_payload())
    assert dealer["version"] == 1
    stale_version = dealer["version"]

    listed = validate_success(api_client.renew_dealer_certification(
        dealer["id"],
        dealer_renewal_payload(stale_version, "2027-06-30",
                               icssl_listed_through="2027-06-30"),
        AUTHORITY), 200)
    assert listed["version"] == 2
    assert listed["listing_status"] == "LISTED"

    refused = validate_error(api_client.renew_dealer_certification(
        dealer["id"],
        dealer_renewal_payload(stale_version, "2028-06-30",
                               icssl_listed_through="2028-06-30"),
        AUTHORITY), ApiErrorId.ERR_STALE_DEALER_VERSION, 412)
    assert refused["error_id"] != ApiErrorId.ERR_STALE_AREA_VERSION

    between = get_success_data(api_client.get_dealer(dealer["id"], AUTHORITY))
    assert between["version"] == 2
    assert between["certified_through"] == "2027-06-30"
    assert between["listing_status"] == "LISTED"

    retried = validate_success(api_client.renew_dealer_certification(
        dealer["id"],
        dealer_renewal_payload(between["version"], "2028-06-30",
                               icssl_listed_through="2028-06-30"),
        AUTHORITY), 200)
    assert retried["certified_through"] == "2028-06-30"
    assert retried["icssl_listed_through"] == "2028-06-30"
    assert retried["version"] == 3
    assert retried["recall_strike_count"] == 0


def test_the_fifth_failing_sample_is_what_fires_the_downgrade_sweep():
    """The sweep is gated on a cumulative count AND a threshold together. After
    four 200-MPN samples the area is still APPROVED and OPEN with
    `eligible_classification` INSUFFICIENT_DATA, because the window count is
    below the five-sample minimum. The fifth identical sample satisfies the
    minimum and the 14.0 geometric-mean threshold in the same instant, so the
    downgrade lands on exactly that call: 10**2.3010 rounds to 200.0, the
    zero standard deviation puts the 90th percentile at 200.0 too, and 200.0
    above the restricted ceiling of 88.0 makes PROHIBITED the eligible answer
    and therefore the swept classification.

    Design: Corner/cross_cutting_complexity_layers/the_fifth_failing_sample_is_what_fires_the_downgrade_sweep
    """
    set_clock(DW_CLOCK)
    area = create_growing_area(dw_area_payload())
    for day in CLEAN_SAMPLE_DATES[:4]:
        ingest_water_sample(area["id"], {
            "collected_at": day + "T09:00:00Z", "fecal_coliform_mpn": 200})

    before = get_success_data(api_client.get_growing_area(area["id"], AUTHORITY))
    assert before["accepted_sample_count"] == 4
    assert before["classification"] == "APPROVED"
    assert before["harvest_status"] == "OPEN"
    assert before["eligible_classification"] == "INSUFFICIENT_DATA"

    fifth = validate_success(api_client.create_water_sample(
        area["id"],
        water_sample_payload(collected_at=CLEAN_SAMPLE_DATES[4] + "T09:00:00Z",
                             fecal_coliform_mpn=200),
        AUTHORITY), 201)
    assert fifth["sample_status"] == "ACCEPTED"

    after = get_success_data(api_client.get_growing_area(area["id"], AUTHORITY))
    assert after["accepted_sample_count"] == 5
    assert after["geometric_mean_mpn"] == 200.0
    assert after["p90_mpn"] == 200.0
    assert after["eligible_classification"] == "PROHIBITED"
    assert after["classification"] == "PROHIBITED"
    assert after["harvest_status"] == "CLOSED_SAMPLE_FAILURE"
    assert after["consecutive_clean_samples"] == 0

    summary = validate_success(api_client.get_classification_summary(
        area["id"], AUTHORITY, {"variant": "SYSTEMATIC_RANDOM"}), 200)
    assert summary["sample_count"] == 5
    assert summary["geometric_mean_mpn"] == 200.0
