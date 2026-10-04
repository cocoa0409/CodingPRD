"""Access control, section routing invariants, OCC, and the response envelope."""
import pytest

from test_helpers import (
    api_client, ADMIN, LEAD, PROGRAMMER, NON_EXISTENT_UUID,
    validate_success, validate_error, validate_paginated, get_success_data,
    assert_auditorium, assert_menu_item, assert_themed_menu_item, assert_showtime,
    assert_server, make_auditorium, make_menu_item, make_server, make_showtime,
    make_programming_event, make_themed_menu_item, set_clock, server_headers,
    read_section, read_server, read_showtime, read_slip,
    make_headers_with_unknown_role, headers_without_user_id,
    headers_without_role, TEST_USERS,
    setup_dining_open_showtime, setup_themed_event,
    setup_three_servers_one_section, setup_servobuffer_candidate_showtimes,
    setup_daily_cap_showtimes,
)


# ─── Authentication and authorisation (PRD §2.1) ──────────────────────

@pytest.mark.parametrize("bad_headers", [
    headers_without_user_id(),
    headers_without_role("test-no-role-1"),
    make_headers_with_unknown_role("test-undeclared-1"),
])
def test_an_unusable_user_context_is_refused_on_every_write(api, bad_headers):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` carries a value
    that is not one of the platform's declared roles, the request is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_user_context_header_rejected_on_every_write
    """
    existing = make_auditorium(name="Theater 14")
    refused = api_client.create_auditorium({"name": "Ghost Room", "seat_capacity": 0}, bad_headers)
    validate_error(refused, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")
    assert refused.status_code == 400

    listed, meta = validate_paginated(api_client.list_auditoriums(TEST_USERS["platform_admin_headers"]))
    assert meta["total_count"] == 1, "no auditorium row was created by the refused call"
    assert listed[0]["id"] == existing["id"]


def test_the_anonymous_role_holds_no_operation_at_all(api, anonymous_headers):
    """PRD §2.1: "`Anonymous` exists purely so that the authentication row can be
    asserted: it holds no exclusive or shared operations whatsoever, and any
    request presenting it fails the role check rather than passing it."

    Design: Corner/validations/missing_user_context_header_rejected_on_every_write
    """
    refused = api_client.create_auditorium(
        {"name": "Ghost Room", "seat_capacity": 60}, anonymous_headers
    )
    # §2.6 lists "no exclusive operations and no shared operations" for this role,
    # so a real-but-unrostered role fails the roster check rather than the
    # header check.
    validate_error(refused, "ERR_UNAUTHORIZED_ROLE")
    assert refused.status_code == 403


def test_authorisation_is_decided_before_the_path_id_is_looked_up(api):
    """PRD §2.1: "Both checks run before any resource is looked up, so a caller
    from the wrong role never learns whether the identifier in the path exists."

    Design: Corner/validations/unauthorized_role_is_refused_before_any_existence_check
    """
    make_auditorium(name="Theater 15")
    refused = api_client.complete_showtime(NON_EXISTENT_UUID, TEST_USERS["server_headers"])
    validate_error(refused, "ERR_UNAUTHORIZED_ROLE")
    assert refused.status_code == 403, (
        "the declared role is not on this endpoint's roster, so authorisation wins over existence"
    )


def test_the_server_role_may_not_roster_sections(api):
    """PRD §2.1: "If the declared role is real but is not on the permitted roster
    for the addressed operation, the request is rejected with
    `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §2.1: "Each role owns a distinct slice of the operation and no role can
    override another's".

    Design: Corner/rbac/server_role_cannot_assign_sections_or_approve_ejections
    """
    set_clock("2026-09-01T19:40:00Z")
    auditorium = make_auditorium(name="Theater 25")
    first = make_server(auditorium["id"], "Omar")
    second = make_server(auditorium["id"], "Pia")
    showtime = make_showtime(auditorium["id"], "2026-09-01T20:00:00Z", 100)

    refused = api_client.create_section_assignment(
        {"showtime_id": showtime["id"], "server_id": second["id"], "section_label": "LEFT"},
        server_headers(first),
    )
    validate_error(refused, "ERR_UNAUTHORIZED_ROLE")
    assert refused.status_code == 403, "authorisation was evaluated before any existence check"


def test_the_server_role_may_not_approve_an_ejection(api):
    """PRD §3.10: "Ejecting a guest is the kitchen lead's decision, and it is the
    gravest action in the platform."
    PRD §2.1: "the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

    Design: Corner/rbac/server_role_cannot_assign_sections_or_approve_ejections
    """
    scenario = setup_dining_open_showtime(clock="2026-09-01T19:40:00Z")
    refused = api_client.approve_ejection(NON_EXISTENT_UUID, server_headers(scenario["server"]))
    validate_error(refused, "ERR_UNAUTHORIZED_ROLE")
    assert refused.status_code == 403, (
        "neither refusal is an existence error, so authorisation ran first"
    )


def test_the_kitchen_lead_may_not_approve_pre_show_content(api):
    """PRD §3.2: "A producer then either approves the cut — moving it to
    `PRE_SHOW_APPROVED` when it is `PRE_SHOW_IN_REVIEW`".
    PRD §2.1: "If the declared role is real but is not on the permitted roster for
    the addressed operation, the request is rejected with `ERR_UNAUTHORIZED_ROLE`
    (HTTP 403)."

    Design: Corner/rbac/kitchen_lead_cannot_approve_pre_show_content
    """
    staged = setup_themed_event(state="IN_REVIEW")
    event = staged["event"]
    assert event["pre_show_content_status"] == "PRE_SHOW_IN_REVIEW"

    refused = api_client.approve_pre_show_content(event["id"], {}, LEAD)
    validate_error(refused, "ERR_UNAUTHORIZED_ROLE")
    assert refused.status_code == 403

    still = get_success_data(api_client.get_programming_event(event["id"], PROGRAMMER))
    assert still["pre_show_content_status"] == "PRE_SHOW_IN_REVIEW", "the refused call changed nothing"

    approved = validate_success(
        api_client.approve_pre_show_content(event["id"], {}, TEST_USERS["pre_show_producer_headers"]),
        200,
    )
    assert approved["pre_show_content_status"] == "PRE_SHOW_APPROVED"


# ─── Section routing invariants (PRD §2.11) ───────────────────────────

def test_a_ten_minute_separation_between_sections_is_rejected(api):
    """PRD §2.11: "Two of a server's active assignments, in any auditoriums,
    whose on-floor intervals are separated by less than `SERVO_BUFFER_MINUTES` —
    fifteen minutes — are rejected with `ERR_SERVER_SECTION_OVERLAP` (HTTP 409)."
    PRD §2.11: "A server's on-floor interval for a showtime is the closed interval
    running from that showtime's `dining_open_at_utc` to its `start_at_utc`."

    Design: Difficulty/resource_temporal_overlap/servobuffer_overlap_on_the_section_resource
    """
    scenario = setup_servobuffer_candidate_showtimes()
    server = scenario["server"]
    refused = api_client.create_section_assignment(
        {"showtime_id": scenario["too_close"]["id"], "server_id": server["id"],
         "section_label": "CENTER"}, LEAD,
    )
    validate_error(refused, "ERR_SERVER_SECTION_OVERLAP")
    assert refused.status_code == 409
    assert scenario["too_close"]["status"] == "SCHEDULED", (
        "the candidate is a real, schedulable showtime; only the routing rule refused it"
    )


def test_a_fifteen_minute_separation_is_admitted_as_the_boundary(api):
    """PRD §2.11: "A separation of exactly fifteen minutes is admitted; the
    boundary is permissive at the stated figure."

    Design: Difficulty/resource_temporal_overlap/servobuffer_overlap_on_the_section_resource
    """
    scenario = setup_servobuffer_candidate_showtimes()
    server = scenario["server"]
    admitted = validate_success(api_client.create_section_assignment(
        {"showtime_id": scenario["admitted"]["id"], "server_id": server["id"],
         "section_label": "RIGHT"}, LEAD,
    ), 201)
    assert admitted["status"] == "ACTIVE"
    held = scenario["held"]
    assert held["start_at_utc"].endswith("20:00:00Z"), "the held window closes at 20:00"
    assert scenario["too_close"]["start_at_utc"] != scenario["admitted"]["start_at_utc"]
    assert scenario["admitted"]["start_at_utc"].endswith("20:35:00Z"), (
        "the admitted candidate opens exactly fifteen minutes after the held show "
        "begins, so the separation is the buffer's own floor"
    )
    assert scenario["admitted"]["dining_open_at_utc"].endswith("20:15:00Z"), (
        "its on-floor interval runs [20:15, 20:35], starting where the held "
        "showtime's dining window closes"
    )
    assert scenario["admitted"]["version"] == 1, (
        "the permissive boundary admitted the placement rather than merely tolerating it"
    )


def test_the_fourth_assignment_of_a_service_day_is_rejected(api):
    """PRD §2.11: "A server may hold at most `DAILY_SECTION_CAP` — three —
    non-terminal assignments created on the same service day, counted across the
    whole day rather than at any single instant. The fourth assignment of the day
    is rejected with `ERR_SERVER_HARD_CAP_EXCEEDED` (HTTP 409)".
    PRD §2.11: "while the third is admitted even when all three overlap one another
    in time."

    Design: Difficulty/resource_temporal_overlap/aggregate_daily_cap_on_the_server_resource
    """
    scenario = setup_daily_cap_showtimes()
    server, fourth = scenario["server"], scenario["showtimes"][3]
    assert len(scenario["assignments"]) == 3, "the first three were admitted"

    refused = api_client.create_section_assignment(
        {"showtime_id": fourth["id"], "server_id": server["id"], "section_label": "LEFT"}, LEAD,
    )
    validate_error(refused, "ERR_SERVER_HARD_CAP_EXCEEDED")
    assert refused.status_code == 409, (
        "the fourth showtime has no service-time overlap with the others, so it is the whole-day count that rejected it"
    )


def test_a_rejected_assignment_does_not_enter_the_shift_count(api):
    """PRD §3.9: "The projected figure, reported as `shift_load_projected`, counts
    every assignment belonging to that server whose creation date falls on the
    current service day *and* which is not cancelled".
    PRD §2.11: "A server may hold at most `DAILY_SECTION_CAP` — three".

    Design: Difficulty/resource_temporal_overlap/aggregate_daily_cap_on_the_server_resource
    """
    scenario = setup_daily_cap_showtimes()
    server, fourth = scenario["server"], scenario["showtimes"][3]
    before = read_server(server["id"], LEAD)
    assert before["shift_load_projected"] == 3

    validate_error(api_client.create_section_assignment(
        {"showtime_id": fourth["id"], "server_id": server["id"], "section_label": "LEFT"}, LEAD,
    ), "ERR_SERVER_HARD_CAP_EXCEEDED")

    after = read_server(server["id"], LEAD)
    assert after["shift_load_projected"] == 3, (
        "a rejected assignment does not enter the count"
    )


def test_one_person_cannot_hold_two_places_in_the_same_section(api):
    """PRD §2.11: "A server may not hold two non-terminal assignments for the same
    auditorium carrying the same `section_label`, because that would seat one
    person in two places. The rejection is `ERR_SECTION_OCCUPIED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/aggregate_daily_cap_on_the_server_resource
    """
    scenario = setup_servobuffer_candidate_showtimes()
    server = scenario["server"]
    # PRD §2.11: "a server may not hold two non-terminal assignments for the same
    # auditorium carrying the same `section_label`". The probe runs on a showtime
    # of the held room, whose window opens after the held one has closed, so the
    # temporal-separation invariant is silent and occupancy is what answers.
    refused = api_client.create_section_assignment(
        {"showtime_id": scenario["same_room"]["id"], "server_id": server["id"],
         "section_label": "LEFT"}, LEAD,
    )
    validate_error(refused, "ERR_SECTION_OCCUPIED")
    assert refused.status_code == 409


# ─── Optimistic concurrency (PRD §2.7) ────────────────────────────────

def test_a_stale_section_version_is_refused_on_the_second_reassignment(api):
    """PRD §2.7: "Reassigning a section's server carries
    `expected_section_assignment_version`, which must equal the assignment's
    current `version`; otherwise the reassignment is refused with
    `ERR_STALE_SECTION_ASSIGNMENT_VERSION` (HTTP 412)."
    PRD §3.9: "a successful replacement moves the assignment through
    `REASSIGNMENT_PENDING` and back to `ACTIVE` with the new server attached,
    advances the assignment's `version` by one".

    Design: Corner/cross_cutting_layers/optimistic_concurrency_version_advances_on_every_section_reassignment
    """
    scenario = setup_three_servers_one_section()
    assignment, first, second, third = (
        scenario["assignment"], scenario["server_s1"],
        scenario["server_s2"], scenario["server_s3"],
    )
    stale_version = assignment["version"]

    swapped = validate_success(api_client.reassign_section(
        assignment["id"],
        {"server_id": second["id"], "expected_section_assignment_version": stale_version},
        LEAD,
    ), 200)
    assert swapped["server_id"] == second["id"]
    assert swapped["version"] > stale_version

    refused = api_client.reassign_section(
        assignment["id"],
        {"server_id": third["id"], "expected_section_assignment_version": stale_version},
        LEAD,
    )
    validate_error(refused, "ERR_STALE_SECTION_ASSIGNMENT_VERSION")
    assert refused.status_code == 412
    assert read_section(assignment["id"], LEAD)["server_id"] == second["id"], (
        "the stale request changed nothing"
    )
    assert first["id"] != second["id"]


def test_a_slip_composed_against_an_older_showtime_reading_is_refused(api):
    """PRD §2.7: "Placing a seat-side order slip carries `expected_showtime_version`,
    which must equal the target showtime's current `version`; otherwise the
    placement is refused with `ERR_STALE_SHOWTIME_VERSION` (HTTP 412)."
    PRD §3.3: "it advances the parent showtime's `version` by one — which is why a
    caller who composed the slip against an older reading of the showtime is
    turned away with `ERR_STALE_SHOWTIME_VERSION`".

    Design: Corner/cross_cutting_layers/optimistic_concurrency_version_advances_on_every_section_reassignment
    """
    scenario = setup_dining_open_showtime(clock="2026-09-01T19:40:00Z")
    showtime, server, section = scenario["showtime"], scenario["server"], scenario["section"]
    item = make_menu_item("ENTREE", price_cents=900, prep_minutes=1, catalog_name="Slider")

    stale_version = read_showtime(showtime["id"], LEAD)["version"]
    # The intervening writer is another accepted slip, which bumps the version.
    get_success_data(api_client.create_order_slip(
        {"showtime_id": showtime["id"], "section_assignment_id": section["id"],
         "seat_number": 1, "lines": [{"menu_item_id": item["id"], "quantity": 1}],
         "expected_showtime_version": stale_version},
        server_headers(server),
    ))
    assert read_showtime(showtime["id"], LEAD)["version"] > stale_version

    refused = api_client.create_order_slip(
        {"showtime_id": showtime["id"], "section_assignment_id": section["id"],
         "seat_number": 2, "lines": [{"menu_item_id": item["id"], "quantity": 1}],
         "expected_showtime_version": stale_version},
        server_headers(server),
    )
    validate_error(refused, "ERR_STALE_SHOWTIME_VERSION")
    assert refused.status_code == 412


def test_a_stale_check_settlement_is_refused(api):
    """PRD §2.7: "Settling a check carries `expected_order_slip_version`, which
    must equal the `version` of the order slip the check settles; otherwise the
    settlement is refused with `ERR_STALE_ORDER_SLIP_VERSION` (HTTP 412)."
    PRD §2.7: "An automatic service-compensation refund legitimately bumps the
    slip's version while the tab is open, so a close composed against the stale,
    un-refunded view must be refused."

    Design: Corner/cross_cutting_layers/optimistic_concurrency_version_advances_on_every_section_reassignment
    """
    scenario = setup_dining_open_showtime(clock="2026-09-01T19:40:00Z")
    showtime, server, section = scenario["showtime"], scenario["server"], scenario["section"]
    item = make_menu_item("ENTREE", price_cents=1000, prep_minutes=1, catalog_name="Poutine")
    version = read_showtime(showtime["id"], LEAD)["version"]
    slip = get_success_data(api_client.create_order_slip(
        {"showtime_id": showtime["id"], "section_assignment_id": section["id"],
         "seat_number": 8, "lines": [{"menu_item_id": item["id"], "quantity": 1}],
         "expected_showtime_version": version},
        server_headers(server),
    ))
    stale_slip_version = slip["version"]
    check = _check_for(slip["id"])

    set_clock("2026-09-01T20:05:00Z")
    get_success_data(api_client.prepare_order_slip(slip["id"], server_headers(server)))
    assert read_slip(slip["id"], LEAD)["version"] > stale_slip_version, (
        "preparing the slip bumped its version while the tab stayed open"
    )

    refused = api_client.close_check(
        check["id"], {"expected_order_slip_version": stale_slip_version},
        server_headers(server),
    )
    validate_error(refused, "ERR_STALE_ORDER_SLIP_VERSION")
    assert refused.status_code == 412


# ─── Response envelope (PRD §2.2, §2.3) ───────────────────────────────

def test_the_success_envelope_has_the_same_shape_on_read_and_write(api):
    """PRD §2.2: "All successful API responses (those with 2xx status codes)
    follow this standard envelope format in their JSON body".
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/response_envelope/success_envelope_shape_is_stable_across_read_and_write
    """
    set_clock("2026-09-01T00:00:00Z")
    created = api_client.create_auditorium({"name": "Theater 32", "seat_capacity": 40}, ADMIN)
    body = created.json()
    assert created.status_code == 201
    assert body["response_type"] == "object"
    assert set(body) == {"meta", "response_type", "data"}, (
        "a success envelope carries exactly meta, response_type and data"
    )
    assert body["meta"]["api_request_id"].startswith("req_")
    assert body["meta"]["api_request_timestamp"]

    listed = api_client.list_auditoriums(ADMIN).json()
    assert listed["response_type"] == "array", (
        "the list form differs from the object form only in response_type"
    )
    assert "error_id" not in listed["data"] or isinstance(listed["data"], list)


def test_the_error_envelope_carries_only_the_two_declared_keys(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this standard
    envelope format" with `data` holding "error_id" and "message".
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    Design: Corner/response_envelope/error_envelope_shape_matches_the_declared_contract
    """
    set_clock("2026-09-01T00:00:00Z")
    refused = api_client.get_auditorium(NON_EXISTENT_UUID, ADMIN)
    validate_error(refused, "ERR_AUDITORIUM_NOT_FOUND")
    body = refused.json()
    assert refused.status_code == 404
    assert body["response_type"] == "error"
    assert set(body["data"]) == {"error_id", "message"}, (
        "an error payload carries no partial business fields such as name or seat_capacity"
    )
    assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}


def test_a_list_endpoint_applies_the_declared_pagination_defaults(api):
    """PRD §2.3: "`limit` defaults to 10, may not be smaller than 1 and may not
    exceed 100; `offset` defaults to 0."
    PRD §2.3: "Paginated list responses carry `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope".

    Design: Corner/entities/list_endpoints_apply_the_default_pagination_envelope
    """
    for name in ("Popcorn", "Root Beer", "Pale Ale"):
        api_client.create_menu_item(
            {"catalog_name": name, "channel": "ENTREE", "price_cents": 800,
             "prep_minutes": 1, "is_alcoholic": False}, ADMIN,
        )
    data, meta = validate_paginated(api_client.list_menu_items(ADMIN))
    assert len(data) == 3
    assert meta["limit"] == 10, "the declared default limit"
    assert meta["offset"] == 0
    assert meta["total_count"] == 3
    assert meta["has_more"] is False


# ─── Creation defaults and derived values ─────────────────────────────

def test_a_new_auditorium_carries_its_posture_axes_and_version_one(api):
    """PRD §3.1: "On creation the room is `DARK`, its `service_posture` mirror
    reads `DARK`, its `build_phase` is `EMPTY`, and its `version` is 1."
    PRD §2.6: "`version` is an integer that begins at 1".

    Design: Corner/entities/auditorium_create_supplies_posture_axes_and_version_one
    """
    set_clock("2026-09-01T00:00:00Z")
    created = validate_success(
        api_client.create_auditorium({"name": "Theater 1", "seat_capacity": 80}, ADMIN), 201
    )
    assert_auditorium(created)
    assert created["name"] == "Theater 1"
    assert created["seat_capacity"] == 80
    assert created["status"] == "DARK"
    assert created["service_posture"] == "DARK"
    assert created["build_phase"] == "EMPTY"
    assert created["screen_lead_time_minutes"] == 20
    assert created["kitchen_point_rate"] == 1
    assert created["alcove_point_rate"] == 3
    assert created["version"] == 1


def test_a_new_showtime_has_every_window_instant_derived(api):
    """PRD §2.12: "From the `start_at_utc` the caller provides and the parent
    auditorium's `screen_lead_time_minutes` (default twenty minutes, and
    constrained to lie between ten and forty minutes inclusive), the platform
    inherits `pre_show_minutes` and computes `dining_open_at_utc` as the feature
    start minus that pre-show length."
    PRD §2.12: "It computes `entree_ready_deadline_utc` as the feature start plus
    three-quarters of the `runtime_minutes`, truncated to a whole number of
    minutes — that is, the product is floored, not rounded."
    PRD §2.12: "It computes `dining_close_at_utc` as the entrée deadline minus
    `IN_KITCHEN_LEAD_MINUTES`, which is thirty minutes".

    Design: Corner/entities/showtime_create_ignores_client_supplied_derived_instants
    """
    set_clock("2026-09-01T19:00:00Z")
    auditorium = make_auditorium(name="Theater 4", screen_lead_time_minutes=20)
    # A 60-minute feature puts `dining_close_at_utc` (its deadline minus thirty
    # minutes) *before* its own `dining_open_at_utc`, which the window rule in
    # PRD §2.12 treats as an overlap with itself. The three instants are pinned
    # on a runtime long enough to be well formed; a 100-minute feature gives the
    # deadline 21:15 and a close at 21:05.
    showtime = validate_success(api_client.create_showtime(
        {"auditorium_id": auditorium["id"], "title": "Alien",
         "start_at_utc": "2026-09-01T20:00:00Z", "runtime_minutes": 100,
         "content_type": "STANDARD"},
        PROGRAMMER,
    ), 201)
    assert_showtime(showtime)
    assert showtime["pre_show_minutes"] == 20, "inherited from the parent auditorium"
    assert showtime["dining_open_at_utc"] == "2026-09-01T19:40:00Z"
    assert showtime["entree_ready_deadline_utc"] == "2026-09-01T21:15:00Z", (
        "the feature start plus floor(100 * 0.75) minutes"
    )
    assert showtime["dining_close_at_utc"] == "2026-09-01T20:45:00Z"
    assert showtime["status"] == "SCHEDULED"
    assert showtime["mode"] == "DINING_CLOSED"


def test_a_freshly_created_server_round_trips_with_no_ratings(api):
    """PRD §3.9: "A new server begins `ACTIVE` with `in_rotation` true, its
    `lifetime_points` at zero, and an empty `ratings` list."
    PRD §2.9: "The roster status of a server is one of `ACTIVE` or `PENALIZED`,
    and there is deliberately no third value".

    Design: Corner/entities/server_create_reads_back_with_empty_ratings_and_rotation_on
    """
    auditorium = make_auditorium(name="Theater 2")
    created = validate_success(api_client.create_server(
        {"display_name": "Ada", "home_auditorium_id": auditorium["id"]}, LEAD
    ), 201)
    fetched = validate_success(api_client.get_server(created["id"], ADMIN), 200)
    assert_server(fetched)
    assert fetched["display_name"] == "Ada"
    assert fetched["home_auditorium_id"] == auditorium["id"]
    assert fetched["ratings"] == []
    assert fetched["lifetime_points"] == 0
    assert fetched["status"] == "ACTIVE"
    assert fetched["in_rotation"] is True
    assert fetched["version"] == 1


def test_a_themed_menu_item_has_neither_a_version_nor_an_updated_at(api):
    """PRD §2.6: "A `ThemedMenuItem` and a `DisturbanceEvent` carry only `id` and
    `created_at`; neither has an `updated_at` field nor a `version` field."
    PRD §3.2: "Themed menu items are addressable and readable but are not revised
    after creation".

    Design: Corner/entities/themed_menu_item_is_immutable_and_has_no_version
    """
    auditorium = make_auditorium(name="Theater 6")
    item = make_menu_item("ENTREE", price_cents=900, prep_minutes=1, catalog_name="Meat Pie")
    event = make_programming_event(auditorium["id"], "Medieval Night", True)
    themed = make_themed_menu_item(event["id"], item["id"], 1100, is_signature=True)

    fetched = validate_success(api_client.get_themed_menu_item(themed["id"], ADMIN), 200)
    assert_themed_menu_item(fetched)
    assert fetched["id"] == themed["id"]
    assert fetched["theme_price_cents"] == 1100
    assert fetched["is_signature"] is True
    assert "updated_at" not in fetched, "a themed menu item carries no updated_at key"
    assert "version" not in fetched, "a themed menu item carries no version key"


def test_menu_availability_starts_available_and_has_one_writer(api):
    """PRD §3.1: "A new item begins `AVAILABLE`. Stopping an item is the
    counter-operation: an administrator sets `availability_state` on a catalogue
    item explicitly to `AVAILABLE` or to `OUT_OF_STOCK`".
    PRD §3.3: "Every referenced item must additionally be `AVAILABLE`; a line
    naming an `OUT_OF_STOCK` item fails the whole placement with
    `ERR_MENU_ITEM_UNAVAILABLE`."

    Design: Corner/entities/menu_item_availability_enum_starts_available_and_has_one_writer
    """
    set_clock("2026-09-01T00:00:00Z")
    created = validate_success(api_client.create_menu_item(
        {"catalog_name": "Bavarian Pretzel", "channel": "ENTREE", "price_cents": 950,
         "prep_minutes": 2, "is_alcoholic": False}, ADMIN,
    ), 201)
    assert created["availability_state"] == "AVAILABLE"
    assert_menu_item(created)

    stocked = validate_success(
        api_client.set_menu_item_stock(created["id"], "OUT_OF_STOCK", ADMIN), 200
    )
    assert stocked["availability_state"] == "OUT_OF_STOCK"
    assert validate_success(
        api_client.get_menu_item(created["id"], ADMIN), 200
    )["availability_state"] == "OUT_OF_STOCK"


def test_a_runtime_below_one_minute_cannot_derive_windows(api):
    """PRD §2.12: "A `runtime_minutes` below 1 cannot produce derivable windows at
    all and is rejected with `ERR_INVALID_SHOWTIME_RUNTIME` (HTTP 400)."

    Design: Corner/entities/showtime_create_rejects_runtime_below_one_minute
    """
    auditorium = make_auditorium(name="Theater 5")
    refused = api_client.create_showtime(
        {"auditorium_id": auditorium["id"], "title": "Zero",
         "start_at_utc": "2026-09-01T20:00:00Z", "runtime_minutes": 0,
         "content_type": "STANDARD"},
        PROGRAMMER,
    )
    validate_error(refused, "ERR_INVALID_SHOWTIME_RUNTIME")
    assert refused.status_code == 400


def test_reading_a_showtime_that_was_never_minted_is_a_not_found(api):
    """PRD §2.1: "A path identifier that matches nothing is reported as
    `ERR_AUDITORIUM_NOT_FOUND`, `ERR_SHOWTIME_NOT_FOUND`, `ERR_MENU_ITEM_NOT_FOUND`,
    `ERR_PROGRAMMING_EVENT_NOT_FOUND`, `ERR_THEMED_MENU_ITEM_NOT_FOUND`,
    `ERR_SERVER_NOT_FOUND`, `ERR_SECTION_ASSIGNMENT_NOT_FOUND`,
    `ERR_ORDER_SLIP_NOT_FOUND`, `ERR_CHECK_NOT_FOUND`, or
    `ERR_DISTURBANCE_EVENT_NOT_FOUND` according to the kind of resource named".

    Design: Corner/entities/get_missing_showtime_returns_not_found_error
    """
    make_auditorium(name="Theater 3")
    refused = api_client.get_showtime(NON_EXISTENT_UUID, ADMIN)
    validate_error(refused, "ERR_SHOWTIME_NOT_FOUND")
    assert refused.status_code == 404
    assert refused.json()["response_type"] == "error"


def _check_for(slip_id: str) -> dict:
    body = api_client.list_checks(LEAD, params={"id": slip_id}).json()
    assert body["data"], "the slip must have a check"
    return body["data"][0]