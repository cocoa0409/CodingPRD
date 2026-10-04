"""Remaining corner breadth: RBAC, windows, cascades, listing and read models."""
import pytest

from test_helpers import validate_success, validate_error, validate_paginated, ApiErrorId
from test_helpers.fixtures import (
    make_anonymous_headers,
    declare_patronization_record,
    declare_host,
    declare_sites,
    approve_host,
    setup_basic_scenario,
    setup_confirmed_stay,
    setup_checked_in_stay,
    file_stay,
    confirm_stay,
    decline_stay,
    read_host,
    read_member,
    read_stay,
    read_capacity_summary,
    resolve_site_id,
    host_version,
    conduct_injection,
    set_clock,
    make_host_operator_headers,
    make_member_headers,
    make_platform_admin_headers,
)


def test_lead_time_admits_an_arrival_exactly_at_the_guard(api):
    """PRD §3.4: "The logical clock must be at least 48 hours before the request's
    `occupancy_start`, unless the host has enabled same-day availability and the
    request carries `same_day_hold` as true, in which case the guard is waived
    entirely"
    PRD §3.4: "The `occupancy_start` is the arrival date plus the host's
    `arrival_window_start_hour`"

    Design: Corner/validations/lead_time_guard_boundary_at_exactly_forty_eight_hours
    """
    set_clock("2026-06-10T00:00:00Z")
    parts = setup_basic_scenario(site_count=2)
    host_id = parts["host"]["id"]
    member_id = parts["member"]["id"]
    vehicle_id = parts["vehicle"]["id"]

    # arrival 2026-06-12 with the default 14:00 start hour is exactly 48 hours out.
    exact = file_stay(host_id, member_id, vehicle_id,
                      arrival_date="2026-06-12", nights=1)
    assert exact["occupancy_start"].startswith("2026-06-12T14:00")

    resp = api.create_stay_request(
        {"host_id": host_id, "member_id": member_id, "vehicle_id": vehicle_id,
         "arrival_date": "2026-06-11", "nights": 1, "party_size": 1,
         "electric_request_code": "NONE", "request_depth": 0,
         "same_day_hold": False},
        make_member_headers(member_id),
    )
    validate_error(resp, ApiErrorId.ERR_REQUEST_LEAD_TIME, 422)


def test_a_same_day_hold_request_at_the_same_proximity_is_admitted(api):
    """PRD §3.4: "unless the host has enabled same-day availability and the request
    carries `same_day_hold` as true, in which case the guard is waived entirely"
    PRD §3.4: "`same_day_hold` marks the request as exempt from the lead-time guard
    when the host has enabled same-day availability and defaults to false"

    Design: Corner/validations/lead_time_guard_boundary_at_exactly_forty_eight_hours
    """
    set_clock("2026-06-10T00:00:00Z")
    parts = setup_basic_scenario(site_count=2)
    host_id = parts["host"]["id"]
    member_id = parts["member"]["id"]
    vehicle_id = parts["vehicle"]["id"]

    admitted = file_stay(host_id, member_id, vehicle_id,
                         arrival_date="2026-06-11", nights=1, same_day_hold=True)
    assert admitted["same_day_hold"] is True
    assert admitted["request_status"] == "REQUESTED"

    stays = validate_success(
        api.list_stay_requests(
            make_host_operator_headers(host_id),
            {"host_id": host_id, "limit": 50, "offset": 0},
        )
    )
    assert len(stays) == 1, "only the admitted request exists"


def test_the_state_gate_outranks_the_lead_time_guard_on_a_cancelled_request(api):
    """PRD §3.5: "A stay already at `CONFIRMED` may also be cancelled by its owning
    member, and that one carries consequences: the stay moves to `CANCELLED`, its
    `request_depth` advances by one"
    PRD §2.10: "State suitability is checked next, yielding `ERR_INVALID_STATE`
    (HTTP 409) whenever a target resource is not in a state that permits the
    requested operation."

    Design: Corner/validations/state_gate_outranks_lead_time_on_an_already_confirmed_request
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_confirmed_stay(site_count=1, arrival_date="2026-06-20", nights=2)
    host_id = parts["host"]["id"]
    member_id = parts["member"]["id"]

    # Move the clock to a few hours before the arrival window, then cancel.
    set_clock("2026-06-20T09:00:00Z")
    cancelled = validate_success(
        api.cancel_stay_request(parts["stay"]["id"], make_member_headers(member_id))
    )
    assert cancelled["request_status"] == "CANCELLED"
    assert cancelled["request_depth"] == 1
    assert cancelled["cancellation_fee_cents"] == 0, (
        "the ancillary charge was 0, under the 2000-cent tier bound"
    )

    resp = api.decide_stay_request(
        parts["stay"]["id"],
        {"decision": "CONFIRM", "site_id": resolve_site_id(host_id, "S1"),
         "expected_host_version": host_version(host_id)},
        make_host_operator_headers(host_id),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    after = read_stay(parts["stay"]["id"], host_id)
    assert after["request_status"] == "CANCELLED"
    assert after["request_depth"] == 1


def test_a_cancelled_or_superseded_window_is_never_consulted(api):
    """PRD §2.4: "Inactive sites are excluded from the base basis, and windows in
    `SCHEDULED` or `CANCELLED` status are never consulted."
    PRD §2.13: "a window that is no longer wanted — whether still `SCHEDULED` or
    already `ACTIVE` — is `CANCELLED`"

    Design: Corner/cross_cutting_layers/window_activation_cascade_gates_stay_requests_through_host_posture
    """
    set_clock("2026-06-25T00:00:00Z")
    host = declare_host(category="ATTRACTION", state_code="TX",
                        self_contained_required=False)
    declare_sites(host["id"], 4, labels=["K1", "K2", "K3", "K4"],
                  site_class="PULL_THROUGH", max_vehicle_length_feet=50)
    approve_host(host["id"])
    window = validate_success(
        api.create_window(
            {"host_id": host["id"], "kind": "EVENT", "label": "Rodeo Week",
             "start_date": "2026-07-01", "end_date": "2026-07-10",
             "capacity_override": 20, "reserved_sites": 20},
            make_host_operator_headers(host["id"]),
        ),
        201,
    )
    headers = make_host_operator_headers(host["id"])

    before = read_capacity_summary(host["id"])
    assert before["capacity_basis"] == "base"
    assert before["effective_capacity"] == 4
    assert before["posture"] == "OPEN"

    cancelled = validate_success(api.cancel_window(window["id"], headers))
    assert cancelled["window_status"] == "CANCELLED"
    after = read_capacity_summary(host["id"])
    assert after["capacity_basis"] == "base"
    assert after["effective_capacity"] == 4
    assert after["posture"] == "OPEN"


def test_a_request_is_gated_when_the_live_window_zeroes_the_capacity(api):
    """PRD §2.4: "Occupancy is tracked separately." / "`free_sites` is
    `effective_capacity` minus `committed_sites`, floored at zero — it is never
    negative."
    PRD §3.4: "A request that cannot be admitted is refused with
    `ERR_HOST_CAPACITY_FULL` (HTTP 409)."

    Design: Corner/cross_cutting_layers/window_activation_cascade_gates_stay_requests_through_host_posture
    """
    set_clock("2026-07-02T00:00:00Z")
    host = declare_host(category="ATTRACTION", state_code="TX",
                        self_contained_required=False)
    declare_sites(host["id"], 4, labels=["K1", "K2", "K3", "K4"],
                  site_class="PULL_THROUGH", max_vehicle_length_feet=50)
    approve_host(host["id"])
    window = validate_success(
        api.create_window(
            {"host_id": host["id"], "kind": "EVENT", "label": "Rodeo Week",
             "start_date": "2026-07-01", "end_date": "2026-07-10",
             "capacity_override": 20, "reserved_sites": 20},
            make_host_operator_headers(host["id"]),
        ),
        201,
    )
    assert window["window_status"] == "ACTIVE"
    live = read_capacity_summary(host["id"])
    assert live["capacity_basis"] == "live"
    assert live["active_window_member_ceiling"] == 0
    assert live["effective_capacity"] == 0
    assert live["posture"] == "UNAVAILABLE"


def test_an_onboarding_decision_carrying_a_stale_version_is_refused(api):
    """PRD §2.9: "A request that decides a stay must carry `expected_host_version`,
    the host's `version` as the caller last observed it"
    PRD §2.10: "finally the version preconditions (`ERR_STALE_HOST_VERSION`,
    `ERR_STALE_REQUEST_VERSION` and the window's `expected_window_version` check, the
    first two both HTTP 412)."

    Design: Corner/cross_cutting_layers/host_decision_with_stale_version_shadows_the_business_gate
    """
    host = declare_host()
    declare_sites(host["id"], 1, labels=["V1"])
    stale_version = host_version(host["id"])
    # A second declaration advances the host's version past the observation.
    declare_sites(host["id"], 1, labels=["V2"])

    resp = api.decide_host(
        host["id"],
        {"action": "APPROVE", "reason": "declared",
         "expected_host_version": stale_version},
        make_platform_admin_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_HOST_VERSION, 412)
    assert read_host(host["id"])["onboarding_status"] == "PENDING_REVIEW"

    fresh = validate_success(
        api.decide_host(
            host["id"],
            {"action": "APPROVE", "reason": "declared",
             "expected_host_version": host_version(host["id"])},
            make_platform_admin_headers(),
        )
    )
    assert fresh["onboarding_status"] == "APPROVED"


def test_a_stay_confirmable_carrying_a_superseded_host_version_is_refused(api):
    """PRD §2.9: "If the host's current `version` has advanced beyond that value, the
    decision is rejected with `ERR_STALE_HOST_VERSION` (HTTP 412) and no state change
    occurs."
    PRD §2.9: "The field is a required member of the request body for that operation,
    not an optional one."

    Design: Corner/cross_cutting_layers/stay_confirmation_with_stale_host_version_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_basic_scenario(site_count=2)
    host_id = parts["host"]["id"]
    stay = file_stay(host_id, parts["member"]["id"], parts["vehicle"]["id"],
                     arrival_date="2026-06-20", nights=2)
    stale_version = host_version(host_id)

    # Declaring a window advances the host's version after the read.
    validate_success(
        api.create_window(
            {"host_id": host_id, "kind": "EVENT", "label": "Later Window",
             "start_date": "2026-08-01", "end_date": "2026-08-10",
             "capacity_override": 6, "reserved_sites": 1},
            make_host_operator_headers(host_id),
        ),
        201,
    )

    resp = api.decide_stay_request(
        stay["id"],
        {"decision": "CONFIRM", "site_id": resolve_site_id(host_id, "S1"),
         "expected_host_version": stale_version},
        make_host_operator_headers(host_id),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_HOST_VERSION, 412)
    unchanged = read_stay(stay["id"], host_id)
    assert unchanged["request_status"] == "REQUESTED"
    assert unchanged["confirmed_site_id"] is None

    confirmed = confirm_stay(host_id, stay["id"], site_label="S1")
    assert confirmed["request_status"] == "CONFIRMED"


def test_a_second_receipt_reusing_the_observed_stay_version_is_refused(api):
    """PRD §2.9: "A request that files a patronization record must carry
    `expected_request_version`, the `version` of the stay the purchase is attached to
    as the caller last observed it."
    PRD §3.8: "The recording request must carry `expected_request_version` matching
    the stay's current `version`, exactly as described in §2.9, and the act of
    recording increments that stay's `version` by one."

    Design: Corner/cross_cutting_layers/patronization_capture_with_superseded_request_version_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_confirmed_stay(
        site_count=1, arrival_date="2026-06-20", nights=2,
        self_contained_required=True, category="WINERY", state_code="CA",
    )
    host_id = parts["host"]["id"]
    member_id = parts["member"]["id"]
    stay_id = parts["stay"]["id"]
    stale_version = read_stay(stay_id, host_id)["version"]
    host_headers = make_host_operator_headers(host_id)

    first = validate_success(
        api.create_patronization_record(
            {"host_id": host_id, "member_id": member_id,
             "stay_request_id": stay_id, "receipt_cents": 5000,
             "purchase_kind": "TASTING",
             "expected_request_version": stale_version},
            host_headers,
        ),
        201,
    )
    assert first["verification_status"] == "PENDING"

    second = api.create_patronization_record(
        {"host_id": host_id, "member_id": member_id, "stay_request_id": stay_id,
         "receipt_cents": 6000, "purchase_kind": "MEAL",
         "expected_request_version": stale_version},
        host_headers,
    )
    validate_error(second, ApiErrorId.ERR_STALE_REQUEST_VERSION, 412)

    data, meta = validate_paginated(
        api.list_patronization_records(
            host_headers, {"stay_request_id": stay_id, "limit": 20, "offset": 0}
        )
    )
    assert meta["total_count"] == 1, "the refused call wrote nothing"
    assert data[0]["id"] == first["id"]


def test_host_operator_scope_refuses_a_rival_operators_window_write(api):
    """PRD §2.1: "When `X-User-Role` is `HostOperator`, `X-User-ID` is the `id` of
    the acting `HostBusiness`; every host-scoped operation — declaring or amending
    sites, opening and amending availability windows, deciding, checking in and
    checking out stays, recording no-shows, verifying patronization receipts, and
    writing the host side of a review — compares the target host against `X-User-ID`."

    Design: Corner/rbac/host_operator_cannot_operate_on_another_hosts_stay_window
    """
    set_clock("2026-10-05T00:00:00Z")
    owner = declare_host()
    declare_sites(owner["id"], 1, labels=["W1"])
    approve_host(owner["id"])
    rival = declare_host()

    window = validate_success(
        api.create_window(
            {"host_id": owner["id"], "kind": "EVENT", "label": "Owner Festival",
             "start_date": "2026-10-01", "end_date": "2026-10-20",
             "capacity_override": 12, "reserved_sites": 10},
            make_host_operator_headers(owner["id"]),
        ),
        201,
    )

    validate_error(
        api.amend_window(
            window["id"],
            {"capacity_override": 4, "expected_window_version": window["version"]},
            make_host_operator_headers(rival["id"]),
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api.cancel_window(window["id"], make_host_operator_headers(rival["id"])),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )

    amended = validate_success(
        api.amend_window(
            window["id"],
            {"capacity_override": 22, "expected_window_version": window["version"]},
            make_host_operator_headers(owner["id"]),
        )
    )
    assert amended["window_status"] == "ACTIVE"
    assert amended["member_capacity_ceiling"] == 12


def test_the_confirm_and_counter_operations_are_role_exclusive(api):
    """PRD §2.1: "Acting outside the granted role — including a `Member` attempting an
    operation reserved to host staff or to platform staff — is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/member_cannot_decide_a_stay_and_host_cannot_counter_request
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_basic_scenario(site_count=1)
    host_id = parts["host"]["id"]
    member_id = parts["member"]["id"]
    stay = file_stay(host_id, member_id, parts["vehicle"]["id"],
                     arrival_date="2026-06-20", nights=2)

    validate_error(
        api.decide_stay_request(
            stay["id"],
            {"decision": "CONFIRM", "site_id": resolve_site_id(host_id, "S1"),
             "expected_host_version": host_version(host_id)},
            make_member_headers(member_id),
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api.counter_stay_request(
            stay["id"],
            {"arrival_date": "2026-06-22", "nights": 2, "party_size": 1},
            make_host_operator_headers(host_id),
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    after = read_stay(stay["id"], host_id)
    assert after["request_status"] == "REQUESTED"
    assert after["ancillary_charge_cents"] == 0


def test_an_unknown_role_is_refused_before_the_resource_is_looked_up(api):
    """PRD §2.1: "A request that omits either header, or that names a role the
    platform does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.10: "Authentication comes first: a caller with a missing or unrecognized
    role is told `ERR_UNAUTHENTICATED` (HTTP 401) before anything about their payload
    is examined."

    Design: Corner/rbac/missing_headers_and_unknown_role_are_refused_before_resource_lookup
    """
    from test_helpers.test_users import UNKNOWN_ROLE_HEADERS

    host = declare_host()
    validate_error(
        api.get_host(host["id"], UNKNOWN_ROLE_HEADERS),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )

    from prd_bench_local_runner.testing import NON_EXISTENT_UUID

    validate_error(
        api.get_host(NON_EXISTENT_UUID, UNKNOWN_ROLE_HEADERS),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )
    validate_error(
        api.list_members(make_member_headers("3f1a2b4c-0000-4000-8000-000000000011")),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    assert read_host(host["id"])["id"] == host["id"]


def test_the_disposition_display_name_must_be_segmented_from_other_members(api):
    """PRD §3.7: "The `decided_by_display_name` supplied in the body must be segmented
    from every other member's `full_name` on the platform — it may not coincide with
    any other member's display name — and a collision is refused with
    `ERR_DISPOSITION_NAME_COLLISION` (HTTP 409)."

    Design: Corner/rbac/segregation_of_duty_between_deciding_and_being_decided
    """
    set_clock("2026-06-01T00:00:00Z")
    decider = validate_success(
        api.register_member(
            {"email": "seg1@example.com", "full_name": "Seg One",
             "plan_tier": "PLUS", "home_state_code": "TX"},
            make_anonymous_headers(),
        ),
        201,
    )
    subject = validate_success(
        api.register_member(
            {"email": "seg2@example.com", "full_name": "Seg Two",
             "plan_tier": "PLUS", "home_state_code": "TX"},
            make_anonymous_headers(),
        ),
        201,
    )
    for m in (decider, subject):
        validate_success(
            api.member_subscription_action(
                m["id"], {"action": "ACTIVATE"}, make_platform_admin_headers()
            )
        )

    # PRD §3.7: `host_id` names the HostBusiness that reported or was affected,
    # so the incident must reference a real host rather than the member's id.
    host = declare_host(category="FARM", state_code="TX",
                        self_contained_required=False)

    incident = validate_success(
        api.create_incident(
            {"member_id": subject["id"], "host_id": host["id"],
             "severity": "MAJOR", "narrative": "left a mess",
             "origin": "MEMBER_REPORT"},
            make_member_headers(decider["id"]),
        ),
        201,
    )

    validate_error(
        api.create_disposition(
            incident["id"],
            {"action": "DISMISS", "decided_by_display_name": "Seg Two"},
            make_member_headers(decider["id"]),
        ),
        ApiErrorId.ERR_DISPOSITION_NAME_COLLISION,
        409,
    )
    after = api.get_incident(incident["id"], make_platform_admin_headers()).json()[
        "data"
    ]
    assert after["incident_status"] == "OPEN"
    assert read_member(subject["id"])["strike_count"] == 1


def test_the_host_list_honours_limit_offset_total_count_and_has_more(api):
    """PRD §2.3: "List endpoints are paginated through query parameters. `limit` caps
    how many items a single response returns; when the caller omits it the value
    defaults to 10"
    PRD §2.3: "Responses for list endpoints carry `limit`, `offset`, `total_count` and
    `has_more` in the `meta` object of the envelope"

    Design: Corner/endpoints/host_list_pagination_contract_on_an_empty_and_a_populated_page
    """
    hosts = [declare_host(category=c) for c in ("FARM", "WINERY", "BREWERY")]

    page1, meta1 = validate_paginated(
        api.list_hosts(make_platform_admin_headers(), {"limit": 2, "offset": 0})
    )
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert len(page1) == 2

    page2, meta2 = validate_paginated(
        api.list_hosts(make_platform_admin_headers(), {"limit": 2, "offset": 2})
    )
    assert meta2["has_more"] is False
    assert len(page2) == 1

    ids = {h["id"] for h in hosts}
    assert {page1[0]["id"], page1[1]["id"], page2[0]["id"]} == ids


def test_a_filter_that_matches_nothing_returns_an_empty_array(api):
    """PRD §3.9: "Listing operations carry optional filters rather than requiring
    callers to walk the whole set."
    PRD §2.3: "Responses for list endpoints carry `limit`, `offset`, `total_count` and
    `has_more` in the `meta` object of the envelope"

    Design: Corner/endpoints/host_list_pagination_contract_on_an_empty_and_a_populated_page
    """
    host = declare_host(category="BREWERY", state_code="CA")
    data, meta = validate_paginated(
        api.list_hosts(make_platform_admin_headers(),
                       {"category": "FARM", "limit": 10, "offset": 0})
    )
    assert data == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False

    farm = declare_host(category="FARM")
    data2, meta2 = validate_paginated(
        api.list_hosts(make_platform_admin_headers(),
                       {"category": "FARM", "limit": 10, "offset": 0})
    )
    assert meta2["total_count"] == 1
    assert data2[0]["id"] == farm["id"]
    assert data2[0]["id"] != host["id"]


def test_the_capacity_read_agrees_with_the_hosts_own_counters(api):
    """PRD §3.9: "A host's live capacity read reports which basis is currently in
    force through `capacity_basis`, the physical active-site count as `base_capacity`"
    PRD §2.4: "`latest_checkout_at` is the latest `occupancy_end` among the host's
    stays whose status is `CONFIRMED` or `CHECKED_IN`, and is null when the host has
    no such stay"

    Design: Corner/endpoints/capacity_summary_computed_read_matches_its_underlying_counters
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_basic_scenario(site_count=4)
    host_id = parts["host"]["id"]
    file_stay(host_id, parts["member"]["id"], parts["vehicle"]["id"],
              arrival_date="2026-06-20", nights=3)

    summary = read_capacity_summary(host_id)
    assert summary["capacity_basis"] == "base"
    assert summary["base_capacity"] == 4
    assert summary["effective_capacity"] == 4
    assert summary["committed_sites_reserved_basis"] == 1
    assert summary["committed_sites_occupied_basis"] == 0
    assert summary["free_sites"] == 3
    assert summary["posture"] == "OPEN", "3 free of 4 exceeds ceil(4 * 0.20) = 1"
    assert summary["latest_checkout_at"] is None, "no stay has been confirmed yet"
    assert read_host(host_id)["committed_sites"] == summary[
        "committed_sites_reserved_basis"
    ]


def test_the_stay_collection_filters_on_its_foreign_keys(api):
    """PRD §3.9: "stay requests filter on `host_id`, `member_id`, `vehicle_id`,
    `confirmed_site_id`, `request_status` and a `from_date`"

    Design: Corner/endpoints/stay_list_filters_by_vehicle_and_by_assigned_site
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_basic_scenario(site_count=2, labels=["Q1", "Q2"])
    host_id = parts["host"]["id"]
    member_id = parts["member"]["id"]
    host_headers = make_host_operator_headers(host_id)

    second_vehicle = validate_success(
        api.create_vehicle(
            member_id,
            {"vehicle_class": "TRAVEL_TRAILER", "length_feet": 24,
             "self_contained": True, "inspection_state_code": "TX"},
            make_member_headers(member_id),
        ),
        201,
    )
    site_q1 = resolve_site_id(host_id, "Q1")
    stay_a = file_stay(host_id, member_id, parts["vehicle"]["id"],
                       arrival_date="2026-06-20", nights=2)
    stay_b = file_stay(host_id, member_id, second_vehicle["id"],
                       arrival_date="2026-06-20", nights=2)
    confirm_stay(host_id, stay_a["id"], site_id=site_q1)
    decline_stay(host_id, stay_b["id"])

    by_vehicle, meta_v = validate_paginated(
        api.list_stay_requests(host_headers,
                               {"vehicle_id": parts["vehicle"]["id"],
                                "limit": 50, "offset": 0})
    )
    assert meta_v["total_count"] == 1
    assert by_vehicle[0]["id"] == stay_a["id"]

    by_status, meta_s = validate_paginated(
        api.list_stay_requests(host_headers,
                               {"host_id": host_id, "request_status": "DECLINED",
                                "limit": 50, "offset": 0})
    )
    assert meta_s["total_count"] == 1
    assert by_status[0]["id"] == stay_b["id"]

    by_site, meta_site = validate_paginated(
        api.list_stay_requests(host_headers,
                               {"confirmed_site_id": site_q1, "limit": 50,
                                "offset": 0})
    )
    assert meta_site["total_count"] == 1
    assert by_site[0]["id"] == stay_a["id"]


def test_a_site_declaration_needs_a_resolvable_parent_host(api):
    """PRD §2.10: "When a request targets an inner resource inside an outer one — an
    availability window inside a host, a parking site inside a host, the dispositions
    recorded against an incident — the outer identifier is resolved and validated
    before the inner one is even looked at."
    PRD §2.10: "Every unresolvable path or body identifier produces
    `ERR_RESOURCE_NOT_FOUND` (HTTP 404)."

    Design: Corner/entity_topology/site_creation_requires_a_resolvable_host
    """
    from prd_bench_local_runner.testing import NON_EXISTENT_UUID

    host = declare_host()
    validate_error(
        api.create_parking_site(
            NON_EXISTENT_UUID,
            {"site_label": "Z1", "site_class": "BACK_IN",
             "max_vehicle_length_feet": 40, "has_electric": False,
             "electric_service_code": "NONE"},
            make_host_operator_headers(host["id"]),
        ),
        ApiErrorId.ERR_RESOURCE_NOT_FOUND,
        404,
    )

    site = validate_success(
        api.create_parking_site(
            host["id"],
            {"site_label": "Z1", "site_class": "BACK_IN",
             "max_vehicle_length_feet": 40, "has_electric": False,
             "electric_service_code": "NONE"},
            make_host_operator_headers(host["id"]),
        ),
        201,
    )
    assert site["host_id"] == host["id"]

    listed = validate_success(
        api.list_parking_sites(host["id"], make_host_operator_headers(host["id"]),
                               {"limit": 10, "offset": 0})
    )
    assert len(listed) == 1
    assert listed[0]["id"] == site["id"]


def test_a_stay_row_resolves_four_peer_references_and_a_child(api):
    """PRD §2.1: "When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the
    acting `Member`; ownership checks on any resource that references a `Member`
    compare that resource's member foreign-key field to `X-User-ID`"
    PRD §3.8: "During a stay, a member records a purchase at the host with a
    patronization record naming the host, the member, the `stay_request_id` of the stay
    during which the purchase was made"

    Design: Corner/entity_topology/stay_request_references_span_four_peer_entities
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_confirmed_stay(site_count=1, arrival_date="2026-06-20", nights=2)
    host_id = parts["host"]["id"]
    member_id = parts["member"]["id"]
    vehicle_id = parts["vehicle"]["id"]
    stay_id = parts["stay"]["id"]
    host_headers = make_host_operator_headers(host_id)

    stay = read_stay(stay_id, host_id)
    assert stay["host_id"] == host_id
    assert stay["member_id"] == member_id
    assert stay["vehicle_id"] == vehicle_id
    assert stay["confirmed_site_id"] is not None

    record = declare_patronization_record(host_id, member_id, stay_id,
                                          receipt_cents=3000)
    assert record["stay_request_id"] == stay_id

    data, meta = validate_paginated(
        api.list_patronization_records(
            host_headers, {"stay_request_id": stay_id, "limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 1
    assert data[0]["id"] == record["id"]


def test_counters_reconcile_on_the_very_next_read_after_a_checkout(api):
    """PRD §2.5: "Recomputation counts as mutation. Whenever a rule in this document
    recomputes a derived field on a resource — capacity, posture, a rating average, a
    standing score, a guest-pass pool — that write refreshes the resource's
    `updated_at` and increments its `version`."
    PRD §3.5: "the member's `guest_passes_remaining` pool is recalculated on departure
    only if the member has no other in-flight stay in `REQUESTED`, `CONFIRMED` or
    `CHECKED_IN` status"

    Design: Corner/consistency_model/derived_counters_reconcile_immediately_after_each_mutation
    """
    set_clock("2026-06-05T00:00:00Z")
    parts = setup_checked_in_stay(arrival_date="2026-06-05", nights=1,
                                  party_size=2, plan_tier="PLUS")
    host_id = parts["host"]["id"]
    member_id = parts["member"]["id"]
    host_headers = make_host_operator_headers(host_id)

    in_progress, meta_in = validate_paginated(
        api.list_stay_requests(host_headers,
                               {"host_id": host_id, "request_status": "CHECKED_IN",
                                "limit": 10, "offset": 0})
    )
    assert meta_in["total_count"] == 1
    assert in_progress[0]["id"] == parts["stay"]["id"]

    set_clock("2026-06-06T11:00:00Z")
    out = validate_success(api.check_out_stay(parts["stay"]["id"], host_headers))
    assert out["request_status"] == "CHECKED_OUT"
    assert out["checked_out_at"] is not None

    member = read_member(member_id)
    assert member["total_stays_completed"] == 1, (
        "the counter reconciles on the very next read, with no refresh call between"
    )
    assert member["guest_passes_remaining"] == 1, (
        "recomputed from the PLUS allotment of 2 minus the guest usage of this "
        "calendar year: the party of 2 was one guest beyond the driver, so 2 - 1 = 1"
    )

    completed, meta_out = validate_paginated(
        api.list_stay_requests(host_headers,
                               {"host_id": host_id, "request_status": "CHECKED_OUT",
                                "limit": 10, "offset": 0})
    )
    assert meta_out["total_count"] == 1
    assert completed[0]["id"] == parts["stay"]["id"]