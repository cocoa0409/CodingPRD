"""Derived arithmetic: quotes, sizing, retention deadlines, ledgers and claim money.

Every quantity asserted here is frozen or recomputed by the server from inputs
the test supplies, so each test builds its own structure, graph and downstream
rows and then reads the derived figures back.
"""

import pytest

from test_helpers import (
    CONDUCIVE_EXCESS_MOISTURE,
    CONDUCIVE_FAULTY_GRADE,
    CONDUCIVE_WOOD_TO_GROUND,
    CONSTRUCTION_CRAWLSPACE,
    CONSTRUCTION_PIER_AND_BEAM,
    CONSTRUCTION_SLAB,
    ERR_FORM_CODE_MISMATCH,
    EXCLUSION_AGGREGATE_PRORATION,
    FINDING_CONDUCIVE_CONDITION,
    INSPECTION_GRAPHED,
    METHOD_BAIT_STATION,
    METHOD_LIQUID_BARRIER,
    OFFICER_HEADERS,
    PRODUCT_IMID_4,
    REPORT_DRAFT,
    STATE_FORM_MAP,
    TIER_REPAIR_AND_RETREAT,
    TIER_RETREAT_ONLY,
    add_finding,
    approve_plan,
    assert_bond_money,
    assert_claim_money,
    assert_conducive_counts_conserved,
    assert_date_shape,
    assert_immutable_record_fields,
    assert_instant_equals,
    assert_money,
    assert_status,
    attach_verification,
    bonded_property,
    conducive_finding_payload,
    damage_graph,
    evidence_finding_payload,
    file_claim,
    graphed_inspection,
    infestation_finding_payload,
    open_graph,
    open_wdo_report,
    propose_bait_plan,
    propose_plan,
    real_estate_graph,
    record_application,
    register_inspector,
    register_property_and_inspector,
    retention_until,
    set_clock,
    sign_graph,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_claim,
)
from test_helpers.test_users import make_property_owner_headers

CLOCK_START = "2026-08-01T00:00:00Z"


def _structure_with_plan(api, method=METHOD_LIQUID_BARRIER, findings=(), **overrides):
    """Register a structure, sign an INITIAL graph on it and propose one plan."""
    prop, inspector = register_property_and_inspector(api, **overrides)
    graph = graphed_inspection(api, prop["id"], inspector["id"], findings)
    if method == METHOD_BAIT_STATION:
        plan = propose_bait_plan(api, prop["id"], graph["id"], inspector["id"])
    else:
        plan = propose_plan(
            api, prop["id"], graph["id"], inspector["id"], method=method
        )
    return prop, inspector, graph, plan


# ---------------------------------------------------------------------------
# Floor-area brackets
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "square_footage,expected_quote,expected_gallons",
    [(1500, 905.00, 108.00), (3000, 1430.00, 115.00), (3001, 1430.28, 116.00)],
)
def test_quote_brackets_at_the_declared_area_boundaries(
    api, square_footage, expected_quote, expected_gallons
):
    """A slab liquid quote at 1500, 3000 and 3001 heated square feet.

    PRD 3.5: "the first 1500 square feet are charged at 0.42 per square foot;
    the portion above 1500 up to and including 3000 square feet at 0.35 per
    square foot; and the portion beyond 3000 square feet at 0.28 per square
    foot."

    Design: Corner/calculations/quote_tier_boundaries_at_exactly_fifteen_hundred_and_three_thousand_sqft
    """
    set_clock(api, CLOCK_START)
    _, _, _, plan = _structure_with_plan(
        api,
        square_footage=square_footage,
        linear_footage=100,
        construction_type=CONSTRUCTION_SLAB,
    )
    assert_money(plan["quoted_price_usd"], expected_quote)
    assert_money(plan["target_gallons"], expected_gallons)
    assert plan["target_station_count"] == 0, (
        "a liquid plan installs no bait stations, got %r"
        % plan["target_station_count"]
    )


def test_one_square_foot_past_three_thousand_is_charged_at_the_third_rate(api):
    """The 3001st square foot is priced at 0.28, not at 0.35.

    PRD 3.5: "the portion above 1500 up to and including 3000 square feet at
    0.35 per square foot; and the portion beyond 3000 square feet at 0.28 per
    square foot."

    Design: Corner/calculations/quote_tier_boundaries_at_exactly_fifteen_hundred_and_three_thousand_sqft
    """
    set_clock(api, CLOCK_START)
    _, _, _, at_boundary = _structure_with_plan(
        api,
        square_footage=3000,
        linear_footage=100,
        construction_type=CONSTRUCTION_SLAB,
    )
    _, _, _, past_boundary = _structure_with_plan(
        api,
        square_footage=3001,
        linear_footage=100,
        construction_type=CONSTRUCTION_SLAB,
        address_line1="2 Bracket Crossing",
    )
    delta = past_boundary["quoted_price_usd"] - at_boundary["quoted_price_usd"]
    assert delta == pytest.approx(0.28, abs=0.01), (
        "one square foot beyond 3000 must add 0.28, added %r" % delta
    )


# ---------------------------------------------------------------------------
# Method ceilings
# ---------------------------------------------------------------------------


def test_bait_quote_is_clamped_to_the_bait_station_ceiling(api):
    """A 12000 sqft pier-and-beam bait quote lands on the method ceiling.

    PRD 3.5: "the quote is the lesser of that figure and the method's ceiling,
    which is 4200.00 for `LIQUID_BARRIER`, 3600.00 for `BAIT_STATION` and
    9800.00 for `FUMIGATION`. The cap is applied after rounding, never before."

    Design: Corner/calculations/bait_station_quote_is_clamped_by_the_method_price_cap
    """
    set_clock(api, CLOCK_START)
    _, _, _, plan = _structure_with_plan(
        api,
        method=METHOD_BAIT_STATION,
        square_footage=12000,
        linear_footage=200,
        construction_type=CONSTRUCTION_PIER_AND_BEAM,
        year_built=1972,
        address_line1="88 Stilt Road",
    )
    assert_money(plan["quoted_price_usd"], 3600.00)
    assert plan["target_station_count"] == 20, (
        "200 linear feet at 10-foot spacing installs 20 stations, got %r"
        % plan["target_station_count"]
    )
    assert_money(plan["target_gallons"], 0.00)


def test_liquid_quote_on_the_same_structure_is_clamped_to_the_liquid_ceiling(api):
    """The same oversized structure prices out at the liquid ceiling instead.

    PRD 3.5: "the quote is the lesser of that figure and the method's ceiling,
    which is 4200.00 for `LIQUID_BARRIER`, 3600.00 for `BAIT_STATION` and
    9800.00 for `FUMIGATION`."

    Design: Corner/calculations/bait_station_quote_is_clamped_by_the_method_price_cap
    """
    set_clock(api, CLOCK_START)
    _, _, _, plan = _structure_with_plan(
        api,
        method=METHOD_LIQUID_BARRIER,
        square_footage=12000,
        linear_footage=200,
        construction_type=CONSTRUCTION_PIER_AND_BEAM,
        year_built=1972,
        address_line1="88 Stilt Road",
    )
    assert_money(plan["quoted_price_usd"], 4200.00)
    assert_money(plan["target_gallons"], 250.00)
    assert plan["target_station_count"] == 0, (
        "a liquid plan installs no bait stations, got %r"
        % plan["target_station_count"]
    )


# ---------------------------------------------------------------------------
# The infestation surcharge
# ---------------------------------------------------------------------------


def test_infestation_surcharge_raises_the_quote_by_twelve_percent(api):
    """An active-infestation graph adds 12 percent; sizing is untouched.

    PRD 3.5: "When the justifying graph's `active_infestation_found` is true,
    the running figure is increased by a further 12 percent - that is,
    multiplied by 1.12; when it is false the figure is carried forward
    unchanged."

    Design: Corner/calculations/infestation_surcharge_applies_only_when_the_graph_found_active_infestation
    """
    set_clock(api, CLOCK_START)
    _, _, clean_graph, clean_plan = _structure_with_plan(api)
    assert clean_graph["active_infestation_found"] is False, (
        "a zero-notation graph found no infestation, got %r"
        % clean_graph["active_infestation_found"]
    )

    _, _, infested_graph, infested_plan = _structure_with_plan(
        api,
        findings=[
            infestation_finding_payload("B2"),
            evidence_finding_payload("C3"),
        ],
        address_line1="7 Swarmer Lane",
    )
    assert infested_graph["active_infestation_found"] is True, (
        "an ACTIVE_INFESTATION notation sets the flag, got %r"
        % infested_graph["active_infestation_found"]
    )
    assert infested_graph["findings_count"] == 2, (
        "the graph carries two notations, got %r" % infested_graph["findings_count"]
    )

    assert_money(clean_plan["quoted_price_usd"], 1080.00)
    assert_money(infested_plan["quoted_price_usd"], 1209.60)
    assert_money(clean_plan["target_gallons"], 190.00)
    assert_money(infested_plan["target_gallons"], 190.00)


def test_previous_treatment_evidence_alone_leaves_the_quote_unsurcharged(api):
    """Old-treatment evidence is not an active infestation, so no surcharge.

    PRD 3.3: "`active_infestation_found` is true when at least one notation has
    `finding_type` equal to `ACTIVE_INFESTATION`."

    Design: Corner/calculations/infestation_surcharge_applies_only_when_the_graph_found_active_infestation
    """
    set_clock(api, CLOCK_START)
    _, _, graph, plan = _structure_with_plan(
        api,
        findings=[evidence_finding_payload("C3")],
        address_line1="9 Old Trench Way",
    )
    assert graph["active_infestation_found"] is False, (
        "PREVIOUS_TREATMENT_EVIDENCE must not set the infestation flag, got %r"
        % graph["active_infestation_found"]
    )
    assert graph["findings_count"] == 1, (
        "the graph carries one notation, got %r" % graph["findings_count"]
    )
    assert_money(plan["quoted_price_usd"], 1080.00)


# ---------------------------------------------------------------------------
# Tier multipliers and the cap loading
# ---------------------------------------------------------------------------


def test_retreat_only_tier_zeroes_the_ceiling_and_its_loading(api):
    """A RETREAT_ONLY bond carries no monetary repair liability at all.

    PRD 3.7: "For `RETREAT_ONLY` that multiplier is zero, so the ceiling is 0.00
    and the bond carries no monetary repair liability at all."

    Design: Corner/calculations/retreat_only_tier_zeroes_both_the_cap_and_the_cap_loading
    """
    chain = bonded_property(
        api,
        coverage_tier=TIER_RETREAT_ONLY,
        issue_instant="2026-09-01T00:00:00Z",
    )
    plan = chain["plan"]
    bond = chain["bond"]
    assert_money(plan["quoted_price_usd"], 1080.00)
    assert_bond_money(
        bond,
        base_premium_usd=194.40,
        repair_liability_cap_usd=0.00,
        annual_premium_usd=194.40,
        claims_paid_to_date_usd=0.00,
        reserved_claim_amount_usd=0.00,
        remaining_repair_cap_usd=0.00,
    )
    assert bond["retreat_required"] is False, (
        "a fresh bond raises no retreat obligation, got %r" % bond["retreat_required"]
    )
    assert bond["coverage_watch"] is False, (
        "a fresh bond is not on coverage watch, got %r" % bond["coverage_watch"]
    )
    assert bond["retreat_credit_count"] == 0, (
        "a fresh bond has issued no retreat credits, got %r"
        % bond["retreat_credit_count"]
    )


def test_repair_and_retreat_tier_loads_the_annual_premium(api):
    """The 60x ceiling adds a 0.004 loading the retreat-only tier cannot have.

    PRD 3.7: "`annual_premium_usd` is `base_premium_usd` plus a cap loading of
    0.004 - four tenths of one percent - of `repair_liability_cap_usd`, the sum
    rounded half up to two decimal places."

    Design: Corner/calculations/retreat_only_tier_zeroes_both_the_cap_and_the_cap_loading
    """
    chain = bonded_property(
        api,
        coverage_tier=TIER_REPAIR_AND_RETREAT,
        issue_instant="2026-09-01T00:00:00Z",
    )
    bond = chain["bond"]
    assert_bond_money(
        bond,
        base_premium_usd=194.40,
        repair_liability_cap_usd=11664.00,
        annual_premium_usd=241.06,
        claims_paid_to_date_usd=0.00,
        reserved_claim_amount_usd=0.00,
        remaining_repair_cap_usd=11664.00,
    )


# ---------------------------------------------------------------------------
# Pesticide-record retention
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "state_code,plan_overrides,expected_retention",
    [
        ("FL", {}, "2030-07-31"),
        ("GA", {"chemical_product_code": PRODUCT_IMID_4}, "2028-07-31"),
    ],
)
def test_retention_deadline_uses_fixed_three_hundred_sixty_five_day_years(
    api, state_code, plan_overrides, expected_retention
):
    """Florida's four years and Georgia's two years, counted in 365-day years.

    PRD 2.10: "the retention deadline is always computed as that year count
    multiplied by 365 days added to the date on which the chemical was applied."

    Design: Corner/calculations/pesticide_retention_uses_fixed_three_hundred_sixty_five_day_years_per_state
    """
    set_clock(api, CLOCK_START)
    prop, inspector = register_property_and_inspector(api, state_code=state_code)
    graph = graphed_inspection(api, prop["id"], inspector["id"])
    plan = propose_plan(
        api, prop["id"], graph["id"], inspector["id"], **plan_overrides
    )
    plan = approve_plan(api, plan["id"])
    record = record_application(
        api, plan["id"], inspector["id"], plan["version"], gallons_applied=95.00
    )

    assert_instant_equals(record["applied_at"], CLOCK_START)
    assert_date_shape(record["retention_until"])
    assert record["retention_until"] == expected_retention, (
        "expected retention_until %r, got %r"
        % (expected_retention, record["retention_until"])
    )
    assert record["retention_until"] == retention_until(CLOCK_START, state_code)
    assert record["state_code"] == state_code, (
        "the treated structure's jurisdiction is snapshotted, got %r"
        % record["state_code"]
    )
    assert record["applicator_license_state"] == state_code
    assert record["applicator_license_number"] == inspector["license_number"]
    assert_immutable_record_fields(record, "pesticide_record")

    plan = validate_success(api.get_treatment_plan(plan["id"], OFFICER_HEADERS))
    assert_money(plan["gallons_applied_total"], 95.00)
    assert_money(plan["target_gallons"], 190.00)
    rows, meta = validate_paginated(api.list_applications(plan["id"], OFFICER_HEADERS))
    assert meta["total_count"] == 1, (
        "one application was recorded, got %r" % meta["total_count"]
    )
    assert len(rows) == 1


def test_retention_years_are_not_calendar_anniversaries(api):
    """Four 365-day years from 2026-08-01 land on 2030-07-31, not 2030-08-01.

    PRD 2.10: "Retention periods are expressed in fixed 365-day years, never in
    calendar years, so a leap day shortens the calendar span rather than moving
    the anniversary."

    Design: Corner/calculations/pesticide_retention_uses_fixed_three_hundred_sixty_five_day_years_per_state
    """
    set_clock(api, CLOCK_START)
    prop, inspector = register_property_and_inspector(api, state_code="FL")
    graph = graphed_inspection(api, prop["id"], inspector["id"])
    plan = approve_plan(
        api, propose_plan(api, prop["id"], graph["id"], inspector["id"])["id"]
    )
    record = record_application(
        api, plan["id"], inspector["id"], plan["version"], gallons_applied=95.00
    )
    assert record["retention_until"] == "2030-07-31", (
        "four fixed years from 2026-08-01 end on 2030-07-31, got %r"
        % record["retention_until"]
    )


# ---------------------------------------------------------------------------
# The deductible tier
# ---------------------------------------------------------------------------


def _bonded_chain_with_peer_verifier(api, coverage_tier=TIER_REPAIR_AND_RETREAT):
    """A bonded structure plus a second licensee who may verify its damage."""
    chain = bonded_property(
        api, coverage_tier=coverage_tier, issue_instant="2026-09-01T00:00:00Z"
    )
    verifier = register_inspector(
        api, license_state="FL", full_name="Ines Duarte Alvarez"
    )
    return chain, verifier


def test_deductible_rate_is_seven_percent_at_exactly_two_thousand_eligible(api):
    """An eligible amount of exactly 2000.00 sits in the middle tier.

    PRD 3.10: "7 percent when it is at least 2000.00 but below 10000.00."

    Design: Corner/calculations/deductible_rate_is_keyed_on_the_pre_deductible_eligible_amount
    """
    chain, verifier = _bonded_chain_with_peer_verifier(api)
    prop = chain["property"]
    graph = damage_graph(
        api, prop["id"], verifier["id"], [("D2", 5000.00, False, 3)]
    )
    claim = file_claim(api, chain["bond"], prop["id"], 2000.00)
    claim = attach_verification(api, claim["id"], graph["id"], verifier["id"])

    assert claim["exclusion_basis"] == EXCLUSION_AGGREGATE_PRORATION, (
        "a graph that supersedes nothing prorates, got %r" % claim["exclusion_basis"]
    )
    assert_claim_money(
        claim,
        eligible_damage_usd=2000.00,
        excluded_pre_existing_usd=0.00,
        deductible_usd=140.00,
        projected_payout_usd=1860.00,
    )
    bond = validate_success(api.get_bond(chain["bond"]["id"], OFFICER_HEADERS))
    assert_bond_money(
        bond,
        repair_liability_cap_usd=11664.00,
        reserved_claim_amount_usd=1860.00,
        remaining_repair_cap_usd=9804.00,
    )


def test_deductible_rate_is_ten_percent_one_cent_below_the_boundary(api):
    """An eligible amount of 1999.99 falls into the lowest tier at 10 percent.

    PRD 3.10: "10 percent when `eligible_damage_usd` is below 2000.00 ... The
    tier is keyed on the eligible amount and is never re-keyed on the
    post-deductible or post-cap figure."

    Design: Corner/calculations/deductible_rate_is_keyed_on_the_pre_deductible_eligible_amount
    """
    chain, verifier = _bonded_chain_with_peer_verifier(api)
    prop = chain["property"]
    graph = damage_graph(
        api, prop["id"], verifier["id"], [("D2", 5000.00, False, 3)]
    )
    claim = file_claim(api, chain["bond"], prop["id"], 1999.99)
    claim = attach_verification(api, claim["id"], graph["id"], verifier["id"])

    assert_claim_money(
        claim,
        eligible_damage_usd=1999.99,
        excluded_pre_existing_usd=0.00,
        deductible_usd=200.00,
        projected_payout_usd=1799.99,
    )
    bond = validate_success(api.get_bond(chain["bond"]["id"], OFFICER_HEADERS))
    assert_bond_money(
        bond,
        reserved_claim_amount_usd=1799.99,
        remaining_repair_cap_usd=9864.01,
    )


def test_withdrawal_releases_the_reserve_so_the_next_claim_is_priced_afresh(api):
    """Verification and withdrawal are a matched pair; the tier is re-keyed.

    PRD 3.10: "`reserved_claim_amount_usd` falls by `projected_payout_usd` and
    `remaining_repair_cap_usd` rises by the identical figure, so
    `remaining_repair_cap_usd` returns to its exact pre-verification value with
    zero drift."

    Design: Corner/calculations/deductible_rate_is_keyed_on_the_pre_deductible_eligible_amount
    """
    chain, verifier = _bonded_chain_with_peer_verifier(api)
    prop = chain["property"]
    bond_id = chain["bond"]["id"]
    graph = damage_graph(
        api, prop["id"], verifier["id"], [("D2", 5000.00, False, 3)]
    )

    first = file_claim(api, chain["bond"], prop["id"], 2000.00)
    first = attach_verification(api, first["id"], graph["id"], verifier["id"])
    assert_claim_money(first, deductible_usd=140.00, projected_payout_usd=1860.00)

    withdraw_claim(api, first["id"], prop["id"])
    released = validate_success(api.get_bond(bond_id, OFFICER_HEADERS))
    assert_bond_money(
        released,
        reserved_claim_amount_usd=0.00,
        remaining_repair_cap_usd=11664.00,
    )

    second = file_claim(api, released, prop["id"], 1999.99)
    second = attach_verification(api, second["id"], graph["id"], verifier["id"])
    assert_claim_money(second, deductible_usd=200.00, projected_payout_usd=1799.99)
    shortfall = first["projected_payout_usd"] - second["projected_payout_usd"]
    assert shortfall == pytest.approx(60.01, abs=0.01), (
        "one cent less eligible damage costs 60.01 of payout, cost %r" % shortfall
    )


# ---------------------------------------------------------------------------
# The conducive-condition ledger
# ---------------------------------------------------------------------------


def _crawlspace_with_three_conducive_notations(api):
    """A crawlspace whose signed graph carries two codes across three cells."""
    prop, inspector = register_property_and_inspector(
        api,
        state_code="FL",
        construction_type=CONSTRUCTION_CRAWLSPACE,
        square_footage=1400,
        linear_footage=150,
        crawl_clearance_inches=18,
        address_line1="12 Vent Row",
    )
    graph = graphed_inspection(
        api,
        prop["id"],
        inspector["id"],
        [
            conducive_finding_payload("A1", CONDUCIVE_EXCESS_MOISTURE),
            conducive_finding_payload("A2", CONDUCIVE_EXCESS_MOISTURE),
            conducive_finding_payload("B1", CONDUCIVE_WOOD_TO_GROUND),
        ],
    )
    return prop, inspector, graph


def test_structure_counts_distinct_codes_while_the_graph_counts_rows(api):
    """Three notations carrying two codes: the graph says 3, the structure 2.

    PRD 3.1: "the structure-level counters count **distinct codes**, whereas the
    graph-level counter described in 3.3 counts **rows**. Two `EXCESS_MOISTURE`
    notations in different grid cells raise the graph's row count by two but the
    structure's distinct-code count by one."

    Design: Corner/calculations/conducive_ledger_counts_distinct_codes_of_the_latest_graph_only
    """
    set_clock(api, CLOCK_START)
    prop, _, graph = _crawlspace_with_three_conducive_notations(api)

    assert graph["findings_count"] == 3, (
        "the graph carries three notations, got %r" % graph["findings_count"]
    )
    assert graph["conducive_condition_count"] == 3, (
        "the graph counts conducive rows, got %r" % graph["conducive_condition_count"]
    )
    rows, meta = validate_paginated(
        api.list_findings(
            graph["id"], OFFICER_HEADERS, finding_type=FINDING_CONDUCIVE_CONDITION
        )
    )
    assert meta["total_count"] == 3, (
        "three conducive notations were written, got %r" % meta["total_count"]
    )
    assert len(rows) == 3

    prop = validate_success(api.get_property(prop["id"], OFFICER_HEADERS))
    assert prop["total_conducive_condition_count"] == 2, (
        "two distinct codes were found, got %r"
        % prop["total_conducive_condition_count"]
    )
    assert prop["waived_conducive_condition_count"] == 0
    assert prop["open_conducive_condition_count"] == 2
    assert_conducive_counts_conserved(prop)


def test_a_draft_graph_contributes_nothing_to_the_ledger(api):
    """A second graph left in DRAFT leaves the structure's counters alone.

    PRD 3.1: "Graphs still in `DRAFT`, and graphs already `SUPERSEDED`,
    contribute nothing at all."

    Design: Corner/calculations/conducive_ledger_counts_distinct_codes_of_the_latest_graph_only
    """
    set_clock(api, CLOCK_START)
    prop, inspector, _ = _crawlspace_with_three_conducive_notations(api)
    draft = open_graph(api, prop["id"], inspector["id"])
    add_finding(
        api,
        draft["id"],
        inspector["id"],
        conducive_finding_payload("C1", CONDUCIVE_FAULTY_GRADE),
    )

    prop = validate_success(api.get_property(prop["id"], OFFICER_HEADERS))
    assert prop["total_conducive_condition_count"] == 2, (
        "the draft's code must not enter the ledger, got %r"
        % prop["total_conducive_condition_count"]
    )
    assert prop["open_conducive_condition_count"] == 2
    assert_conducive_counts_conserved(prop)


def test_signing_a_later_graph_replaces_the_whole_ledger(api):
    """The ledger reads the latest signed graph only, not the union of graphs.

    PRD 3.1: "among the structure's graphs in status `GRAPHED`, the one with the
    greatest `graph_completed_at` ... the number of distinct codes found is
    `total_conducive_condition_count`."

    Design: Corner/calculations/conducive_ledger_counts_distinct_codes_of_the_latest_graph_only
    """
    set_clock(api, CLOCK_START)
    prop, inspector, first = _crawlspace_with_three_conducive_notations(api)
    later = open_graph(api, prop["id"], inspector["id"])
    add_finding(
        api,
        later["id"],
        inspector["id"],
        conducive_finding_payload("C1", CONDUCIVE_FAULTY_GRADE),
    )
    set_clock(api, "2026-08-05T00:00:00Z")
    later = sign_graph(api, later["id"], inspector["id"])
    assert later["conducive_condition_count"] == 1

    prop = validate_success(api.get_property(prop["id"], OFFICER_HEADERS))
    assert prop["total_conducive_condition_count"] == 1, (
        "only the latest signed graph's codes count, got %r"
        % prop["total_conducive_condition_count"]
    )
    assert prop["open_conducive_condition_count"] == 1
    assert_conducive_counts_conserved(prop)

    earlier = validate_success(api.get_inspection(first["id"], OFFICER_HEADERS))
    assert_status(earlier, INSPECTION_GRAPHED, "inspection")


# ---------------------------------------------------------------------------
# Statutory turnaround and form selection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "state_code,expected_due_at,files_as_owner",
    [
        ("FL", "2026-08-04T00:00:00Z", False),
        ("TX", "2026-08-05T00:00:00Z", True),
    ],
)
def test_report_due_at_and_form_are_keyed_on_the_structures_state(
    api, state_code, expected_due_at, files_as_owner
):
    """Florida allows 72 hours and Texas 96, from the same request instant.

    PRD 3.4: "three values are snapshotted onto it at that moment: `state_code`
    from the inspected structure, `closing_date` from the graph, and `due_at`,
    computed as `requested_at` plus that state's turnaround allowance in hours."

    Design: Corner/calculations/wdo_due_at_and_required_form_are_keyed_on_the_property_state
    """
    set_clock(api, CLOCK_START)
    prop, inspector = register_property_and_inspector(
        api, state_code=state_code, square_footage=2200
    )
    graph = real_estate_graph(
        api, prop["id"], inspector["id"], closing_date="2026-09-15"
    )
    headers = make_property_owner_headers(prop["id"]) if files_as_owner else None
    report = open_wdo_report(
        api, graph["id"], state_code=state_code, headers=headers
    )

    assert report["form_code"] == STATE_FORM_MAP[state_code], (
        "the structure's state mandates %r, got %r"
        % (STATE_FORM_MAP[state_code], report["form_code"])
    )
    assert report["state_code"] == state_code, (
        "the jurisdiction is snapshotted from the structure, got %r"
        % report["state_code"]
    )
    assert report["closing_date"] == "2026-09-15", (
        "the closing date is snapshotted from the graph, got %r"
        % report["closing_date"]
    )
    assert_status(report, REPORT_DRAFT, "wdo_report")
    assert_instant_equals(report["requested_at"], CLOCK_START)
    assert_instant_equals(report["due_at"], expected_due_at)
    assert report["issued_at"] is None, (
        "an unissued report has no issued_at, got %r" % report["issued_at"]
    )
    assert report["turnaround_hours"] is None, (
        "turnaround is measured on the first issuance only, got %r"
        % report["turnaround_hours"]
    )
    assert report["amendment_count"] == 0, (
        "a fresh report has no amendments, got %r" % report["amendment_count"]
    )


def test_a_texas_structure_may_not_be_filed_on_the_florida_form(api):
    """The form must be the one the snapshotted jurisdiction mandates.

    PRD 2.10: "A report filed on any other state's form is not a compliant
    filing and is refused with `ERR_FORM_CODE_MISMATCH` (422)."

    Design: Corner/calculations/wdo_due_at_and_required_form_are_keyed_on_the_property_state
    """
    set_clock(api, CLOCK_START)
    prop, inspector = register_property_and_inspector(
        api, state_code="TX", square_footage=2200
    )
    graph = real_estate_graph(
        api, prop["id"], inspector["id"], closing_date="2026-09-15"
    )
    response = api.create_wdo_report(
        {"inspection_id": graph["id"], "form_code": STATE_FORM_MAP["FL"]},
        OFFICER_HEADERS,
    )
    validate_error(response, ERR_FORM_CODE_MISMATCH)


# ---------------------------------------------------------------------------
# Attached structures and the station target
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "has_attached_structures,expected_stations",
    [(True, 21), (False, 19)],
)
def test_attached_structures_add_two_stations(
    api, has_attached_structures, expected_stations
):
    """185 linear feet needs 19 stations, or 21 with attached structures.

    PRD 3.5: "it is the structure's `linear_footage` divided by a station spacing
    of 10 feet, raised to the next whole number if not already whole, plus 2
    extra stations when the structure has attached garages or porches."

    Design: Corner/calculations/attached_structures_add_two_stations_without_moving_the_price
    """
    set_clock(api, CLOCK_START)
    _, _, _, plan = _structure_with_plan(
        api,
        method=METHOD_BAIT_STATION,
        square_footage=2000,
        linear_footage=185,
        has_attached_structures=has_attached_structures,
    )
    assert plan["target_station_count"] == expected_stations, (
        "expected %d stations, got %r"
        % (expected_stations, plan["target_station_count"])
    )
    assert_money(plan["quoted_price_usd"], 1195.00)
    assert_money(plan["target_gallons"], 0.00)
    assert plan["escalated_station_count"] == 0, (
        "a proposed plan has escalated nothing, got %r"
        % plan["escalated_station_count"]
    )
    assert plan["retreat_required"] is False, (
        "a proposed plan raises no retreat obligation, got %r"
        % plan["retreat_required"]
    )


def test_attached_structures_do_not_move_the_quoted_price(api):
    """The porch changes the station count and nothing about the money.

    PRD 3.5: "A floor-area subtotal is accumulated across three brackets of
    heated area ... The method's base fee is added to that subtotal ... The
    running figure is multiplied by a construction multiplier."

    Design: Corner/calculations/attached_structures_add_two_stations_without_moving_the_price
    """
    set_clock(api, CLOCK_START)
    _, _, _, attached = _structure_with_plan(
        api,
        method=METHOD_BAIT_STATION,
        square_footage=2000,
        linear_footage=185,
        has_attached_structures=True,
    )
    _, _, _, detached = _structure_with_plan(
        api,
        method=METHOD_BAIT_STATION,
        square_footage=2000,
        linear_footage=185,
        has_attached_structures=False,
        address_line1="311 Detached Court",
    )
    assert attached["target_station_count"] == 21
    assert detached["target_station_count"] == 19
    assert attached["quoted_price_usd"] == pytest.approx(
        detached["quoted_price_usd"], abs=0.01
    ), (
        "the perimeter hardware count must not move the price: %r vs %r"
        % (attached["quoted_price_usd"], detached["quoted_price_usd"])
    )
    assert_money(attached["quoted_price_usd"], 1195.00)
