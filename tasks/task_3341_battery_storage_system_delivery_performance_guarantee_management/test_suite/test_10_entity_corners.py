"""Entity creation / read / listing corner tests."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_project,
    create_esa_payload,
    create_project,
    create_project_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

DEV = TEST_USERS["project_developer_headers"]
MARKET = TEST_USERS["market_operator_headers"]


def test_project_create_computes_duration_sizing_and_common_fields(api):
    """PRD §3.1: "`duration_hours` is the nameplate energy divided by the
    nameplate power, rounded half up to 2 decimal places."
    PRD §3.1: "a `CAPACITY_FIRMING` project is `VALID` only when its duration
    is at least 4.00 hours and its duty cycle is `ONE_CYCLE_DAILY` — the
    boundary is inclusive, so exactly 4.00 hours passes while 3.99 fails"
    PRD §3.1: "A project also carries a commissioning baseline
    `commissioned_capacity_mwh`, initially zero; a most-recent
    `equivalent_cycles` count, initially zero; a forward-looking
    `projected_capacity_mwh`; and an `augmentation_count` of its augmentation
    events in `PLANNED` or `EXECUTED` status."
    PRD §2.5: "Every entity in the system carries the same four system-managed
    properties: `id`, a server-minted UUID with no type prefix; `created_at`,
    an ISO 8601 UTC timestamp with three fractional digits, fixed at creation;
    `updated_at`, refreshed on every mutation; and `version`, an integer that
    increments by one on every mutation of the entity."

    Design: Corner/entities/project_create_computes_duration_and_sizing_and_returns_common_fields
    """
    data = validate_success(
        api.create_project(
            create_project_payload(
                name="Boundary BESS",
                market_application="CAPACITY_FIRMING",
                duty_cycle_profile="ONE_CYCLE_DAILY",
                rated_power_mw=10,
                rated_energy_mwh=40,
                budget_cents=1000000,
            ),
            DEV,
        ),
        expected_status=201,
    )
    assert_project(data)
    assert data["version"] == 1
    assert data["duration_hours"] == 4.0, (
        f"40 / 10 == 4.00, got {data['duration_hours']}"
    )
    assert data["sizing_status"] == "VALID"
    assert data["commissioned_capacity_mwh"] == 0
    assert data["augmentation_count"] == 0


def test_project_sizing_invalid_and_client_computed_inputs_ignored(api):
    """PRD §3.1: "a `CAPACITY_FIRMING` project is `VALID` only when its
    duration is at least 4.00 hours and its duty cycle is `ONE_CYCLE_DAILY` —
    the boundary is inclusive, so exactly 4.00 hours passes while 3.99 fails"
    PRD §3.1: "The sizing verdict is computed at creation and whenever the
    market application or duty cycle changes; it gates contract execution
    later."

    Design: Corner/entities/project_sizing_invalid_when_firming_duration_below_four_computed_input_ignored
    """
    payload = create_project_payload(
        name="Short BESS",
        market_application="CAPACITY_FIRMING",
        duty_cycle_profile="ONE_CYCLE_DAILY",
        rated_power_mw=11,
        rated_energy_mwh=33,
        budget_cents=1000000,
    )
    # Inject bogus computed-field values; the server must compute its own.
    payload["sizing_status"] = "VALID"
    payload["duration_hours"] = 9
    data = validate_success(api.create_project(payload, DEV), expected_status=201)
    assert data["sizing_status"] == "INVALID", (
        f"duration 3.00 < 4.00 for CAPACITY_FIRMING -> INVALID, got {data['sizing_status']}"
    )
    assert data["duration_hours"] == 3.0, (
        f"33 / 11 == 3.00, got {data['duration_hours']}"
    )


def test_esa_create_computes_total_price_and_rejects_bad_shape(api):
    """PRD §3.2: "The agreement's `total_price_cents` is computed at creation
    as the contracted energy — rounded to 2 decimal places first — multiplied
    by the unit price, kept as integer cents. The agreement starts `DRAFT`,
    with `accrued_ld_cents`, `waived_ld_cents`, and `net_ld_due_cents` all
    zero."
    PRD §3.2: "The create payload names the `project_id`, the
    `contracted_power_mw` and `contracted_energy_mwh` (both greater than zero),
    a `guaranteed_capacity_mwh` that must be greater than zero and no larger
    than `contracted_energy_mwh`, a `guaranteed_rte_pct` expressed as a
    fraction greater than zero and at most one, a non-negative
    `price_per_mwh_cents`, non-negative `ld_rate_per_day_cents` and
    `ld_cap_cents`, and the `guaranteed_delivery_date` together with a
    `longstop_date` that must fall strictly after it. Violating any of these
    input constraints is a creation-time `ERR_INVALID_REQUEST`."

    Design: Corner/entities/esa_create_computes_total_price_and_rejects_bad_shape
    """
    project = create_project(api=api)
    good = validate_success(
        api.create_esa(create_esa_payload(project["id"]), DEV), expected_status=201
    )
    assert good["total_price_cents"] == 12000000, (
        f"40 * 300000 == 12000000, got {good['total_price_cents']}"
    )
    assert good["status"] == "DRAFT"
    assert good["accrued_ld_cents"] == 0
    assert good["waived_ld_cents"] == 0
    assert good["net_ld_due_cents"] == 0

    # guaranteed_capacity_mwh (41) > contracted_energy_mwh (40)
    resp = api.create_esa(
        create_esa_payload(project["id"], guaranteed_capacity_mwh=41), DEV
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    # longstop_date not strictly after guaranteed_delivery_date
    resp = api.create_esa(
        create_esa_payload(project["id"], longstop_date="2026-10-01T00:00:00Z"), DEV
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_project_get_with_unknown_id_returns_not_found(api):
    """PRD §2.9: "An unresolvable id in the URL path itself yields the generic
    `ERR_NOT_FOUND`."

    Design: Corner/entities/project_get_with_unknown_id_returns_not_found
    """
    resp = api.get_project(NON_EXISTENT_UUID, DEV)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_body_fk_to_missing_parent_returns_specific_not_found(api):
    """PRD §2.9: "Every such reference must resolve to an existing resource,
    and the specific not-found error identifies which reference failed:
    `ERR_PROJECT_NOT_FOUND`, `ERR_ESA_NOT_FOUND`, `ERR_LTSA_NOT_FOUND`,
    `ERR_CLAIM_NOT_FOUND`, `ERR_MILESTONE_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`,
    `ERR_TEST_NOT_FOUND`, `ERR_AUGMENTATION_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    or `ERR_BID_SESSION_NOT_FOUND`."

    Design: Corner/entities/body_fk_to_missing_parent_returns_specific_not_found
    """
    resp = api.create_milestone(
        {
            "esa_id": NON_EXISTENT_UUID,
            "kind": "DELIVERY",
            "planned_date": "2026-10-01T00:00:00Z",
        },
        DEV,
    )
    validate_error(resp, ApiErrorId.ERR_ESA_NOT_FOUND)


def test_projects_list_paginates_with_limit_offset_total_and_has_more(api):
    """PRD §2.3: "List endpoints accept the query parameters `limit` and
    `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of
    100; `offset` defaults to 0. List responses carry `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object."

    Design: Corner/entities/projects_list_paginates_with_limit_offset_total_has_more
    """
    create_project(api=api, name="P1")
    create_project(
        api=api, name="P2", market_application="FREQUENCY_REGULATION",
        duty_cycle_profile="CONTINUOUS", rated_energy_mwh=20,
    )
    create_project(api=api, name="P3", duty_cycle_profile="TWO_CYCLES_DAILY")

    page1, meta1 = validate_paginated(
        api.list_projects(MARKET, params={"limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_projects(MARKET, params={"limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    all_rows, meta_all = validate_paginated(api.list_projects(MARKET))
    assert len(all_rows) == 3, "default limit 10 returns all three rows"
