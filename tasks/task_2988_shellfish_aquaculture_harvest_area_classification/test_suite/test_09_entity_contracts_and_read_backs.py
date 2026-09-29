"""Entity contracts, declared defaults and read-back fidelity.

Covers the structural half of the specification rather than any one workflow:
the success and error envelopes and the `req_` request identifier (PRD §2.2),
the pagination fields and their defaults together with the water-sample journal
ordering (PRD §2.3), the identity/timestamp/version quartet and the append-only
carve-out for `WaterSample` and `HusbandryLog` (PRD §2.4), the per-entity
not-found errors for both path and body references (PRD §2.6), the request-shape
rung of the validation ladder (PRD §2.7 rung 5), growing-area registration with
its five optional configuration defaults and its born-permissive counters
(PRD §3.1), the supersession rule and the statistics window (PRD §3.2), the
required lease inputs and the two lease counters (PRD §3.4), the seed
allocation counters (PRD §3.5), the deployment's derived husbandry fields and
the seed-lot/lease coherence rung (PRD §3.6), vessel registration inputs
(PRD §3.7) and vibrio-plan publication inputs (PRD §3.8).
"""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    OPERATOR_USER_ID,
    TEST_USERS,
    api_client,
    assert_growing_area,
    assert_growout_unit,
    assert_husbandry_log,
    assert_millis_instant,
    assert_water_sample,
    create_approved_lease,
    create_area_with_accepted_samples,
    create_growing_area,
    create_hatchery,
    design_world,
    dw_area_payload,
    dw_hatchery_payload,
    dw_lease_payload_overrides,
    dw_unit_payload_overrides,
    dw_walk_seed_lot,
    get_success_data,
    growing_area_payload,
    growout_unit_payload,
    harvest_vessel_payload,
    hatchery_payload,
    husbandry_log_payload,
    ingest_water_sample,
    iso,
    lease_payload,
    set_clock,
    to_millis,
    validate_error,
    validate_paginated,
    validate_success,
    vibrio_control_plan_payload,
    water_sample_payload,
)

AUTHORITY = TEST_USERS["authority_headers"]
OPERATOR = TEST_USERS["operator_headers"]

CLOCK = iso(2026, 8, 1)


def _assert_object_envelope(response):
    """PRD §2.2: a single-resource success body carries `response_type` "object"
    and a `meta` holding a server-generated `api_request_id` that starts with
    `req_` beside a millisecond-precision `api_request_timestamp`."""
    body = response.json()
    assert body["response_type"] == "object", (
        f'response_type must be "object" for a single resource, '
        f'got {body["response_type"]!r}'
    )
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), (
        f'api_request_id must start with "req_", got {meta["api_request_id"]!r}'
    )
    assert_millis_instant(meta["api_request_timestamp"], "meta.api_request_timestamp")


def test_create_growing_area_returns_all_declared_fields_in_the_success_envelope():
    """One registration carrying every declared input answers HTTP 201 with the
    whole GrowingArea in the `data` block. Both status dimensions start
    permissive and independent — `classification` APPROVED on the sanitary axis
    and `harvest_status` OPEN on the availability axis — and the four statistics
    fields hold their empty-database values: the three counters are 0 while
    `geometric_mean_mpn` and `p90_mpn` are null (no accepted samples) and
    `eligible_classification` reads INSUFFICIENT_DATA because the window holds
    fewer than the five samples a decision needs. The two closure instants are
    null because the area has never closed, and `version` is 1.

    Design: Corner/entities/create_growing_area_returns_the_full_entity_in_the_success_envelope
    """
    set_clock(CLOCK)

    response = api_client.create_growing_area(dw_area_payload(), AUTHORITY)

    data = validate_success(response, 201)
    _assert_object_envelope(response)
    assert_growing_area(data)
    assert data["code"] == "GA-114"
    assert data["water_body"] == "Pamlico Sound"
    assert data["classification"] == "APPROVED"
    assert data["harvest_status"] == "OPEN"
    assert data["rainfall_closure_threshold_in"] == 1.00
    assert data["rainfall_closure_hours"] == 96
    assert data["reopen_sample_count_required"] == 3
    assert data["clean_sample_mpn_limit"] == 14.0
    assert data["conditional_management_plan_on_file"] is False
    assert data["accepted_sample_count"] == 0
    assert data["consecutive_clean_samples"] == 0
    assert data["open_authorization_count"] == 0
    assert data["geometric_mean_mpn"] is None
    assert data["p90_mpn"] is None
    assert data["eligible_classification"] == "INSUFFICIENT_DATA"
    assert data["last_closure_started_at"] is None
    assert data["closure_reopen_eligible_at"] is None
    assert isinstance(data["id"], str) and data["id"]
    assert data["version"] == 1


def test_get_growing_area_returns_the_non_default_configuration_as_stored():
    """GA-220 is registered with a configuration that contradicts every declared
    default — 2.50 inches instead of 1.00, 48 closure hours instead of 96, two
    reopen samples instead of three, a 10.0 clean limit instead of 14.0, and a
    conditional management plan on file instead of absent. The read path returns
    exactly those five figures rather than re-deriving them from the constants,
    and `version` is still 1 because a read is not a mutation.

    Design: Corner/entities/get_growing_area_returns_the_stored_configuration
    """
    set_clock(CLOCK)
    area = create_growing_area(dw_area_payload(
        code="GA-220",
        rainfall_closure_threshold_in=2.5,
        rainfall_closure_hours=48,
        reopen_sample_count_required=2,
        clean_sample_mpn_limit=10.0,
        conditional_management_plan_on_file=True,
    ))

    response = api_client.get_growing_area(area["id"], AUTHORITY)

    data = validate_success(response, 200)
    _assert_object_envelope(response)
    assert data["code"] == "GA-220"
    assert data["rainfall_closure_threshold_in"] == 2.50
    assert data["rainfall_closure_hours"] == 48
    assert data["reopen_sample_count_required"] == 2
    assert data["clean_sample_mpn_limit"] == 10.0
    assert data["conditional_management_plan_on_file"] is True
    assert data["classification"] == "APPROVED"
    assert data["harvest_status"] == "OPEN"
    assert data["version"] == 1


def test_growing_area_pages_carry_the_whole_match_count_in_total_count():
    """Three areas are on file. `total_count` is the number of rows matching the
    filters *before* the page window is applied, so both pages report 3 rather
    than the size of the page they returned. `has_more` is true exactly when
    offset plus the rows in this page is below `total_count`: true for the first
    page (0 + 2 < 3) and false for the second (2 + 1 == 3). `limit` and `offset`
    echo the values actually applied, and the two pages partition the collection
    with no row repeated.

    Design: Corner/entities/list_growing_areas_paginates_with_total_count_and_has_more
    """
    set_clock(CLOCK)
    for code in ("GA-114", "GA-115", "GA-116"):
        create_growing_area(dw_area_payload(code=code))

    first_rows, first_meta = validate_paginated(
        api_client.list_growing_areas(AUTHORITY, params={"limit": 2, "offset": 0}))
    second_rows, second_meta = validate_paginated(
        api_client.list_growing_areas(AUTHORITY, params={"limit": 2, "offset": 2}))

    assert len(first_rows) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert len(second_rows) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert second_meta["offset"] == 2
    codes = [row["code"] for row in first_rows] + [row["code"] for row in second_rows]
    assert sorted(codes) == ["GA-114", "GA-115", "GA-116"]
    assert len(set(codes)) == 3


def test_each_addressed_entity_has_its_own_not_found_error():
    """The existence rung fires for an identifier in the path and for an
    identifier inside a request body alike, and the error identifies the entity
    type that was being resolved rather than being one generic 404. The same
    never-minted uuid therefore yields three different identifiers: it is a
    missing deployment when addressed as a grow-out unit path parameter, a
    missing growing area when named as `growing_area_id` while drafting a lease,
    and a missing vibrio control plan when addressed as a plan. The lease draft
    is a complete, well-shaped payload, so nothing below the existence rung is
    reached and no lease row survives the attempt.

    Design: Corner/entities/unknown_ids_return_the_matching_not_found_error
    """
    set_clock(CLOCK)

    unit_response = api_client.get_growout_unit(NON_EXISTENT_UUID, OPERATOR)
    lease_response = api_client.create_lease(
        lease_payload(
            NON_EXISTENT_UUID,
            lease_code="L-2988-99",
            requested_acreage=5.0,
            plot_codes=["P1"],
            gear_types_permitted=["BOTTOM"],
            authorized_gear_units=10,
        ),
        OPERATOR,
    )
    plan_response = api_client.get_vibrio_control_plan(NON_EXISTENT_UUID, AUTHORITY)

    for response, error_id in (
        (unit_response, ApiErrorId.ERR_GROWOUT_UNIT_NOT_FOUND),
        (lease_response, ApiErrorId.ERR_GROWING_AREA_NOT_FOUND),
        (plan_response, ApiErrorId.ERR_VIBRIO_PLAN_NOT_FOUND),
    ):
        error = validate_error(response, error_id, 404)
        assert error["message"].strip()
        assert response.json()["response_type"] == "error"
    _rows, meta = validate_paginated(api_client.list_leases(AUTHORITY))
    assert meta["total_count"] == 0


def test_lease_without_authorized_gear_units_is_rejected_and_persists_nothing():
    """Every one of the six lease inputs is required — the gear ceiling has no
    declared default, unlike the five growing-area configuration fields — so a
    draft that omits `authorized_gear_units` fails the request-shape rung with
    ERR_INVALID_REQUEST at HTTP 400. Nothing above that rung objects: the
    identity headers are good, FarmOperator is authorised for the endpoint and
    the named growing area exists. No DRAFT lease is persisted, which the
    unfiltered lease list confirms (the endpoint's growing-area filter parameter
    is described but not spelled by the PRD, and the database is empty apart
    from this area, so the unfiltered count is the stronger read).

    Design: Corner/entities/create_lease_missing_required_authorized_gear_units_is_rejected
    """
    set_clock(CLOCK)
    area = create_growing_area(dw_area_payload())
    payload = lease_payload(
        area["id"],
        lease_code="L-2988-01",
        requested_acreage=5.0,
        plot_codes=["P1", "P2", "P3"],
        gear_types_permitted=["BOTTOM"],
    )
    payload.pop("authorized_gear_units")

    response = api_client.create_lease(payload, OPERATOR)

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)
    _rows, meta = validate_paginated(api_client.list_leases(AUTHORITY))
    assert meta["total_count"] == 0


def test_growing_area_registration_applies_the_five_declared_defaults():
    """A registration naming only `code` and `water_body` leaves all five
    optional configuration fields unsupplied, and the response carries the five
    declared defaults rather than nulls: 1.00 inch of rain over 24 hours, a
    96-hour minimum closure, three consecutive clean samples to reopen, a 14.0
    MPN clean-sample limit, and no conditional management plan on file. The
    defaults are applied at creation, so the defaulted 14.0 clean limit is
    already the same figure the APPROVED classification tier compares against.

    Design: Corner/entities/create_growing_area_without_optional_config_applies_the_declared_defaults
    """
    set_clock(CLOCK)

    response = api_client.create_growing_area(
        growing_area_payload(code="GA-301", water_body="Core Sound"), AUTHORITY)

    data = validate_success(response, 201)
    assert_growing_area(data)
    assert data["rainfall_closure_threshold_in"] == 1.00
    assert data["rainfall_closure_hours"] == 96
    assert data["reopen_sample_count_required"] == 3
    assert data["clean_sample_mpn_limit"] == 14.0
    assert data["conditional_management_plan_on_file"] is False
    assert data["classification"] == "APPROVED"
    assert data["harvest_status"] == "OPEN"


def test_water_sample_list_applies_the_default_limit_ten_offset_zero():
    """Twelve accepted samples are on file and the client sends neither `limit`
    nor `offset`. The endpoint applies the declared defaults rather than
    returning the whole collection: exactly 10 rows come back, `meta` echoes
    limit 10 and offset 0, `total_count` is the full 12 and `has_more` is true.
    The journal ordering override puts the newest `collected_at` first, so row
    one is the 2026-07-12 sample. Every sample reads 2 MPN, so the recomputed
    SYSTEMATIC_RANDOM geometric mean is 2.0 — not strictly greater than the 14.0
    sweep trigger — and the area is left APPROVED and OPEN with all twelve
    samples counted.

    Design: Corner/entities/list_water_samples_without_pagination_params_applies_limit_ten_offset_zero
    """
    set_clock(CLOCK)
    area, _samples = create_area_with_accepted_samples(
        [2] * 12, station_code="ST-1", start_date=(2026, 7, 1),
        area_overrides=dw_area_payload(),
    )

    rows, meta = validate_paginated(api_client.list_water_samples(area["id"], AUTHORITY))

    assert len(rows) == 10
    assert meta["total_count"] == 12
    assert meta["has_more"] is True
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert rows[0]["collected_at"] == to_millis(iso(2026, 7, 12, 9))
    read_back = get_success_data(api_client.get_growing_area(area["id"], AUTHORITY))
    assert read_back["classification"] == "APPROVED"
    assert read_back["harvest_status"] == "OPEN"
    assert read_back["accepted_sample_count"] == 12
    assert read_back["geometric_mean_mpn"] == 2.0


def test_deployment_recomputes_the_lease_and_seed_lot_counters():
    """One deployment supplies `gear_units` 40 and `seed_count_planted` 25000 and
    nothing else, yet three entities' computed fields move. On the lease,
    `deployed_gear_units` becomes the 40 units now in the water while
    `royalty_accrued_cents` stays 0 because no lot has been landed. On the seed
    lot, `allocated_seed_count` becomes 25000 and `unallocated_seed_count` the
    35000 remaining of 60000 survivors, `survival_rate_pct` still reads the
    60.00 derived at nursery completion, and the lot stays READY_FOR_PLANTING
    because seed is left unallocated. On the new unit itself,
    `husbandry_current` is false with both currency instants null, because no
    husbandry log exists yet, and `mortality_count_total` is 0.

    Design: Corner/entities/lease_and_seed_lot_counters_are_recomputed_from_the_deployment
    """
    world = design_world(stage="seed")

    response = api_client.create_growout_unit(
        growout_unit_payload(
            world["lease"]["id"], world["seed_lot"]["id"],
            **dw_unit_payload_overrides()),
        OPERATOR,
    )

    unit = validate_success(response, 201)
    assert_growout_unit(unit)
    assert unit["status"] == "DEPLOYED"
    assert unit["retrieved_on"] is None
    assert unit["void_reason"] is None
    assert unit["husbandry_current"] is False
    assert unit["last_inspection_at"] is None
    assert unit["last_predator_control_at"] is None
    assert unit["mortality_count_total"] == 0
    lease = get_success_data(api_client.get_lease(world["lease"]["id"], AUTHORITY))
    seed_lot = get_success_data(
        api_client.get_seed_lot(world["seed_lot"]["id"], AUTHORITY))
    assert lease["deployed_gear_units"] == 40
    assert lease["royalty_accrued_cents"] == 0
    assert seed_lot["allocated_seed_count"] == 25000
    assert seed_lot["unallocated_seed_count"] == 35000
    assert seed_lot["survival_rate_pct"] == 60.00
    assert seed_lot["status"] == "READY_FOR_PLANTING"


def test_husbandry_log_stamps_the_acting_operator_and_moves_the_unit_fields():
    """`performed_by_user_id` is never a request input — the log is stamped with
    the acting `X-User-ID`, which here is the operator identity that drafted the
    lease. The log is an append-only journal record, so neither `updated_at` nor
    `version` appears on it, and the two predator fields stay null because an
    INSPECTION log ignores them. The single log immediately recomputes the
    deployment's derived fields: `last_inspection_at` becomes the log's
    `performed_at` and `mortality_count_total` the 3 dead animals counted. Yet
    `husbandry_current` stays false: this is BOTTOM gear, whose predator test is
    not satisfied automatically and still has `last_predator_control_at` null.

    Design: Corner/entities/husbandry_log_stamps_the_acting_operator_id
    """
    world = design_world(stage="unit", husbandry=False)
    performed_at = iso(2026, 7, 20, 12)

    response = api_client.create_husbandry_log(
        world["unit"]["id"],
        husbandry_log_payload(
            "INSPECTION", performed_at,
            mortality_count=3, notes="routine walk of the bottom lease"),
        OPERATOR,
    )

    log = validate_success(response, 201)
    assert_husbandry_log(log)
    assert log["performed_by_user_id"] == OPERATOR_USER_ID
    assert log["growout_unit_id"] == world["unit"]["id"]
    assert log["log_type"] == "INSPECTION"
    assert log["performed_at"] == to_millis(performed_at)
    assert log["mortality_count"] == 3
    assert log["predator_species"] is None
    assert log["control_method"] is None
    assert "version" not in log
    unit = get_success_data(
        api_client.get_growout_unit(world["unit"]["id"], OPERATOR))
    assert unit["last_inspection_at"] == to_millis(performed_at)
    assert unit["mortality_count_total"] == 3
    assert unit["last_predator_control_at"] is None
    assert unit["husbandry_current"] is False


def test_charset_range_and_enum_violations_all_answer_invalid_request():
    """Three different kinds of malformed field converge on the one request-shape
    rung. `state_code` "nc" is the right length and the right JSON type but the
    wrong charset, because the field is exactly two uppercase letters.
    `season_month` 13 is an integer outside the declared 1-12 calendar range.
    `refrigeration_type` GLACIER is a plausible-looking string that is not a
    member of the declared enumeration. Each is ERR_INVALID_REQUEST at HTTP 400
    rather than a domain-specific 409, and none of the three rows is persisted,
    which the empty vibrio-plan collection confirms.

    Design: Corner/entities/type_constraint_violations_on_three_endpoints_are_rejected
    """
    set_clock(CLOCK)

    hatchery_response = api_client.create_hatchery(
        hatchery_payload(name="Sound Hatchery", state_code="nc"), AUTHORITY)
    plan_response = api_client.create_vibrio_control_plan(
        vibrio_control_plan_payload(13, high_water_temp_c=23.0), AUTHORITY)
    vessel_response = api_client.create_harvest_vessel(
        harvest_vessel_payload(name="Miss Pamlico", refrigeration_type="GLACIER"),
        OPERATOR)

    for response in (hatchery_response, plan_response, vessel_response):
        error = validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)
        assert error["message"].strip()
    _rows, meta = validate_paginated(
        api_client.list_vibrio_control_plans(AUTHORITY))
    assert meta["total_count"] == 0


def test_resampling_a_station_on_the_same_date_supersedes_the_earlier_row():
    """A water sample is append-only, so a correction is a second insert rather
    than an update: there is no PATCH and no DELETE for the journal. The later
    row at the same station on the same calendar date wins, arriving ACCEPTED
    with its own 9 MPN and carrying no `version` field. The earlier 09:00 row is
    not rewritten -- it keeps `collected_at` 09:00 and `fecal_coliform_mpn` 5 --
    only its `sample_status` flips to SUPERSEDED, which drops it out of the
    statistics window. So `accepted_sample_count` is 1 rather than 2, the
    geometric mean is the surviving 9.0, and one sample is still short of the
    five a decision needs, leaving `eligible_classification` INSUFFICIENT_DATA.
    The design read the two statuses through `?sample_status=` filters; the PRD
    declares no filter parameter on this endpoint, so the assertions below read
    the unfiltered journal, which the newest-first ordering makes unambiguous.

    Design: Corner/entities/resampling_a_station_on_the_same_date_supersedes_the_earlier_row
    """
    set_clock(CLOCK)
    area = create_growing_area(dw_area_payload())
    ingest_water_sample(area["id"], {
        "station_code": "ST-1", "collected_at": iso(2026, 7, 10, 9),
        "fecal_coliform_mpn": 5, "water_temp_c": 24.0, "salinity_ppt": 30.0})

    response = api_client.create_water_sample(
        area["id"],
        water_sample_payload(
            station_code="ST-1", collected_at=iso(2026, 7, 10, 15),
            fecal_coliform_mpn=9, water_temp_c=24.0, salinity_ppt=30.0),
        AUTHORITY,
    )

    sample = validate_success(response, 201)
    assert_water_sample(sample)
    assert sample["sample_status"] == "ACCEPTED"
    assert sample["fecal_coliform_mpn"] == 9
    assert "version" not in sample
    assert "updated_at" not in sample
    rows, meta = validate_paginated(
        api_client.list_water_samples(area["id"], AUTHORITY))
    assert meta["total_count"] == 2
    assert rows[0]["collected_at"] == to_millis(iso(2026, 7, 10, 15))
    assert rows[0]["sample_status"] == "ACCEPTED"
    assert rows[1]["collected_at"] == to_millis(iso(2026, 7, 10, 9))
    assert rows[1]["sample_status"] == "SUPERSEDED"
    assert rows[1]["fecal_coliform_mpn"] == 5
    read_back = get_success_data(api_client.get_growing_area(area["id"], AUTHORITY))
    assert read_back["accepted_sample_count"] == 1
    assert read_back["geometric_mean_mpn"] == 9.0
    assert read_back["eligible_classification"] == "INSUFFICIENT_DATA"
    assert read_back["classification"] == "APPROVED"
    assert read_back["harvest_status"] == "OPEN"


def test_deploying_seed_from_another_lease_is_a_seed_lot_lease_mismatch():
    """The entity topology is flat, so a deployment names its lease and its seed
    lot as two independent body fields and nothing in the URL forces them to
    agree. Both parents exist, both leases are APPROVED and held by the same
    operator, and the seed lot is READY_FOR_PLANTING with all 60000 survivors
    unallocated -- yet the lot belongs to L-2988-02 while the deployment names
    L-2988-01, which the referential-coherence rung refuses with
    ERR_SEED_LOT_LEASE_MISMATCH at HTTP 409. Two neighbouring rules are
    deliberately not the answer: the plot P1 is a plot of the named lease so the
    plot check is satisfied, and 25000 seed is well inside the lot's unallocated
    balance so the allocation ceiling further down the ladder is never reached.
    The refusal persists nothing, which the unfiltered deployment list confirms
    (the PRD does not spell a lease filter parameter for that endpoint), and
    neither counter on either parent moves.

    Design: Corner/entities/deploying_with_a_seed_lot_from_another_lease_is_rejected
    """
    world = design_world(stage="lease")
    lease_b = create_approved_lease(
        world["area"]["id"], OPERATOR, "2026-12-31",
        dw_lease_payload_overrides(lease_code="L-2988-02"))
    hatchery = create_hatchery(dw_hatchery_payload())
    seed_lot_b = dw_walk_seed_lot(lease_b, hatchery, "plantable", OPERATOR)
    assert seed_lot_b["lease_id"] == lease_b["id"]
    assert seed_lot_b["unallocated_seed_count"] == 60000

    response = api_client.create_growout_unit(
        growout_unit_payload(
            world["lease"]["id"], seed_lot_b["id"], **dw_unit_payload_overrides()),
        OPERATOR,
    )

    error = validate_error(response, ApiErrorId.ERR_SEED_LOT_LEASE_MISMATCH, 409)
    assert error["error_id"] != ApiErrorId.ERR_PLOT_NOT_IN_LEASE
    assert error["error_id"] != ApiErrorId.ERR_SEED_ALLOCATION_EXCEEDED
    _rows, meta = validate_paginated(api_client.list_growout_units(OPERATOR))
    assert meta["total_count"] == 0
    lease_a = get_success_data(api_client.get_lease(world["lease"]["id"], AUTHORITY))
    read_back = get_success_data(api_client.get_seed_lot(seed_lot_b["id"], AUTHORITY))
    assert lease_a["deployed_gear_units"] == 0
    assert read_back["allocated_seed_count"] == 0
    assert read_back["unallocated_seed_count"] == 60000
    assert read_back["status"] == "READY_FOR_PLANTING"
