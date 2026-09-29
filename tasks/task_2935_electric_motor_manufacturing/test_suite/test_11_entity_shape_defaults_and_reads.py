"""Entity shape: computed creation, envelopes, defaults, existence and reads."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import test_users as U
from test_helpers.api_errors import (
    ERR_DESIGN_NOT_FOUND,
    ERR_DISTRIBUTOR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    NOT_FOUND_BY_COLLECTION,
)


def test_creating_a_design_runs_the_loss_model_and_reports_both_verdicts(api):
    """A single create echoes all 24 inputs and adds the five computed outputs.

    PRD 3.2: "Creation runs a five-component loss model against the submitted
    geometry and materials, and re-running that model is the first act of every
    subsequent submission for review."

    Design: Corner/entities/motor_design_creation_returns_computed_loss_model_and_both_classes
    """
    payload = F.motor_design_payload()

    created = validate_success(
        api.create_motor_design(payload, U.DESIGN_ENGINEER), 201
    )

    for field, value in payload.items():
        assert created[field] == value, "input %s was not echoed" % field
    A.assert_design_loss_model(created, payload)
    assert created["total_predicted_loss_w"] == 479.7
    assert created["predicted_efficiency_pct"] == 93.99
    assert created["guaranteed_efficiency_pct"] == 93.09
    assert created["design_estimate_class"] == "IE4"
    assert created["predicted_class"] == "IE3"
    assert created["status"] == "DRAFT"
    assert created["revision_index"] == 0
    assert created["review_round"] == 0
    assert created["created_by_user_id"] == U.USER_DESIGN_ENGINEER
    assert created["released_by_user_id"] is None
    assert created["released_at"] is None
    assert created["supersedes_design_id"] is None
    A.assert_common_fields(created, 1)


def test_reading_a_design_back_returns_the_stored_row_in_the_object_envelope(api):
    """The single-resource read repeats every value inside the declared envelope.

    PRD 2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/entities/motor_design_retrieval_matches_stored_row_and_success_envelope
    """
    payload = F.motor_design_payload()
    created = validate_success(
        api.create_motor_design(payload, U.DESIGN_ENGINEER), 201
    )

    response = api.get_motor_design(created["id"], U.DESIGN_REVIEWER)

    fetched = A.assert_ok(response)
    assert response.json()["response_type"] == "object"
    assert "limit" not in response.json()["meta"]
    assert fetched == created
    assert fetched["id"] == created["id"]
    assert fetched["created_at"] == created["created_at"]
    assert fetched["total_predicted_loss_w"] == 479.7
    assert fetched["guaranteed_efficiency_pct"] == 93.09
    assert fetched["status"] == "DRAFT"
    assert fetched["version"] == 1


def test_the_design_listing_windows_the_page_and_filters_before_paginating(api):
    """Three rows, two pages, then two filters that narrow total_count itself.

    PRD 2.3: "Every list response carries the four pagination fields inside
    `meta`: the `limit` and `offset` actually applied, `total_count` giving the
    number of rows matching the filters before pagination, and `has_more`
    indicating whether any further rows follow the returned page."

    Design: Corner/entities/motor_design_listing_paginates_and_filters_by_status
    """
    first = validate_success(
        api.create_motor_design(F.motor_design_payload(), U.DESIGN_ENGINEER), 201
    )
    validate_success(
        api.submit_design_review(
            first["id"], F.submit_review_payload(), U.DESIGN_ENGINEER
        )
    )
    second = validate_success(
        api.create_motor_design(
            F.premium_motor_design_payload(), U.DESIGN_ENGINEER
        ),
        201,
    )
    third = validate_success(
        api.create_motor_design(
            F.economy_motor_design_payload(), U.DESIGN_ENGINEER
        ),
        201,
    )

    page_one, meta_one = validate_paginated(
        api.list_motor_designs(U.PRODUCTION_PLANNER, {"limit": 2, "offset": 0})
    )
    page_two, meta_two = validate_paginated(
        api.list_motor_designs(U.PRODUCTION_PLANNER, {"limit": 2, "offset": 2})
    )
    in_review, meta_review = validate_paginated(
        api.list_motor_designs(U.PRODUCTION_PLANNER, {"status": "IN_REVIEW"})
    )
    targeting_ie4, meta_ie4 = validate_paginated(
        api.list_motor_designs(
            U.PRODUCTION_PLANNER, {"target_efficiency_class": "IE4"}
        )
    )

    assert [row["id"] for row in page_one] == [first["id"], second["id"]]
    assert meta_one["total_count"] == 3
    assert meta_one["limit"] == 2
    assert meta_one["offset"] == 0
    assert meta_one["has_more"] is True
    assert [row["id"] for row in page_two] == [third["id"]]
    assert meta_two["total_count"] == 3
    assert meta_two["offset"] == 2
    assert meta_two["has_more"] is False
    assert [row["id"] for row in in_review] == [first["id"]]
    assert meta_review["total_count"] == 1
    assert meta_review["has_more"] is False
    assert [row["id"] for row in targeting_ie4] == [second["id"]]
    assert meta_ie4["total_count"] == 1
    assert (
        validate_success(api.get_motor_design(third["id"], U.PLANT_ADMIN))["status"]
        == "DRAFT"
    )


def test_each_path_addressed_collection_reports_its_own_not_found_identifier(api):
    """Thirteen unknown paths, twelve distinct 404 identifiers.

    PRD 2.6: "The first unresolvable identifier decides the response, and the
    error identifies the *kind* of resource that was missing:
    `ERR_DESIGN_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`,
    `ERR_SUBASSEMBLY_NOT_FOUND` (for a stator or rotor build),
    `ERR_ASSEMBLY_RECORD_NOT_FOUND`, `ERR_PERFORMANCE_TEST_NOT_FOUND`,
    `ERR_NAMEPLATE_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND`,
    `ERR_DISTRIBUTOR_NOT_FOUND`, `ERR_OVEN_NOT_FOUND`, `ERR_TEST_CELL_NOT_FOUND`
    or `ERR_STANDARD_NOT_FOUND`, each with HTTP 404."

    Design: Corner/entities/every_path_id_collection_returns_its_own_not_found_error
    """
    reported = {}

    for collection, expected_error in NOT_FOUND_BY_COLLECTION.items():
        response = api.get_by_path(collection, NON_EXISTENT_UUID, U.PLANT_ADMIN)
        reported[collection] = validate_error(response, expected_error, 404)["error_id"]

    assert len(reported) == 13
    assert len(set(reported.values())) == 12
    assert reported["stator-builds"] == reported["rotor-builds"]
    assert reported["motor-designs"] != reported["customer-orders"]


def test_a_create_missing_one_required_field_persists_nothing(api):
    """Three malformed creates, three 400s, and every collection still empty.

    PRD 2.2: "The `error_id` is a unique, machine-readable string that identifies
    the specific error."

    Design: Corner/entities/missing_required_fields_are_rejected_before_any_row_is_created
    """
    design_without_model_code = F.motor_design_payload()
    design_without_model_code.pop("model_code")
    distributor_without_tier = F.distributor_payload()
    distributor_without_tier.pop("tier")
    standard_without_effective_from = F.regulatory_standard_payload()
    standard_without_effective_from.pop("effective_from")

    validate_error(
        api.create_motor_design(design_without_model_code, U.DESIGN_ENGINEER),
        ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_distributor(distributor_without_tier, U.PLANT_ADMIN),
        ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_regulatory_standard(
            standard_without_effective_from, U.PLANT_ADMIN
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    designs, design_meta = validate_paginated(api.list_motor_designs(U.PLANT_ADMIN))
    assert designs == []
    assert design_meta["total_count"] == 0
    _distributors, distributor_meta = validate_paginated(
        api.list_distributors(U.PLANT_ADMIN)
    )
    assert distributor_meta["total_count"] == 0
    _standards, standard_meta = validate_paginated(
        api.list_regulatory_standards(U.PLANT_ADMIN)
    )
    assert standard_meta["total_count"] == 0


def test_omitted_optional_inputs_take_their_declared_defaults(api):
    """Bare creates land on false, zero, AVAILABLE and an empty requirements object.

    PRD 3.4: "An optional `special_requirements` object, defaulting to empty,
    carries engineered-motor flags; the four recognised keys are
    `non_standard_mounting`, `hazardous_environment`, `non_standard_duty` and
    `marine_certification`, each a boolean."

    Design: Corner/entities/omitted_optional_inputs_fall_back_to_declared_defaults
    """
    design = validate_success(
        api.create_motor_design(F.motor_design_payload(), U.DESIGN_ENGINEER), 201
    )

    distributor = validate_success(
        api.create_distributor(
            {"name": "Sparse Partner", "tier": "SILVER", "jurisdiction": "EU"},
            U.PLANT_ADMIN,
        ),
        201,
    )
    oven = validate_success(
        api.create_curing_oven(
            {"oven_code": "OVEN-D", "max_temp_c": 180.0, "cooldown_buffer_minutes": 45},
            U.PLANT_ADMIN,
        ),
        201,
    )
    cell = validate_success(
        api.create_test_cell(
            {"cell_code": "DYNO-D", "max_concurrent_kw": 20.0}, U.PLANT_ADMIN
        ),
        201,
    )
    standard_payload = F.regulatory_standard_payload()
    standard_payload.pop("tolerance_pct", None)
    standard = validate_success(
        api.create_regulatory_standard(standard_payload, U.PLANT_ADMIN), 201
    )
    order = validate_success(
        api.create_customer_order(
            {
                "distributor_id": distributor["id"],
                "design_id": design["id"],
                "order_type": "MADE_TO_ORDER",
                "quantity": 4,
                "requested_ship_date": F.FAR_FUTURE_DATE,
                "jurisdiction": "EU",
            },
            U.PRODUCTION_PLANNER,
        ),
        201,
    )

    assert distributor["stocking_program_enrolled"] is False
    assert distributor["committed_annual_units"] == 0
    assert distributor["stock_buffer_units"] == 0
    assert distributor["units_outstanding"] == 0
    assert distributor["stock_allowance_remaining_units"] == 0
    assert distributor["warranty_credit_balance_cents"] == 0
    assert distributor["open_presumed_defect_count"] == 0
    assert oven["status"] == "AVAILABLE"
    assert oven["booked_minutes"] == 0
    assert cell["status"] == "AVAILABLE"
    A.assert_rounded_to(cell["peak_reserved_kw"], 0, 1, "peak_reserved_kw")
    A.assert_rounded_to(standard["tolerance_pct"], 0, 2, "tolerance_pct")
    assert order["special_requirements"] == {}
    expected_days = A.expected_lead_time_days("MADE_TO_ORDER", "EU", "SILVER", 4, 0)
    assert expected_days == 31
    assert order["promised_lead_time_days"] == expected_days
    assert order["promised_ship_date"] == A.add_days(F.CLOCK_DAY, expected_days)
    assert order["promised_ship_date"] == "2026-09-01"
    assert design["supersedes_design_id"] is None


def test_system_fields_are_server_minted_and_the_version_advances_once_per_write(api):
    """One create and two mutations walk the version from 1 to 3.

    PRD 2.4: "`version` is an integer that starts at 1 when the row is created and
    increments by exactly 1 on every mutation of that row, including mutations the
    row suffers as a *consequence* of some other resource's transition."

    Design: Corner/entities/system_fields_are_server_minted_and_version_increments_on_each_mutation
    """
    created = validate_success(
        api.create_motor_design(F.motor_design_payload(), U.DESIGN_ENGINEER), 201
    )
    A.assert_common_fields(created, 1)
    assert created["id"] != F.motor_design_payload()["model_code"]

    # PRD 2.5: "Advancing the clock changes no stored row ... only future
    # computations see the new time." Every system instant, `updated_at`
    # included, is read from the logical clock, so the clock is advanced here to
    # separate the creation instant from the two mutation instants that follow.
    validate_success(
        api.set_clock(F.clock_payload(F.instant("2026-08-02", 6, 30)), U.PLANT_ADMIN)
    )

    in_review = validate_success(
        api.submit_design_review(
            created["id"], F.submit_review_payload(), U.DESIGN_ENGINEER
        )
    )
    released = validate_success(
        api.record_review_decision(
            created["id"], F.review_decision_payload("APPROVE"), U.DESIGN_REVIEWER
        )
    )

    assert in_review["version"] == 2
    assert released["version"] == 3
    assert released["created_at"] == created["created_at"]
    assert released["updated_at"] > created["created_at"]
    assert released["status"] == "RELEASED"
    assert released["released_by_user_id"] == U.USER_DESIGN_REVIEWER
    A.assert_three_fractional_digits(released["released_at"], "released_at")
    assert released["created_by_user_id"] == U.USER_DESIGN_ENGINEER
    assert released["review_round"] == 1
    assert released["revision_index"] == 0


def test_a_registered_standard_carries_no_version_and_no_updated_at(api):
    """Immutable reference data is the one entity without the mutable pair.

    PRD 2.4: "Regulatory standards are the deliberate exception. A registered
    standard is immutable reference data: it carries only `id` and `created_at`,
    and it has neither an `updated_at` field nor a `version` field."

    Design: Corner/entities/regulatory_standard_is_immutable_with_no_update_endpoint_or_version
    """
    payload = F.regulatory_standard_payload(tolerance_pct=0.0)

    created = validate_success(
        api.create_regulatory_standard(payload, U.PLANT_ADMIN), 201
    )
    fetched = validate_success(
        api.get_regulatory_standard(created["id"], U.QUALITY_CERTIFIER), 200
    )

    A.assert_immutable_common_fields(created)
    A.assert_immutable_common_fields(fetched)
    assert fetched["id"] == created["id"]
    assert fetched["created_at"] == created["created_at"]
    A.assert_rounded_to(
        fetched["minimum_efficiency_pct"], 89.60, 2, "minimum_efficiency_pct"
    )
    assert fetched["effective_from"] == "2021-07-01"
    assert fetched["standard_code"] == payload["standard_code"]


def test_out_of_set_enums_out_of_range_numbers_and_an_oversized_page_are_refused(api):
    """Three schema failures, one identifier, and nothing persisted.

    PRD 2.3: "A `limit` below 1 or above 100, or a negative `offset`, is a
    malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400) rather
    than being silently clamped."

    Design: Corner/entities/out_of_set_enums_and_out_of_range_numbers_are_rejected
    """
    outside_the_class_set = F.motor_design_payload(
        model_code="WM-BAD-ENUM", target_efficiency_class="IE1"
    )
    below_the_rating_floor = F.motor_design_payload(
        model_code="WM-BAD-RANGE", rated_output_kw=3.9
    )

    validate_error(
        api.create_motor_design(outside_the_class_set, U.DESIGN_ENGINEER),
        ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_motor_design(below_the_rating_floor, U.DESIGN_ENGINEER),
        ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.list_motor_designs(U.PLANT_ADMIN, {"limit": 101}),
        ERR_INVALID_REQUEST,
        400,
    )

    _rows, meta = validate_paginated(api.list_motor_designs(U.PLANT_ADMIN))
    assert meta["total_count"] == 0
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    at_the_floor = validate_success(
        api.create_motor_design(
            F.motor_design_payload(model_code="WM-AT-FLOOR", rated_output_kw=4.0),
            U.DESIGN_ENGINEER,
        ),
        201,
    )
    assert at_the_floor["rated_output_kw"] == 4.0


def test_an_unknown_body_foreign_key_reports_the_parent_collection(api):
    """A flat topology carries its parents in the body, and 404s name the parent.

    PRD 2.6: "A child is always created by posting to its own flat collection with
    its parents' identifiers in the request body — a stator build carries
    `work_order_id`, a warranty claim carries both `work_order_id` and
    `distributor_id` — and a child is always discovered by filtering its own
    collection."

    Design: Corner/entities/body_foreign_keys_are_validated_across_peer_collections
    """
    distributor = validate_success(
        api.create_distributor(F.distributor_payload(), U.PLANT_ADMIN), 201
    )
    design = validate_success(
        api.create_motor_design(F.motor_design_payload(), U.DESIGN_ENGINEER), 201
    )

    unknown_distributor = api.create_customer_order(
        F.customer_order_payload(NON_EXISTENT_UUID, design["id"]),
        U.PRODUCTION_PLANNER,
    )
    unknown_design = api.create_customer_order(
        F.customer_order_payload(distributor["id"], NON_EXISTENT_UUID),
        U.PRODUCTION_PLANNER,
    )

    validate_error(unknown_distributor, ERR_DISTRIBUTOR_NOT_FOUND, 404)
    validate_error(unknown_design, ERR_DESIGN_NOT_FOUND, 404)
    _orders, meta = validate_paginated(api.list_customer_orders(U.PRODUCTION_PLANNER))
    assert meta["total_count"] == 0


def test_a_successor_design_is_discoverable_by_filtering_on_the_key_it_carries(api):
    """The self-reference is resolved by a filtered list, never by a nested path.

    PRD 3.1: "The designs collection may be filtered by `status`, by
    `target_efficiency_class`, by `predicted_class` and by `supersedes_design_id`,
    the last of which is how the successors of a superseded design are found."

    Design: Corner/entities/flat_topology_cross_references_resolve_between_nameplate_test_and_standard
    """
    superseded = validate_success(
        api.create_motor_design(F.motor_design_payload(), U.DESIGN_ENGINEER), 201
    )
    validate_success(
        api.submit_design_review(
            superseded["id"], F.submit_review_payload(), U.DESIGN_ENGINEER
        )
    )
    released = validate_success(
        api.record_review_decision(
            superseded["id"], F.review_decision_payload("APPROVE"), U.DESIGN_REVIEWER
        )
    )
    assert released["status"] == "RELEASED"
    successor_payload = F.premium_motor_design_payload(
        supersedes_design_id=superseded["id"]
    )
    successor = validate_success(
        api.create_motor_design(successor_payload, U.DESIGN_ENGINEER), 201
    )

    successors_of_the_old, meta_old = validate_paginated(
        api.list_motor_designs(
            U.DESIGN_ENGINEER, {"supersedes_design_id": superseded["id"]}
        )
    )
    successors_of_the_new, meta_new = validate_paginated(
        api.list_motor_designs(
            U.DESIGN_ENGINEER, {"supersedes_design_id": successor["id"]}
        )
    )

    assert meta_old["total_count"] == 1
    assert [row["id"] for row in successors_of_the_old] == [successor["id"]]
    assert successors_of_the_old[0]["supersedes_design_id"] == superseded["id"]
    assert meta_new["total_count"] == 0
    assert meta_new["has_more"] is False
    assert successors_of_the_new == []
    A.assert_design_loss_model(successor, successor_payload)
