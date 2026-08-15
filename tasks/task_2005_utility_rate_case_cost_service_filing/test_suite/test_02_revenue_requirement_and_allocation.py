"""Revenue-requirement variants, class cost allocation, and tiered present
revenue (PRD §3.7, §3.8)."""
import pytest

from test_helpers import (
    add_class,
    add_entry,
    add_rate_base_item,
    add_res_class,
    add_com_class,
    api_client,
    create_case,
    get_case,
    get_class,
    setup_filed_case,
    submit_entry,
    validate_success,
    TEST_USERS,
)

UF = TEST_USERS["utility_filer_alice"]
STAFF = TEST_USERS["commission_staff"]
ALJ = TEST_USERS["alj"]

EDGE_TIERS = [
    {"up_to_kwh": 300, "rate_mills": 700},
    {"up_to_kwh": 600, "rate_mills": 900},
    {"up_to_kwh": None, "rate_mills": 1100},
]


def _line_for_class(lines, class_code, class_id):
    for line in lines:
        if line.get("class_code") == class_code or line.get("customer_class_id") == class_id:
            return line
    pytest.fail(f"no cost-allocation line identifies class {class_code}/{class_id}: {lines}")


def _line_numbers(line):
    return {v for v in line.values() if isinstance(v, int)}


# ─── Difficulty: dual_variant_calc / revenue_requirement ─────────────────────

def _setup_variant_case():
    """Canonical FILED case with RB1 AUDITED and RB2 still SUBMITTED."""
    s = setup_filed_case()
    validate_success(api_client.audit_rate_base_item(
        s.rb1["id"], {"outcome": "AUDIT_PASS"}, STAFF), 200)
    return s


def test_revenue_requirement_as_filed_uses_submitted_and_audited(api):
    """PRD §3.8: "The as-filed variant — the filing-time view used by
    submit-filing validation — includes RateBaseItems in `SUBMITTED` or
    `AUDITED`." and "third compute the return component as the rate-base total
    multiplied by `return_on_rate_base_bp` and divided by ten thousand, rounded
    half up to integer cents — the return is rounded before addition; fourth,
    the revenue requirement is the cost of service plus the rounded return."

    Design: Difficulty/dual_variant_calc/revenue_requirement_as_filed_vs_as_audited
    """
    s = _setup_variant_case()
    data = validate_success(api.get_revenue_requirement(
        s.case["id"], STAFF, params={"variant": "as_filed"}), 200)
    assert data["variant"] == "as_filed"
    assert data["rate_base_cents"] == 3300000000, "RB1 AUDITED 2.4e9 + RB2 SUBMITTED 0.9e9"
    assert data["cost_of_service_cents"] == 1650000000
    assert data["return_cents"] == 247500000, "round_half_up(3.3e9 * 750 / 10000)"
    assert data["revenue_requirement_cents"] == 1897500000


def test_revenue_requirement_as_audited_excludes_submitted(api):
    """PRD §3.8: "The as-audited variant — the post-audit view used at order
    drafting — includes RateBaseItems in `AUDITED` only, excluding `SUBMITTED`
    and `EXCEPTION` items."

    Design: Difficulty/dual_variant_calc/revenue_requirement_as_filed_vs_as_audited
    """
    s = _setup_variant_case()
    filed = validate_success(api.get_revenue_requirement(
        s.case["id"], STAFF, params={"variant": "as_filed"}), 200)
    audited = validate_success(api.get_revenue_requirement(
        s.case["id"], STAFF, params={"variant": "as_audited"}), 200)
    assert audited["variant"] == "as_audited"
    assert audited["rate_base_cents"] == 2400000000, "RB2's SUBMITTED status excluded"
    assert audited["cost_of_service_cents"] == 1650000000
    assert audited["return_cents"] == 180000000
    assert audited["revenue_requirement_cents"] == 1830000000
    delta = filed["revenue_requirement_cents"] - audited["revenue_requirement_cents"]
    assert delta == 67500000, (
        "delta is caused solely by RB2's 900,000,000 net rate base leaving the "
        "input set: round(900,000,000 * 0.075) = 67,500,000"
    )


# ─── Difficulty: dual_variant_calc / class_cost_allocation ───────────────────

def test_class_allocation_coincident_peak_components(api):
    """PRD §3.7: "The demand share depends on the case's `allocation_method`:
    under `COINCIDENT_PEAK` the share is the class's `coincident_peak_kw` over
    the sum of `coincident_peak_kw` across all classes" and "The chosen class's
    `allocated_cost_cents` absorbs the residual; every other class's
    `allocated_cost_cents` equals its pre-residual sum."

    Design: Difficulty/dual_variant_calc/class_allocation_coincident_peak_vs_energy_average
    """
    s = setup_filed_case(classes="both")
    data = validate_success(api.get_cost_allocation(
        s.case["id"], STAFF, params={"method": "COINCIDENT_PEAK"}), 200)
    assert data["method"] == "COINCIDENT_PEAK"
    assert data["cost_of_service_cents"] == 1650000000
    assert data["residual_cents"] == 0
    # Per-class allocated cost is pinned on the class entity (PRD §3.7):
    # RES: 742,500,000 + 275,000,000 + 225,000,000; COM: 247,500,000 + 137,500,000 + 22,500,000.
    res_cls = get_class(s.cls_res["id"])
    com_cls = get_class(s.cls_com["id"])
    assert res_cls["allocated_cost_cents"] == 1242500000
    assert com_cls["allocated_cost_cents"] == 407500000
    line_res = _line_for_class(data["lines"], "RESIDENTIAL", s.cls_res["id"])
    line_com = _line_for_class(data["lines"], "COMMERCIAL", s.cls_com["id"])
    assert 1242500000 in _line_numbers(line_res), "RES line carries its final allocated cost"
    assert 407500000 in _line_numbers(line_com), "COM line carries its final allocated cost"


def test_class_allocation_energy_average_override_moves_demand_share(api):
    """PRD §3.7: "under `ENERGY_AVERAGE` the share is the class's `annual_kwh`
    over the sum of `annual_kwh` across all classes."
    PRD §3.8: "The computed read for cost allocation accepts an optional
    `method` parameter (defaulting to the case's `allocation_method`, so an
    `ENERGY_AVERAGE` override may be requested on a `COINCIDENT_PEAK` case and
    vice versa)"

    Design: Difficulty/dual_variant_calc/class_allocation_coincident_peak_vs_energy_average
    """
    s = setup_filed_case(classes="both")
    data = validate_success(api.get_cost_allocation(
        s.case["id"], STAFF, params={"method": "ENERGY_AVERAGE"}), 200)
    assert data["method"] == "ENERGY_AVERAGE"
    assert data["cost_of_service_cents"] == 1650000000
    assert data["residual_cents"] == 0
    # Demand component switches to annual-kwh share: RES 660,000,000 (2/3),
    # COM 330,000,000 (1/3); energy/customer components are method-independent.
    line_res = _line_for_class(data["lines"], "RESIDENTIAL", s.cls_res["id"])
    line_com = _line_for_class(data["lines"], "COMMERCIAL", s.cls_com["id"])
    nums_res = _line_numbers(line_res)
    nums_com = _line_numbers(line_com)
    assert 660000000 in nums_res, "RES demand component by annual-kwh share"
    assert 275000000 in nums_res and 225000000 in nums_res, (
        "energy and customer components are identical across methods"
    )
    assert 1160000000 in nums_res, "RES final allocated cost under ENERGY_AVERAGE"
    assert 330000000 in nums_com
    assert 137500000 in nums_com and 22500000 in nums_com
    assert 490000000 in nums_com, "COM final allocated cost under ENERGY_AVERAGE"
    assert 1242500000 not in nums_res, "the COINCIDENT_PEAK result must not leak in"


# ─── Difficulty: combinatorial_formula / present_revenue ─────────────────────

def _setup_four_class_draft():
    case = create_case()
    cls_res = add_res_class(case["id"])
    cls_com = add_com_class(case["id"])
    cls_edge = add_class(case["id"], class_code="EDGE", customer_count=1000,
                         monthly_kwh_per_customer=300, annual_kwh=3600000,
                         coincident_peak_kw=3000, average_demand_kw=2000)
    cls_edge2 = add_class(case["id"], class_code="EDGE2", customer_count=1000,
                          monthly_kwh_per_customer=600, annual_kwh=7200000,
                          coincident_peak_kw=6000, average_demand_kw=4000)
    return case, cls_res, cls_com, cls_edge, cls_edge2


def test_present_revenue_straddle_and_case_total(api):
    """PRD §3.7: "A class's `present_revenue_cents` is twelve times
    `customer_count`, multiplied by the sum of `present_customer_charge_cents`
    and the tiered-marginal energy charge for `monthly_kwh_per_customer` under
    `present_tiers`."

    Design: Difficulty/combinatorial_formula/present_revenue_tiered_straddle
    """
    case, cls_res, cls_com, _e, _e2 = _setup_four_class_draft()
    res_cls = get_class(cls_res["id"])
    com_cls = get_class(cls_com["id"])
    assert res_cls["present_revenue_cents"] == 1128000000, (
        "500 kwh straddles the 300-kwh boundary: 12*20000*(800 + 300*7 + 200*9)"
    )
    assert com_cls["present_revenue_cents"] == 612000000, (
        "12*2000*(2500 + 1000*8 + 1500*10)"
    )
    case_after = get_case(case["id"])
    assert case_after["present_revenue_total_cents"] == 1842000000, (
        "1,128,000,000 + 612,000,000 + 34,800,000 + 67,200,000 over the four classes"
    )


def test_present_revenue_exact_tier_boundaries(api):
    """PRD §3.7: "Each tier's width is: for the terminal null tier, the usage
    minus the floor; for any other tier, the larger of zero and the smaller of
    the usage and that tier's `up_to_kwh`, minus the floor." and "After each
    non-terminal tier, the floor advances to that tier's `up_to_kwh`, and the
    walk stops once the floor reaches the usage."

    Design: Difficulty/combinatorial_formula/present_revenue_tiered_straddle
    """
    _case, _r, _c, cls_edge, cls_edge2 = _setup_four_class_draft()
    edge = get_class(cls_edge["id"])
    edge2 = get_class(cls_edge2["id"])
    assert edge["present_revenue_cents"] == 34800000, (
        "at exactly 300 kwh tier 1 fills completely, zero spills into tier 2: "
        "12*1000*(800 + 300*7 + 0)"
    )
    assert edge2["present_revenue_cents"] == 67200000, (
        "at exactly 600 kwh tiers 1+2 fill completely, zero spills into tier 3: "
        "12*1000*(800 + 300*7 + 300*9 + 0)"
    )


# ─── Corner: calculations ────────────────────────────────────────────────────

def test_cost_of_service_excludes_unlocked_entries(api):
    """PRD §3.7: "The cost-of-service total is the sum of `adjusted_amount_cents`
    over the case's TestYearEntries in `LOCKED` status across the `O_AND_M`,
    `DEPRECIATION`, and `TAXES` categories — `DRAFT` and `SUBMITTED` entries are
    excluded."

    Design: Corner/calculations/cost_of_service_excludes_unlocked_entries
    """
    case = create_case()
    e1 = add_entry(case["id"], "900", "O_AND_M", 1000000000)
    submit_entry(e1["id"])
    rb1 = add_rate_base_item(case["id"])
    data = validate_success(api.get_revenue_requirement(case["id"], STAFF), 200)
    assert data["cost_of_service_cents"] == 0, "SUBMITTED entry excluded; only LOCKED count"
    assert data["rate_base_cents"] == 2400000000, "SUBMITTED item included in as_filed"
    assert data["return_cents"] == 180000000, "round_half_up(2,400,000,000 * 750 / 10000)"
    assert data["revenue_requirement_cents"] == 180000000
    assert data["variant"] == "as_filed"


def test_revenue_requirement_default_variant_is_as_filed(api):
    """PRD §3.8: "The computed read for revenue requirement accepts an optional
    `variant` parameter (default `as_filed`) and returns `variant`,
    `rate_base_cents`, `cost_of_service_cents`, `return_cents`, and
    `revenue_requirement_cents`."

    Design: Corner/calculations/revenue_requirement_default_variant_is_as_filed
    """
    s = _setup_variant_case()
    default = validate_success(api.get_revenue_requirement(s.case["id"], ALJ), 200)
    explicit = validate_success(api.get_revenue_requirement(
        s.case["id"], ALJ, params={"variant": "as_filed"}), 200)
    assert default["variant"] == "as_filed"
    assert default["revenue_requirement_cents"] == 1897500000
    for field in ("variant", "rate_base_cents", "cost_of_service_cents",
                  "return_cents", "revenue_requirement_cents"):
        assert default[field] == explicit[field], f"default response matches explicit as_filed on {field}"
    assert default["revenue_requirement_cents"] != 1830000000, (
        "as_audited would differ (RB2 SUBMITTED excluded there)"
    )
