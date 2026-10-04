"""Brewers: telemetry, descale/dormancy/warranty clocks, and subsidy snapshots."""
from test_helpers import (
    ADMIN,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_brewer,
    create_brand,
    create_brewer_model,
    create_household,
    create_variety,
    get_success_data,
    open_service_event,
    record_brews,
    register_brewer,
    resolve_event,
    set_clock,
    setup_household_with_brewer,
    validate_error,
)


def test_record_brews_with_unknown_variety_returns_not_found(api, admin_headers):
    """PRD §2.8: "The same discipline applies to foreign keys supplied in a
    request body — identifiers such as `brand_id`, `model_id`, `line_id`,
    `variety_id`, and each slot's `variety_id` must resolve to existing
    resources, and an unresolvable reference is likewise `ERR_NOT_FOUND`."

    Design: Corner/entities/record_brews_with_unknown_variety_returns_not_found
    """
    _, _, brewer = setup_household_with_brewer(size=1)

    resp = api.record_brews(
        brewer["id"], {"brews": 3, "variety_id": NON_EXISTENT_UUID}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    read_back = get_success_data(api.get_brewer(brewer["id"], admin_headers))
    assert read_back["brew_count"] == 0


def test_restrictive_firmware_blocks_unlicensed_pods(api):
    """PRD §3.5: "a brewer whose model is `RESTRICTIVE` refuses pods of any
    brand whose `kind` is `UNLICENSED_COMPATIBLE`, and recording such a brew is
    rejected with `ERR_POD_BLOCKED` (HTTP 422) — this is the program's
    technical countermeasure to unlicensed competition, while an `OPEN` brewer
    accepts any pod."

    Design: Corner/validations/restrictive_firmware_blocks_unlicensed_pods
    """
    unlicensed = create_brand(kind="UNLICENSED_COMPATIBLE", name="Pirate Pods")
    knockoff = create_variety(unlicensed["id"], name="Knockoff Dark",
                              roast_level="DARK")

    lock_model = create_brewer_model(model_code="K-LOCK",
                                     firmware_compat="RESTRICTIVE")
    open_model = create_brewer_model(model_code="K-OPEN", firmware_compat="OPEN")
    h1 = create_household(size=2, region="NW")
    h2 = create_household(size=2, region="NW")
    brewer_lock = register_brewer(h1["id"], lock_model["id"])
    brewer_open = register_brewer(h2["id"], open_model["id"])

    blocked = api.record_brews(
        brewer_lock["id"], {"brews": 5, "variety_id": knockoff["id"]}, ADMIN)
    validate_error(blocked, ApiErrorId.ERR_POD_BLOCKED)

    accepted = record_brews(brewer_open["id"], 5, knockoff["id"])
    assert accepted["brew_count"] == 5

    lock_after = get_success_data(api.get_brewer(brewer_lock["id"], ADMIN))
    assert lock_after["brew_count"] == 0


def test_descale_boundary_at_interval_minus_one_and_exact(api):
    """PRD §3.6: "`descale_overdue` is true once the number of brews since the
    last resolved descaling — `brew_count` minus `last_descaled_brew_count` —
    reaches the model's `descale_interval_brews`, and equality counts as
    overdue."

    Design: Difficulty/boundary_precision_check/descale_exact_interval_boundary
    """
    brand = create_brand(kind="PLATFORM_OWNED", name="Descale Beans")
    variety = create_variety(brand["id"], name="Daily Grind")
    _, _, brewer = setup_household_with_brewer(size=4, descale_interval_brews=200)

    after_199 = record_brews(brewer["id"], 199, variety["id"])
    assert after_199["brew_count"] == 199
    assert after_199["descale_overdue"] is False

    after_200 = record_brews(brewer["id"], 1, variety["id"])
    assert after_200["brew_count"] == 200
    assert after_200["descale_overdue"] is True


def test_descale_overdue_applies_the_085_factor(api, admin_headers):
    """PRD §3.5: "The descale factor is 0.85 whenever any `ACTIVE` brewer of
    the household currently has `descale_overdue` set, and 1.0 otherwise."
    PRD §3.6: "equality counts as overdue."

    Design: Difficulty/boundary_precision_check/descale_exact_interval_boundary
    """
    brand = create_brand(kind="PLATFORM_OWNED", name="Descale Beans 2")
    variety = create_variety(brand["id"], name="Daily Grind 2")
    household, _, brewer = setup_household_with_brewer(
        size=4, descale_interval_brews=200)

    before = get_success_data(api.get_household(household["id"], admin_headers))
    assert before["expected_monthly_pods"] == 120.00

    record_brews(brewer["id"], 200, variety["id"])

    after = get_success_data(api.get_household(household["id"], admin_headers))
    # 4 * 30 * 1.0 * 0.85 * 1.0 == 102.00
    assert after["expected_monthly_pods"] == 102.00


def test_warranty_expires_while_operational_stays_active(api, admin_headers):
    """PRD §3.6: "once the logical clock reaches `registered_at` plus the
    model's `warranty_months`, the brewer's `warranty_status` becomes
    `EXPIRED` — the exact anniversary expires it — and a dormant brewer keeps
    aging out of warranty regardless."
    PRD §3.6 describes warranty and operational as independent dimensions.

    Design: Difficulty/non_linear_state_machine/brewer_independent_dimensions
    """
    _, _, brewer = setup_household_with_brewer(
        size=2, warranty_months=1, descale_interval_brews=200)

    set_clock("2026-10-01T00:00:00Z")  # exactly registered_at + 1 month
    read_back = get_success_data(api.get_brewer(brewer["id"], admin_headers))
    assert read_back["warranty_status"] == "EXPIRED"
    assert read_back["operational"] == "ACTIVE"  # only 30 idle days


def test_dormancy_and_reactivation_do_not_touch_warranty(api, admin_headers):
    """PRD §3.6: "sixty or more days between `last_brew_at` and the logical
    clock flips an `ACTIVE` brewer to `DORMANT`, with exactly sixty days being
    the flip point"
    PRD §3.5: "If the brewer had drifted to `DORMANT`, the recording
    reactivates it to `ACTIVE`"
    PRD §3.6: "`EXPIRED` and `VOID` are both permanent."

    Design: Difficulty/non_linear_state_machine/brewer_independent_dimensions
    """
    brand = create_brand(kind="PLATFORM_OWNED", name="Platform Basics")
    variety = create_variety(brand["id"], name="Morning Cup", roast_level="LIGHT")
    _, _, brewer = setup_household_with_brewer(
        size=2, warranty_months=1, descale_interval_brews=200)

    set_clock("2026-10-31T00:00:00Z")  # exactly 60 idle days
    dormant = get_success_data(api.get_brewer(brewer["id"], admin_headers))
    assert dormant["operational"] == "DORMANT"
    assert dormant["warranty_status"] == "EXPIRED"

    revived = record_brews(brewer["id"], 5, variety["id"])
    assert revived["operational"] == "ACTIVE"
    assert revived["warranty_status"] == "EXPIRED"


def test_subsidy_snapshot_at_zero_installed_base(api):
    """PRD §3.5: "first the **current** global installed base is snapshotted,
    counting every brewer in any household whose `operational` state is
    `ACTIVE` or `DORMANT`; future sales are never projected."
    PRD §3.5: "Finally the model's `margin_cents` is derived as `msrp_cents`
    minus `unit_cost_cents` minus `subsidy_cents`."

    Design: Difficulty/combinatorial_formula/subsidy_snapshot_evaluation_order
    """
    model_a = create_brewer_model(model_code="K-ALPHA", msrp_cents=8000,
                                  unit_cost_cents=9000)
    # No brewers exist anywhere: the snapshot is 0.
    assert model_a["subsidy_cents"] == 0
    assert model_a["margin_cents"] == 8000 - 9000 - 0


def test_subsidy_snapshot_counts_current_installed_base(api):
    """PRD §3.5: "each installed brewer is expected to brew 40 pods per month
    at 18 cents of pod margin, half of which the program treats as recoverable,
    amortized across 24 months, which works out to exactly 15 cents per
    installed brewer."
    PRD §3.5: "Existing models are never re-snapshotted: two models registered
    before and after a wave of installed-base growth legitimately carry
    different subsidies, by design."

    Design: Difficulty/combinatorial_formula/subsidy_snapshot_evaluation_order
    """
    model_a = create_brewer_model(model_code="K-ALPHA-2", msrp_cents=8000,
                                  unit_cost_cents=9000)
    assert model_a["subsidy_cents"] == 0

    household = create_household(size=2, region="NW")
    register_brewer(household["id"], model_a["id"])
    register_brewer(household["id"], model_a["id"])

    model_b = create_brewer_model(model_code="K-BETA", msrp_cents=8000,
                                  unit_cost_cents=9000)
    # 2 installed brewers * exactly 15 cents recoverable each.
    assert model_b["subsidy_cents"] == 30
    assert model_b["margin_cents"] == 8000 - 9000 - 30


def test_register_then_replace_conserves_installed_base(api, admin_headers):
    """PRD §3.6: "Approving a `REPLACEMENT` event decommissions the machine:
    `operational` becomes `DECOMMISSIONED`, then the household's
    `installed_brewers` recomputes, and if that count has reached zero the
    household's `engagement` becomes `CHURNED` and its `expected_monthly_pods`
    collapses to 0.00."

    Design: Difficulty/compensating_invariant/installed_base_register_replace_conservation
    """
    household = create_household(size=4, region="NW")
    at_create = get_success_data(api.get_household(household["id"], admin_headers))
    assert at_create["installed_brewers"] == 0
    assert at_create["engagement"] == "CHURNED"
    assert at_create["expected_monthly_pods"] == 0.00

    model = create_brewer_model(model_code="K-CONS")
    brewer = register_brewer(household["id"], model["id"])

    event = open_service_event(brewer["id"], "REPLACEMENT", note="dead on arrival")
    resolved = resolve_event(event["id"], "APPROVED")
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolution"] == "APPROVED"

    brewer_after = get_success_data(api.get_brewer(brewer["id"], admin_headers))
    assert brewer_after["operational"] == "DECOMMISSIONED"

    after = get_success_data(api.get_household(household["id"], admin_headers))
    assert after["installed_brewers"] == 0
    assert after["engagement"] == "CHURNED"
    assert after["expected_monthly_pods"] == 0.00


def test_registration_raises_installed_base_and_projection(api, admin_headers):
    """PRD §3.5: "Registration stamps `registered_at` with the logical clock,
    sets `last_brew_at` to that same instant, zeroes `brew_count` and
    `last_descaled_brew_count`, and puts the brewer in `operational` `ACTIVE`
    with `warranty_status` `IN_WARRANTY`"
    PRD §3.5: "The household's `installed_brewers`, `engagement`, and
    `expected_monthly_pods` recompute on the spot."

    Design: Difficulty/compensating_invariant/installed_base_register_replace_conservation
    """
    household = create_household(size=4, region="NW")
    model = create_brewer_model(model_code="K-REG")
    brewer = register_brewer(household["id"], model["id"])
    assert_brewer(brewer)
    assert brewer["operational"] == "ACTIVE"
    assert brewer["warranty_status"] == "IN_WARRANTY"
    assert brewer["brew_count"] == 0
    assert brewer["last_descaled_brew_count"] == 0

    data = get_success_data(api.get_household(household["id"], admin_headers))
    assert data["installed_brewers"] == 1
    assert data["engagement"] == "ENGAGED"
    # 4 * 30 * 1.0 * 1.0 * 1.0 == 120.00
    assert data["expected_monthly_pods"] == 120.00
