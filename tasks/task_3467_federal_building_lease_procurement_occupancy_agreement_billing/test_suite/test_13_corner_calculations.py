"""Corner coverage: calculation rules — projection, security scoring, TI
amortization variants, abatement boundary, amortization window gate, SLA
credit cap, utilization rounding, and expiration option scoring."""
import pytest

from test_helpers import (
    ApiErrorId, TEST_USERS, create_agency, create_alteration, create_plan,
    create_requirement, create_survey, create_ticket, estimate_alteration,
    finalize_survey, generate_bill, list_reduction_actions,
    make_agency_manager_headers, select_plan_option, set_clock,
    setup_active_leased_oa, setup_active_owned_oa, setup_commenced_lease,
    submit_requirement, validate_error, validate_paginated, validate_success,
)

ADMIN = TEST_USERS["gsa_admin_headers"]
OFFICER = TEST_USERS["gsa_leasing_officer_headers"]
PM = TEST_USERS["gsa_property_manager_headers"]


def test_requirement_validate_computes_projection_security_sf(api):
    """PRD §3.2: "The `projected_headcount` is the `base_headcount` grown at
    the `annual_growth_pct` rate, compounded once per year across that horizon,
    and rounded half up to whole persons. From it, `required_usable_sf` is the
    `projected_headcount` multiplied by `sf_per_person`, plus the sum of the
    `sf` of every item in `special_needs`."
    PRD §3.2: "the base level is 1 when the total is below 15, 2 when it is at
    least 15 but below 30, 3 when at least 30 but below 45, 4 when at least 45
    but below 60, and 5 when it reaches 60."
    PRD §3.2: "When any special need is of type `SCIF`, the level is raised to
    at least 4."

    400 headcount at 2% for 5 years (clock 2026 -> target 2031) projects to
    round_half_up(441.632) == 442; 442 * 150 + 2000 == 68,300 sf; 53 ISC
    points plus the SCIF floor resolve to level 4.

    Design: Corner/calculations/requirement_validate_computes_projection_security_sf
    """
    agency = create_agency()
    set_clock("2026-10-01T00:00:00Z")
    req = create_requirement(agency)
    submit_requirement(req, agency)

    validated = validate_success(api.validate_requirement(req["id"], OFFICER), 200)
    assert validated["status"] == "VALIDATED"
    assert validated["projected_headcount"] == 442
    assert validated["required_usable_sf"] == 68300
    assert validated["required_security_level"] == 4


def test_security_level_points_boundary_45_vs_44(api):
    """PRD §3.2: "the base level is 1 when the total is below 15, 2 when it is
    at least 15 but below 30, 3 when at least 30 but below 45, 4 when at least
    45 but below 60, and 5 when it reaches 60."

    The 45-point level-4 threshold is inclusive: 45 points -> 4, 44 -> 3.

    Design: Corner/calculations/security_level_points_boundary_45_vs_44
    """
    agency = create_agency()
    set_clock("2026-10-01T00:00:00Z")
    req45 = create_requirement(
        agency, title="Req 45", base_headcount=100, annual_growth_pct=0.0,
        target_occupancy_year=2028, sf_per_person=150, special_needs=[],
        region_code="R4", mission_points=15, population_points=10,
        size_points=10, criticality_points=10)
    req44 = create_requirement(
        agency, title="Req 44", base_headcount=100, annual_growth_pct=0.0,
        target_occupancy_year=2028, sf_per_person=150, special_needs=[],
        region_code="R4", mission_points=14, population_points=10,
        size_points=10, criticality_points=10)
    submit_requirement(req45, agency)
    submit_requirement(req44, agency)

    v45 = validate_success(api.validate_requirement(req45["id"], OFFICER), 200)
    v44 = validate_success(api.validate_requirement(req44["id"], OFFICER), 200)
    assert v45["required_security_level"] == 4, "45 >= 45"
    assert v44["required_security_level"] == 3, "44 < 45"


def test_security_scif_floor_overrides_low_points(api):
    """PRD §3.2: "When any special need is of type `SCIF`, the level is raised
    to at least 4."
    PRD §3.2: "From it, `required_usable_sf` is the `projected_headcount`
    multiplied by `sf_per_person`, plus the sum of the `sf` of every item in
    `special_needs`."

    20 points alone is level 2; adding a SCIF need forces 4.

    Design: Corner/calculations/security_scif_floor_overrides_low_points
    """
    agency = create_agency()
    set_clock("2026-10-01T00:00:00Z")
    plain = create_requirement(
        agency, title="No SCIF", base_headcount=100, annual_growth_pct=0.0,
        target_occupancy_year=2028, sf_per_person=150, special_needs=[],
        region_code="R4", mission_points=5, population_points=5,
        size_points=5, criticality_points=5)
    scif = create_requirement(
        agency, title="With SCIF", base_headcount=100, annual_growth_pct=0.0,
        target_occupancy_year=2028, sf_per_person=150,
        special_needs=[{"need_type": "SCIF", "sf": 1500}], region_code="R4",
        mission_points=5, population_points=5, size_points=5,
        criticality_points=5)
    submit_requirement(plain, agency)
    submit_requirement(scif, agency)

    v_plain = validate_success(api.validate_requirement(plain["id"], OFFICER), 200)
    v_scif = validate_success(api.validate_requirement(scif["id"], OFFICER), 200)
    assert v_plain["required_security_level"] == 2, "20 points"
    assert v_scif["required_security_level"] == 4, "SCIF floor"
    assert v_scif["required_usable_sf"] == 16500, "100 * 150 + 1500"


def test_ti_annuity_vs_straight_line_month_one_divergence(api):
    """PRD §3.4: "Under `ANNUITY`, a single level payment is computed: the
    principal multiplied by the monthly rate, divided by one minus the quantity
    one-plus-the-monthly-rate raised to the negative power of the term in
    months, rounded half up to whole cents; every month's entry equals that
    level payment."
    PRD §3.4: "Under `STRAIGHT_LINE`, an equal principal portion is computed as
    the principal divided by the term in months, rounded half up; each month
    then charges that equal principal plus interest of the current remaining
    balance times the monthly rate, rounded half up, and the balance is reduced
    by the equal principal before the next month is computed — so the method is
    front-loaded and its early entries differ from the annuity's."

    Same principal (58,500,000 over 120 months at 0.5%/month): ANNUITY bills
    649,470 every month; STRAIGHT_LINE's month-1 entry is 780,000 (487,500
    equal principal + 292,500 interest on the full balance), so the
    commencement-month (2027-01, month_index 1) totals diverge:
    6,419,144 vs 6,556,200.

    Design: Corner/calculations/ti_annuity_vs_straight_line_month_one_divergence
    """
    bundle_a = setup_active_leased_oa()  # ANNUITY, 2027 stmt actual 460
    bundle_b = setup_active_leased_oa(ti_amort_method="STRAIGHT_LINE")

    for bundle in (bundle_a, bundle_b):
        lease = validate_success(api.get_lease(bundle["lease"]["id"], ADMIN), 200)
        assert lease["ti_amortized_principal_cents"] == 58500000
        assert lease["ti_allowance_total_cents"] == 341500000

    bill_a = generate_bill(bundle_a["oa"], "2027-01")
    bill_b = generate_bill(bundle_b["oa"], "2027-01")
    assert bill_a["ti_amortization_cents"] == 649470
    assert bill_a["total_cents"] == 6419144
    assert bill_b["ti_amortization_cents"] == 780000
    assert bill_b["total_cents"] == 6556200
    assert bill_a["ti_amortization_cents"] != bill_b["ti_amortization_cents"]


def test_free_rent_abatement_last_free_month_vs_first_paid_month(api):
    """PRD §3.5: "The month index is the one-based count of months from the
    lease's commencement month to the billing month — defined for leased
    agreements."
    PRD §3.5: "`abatement_credit_cents` equals `shell_cents` when the agreement
    is leased and the month index falls within the lease's `free_rent_months`;
    otherwise it is zero."

    With free_rent_months == 3: month_index 3 (2027-03) still abates the full
    shell; month_index 4 (2027-04) abates nothing.

    Design: Corner/calculations/free_rent_abatement_last_free_month_vs_first_paid_month
    """
    bundle = setup_active_leased_oa()  # 2027 stmt actual 460
    oa = bundle["oa"]

    bill_mar = generate_bill(oa, "2027-03")
    assert bill_mar["abatement_credit_cents"] == 17075000
    assert bill_mar["shell_cents"] == 17075000
    assert bill_mar["total_cents"] == 6419144

    bill_apr = generate_bill(oa, "2027-04")
    assert bill_apr["abatement_credit_cents"] == 0
    assert bill_apr["total_cents"] == 24347894


def test_amortization_window_exactly_twelve_months_allowed(api):
    """PRD §3.6: "Choosing `AMORTIZED` commits to at least twelve whole
    amortization months between the month after the work-end month and the
    agreement's end month; a shorter runway is rejected with
    `ERR_AMORTIZATION_WINDOW_TOO_SHORT`."

    Work ending 2035-12-05 against an OA ending 2036-12 leaves exactly 12
    amortization months (2036-01..2036-12) and is approved; ending 2036-01-05
    leaves 11 and is rejected — yet the same alteration still approves as
    LUMP_SUM, because the fiscal gate applies only to AMORTIZED.

    Design: Corner/calculations/amortization_window_exactly_twelve_months_allowed
    """
    bundle = setup_active_leased_oa(tax_year=None)
    oa, agency = bundle["oa"], bundle["agency"]
    agency_h = make_agency_manager_headers(agency["id"])

    alt_ok = create_alteration(oa, agency, title="Edge OK",
                               description="twelve months exactly", scope_sf=500)
    estimate_alteration(alt_ok, estimated_cost_cents=6000000,
                        work_start_date="2035-09-01", work_end_date="2035-12-05")
    alt_bad = create_alteration(oa, agency, title="Edge bad",
                                description="eleven months only", scope_sf=500)
    estimate_alteration(alt_bad, estimated_cost_cents=6000000,
                        work_start_date="2035-12-20", work_end_date="2036-01-05")

    ok = validate_success(api.approve_alteration(
        alt_ok["id"], {"funding_method": "AMORTIZED"}, agency_h), 200)
    assert ok["status"] == "APPROVED"
    assert ok["funding_method"] == "AMORTIZED"

    resp = api.approve_alteration(alt_bad["id"], {"funding_method": "AMORTIZED"},
                                  agency_h)
    validate_error(resp, ApiErrorId.ERR_AMORTIZATION_WINDOW_TOO_SHORT)
    alts, _ = validate_paginated(api.list_alterations(oa["id"], ADMIN))
    bad_mid = next(a for a in alts if a["id"] == alt_bad["id"])
    assert bad_mid["status"] == "ESTIMATED"

    lump = validate_success(api.approve_alteration(
        alt_bad["id"], {"funding_method": "LUMP_SUM"}, agency_h), 200)
    assert lump["status"] == "APPROVED"
    assert lump["funding_method"] == "LUMP_SUM"


def test_sla_service_credit_capped_at_ceiling(api):
    """PRD §3.7: "The ticket's open hours are measured exactly from
    `created_at` to `resolved_at`; `sla_breached` is true only when that span
    strictly exceeds `sla_hours` — resolution at exactly the SLA limit is not a
    breach."
    PRD §3.7: "A breached ticket earns ten thousand cents per started
    twenty-four-hour block of overrun — partial blocks round up — capped at one
    hundred thousand cents."
    PRD §3.7: "Any positive credit is added to the agreement's
    `pending_service_credit_cents`, where it sits until the next generated bill
    consumes it (§3.5, step 11)."

    A ROUTINE ticket open 505 hours overruns its 72h SLA by 433 hours ->
    ceil(433/24) == 19 blocks -> 190,000 cents, capped to 100,000; the next
    bill consumes exactly 100,000.

    Design: Corner/calculations/sla_service_credit_capped_at_ceiling
    """
    bundle = setup_active_leased_oa()  # 2027 stmt actual 460
    oa, agency, building = bundle["oa"], bundle["agency"], bundle["building"]
    agency_h = make_agency_manager_headers(agency["id"])

    set_clock("2027-01-05T00:00:00Z")
    ticket = create_ticket(building, oa, agency, category="CLEANING",
                           severity="ROUTINE",
                           description="Garage sweeping backlog")
    set_clock("2027-01-26T01:00:00Z")
    validate_success(api.resolve_ticket(ticket["id"], PM), 200)
    verified = validate_success(api.verify_ticket(ticket["id"], agency_h), 200)
    assert verified["sla_breached"] is True
    assert verified["credit_cents"] == 100000, "19 blocks * 10,000, capped"

    bill = generate_bill(oa, "2027-02")
    assert bill["service_credit_applied_cents"] == 100000
    assert bill["total_cents"] == 6319144

    oa_after = validate_success(api.get_oa(oa["id"], ADMIN), 200)
    assert oa_after["pending_service_credit_cents"] == 0


def test_utilization_rounding_before_threshold_compare(api):
    """PRD §3.8: "Either way the rate is rounded half up to four decimal
    places."
    PRD §3.8: "When the finalized rate falls strictly below 0.60 — a rate of
    exactly 0.6000 does not qualify — the system auto-creates a space reduction
    action in `PROPOSED` on the same agreement, copies the recommendation into
    it, and links it back through the survey's `reduction_action_id`; otherwise
    that field stays null."
    PRD §3.8: "Finalization also sets `recommended_release_sf`: the
    `assigned_sf` minus the `measured_headcount` times the same
    150-square-feet-per-person standard, floored at zero."

    The finalized (rounded) rate is what the threshold sees: 11,999 / 20,000 is
    raw 0.59995 -> stored 0.6000 -> NO action; 11,990 -> 0.5995 -> action with
    recommended_release_sf 5,000.

    Design: Corner/calculations/utilization_rounding_before_threshold_compare
    """
    bundle = setup_active_owned_oa(clock="2027-03-20T00:00:00Z")
    oa = bundle["oa"]

    s1 = create_survey(oa, method="SPACE_BASED", measured_headcount=100,
                       utilized_sf=11999)
    s2 = create_survey(oa, method="SPACE_BASED", measured_headcount=100,
                       utilized_sf=11990)
    f1 = finalize_survey(s1)
    f2 = finalize_survey(s2)

    assert f1["utilization_rate"] == pytest.approx(0.6000, abs=1e-9), (
        "0.59995 rounds up to 0.6000")
    assert f1["reduction_action_id"] is None
    assert f2["utilization_rate"] == pytest.approx(0.5995, abs=1e-9)
    assert f2["reduction_action_id"] is not None

    actions = list_reduction_actions(oa)
    assert len(actions) == 1
    assert actions[0]["recommended_release_sf"] == 5000, "20,000 - 100 * 150"


def test_expiration_option_scoring_minimum_and_tiebreak(api):
    """PRD §3.9: "All three options are then scored over a ten-year, 120-month
    horizon against the lease's `leased_sf`. The succeeding-lease cost is the
    sum of the succeeding shell and operating rates, times the square feet,
    times ten years. The relocation cost is the move cost plus the downtime
    cost, plus the sum of the market shell and operating rates times the square
    feet times ten years. The replacement-construction cost amortizes the
    construction cost over a 300-month — twenty-five-year — schedule and
    charges the 120-month horizon's share of it, rounded half up, then adds the
    construction operating rate times the square feet times ten years."
    PRD §3.9: "The three results are stored in `option_costs`, each option
    paired with its `projected_cost_cents`; `recommended_option` is the
    cheapest, with ties broken by the fixed priority `SUCCEEDING_LEASE` over
    `RELOCATION` over `REPLACEMENT_CONSTRUCTION`. The supplied inputs are
    retained in `cost_params` for reuse at execution, and `selected_option`
    records the officer's choice."

    Plan A recommends REPLACEMENT_CONSTRUCTION (cheapest) regardless of the
    officer's selection; plan B ties SUCCEEDING_LEASE with RELOCATION and the
    fixed priority recommends SUCCEEDING_LEASE.

    Design: Corner/calculations/expiration_option_scoring_minimum_and_tiebreak
    """
    bundle_a = setup_commenced_lease()
    bundle_b = setup_commenced_lease()
    plan_a = create_plan(bundle_a["lease"])
    plan_b = create_plan(bundle_b["lease"])

    sel_a = select_plan_option(plan_a, option="SUCCEEDING_LEASE")
    costs_a = {c["option"]: c["projected_cost_cents"] for c in sel_a["option_costs"]}
    assert costs_a["SUCCEEDING_LEASE"] == 2834450000
    assert costs_a["RELOCATION"] == 2918600000
    assert costs_a["REPLACEMENT_CONSTRUCTION"] == 2478100000
    assert sel_a["recommended_option"] == "REPLACEMENT_CONSTRUCTION"
    assert sel_a["selected_option"] == "SUCCEEDING_LEASE", (
        "recommendation is advisory; selection is the officer's")

    sel_b = select_plan_option(plan_b, option="RELOCATION",
                               relocation_move_cost_cents=102450000,
                               market_shell_rate=3200, market_operating_rate=800,
                               construction_cost_cents=9999000000)
    costs_b = {c["option"]: c["projected_cost_cents"] for c in sel_b["option_costs"]}
    assert costs_b["SUCCEEDING_LEASE"] == 2834450000
    assert costs_b["RELOCATION"] == 2834450000, "engineered tie"
    assert sel_b["recommended_option"] == "SUCCEEDING_LEASE", (
        "fixed priority breaks the tie")
    assert sel_b["selected_option"] == "RELOCATION"
