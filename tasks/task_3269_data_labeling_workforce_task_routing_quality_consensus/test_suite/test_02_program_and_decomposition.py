"""Program intake, decomposition, listing and existence errors."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    create_program_payload,
    create_spec_unit_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def _program(**overrides) -> dict:
    return validate_success(api_client.create_program(create_program_payload(**overrides), ADMIN), 201)


def _unit(program, **overrides) -> dict:
    live = validate_success(api_client.get_program(program["id"], ADMIN), 200)
    payload = create_spec_unit_payload(
        program_id=program["id"], expected_program_version=live["version"], **overrides
    )
    return validate_success(api_client.create_spec_unit(payload, ADMIN), 201)


def test_program_get_round_trips_the_full_configuration(api):
    """PRD §3.1: "The registration also accepts `coverage_hours`, the wall-clock
    span of the engagement's delivery window, which defaults to 168 hours. The
    engagement is created in `DRAFT`, which is the state in which it can still be
    decomposed but cannot yet produce work."

    Design: Corner/entities/program_get_round_trips_the_full_engagement_configuration
    """
    program = _program(
        instruction_model="SPAN_EXTRACTION",
        sensitivity_class="SENSITIVE",
        min_consensus_agreement=0.75,
        commitment_quorum=4,
        patience_seconds=900,
        capacity_points=50000,
    )
    data = validate_success(api.get_program(program["id"], ADMIN), 200)

    assert data["program_code"] == "AX-4410"
    assert data["instruction_model"] == "SPAN_EXTRACTION"
    assert data["sensitivity_class"] == "SENSITIVE"
    assert data["min_consensus_agreement"] == 0.75
    assert data["commitment_quorum"] == 4
    assert data["patience_seconds"] == 900
    # PRD §2.7 renders every server timestamp with exactly three fractional
    # digits, so a blackout instant that was supplied without a fractional part
    # round-trips as ".000Z".
    assert data["blackout_start_utc"] == "2026-09-20T00:00:00.000Z"
    assert data["blackout_end_utc"] == "2026-09-25T00:00:00.000Z"
    assert data["status"] == "DRAFT"
    assert data["operational_restricted"] is False
    assert data["demand_points"] == 0, "an engagement with no units demands no points"


def test_item_listing_filters_by_spec_unit_and_paginates(api):
    """PRD §2.3: "When `limit` is omitted it defaults to 10, and it must fall
    between a minimum of 1 and a maximum of 100 inclusive."

    PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/item_listing_filters_by_spec_unit_and_paginates
    """
    program = _program()
    u1 = _unit(program, unit_code="U-1")
    u2 = _unit(program, unit_code="U-2")
    for key in ("i-0001", "i-0002"):
        validate_success(
            api_client.create_item(u1["id"], {"item_key": key, "payload_uri": f"s3://ax/{key}"}, ADMIN),
            201,
        )
    validate_success(
        api_client.create_item(u2["id"], {"item_key": "i-0003", "payload_uri": "s3://ax/i-0003"}, ADMIN),
        201,
    )

    resp = api_client.list_items(ADMIN, {"spec_unit_id": u1["id"], "limit": 1, "offset": 0})
    rows, meta = validate_paginated(resp)
    assert len(rows) == 1, "limit 1 must page a single row"
    assert meta["total_count"] == 2, "the counter describes the filtered set"
    assert meta["has_more"] is True
    assert rows[0]["item_key"] == "i-0001", "rows are ordered by item_seq ascending"

    validate_error(api_client.list_items(ADMIN, {"limit": 0}), "ERR_INVALID_REQUEST", 400)
    validate_error(api_client.list_items(ADMIN, {"limit": 101}), "ERR_INVALID_REQUEST", 400)


def test_unknown_item_and_commit_ids_report_their_own_not_found(api):
    """PRD §2.11: "a missing piece yields `ERR_ITEM_NOT_FOUND` (404), a missing
    assignment yields `ERR_COMMIT_NOT_FOUND` (404)"

    Design: Corner/entities/get_item_with_unknown_id_returns_item_not_found
    """
    validate_error(api_client.get_item(NON_EXISTENT_UUID, ADMIN), "ERR_ITEM_NOT_FOUND", 404)
    validate_error(api_client.get_commit(NON_EXISTENT_UUID, ADMIN), "ERR_COMMIT_NOT_FOUND", 404)


def test_each_path_identifier_family_reports_its_own_not_found(api):
    """PRD §2.11: "Rank 3 is existence, and it resolves path parameters strictly
    from left to right: the first identifier in the path that does not resolve to
    an existing resource determines the error, and later identifiers are never
    examined."

    Design: Corner/errors/appeal_case_endpoints_report_their_own_not_found
    """
    validate_error(
        api_client.advance_appeal(
            NON_EXISTENT_UUID, {"appeal_action": "PROPOSE", "proposed_outcome": "OUTCOME_STANDS"},
            TEST_USERS["reviewer_headers"],
        ),
        "ERR_APPEAL_CASE_NOT_FOUND",
        404,
    )
    validate_error(api_client.get_spec_unit(NON_EXISTENT_UUID, ADMIN), "ERR_SPEC_UNIT_NOT_FOUND", 404)
    validate_error(api_client.get_program(NON_EXISTENT_UUID, ADMIN), "ERR_PROGRAM_NOT_FOUND", 404)
    validate_error(
        api_client.worker_qualification_action(
            NON_EXISTENT_UUID,
            {"language_code": "es-MX", "tier": "PROFICIENT", "qualification_action": "ENROLL"},
            ADMIN,
        ),
        "ERR_WORKER_NOT_FOUND",
        404,
    )


def test_duplicate_unit_code_and_item_key_are_refused(api):
    """PRD §2.4: "Uniqueness is scoped rather than global: `unit_code` must be
    unique within its owning engagement, `item_key` must be unique within its spec
    unit, and `handle` must be unique across the whole workforce. A violation of
    any of those three is reported identically as `ERR_UNIT_CODE_DUPLICATE` (409)."

    Design: Corner/cross_cutting_complexity_layers/duplicate_unit_code_is_refused_by_the_uniqueness_gate
    """
    program = _program()
    u1 = _unit(program, unit_code="U-1")
    validate_success(
        api_client.create_item(u1["id"], {"item_key": "i-0001", "payload_uri": "s3://ax/0001"}, ADMIN),
        201,
    )

    live = validate_success(api_client.get_program(program["id"], ADMIN), 200)
    dup_unit = create_spec_unit_payload(
        program_id=program["id"],
        unit_code="U-1",
        max_items=5,
        expected_program_version=live["version"],
    )
    validate_error(api_client.create_spec_unit(dup_unit, ADMIN), "ERR_UNIT_CODE_DUPLICATE", 409)

    validate_error(
        api_client.create_item(u1["id"], {"item_key": "i-0001", "payload_uri": "s3://ax/dup"}, ADMIN),
        "ERR_UNIT_CODE_DUPLICATE",
        409,
    )


def test_cross_entity_reference_resolves_and_a_cycle_is_refused(api):
    """PRD §2.4: "The graph is acyclic; a submission whose `parent_unit_id` would
    close a cycle is refused with `ERR_SPEC_UNIT_CYCLE` (409)."

    Design: Corner/errors/cross_entity_reference_must_resolve_to_an_existing_parent
    """
    program = _program()
    root = _unit(program, unit_code="U-ROOT")
    live = validate_success(api_client.get_program(program["id"], ADMIN), 200)
    child = validate_success(
        api_client.create_spec_unit(
            create_spec_unit_payload(
                program_id=program["id"],
                unit_code="U-CHILD",
                parent_unit_id=root["id"],
                expected_program_version=live["version"],
            ),
            ADMIN,
        ),
        201,
    )
    assert child["parent_unit_id"] == root["id"]

    live = validate_success(api_client.get_program(program["id"], ADMIN), 200)
    grandchild = validate_success(
        api_client.create_spec_unit(
            create_spec_unit_payload(
                program_id=program["id"],
                unit_code="U-GRAND",
                parent_unit_id=child["id"],
                expected_program_version=live["version"],
            ),
            ADMIN,
        ),
        201,
    )
    assert grandchild["parent_unit_id"] == child["id"], "a two-level tree is not a cycle"

    # A brand-new unit is a leaf, so it cannot parent itself; the cycle a
    # submission can close is the scope-identity one, where the submitted
    # unit_code is already carried by an ancestor of the parent it names
    # (PRD §2.4 scopes `unit_code` to its owning engagement and refuses a
    # submission "whose `parent_unit_id` would close a cycle").
    live = validate_success(api_client.get_program(program["id"], ADMIN), 200)
    cycle = validate_error(
        api_client.create_spec_unit(
            create_spec_unit_payload(
                program_id=program["id"],
                unit_code="U-ROOT",
                parent_unit_id=grandchild["id"],
                expected_program_version=live["version"],
            ),
            ADMIN,
        ),
        "ERR_SPEC_UNIT_CYCLE",
        409,
    )
    assert cycle["error_id"] == "ERR_SPEC_UNIT_CYCLE"


def test_derived_counts_are_visible_in_the_mutating_request(api):
    """PRD §3.11: "The engagement's `demand_points` is the sum of
    `unit_effective_points` over **every** **SpecUnit** under the engagement"

    PRD §2.4: "`max_items` is the ceiling on how many pieces a unit may hold, and
    `item_count` is the live count of pieces attached to it"

    Design: Corner/consistency_model/derived_counts_are_visible_in_the_same_request_that_changes_them
    """
    program = _program()
    unit = _unit(program, unit_code="U-1", max_items=10)
    for key in ("i-0001", "i-0002"):
        validate_success(
            api_client.create_item(unit["id"], {"item_key": key, "payload_uri": f"s3://ax/{key}"}, ADMIN),
            201,
        )

    third = validate_success(
        api_client.create_item(unit["id"], {"item_key": "i-0003", "payload_uri": "s3://ax/i-0003"}, ADMIN),
        201,
    )
    assert third["item_seq"] == 3, "the insertion sequence is assigned inside the write"

    live_unit = validate_success(api_client.get_spec_unit(unit["id"], ADMIN), 200)
    assert live_unit["item_count"] == 3
    assert live_unit["remaining_item_slots"] == 7

    live_program = validate_success(api_client.get_program(program["id"], ADMIN), 200)
    assert live_program["demand_points"] == 10, "STANDARD weight 1 times max_items 10"