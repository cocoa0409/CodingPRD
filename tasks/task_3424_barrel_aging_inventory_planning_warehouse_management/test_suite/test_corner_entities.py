"""Corner-design translations: entity intake, system fields, and listings.

Barrel creation runs the payload-shape gate before any state change
(PRD §2.10 gate 3, §3.2); a freshly filled barrel is server-stamped and
already AGING with its INITIAL_FILL occupancy open (PRD §2.5, §3.2); unknown
identifiers resolve to ERR_NOT_FOUND (PRD §2.8); list endpoints paginate
through meta (PRD §2.3); and an omitted assessment quality_score persists as
null (PRD §2.5, §3.3).
"""
from datetime import datetime

from test_helpers import (
    ApiErrorId,
    DEFAULT_CLOCK_ISO,
    STANDARD_FILL_ISO,
    assert_barrel,
    assert_barrel_assessment,
    assert_slot_occupancy,
    create_assessment_payload,
    create_barrel_payload,
    create_commissioned_rickhouse,
    fill_placed_barrel,
    get_barrel_fresh,
    is_valid_uuid,
    set_clock,
    setup_barrel_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)


def _parse_instant(iso: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp with or without fractional digits.

    PRD pins the stamped *instant* for lifecycle fields (fill_date, start_at)
    but states the three-fractional-digit string format only for
    created_at/updated_at/api_request_timestamp, so comparisons here are
    instant comparisons, not string comparisons.
    """
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def test_barrel_create_missing_fill_volume_returns_validation(api, warehouse_manager_headers):
    """PRD §2.10: "all required input fields are present, no undeclared fields
    appear, types match, enum values are valid, numeric ranges hold ... and
    kind-conditional assessment inputs are present (`ERR_VALIDATION`, HTTP
    400)."
    PRD §3.2: "the `fill_volume_liters` (above zero); and the
    `min_maturation_months` (zero or more) the spirit must rest before it can
    be called mature."

    Design: Corner/entities/barrel_create_missing_fill_volume_returns_validation
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=1, positions_per_row=1, name="RH-E1",
    )
    payload = create_barrel_payload(ctx["slots"][0]["id"])
    del payload["fill_volume_liters"]

    validate_error(
        api.create_barrel(payload, warehouse_manager_headers),
        ApiErrorId.ERR_VALIDATION,
    )

    data, meta = validate_paginated(api.list_barrels(warehouse_manager_headers))
    assert data == [] and meta["total_count"] == 0, (
        "a rejected barrel creation persists nothing"
    )


def test_barrel_create_char_level_out_of_range_rejected(api, warehouse_manager_headers):
    """PRD §2.10: "numeric ranges hold (`char_level` within 1 to 4,
    `drawn_volume_liters` above zero, `period_start` before `period_end`,
    `scheduled_bottling_date` strictly in the future, `limit` within 1 to
    100)".
    PRD §3.2: "`char_level` (an integer from 1 to 4)".

    Design: Corner/entities/barrel_create_char_level_out_of_range_rejected
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=1, positions_per_row=1, name="RH-E2",
    )
    slot_id = ctx["slots"][0]["id"]
    payload = create_barrel_payload(slot_id, char_level=5)

    validate_error(
        api.create_barrel(payload, warehouse_manager_headers),
        ApiErrorId.ERR_VALIDATION,
    )

    occupancies, _meta = validate_paginated(
        api.list_slot_occupancies(slot_id, warehouse_manager_headers)
    )
    assert occupancies == [], "the rejected fill opened no occupancy on the slot"


def test_barrel_create_undeclared_computed_field_rejected(api, warehouse_manager_headers):
    """PRD §2.10: "all required input fields are present, no undeclared fields
    appear, types match, enum values are valid, numeric ranges hold".
    PRD §3.3: "`current_volume_ledger_liters` is the volume of record — the
    number withdrawals, blends, and loss reporting all trust." (a computed
    figure, never an intake input).

    Design: Corner/entities/barrel_create_undeclared_computed_field_rejected
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=1, positions_per_row=1, name="RH-E3",
    )
    payload = create_barrel_payload(
        ctx["slots"][0]["id"], current_volume_ledger_liters=1.0,
    )

    validate_error(
        api.create_barrel(payload, warehouse_manager_headers),
        ApiErrorId.ERR_VALIDATION,
    )


def test_barrel_create_initial_state_and_system_fields(api, warehouse_manager_headers):
    """PRD §2.5: "`id`, a server-minted UUID with no type prefix" and
    "`version`, an integer that increments by one on every mutation of the
    resource".
    PRD §3.2: "The barrel's `fill_date` is the logical clock at creation; it
    begins `BONDED` in custody and `FILLED` in maturation."
    PRD §3.2: "The system opens a slot occupancy on the named slot with
    `move_reason` `INITIAL_FILL`, stamping `start_at` with the current clock
    and leaving `end_at` null".
    PRD §3.2: "Within that same request the barrel's maturation advances
    `FILLED` → `AGING`, so the creation response already shows `AGING`."
    PRD §3.3: "It starts at the barrel's `fill_volume_liters`".

    Design: Corner/entities/barrel_create_initial_state_and_system_fields
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=1, positions_per_row=1, name="RH-E4",
    )
    slot_id = ctx["slots"][0]["id"]
    # The commissioned-rickhouse chain leaves the logical clock at
    # STANDARD_FILL_ISO, so the fill is stamped with that instant.
    barrel = fill_placed_barrel(slot_id)

    assert_barrel(barrel)
    assert is_valid_uuid(barrel["id"]), "id is a server-minted UUID"
    assert barrel["version"] == 1, "creation is the resource's first version"
    assert _parse_instant(barrel["fill_date"]) == _parse_instant(STANDARD_FILL_ISO), (
        "fill_date is the logical clock at creation, not the wall clock"
    )
    assert barrel["maturation_status"] == "AGING", (
        "FILLED -> AGING fires within the create request"
    )
    assert barrel["custody_status"] == "BONDED"

    fresh = get_barrel_fresh(barrel["id"])
    # No ledger events and zero fully elapsed statutory blocks at the fill
    # instant: both variants equal the fill volume.
    assert fresh["current_volume_ledger_liters"] == 200.00
    assert fresh["current_volume_statutory_liters"] == 200.00

    occupancies, meta = validate_paginated(
        api.list_barrel_occupancies(barrel["id"], warehouse_manager_headers)
    )
    assert meta["total_count"] == 1 and len(occupancies) == 1, (
        "exactly one occupancy exists for the barrel"
    )
    occupancy = occupancies[0]
    assert_slot_occupancy(occupancy)
    assert occupancy["slot_id"] == slot_id
    assert occupancy["status"] == "OPEN"
    assert occupancy["move_reason"] == "INITIAL_FILL"
    assert _parse_instant(occupancy["start_at"]) == _parse_instant(STANDARD_FILL_ISO)
    assert occupancy["end_at"] is None


def test_barrel_get_unknown_id_returns_not_found(api, warehouse_manager_headers):
    """PRD §2.8: "Each identifier in the path must resolve to an existing
    resource before the next is examined, and the request is rejected with
    `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve."

    Design: Corner/entities/barrel_get_unknown_id_returns_not_found
    """
    set_clock(DEFAULT_CLOCK_ISO)
    validate_error(
        api.get_barrel("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", warehouse_manager_headers),
        ApiErrorId.ERR_NOT_FOUND,
    )


def test_barrels_list_paginates_with_total_count(api, warehouse_manager_headers):
    """PRD §2.3: "`limit` sets the maximum number of items returned: it
    defaults to 10, with a minimum of 1 and a maximum of 100".
    PRD §2.3: "Paginated list responses carry `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the response
    envelope."

    Design: Corner/entities/barrels_list_paginates_with_total_count
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=1, positions_per_row=3, name="RH-E6",
    )
    s1, s2, s3 = (slot["id"] for slot in ctx["slots"])
    fill_placed_barrel(s1, fill_volume_liters=100.0, min_maturation_months=12)
    fill_placed_barrel(
        s2, spirit_type="RYE", fill_proof=110.0,
        fill_volume_liters=100.0, min_maturation_months=12,
    )
    fill_placed_barrel(s3, fill_volume_liters=100.0, min_maturation_months=12)

    data, meta = validate_paginated(
        api.list_barrels(warehouse_manager_headers, params={"limit": 2, "offset": 0})
    )
    assert len(data) == 2, "limit=2 caps the page at two items"
    assert meta["total_count"] == 3
    assert meta["has_more"] is True


def test_assessment_quality_score_omitted_defaults_null(api, warehouse_manager_headers):
    """PRD §3.3: "A quality sample requires `sample_draw_liters` (above zero),
    the volume drawn and consumed, and may carry an optional `quality_score`,
    an integer from 0 to 100 that is null when omitted and meaningful only for
    samples."
    PRD §2.5: "an omitted `quality_score` is null."
    PRD §3.3: "an `EVAPORATION_READING` assessment resets the running volume
    outright to its `measured_volume_liters` — an authoritative measurement of
    what is actually in the barrel, not a delta".

    Design: Corner/entities/assessment_quality_score_omitted_defaults_null
    """
    ctx = setup_barrel_scenario(
        floors=1, rows_per_floor=1, positions_per_row=1, name="RH-E7",
    )
    barrel = ctx["barrel"]  # 200.0 L filled at STANDARD_FILL_ISO

    set_clock("2029-01-01T00:00:00Z")
    payload = create_assessment_payload("EVAPORATION_READING", measured_volume_liters=195.0)
    assert "quality_score" not in payload, "the input omits quality_score entirely"

    data = validate_success(
        api.create_barrel_assessment(barrel["id"], payload, warehouse_manager_headers),
        expected_status=201,
    )
    assert_barrel_assessment(data)
    assert data["quality_score"] is None, "omitted quality_score persists as null"
    assert data["measured_volume_liters"] == 195.00

    fresh = get_barrel_fresh(barrel["id"])
    assert fresh["current_volume_ledger_liters"] == 195.00, (
        "the reading authoritatively resets the ledger to the measured volume"
    )
