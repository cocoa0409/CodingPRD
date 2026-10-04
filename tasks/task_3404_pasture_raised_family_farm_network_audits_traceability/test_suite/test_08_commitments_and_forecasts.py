"""Supply commitments: creation gates, cumulative cap, retailer scoping."""
from test_helpers import (
    ApiErrorId,
    api_client,
    complete_audit,
    create_active_farm,
    create_contract,
    create_commitment,
    create_forecast,
    create_retailer,
    get_farm,
    make_retailer_buyer_headers,
    schedule_audit,
    set_clock,
    setup_commitment_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

NM = TEST_USERS["network_manager_headers"]


def test_forecast_duplicate_farm_week_rejected(api):
    """PRD §3.7: "only one forecast may exist per farm and week: a duplicate
    declaration for the same pair is rejected with `ERR_FORECAST_EXISTS`
    (HTTP 409)."

    Design: Corner/entities/forecast_duplicate_farm_week_rejected
    """
    farm = create_active_farm(name="Forecast Dup Farm")["farm"]
    validate_success(
        api.create_forecast(
            farm["id"],
            {"week_start": "2026-09-07", "season": "AUTUMN", "weather_severity": "NONE"},
            NM,
        ),
        201,
    )

    resp = api.create_forecast(
        farm["id"],
        {"week_start": "2026-09-07", "season": "WINTER", "weather_severity": "SEVERE"},
        NM,
    )
    validate_error(resp, ApiErrorId.ERR_FORECAST_EXISTS, 409)


def test_retailer_creation_supports_entity_backed_identity(api):
    """PRD §2.1: "When `X-User-Role` is `RetailerBuyer`, `X-User-ID` is the `id`
    of the acting `RetailerAccount`; ownership checks on supply commitments
    compare the commitment's `retailer_id` field to `X-User-ID`, and a buyer may
    therefore only ever see its own account's commitments."

    Design: Corner/entities/retailer_creation_supports_entity_backed_identity
    """
    retailer = create_retailer(name="Ozark Fresh Markets", banner="Ozark Fresh",
                               terms_net_days=45)

    resp = api.list_commitments(
        make_retailer_buyer_headers(retailer["id"]),
        params={"retailer_id": retailer["id"]},
    )
    rows, meta = validate_paginated(resp)
    assert rows == [] and meta["total_count"] == 0 and meta["has_more"] is False


def test_retailer_buyer_scoped_to_own_commitments(api):
    """PRD §3.7: "A `RetailerBuyer` sees only its own account's commitments: on
    the list endpoint the `retailer_id` filter is mandatory and must equal the
    buyer's `X-User-ID`, and on the detail read the commitment's `retailer_id`
    must equal it — any attempt to reach another retailer's commitments is
    `ERR_FORBIDDEN`."

    Design: Corner/rbac/retailer_buyer_scoped_to_own_commitments
    """
    retailer_a = create_retailer(name="Retailer A", banner="A-Mart", terms_net_days=30)
    retailer_b = create_retailer(name="Retailer B", banner="B-Mart", terms_net_days=60)
    farm = create_active_farm(name="Scoped Farm")["farm"]
    create_forecast(farm["id"], "2026-09-07", "AUTUMN", "NONE")
    commitment = create_commitment(retailer_a["id"], farm["id"], "2026-09-07", 10)

    # Buyer A filtering by retailer B: forbidden.
    resp_scope = api.list_commitments(
        make_retailer_buyer_headers(retailer_a["id"]),
        params={"retailer_id": retailer_b["id"]},
    )
    validate_error(resp_scope, ApiErrorId.ERR_FORBIDDEN, 403)

    # Buyer A filtering by its own id: sees the commitment.
    resp_own = api.list_commitments(
        make_retailer_buyer_headers(retailer_a["id"]),
        params={"retailer_id": retailer_a["id"]},
    )
    rows, meta = validate_paginated(resp_own)
    assert meta["total_count"] == 1 and rows[0]["id"] == commitment["id"]

    # Buyer B reading A's commitment by id: forbidden.
    resp_detail = api.get_commitment(
        commitment["id"], make_retailer_buyer_headers(retailer_b["id"])
    )
    validate_error(resp_detail, ApiErrorId.ERR_FORBIDDEN, 403)


def test_commitment_without_forecast_returns_forecast_required(api):
    """PRD §3.7: "And a production forecast must already exist for that exact
    farm and `week_start`, else `ERR_FORECAST_REQUIRED` (HTTP 422)."

    Design: Corner/validations/commitment_without_forecast_returns_forecast_required
    """
    farm = create_active_farm(name="No Forecast Farm")["farm"]
    retailer = create_retailer()

    resp = api.create_commitment(
        {
            "retailer_id": retailer["id"],
            "farm_id": farm["id"],
            "week_start": "2026-09-07",
            "committed_dozens": 10,
        },
        NM,
    )
    validate_error(resp, ApiErrorId.ERR_FORECAST_REQUIRED, 422)


def test_commitment_on_probation_farm_returns_not_active(api):
    """PRD §3.7: "The farm must be `ACTIVE`, else `ERR_FARM_NOT_ACTIVE`."
    PRD §3.2: "When the outcome is `FAILED`, the audit moves `SCHEDULED →
    FAILED` with the same auditor and completion stamps"

    Design: Corner/validations/commitment_on_probation_farm_returns_not_active
    """
    farm = create_active_farm(name="Probation Farm")["farm"]
    retailer = create_retailer()

    audit2 = schedule_audit(farm["id"], "ANNUAL", "2026-10-05T00:00:00Z")
    set_clock("2026-10-05T10:00:00Z")
    complete_audit(audit2["id"], "FAILED")
    assert get_farm(farm["id"])["status"] == "PROBATION"

    resp = api.create_commitment(
        {
            "retailer_id": retailer["id"],
            "farm_id": farm["id"],
            "week_start": "2026-10-12",
            "committed_dozens": 10,
        },
        NM,
    )
    validate_error(resp, ApiErrorId.ERR_FARM_NOT_ACTIVE, 409)


def test_commitment_cumulative_cap_exceeded(api):
    """PRD §3.7: "the sum of `committed_dozens` over all of the farm's
    commitments for that week in `ACTIVE`, `FILLED`, or `SHORTFALL` status —
    cancelled commitments release their room — plus the new `committed_dozens`
    must not exceed the farm's conservative forecast for the week scaled down by
    nine-tenths and floored to whole dozens. Equality with the cap is permitted;
    exceeding it is rejected with `ERR_COMMITMENT_EXCEEDS_FORECAST` (HTTP 422)."

    Design: Corner/errors_remaining_triggers/commitment_cumulative_cap_exceeded
    """
    ctx = setup_commitment_scenario(week_start="2026-09-07", season="AUTUMN",
                                    weather_severity="NONE", committed_dozens=40,
                                    farm_name="Capped Farm")
    farm_id, retailer_id = ctx["farm"]["id"], ctx["retailer"]["id"]
    # conservative 57 dozens -> cap floor(57 x 0.9) == 51; 40 already booked.

    resp = api.create_commitment(
        {
            "retailer_id": retailer_id,
            "farm_id": farm_id,
            "week_start": "2026-09-07",
            "committed_dozens": 12,
        },
        NM,
    )
    validate_error(resp, ApiErrorId.ERR_COMMITMENT_EXCEEDS_FORECAST, 422)

    # 40 + 11 == 51 == cap: the inclusive boundary is accepted.
    resp_ok = api.create_commitment(
        {
            "retailer_id": retailer_id,
            "farm_id": farm_id,
            "week_start": "2026-09-07",
            "committed_dozens": 11,
        },
        NM,
    )
    validate_success(resp_ok, 201)


def _setup_contract_coverage():
    """ACTIVE farm (contract covers 2026-09-01..2027-08-31) + retailer +
    AUTUMN/NONE forecast for week 2027-09-06 (outside the contract window)."""
    ctx = setup_commitment_scenario(week_start="2027-09-06", season="AUTUMN",
                                    weather_severity="NONE", farm_name="Rolling Hills Farm")
    return ctx


def test_commitment_outside_contract_coverage_rejected_then_accepted(api):
    """PRD §3.7: "A contract of the farm — of any status — must cover the
    committed week, meaning `start_date` is on or before `week_start` and
    `end_date` is on or after it; otherwise `ERR_CONTRACT_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/commitment_gated_by_contract_coverage
    """
    ctx = _setup_contract_coverage()
    farm_id, retailer_id = ctx["farm"]["id"], ctx["retailer"]["id"]

    resp = api.create_commitment(
        {
            "retailer_id": retailer_id,
            "farm_id": farm_id,
            "week_start": "2027-09-06",
            "committed_dozens": 40,
        },
        NM,
    )
    validate_error(resp, ApiErrorId.ERR_CONTRACT_REQUIRED, 422)

    # Supersede with a contract that extends coverage to 2028-08-31.
    create_contract(farm_id, end_date="2028-08-31")

    commitment = validate_success(
        api.create_commitment(
            {
                "retailer_id": retailer_id,
                "farm_id": farm_id,
                "week_start": "2027-09-06",
                "committed_dozens": 40,
            },
            NM,
        ),
        201,
    )
    assert commitment["status"] == "ACTIVE"


def test_commitment_coverage_supersede_marks_old_contract(api):
    """PRD §3.1: "a successful creation moves the farm's previously `ACTIVE`
    contract — if one exists — to `SUPERSEDED`"
    PRD §3.7: "A contract of the farm — of any status — must cover the committed
    week, meaning `start_date` is on or before `week_start` and `end_date` is on
    or after it; otherwise `ERR_CONTRACT_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/commitment_gated_by_contract_coverage
    """
    ctx = _setup_contract_coverage()
    farm_id, retailer_id = ctx["farm"]["id"], ctx["retailer"]["id"]
    old_contract_id = ctx["contract"]["id"]

    resp = api.create_commitment(
        {
            "retailer_id": retailer_id,
            "farm_id": farm_id,
            "week_start": "2027-09-06",
            "committed_dozens": 40,
        },
        NM,
    )
    validate_error(resp, ApiErrorId.ERR_CONTRACT_REQUIRED, 422)

    create_contract(farm_id, end_date="2028-08-31")

    rows, _ = validate_paginated(api.list_contracts(farm_id, NM))
    by_id = {row["id"]: row for row in rows}
    assert by_id[old_contract_id]["status"] == "SUPERSEDED"

    commitment = validate_success(
        api.create_commitment(
            {
                "retailer_id": retailer_id,
                "farm_id": farm_id,
                "week_start": "2027-09-06",
                "committed_dozens": 40,
            },
            NM,
        ),
        201,
    )
    assert commitment["status"] == "ACTIVE"


def _setup_lapsed_farm_scenario():
    """ACTIVE farm with contract covering through 2027-12-31, retailer, and an
    AUTUMN/NONE forecast for week 2027-09-06 (conservative 57, cap 51); clock
    advanced to 2027-09-04 so the farm's certification has lapsed."""
    ctx = setup_commitment_scenario(
        week_start="2027-09-06", season="AUTUMN", weather_severity="NONE",
        farm_name="Sunset Ridge Farm", contract_end="2027-12-31",
    )
    # Last pass 2026-09-03T09:00:00Z + 365 days < 2027-09-04: CERT_LAPSED.
    set_clock("2027-09-04T00:00:00Z")
    return ctx


def test_commitment_cert_lapse_beats_forecast_cap(api):
    """PRD §2.11: "Business rules then run in this sequence: certification gates
    first (`ERR_CERTIFICATION_REQUIRED`, `ERR_CERTIFICATION_NOT_CURRENT`), then
    covering-contract and forecast existence (`ERR_CONTRACT_REQUIRED`,
    `ERR_FORECAST_REQUIRED`), then temporal rules (`ERR_AUDIT_TOO_SOON`,
    `ERR_AUDIT_WINDOW_MISSED`, `ERR_STOP_DATE_CONFLICT`), then uniqueness and
    aggregate gates (`ERR_STOP_SEQUENCE_CONFLICT`, `ERR_FORECAST_EXISTS`,
    `ERR_DUPLICATE_SETTLEMENT`, `ERR_ROUTE_STOPS_OPEN`), and finally capacity
    and quota limits (`ERR_BIRD_CAPACITY_INSUFFICIENT`,
    `ERR_COMMITMENT_EXCEEDS_FORECAST`, `ERR_ROUTE_CAPACITY_EXCEEDED`,
    `ERR_INSUFFICIENT_LOT_DOZENS`)."
    PRD §3.7: "Its `certification_status` must be `CERTIFIED`, else
    `ERR_CERTIFICATION_NOT_CURRENT`."

    Design: Difficulty/priority_pair_validation_conflict/commitment_cert_lapse_beats_forecast_cap
    """
    ctx = _setup_lapsed_farm_scenario()
    farm_id, retailer_id = ctx["farm"]["id"], ctx["retailer"]["id"]

    farm_now = get_farm(farm_id)
    assert farm_now["status"] == "ACTIVE"
    assert farm_now["certification_status"] == "CERT_LAPSED"

    # 60 dozens also breaches the cap (51): the cert gate must win.
    resp = api.create_commitment(
        {
            "retailer_id": retailer_id,
            "farm_id": farm_id,
            "week_start": "2027-09-06",
            "committed_dozens": 60,
        },
        NM,
    )
    validate_error(resp, ApiErrorId.ERR_CERTIFICATION_NOT_CURRENT, 422)


def test_commitment_cert_lapse_fires_even_within_cap(api):
    """PRD §3.7: "Its `certification_status` must be `CERTIFIED`, else
    `ERR_CERTIFICATION_NOT_CURRENT`."

    Design: Difficulty/priority_pair_validation_conflict/commitment_cert_lapse_beats_forecast_cap
    """
    ctx = _setup_lapsed_farm_scenario()
    farm_id, retailer_id = ctx["farm"]["id"], ctx["retailer"]["id"]

    farm_now = get_farm(farm_id)
    assert farm_now["certification_status"] == "CERT_LAPSED"

    # 10 dozens is well within the cap (51): only the certification gate fails.
    resp = api.create_commitment(
        {
            "retailer_id": retailer_id,
            "farm_id": farm_id,
            "week_start": "2027-09-06",
            "committed_dozens": 10,
        },
        NM,
    )
    validate_error(resp, ApiErrorId.ERR_CERTIFICATION_NOT_CURRENT, 422)
