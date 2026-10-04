"""Entity surface: creation echoes, system-minted ids, round-trips, listings, 404s, defaults."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    PASSENGER_OPERATOR_HEADERS,
    STATE_SPONSOR_HEADERS,
    SYSTEM_ADMIN_HEADERS,
    ApiErrorId,
    assert_created_equals_updated,
    assert_envelope_meta,
    assert_host_railroad,
    assert_list_page,
    assert_mutable_common_fields,
    factories,
    fixtures,
)


def test_host_railroad_create_returns_defaults_and_envelope(api):
    """A created host railroad carries 201, the object envelope, and version 1.

    PRD: "Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`."
    PRD: "The `response_type` is either "object" for a single resource or "array" for a list of resources."
    PRD: "Every resource in this API carries a standard set of system-managed fields: `id`, a server-minted unique identifier formatted as a UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created; `updated_at`, an ISO 8601 UTC timestamp refreshed on every modification; and `version`, an integer that increments by exactly one on every mutation of the resource and underpins optimistic concurrency control."
    Design: Corner/entities/host_railroad_create_returns_defaults_and_envelope
    """
    response = api.create_host_railroad(
        factories.host_railroad_payload(name="Great Plains Rail", reporting_mark="GPR"),
        SYSTEM_ADMIN_HEADERS,
    )

    host = validate_success(response, 201)
    body = response.json()
    assert body["response_type"] == "object"
    assert_envelope_meta(body)
    assert host["name"] == "Great Plains Rail"
    assert host["reporting_mark"] == "GPR"
    assert host["version"] == 1
    assert host["created_at"] is not None
    assert host["updated_at"] is not None
    assert_host_railroad(host)
    assert_created_equals_updated(host, "host_railroad")


def test_client_supplied_id_on_create_is_ignored(api):
    """A client-supplied id in the create body is ignored; the server mints its own UUID.

    PRD: "Every resource in this API carries a standard set of system-managed fields: `id`, a server-minted unique identifier formatted as a UUID with no type prefix"
    Design: Corner/entities/host_railroad_create_id_input_ignored
    """
    bogus_id = "11111111-2222-3333-4444-555555555555"
    response = api.create_host_railroad(
        factories.host_railroad_payload(name="Shadow Rail", reporting_mark="SHD", id=bogus_id),
        SYSTEM_ADMIN_HEADERS,
    )

    host = validate_success(response, 201)
    assert host["id"] != bogus_id


def test_agreement_get_round_trips_commercial_terms(api):
    """Every commercial term round-trips through GET; status/amendment_seq carry defaults.

    PRD: "The commercial heart of the system is the **OperatingAgreement**, drafted by a `PassengerOperator` with a payload carrying the `host_railroad_id`, the `corridor_id`, the `effective_from` and `effective_to` instants, the `on_time_threshold_minutes` (an arrival delayed by at most this many minutes counts as on time), the `penalty_rate_cents_per_minute` charged per host-attributed delay minute, the `incentive_rate_cents_per_train_mile` paid per completed train-mile when the OTP target is met, the `otp_target_pct` fraction (for example 0.80), and the `running_time_allowance_pct` — the host-negotiated schedule pad expressed as a fraction of pure running time. A new agreement is born in `DRAFT` with `amendment_seq` starting at zero."
    Design: Corner/entities/operating_agreement_get_round_trips_terms
    """
    net = fixtures.setup_draft_agreement(api)

    fetched = get_success_data(api.get_operating_agreement(net["agreement"]["id"], STATE_SPONSOR_HEADERS))

    assert fetched["on_time_threshold_minutes"] == 15
    assert fetched["penalty_rate_cents_per_minute"] == 50
    assert fetched["incentive_rate_cents_per_train_mile"] == 12
    assert fetched["otp_target_pct"] == 0.80
    assert fetched["running_time_allowance_pct"] == 0.25
    assert fetched["status"] == "DRAFT"
    assert fetched["amendment_seq"] == 0


def test_train_runs_list_paginates_with_filter(api):
    """Filtering a 2-run timetable by page yields one row per page with correct meta.

    PRD: "List endpoints are paginated through query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of leading items and defaults to 0."
    PRD: "List responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."
    Design: Corner/entities/train_runs_list_paginates_with_filter
    """
    net = fixtures.setup_published_timetable(api, trains_per_day=2, service_date="2026-09-03")
    timetable_id = net["timetable"]["id"]

    page1, meta1 = validate_paginated(
        api.list_train_runs(
            PASSENGER_OPERATOR_HEADERS, params={"timetable_id": timetable_id, "limit": 1, "offset": 0}
        )
    )
    assert len(page1) == 1
    assert_list_page(meta1, limit=1, offset=0, total=2, has_more=True)

    page2, meta2 = validate_paginated(
        api.list_train_runs(
            PASSENGER_OPERATOR_HEADERS,
            params={"timetable_id": timetable_id, "limit": 1, "offset": 1, "status": "SCHEDULED"},
        )
    )
    assert len(page2) == 1
    assert_list_page(meta2, limit=1, offset=1, total=2, has_more=False)
    assert page2[0]["id"] != page1[0]["id"]


def test_get_corridor_with_unknown_id_returns_404(api):
    """A well-formed UUID that does not exist returns 404 ERR_NOT_FOUND.

    PRD: "fourth, existence of every path identifier and every foreign-key identifier in the body (`ERR_NOT_FOUND`)"
    Design: Corner/entities/corridor_get_not_found_returns_404
    """
    response = api.get_corridor("3fa85f64-5717-4562-b3fc-2c963f66afa6", SYSTEM_ADMIN_HEADERS)

    assert response.status_code == 404
    validate_error(response, ApiErrorId.ERR_NOT_FOUND)


def test_corridor_create_missing_required_code_returns_validation(api):
    """Omitting the required field code on corridor create yields 400 ERR_VALIDATION.

    PRD: "first, request format — the body must be valid JSON with all required fields present, enum fields holding declared members, and numeric fields within range (a segment's `milepost_end` must be strictly greater than its `milepost_start`, a window's `window_end_at` must be strictly greater than its `window_start_at`, and coded `delay_minutes` must be at least zero), violations yielding `ERR_VALIDATION`"
    Design: Corner/entities/corridor_create_missing_required_code_returns_validation
    """
    net = fixtures.setup_network(api)
    payload = factories.corridor_payload(net["host"]["id"], name="No Code")
    payload.pop("code")

    response = api.create_corridor(payload, SYSTEM_ADMIN_HEADERS)

    assert response.status_code == 400
    validate_error(response, ApiErrorId.ERR_VALIDATION)


def test_corridor_create_invalid_enum_service_type_rejected(api):
    """A service_type outside the declared members yields 400 ERR_VALIDATION.

    PRD: "a `service_type` of `LONG_DISTANCE` or `STATE_SUPPORTED`"
    PRD: "first, request format — the body must be valid JSON with all required fields present, enum fields holding declared members, and numeric fields within range (a segment's `milepost_end` must be strictly greater than its `milepost_start`, a window's `window_end_at` must be strictly greater than its `window_start_at`, and coded `delay_minutes` must be at least zero), violations yielding `ERR_VALIDATION`"
    Design: Corner/entities/corridor_create_invalid_enum_service_type_rejected
    """
    net = fixtures.setup_network(api)
    payload = factories.corridor_payload(net["host"]["id"], service_type="MAGLEV")

    response = api.create_corridor(payload, SYSTEM_ADMIN_HEADERS)

    assert response.status_code == 400
    validate_error(response, ApiErrorId.ERR_VALIDATION)


def test_timetable_created_in_draft_with_revision_zero(api):
    """A created timetable starts in DRAFT with revision_no 0 without client input.

    PRD: "A new timetable is `DRAFT` with `revision_no` zero."
    Design: Corner/entities/timetable_defaults_draft_and_revision_zero
    """
    net = fixtures.setup_draft_agreement(api)

    timetable = fixtures.create_timetable(api, net)

    assert timetable["status"] == "DRAFT"
    assert timetable["revision_no"] == 0
    assert_mutable_common_fields(timetable, "timetable")
