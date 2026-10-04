"""Corner queue B — section: errors.

Read-only role refusal, missing identity header, per-hub code uniqueness and the
payment-required budget ceiling.
"""
import pytest

from test_helpers import (
    api,
    create_hub,
    create_hub_with_clock,
    create_site,
    create_region,
    create_market,
    create_route,
    create_edition,
    get_success_data,
    record_print_volume,
    validate_error,
    validate_success,
    NON_EXISTENT_UUID,
    TEST_USERS,
)
from test_helpers.constants import CLOCK_2026_09_01, CLOCK_2026_09_30

ADMIN = TEST_USERS["platform_admin_headers"]
PRINT_OPS = TEST_USERS["print_ops_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_the_read_only_auditor_cannot_write_a_print_site():
    """PRD §2.1: "A request that presents a valid identity but attempts an operation
    that role does not hold is refused with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "`Auditor` is read-only across every GET surface, including the hub
    compliance read."

    Design: Corner/errors/printer_receives_unauthorized_on_dml
    """
    hub = create_hub_with_clock(CLOCK_2026_09_01)

    response = api.create_print_site(
        hub["id"],
        {
            "code": "KOT",
            "press_units": 2,
            "shifts_per_night": 2,
            "copies_per_hour_per_press": 25000,
            "max_concurrent_departures": 2,
            "allocation_method": "PRIORITY",
        },
        AUDITOR,
    )

    error = validate_error(response, "ERR_UNAUTHORIZED")
    assert response.status_code == 403
    assert error["error_id"] == "ERR_UNAUTHORIZED"

    sites = validate_success(api.list_print_sites(hub["id"], PRINT_OPS), 200)
    assert sites == [], "the refused write must not create a site"


def test_call_without_role_header_returns_unauthenticated():
    """PRD §2.1: "A request whose headers are absent, whose `X-User-Role` names no
    such role, or whose `X-User-ID` does not resolve for an entity-backed role is
    refused with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.11: "Identity precedes authorization, so a missing header reports
    `ERR_UNAUTHENTICATED` (HTTP 401) rather than `ERR_UNAUTHORIZED`."

    Design: Corner/errors/call_without_role_header_returns_unauthenticated
    """
    hub = create_hub_with_clock(CLOCK_2026_09_01)

    response = api.create_region(
        hub["id"],
        {"name": "North", "daily_headcount_floor": 4,
         "daily_headcount_cap": 10, "allocation_priority": 1},
        {},
    )

    body = response.json()
    assert response.status_code == 401, (
        f"a missing identity reports 401, got {response.status_code}"
    )
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_UNAUTHENTICATED"
    assert body["data"]["error_id"] != "ERR_UNAUTHORIZED", (
        "the two identity failures must be distinguishable"
    )

    no_role = api.create_region(
        hub["id"],
        {"name": "North", "daily_headcount_floor": 4,
         "daily_headcount_cap": 10, "allocation_priority": 1},
        {"X-User-ID": "opaque-9", "Content-Type": "application/json"},
    )
    assert no_role.status_code == 401
    assert no_role.json()["data"]["error_id"] == "ERR_UNAUTHENTICATED"


def test_reusing_a_hub_code_returns_duplicate_hub_code():
    """PRD §2.12: "Names and codes are scoped to their container, and the API refuses
    reuse within that scope."
    PRD §2.12: "Any reuse is refused with `ERR_DUPLICATE_HUB_CODE` (HTTP 409), and
    a missing or empty required name or code is refused as `ERR_INVALID_REQUEST`
    (HTTP 400) before the uniqueness check is reached."
    PRD §2.12: "a `PrintSite`'s `code` must be unique within its hub".

    Design: Corner/errors/reusing_a_hub_code_returns_duplicate_hub_code
    """
    api.set_current_utc({"current_utc": CLOCK_2026_09_01}, ADMIN)
    hub = create_hub()
    other_hub = create_hub(name="South Ridge Media Group")
    create_site(hub["id"], code="KOT")

    duplicate = api.create_print_site(
        hub["id"],
        {
            "code": "KOT",
            "press_units": 1,
            "shifts_per_night": 2,
            "copies_per_hour_per_press": 25000,
            "max_concurrent_departures": 2,
            "allocation_method": "PRIORITY",
        },
        PRINT_OPS,
    )

    error = validate_error(duplicate, "ERR_DUPLICATE_HUB_CODE")
    assert duplicate.status_code == 409
    assert error["error_id"] == "ERR_DUPLICATE_HUB_CODE"

    elsewhere = api.create_print_site(
        other_hub["id"],
        {
            "code": "KOT",
            "press_units": 1,
            "shifts_per_night": 2,
            "copies_per_hour_per_press": 25000,
            "max_concurrent_departures": 2,
            "allocation_method": "PRIORITY",
        },
        PRINT_OPS,
    )
    assert elsewhere.status_code == 201, (
        "the identical code in a different hub is accepted"
    )


def test_print_budget_exceeded_is_a_402_condition():
    """PRD §3.5: "a run that would push the hub's aggregate print tonnage charge for
    the period past `max_print_tonnage_budget_cents` — counting partial-period
    consumption, never annualizing it — is refused with `ERR_PRINT_BUDGET_EXCEEDED`
    (HTTP 402)."

    Design: Corner/errors/print_budget_exceeded_is_a_402_condition
    """
    api.set_current_utc({"current_utc": CLOCK_2026_09_01}, ADMIN)
    hub = create_hub(name="Tiny Budget Hub", max_print_tonnage_budget_cents=500)
    site = create_site(hub["id"])
    region = create_region(hub["id"])
    market = create_market(region["id"], guaranteed_floor_copies=0)
    create_route(site["id"], market["id"])
    version = validate_success(api.get_hub(hub["id"], PRINT_OPS), 200)["version"]
    validate_success(
        api.plan_market_transfer(
            market["id"],
            {"receiving_print_site_id": site["id"], "expected_hub_version": version},
            PRINT_OPS),
        200,
    )
    create_edition(market["id"], site["id"], slug="2026-09-21", page_count=8,
                   requested_print_run_copies=1)
    # The 500-cent budget is then consumed by the site's recorded press-volume feed,
    # the one aggregate the PRD fixes in cents (§2.4).
    record_print_volume(site["id"], "2026-09-29", 500)

    response = api.create_edition(
        market["id"],
        {
            "assigned_print_site_id": site["id"],
            "slug": "2026-09-22",
            "page_count": 8,
            "requested_print_run_copies": 1,
            "late_sports_engineering_flag": False,
            "legal_notice_count": 0,
        },
        PRINT_OPS,
    )

    error = validate_error(response, "ERR_PRINT_BUDGET_EXCEEDED")
    assert response.status_code == 402, (
        f"budget exhaustion carries HTTP 402, got {response.status_code}"
    )
    assert error["error_id"] == "ERR_PRINT_BUDGET_EXCEEDED"
    assert error["error_id"] != "ERR_PRESS_CAPACITY_EXCEEDED", (
        "budget and capacity failures must be distinguishable"
    )

    editions = validate_success(api.list_market_editions(market["id"], PRINT_OPS), 200)
    assert len(editions) == 1, "only one edition may exist after the refusal"