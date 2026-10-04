"""Entity shape: declared defaults, derived counters, and creation rejection."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    is_iso8601_timestamp,
)
from test_helpers.fixtures import (
    declare_host,
    declare_sites,
    approve_host,
    setup_basic_scenario,
    read_host,
    read_capacity_summary,
    make_host_operator_headers,
    make_anonymous_headers,
    make_member_headers,
    make_platform_admin_headers,
)
from test_helpers.factories import create_host_payload, create_member_payload


def test_a_host_declared_without_its_optional_fields_takes_the_documented_defaults(api):
    """PRD §3.1: "Three declarations may be supplied at the same time and each has a
    fixed default when it is left out: `arrival_window_start_hour` defaults to 14, the
    local hour on the arrival day at which a member may occupy a site;
    `arrival_window_end_hour` defaults to 11, the local hour by which a rig must be
    gone on the final morning; and `self_contained_required` defaults to true"
    PRD §3.1: "A freshly declared host sits at `onboarding_status` `PENDING_REVIEW`
    with `posture` `UNAVAILABLE`, `effective_capacity` 0, `committed_sites` 0,
    `free_sites` 0, `patronization_credit_cents` 0 and `latest_checkout_at` null."

    Design: Corner/entities/host_creation_applies_declared_defaults_and_derived_zeros
    """
    resp = api.create_host(
        create_host_payload(legal_name="Default Farm", category="FARM",
                            state_code="TX"),
        make_host_operator_headers("bootstrap-host"),
    )
    host = validate_success(resp, 201)
    assert host["self_contained_required"] is True
    assert host["arrival_window_start_hour"] == 14
    assert host["arrival_window_end_hour"] == 11
    assert host["onboarding_status"] == "PENDING_REVIEW"
    assert host["posture"] == "UNAVAILABLE"
    assert host["effective_capacity"] == 0
    assert host["committed_sites"] == 0
    assert host["free_sites"] == 0
    assert host["electric_site_count"] == 0
    assert host["patronization_credit_cents"] == 0
    assert host["latest_checkout_at"] is None

    reread = read_host(host["id"])
    assert reread["version"] == 1
    assert is_iso8601_timestamp(reread["created_at"])


@pytest.mark.parametrize(
    "payload,reason",
    [
        ({"email": "bad1@example.com", "full_name": "Bad One",
          "plan_tier": "CLASSIC"}, "absent home_state_code"),
        ({"email": "bad2@example.com", "full_name": "Bad Two",
          "plan_tier": "ELITE", "home_state_code": "TX"},
         "plan_tier outside {CLASSIC, PLUS, PREMIER}"),
    ],
)
def test_member_registration_rejects_a_malformed_payload(api, payload, reason):
    """PRD §2.10: "Payload well-formedness is fourth: every required input must be
    present, every enumerated value must fall inside its declared set, and every
    numeric range must hold, or the request fails with `ERR_INVALID_REQUEST`
    (HTTP 400)."

    Design: Corner/entities/member_creation_rejects_missing_required_and_bad_enum
    """
    resp = api.register_member(payload, make_anonymous_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_a_rejected_member_payload_creates_no_row(api):
    """PRD §2.10: "Payload well-formedness is fourth: every required input must be
    present, every enumerated value must fall inside its declared set, and every
    numeric range must hold, or the request fails with `ERR_INVALID_REQUEST`
    (HTTP 400)."
    PRD §3.3: "a `CLASSIC` member receives no overnight guest passes at all"

    Design: Corner/entities/member_creation_rejects_missing_required_and_bad_enum
    """
    ok = validate_success(
        api.register_member(create_member_payload(plan_tier="CLASSIC"),
                            make_anonymous_headers()),
        201,
    )
    assert ok["guest_passes_remaining"] == 0, "the CLASSIC allotment"

    for bad in (
        {"email": "nope1@example.com", "full_name": "Nope One",
         "plan_tier": "CLASSIC"},
        {"email": "nope2@example.com", "full_name": "Nope Two",
         "plan_tier": "ELITE", "home_state_code": "TX"},
    ):
        validate_error(
            api.register_member(bad, make_anonymous_headers()),
            ApiErrorId.ERR_INVALID_REQUEST,
            400,
        )

    data, meta = validate_paginated(
        api.list_members(make_platform_admin_headers(), {"limit": 50, "offset": 0})
    )
    assert meta["total_count"] == 1, "neither rejected payload created a row"
    assert data[0]["id"] == ok["id"]


def test_site_labels_are_unique_within_a_host_but_not_across_hosts(api):
    """PRD §3.1: "A host staff member declares each physical `HostParkingSite` with a
    `site_label` that is unique within the host"
    PRD §3.1: "A site label that already exists on the host is refused with
    `ERR_DUPLICATE_SITE_LABEL` (HTTP 409)."

    Design: Corner/entities/duplicate_site_label_and_duplicate_member_email_rejected
    """
    first = declare_host()
    second = declare_host()
    site = declare_sites(first["id"], 1, labels=["LOT-A"],
                         site_class="BACK_IN", max_vehicle_length_feet=40)[0]

    resp = api.create_parking_site(
        first["id"],
        {"site_label": "LOT-A", "site_class": "PULL_THROUGH",
         "max_vehicle_length_feet": 50, "has_electric": True,
         "electric_service_code": "ELECTRIC_30A"},
        make_host_operator_headers(first["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SITE_LABEL, 409)

    # The same label is accepted on a different host.
    other = validate_success(
        api.create_parking_site(
            second["id"],
            {"site_label": "LOT-A", "site_class": "BACK_IN",
             "max_vehicle_length_feet": 40, "has_electric": False,
             "electric_service_code": "NONE"},
            make_host_operator_headers(second["id"]),
        ),
        201,
    )
    assert other["host_id"] == second["id"]

    original = validate_success(
        api.list_parking_sites(first["id"], make_host_operator_headers(first["id"]))
    )
    assert original[0]["site_class"] == "BACK_IN", (
        "the refused update did not partially apply"
    )
    assert original[0]["max_vehicle_length_feet"] == 40
    assert original[0]["id"] == site["id"]


def test_member_emails_are_unique_globally(api):
    """PRD §3.3: "An email already on file is refused with
    `ERR_MEMBER_EMAIL_DUPLICATE` (HTTP 409)."

    Design: Corner/entities/duplicate_site_label_and_duplicate_member_email_rejected
    """
    first = validate_success(
        api.register_member(create_member_payload(email="dup@example.com"),
                            make_anonymous_headers()),
        201,
    )
    resp = api.register_member(
        {"email": "dup@example.com", "full_name": "Another Person",
         "plan_tier": "PLUS", "home_state_code": "CA"},
        make_anonymous_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_MEMBER_EMAIL_DUPLICATE, 409)
    assert first["email"] == "dup@example.com"


def test_unresolvable_path_ids_report_not_found(api):
    """PRD §2.10: "Every unresolvable path or body identifier produces
    `ERR_RESOURCE_NOT_FOUND` (HTTP 404)."
    PRD §2.10: "the outer identifier is resolved and validated before the inner one is
    even looked at"

    Design: Corner/entities/missing_host_and_missing_stay_return_not_found_left_to_right
    """
    host = declare_host()
    from prd_bench_local_runner.testing import NON_EXISTENT_UUID

    validate_error(
        api.get_host(NON_EXISTENT_UUID, make_host_operator_headers(host["id"])),
        ApiErrorId.ERR_RESOURCE_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_stay_request(NON_EXISTENT_UUID,
                             make_host_operator_headers(host["id"])),
        ApiErrorId.ERR_RESOURCE_NOT_FOUND,
        404,
    )
    assert read_host(host["id"])["legal_name"] == host["legal_name"]


def test_capacity_and_amenity_counters_track_the_declared_site_rows(api):
    """PRD §2.4: "When no availability window of the host is in `ACTIVE` status,
    capacity runs on the **base basis**: `effective_capacity` equals the number of
    that host's parking sites whose `is_active` flag is true."
    PRD §2.4: "`electric_site_count` is the number of parking sites belonging to the
    host that are both active and carry an electric pedestal."

    Design: Corner/entities/host_capacity_and_posture_are_recomputed_from_declared_sites
    """
    host = declare_host()
    assert host["effective_capacity"] == 0

    declare_sites(host["id"], 1, labels=["G1"], has_electric=True,
                  electric_service_code="ELECTRIC_30A")
    declare_sites(host["id"], 1, labels=["G2"], has_electric=False)
    two = read_capacity_summary(host["id"])
    assert two["base_capacity"] == 2

    declare_sites(host["id"], 1, labels=["G3"], has_electric=True,
                  electric_service_code="ELECTRIC_50A")
    refreshed = read_host(host["id"])
    assert refreshed["effective_capacity"] == 3
    assert refreshed["electric_site_count"] == 2
    assert refreshed["posture"] == "OPEN", (
        "3 free sites of 3 exceed ceil(3 * 0.20) = 1"
    )


def test_a_new_member_starts_pending_and_full_scored(api):
    """PRD §3.3: "A newly registered member opens at `subscription_status` `PENDING`
    with `standing_score` 100, `strike_count` 0, `removal_status` `NONE`,
    `total_stays_completed` 0, and a `guest_passes_remaining` pool set from their
    plan's yearly allotment."
    PRD §3.3: "a `PLUS` member receives 2"

    Design: Corner/entities/member_subscription_starts_pending_and_stays_field_inmutable
    """
    member = validate_success(
        api.register_member(create_member_payload(plan_tier="PLUS"),
                            make_anonymous_headers()),
        201,
    )
    assert member["subscription_status"] == "PENDING"
    assert member["standing_score"] == 100
    assert member["strike_count"] == 0
    assert member["removal_status"] == "NONE"
    assert member["total_stays_completed"] == 0
    assert member["guest_passes_remaining"] == 2


def test_a_pending_member_cannot_open_a_stay(api):
    """PRD §3.3: "a member must have `subscription_status` `ACTIVE` and must not have
    `removal_status` `REMOVED`, and a member failing either test is refused with
    `ERR_MEMBER_NOT_ELIGIBLE` (HTTP 403) when they try to open or re-open a stay."

    Design: Corner/entities/member_subscription_starts_pending_and_stays_field_inmutable
    """
    host = declare_host()
    declare_sites(host["id"], 1, labels=["P1"])
    approve_host(host["id"])

    member = validate_success(
        api.register_member(create_member_payload(plan_tier="PLUS"),
                            make_anonymous_headers()),
        201,
    )
    vehicle = validate_success(
        api.create_vehicle(
            member["id"],
            {"vehicle_class": "CLASS_C", "length_feet": 30, "self_contained": True,
             "inspection_state_code": "TX"},
            make_member_headers(member["id"]),
        ),
        201,
    )
    resp = api.create_stay_request(
        {"host_id": host["id"], "member_id": member["id"], "vehicle_id": vehicle["id"],
         "arrival_date": "2026-09-20", "nights": 2, "party_size": 1,
         "electric_request_code": "NONE", "request_depth": 0, "same_day_hold": False},
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_ELIGIBLE, 403)