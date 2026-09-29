"""Entity-level corners: envelopes, defaults, computed fields and uniqueness.

These probe the shape of a single resource rather than a workflow - what a
create echoes, what it derives, what it defaults, what it refuses and what it
never lets a client write.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    LINE_OPERATOR_HEADERS,
    PLANT_ADMIN_HEADERS,
    QA_MANAGER_HEADERS,
    QA_TECHNICIAN_HEADERS,
    SANITATION_TECH_HEADERS,
    SHIPPING_CLERK_HEADERS,
    USER_QA_TECH_C,
    USER_RECEIVING_CLERK,
    USER_SANITATION_TECH_B,
    make_qa_technician_headers,
    make_receiving_clerk_headers,
    make_sanitation_tech_headers,
)

HTTP_CREATED = 201

# A lot whose field evidence carries no penalty at all.
CLEAN_LOT_OVERRIDES = {
    "grower_code": "GRW-910",
    "ranch_block": "B10",
    "harvest_datetime": "2026-08-01T08:00:00Z",
    "water_source": c.WATER_WELL,
}
UNDECLARED_COMMODITY_CLASS = "HERB"
DATE_ONLY_HARVEST = "2026-08-01"
NEGATIVE_COMPONENT_COUNT = -3

# Two readings drawn at the very same instant on an unloaded flume.
FIRST_READING_AT = "2026-08-02T05:30:00Z"
FIRST_READING_PPM = 24.0
SECOND_READING_PPM = 19.0
NO_TOPUP_REQUIRED = 0.0
SECOND_READING_TOPUP = 1.0
UNLOADED_INDEX = 0.000

# The one-second window that proves the interval rule is strictly-greater.
WINDOW_START_AT = "2026-08-03T07:00:00Z"
WINDOW_INVERTED_END_AT = "2026-08-03T06:00:00Z"
WINDOW_ONE_SECOND_END_AT = "2026-08-03T07:00:01Z"


def test_a_new_product_echoes_its_inputs_and_mints_its_audit_fields(api):
    """Version 1, both audit instants, and the computed counter already present.

    PRD: Endpoints that create a new resource respond with HTTP 201 and return the created resource in `data`.
    PRD: Most resources also carry three system-managed audit fields: `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording when the row was first written; `updated_at`, an ISO 8601 UTC timestamp in the same format recording the most recent mutation; and `version`, an integer that begins at 1 and increases by exactly 1 on every mutation of that row.
    PRD: The server maintains `active_spec_count` on the product, starting at 0, as the number of that product's specification revisions whose `status` is `ACTIVE`.

    Design: Corner/entities/corner_product_create_returns_envelope_and_common_fields
    """
    response = api.create_product(f.product_payload(), PLANT_ADMIN_HEADERS)
    product = validate_success(response, expected_status=HTTP_CREATED)
    a.assert_object_envelope(response)

    assert product["code"] == c.PRODUCT_CODE
    assert product["name"] == c.PRODUCT_NAME
    assert product["commodity_class"] == c.COMMODITY_LEAFY
    assert product["allergen_group"] == c.ALLERGEN_NONE
    assert product["min_antimicrobial_ppm"] == c.PRODUCT_MIN_ANTIMICROBIAL_PPM
    assert product["min_yield_pct"] == c.PRODUCT_MIN_YIELD_PCT
    assert product["hold_and_release_required"] is True

    a.assert_common_fields(product, "product")
    a.assert_version_is(product, 1, "product")
    a.assert_created_equals_updated(product, "product")
    assert product["active_spec_count"] == 0


def test_the_product_page_reports_its_total_and_whether_more_remain(api):
    """Two pages over three rows, with no row repeated between them.

    PRD: The `meta` object of a list response carries `limit`, `offset`, `total_count` and `has_more`, where `total_count` is the number of rows matching the filters before pagination is applied.
    PRD: `offset` is the number of rows to skip and defaults to 0. Unless a specific collection declares otherwise, list results are ordered by `created_at` ascending.

    Design: Corner/entities/corner_products_list_pagination_reports_total_and_has_more
    """
    fx.set_clock(api, c.CLOCK_MASTER_DATA)
    fx.create_product(api)
    fx.create_product(api, **f.celery_product_payload())
    fx.create_product(api, **f.slaw_product_payload())

    first_page = a.assert_page(
        api.list_products(QA_MANAGER_HEADERS, {"limit": 2, "offset": 0}),
        expected_total=3,
        expected_has_more=True,
        expected_count=2,
        expected_limit=2,
        expected_offset=0,
    )
    last_page = a.assert_page(
        api.list_products(QA_MANAGER_HEADERS, {"limit": 2, "offset": 2}),
        expected_total=3,
        expected_has_more=False,
        expected_count=1,
        expected_offset=2,
    )

    codes = [row["code"] for row in first_page] + [row["code"] for row in last_page]
    assert len(set(codes)) == 3, f"the two pages overlapped: {codes}"
    assert set(codes) == {c.PRODUCT_CODE, "CELR-DICE", "SLAW-MIX"}


def test_each_unknown_path_identifier_reports_its_own_entity(api):
    """Twelve routes, twelve distinct not-found identifiers.

    PRD: Identifiers embedded in the URL are resolved left to right, and always before any body field is resolved. The first identifier that names nothing produces its own not-found error: `ERR_PRODUCT_NOT_FOUND`, `ERR_GROWER_LOT_NOT_FOUND`, `ERR_RAW_RECEIPT_NOT_FOUND`, `ERR_LINE_NOT_FOUND`, `ERR_WASH_SYSTEM_NOT_FOUND`, `ERR_PROCESS_RUN_NOT_FOUND`, `ERR_LOT_CONSUMPTION_NOT_FOUND`, `ERR_FINISHED_CASE_NOT_FOUND`, `ERR_HOLD_RECORD_NOT_FOUND`, `ERR_SANITATION_EVENT_NOT_FOUND`, `ERR_ENVIRONMENTAL_SWAB_NOT_FOUND` or `ERR_CORRECTIVE_ACTION_NOT_FOUND`, each with HTTP 404.
    PRD: The `error_id` is a unique, machine-readable string that identifies the specific error.

    Design: Corner/entities/corner_unknown_path_id_returns_entity_specific_not_found
    """
    missing = c.UNKNOWN_ID
    attempts = (
        (api.get_product(missing, QA_MANAGER_HEADERS), ApiErrorId.PRODUCT_NOT_FOUND),
        (api.get_grower_lot(missing, QA_MANAGER_HEADERS), ApiErrorId.GROWER_LOT_NOT_FOUND),
        (api.get_raw_receipt(missing, QA_MANAGER_HEADERS), ApiErrorId.RAW_RECEIPT_NOT_FOUND),
        (api.get_line(missing, QA_MANAGER_HEADERS), ApiErrorId.LINE_NOT_FOUND),
        (api.get_wash_system(missing, QA_MANAGER_HEADERS), ApiErrorId.WASH_SYSTEM_NOT_FOUND),
        (api.get_process_run(missing, QA_MANAGER_HEADERS), ApiErrorId.PROCESS_RUN_NOT_FOUND),
        (
            api.void_lot_consumption(missing, f.void_payload(1), LINE_OPERATOR_HEADERS),
            ApiErrorId.LOT_CONSUMPTION_NOT_FOUND,
        ),
        (
            api.ship_finished_case(missing, SHIPPING_CLERK_HEADERS),
            ApiErrorId.FINISHED_CASE_NOT_FOUND,
        ),
        (api.release_hold(missing, QA_MANAGER_HEADERS), ApiErrorId.HOLD_RECORD_NOT_FOUND),
        (
            api.start_sanitation_event(missing, SANITATION_TECH_HEADERS),
            ApiErrorId.SANITATION_EVENT_NOT_FOUND,
        ),
        (
            api.record_swab_result(
                missing, f.swab_result_payload(c.SWAB_RESULT_NEGATIVE), QA_TECHNICIAN_HEADERS
            ),
            ApiErrorId.ENVIRONMENTAL_SWAB_NOT_FOUND,
        ),
        (
            api.start_corrective_action(missing, QA_TECHNICIAN_HEADERS),
            ApiErrorId.CORRECTIVE_ACTION_NOT_FOUND,
        ),
    )
    for response, expected in attempts:
        validate_error(response, expected)
        a.assert_error_body_shape(response, expected.value)


def test_a_create_missing_a_required_field_stores_nothing(api):
    """The minimum yield is required, and its absence is a shape failure.

    PRD: The body must be a JSON object; every required input field must be present and non-null; every enumerated field must carry a declared member; every numeric field must be a number of the permitted sign and range; and every instant field must be an ISO 8601 UTC timestamp. Any violation is `ERR_INVALID_REQUEST` (HTTP 400). Unknown fields are ignored rather than rejected.
    PRD: Two acceptance figures complete the record: `min_yield_pct`, the lowest acceptable ratio of case weight out to raw pounds in, greater than 0 and at most 100 with two decimal places, and `hold_and_release_required`, a flag defaulting to false which, when true, causes every run of that product to be placed on hold automatically the moment it closes.

    Design: Corner/entities/corner_missing_required_field_rejected
    """
    incomplete = f.product_payload()
    del incomplete["min_yield_pct"]

    validate_error(
        api.create_product(incomplete, PLANT_ADMIN_HEADERS), ApiErrorId.INVALID_REQUEST
    )
    a.assert_empty_page(api.list_products(PLANT_ADMIN_HEADERS, {"limit": 10, "offset": 0}))


def test_an_undeclared_enum_a_date_only_instant_and_a_negative_count_are_refused(api):
    """Three different shape violations, all reported the same way.

    PRD: The body must be a JSON object; every required input field must be present and non-null; every enumerated field must carry a declared member; every numeric field must be a number of the permitted sign and range; and every instant field must be an ISO 8601 UTC timestamp. Any violation is `ERR_INVALID_REQUEST` (HTTP 400). Unknown fields are ignored rather than rejected.
    PRD: It is registered with a `line_code` such as `L1`, unique across the plant, a `required_disassembly_component_count` of at least 1 stating how many components must come apart before a clean may be submitted, and a `max_atp_rlu` of at least 1 giving the highest post-sanitation ATP swab reading, in relative light units, that still passes validation.

    Design: Corner/entities/corner_enum_and_sign_constraints_rejected
    """
    fx.set_clock(api, c.CLOCK_MASTER_DATA)

    validate_error(
        api.create_grower_lot(
            f.grower_lot_payload(
                grower_code="GRW-900",
                ranch_block="B9",
                commodity_class=UNDECLARED_COMMODITY_CLASS,
            ),
            QA_TECHNICIAN_HEADERS,
        ),
        ApiErrorId.INVALID_REQUEST,
    )
    validate_error(
        api.create_grower_lot(
            f.grower_lot_payload(
                grower_code="GRW-901",
                ranch_block="B9",
                harvest_datetime=DATE_ONLY_HARVEST,
            ),
            QA_TECHNICIAN_HEADERS,
        ),
        ApiErrorId.INVALID_REQUEST,
    )
    validate_error(
        api.create_line(
            f.line_payload(
                line_code="L9",
                required_disassembly_component_count=NEGATIVE_COMPONENT_COUNT,
            ),
            PLANT_ADMIN_HEADERS,
        ),
        ApiErrorId.INVALID_REQUEST,
    )

    a.assert_empty_page(api.list_grower_lots(QA_TECHNICIAN_HEADERS))
    a.assert_empty_page(api.list_lines(PLANT_ADMIN_HEADERS))


def test_an_omitted_prior_rejection_count_defaults_to_zero(api):
    """The default is a stored zero, so the clean lot scores the full hundred.

    PRD: A prior-rejection deduction is then taken: five points for each load counted in `prior_rejected_receipt_count`, but the whole term is capped at twenty points *before* it is subtracted, so a grower with four prior rejected loads and a grower with forty prior rejected loads both lose exactly twenty points.
    PRD: The server writes the computed value into `preharvest_risk_score` and copies the identical value into `trailing_risk_score`, because no operating evidence exists yet, and refreshes `out_of_spec_receipt_count` and `env_positive_run_count` to their current counts.

    Design: Corner/entities/corner_optional_prior_reject_count_defaults_to_zero
    """
    fx.set_clock(api, c.CLOCK_MASTER_DATA)
    payload = f.grower_lot_payload(**CLEAN_LOT_OVERRIDES)
    del payload["prior_rejected_receipt_count"]

    lot = validate_success(
        api.create_grower_lot(payload, QA_TECHNICIAN_HEADERS), expected_status=HTTP_CREATED
    )
    assert lot["prior_rejected_receipt_count"] == 0
    assert lot["prior_rejected_receipt_count"] is not None
    assert lot["status"] == c.LOT_PENDING_APPROVAL

    approved = fx.approve_grower_lot(api, lot["id"])
    a.assert_risk_scores(
        approved,
        preharvest=c.RISK_START,
        trailing=c.RISK_START,
        status=c.LOT_APPROVED,
    )


def test_the_load_derives_its_weights_and_stamps_the_acting_operator(api):
    """Net weight at create, accepted and remaining only after the decision.

    PRD: The server derives `net_weight_lb` as the gross weight less the tare weight, rounded half-up to two decimal places, and sets `status` to `PENDING_INSPECTION` with `trim_loss_lb`, `accepted_lb` and `remaining_lb` all left null.
    PRD: The server sets `accepted_lb` to the net weight less the declared trim loss, rounded half-up to two decimal places, sets `remaining_lb` to that same figure — the load's full drawable balance — and stamps `dispositioned_by_user_id` with the acting `X-User-ID`.

    Design: Corner/entities/corner_computed_receipt_fields_are_derived_server_side
    """
    world = fx.build_world(api, stop_after=fx.STOP_LOT_APPROVED)

    created = validate_success(
        api.create_raw_receipt(
            f.raw_receipt_payload(world.grower_lot_id),
            make_receiving_clerk_headers(USER_RECEIVING_CLERK),
        ),
        expected_status=HTTP_CREATED,
    )
    assert created["net_weight_lb"] == c.RECEIPT_NET_WEIGHT_LB
    a.assert_pounds(created["net_weight_lb"], "net_weight_lb")
    assert created["temp_grade"] == c.TEMP_IN_SPEC
    assert created["status"] == c.RECEIPT_PENDING_INSPECTION
    assert created["accepted_lb"] is None
    assert created["remaining_lb"] is None
    assert created["dispositioned_by_user_id"] is None

    dispositioned = fx.disposition_receipt(
        api,
        created["id"],
        c.DECISION_ACCEPT,
        trim_loss_lb=c.RECEIPT_TRIM_LOSS_LB,
        headers=make_qa_technician_headers(USER_QA_TECH_C),
    )
    assert dispositioned["status"] == c.RECEIPT_ACCEPTED
    assert dispositioned["accepted_lb"] == c.RECEIPT_ACCEPTED_LB
    assert dispositioned["remaining_lb"] == c.RECEIPT_ACCEPTED_LB
    assert dispositioned["dispositioned_by_user_id"] == USER_QA_TECH_C


def test_two_readings_at_one_instant_are_separated_only_by_their_sequence(api):
    """A reading carries id and created_at, no version, and never changes.

    PRD: Readings are append-only measurements: the server assigns each one the next `sequence_no` for that wash system, counting from 1, advances the system's `reading_sequence_high_water` to that number, and stamps `taken_by_user_id` from the acting `X-User-ID`.
    PRD: A wash-water reading is an append-only measurement: it carries only `id` and `created_at`. It has no `updated_at` and no `version`, there is no endpoint that modifies it, and the derived values frozen onto it at the moment of recording — `organic_load_index_at_reading`, `target_free_chlorine_ppm_at_reading`, `topup_ppm_required` and `below_target` — are never revised by later activity on the wash system.
    PRD: `topup_ppm_required` is the tier target from step two less the latest reading's measured `free_chlorine_ppm`, rounded half-up to one decimal place, with any negative result replaced by zero.

    Design: Corner/entities/corner_antimicrobial_reading_is_immutable
    """
    world = fx.master_data_world(api)
    tech_headers = make_sanitation_tech_headers(USER_SANITATION_TECH_B)

    first = fx.create_reading(
        api, world.wash_system_id, FIRST_READING_AT, FIRST_READING_PPM, tech_headers
    )
    second = fx.create_reading(
        api, world.wash_system_id, FIRST_READING_AT, SECOND_READING_PPM, tech_headers
    )

    for reading in (first, second):
        a.assert_append_only_fields(reading)
        assert reading["taken_by_user_id"] == USER_SANITATION_TECH_B
        a.assert_instant_equals(reading["reading_at"], FIRST_READING_AT, "reading_at")

    # An identical reading_at leaves the minted sequence as the only ordering key.
    assert first["sequence_no"] == 1
    assert second["sequence_no"] == 2
    assert fx.read_wash_system(api, world.wash_system_id)[
        "reading_sequence_high_water"
    ] == second["sequence_no"]

    a.assert_reading_derivations(
        first,
        organic_load_index_at_reading=UNLOADED_INDEX,
        target_free_chlorine_ppm_at_reading=c.TARGET_PPM_TIER_BASE,
        topup_ppm_required=NO_TOPUP_REQUIRED,
        below_target=False,
    )
    a.assert_reading_derivations(
        second,
        organic_load_index_at_reading=UNLOADED_INDEX,
        target_free_chlorine_ppm_at_reading=c.TARGET_PPM_TIER_BASE,
        topup_ppm_required=SECOND_READING_TOPUP,
        below_target=True,
    )


def test_a_specification_needs_a_real_parent_before_its_version_is_checked(api):
    """The unknown parent answers first, even with a perfectly current version.

    PRD: Identifiers embedded in the URL are resolved left to right, and always before any body field is resolved.
    PRD: The two checks of §2.7 are evaluated after existence and before any state precondition, so a caller holding a stale version learns that before learning anything about the resource's lifecycle state.
    PRD: The server computes `spec_revision` as 1 plus the number of specification rows that already existed for the same `product_id` and `channel`, sets the new row's `status` to `ACTIVE` with `superseded_at` left null, and moves the previously `ACTIVE` row for that same `product_id` and `channel` to `SUPERSEDED`, stamping its `superseded_at` with the logical clock.

    Design: Corner/entities/corner_customer_spec_requires_existing_parent_product
    """
    fx.set_clock(api, c.CLOCK_MASTER_DATA)
    product = fx.create_product(api)

    validate_error(
        api.create_customer_spec(
            c.UNKNOWN_ID,
            f.customer_spec_payload(product["version"]),
            PLANT_ADMIN_HEADERS,
        ),
        ApiErrorId.PRODUCT_NOT_FOUND,
    )

    spec = validate_success(
        api.create_customer_spec(
            product["id"],
            f.customer_spec_payload(product["version"]),
            PLANT_ADMIN_HEADERS,
        ),
        expected_status=HTTP_CREATED,
    )
    assert spec["spec_revision"] == 1
    assert spec["status"] == c.SPEC_ACTIVE
    assert spec["superseded_at"] is None
    assert spec["product_id"] == product["id"]

    # The child is reachable through the declared sub-resource listing.
    rows = a.assert_page(
        api.list_customer_specs(product["id"], QA_MANAGER_HEADERS), expected_total=1
    )
    a.assert_row_ids(rows, [spec["id"]])


def test_a_repeated_code_is_refused_for_each_kind_of_master_data(api):
    """Products, lines and flumes each police their own plant-wide code.

    PRD: Product codes are unique across the plant; registering a second product with an existing `code` is refused with `ERR_DUPLICATE_CODE` (HTTP 409).
    PRD: A duplicate `line_code` is refused with `ERR_DUPLICATE_CODE`.
    PRD: A duplicate `system_code` is likewise refused with `ERR_DUPLICATE_CODE`.

    Design: Corner/entities/corner_duplicate_master_data_code_rejected
    """
    world = fx.master_data_world(api)

    validate_error(
        api.create_product(
            f.product_payload(name="Romaine Shred Duplicate", min_dwell_seconds=95),
            PLANT_ADMIN_HEADERS,
        ),
        ApiErrorId.DUPLICATE_CODE,
    )
    validate_error(
        api.create_line(
            f.line_payload(required_disassembly_component_count=8, max_atp_rlu=180),
            PLANT_ADMIN_HEADERS,
        ),
        ApiErrorId.DUPLICATE_CODE,
    )
    validate_error(
        api.create_wash_system(
            f.wash_system_payload(water_volume_gal=2000.00, max_concurrent_runs=1),
            PLANT_ADMIN_HEADERS,
        ),
        ApiErrorId.DUPLICATE_CODE,
    )

    # The refused writes left the originals alone.
    rows = a.assert_page(
        api.list_products(PLANT_ADMIN_HEADERS), expected_total=1, expected_count=1
    )
    a.assert_row_ids(rows, [world.product_id])
    assert rows[0]["min_dwell_seconds"] == c.PRODUCT_MIN_DWELL_SECONDS
    assert rows[0]["name"] == c.PRODUCT_NAME
    assert fx.read_line(api, world.line_id)[
        "required_disassembly_component_count"
    ] == c.LINE_REQUIRED_COMPONENTS
    assert (
        fx.read_wash_system(api, world.wash_system_id)["water_volume_gal"]
        == c.WASH_WATER_VOLUME_GAL
    )


def test_a_planned_window_must_be_strictly_forward_but_may_be_one_second_long(api):
    """Equal and inverted windows are interval conflicts; one second is a run.

    PRD: The planned window is treated as half-open: `planned_start_at` is inclusive and `planned_end_at` is exclusive, and `planned_end_at` must be strictly after `planned_start_at`. The window must not overlap the window of any other run on the same line whose `run_status` is `SETUP` or `RUNNING`. Two windows that merely touch, where one ends at exactly the instant the next begins, do not overlap. A violation of either the ordering or the exclusion is refused with `ERR_LINE_INTERVAL_CONFLICT` (HTTP 409).

    Design: Corner/entities/corner_run_planned_window_must_be_non_empty
    """
    world = fx.master_data_world(api)

    def plan(planned_end_at):
        return api.create_process_run(
            f.process_run_payload(
                world.line_id,
                world.product_id,
                world.spec_id,
                world.wash_system_id,
                planned_start_at=WINDOW_START_AT,
                planned_end_at=planned_end_at,
            ),
            LINE_OPERATOR_HEADERS,
        )

    validate_error(plan(WINDOW_START_AT), ApiErrorId.LINE_INTERVAL_CONFLICT)
    validate_error(plan(WINDOW_INVERTED_END_AT), ApiErrorId.LINE_INTERVAL_CONFLICT)

    planned = validate_success(
        plan(WINDOW_ONE_SECOND_END_AT), expected_status=HTTP_CREATED
    )
    assert planned["run_status"] == c.RUN_SETUP
    a.assert_instant_equals(planned["planned_start_at"], WINDOW_START_AT,
                            "planned_start_at")
    a.assert_instant_equals(planned["planned_end_at"], WINDOW_ONE_SECOND_END_AT,
                            "planned_end_at")
