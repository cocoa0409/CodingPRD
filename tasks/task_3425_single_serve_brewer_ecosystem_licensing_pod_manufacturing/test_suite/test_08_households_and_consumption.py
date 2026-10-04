"""Households, consumption records, and the two consumption projections."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    add_consumption_record,
    assert_consumption_record,
    create_brewer_model,
    create_household,
    get_success_data,
    register_brewer,
    set_clock,
    setup_household_with_brewer,
    validate_error,
    validate_success,
)


def test_household_create_initializes_computed_fields(api, admin_headers):
    """PRD §3.5: "A new household has no machines: its `installed_brewers` is
    0, its `engagement` is `CHURNED`, and both consumption projections,
    `trailing_avg_pods` and `expected_monthly_pods`, read 0.00."

    Design: Corner/entities/household_create_initializes_computed_fields
    """
    resp = api.create_household({"region": "NE", "size": 3}, admin_headers)
    data = validate_success(resp, 201)
    assert data["installed_brewers"] == 0
    assert data["engagement"] == "CHURNED"
    assert data["trailing_avg_pods"] == 0.00
    assert data["expected_monthly_pods"] == 0.00
    assert data["version"] == 1


def test_create_household_with_zero_size_rejected(api, admin_headers):
    """PRD §3.5: "A `PlatformAdmin` registers a household with a `region` code
    and a `size` of at least one resident."
    PRD §2.10: "numeric ranges hold (`pods_brewed` at least 0, `brews` between
    1 and 10000 inclusive, `unlicensed_share_pct` between 0 and 100 inclusive,
    `cup_score` between 0 and 100 inclusive, `facings` at least 1, household
    `size` at least 1)"

    Design: Corner/entities/create_household_with_zero_size_rejected
    """
    bad = api.create_household({"region": "NW", "size": 0}, admin_headers)
    validate_error(bad, ApiErrorId.ERR_INVALID_REQUEST)

    good = api.create_household({"region": "NW", "size": 1}, admin_headers)
    data = validate_success(good, 201)
    assert data["size"] == 1


def test_consumption_record_is_immutable_without_version(api):
    """PRD §2.5: "Two resources are immutable record types and carry only `id`
    and `created_at`: the quality audit and the consumption record. Both
    `updated_at` and `version` are **absent** from their representations — an
    audit or a consumption record is never modified after creation."

    Design: Corner/entities/consumption_record_is_immutable_without_version
    """
    household = create_household(size=2, region="NW")
    resp = api.create_consumption_record(
        household["id"], {"period": "2026-08", "pods_brewed": 100}, ADMIN)
    data = validate_success(resp, 201)
    assert_consumption_record(data)
    assert data["period"] == "2026-08"
    assert data["pods_brewed"] == 100
    assert data["household_id"] == household["id"]


def test_duplicate_consumption_period_rejected(api, admin_headers):
    """PRD §3.5: "each household may hold at most one record per period: a
    duplicate is `ERR_DUPLICATE_CONSUMPTION_PERIOD` (HTTP 409)."

    Design: Corner/validations/duplicate_consumption_period_rejected
    """
    household = create_household(size=2, region="NW")
    add_consumption_record(household["id"], "2026-08", 100)

    resp = api.create_consumption_record(
        household["id"], {"period": "2026-08", "pods_brewed": 150}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CONSUMPTION_PERIOD)

    rows = get_success_data(
        api.list_consumption_records(household["id"], admin_headers))
    assert len(rows) == 1
    assert rows[0]["pods_brewed"] == 100


def test_trailing_avg_normalizes_over_two_records(api, admin_headers):
    """PRD §3.5: "take the last three consumption records ordered by `period`
    descending, weight them 3, 2, and 1 with the most recent heaviest, and
    divide by the sum of the weights actually present — six when all three
    exist, three when two do, one when only one does — and round half-up to
    two decimals; a household with no records reads 0.00."

    Design: Corner/calculations/trailing_avg_normalizes_over_two_records
    """
    household = create_household(size=2, region="NW")
    add_consumption_record(household["id"], "2026-07", 100)
    add_consumption_record(household["id"], "2026-08", 300)

    data = get_success_data(api.get_household(household["id"], admin_headers))
    # (3*300 + 2*100) / (3+2) == 1100/5 == 220.00
    assert data["trailing_avg_pods"] == 220.00


def test_household_trailing_variant_replays_history(api, admin_headers):
    """PRD §3.5: "`trailing_avg_pods` replays the household's history: take
    the last three consumption records ordered by `period` descending, weight
    them 3, 2, and 1 with the most recent heaviest, and divide by the sum of
    the weights actually present"

    Design: Difficulty/dual_variant_calc/household_forward_vs_trailing_divergence
    """
    household = create_household(size=4, region="NW")
    model = create_brewer_model(model_code="K-MINI")
    brewer = register_brewer(household["id"], model["id"])
    add_consumption_record(household["id"], "2026-06", 90)
    add_consumption_record(household["id"], "2026-07", 150)
    add_consumption_record(household["id"], "2026-08", 240)

    data = get_success_data(api.get_household(household["id"], admin_headers))
    assert data["installed_brewers"] == 1
    assert data["engagement"] == "ENGAGED"
    # (3*240 + 2*150 + 1*90) / 6 == 1110/6 == 185.00
    assert data["trailing_avg_pods"] == 185.00
    assert brewer["operational"] == "ACTIVE"


def test_household_forward_variant_projects_from_posture(api, admin_headers):
    """PRD §3.5: "`expected_monthly_pods` is forward-looking and ignores
    consumption records entirely: start from the household's `size` times 30
    pods per person per month, then scale by three factors."
    PRD §3.5: "The two projections measure different things and never borrow
    each other's inputs."

    Design: Difficulty/dual_variant_calc/household_forward_vs_trailing_divergence
    """
    household = create_household(size=4, region="NW")
    model = create_brewer_model(model_code="K-MINI-2")
    brewer = register_brewer(household["id"], model["id"])
    add_consumption_record(household["id"], "2026-06", 90)
    add_consumption_record(household["id"], "2026-07", 150)
    add_consumption_record(household["id"], "2026-08", 240)

    data = get_success_data(api.get_household(household["id"], admin_headers))
    # 4 * 30 * 1.0 (ENGAGED) * 1.0 (no descale overdue) * 1.0 (in warranty)
    assert data["expected_monthly_pods"] == 120.00
    assert brewer["brew_count"] == 0
    # The two variants deliberately disagree on the same household.
    assert data["trailing_avg_pods"] == 185.00
    assert data["trailing_avg_pods"] != data["expected_monthly_pods"]


def test_warranty_factor_applies_when_all_brewers_unwarranted(api, admin_headers):
    """PRD §3.5: "The warranty factor is 0.90 when the household has at least
    one installed brewer and every non-decommissioned brewer is out of warranty
    — no longer `IN_WARRANTY` — and 1.0 otherwise."
    PRD §3.6: "once the logical clock reaches `registered_at` plus the model's
    `warranty_months`, the brewer's `warranty_status` becomes `EXPIRED` — the
    exact anniversary expires it"

    Design: Corner/calculations/warranty_factor_applies_when_all_brewers_unwarranted
    """
    household, _, brewer = setup_household_with_brewer(
        size=4, warranty_months=1, descale_interval_brews=200)

    set_clock("2026-10-01T00:00:00Z")  # exactly registered_at + 1 month
    brewer_after = get_success_data(api.get_brewer(brewer["id"], admin_headers))
    assert brewer_after["warranty_status"] == "EXPIRED"
    assert brewer_after["operational"] == "ACTIVE"  # 30 idle days < 60

    data = get_success_data(api.get_household(household["id"], admin_headers))
    assert data["engagement"] == "ENGAGED"
    # 4 * 30 * 1.0 * 1.0 * 0.90 == 108.00
    assert data["expected_monthly_pods"] == 108.00


def test_lapsed_engagement_quarters_the_forward_model(api, admin_headers):
    """PRD §3.6: "sixty or more days between `last_brew_at` and the logical
    clock flips an `ACTIVE` brewer to `DORMANT`, with exactly sixty days being
    the flip point"
    PRD §3.5: "The engagement factor is 1.0 for an `ENGAGED` household, 0.4
    for a `LAPSED` one, and 0.0 for a `CHURNED` one."

    Design: Corner/calculations/lapsed_engagement_quarters_the_forward_model
    """
    household, _, brewer = setup_household_with_brewer(
        size=4, warranty_months=12, descale_interval_brews=200)

    set_clock("2026-10-31T00:00:00Z")  # exactly 60 idle days
    brewer_after = get_success_data(api.get_brewer(brewer["id"], admin_headers))
    assert brewer_after["operational"] == "DORMANT"

    data = get_success_data(api.get_household(household["id"], admin_headers))
    assert data["engagement"] == "LAPSED"
    # 4 * 30 * 0.4 == 48.00
    assert data["expected_monthly_pods"] == 48.00
