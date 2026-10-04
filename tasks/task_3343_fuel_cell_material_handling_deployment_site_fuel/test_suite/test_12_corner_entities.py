"""Corner coverage — entity creation, defaults, computed fields, request-shape
rejections, and the pagination envelope (PRD §2.3, §2.4, §3.1, §3.2, §3.4).
"""
import re

import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    NON_EXISTENT_UUID, is_valid_uuid, is_iso8601_timestamp,
    create_site, create_site_payload, create_assessment_payload,
    create_supply_contract_payload,
    MANAGER, ADMIN,
)


def test_site_creation_applies_defaults_and_system_fields(api):
    """PRD §3.1: "A new site is `ACTIVE` and carries
    `actual_productivity_units_per_hour` as null until observed throughput is
    recorded after conversion."
    PRD §2.4: "`version` (integer): starts at 1 on creation and increments by
    exactly 1 on every mutation of the resource, including mutations caused by
    automatic state transitions and cascades."

    Design: Corner/entities/site_creation_applies_defaults_and_system_fields
    """
    resp = api.create_site(create_site_payload(
        code="S-E1", name="Entity Site", address="1 Main St",
        baseline_labor_rate_per_hour=30.0), MANAGER)
    site = validate_success(resp, 201)
    assert site["status"] == "ACTIVE"
    assert site["version"] == 1
    assert site["actual_productivity_units_per_hour"] is None
    assert is_valid_uuid(site["id"]), "the server mints a UUID id"


def test_site_get_nonexistent_returns_404(api):
    """PRD §2.6: "The first identifier that does not correspond to an existing
    resource produces `ERR_NOT_FOUND` (HTTP 404), and no later identifier is
    consulted."

    Design: Corner/entities/site_get_nonexistent_returns_404
    """
    resp = api.get_site(NON_EXISTENT_UUID, MANAGER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_site_duplicate_code_rejected(api):
    """PRD §3.1: "creating a **Site** with a human-readable `code` (unique
    across all sites, 1–40 characters; a duplicate is rejected with
    `ERR_DUPLICATE_CODE`, HTTP 409)"

    Design: Corner/entities/site_duplicate_code_rejected
    """
    create_site(code="S-DUP", name="First")
    resp = api.create_site(create_site_payload(
        code="S-DUP", name="Second", address="2 B St",
        baseline_labor_rate_per_hour=31.0), MANAGER)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CODE)


def test_assessment_daily_kg_computed_at_creation(api):
    """PRD §3.1: "the system computes `daily_kg_estimate`: multiply the
    forklift count by the duty-cycle hours and by a consumption factor of 0.9
    kg per engine-on hour, then apply a peak-shift multiplier of 1.0 when the
    peak window is 8 hours or shorter and 1.15 when it is longer, and round the
    result half-up to 2 decimal places."

    Design: Corner/entities/assessment_daily_kg_computed_at_creation
    """
    site = create_site(code="S-E2")
    resp = api.create_assessment(site["id"], create_assessment_payload(
        forklift_count=10, duty_cycle_hours_per_day=7.5, peak_shift_hours=9), MANAGER)
    assessment = validate_success(resp, 201)
    # 10 x 7.5 x 0.9 = 67.5; peak 9 > 8 so x1.15 -> 77.625 -> ROUND_HALF_UP 77.63
    assert assessment["daily_kg_estimate"] == pytest.approx(77.63), (
        f"expected 77.63, got {assessment['daily_kg_estimate']}")


def test_technician_active_defaults_true(api):
    """PRD §3.4: "Technicians themselves are registered by `PlatformAdmin` with
    a `name`, a `certification_level` of `BASIC`, `ADVANCED`, or `MASTER`, a
    `certified_until` date that must lie in the future at registration, and an
    `active` flag that defaults to true when not supplied."

    Design: Corner/entities/technician_active_defaults_true
    """
    resp = api.create_technician(
        {"name": "Default Tech", "certification_level": "BASIC",
         "certified_until": "2027-06-01"}, ADMIN)
    tech = validate_success(resp, 201)
    assert tech["active"] is True, "omitted active flag defaults to true"


def test_invalid_enum_supply_mode_rejected(api):
    """PRD §3.2: "created in `DRAFT` with a `supply_mode` of exactly one of
    `DELIVERED_LIQUID`, `ON_SITE_GENERATION`, or `PIPELINE`"
    PRD §2.10: "Sixth, request shape: required fields present, well-typed,
    enum values within their declared sets, date and datetime formats valid
    (`ERR_INVALID_REQUEST`, HTTP 400)."

    Design: Corner/entities/invalid_enum_supply_mode_rejected
    """
    site = create_site(code="S-E3")
    resp = api.create_supply_contract(site["id"], create_supply_contract_payload(
        supply_mode="MAGIC_PIPE"), MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_missing_required_field_rejected(api):
    """PRD §2.10: "Sixth, request shape: required fields present, well-typed,
    enum values within their declared sets, date and datetime formats valid
    (`ERR_INVALID_REQUEST`, HTTP 400)."
    PRD §3.2: "a `base_price_per_kg` commodity price (greater than 0)"

    Design: Corner/entities/missing_required_field_rejected
    """
    site = create_site(code="S-E4")
    payload = create_supply_contract_payload()
    del payload["base_price_per_kg"]
    resp = api.create_supply_contract(site["id"], payload, MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_invalid_date_range_rejected(api):
    """PRD §3.2: "a coverage window from `start_date` to `end_date` (ISO dates,
    with `end_date` on or after `start_date` — otherwise
    `ERR_INVALID_DATE_RANGE`)"

    Design: Corner/entities/invalid_date_range_rejected
    """
    site = create_site(code="S-E5")
    resp = api.create_supply_contract(site["id"], create_supply_contract_payload(
        start_date="2026-12-31", end_date="2026-10-01"), MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)


def test_list_pagination_envelope(api):
    """PRD §2.3: "`limit` sets the maximum number of items returned; it
    defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets
    the number of items skipped; it defaults to 0."
    PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/list_pagination_envelope
    """
    create_site(code="S-PG1", name="Page One")
    create_site(code="S-PG2", name="Page Two")
    page1, meta1 = validate_paginated(
        api.list_sites(MANAGER, params={"limit": 1, "offset": 0}))
    assert len(page1) == 1
    assert meta1["total_count"] == 2
    assert meta1["has_more"] is True
    page2, meta2 = validate_paginated(
        api.list_sites(MANAGER, params={"limit": 1, "offset": 1}))
    assert len(page2) == 1
    assert meta2["has_more"] is False
    assert page1[0]["id"] != page2[0]["id"]


def test_system_fields_server_minted(api):
    """PRD §2.4: "`id` (string): a server-minted UUID with no type prefix."
    PRD §2.4: "`created_at` (string): an ISO 8601 UTC timestamp with three
    fractional digits, set at creation."
    PRD §2.4: "`version` (integer): starts at 1 on creation and increments by
    exactly 1 on every mutation of the resource, including mutations caused by
    automatic state transitions and cascades."

    Design: Corner/entities/system_fields_input_ignored
    """
    resp = api.create_site(create_site_payload(
        code="S-SYS", name="Sys Site", address="9 Sys St",
        baseline_labor_rate_per_hour=30.0), MANAGER)
    site = validate_success(resp, 201)
    assert site["version"] == 1
    assert is_iso8601_timestamp(site["created_at"])
    assert re.search(r"\.\d{3}", site["created_at"]), (
        "created_at carries three fractional digits per PRD §2.4")
