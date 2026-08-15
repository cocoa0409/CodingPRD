"""Final-order cascade, tariff windows and price-integrity guards, bill impact,
and the tariff-supersede sweep (PRD §3.6, §3.7, §3.8)."""
from test_helpers import (
    ApiErrorId,
    accept_case,
    add_class,
    add_com_tariff_2027,
    add_entry,
    add_rate_base_item,
    add_regulatory_asset,
    add_tariff,
    create_case,
    create_regulatory_asset_payload,
    create_tariff_rate_payload,
    file_case,
    get_asset,
    get_case,
    get_class,
    get_proposal,
    get_tariff,
    issue_order,
    open_discovery,
    setup_decided_with_tariffs_and_asset,
    setup_discovery_case,
    submit_and_lock_entry,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

UF = TEST_USERS["utility_filer_alice"]
STAFF = TEST_USERS["commission_staff"]
ALJ = TEST_USERS["alj"]
IR = TEST_USERS["intervenor_rep"]


# ─── Difficulty: transitive_cascade / issue_order_tariff_ledger ──────────────

def test_issue_order_tariff_states_and_proposal_adoption(api):
    """PRD §3.6: "Second, each listed tariff moves from `PROPOSED` to `APPROVED`,
    and each unlisted `PROPOSED` tariff moves to `REJECTED`." and "First, the
    case's `authorized_revenue_requirement_cents` is set from the `RECOMMENDED`
    proposal's `proposed_revenue_requirement_cents` (if several proposals are
    `RECOMMENDED`, the one with the largest `round_number`; a tie is impossible),
    and that proposal moves from `RECOMMENDED` to `ADOPTED`."

    Design: Difficulty/transitive_cascade/issue_order_tariff_ledger_cascade
    """
    s = setup_decided_with_tariffs_and_asset(extra_com_tariff_2029=True)
    assert s.case["status"] == "DECIDED"
    assert s.case["authorized_revenue_requirement_cents"] == 1850000000, (
        "adopted from the RECOMMENDED proposal"
    )
    assert get_tariff(s.t_res["id"])["status"] == "APPROVED"
    assert get_tariff(s.t_com["id"])["status"] == "APPROVED"
    assert get_tariff(s.t_x["id"])["status"] == "REJECTED", "unlisted PROPOSED tariff"
    assert get_proposal(s.sp1["id"])["status"] == "ADOPTED"
    assert get_asset(s.ra1["id"])["status"] == "APPROVED_FOR_AMORTIZATION"
    entries, meta = validate_paginated(api.list_amortization_entries(
        UF, params={"regulatory_asset_id": s.ra1["id"]}))
    assert meta["total_count"] == 4
    assert all(e["status"] == "PENDING" for e in entries)


def test_issue_order_class_revenue_and_case_aggregate(api):
    """PRD §3.6: "Third, each tariff approval recomputes its class's
    `approved_revenue_cents` from the approved tariff's `proposed_revenue_cents`.
    Fourth, each class recompute refreshes the case's
    `revenue_at_approved_rates_cents` as the sum of `approved_revenue_cents` over
    all classes."

    Design: Difficulty/transitive_cascade/issue_order_tariff_ledger_cascade
    """
    s = setup_decided_with_tariffs_and_asset(extra_com_tariff_2029=True)
    assert get_class(s.cls_res["id"])["approved_revenue_cents"] == 1212000000
    assert get_class(s.cls_com["id"])["approved_revenue_cents"] == 695088000
    case = get_case(s.case["id"])
    assert case["revenue_at_approved_rates_cents"] == 1907088000, (
        "1,212,000,000 + 695,088,000; the REJECTED 666,000,000 tariff "
        "contributes nothing"
    )


# ─── Corner: issue-order id validation ───────────────────────────────────────

def test_issue_order_foreign_tariff_and_asset_rejected(api):
    """PRD §3.6: "Ids are validated in a pinned order: tariff ids before asset
    ids. Every id in `approved_tariff_ids` must reference a TariffRate of this
    case in `PROPOSED` — otherwise `ERR_INVALID_TARIFF_STATE`. Every id in
    `approved_asset_ids` must reference a RegulatoryAsset of this case in
    `DEFERRED` — otherwise `ERR_INVALID_ASSET_STATE`."

    Design: Corner/state_machines/issue_order_foreign_tariff_and_asset_rejected
    """
    # Case 1: canonical, ORDER_PENDING, own PROPOSED tariff t1 on RESIDENTIAL.
    s1 = setup_decided_with_tariffs_and_asset(
        num_intervenors=1, with_com_tariff=False, classes="res",
        with_asset=False, issue=False)
    t1 = s1.t_res
    # Case 2: revenue-neutral mini-case in DISCOVERY with its own class,
    # PROPOSED tariff t2, and DEFERRED asset a2x.
    case2 = create_case(case_number="UR-2026-999", utility_name="Other State Gas",
                        return_on_rate_base_bp=800,
                        proposed_revenue_requirement_cents=58000000,
                        allocation_method="ENERGY_AVERAGE")
    e2x = add_entry(case2["id"], "900", "O_AND_M", 50000000)
    submit_and_lock_entry(e2x["id"])
    add_rate_base_item(case2["id"], label="Small plant",
                       plant_in_service_cents=100000000,
                       accumulated_depreciation_cents=0,
                       working_capital_cents=0,
                       accumulated_deferred_taxes_cents=0)
    a2x = add_regulatory_asset(case2["id"], asset_name="Case2 deferral",
                               principal_cents=1000000,
                               incurrence_start="2024-01-01T00:00:00Z",
                               incurrence_end="2024-06-30T00:00:00Z",
                               amortization_months=2)
    cls2 = add_class(case2["id"], class_code="GENERAL", customer_count=10000,
                     monthly_kwh_per_customer=100, annual_kwh=12000000,
                     coincident_peak_kw=10000, average_demand_kw=5000,
                     present_customer_charge_cents=100,
                     present_tiers=[{"up_to_kwh": None, "rate_mills": 500}])
    file_case(case2["id"])
    accept_case(case2["id"])
    open_discovery(case2["id"])
    t2 = add_tariff(case2["id"], cls2["id"], label="GENERAL flat 2027",
                    proposed_customer_charge_cents=100,
                    proposed_tiers=[{"up_to_kwh": None, "rate_mills": 500}])

    res1 = api.issue_order(s1.case["id"],
                           {"approved_tariff_ids": [t2["id"]], "approved_asset_ids": []},
                           ALJ)
    validate_error(res1, ApiErrorId.ERR_INVALID_TARIFF_STATE, expected_status=409)
    res2 = api.issue_order(s1.case["id"],
                           {"approved_tariff_ids": [t1["id"]],
                            "approved_asset_ids": [a2x["id"]]},
                           ALJ)
    validate_error(res2, ApiErrorId.ERR_INVALID_ASSET_STATE, expected_status=409)
    assert get_case(s1.case["id"])["status"] == "ORDER_PENDING"
    final = validate_success(api.issue_order(
        s1.case["id"], {"approved_tariff_ids": [t1["id"]], "approved_asset_ids": []},
        ALJ), 200)
    assert final["status"] == "DECIDED"
    assert get_tariff(t2["id"])["status"] == "PROPOSED", "case 2 tariff untouched"
    assert get_asset(a2x["id"])["status"] == "DEFERRED", "case 2 asset untouched"


def test_implement_rates_requires_class_coverage(api):
    """PRD §3.6: "Rate implementation, performed by the utility while the case is
    `DECIDED`, requires every CustomerClass of the case to have at least one
    tariff in `APPROVED` — otherwise `ERR_CLASS_TARIFF_MISSING`."

    Design: Corner/state_machines/implement_rates_requires_class_coverage
    """
    s = setup_decided_with_tariffs_and_asset(
        num_intervenors=1, with_com_tariff=True, classes="both",
        with_asset=False, issue=False)
    decided = issue_order(s.case["id"], [s.t_res["id"]], [])
    assert decided["status"] == "DECIDED", "order issued approving only the RES tariff"
    assert get_tariff(s.t_com["id"])["status"] == "REJECTED", "unlisted at issue-order"
    res = api.implement_rates(s.case["id"], UF)
    validate_error(res, ApiErrorId.ERR_CLASS_TARIFF_MISSING, expected_status=409)
    assert get_case(s.case["id"])["status"] == "DECIDED", "case unchanged"


# ─── Difficulty: resource_temporal_overlap / tariff windows ──────────────────

def test_tariff_windows_half_open_adjacency_allowed(api):
    """PRD §3.7: "The window must not overlap another non-`REJECTED` tariff of
    the same class under half-open semantics — adjacency is allowed and a null
    end is infinity; an overlap is `ERR_TARIFF_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/tariff_windows_half_open_adjacency_allowed_overlap_rejected
    """
    s = setup_discovery_case(classes="com")
    t1 = add_com_tariff_2027(s.case["id"], s.cls_com["id"], label="COM 2027")
    t2 = add_com_tariff_2027(
        s.case["id"], s.cls_com["id"], label="COM 2028",
        effective_start="2028-01-01T00:00:00Z", effective_end="2029-01-01T00:00:00Z")
    assert t1["status"] == "PROPOSED" and t2["status"] == "PROPOSED", (
        "touching endpoints [2028-01-01) == [start) are disjoint under half-open "
        "semantics — both created"
    )


def test_tariff_window_interior_overlap_rejected(api):
    """PRD §3.7: "The window must not overlap another non-`REJECTED` tariff of
    the same class under half-open semantics — adjacency is allowed and a null
    end is infinity; an overlap is `ERR_TARIFF_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/tariff_windows_half_open_adjacency_allowed_overlap_rejected
    """
    s = setup_discovery_case(classes="com")
    t1 = add_com_tariff_2027(s.case["id"], s.cls_com["id"], label="COM 2027")
    t2 = add_com_tariff_2027(
        s.case["id"], s.cls_com["id"], label="COM 2028",
        effective_start="2028-01-01T00:00:00Z", effective_end="2029-01-01T00:00:00Z")
    res = api.create_tariff_rate(
        create_tariff_rate_payload(
            s.case["id"], s.cls_com["id"], label="COM straddler",
            proposed_customer_charge_cents=1462,
            proposed_tiers=[{"up_to_kwh": None, "rate_mills": 1100}],
            effective_start="2027-06-01T00:00:00Z",
            effective_end="2028-06-01T00:00:00Z"),
        UF)
    validate_error(res, ApiErrorId.ERR_TARIFF_WINDOW_OVERLAP, expected_status=409)
    data, meta = validate_paginated(api.list_tariff_rates(
        UF, params={"rate_case_id": s.case["id"], "status": "PROPOSED"}))
    assert meta["total_count"] == 2
    assert {t["id"] for t in data} == {t1["id"], t2["id"]}


# ─── Difficulty: resource_temporal_overlap / deferral closed interval ────────

def test_deferral_outside_test_year_accepted(api):
    """PRD §3.6: "the window must not intersect the case's test year — a single
    shared day counts as intersection, otherwise
    `ERR_DEFERRAL_OVERLAPS_TEST_YEAR`" and "At creation the server computes
    `monthly_base_cents` as the floor of `principal_cents` divided by
    `amortization_months`, and `final_month_cents` as `principal_cents` minus
    `monthly_base_cents` multiplied by one less than `amortization_months`".

    Design: Difficulty/resource_temporal_overlap/deferral_incurrence_closed_interval_touch_is_conflict
    """
    case = create_case()
    asset = validate_success(api.create_regulatory_asset(
        create_regulatory_asset_payload(case["id"]), UF), 201)
    assert asset["monthly_base_cents"] == 2500000, "floor(10,000,001 / 4)"
    assert asset["final_month_cents"] == 2500001, "10,000,001 - 2,500,000*3"
    assert asset["status"] == "DEFERRED"


def test_deferral_touching_test_year_by_one_day_rejected(api):
    """PRD §3.6: "the window must not intersect the case's test year — a single
    shared day counts as intersection, otherwise
    `ERR_DEFERRAL_OVERLAPS_TEST_YEAR`"

    Design: Difficulty/resource_temporal_overlap/deferral_incurrence_closed_interval_touch_is_conflict
    """
    case = create_case()
    res = api.create_regulatory_asset(
        create_regulatory_asset_payload(
            case["id"], asset_name="Winter storm Uri deferral",
            principal_cents=5000000,
            incurrence_start="2025-12-31T00:00:00Z",
            incurrence_end="2026-01-15T00:00:00Z",
            amortization_months=5),
        UF)
    validate_error(res, ApiErrorId.ERR_DEFERRAL_OVERLAPS_TEST_YEAR, expected_status=409)


# ─── Difficulty: boundary_precision / gradualism cap ─────────────────────────

def test_gradualism_cap_exact_boundary_passes(api):
    """PRD §3.7: "The tariff is rejected with `ERR_GRADUALISM_CAP_EXCEEDED` only
    when the class increase is strictly greater than the cap; an increase exactly
    equal to the cap passes."

    Design: Difficulty/boundary_precision_check/gradualism_cap_exact_bp_boundary
    """
    s = setup_discovery_case(classes="both")
    t_ok = validate_success(api.create_tariff_rate(
        create_tariff_rate_payload(
            s.case["id"], s.cls_com["id"], label="COM at cap",
            proposed_customer_charge_cents=1462,
            proposed_tiers=[{"up_to_kwh": None, "rate_mills": 1100}]),
        UF), 201)
    assert t_ok["proposed_revenue_cents"] == 695088000, (
        "12*2000*(1462 + 2500*1100/100)"
    )
    # system avg = round(10000*(1,897,500,000-1,740,000,000)/1,740,000,000) = 905;
    # cap = round(1.5*905) = 1358; class increase = round(10000*83,088,000/612,000,000)
    # = 1358 == cap -> passes because the rule is strictly-greater.
    assert t_ok["status"] == "PROPOSED"


def test_gradualism_cap_one_bp_over_rejected(api):
    """PRD §3.7: "Otherwise the cap in basis points is the round-half-up of one
    and a half times the system-average increase, and the class increase in basis
    points is the round-half-up of ten thousand times the tariff's
    `proposed_revenue_cents` minus the class's `present_revenue_cents`, divided by
    the class's `present_revenue_cents`. The tariff is rejected with
    `ERR_GRADUALISM_CAP_EXCEEDED` only when the class increase is strictly greater
    than the cap"

    Design: Difficulty/boundary_precision_check/gradualism_cap_exact_bp_boundary
    """
    s = setup_discovery_case(classes="both")
    validate_success(api.create_tariff_rate(
        create_tariff_rate_payload(
            s.case["id"], s.cls_com["id"], label="COM at cap",
            proposed_customer_charge_cents=1462,
            proposed_tiers=[{"up_to_kwh": None, "rate_mills": 1100}]),
        UF), 201)
    res = api.create_tariff_rate(
        create_tariff_rate_payload(
            s.case["id"], s.cls_com["id"], label="COM 1bp over cap",
            proposed_customer_charge_cents=1465,
            proposed_tiers=[{"up_to_kwh": None, "rate_mills": 1100}],
            effective_start="2028-01-01T00:00:00Z",
            effective_end="2029-01-01T00:00:00Z"),
        UF)
    validate_error(res, ApiErrorId.ERR_GRADUALISM_CAP_EXCEEDED, expected_status=422)
    # 695,160,000 -> round(10000*83,160,000/612,000,000) = 1359 > 1358; the
    # adjacent [2028,2029) window isolates the cap as the sole failure.
    data, meta = validate_paginated(api.list_tariff_rates(
        UF, params={"rate_case_id": s.case["id"]}))
    assert meta["total_count"] == 1, "only the passing tariff persisted"


def test_customer_cost_floor_beats_window_overlap(api):
    """PRD §3.7: "The anti-subsidy floor requires the tariff's
    `proposed_revenue_cents` to be at least the class's customer-cost component —
    that is, the cost-of-service total times 15% times the class's customer share,
    rounded half up — computed at tariff-create time; a tariff below the floor is
    `ERR_BELOW_CUSTOMER_COST_FLOOR`."
    PRD §2.9: "then business-safety (`ERR_BELOW_CUSTOMER_COST_FLOOR`), then
    temporal-window rules (`ERR_DISCOVERY_WINDOW_CLOSED`,
    `ERR_TARIFF_WINDOW_OVERLAP`, `ERR_DEFERRAL_OVERLAPS_TEST_YEAR`,
    `ERR_CLOCK_REGRESSION`)"

    Design: Corner/validations/customer_cost_floor_beats_window_overlap
    """
    s = setup_discovery_case(classes="com")
    add_com_tariff_2027(s.case["id"], s.cls_com["id"], label="COM 2027")
    res = api.create_tariff_rate(
        create_tariff_rate_payload(
            s.case["id"], s.cls_com["id"], label="COM below floor",
            proposed_customer_charge_cents=0,
            proposed_tiers=[{"up_to_kwh": None, "rate_mills": 10}],
            effective_start="2027-06-01T00:00:00Z",
            effective_end="2028-06-01T00:00:00Z"),
        UF)
    validate_error(res, ApiErrorId.ERR_BELOW_CUSTOMER_COST_FLOOR, expected_status=422)
    # proposed revenue 12*2000*(0 + 2500*10/100) == 6,000,000 is below the
    # customer-cost floor; the also-violated window-overlap rule must not win.


# ─── Corner: bill impact ─────────────────────────────────────────────────────

def test_bill_impact_with_explicit_tariff(api):
    """PRD §3.8: "The present bill is the class's `present_customer_charge_cents`
    plus the tiered-marginal charge for `monthly_kwh` under `present_tiers`. The
    proposed bill is the selected tariff's `proposed_customer_charge_cents` plus
    the tiered-marginal charge for `monthly_kwh` under `proposed_tiers`. The
    impact in basis points is the round-half-up of ten thousand times the
    difference of proposed minus present bill, divided by the present bill; a
    present bill of zero is `ERR_INVALID_REQUEST`."

    Design: Corner/calculations/bill_impact_with_explicit_tariff
    """
    s = setup_discovery_case(classes="res")
    t_res = add_tariff(s.case["id"], s.cls_res["id"])
    data = validate_success(api.get_bill_impact(
        s.case["id"], IR,
        params={"customer_class_id": s.cls_res["id"], "monthly_kwh": 500,
                "tariff_id": t_res["id"]}), 200)
    assert data["present_bill_cents"] == 4700, "800 + 300*7 + 200*9"
    assert data["proposed_bill_cents"] == 5050, "900 + 300*7.5 + 200*9.5"
    assert data["impact_pct_bp"] == 745, "round_half_up(10000*350/4700)"


def test_bill_impact_without_tariff_returns_not_found(api):
    """PRD §3.8: "if none, the read is rejected with `ERR_TARIFF_NOT_FOUND`."

    Design: Corner/calculations/bill_impact_without_tariff_returns_not_found
    """
    case = create_case()
    cls = add_class(case["id"])
    res = api.get_bill_impact(case["id"], UF,
                              params={"customer_class_id": cls["id"], "monthly_kwh": 500})
    validate_error(res, ApiErrorId.ERR_TARIFF_NOT_FOUND, expected_status=404)


# ─── Corner: tariff supersede sweep ──────────────────────────────────────────

def test_effective_tariff_superseded_by_later_window_sweep(api):
    """PRD §3.7: "For each CustomerClass, consider its tariffs in `EFFECTIVE`:
    the current tariff is the one with the latest `effective_start` that is less
    than or equal to the new clock (a tie is impossible, because overlapping
    windows for the same class are rejected at create). Every other `EFFECTIVE`
    tariff of the class whose `effective_start` is strictly before that latest
    `effective_start` moves to `SUPERSEDED`."
    PRD §3.6: "On success every `APPROVED` tariff moves to `EFFECTIVE`"

    Design: Corner/calculations/effective_tariff_superseded_by_later_window_sweep
    """
    s = setup_decided_with_tariffs_and_asset(
        num_intervenors=1, with_com_tariff=False, classes="res",
        with_asset=False, extra_res_tariff_2028=True)
    t_a, t_b = s.t_res, s.t_res_b
    assert get_tariff(t_a["id"])["status"] == "APPROVED"
    assert get_tariff(t_b["id"])["status"] == "APPROVED"
    validate_success(api.implement_rates(s.case["id"], UF), 200)
    assert get_tariff(t_a["id"])["status"] == "EFFECTIVE"
    assert get_tariff(t_b["id"])["status"] == "EFFECTIVE"
    validate_success(api.set_clock("2027-06-01T00:00:00Z", STAFF), 200)
    assert get_tariff(t_a["id"])["status"] == "EFFECTIVE", (
        "T_A is current; T_B's start is in the future"
    )
    assert get_tariff(t_b["id"])["status"] == "EFFECTIVE"
    validate_success(api.set_clock("2028-01-01T00:00:00Z", STAFF), 200)
    assert get_tariff(t_a["id"])["status"] == "SUPERSEDED", (
        "T_B's later start is now reachable and displaces T_A"
    )
    assert get_tariff(t_b["id"])["status"] == "EFFECTIVE"
