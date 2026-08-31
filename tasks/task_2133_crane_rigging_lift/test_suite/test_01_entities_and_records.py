"""Creation, retrieval, defaults, immutability and listing of the static records
every lift depends on."""

import pytest

from test_helpers import (
    ApiErrorId,
    DISPATCHER,
    SAFETY_MANAGER,
    assert_customer,
    assert_load_chart_entry,
    assert_rigging_gear,
    build_standard_world,
    create_gear_assignment_payload,
    create_load_chart_entry_payload,
    create_rigging_gear_payload,
    create_standard_crane_payload,
    gear_version,
    is_valid_uuid,
    new_customer,
    new_site,
    new_standard_crane,
    open_plan,
    survey_plan,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"


def test_registering_a_customer_mints_the_system_fields_and_the_envelope(api):
    """PRD 3.1: "A customer account is opened with a legal `account_name` and,
    optionally, `billing_terms` chosen from `NET_15`, `NET_30` and `NET_45`; when the
    terms are omitted the account is opened on `NET_30`. A newly registered account
    has `credit_hold` false, `credit_hold_reason` null, `open_receivable_cents` at 0
    and `invoice_count` at 0."
    PRD 2.4: "Every stored resource carries an `id` that is a server-minted UUID.
    Identifiers are bare UUIDs with no type prefix, no embedded entity name, and no
    client-supplied component; a client that supplies its own `id` has it ignored."
    PRD 2.4: "and `version`, an integer that begins at 1 when the row is created and
    increases by exactly 1 on every mutation of that row."

    Design: Corner/entities/create_customer_returns_201_with_system_fields_and_envelope
    """
    resp = api.create_customer({"account_name": "Northgate Industrial"}, DISPATCHER)
    data = validate_success(resp, 201)

    assert_customer(data)
    assert data["version"] == 1
    assert data["credit_hold"] is False
    assert data["credit_hold_reason"] is None
    assert data["open_receivable_cents"] == 0
    assert data["invoice_count"] == 0
    assert data["billing_terms"] == "NET_30"
    assert is_valid_uuid(data["id"]), "the id must be a bare 8-4-4-4-12 UUID"
    assert "_" not in data["id"], "the id carries no type prefix such as cus_"

    body = resp.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"]["api_request_timestamp"], str)


def test_reading_a_customer_echoes_the_stored_row(api):
    """PRD 2.2: "The `data` field contains the resource object or an array of resource
    objects."
    PRD 3.1: "A customer account is opened with a legal `account_name` and,
    optionally, `billing_terms` chosen from `NET_15`, `NET_30` and `NET_45`; when the
    terms are omitted the account is opened on `NET_30`."
    PRD 2.4: "and `version`, an integer that begins at 1 when the row is created and
    increases by exactly 1 on every mutation of that row."

    Design: Corner/entities/get_customer_by_id_returns_the_stored_row
    """
    created = new_customer(account_name="Northgate Industrial", billing_terms="NET_45")
    fetched = validate_success(api.get_customer(created["id"], DISPATCHER))

    assert fetched["id"] == created["id"]
    assert fetched["billing_terms"] == "NET_45"
    assert fetched["version"] == 1


def test_listing_cranes_carries_the_pagination_envelope(api):
    """PRD 2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD 2.3: "The `meta` block of a list response carries `limit`, `offset`,
    `total_count` and `has_more`, where `total_count` is the number of rows matching
    the filters before pagination is applied and `has_more` is true when rows remain
    beyond the current page."

    Design: Corner/entities/list_cranes_returns_pagination_envelope_fields
    """
    new_standard_crane(model_code="RT-150-A")
    new_standard_crane(model_code="RT-150-B")

    resp = api.list_cranes(DISPATCHER, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)

    assert resp.json()["response_type"] == "array"
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert meta["limit"] == 1
    assert meta["offset"] == 0


def test_reading_an_unknown_lift_plan_reports_the_plan_not_found_code(api):
    """PRD 2.7: "Every identifier embedded in the URL path resolves to a stored row,
    checked left to right. Depending on which segment fails, the code is one of
    `ERR_CUSTOMER_NOT_FOUND`, `ERR_SITE_NOT_FOUND`, `ERR_CRANE_NOT_FOUND`,
    `ERR_PERSONNEL_NOT_FOUND`, `ERR_GEAR_NOT_FOUND`, `ERR_LIFT_PLAN_NOT_FOUND`,
    `ERR_GEAR_ASSIGNMENT_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`,
    `ERR_STANDBY_EVENT_NOT_FOUND` or `ERR_INVOICE_NOT_FOUND`, always with HTTP 404."

    Design: Corner/entities/get_lift_plan_with_unknown_id_returns_not_found
    """
    resp = api.get_lift_plan(UNKNOWN_UUID, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_LIFT_PLAN_NOT_FOUND.value, 404)
    assert resp.json()["response_type"] == "error"


def test_registering_a_site_without_the_soil_capacity_is_a_shape_failure(api):
    """PRD 3.1: "Registering a site requires the owning `customer_id`, a human
    `address_label`, the `jurisdiction_code` of the permitting authority that governs
    that address (for example a county-level code such as `NJ-BERGEN`), and an initial
    `soil_bearing_capacity_psf` — the allowable soil bearing pressure in pounds per
    square foot, which must be strictly greater than zero."
    PRD 2.7: "Request-body shape: every required field is present, every value has the
    correct type, every enum value is a legal member"
    PRD 2.7: "Any violation is `ERR_INVALID_REQUEST` (400). This rule applies to every
    POST endpoint and to the query parameters of every list endpoint."

    Design: Corner/entities/create_site_missing_required_field_returns_invalid_request
    """
    customer = new_customer(account_name="Northgate Industrial")
    resp = api.create_site(
        {"customer_id": customer["id"], "address_label": "Bergen Plant 4",
         "jurisdiction_code": "NJ-BERGEN"}, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    _, meta = validate_paginated(
        api.list_sites(DISPATCHER, params={"customer_id": customer["id"]}))
    assert meta["total_count"] == 0, "a rejected create must persist nothing"


def test_personnel_optional_attributes_take_their_declared_defaults(api):
    """PRD 3.1: "Three further attributes are meaningful only for one discriminator
    each and default when omitted: `endorsement_class_tons`, the largest crane class
    in tons this person may operate, defaulting to 0 and meaningful only for an
    `OPERATOR`; `rigger_level`, defaulting to `NONE` and meaningful only for a
    `RIGGER`, drawn from a ladder ordered `NONE`, then `BASIC`, then `INTERMEDIATE`,
    then `ADVANCED`, then `MASTER`; and `pe_license_state`, defaulting to null and
    meaningful only for an `ENGINEER`."
    PRD 3.1: "A person's `status` is derived, not stored: it reads `EXPIRED` once the
    logical clock has reached or passed `certification_expires_on`, and `ACTIVE`
    otherwise. Their `peak_daily_assigned_hours` starts at 0 and is maintained by the
    scheduling rules in §3.4."

    Design: Corner/entities/personnel_optional_fields_take_declared_defaults
    """
    data = validate_success(api.create_personnel(
        {"full_name": "Ray Kolb", "role_type": "OPERATOR",
         "certification_number": "NCCCO-88421",
         "certification_expires_on": "2027-03-31T00:00:00Z"}, DISPATCHER), 201)

    assert data["rigger_level"] == "NONE"
    assert data["endorsement_class_tons"] == 0
    assert data["pe_license_state"] is None
    assert data["status"] == "ACTIVE"
    assert data["peak_daily_assigned_hours"] == pytest.approx(0, abs=0.0001)


def test_registering_gear_mints_its_posture_and_derate_regardless_of_input(api):
    """PRD 3.2: "Newly registered gear starts at `DUE_INSPECTION` with `repair_count`
    at 0, `effective_wll_lb` equal to `rated_wll_lb`, `committed_assignment_count` at
    0, and both `last_inspection_at` and `next_inspection_due_at` null."

    Design: Corner/entities/rigging_gear_computed_and_system_fields_input_ignored
    """
    data = validate_success(api.create_rigging_gear(
        {"gear_tag": "SL-9001", "gear_type": "SHACKLE", "rated_wll_lb": 18_000,
         "weight_lb": 60, "inspection_interval_days": 30}, SAFETY_MANAGER), 201)

    assert_rigging_gear(data)
    assert data["status"] == "DUE_INSPECTION"
    assert data["effective_wll_lb"] == 18_000
    assert data["repair_count"] == 0
    assert data["committed_assignment_count"] == 0
    assert data["last_inspection_at"] is None
    assert data["next_inspection_due_at"] is None


def test_gear_type_outside_the_declared_family_is_rejected(api):
    """PRD 3.2: "A `SafetyManager` registers a piece of gear with a `gear_tag` that
    must be globally unique across the whole inventory — a collision is refused with
    `ERR_DUPLICATE_GEAR_TAG` — a `gear_type` drawn from `SLING`, `SHACKLE` and
    `SPREADER_BAR`, the manufacturer's `rated_wll_lb` working load limit in pounds,
    the dead `weight_lb` of the gear itself (which may be zero but not negative), and
    optionally an `inspection_interval_days` cadence that defaults to 30 days when
    omitted and must be positive."
    PRD 2.7: "Request-body shape: every required field is present, every value has the
    correct type, every enum value is a legal member"

    Design: Corner/entities/create_rigging_gear_with_invalid_enum_returns_invalid_request
    """
    resp = api.create_rigging_gear(
        {"gear_tag": "SL-9002", "gear_type": "CHAIN_HOIST", "rated_wll_lb": 18_000,
         "weight_lb": 60}, SAFETY_MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    _, meta = validate_paginated(api.list_rigging_gear(DISPATCHER, params={"gear_type": "SLING"}))
    assert meta["total_count"] == 0


def test_leg_count_outside_one_to_four_is_a_shape_failure(api):
    """PRD 3.4: "A `Dispatcher` commits one item at a time, naming the
    `lift_plan_id`, the `gear_id`, the `leg_count` — how many sling legs share the
    load, between 1 and 4 inclusive — and the `sling_angle_deg`, the horizontal sling
    angle, which is accepted only at the four tabulated values 30, 45, 60 and 90."
    PRD 2.7: "`leg_count` lies between 1 and 4 inclusive, `sling_angle_deg` is one of
    30, 45, 60 or 90, all hour and mile quantities are at least 0"

    Design: Corner/entities/gear_assignment_leg_count_out_of_range_returns_invalid_request
    """
    world = build_standard_world()
    plan = open_plan(world, job_reference="JOB-9100")
    survey_plan(world, plan["id"])

    payload = create_gear_assignment_payload(
        plan["id"], world["gear_id"], gear_version(world["gear_id"]), leg_count=5)
    validate_error(api.create_gear_assignment(payload, DISPATCHER),
                   ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    gear = validate_success(api.get_rigging_gear(world["gear_id"], DISPATCHER))
    assert gear["committed_assignment_count"] == 0


def test_load_chart_rows_are_append_only_and_uniquely_keyed(api):
    """PRD 3.1: "Chart rows are immutable once written — there is no update and no
    delete — and the combination of crane, configuration, boom length and radius must
    be unique; a duplicate is refused with `ERR_DUPLICATE_CHART_ROW`."
    PRD 2.4: "Two resource kinds are deliberately excluded from that pair, because
    both are append-only records of a moment rather than living objects: a load-chart
    row and a gear-inspection record carry only `id` and `created_at`. Neither has an
    `updated_at` and neither has a `version`, and no endpoint exists that would update
    or delete either of them."

    Design: Corner/entities/load_chart_entry_is_immutable_and_duplicate_key_rejected
    """
    crane = validate_success(api.create_crane(
        create_standard_crane_payload(model_code="LTM-1250", class_tons=275),
        DISPATCHER), 201)
    first = validate_success(api.create_load_chart_entry(
        create_load_chart_entry_payload(crane["id"], boom_length_ft=120, radius_ft=40,
                                        gross_capacity_lb=100_000), DISPATCHER), 201)
    assert_load_chart_entry(first)

    duplicate = api.create_load_chart_entry(
        create_load_chart_entry_payload(crane["id"], boom_length_ft=120, radius_ft=40,
                                        gross_capacity_lb=88_000), DISPATCHER)
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_CHART_ROW.value, 409)

    rows, meta = validate_paginated(api.list_crane_load_chart_entries(crane["id"], DISPATCHER))
    assert meta["total_count"] == 1
    assert rows[0]["gross_capacity_lb"] == 100_000
    assert "version" not in rows[0]
    assert "updated_at" not in rows[0]


def test_registering_a_site_under_an_unknown_customer_is_a_foreign_key_failure(api):
    """PRD 2.7: "Every foreign key supplied in the request body resolves to a stored
    row, yielding `ERR_CUSTOMER_NOT_FOUND`, `ERR_SITE_NOT_FOUND`,
    `ERR_CRANE_NOT_FOUND`, `ERR_PERSONNEL_NOT_FOUND`, `ERR_GEAR_NOT_FOUND` or
    `ERR_LIFT_PLAN_NOT_FOUND` at HTTP 404. This rule guards exactly these ten
    operations: `POST /sites`, `POST /load-chart-entries`, `POST /gear-inspections`,
    `POST /lift-plans`, `POST /lift-plans/{id}/configure`, `POST /gear-assignments`,
    `POST /engineering-reviews`, `POST /permits`, `POST /standby-events` and
    `POST /invoices`."

    Design: Corner/entities/create_site_with_unknown_customer_returns_customer_not_found
    """
    resp = api.create_site(
        {"customer_id": UNKNOWN_UUID, "address_label": "Nowhere",
         "jurisdiction_code": "NJ-BERGEN", "soil_bearing_capacity_psf": 2000}, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_CUSTOMER_NOT_FOUND.value, 404)


def test_sites_can_be_narrowed_to_one_owning_customer(api):
    """PRD 3.1: "Sites may be listed filtered by `customer_id` and by
    `survey_status`."
    PRD 2.3: "The `meta` block of a list response carries `limit`, `offset`,
    `total_count` and `has_more`, where `total_count` is the number of rows matching
    the filters before pagination is applied and `has_more` is true when rows remain
    beyond the current page."

    Design: Corner/entities/list_sites_filtered_by_customer_id_returns_only_that_customers_sites
    """
    customer_a = new_customer(account_name="Customer A")
    customer_b = new_customer(account_name="Customer B")
    site_a = new_site(customer_a["id"], address_label="Site A",
                      jurisdiction_code="NJ-BERGEN", soil_bearing_capacity_psf=2000)
    site_b = new_site(customer_b["id"], address_label="Site B",
                      jurisdiction_code="NY-ROCKLAND", soil_bearing_capacity_psf=2500)

    data, meta = validate_paginated(
        api.list_sites(DISPATCHER, params={"customer_id": customer_a["id"]}))

    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert data[0]["id"] == site_a["id"]
    assert site_b["id"] not in [row["id"] for row in data]


def test_the_inspection_log_for_one_gear_item_reads_newest_first(api):
    """PRD 3.2: "The inspection record is append-only: it stamps `inspected_at` with
    the logical clock, records the `resulting_status` it drove the gear to, and
    snapshots `repair_count_after` — the gear's repair tally immediately after this
    inspection was applied."
    PRD 3.2: "The inspection log for a single gear item is readable, filterable by
    `result`, and — unusually for this API — is returned **newest first**."
    PRD 3.2: "A `FAIL` moves the gear to `QUARANTINED`."

    Design: Corner/entities/list_gear_inspections_subresource_returns_full_log_for_one_gear
    """
    gear = validate_success(api.create_rigging_gear(
        create_rigging_gear_payload(), SAFETY_MANAGER), 201)
    first = validate_success(api.create_gear_inspection(
        {"gear_id": gear["id"], "result": "PASS", "inspector_note": "acceptance"},
        SAFETY_MANAGER), 201)
    second = validate_success(api.create_gear_inspection(
        {"gear_id": gear["id"], "result": "FAIL", "inspector_note": "broken wires"},
        SAFETY_MANAGER), 201)

    assert first["resulting_status"] == "SERVICEABLE"
    assert second["resulting_status"] == "QUARANTINED"

    rows, meta = validate_paginated(api.list_gear_inspections(gear["id"], SAFETY_MANAGER))
    assert meta["total_count"] == 2
    assert rows[0]["id"] == second["id"], "the inspection log is returned newest first"

    assert validate_success(api.get_rigging_gear(gear["id"], SAFETY_MANAGER))["status"] \
        == "QUARANTINED"


def test_a_pagination_limit_above_one_hundred_is_rejected_not_clamped(api):
    """PRD 2.3: "Every list endpoint is paginated through two optional query
    parameters. `limit` defaults to 10 when omitted, may not be smaller than 1, and
    may not be larger than 100. `offset` defaults to 0 and may not be negative. A
    `limit` outside the 1-to-100 band or a negative `offset` is a request-shape
    failure and is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/pagination_limit_above_hundred_returns_invalid_request
    """
    validate_error(api.list_cranes(DISPATCHER, params={"limit": 101, "offset": 0}),
                   ApiErrorId.ERR_INVALID_REQUEST.value, 400)
