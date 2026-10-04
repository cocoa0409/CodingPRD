"""Warranty economics: dual age bases, pinned rounding order, boundary bands."""
from test_helpers import (
    ApiErrorId,
    adjudicate_claim,
    create_account,
    create_battery_asset,
    create_center,
    create_certified_pack,
    create_claim,
    create_platform,
    create_tool,
    create_tool_asset,
    get_claim,
    make_service_agent_headers,
    set_clock,
    validate_error,
    validate_success,
)


def _setup_dual_basis_world():
    """Platform; CERTIFIED pack (20000, 720d, 90d); tool (30000, 360d, 60d);
    dual-capability center; PROFESSIONAL account holding a TOOL asset and a
    BATTERY asset, both manufactured 2026-01-01 and both paired 2026-03-01;
    claims filed at logical date 2026-04-15 and adjudicated. Returns the two
    adjudicated claims (tool_claim, battery_claim)."""
    set_clock("2026-09-01T00:00:00Z")
    pf = create_platform(code="MX18")
    pk = create_certified_pack(pf["id"], sku="P-48-11", replacement_price_cents=20000,
                               warranty_days=720, free_replacement_days=90)
    tm = create_tool(pf["id"], model_code="T-2804", trade="PLUMBING", category="PIPE_TOOL",
                     tier="PROFESSIONAL", avg_power_draw_w=500,
                     min_pack_generation=1, max_pack_generation=2,
                     replacement_price_cents=30000, warranty_days=360,
                     free_replacement_days=60, torque_min_nm=10, torque_max_nm=200)
    sc = create_center(code="SC-1", capabilities=["TOOL_REPAIR", "BATTERY_SERVICE"],
                       daily_capacity=10)
    ac = create_account(org_name="Acme Mechanical", tier="PROFESSIONAL")
    set_clock("2026-03-01T00:00:00Z")
    at = create_tool_asset(ac["id"], tm["id"], serial_number="SN-T-1",
                           manufactured_at="2026-01-01T00:00:00Z")
    ab = create_battery_asset(ac["id"], pk["id"], serial_number="SN-B-1",
                              manufactured_at="2026-01-01T00:00:00Z")
    set_clock("2026-04-15T00:00:00Z")
    ct = create_claim(at["id"], ac["id"], "TOOL_REPAIR", "2026-04-16", "NO_POWER")
    cb = create_claim(ab["id"], ac["id"], "BATTERY_REPLACEMENT", "2026-04-16", "NO_CHARGE")
    center = ct["service_center_id"]
    tool_claim = adjudicate_claim(ct["id"], center, "APPROVED")
    battery_claim = adjudicate_claim(cb["id"], center, "APPROVED")
    return tool_claim, battery_claim


def test_warranty_age_basis_tool_claim_uses_activation(api):
    """PRD §3.5: "The claim's `age_basis` is pinned by its `claim_type`:
    `TOOL_REPAIR` measures age by ACTIVATION from the asset's `first_paired_at`,
    while `BATTERY_REPLACEMENT` measures by MANUFACTURE from the asset's
    `manufactured_at`"
    PRD §3.5: "`FREE` when `age_days` is at most the subject's
    `free_replacement_days` — a claim filed on or before the final
    free-replacement day is free"

    Design: Difficulty/dual_variant_calc/warranty_age_basis_divergence_tool_vs_battery
    """
    tool_claim, _ = _setup_dual_basis_world()
    assert tool_claim["age_basis"] == "ACTIVATION"
    assert tool_claim["age_days"] == 45  # paired 2026-03-01 -> clock 2026-04-15
    assert tool_claim["coverage"] == "FREE"  # 45 <= free_replacement_days 60
    assert tool_claim["credit_cents"] == 30000  # full replacement price


def test_warranty_age_basis_battery_claim_uses_manufacture(api):
    """PRD §3.5: "`PRORATED` when `age_days` exceeds `free_replacement_days` but
    is at most the subject's `warranty_days`"
    PRD §3.5: "when `PRORATED`, the monthly rate is computed FIRST as
    `replacement_price_cents` divided by the number of 30-day warranty months
    (`warranty_days` divided by 30), rounded half up to whole cents, and THEN
    multiplied by the remaining full months — the whole-month floor of
    (`warranty_days` minus `age_days`) divided by 30"

    Design: Difficulty/dual_variant_calc/warranty_age_basis_divergence_tool_vs_battery
    """
    _, battery_claim = _setup_dual_basis_world()
    assert battery_claim["age_basis"] == "MANUFACTURE"
    assert battery_claim["age_days"] == 104  # manufactured 2026-01-01 -> 2026-04-15
    assert battery_claim["coverage"] == "PRORATED"  # 90 < 104 <= 720
    # rate = round_half_up(20000/24) = 833; remaining = floor(616/30) = 20
    assert battery_claim["credit_cents"] == 16660


def _setup_prorated_rounding_claim():
    """CERTIFIED pack (price 10001, 360d, 30d); battery asset manufactured
    2026-01-01; claim adjudicated at logical date 2026-03-16 (age 74)."""
    set_clock("2026-03-16T00:00:00Z")
    pf = create_platform(code="MX18")
    pk = create_certified_pack(pf["id"], sku="P-PR", replacement_price_cents=10001,
                               warranty_days=360, free_replacement_days=30)
    sc = create_center(code="SC-1", capabilities=["TOOL_REPAIR", "BATTERY_SERVICE"],
                       daily_capacity=10)
    ac = create_account(org_name="Acme Mechanical", tier="PROFESSIONAL")
    ab = create_battery_asset(ac["id"], pk["id"], serial_number="SN-PR-1",
                              manufactured_at="2026-01-01T00:00:00Z")
    cb = create_claim(ab["id"], ac["id"], "BATTERY_REPLACEMENT", "2026-03-16", "SWELL")
    return adjudicate_claim(cb["id"], cb["service_center_id"], "APPROVED")


def test_prorated_credit_rounds_monthly_rate_before_multiplying(api):
    """PRD §3.5: "when `PRORATED`, the monthly rate is computed FIRST as
    `replacement_price_cents` divided by the number of 30-day warranty months
    (`warranty_days` divided by 30), rounded half up to whole cents, and THEN
    multiplied by the remaining full months"

    Design: Difficulty/combinatorial_formula/prorated_credit_monthly_rate_rounded_before_multiply
    """
    claim = _setup_prorated_rounding_claim()
    assert claim["age_days"] == 74
    assert claim["coverage"] == "PRORATED"  # 30 < 74 <= 360
    # rate = round_half_up(10001/12) = 833; remaining = floor(286/30) = 9
    assert claim["credit_cents"] == 7497


def test_prorated_credit_rejects_round_last_alternative(api):
    """PRD §2.6: "Warranty prorated credit rounds the per-month rate FIRST —
    the monthly rate in whole cents, round half up to 0 decimal places — and
    only THEN multiplies that rounded rate by the number of remaining full
    months. Rounding only the final product is a different, non-conformant
    algorithm and yields different cents."

    Design: Difficulty/combinatorial_formula/prorated_credit_monthly_rate_rounded_before_multiply
    """
    claim = _setup_prorated_rounding_claim()
    # The round-only-the-final-product alternative yields
    # round_half_up(10001 * 286 / 360) = 7945; the pinned order yields 7497.
    assert claim["credit_cents"] == 833 * 9
    assert claim["credit_cents"] != 7945


def _setup_free_boundary():
    """CERTIFIED pack (20000, 720d, 90d); two battery assets manufactured
    2026-01-01. Returns (ac, a1, a2)."""
    set_clock()
    pf = create_platform(code="MX18")
    pk = create_certified_pack(pf["id"], sku="P-BD")
    create_center(code="SC-1", capabilities=["TOOL_REPAIR", "BATTERY_SERVICE"],
                  daily_capacity=10)
    ac = create_account(org_name="Acme Mechanical", tier="PROFESSIONAL")
    set_clock("2026-04-01T00:00:00Z")
    a1 = create_battery_asset(ac["id"], pk["id"], serial_number="SN-BD-1",
                              manufactured_at="2026-01-01T00:00:00Z")
    a2 = create_battery_asset(ac["id"], pk["id"], serial_number="SN-BD-2",
                              manufactured_at="2026-01-01T00:00:00Z")
    return ac, a1, a2


def test_warranty_free_boundary_age_90_is_free(api):
    """PRD §3.5: "Coverage bands are inclusive at the free boundary: `FREE`
    when `age_days` is at most the subject's `free_replacement_days` — a claim
    filed on or before the final free-replacement day is free"

    Design: Difficulty/boundary_precision_check/warranty_free_replacement_inclusive_day_boundary
    """
    ac, a1, a2 = _setup_free_boundary()
    ca = create_claim(a1["id"], ac["id"], "BATTERY_REPLACEMENT", "2026-04-01", "NO_CHARGE")
    adjudicated = adjudicate_claim(ca["id"], ca["service_center_id"], "APPROVED")
    assert adjudicated["age_days"] == 90  # 2026-01-01 -> 2026-04-01
    assert adjudicated["coverage"] == "FREE"  # 90 <= 90: inclusive boundary
    assert adjudicated["credit_cents"] == 20000


def test_warranty_free_boundary_age_91_is_prorated(api):
    """PRD §3.5: "`PRORATED` when `age_days` exceeds `free_replacement_days`
    but is at most the subject's `warranty_days`"

    Design: Difficulty/boundary_precision_check/warranty_free_replacement_inclusive_day_boundary
    """
    ac, a1, a2 = _setup_free_boundary()
    set_clock("2026-04-02T00:00:00Z")
    cb = create_claim(a2["id"], ac["id"], "BATTERY_REPLACEMENT", "2026-04-02", "NO_CHARGE")
    adjudicated = adjudicate_claim(cb["id"], cb["service_center_id"], "APPROVED")
    assert adjudicated["age_days"] == 91  # one day past the free boundary
    assert adjudicated["coverage"] == "PRORATED"
    # rate = round_half_up(20000/24) = 833; remaining = floor(629/30) = 20
    assert adjudicated["credit_cents"] == 16660


def test_warranty_age_at_exactly_warranty_days_is_prorated_zero(api):
    """PRD §3.5: "`PRORATED` when `age_days` exceeds `free_replacement_days`
    but is at most the subject's `warranty_days`; and `OUT_OF_WARRANTY` beyond
    `warranty_days`. An approval whose coverage computes to `OUT_OF_WARRANTY`
    is rejected with `ERR_WARRANTY_EXPIRED`."

    Design: Corner/calculations/warranty_age_at_exactly_warranty_days_is_prorated_zero
    """
    set_clock()
    pf = create_platform(code="MX18")
    pk = create_certified_pack(pf["id"], sku="P-WB", cell_format="C18650",
                               rated_capacity_wh=80, max_charge_rate_w=150,
                               replacement_price_cents=12000, warranty_days=360,
                               free_replacement_days=30)
    create_center(code="SC-A", capabilities=["BATTERY_SERVICE"], daily_capacity=5)
    ac = create_account(org_name="Paginators Inc")
    a1 = create_battery_asset(ac["id"], pk["id"], serial_number="SN-WB-1",
                              manufactured_at="2025-09-06T00:00:00Z")  # age 360
    a2 = create_battery_asset(ac["id"], pk["id"], serial_number="SN-WB-2",
                              manufactured_at="2025-09-05T00:00:00Z")  # age 361
    c1 = create_claim(a1["id"], ac["id"], "BATTERY_REPLACEMENT", "2026-09-01", "F1")
    c2 = create_claim(a2["id"], ac["id"], "BATTERY_REPLACEMENT", "2026-09-01", "F2")
    at_boundary = adjudicate_claim(c1["id"], c1["service_center_id"], "APPROVED")
    assert at_boundary["adjudication_status"] == "APPROVED"
    assert at_boundary["coverage"] == "PRORATED"  # 360 <= warranty_days 360
    assert at_boundary["credit_cents"] == 0  # floor(0/30) = 0 remaining months
    resp = api.adjudicate_warranty_claim(
        c2["id"], {"decision": "APPROVED"},
        make_service_agent_headers(c1["service_center_id"]),
    )
    validate_error(resp, ApiErrorId.ERR_WARRANTY_EXPIRED)
    assert get_claim(c2["id"])["adjudication_status"] == "SUBMITTED"
