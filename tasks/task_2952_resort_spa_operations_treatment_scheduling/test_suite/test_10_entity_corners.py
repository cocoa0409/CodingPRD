"""Entity-level corners: server-minted common fields and omitted defaults, the
three distinct refusal reasons on one collection, per-collection 404 identities,
left-to-right path resolution, write-once audit rows, server-owned computed
fields, declared-order body reference resolution and the listing envelope.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_audit_row_fields,
    assert_common_fields,
    assert_same_instant,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.constants import CLOCK_STARTUP_DEFAULT
from test_helpers import factories as f
from test_helpers import fixtures as fx

DEFAULT_CLOCK_INSTANT = "2026-08-01T00:00:00.000Z"


def test_omitted_optional_menu_fields_default_and_common_fields_are_server_minted():
    """DRY60 registers without contraindication_codes or high_demand.

    PRD §3.1: "`contraindication_codes` is an array of uppercase condition codes
    that bar the treatment outright; it is optional on registration and defaults
    to an empty array."

    PRD §3.1: "`high_demand` is a boolean that defaults to false; marking an item
    as high-demand feeds both the price surcharge and the late-cancellation uplift
    described later."

    PRD §2.5: "Most resources additionally expose `updated_at`, an ISO 8601 UTC
    instant refreshed on every mutation of that resource, and `version`, an
    integer that starts at 1 on creation and increments by exactly 1 on every
    mutation of that resource."

    PRD §2.4: "Before the clock has ever been set, it reads exactly
    `2026-08-01T00:00:00Z`; it never falls back to real time."

    Design: Corner/entities/treatment_type_defaults_and_system_fields
    """
    assert CLOCK_STARTUP_DEFAULT.startswith("2026-08-01T00:00:00"), (
        "this test never sets the clock, so both stamps must be the startup value")

    created = validate_success(api_client.create_treatment_type(
        f.treatment_type_payload(
            code="DRY60", name="Swedish Dry 60", duration_minutes=60,
            room_class_required="DRY", required_skill_code="SWEDISH",
            required_scope_level="BASIC", base_price_cents=18000,
            retail_product_line="MARINE", required_consent_version="2026.1",
            contraindication_codes=None, high_demand=None),
        fx.DIRECTOR), 201)

    assert created["contraindication_codes"] == [], (
        "the omitted array defaults to empty, got "
        f"{created['contraindication_codes']!r}")
    assert created["high_demand"] is False, (
        f"the omitted boolean defaults to false, got {created['high_demand']!r}")

    assert_common_fields(created, "treatment type")
    assert created["version"] == 1
    assert_same_instant(created["created_at"], DEFAULT_CLOCK_INSTANT, "created_at")
    assert_same_instant(created["updated_at"], DEFAULT_CLOCK_INSTANT, "updated_at")
    assert created["base_price_cents"] == 18000


def test_missing_field_bad_enum_and_duplicate_code_are_three_distinct_refusals():
    """Two 422s from rung 3 and one 409 from rung 6, never confused.

    PRD §2.7 rung 3: "**Request shape** — required fields present, enum values
    legal, integers within their declared ranges, datetimes valid ISO 8601 UTC
    instants, dates valid calendar dates, `limit` within 1 through 100 and
    `offset` not negative. Applies to every endpoint. Violation:
    `ERR_INVALID_REQUEST` (422)."

    PRD §2.7 rung 6: "**Code uniqueness** — a treatment type's `code` is unique
    across all treatment types and a room's `code` is unique across all rooms.
    Applies to treatment-type registration and room registration. Violation:
    `ERR_DUPLICATE_CODE` (409)."

    PRD §3.1: "Rooms are registered by a `SpaDirector` too, with a `code` unique
    across all rooms and between 1 and 24 characters, a physical `room_class`
    drawn from the same four values, a `capacity_guests` of 1 or 2, a
    `turnover_buffer_minutes` between 0 and 60 that represents the sanitation and
    reset time appended to every appointment's occupancy in that room, and an
    `hourly_fixed_cost_cents` of at least 0 that the margin calculations charge
    against delivered minutes."

    Design: Corner/entities/treatment_room_required_fields_enums_and_code_uniqueness
    """
    room = fx.create_room("HYDRO-1")
    assert room["capacity_guests"] == 1

    missing_cost = api_client.create_treatment_room(
        f.treatment_room_payload(code="DRY-1", room_class="DRY",
                                 turnover_buffer_minutes=15,
                                 hourly_fixed_cost_cents=None),
        fx.DIRECTOR)
    validate_error(missing_cost, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    bad_enum = api_client.create_treatment_room(
        f.treatment_room_payload(code="DRY-2", room_class="SAUNA",
                                 turnover_buffer_minutes=15,
                                 hourly_fixed_cost_cents=2500),
        fx.DIRECTOR)
    validate_error(bad_enum, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    duplicate = api_client.create_treatment_room(
        f.treatment_room_payload(code="HYDRO-1", capacity_guests=2),
        fx.DIRECTOR)
    error = validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_CODE.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value, (
        "the duplicate body is otherwise well shaped, so rung 3 passes and rung 6 "
        "is the first violated rung")

    assert validate_success(
        api_client.get_treatment_room(room["id"], fx.DIRECTOR)
    )["capacity_guests"] == 1, (
        "the refused duplicate did not overwrite the surviving room")


def test_every_path_addressed_collection_raises_its_own_not_found_identity():
    """Eight unknown ids, eight distinct 404 error ids.

    PRD §2.7 rung 4: "**Path existence** — every identifier in the URL path
    resolves, checked strictly left to right, so the guest, therapist, licence or
    appointment segment is resolved before any segment nested to its right.
    Applies to every endpoint carrying a path parameter. Violation is the 404
    matching the first unresolved segment: `ERR_GUEST_NOT_FOUND`,
    `ERR_THERAPIST_NOT_FOUND`, `ERR_LICENSE_NOT_FOUND`,
    `ERR_CERTIFICATION_NOT_FOUND`, `ERR_INTAKE_FORM_NOT_FOUND`,
    `ERR_APPOINTMENT_NOT_FOUND`, `ERR_RETAIL_ATTACHMENT_NOT_FOUND` or
    `ERR_ROOM_NOT_FOUND`."

    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."

    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/entities/not_found_on_every_path_addressed_collection
    """
    compliance = fx.make_compliance_headers(fx.CO_SUBMIT)
    probes = [
        ("GET /treatment-rooms/{id}",
         lambda: api_client.get_treatment_room(NON_EXISTENT_UUID, fx.DIRECTOR),
         ApiErrorId.ERR_ROOM_NOT_FOUND.value),
        ("GET /therapists/{id}",
         lambda: api_client.get_therapist(NON_EXISTENT_UUID, fx.DIRECTOR),
         ApiErrorId.ERR_THERAPIST_NOT_FOUND.value),
        ("GET /therapist-licenses/{id}",
         lambda: api_client.get_license(NON_EXISTENT_UUID, compliance),
         ApiErrorId.ERR_LICENSE_NOT_FOUND.value),
        ("POST /certifications/{id}/revoke",
         lambda: api_client.revoke_certification(
             NON_EXISTENT_UUID, f.revoke_payload("n/a"), compliance),
         ApiErrorId.ERR_CERTIFICATION_NOT_FOUND.value),
        ("GET /guests/{id}",
         lambda: api_client.get_guest(NON_EXISTENT_UUID, fx.COORDINATOR),
         ApiErrorId.ERR_GUEST_NOT_FOUND.value),
        ("GET /intake-forms/{id}",
         lambda: api_client.get_intake_form(NON_EXISTENT_UUID, fx.COORDINATOR),
         ApiErrorId.ERR_INTAKE_FORM_NOT_FOUND.value),
        ("GET /appointments/{id}",
         lambda: api_client.get_appointment(NON_EXISTENT_UUID, fx.COORDINATOR),
         ApiErrorId.ERR_APPOINTMENT_NOT_FOUND.value),
        ("POST /retail-attachments/{id}/resolve",
         lambda: api_client.resolve_retail_attachment(
             NON_EXISTENT_UUID, f.resolve_payload("DECLINED"), fx.COORDINATOR),
         ApiErrorId.ERR_RETAIL_ATTACHMENT_NOT_FOUND.value),
    ]

    for label, call, expected_error_id in probes:
        error = validate_error(call(), expected_error_id, 404)
        assert error["error_id"] == expected_error_id, (
            f"{label} must raise its own 404 identity rather than a shared one")
        assert isinstance(error["message"], str) and error["message"], (
            f"{label}: the 404 envelope carries a message string")

    assert len({expected for _, _, expected in probes}) == 8, (
        "the eight collections are pinned to eight distinct error ids")


def test_the_parent_segment_is_resolved_before_the_child_body_is_judged():
    """404 on the unknown therapist beats the 422 the same body would earn.

    PRD §2.7 rung 4: "**Path existence** — every identifier in the URL path
    resolves, checked strictly left to right, so the guest, therapist, licence or
    appointment segment is resolved before any segment nested to its right."

    PRD §3.3: "Three consistency conditions are enforced on filing, each rejected
    with `ERR_INVALID_REQUEST`: the `state_code` must equal the therapist's
    `practice_state_code`, `expires_on` must be strictly after `issued_on`, and
    `current_period_start_on` must be on or before `expires_on`."

    PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and
    `has_more` inside the envelope's `meta` object, where `total_count` is the
    number of records matching the request's filters before pagination is applied
    and `has_more` states whether any matching record remains beyond the returned
    page."

    Design: Corner/entities/nested_path_existence_resolves_left_to_right
    """
    therapist = fx.create_therapist()
    guest = fx.create_guest()
    compliance = fx.make_compliance_headers(fx.CO_SUBMIT)
    body = f.license_payload(license_number="HI-LMT-0001", state_code="HI",
                             expires_on="2026-12-31",
                             current_period_start_on="2024-01-01",
                             ce_hours_required=None)

    unknown_parent = api_client.create_license(NON_EXISTENT_UUID, body, compliance)
    validate_error(unknown_parent, ApiErrorId.ERR_THERAPIST_NOT_FOUND.value, 404)

    wrong_state = api_client.create_license(
        therapist["id"],
        f.license_payload(license_number="HI-LMT-0001", state_code="CA",
                          expires_on="2026-12-31",
                          current_period_start_on="2024-01-01",
                          ce_hours_required=None),
        compliance)
    error = validate_error(wrong_state, ApiErrorId.ERR_INVALID_REQUEST.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_THERAPIST_NOT_FOUND.value, (
        "the parent resolves here, so the body's own consistency condition is "
        "what refuses the filing")
    assert therapist["practice_state_code"] == "HI", (
        "CA disagrees with the therapist's practice state, which is the rule "
        "under test")

    forms, forms_meta = validate_paginated(api_client.list_intake_forms(
        guest["id"], fx.COORDINATOR, params={"limit": 10, "offset": 0}))
    assert forms == [], (
        f"a valid parent with no children is an empty 200, got {forms}")
    assert forms_meta["total_count"] == 0
    assert forms_meta["has_more"] is False

    licences, licence_meta = validate_paginated(
        api_client.list_licenses(therapist["id"], compliance))
    assert licences == [] and licence_meta["total_count"] == 0, (
        "neither refused filing created a licence row")


def test_a_continuing_education_record_is_a_write_once_audit_row():
    """No version, no updated_at, and the officer comes from the header.

    PRD §2.5: "Two record types are write-once audit rows and therefore carry
    only `id` and `created_at` — both `updated_at` and `version` are absent from
    them."

    PRD §3.3: "The filing officer is recorded as `recorded_by_user_id`. These
    records are audit rows: they are immutable, there is no capability to update
    one, and the `license_id` they hang off is taken from the creation path rather
    than from the body."

    PRD §2.3: "Every list endpoint accepts two query parameters. `limit` caps the
    number of records returned; it defaults to 10, its minimum accepted value is 1
    and its maximum accepted value is 100. `offset` skips that many records before
    the page begins; it defaults to 0 and its minimum accepted value is 0."

    Design: Corner/entities/immutable_entities_have_no_version_and_no_update_endpoint
    """
    therapist = fx.create_therapist(full_name="Kai Mahelona",
                                    commission_tier="MASTER",
                                    base_hourly_cost_cents=6000)
    licence = fx.submit_license(therapist["id"], submit_user=fx.CO_SUBMIT,
                                license_number="HI-LMT-9002",
                                issued_on="2022-01-01", expires_on="2027-06-30",
                                current_period_start_on="2024-01-01",
                                ce_hours_required=12)
    assert licence["verification_status"] == "PENDING_REVIEW"

    record = validate_success(api_client.create_ce_record(
        licence["id"],
        f.ce_record_payload(course_code="ETH-201", category="ETHICS",
                            ce_hours=3.0, completed_on="2024-03-15"),
        fx.make_compliance_headers(fx.CO_SUBMIT)), 201)

    assert_audit_row_fields(record, "continuing-education record")
    assert record["recorded_by_user_id"] == fx.CO_SUBMIT, (
        "the officer is derived from X-User-ID, never from the body; got "
        f"{record.get('recorded_by_user_id')!r}")
    assert record["course_code"] == "ETH-201"
    assert record["category"] == "ETHICS"

    rows, meta = validate_paginated(api_client.list_ce_records(
        licence["id"], fx.make_compliance_headers(fx.CO_SUBMIT),
        params={"category": "ETHICS"}))
    assert len(rows) == 1 and rows[0]["id"] == record["id"]
    assert meta["total_count"] == 1
    assert meta["limit"] == 10, (
        f"the omitted limit defaults to 10, got {meta['limit']}")
    assert meta["offset"] == 0, (
        f"the omitted offset defaults to 0, got {meta['offset']}")
    assert meta["has_more"] is False
    assert "version" not in rows[0] and "updated_at" not in rows[0], (
        "the listed row exposes the same audit-row shape as the created one")


def test_screening_writes_three_derived_places_and_flags_only_registry_members():
    """LATEX_SENSITIVITY is recorded faithfully and never flags.

    PRD §3.4: "The registry of high-risk conditions is a closed literal set of
    five codes — `ACUTE_HYPERTENSION`, `PREGNANCY_FIRST_TRIMESTER`,
    `DEEP_VEIN_THROMBOSIS`, `RECENT_SURGERY_90D` and `ACTIVE_INFECTION` — and it
    is not configurable. Comparison is exact string equality, so a declared code
    that is not one of those five is recorded faithfully and never flags."

    PRD §3.4: "Both screening outcomes rewrite `authoritative_intake_form_id` to
    the freshly screened form and copy that form's full `condition_codes` — not
    merely the flagged subset — into the guest's `screened_condition_codes`, which
    is the input set every contraindication check reads."

    PRD §3.4: "Registration initialises the whole derived block:
    `folio_balance_cents` at 0, `late_cancel_count` at 0, `no_show_strikes` at 0,
    `booking_privilege` at `OPEN`, `authoritative_intake_form_id` at null and
    `screened_condition_codes` at an empty array."

    Design: Corner/entities/computed_guest_pointer_and_screened_codes_are_server_owned
    """
    guest = fx.create_guest(loyalty_tier="GOLD")
    assert guest["authoritative_intake_form_id"] is None
    assert guest["screened_condition_codes"] == []
    guest_headers = fx.make_guest_headers(guest["id"])

    intake = validate_success(api_client.create_intake_form(
        guest["id"],
        f.intake_form_payload(guest["version"],
                              condition_codes=["ACTIVE_INFECTION",
                                               "LATEX_SENSITIVITY"],
                              medications=["AMOXICILLIN"]),
        guest_headers), 201)
    assert intake["status"] == "DRAFT"
    validate_success(api_client.submit_intake_form(intake["id"], {}, guest_headers))

    before = validate_success(api_client.get_guest(guest["id"], fx.COORDINATOR))
    assert before["authoritative_intake_form_id"] is None, (
        "an unscreened form does not make the guest's pointer non-null")

    screened = validate_success(api_client.screen_intake_form(
        intake["id"], {}, fx.make_compliance_headers(fx.CO_SCREEN)))
    assert screened["status"] == "SCREENED_FLAGGED"
    assert screened["flagged_condition_codes"] == ["ACTIVE_INFECTION"], (
        "only the registry member flags; got "
        f"{screened['flagged_condition_codes']}")
    assert screened["condition_codes"] == ["ACTIVE_INFECTION",
                                          "LATEX_SENSITIVITY"]
    assert screened["medications"] == ["AMOXICILLIN"]
    assert screened["screened_by_user_id"] == fx.CO_SCREEN

    after = validate_success(api_client.get_guest(guest["id"], fx.COORDINATOR))
    assert after["authoritative_intake_form_id"] == intake["id"]
    assert after["screened_condition_codes"] == ["ACTIVE_INFECTION",
                                                "LATEX_SENSITIVITY"], (
        "the full declared set is copied, not the flagged subset; got "
        f"{after['screened_condition_codes']}")
    assert after["version"] == before["version"] + 1, (
        "each screening increments the guest's version by exactly 1")


def test_unresolvable_body_ids_are_reported_in_the_declared_field_order():
    """guest_id first, then treatment_type_id, whatever else is unknown.

    PRD §2.7 rung 5: "**Body reference existence** — every identifier supplied in
    a request body resolves, checked in the body-field order `guest_id`, then
    `treatment_type_id`, then `room_id`, then `therapist_id`. Applies to
    appointment booking. Violation: `ERR_GUEST_NOT_FOUND`,
    `ERR_TREATMENT_TYPE_NOT_FOUND`, `ERR_ROOM_NOT_FOUND` or
    `ERR_THERAPIST_NOT_FOUND` (404)."

    PRD §2.7: "The server walks the ladder from the top and returns the error of
    the **first** rung the request violates; lower rungs are not evaluated once a
    rung has failed."

    Design: Corner/entities/body_foreign_keys_validated_in_declared_field_order
    """
    room = fx.create_room("HYDRO-1")
    therapist = fx.create_therapist()
    guest = fx.create_guest()
    start_at = "2026-08-10T17:00:00.000Z"

    all_unknown = api_client.create_appointment(
        f.appointment_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID,
                              NON_EXISTENT_UUID, start_at, NON_EXISTENT_UUID),
        fx.COORDINATOR)
    validate_error(all_unknown, ApiErrorId.ERR_GUEST_NOT_FOUND.value, 404)

    only_menu_unknown = api_client.create_appointment(
        f.appointment_payload(guest["id"], NON_EXISTENT_UUID, room["id"],
                              start_at, therapist["id"]),
        fx.COORDINATOR)
    validate_error(only_menu_unknown,
                   ApiErrorId.ERR_TREATMENT_TYPE_NOT_FOUND.value, 404)

    three_unknown = api_client.create_appointment(
        f.appointment_payload(guest["id"], NON_EXISTENT_UUID, NON_EXISTENT_UUID,
                              start_at, NON_EXISTENT_UUID),
        fx.COORDINATOR)
    error = validate_error(three_unknown,
                           ApiErrorId.ERR_TREATMENT_TYPE_NOT_FOUND.value, 404)
    assert error["error_id"] not in (ApiErrorId.ERR_ROOM_NOT_FOUND.value,
                                    ApiErrorId.ERR_THERAPIST_NOT_FOUND.value), (
        "with three ids unresolvable the declared order decides, so the room and "
        "therapist ids are never reached")

    _rows, meta = validate_paginated(api_client.list_appointments(fx.COORDINATOR))
    assert meta["total_count"] == 0, (
        f"no appointment was created by any trigger, got {meta['total_count']}")


def test_a_zero_length_shift_block_and_an_out_of_range_limit_are_both_refused():
    """end_at must be strictly after start_at, and limit must stay within 1..100.

    PRD §3.2: "A block carries a `block_type` of `AVAILABLE`, `BREAK` or `ADMIN`,
    an inclusive `start_at`, an inclusive `end_at` that must be strictly after
    `start_at`, and an optional scheduling `note` that defaults to null; a block
    whose `end_at` is not strictly after its `start_at` is rejected with
    `ERR_INVALID_REQUEST`."

    PRD §2.3: "A `limit` outside the range of 1 through 100, or a negative
    `offset`, is a shape violation and is rejected with `ERR_INVALID_REQUEST`
    (HTTP 422)."

    Design: Corner/entities/shift_block_bounds_and_pagination_envelope
    """
    therapist = fx.create_therapist()
    fx.add_shift_block(therapist["id"], block_type="AVAILABLE",
                       start_at="2026-08-10T08:00:00.000Z",
                       end_at="2026-08-10T22:00:00.000Z")

    zero_length = api_client.create_shift_block(
        therapist["id"],
        f.shift_block_payload(block_type="AVAILABLE",
                              start_at="2026-08-12T10:00:00.000Z",
                              end_at="2026-08-12T10:00:00.000Z"),
        fx.COORDINATOR)
    validate_error(zero_length, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    over_limit = api_client.list_shift_blocks(
        therapist["id"], fx.COORDINATOR, params={"limit": 101, "offset": 0})
    validate_error(over_limit, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    zero_limit = api_client.list_shift_blocks(
        therapist["id"], fx.COORDINATOR, params={"limit": 0, "offset": 0})
    validate_error(zero_limit, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    rows, meta = validate_paginated(
        api_client.list_shift_blocks(therapist["id"], fx.COORDINATOR))
    assert meta["total_count"] == 1, (
        f"only the legal block survives, got {meta['total_count']}")
    assert rows[0]["note"] is None, (
        f"the omitted note defaults to null, got {rows[0]['note']!r}")


def test_the_shift_block_listing_envelope_is_exact_across_two_pages():
    """limit, offset, total_count and has_more are computed, not guessed.

    PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and
    `has_more` inside the envelope's `meta` object, where `total_count` is the
    number of records matching the request's filters before pagination is applied
    and `has_more` states whether any matching record remains beyond the returned
    page."

    PRD §2.3: "Unless a specific list endpoint states otherwise, records are
    returned sorted by their creation timestamp `created_at` in ascending order."

    PRD §3.2: "A therapist's blocks are listable with an optional `block_type`
    filter and an optional `from_at` and `to_at` window."

    Design: Corner/entities/shift_block_bounds_and_pagination_envelope
    """
    therapist = fx.create_therapist()
    fx.add_shift_block(therapist["id"], block_type="AVAILABLE",
                       start_at="2026-08-10T08:00:00.000Z",
                       end_at="2026-08-10T22:00:00.000Z")
    fx.add_shift_block(therapist["id"], block_type="BREAK",
                       start_at="2026-08-10T12:00:00.000Z",
                       end_at="2026-08-10T13:00:00.000Z", note="lunch")
    fx.add_shift_block(therapist["id"], block_type="ADMIN",
                       start_at="2026-08-11T08:00:00.000Z",
                       end_at="2026-08-11T09:00:00.000Z")

    first_page, first_meta = validate_paginated(api_client.list_shift_blocks(
        therapist["id"], fx.COORDINATOR, params={"limit": 2, "offset": 0}))
    assert len(first_page) == 2
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True, (
        "one matching record remains beyond the page, so has_more is true")
    assert [row["block_type"] for row in first_page] == ["AVAILABLE", "BREAK"], (
        "the default ordering is ascending created_at")

    second_page, second_meta = validate_paginated(api_client.list_shift_blocks(
        therapist["id"], fx.COORDINATOR, params={"limit": 2, "offset": 2}))
    assert len(second_page) == 1
    assert second_meta["offset"] == 2
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False, (
        "has_more is computed from the remainder, not from the page being short")
    assert second_page[0]["block_type"] == "ADMIN"

    filtered, filtered_meta = validate_paginated(api_client.list_shift_blocks(
        therapist["id"], fx.COORDINATOR, params={"block_type": "BREAK"}))
    assert filtered_meta["total_count"] == 1, (
        "total_count counts the records matching the filter before pagination")
    assert len(filtered) == 1
    assert filtered[0]["note"] == "lunch"
