"""Grill models, inventory lots and build sizing: defaults, lifecycle guards,
forward/actual sizing variants, and the two FK reverse views of a lot.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_grill_model,
    assert_inventory_lot,
    create_lot,
    create_model,
    create_model_payload,
    create_sale,
    create_season,
    model_lifecycle_payload,
    set_logical_clock,
    setup_in_season,
    unique_suffix,
    validate_error,
    validate_paginated,
    validate_success,
)

PLANNER = TEST_USERS["planner_admin_headers"]


def test_model_create_applies_coverage_and_firmware_defaults(api):
    """PRD 3.2: "Models also carry the warranty schedule that claims will later be
    judged against: `burner_coverage_years` defaulting to 10 years, `grate_coverage_years`
    defaulting to 5 years, `electronics_coverage_years` defaulting to 3 years, and
    `other_coverage_years` defaulting to 2 years, each measured from the sale date.
    Alongside them sits `parts_support_years`, defaulting to 7 years — the
    parts-availability obligation that survives discontinuation — and
    `current_firmware_version`, defaulting to "1.0.0", the firmware stamped onto newly
    paired connected devices."
    PRD 3.2: "A model is born `ACTIVE`"; "while a model has never been discontinued,
    both fields stay null."

    Design: Corner/entities/model_create_applies_coverage_and_firmware_defaults
    """
    resp = api.create_model(create_model_payload(), headers=PLANNER)
    data = validate_success(resp, 201)
    assert_grill_model(data)
    assert data["burner_coverage_years"] == 10
    assert data["grate_coverage_years"] == 5
    assert data["electronics_coverage_years"] == 3
    assert data["other_coverage_years"] == 2
    assert data["parts_support_years"] == 7
    assert data["current_firmware_version"] == "1.0.0"
    assert data["status"] == "ACTIVE"
    assert data["discontinued_at"] is None
    assert data["support_obligation_until"] is None


def test_model_lifecycle_parts_only_gate_and_retire(api):
    """PRD 3.2: "The parts-only rung is guarded by that obligation: marking parts-only
    requires the logical clock to be strictly later than `support_obligation_until` —
    the obligation must have fully expired — and attempting it earlier is
    `ERR_INVALID_STATE`. Retirement from `PARTS_ONLY` to `RETIRED` is unguarded."
    PRD 3.2: "Discontinuing moves either `ACTIVE` or `CLEARANCE_ELIGIBLE` to
    `DISCONTINUED`, stamping `discontinued_at` with the logical clock and computing
    `support_obligation_until` as `discontinued_at` plus the model's
    `parts_support_years` years"

    Design: Corner/state_machines/model_lifecycle_parts_only_gate_and_retire
    """
    set_logical_clock("2018-01-01T00:00:00Z")
    model = create_model(
        model_code="GX-LEG", model_family="GX", model_year=2017,
        base_price_cents=40000, demand_share_bp=1000,
    )
    disc = validate_success(
        api.model_lifecycle(model["id"], model_lifecycle_payload("DISCONTINUE"), headers=PLANNER), 200
    )
    assert disc["discontinued_at"] == "2018-01-01T00:00:00Z"
    assert disc["support_obligation_until"] == "2025-01-01T00:00:00Z", (
        f"obligation must be discontinued_at + 7 years, got {disc['support_obligation_until']}"
    )
    # 2020-06-01 is not strictly later than 2025-01-01: the obligation still runs.
    set_logical_clock("2020-06-01T00:00:00Z")
    early = api.model_lifecycle(model["id"], model_lifecycle_payload("MARK_PARTS_ONLY"), headers=PLANNER)
    validate_error(early, ApiErrorId.ERR_INVALID_STATE)
    # Past the obligation window the rung opens, and RETIRE closes the machine.
    set_logical_clock("2025-01-02T00:00:00Z")
    parts_only = validate_success(
        api.model_lifecycle(model["id"], model_lifecycle_payload("MARK_PARTS_ONLY"), headers=PLANNER), 200
    )
    assert parts_only["status"] == "PARTS_ONLY"
    retired = validate_success(
        api.model_lifecycle(model["id"], model_lifecycle_payload("RETIRE"), headers=PLANNER), 200
    )
    assert retired["status"] == "RETIRED"
    terminal = api.model_lifecycle(model["id"], model_lifecycle_payload("DISCONTINUE"), headers=PLANNER)
    validate_error(terminal, ApiErrorId.ERR_INVALID_STATE)


def test_lot_create_computes_forward_sizing_and_nulls_actual(api):
    """PRD 3.3: "if no such prior season exists, fall back to this season's
    `demand_forecast_units`; multiply that base by the growth multiplier of 11000 basis
    points — that is, 110 percent of the base, a 10 percent growth assumption — then
    by the model's `demand_share_bp` share, and floor to a whole unit."
    PRD 3.3: "Before the season reaches `IN_SEASON`, `recommended_build_actual_units`
    is null." and "Lots are born `BUILDING`"

    Design: Corner/entities/lot_create_computes_forward_sizing_and_nulls_actual
    """
    season = create_season()  # demand_forecast_units 1000
    model = create_model()    # demand_share_bp 5000
    resp = api.create_lot(season["id"], {"model_id": model["id"], "build_week": "2026-W06", "units_built": 10}, headers=PLANNER)
    lot = validate_success(resp, 201)
    assert_inventory_lot(lot)
    # floor(1000 x 11000/10000 x 5000/10000) = 550 via the forecast fallback.
    assert lot["recommended_build_forward_units"] == 550, (
        f"forward sizing must be 550 from the forecast fallback, got {lot['recommended_build_forward_units']}"
    )
    assert lot["recommended_build_actual_units"] is None
    assert lot["status"] == "BUILDING"


def test_build_sizing_actual_variant_diverges_from_forward(api):
    """PRD 3.3: "while the season is `IN_SEASON` or `CLEARANCE`, count the complete
    7-day weeks elapsed between `in_season_start` and the logical clock, floor that to
    a whole number, and never let it drop below 1; the recommendation is then the
    floor of the lot's `units_consumed` multiplied by 26 — the length of the in-season
    annualization window in weeks — divided by those elapsed weeks."

    Design: Corner/calculations/build_sizing_actual_variant_diverges_from_forward
    """
    bundle = setup_in_season(
        allocated_units=30, units_built=30, channel_type="DIRECT",
        in_season_clock="2026-03-15T00:00:00Z",
    )
    create_sale(
        bundle["season"]["id"], bundle["model"]["id"], bundle["channel"]["id"],
        quantity=20, proof_of_purchase_token=f"RCPT-{unique_suffix()}",
    )
    lots, _meta = validate_paginated(api.list_season_lots(bundle["season"]["id"], headers=PLANNER))
    lot = lots[0]
    assert lot["recommended_build_forward_units"] == 550, (
        f"forward variant frozen at creation: 550 expected, got {lot['recommended_build_forward_units']}"
    )
    # Clock 2026-03-15 is 14 days after in_season_start 2026-03-01 -> 2 elapsed weeks;
    # floor(20 consumed x 26 / 2) = 260.
    assert lot["recommended_build_actual_units"] == 260, (
        f"actual variant must annualize the run-rate to 260, got {lot['recommended_build_actual_units']}"
    )
    assert lot["recommended_build_forward_units"] != lot["recommended_build_actual_units"]


def test_lots_reachable_from_season_and_model(api):
    """PRD 2.8: "Several resources are addressed beneath a parent — lots beneath a
    season or a model, claims and devices beneath a sale."
    PRD 4 lists both `GET /grillops/seasons/{id}/lots` and `GET /grillops/models/{id}/lots`.

    Design: Corner/endpoints/lots_reachable_from_season_and_model
    """
    season = create_season()
    model = create_model()
    lot = create_lot(season["id"], model["id"], units_built=10)
    via_season, _m1 = validate_paginated(api.list_season_lots(season["id"], headers=PLANNER))
    via_model, _m2 = validate_paginated(api.list_model_lots(model["id"], headers=PLANNER))
    assert via_season[0]["id"] == lot["id"], "lot must be listed beneath its season"
    assert via_model[0]["id"] == lot["id"], "lot must be listed beneath its model"


def test_created_model_immediately_readable(api):
    """PRD 2.10: "The consistency model is immediate: every mutation triggered by a
    request — including cascades into other entities — is applied and visible within
    that same request's response."

    Design: Corner/consistency_model/created_model_immediately_readable
    """
    created = validate_success(api.create_model(create_model_payload(), headers=PLANNER), 201)
    read = validate_success(api.get_model(created["id"], headers=PLANNER), 200)
    assert read["version"] == created["version"], "no mutation may intervene between create and read"
    assert read["model_code"] == "GX-100"
    assert read["support_obligation_until"] is None
