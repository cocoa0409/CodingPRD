"""Breadth probes over the declared calculations.

An ordered first-match chain, an input-set filter with three decoys, a
constant table keyed on unit type, a chronological tie-break, a pinned
discount waterfall, a weighted score with a banded penalty, and the two
projections that read the obligation ledger.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as a
from test_helpers import factories, fixtures
from test_helpers.constants import (
    AGREEMENT_STATUS_DRAFT,
    AGREEMENT_STATUS_QUALIFIED,
    CRITERION_LIQUEFACTION,
    CRITERION_SEISMIC,
    CRITERION_STATIC,
    DOC_SHA256_ALT,
    DOC_SHA256_THIRD,
    DOC_URI,
    DOC_URI_ALT,
    EVAL_STATUS_ISSUED,
    EVAL_VERDICT_SSI,
    EVENT_STATUS_DRAFT,
    EVENT_TYPE_DETECTION,
    HAZARD_HIGH,
    HAZARD_LOW,
    LINER_UNLINED,
    METHOD_CLOSURE_IN_PLACE,
    PARAM_BORON,
    PHASE_ASSESSMENT,
    PLAN_STATUS_DRAFT,
    POSTING_ANNUAL_GW_REPORT,
    POSTING_STABILITY_ASSESSMENT,
    POSTING_STATUS_WITHDRAWN,
    POSTURE_COMPLIANT,
    POSTURE_FROZEN,
    POSTURE_RESTRICTED,
    POSTURE_WATCH,
    PRODUCT_STRUCTURAL_FILL,
    STABILITY_ADEQUATE,
    STABILITY_DEFICIENT,
    TIMELINESS_PENDING,
    UNIT_TYPE_LANDFILL,
    VERDICT_DISQUALIFIED,
    VERDICT_RESTRICTED_DEMONSTRATION_REQUIRED,
    VERDICT_UNRESTRICTED,
)
from test_helpers.test_users import UTILITY_ADMIN_HEADERS

DISJOINT_WINDOWS = (
    ("2026-01-01", "2026-03-31"),
    ("2026-04-01", "2026-06-30"),
    ("2026-07-01", "2026-09-30"),
    ("2026-10-01", "2026-12-31"),
)


def read_assessment(api, assessment_id):
    return validate_success(api.get_stability_assessment(assessment_id, UTILITY_ADMIN_HEADERS))


def read_posting(api, posting_id):
    return validate_success(api.get_public_posting(posting_id, UTILITY_ADMIN_HEADERS))


def test_the_location_chain_stops_at_the_first_clause_that_matches(api):
    """Four sitings: one clean, one that trips every clause, one wetland, one lined.

    PRD: First, if `unstable_area_flag` is true the verdict is `DISQUALIFIED`. Otherwise, if `fault_distance_ft` is less than 200 feet the verdict is `DISQUALIFIED`. Otherwise, if `uppermost_aquifer_separation_ft` is less than 5 feet the verdict is `DISQUALIFIED`. Otherwise, if `wetland_distance_ft` is less than 500 feet **and** `hazard_potential_class` is either `SIGNIFICANT` or `HIGH`, the verdict is `RESTRICTED_DEMONSTRATION_REQUIRED`. Otherwise, if `seismic_pga_g` is greater than 0.10 g **and** `liner_class` is `UNLINED`, the verdict is again `RESTRICTED_DEMONSTRATION_REQUIRED`. If no clause matches, the verdict is `UNRESTRICTED`.
    PRD: All three of those numeric comparisons are strict: a fault at exactly 200 feet, a separation of exactly 5 feet and an acceleration of exactly 0.10 g each fail to trigger their clause.
    PRD: a unit whose siting came out `DISQUALIFIED` is immediately `RESTRICTED`, a unit that needs a demonstration is `WATCH`, and everything else is `COMPLIANT`
    Design: Corner/calculations/location_restriction_chain_stops_at_the_first_matching_clause
    """
    clean = fixtures.create_unit(api, "IMP-0121", unit_name="Ash Pond 121")
    all_bad = fixtures.create_unit(
        api,
        "IMP-0122",
        unit_name="Ash Pond 122",
        liner_class=LINER_UNLINED,
        hazard_potential_class=HAZARD_HIGH,
        uppermost_aquifer_separation_ft=2.00,
        wetland_distance_ft=100.00,
        seismic_pga_g=0.200,
        fault_distance_ft=100.00,
        unstable_area_flag=True,
    )
    wetland = fixtures.create_unit(
        api, "IMP-0123", unit_name="Ash Pond 123", wetland_distance_ft=400.00
    )
    seismic_lined = fixtures.create_unit(
        api,
        "IMP-0124",
        unit_name="Ash Pond 124",
        uppermost_aquifer_separation_ft=5.00,
        wetland_distance_ft=500.00,
        seismic_pga_g=0.150,
        fault_distance_ft=200.00,
    )

    assert clean["location_restriction_verdict"] == VERDICT_UNRESTRICTED
    assert clean["demonstration_required"] is False
    assert clean["compliance_posture"] == POSTURE_COMPLIANT

    assert all_bad["location_restriction_verdict"] == VERDICT_DISQUALIFIED
    assert all_bad["demonstration_required"] is False
    assert all_bad["compliance_posture"] == POSTURE_RESTRICTED

    assert wetland["location_restriction_verdict"] == VERDICT_RESTRICTED_DEMONSTRATION_REQUIRED
    assert wetland["demonstration_required"] is True
    assert wetland["compliance_posture"] == POSTURE_WATCH

    assert seismic_lined["location_restriction_verdict"] == VERDICT_UNRESTRICTED
    assert seismic_lined["demonstration_required"] is False
    assert seismic_lined["compliance_posture"] == POSTURE_COMPLIANT


def test_the_background_set_ignores_draft_out_of_window_and_other_parameter_rows(api):
    """Three 9.9000 decoys sit in the database and none of them may enter the limit.

    PRD: Eligible data comes only from the program's own **validated** rounds whose `sampled_on` falls inside the closed background window - on or after `background_window_start_on` and on or before `background_window_end_on`. Rounds still in draft or rejected contribute nothing, and results for any other constituent are ignored.
    PRD: Under `INTERWELL`, the contributing wells are every well of the unit whose `well_role` is `BACKGROUND`, whether that well is still certified or has since been decommissioned, and the compliance well's own history is excluded entirely.
    PRD: Under `PARAMETRIC_PREDICTION_INTERVAL`, the limit is the mean plus a coverage multiplier times the standard deviation, where the multiplier depends on how many background values there were: 3.187 when there are 4 or 5 values
    PRD: The measurement compared against the limit comes from a validated round dated **strictly after** `background_window_end_on`
    Design: Corner/calculations/background_limit_ignores_draft_out_of_window_and_other_parameter_rows
    """
    world = fixtures.seed_unit(api, "IMP-0125")
    wells = fixtures.install_standard_network(api, world["unit_id"], world["hydro_headers"])
    fixtures.configure_program(api, world["program_id"], world["hydro_headers"])
    fixtures.certify_network(api, world["program_id"], world["hydro_headers"], "2025-01-05")
    background_well = wells["BG-01"]["id"]
    compliance_well = wells["DG-01"]["id"]
    program_id = world["program_id"]
    hydro = world["hydro_headers"]

    first = fixtures.open_round(api, program_id, hydro, "BG-R1", "2025-02-10")
    fixtures.append_result(api, first["id"], background_well, 0.5000, hydro)
    fixtures.append_result(api, first["id"], background_well, 9.9000, hydro, PARAM_BORON)
    fixtures.close_round(api, first["id"], hydro, "2025-02-11")

    never_validated = fixtures.open_round(api, program_id, hydro, "BG-DRAFT", "2025-05-12")
    fixtures.append_result(api, never_validated["id"], background_well, 9.9000, hydro)

    for code, sampled_on, validated_on, value in (
        ("BG-R2", "2025-05-12", "2025-05-13", 0.6000),
        ("BG-R3", "2025-08-11", "2025-08-12", 0.5500),
        ("BG-R4", "2025-11-10", "2025-11-11", 0.5800),
    ):
        fixtures.validated_round(
            api,
            program_id,
            hydro,
            code,
            sampled_on,
            [(background_well, value)],
            validated_on=validated_on,
        )
    fixtures.validated_round(
        api,
        program_id,
        hydro,
        "BG-OUT",
        "2026-02-10",
        [(background_well, 9.9000)],
        validated_on="2026-02-11",
    )
    detection = fixtures.validated_round(
        api,
        program_id,
        hydro,
        "DET-R1",
        "2026-06-15",
        [(compliance_well, 0.9000)],
        EVENT_TYPE_DETECTION,
        validated_on="2026-06-16",
    )
    world["compliance_well_id"] = compliance_well

    evaluation = fixtures.issue_evaluation(api, world, "EV-FILTER")

    draft_round = fixtures.read_round(api, never_validated["id"], hydro)
    assert draft_round["status"] == EVENT_STATUS_DRAFT
    assert draft_round["result_count"] == 1

    assert evaluation["background_n"] == 4
    a.assert_four_dp(evaluation["background_mean"], 0.5575, "background_mean")
    a.assert_six_dp(evaluation["background_stdev"], 0.043493, "background_stdev")
    a.assert_four_dp(evaluation["background_upper_limit"], 0.6961, "background_upper_limit")
    assert evaluation["comparison_source_event_id"] == detection["id"]
    a.assert_four_dp(evaluation["comparison_value"], 0.9000, "comparison_value")
    assert evaluation["verdict"] == EVAL_VERDICT_SSI
    assert evaluation["status"] == EVAL_STATUS_ISSUED

    assert fixtures.read_program(api, program_id)["phase"] == PHASE_ASSESSMENT
    assert fixtures.read_unit(api, world["unit_id"])["compliance_posture"] == POSTURE_RESTRICTED


def test_the_base_closure_allowance_is_keyed_on_unit_type_and_clamps_the_day(api):
    """The same cessation date yields 2028-06-30 for a landfill and 2030-12-31 for a pond.

    PRD: `closure_deadline_date` is computed from `cessation_date` by advancing the calendar by the base allowance for the unit type - 60 months for a surface impoundment, 30 months for a landfill - plus the current granted extension total, which at registration is nothing. Calendar advancement keeps the day of month and clamps to the last day of a shorter target month, so advancing 31 January by one month lands on 28 February in a non-leap year.
    Design: Corner/calculations/base_closure_months_differ_by_unit_type_and_clamp_the_day_of_month
    """
    landfill = fixtures.create_unit(
        api,
        "LFL-0126",
        unit_name="Ash Landfill 126",
        unit_type=UNIT_TYPE_LANDFILL,
        hazard_potential_class=HAZARD_LOW,
        original_ash_in_place_tons=200000,
        cessation_date="2025-12-31",
    )
    impoundment = fixtures.create_unit(
        api, "IMP-0126", unit_name="Ash Pond 126", cessation_date="2025-12-31"
    )
    short_month_landfill = fixtures.create_unit(
        api,
        "LFL-0127",
        unit_name="Ash Landfill 127",
        unit_type=UNIT_TYPE_LANDFILL,
        hazard_potential_class=HAZARD_LOW,
        original_ash_in_place_tons=200000,
        cessation_date="2026-02-28",
    )

    a.assert_date(landfill["closure_deadline_date"], "2028-06-30", "closure_deadline_date")
    a.assert_date(impoundment["closure_deadline_date"], "2030-12-31", "closure_deadline_date")
    a.assert_date(
        short_month_landfill["closure_deadline_date"], "2028-08-28", "closure_deadline_date"
    )
    for label, unit in (
        ("landfill", landfill),
        ("impoundment", impoundment),
        ("short_month_landfill", short_month_landfill),
    ):
        assert unit["granted_extension_months"] == 0, label
        assert unit["closure_timeliness"] == TIMELINESS_PENDING, label
        assert unit["compliance_posture"] == POSTURE_COMPLIANT, label


def test_the_governing_assessment_is_the_latest_assessed_on_then_the_latest_created_at(api):
    """A back-dated deficient filing does not govern; a same-day later filing does.

    PRD: Across all of a unit's assessments - including deficient ones, none are excluded - the governing row is the one with the latest `assessed_on`, with a later `created_at` breaking a tie. Its verdict becomes the unit's `governing_stability_verdict`; a unit with no assessment at all reports `UNASSESSED`. The governing row carries `superseded` false and every other row of that unit carries `superseded` true.
    PRD: It sets `stability_posting_due_date` to the governing assessment's `assessed_on` plus 30 days - re-derived from whichever row now governs, not from the row just filed, so back-dating an assessment leaves the obligation date where the governing row put it.
    PRD: A static factor below 1.50 contributes `STATIC`; a seismic factor below 1.00 contributes `SEISMIC`; a liquefaction factor below 1.20 contributes `LIQUEFACTION`.
    Design: Corner/calculations/governing_stability_verdict_follows_assessed_on_then_created_at
    """
    world = fixtures.seed_unit(api, "IMP-0128")

    newest = fixtures.file_stability(api, world, "2026-07-20")
    assert newest["verdict"] == STABILITY_ADEQUATE
    a.assert_string_list(newest["deficient_criteria"], [], "deficient_criteria")
    assert newest["superseded"] is False
    a.assert_append_only(newest, "stability_assessment")
    after_first = fixtures.read_unit(api, world["unit_id"])
    assert after_first["governing_stability_verdict"] == STABILITY_ADEQUATE
    a.assert_date(
        after_first["stability_posting_due_date"], "2026-08-19", "stability_posting_due_date"
    )

    backdated = fixtures.file_stability(
        api,
        world,
        "2026-06-01",
        factor_of_safety_static=1.00,
        factor_of_safety_seismic=0.50,
        factor_of_safety_liquefaction=0.60,
    )
    assert backdated["verdict"] == STABILITY_DEFICIENT
    a.assert_string_list(
        backdated["deficient_criteria"],
        [CRITERION_STATIC, CRITERION_SEISMIC, CRITERION_LIQUEFACTION],
        "deficient_criteria",
    )
    assert read_assessment(api, backdated["id"])["superseded"] is True
    assert read_assessment(api, newest["id"])["superseded"] is False
    after_backdating = fixtures.read_unit(api, world["unit_id"])
    assert after_backdating["governing_stability_verdict"] == STABILITY_ADEQUATE
    a.assert_date(
        after_backdating["stability_posting_due_date"], "2026-08-19", "stability_posting_due_date"
    )
    assert after_backdating["compliance_posture"] == POSTURE_WATCH

    tiebreak = fixtures.file_stability(api, world, "2026-07-20", factor_of_safety_static=1.40)
    assert tiebreak["verdict"] == STABILITY_DEFICIENT
    a.assert_string_list(tiebreak["deficient_criteria"], [CRITERION_STATIC], "deficient_criteria")
    assert read_assessment(api, tiebreak["id"])["superseded"] is False
    assert read_assessment(api, newest["id"])["superseded"] is True
    final = fixtures.read_unit(api, world["unit_id"])
    assert final["governing_stability_verdict"] == STABILITY_DEFICIENT
    assert final["compliance_posture"] == POSTURE_FROZEN


def test_capital_is_a_year_zero_bucket_and_only_the_care_stream_discounts(api):
    """The 30-year care stream discounts to 19,600,444 cents and capital never does.

    PRD: The **discounted** variant treats the capital outlay as a payment made in year zero and never discounts it, then discounts each of the care years 1 through the care horizon at 3 percent per year. The rounding order here is pinned and consequential: each individual year's discounted care payment is rounded half up to whole cents *first*, and only then are those rounded per-year amounts added together; the capital outlay is added to that sum last and exactly.
    PRD: each method's nominal total is its capital outlay plus its annual care cost multiplied by the number of care years
    PRD: it is the absolute difference between the two present values, expressed as a percentage of the larger of the two present values, rounded half up to 2 decimal places
    Design: Corner/calculations/capital_is_a_year_zero_bucket_and_only_the_care_stream_is_discounted
    """
    world = fixtures.seed_unit(api, "IMP-0129")

    plan = fixtures.draft_plan(api, world, "CP-0129")

    assert plan["status"] == PLAN_STATUS_DRAFT
    assert plan["return_count"] == 0
    a.assert_cents(plan["in_place_nominal_usd_cents"], 130000000, "in_place_nominal_usd_cents")
    a.assert_cents(plan["removal_nominal_usd_cents"], 930000000, "removal_nominal_usd_cents")
    a.assert_cents(plan["in_place_pv_usd_cents"], 119600444, "in_place_pv_usd_cents")
    a.assert_cents(plan["removal_pv_usd_cents"], 919600444, "removal_pv_usd_cents")
    assert plan["removal_pv_usd_cents"] - plan["in_place_pv_usd_cents"] == 800000000
    a.assert_two_dp(plan["cost_variance_pct"], 86.99, "cost_variance_pct")
    assert plan["recommended_method"] == METHOD_CLOSURE_IN_PLACE
    assert plan["selected_method"] == plan["recommended_method"]


def test_the_haul_band_and_the_product_bonus_move_the_reuse_score(api):
    """Four agreements sharing one chemistry, so only the two additive terms move.

    PRD: A product bonus is then added - 8 points for `CONCRETE_POZZOLAN`, 4 points for `WALLBOARD`, and nothing for `STRUCTURAL_FILL` or `ROADBASE` - and a haul penalty is subtracted: 10 points when `haul_distance_miles` is greater than 150, otherwise 5 points when it is greater than 75, otherwise nothing. Both haul bands are strict, so exactly 75 miles and exactly 150 miles incur no penalty while 76 and 151 miles do.
    PRD: The market component is `market_price_usd_cents_per_ton` divided by 50, capped at 100
    PRD: a score of at least 50.00 moves it `DRAFT` -> `QUALIFIED`
    Design: Corner/calculations/haul_penalty_band_and_product_bonus_move_the_reuse_score
    """
    world = fixtures.seed_unit(api, "IMP-0130")
    windows = [
        {"commitment_start_on": start, "commitment_end_on": end} for start, end in DISJOINT_WINDOWS
    ]
    on_the_band = fixtures.draft_agreement(
        api, world, "AGR-0130-A", haul_distance_miles=75, **windows[0]
    )
    one_mile_past = fixtures.draft_agreement(
        api, world, "AGR-0130-B", haul_distance_miles=76, **windows[1]
    )
    no_bonus = fixtures.draft_agreement(
        api,
        world,
        "AGR-0130-C",
        product_type=PRODUCT_STRUCTURAL_FILL,
        offtaker_name="Piedmont Grading",
        haul_distance_miles=75,
        **windows[2],
    )
    capped_market = fixtures.draft_agreement(
        api,
        world,
        "AGR-0130-D",
        market_price_usd_cents_per_ton=6000,
        haul_distance_miles=75,
        **windows[3],
    )

    qualified = validate_success(
        api.qualify_reuse_agreement(
            on_the_band["id"],
            factories.qualify_agreement_payload("2026-08-01"),
            world["civil_headers"],
        )
    )

    a.assert_two_dp(on_the_band["qualification_score"], 70.30, "qualification_score")
    assert on_the_band["meets_astm_c618_class_f"] is True
    a.assert_two_dp(one_mile_past["qualification_score"], 65.30, "qualification_score")
    a.assert_two_dp(no_bonus["qualification_score"], 62.30, "qualification_score")
    a.assert_two_dp(capped_market["qualification_score"], 75.70, "qualification_score")

    assert qualified["status"] == AGREEMENT_STATUS_QUALIFIED
    assert qualified["qualified_by"] == world["civil_id"]
    a.assert_date(qualified["qualified_on"], "2026-08-01", "qualified_on")
    for label, agreement in (
        ("one_mile_past", one_mile_past),
        ("no_bonus", no_bonus),
        ("capped_market", capped_market),
    ):
        current = validate_success(api.get_reuse_agreement(agreement["id"], UTILITY_ADMIN_HEADERS))
        assert current["status"] == AGREEMENT_STATUS_DRAFT, label
        assert current["shipped_tons_total"] == 0, label


def test_the_obligation_ledger_replays_after_the_clock_moves_and_after_a_withdrawal(api):
    """Overdue reads [], then [STABILITY_ASSESSMENT], then [] again, then overdue once more.

    PRD: `overdue_posting_types` lists every posting type for which the unit carries a non-null obligation date, no `POSTED` posting of that type exists, and the current date is strictly past the obligation date.
    PRD: `late_posting_count` counts the unit's `POSTED` postings whose `days_late` exceeds 0.
    PRD: `satisfied_obligation` is true exactly when the posting's `status` is `POSTED` and the unit carries a non-null obligation date for that type - which means an annual groundwater report never satisfies an obligation
    PRD: Since the withdrawn document no longer counts as a `POSTED` posting of its type, the obligation it discharged becomes unmet again, and if its due date has already passed the type re-enters `overdue_posting_types` and the unit's posture hardens accordingly
    Design: Corner/calculations/posting_ledger_replays_after_the_clock_moves_and_after_a_withdrawal
    """
    world = fixtures.seed_unit(api, "IMP-0131")
    fixtures.file_stability(api, world, "2026-07-15")

    pending = fixtures.read_unit(api, world["unit_id"])
    a.assert_date(pending["stability_posting_due_date"], "2026-08-14", "stability_posting_due_date")
    a.assert_string_list(pending["overdue_posting_types"], [], "overdue_posting_types")
    assert pending["late_posting_count"] == 0
    assert pending["compliance_posture"] == POSTURE_WATCH

    clock = fixtures.set_clock(api, "2026-08-20T00:00:00Z")
    a.assert_instant(clock["current_utc"], "2026-08-20T00:00:00Z", "current_utc")
    overdue = fixtures.read_unit(api, world["unit_id"])
    a.assert_string_list(
        overdue["overdue_posting_types"], [POSTING_STABILITY_ASSESSMENT], "overdue_posting_types"
    )
    assert overdue["compliance_posture"] == POSTURE_FROZEN

    stability_posting = fixtures.post_document(
        api, world, POSTING_STABILITY_ASSESSMENT, "2026-08-20"
    )
    assert stability_posting["satisfied_obligation"] is True
    assert stability_posting["days_late"] == 6
    discharged = fixtures.read_unit(api, world["unit_id"])
    a.assert_string_list(discharged["overdue_posting_types"], [], "overdue_posting_types")
    assert discharged["late_posting_count"] == 1
    assert discharged["compliance_posture"] == POSTURE_COMPLIANT

    annual = fixtures.post_document(
        api,
        world,
        POSTING_ANNUAL_GW_REPORT,
        "2026-08-20",
        document_uri=DOC_URI_ALT,
        document_sha256=DOC_SHA256_ALT,
    )
    assert annual["satisfied_obligation"] is False
    assert annual["days_late"] == 0
    assert fixtures.read_unit(api, world["unit_id"])["late_posting_count"] == 1

    withdrawn = fixtures.withdraw_document(api, stability_posting["id"], "2026-08-20")
    assert withdrawn["status"] == POSTING_STATUS_WITHDRAWN
    reread = read_posting(api, stability_posting["id"])
    assert reread["satisfied_obligation"] is False
    assert reread["days_late"] == 0
    reopened = fixtures.read_unit(api, world["unit_id"])
    a.assert_string_list(
        reopened["overdue_posting_types"], [POSTING_STABILITY_ASSESSMENT], "overdue_posting_types"
    )
    assert reopened["late_posting_count"] == 0
    assert reopened["compliance_posture"] == POSTURE_FROZEN


def test_frozen_outranks_restricted_and_clearing_it_falls_back_to_restricted(api):
    """A permanent siting cause under a temporary posting cause, then only the latter cleared.

    PRD: The posture is evaluated as three predicates and then resolved by strict precedence, first match winning: if the frozen predicate holds the posture is `FROZEN`; otherwise if the restricted predicate holds it is `RESTRICTED`; otherwise if the watch predicate holds it is `WATCH`; otherwise it is `COMPLIANT`.
    PRD: The **restricted** predicate holds when the unit's monitoring program is in either the `ASSESSMENT` or the `CORRECTIVE_ACTION` phase, or when the unit's `location_restriction_verdict` is `DISQUALIFIED`.
    PRD: This verdict is frozen at registration: it is stored once and is never recomputed, no matter what later happens to the unit.
    Design: Corner/calculations/posture_precedence_puts_frozen_above_restricted_and_propagates_both_ways
    """
    world = fixtures.seed_unit(api, "IMP-0132", unstable_area_flag=True)
    assert world["unit"]["location_restriction_verdict"] == VERDICT_DISQUALIFIED
    assert world["unit"]["compliance_posture"] == POSTURE_RESTRICTED

    fixtures.file_stability(api, world, "2026-07-15")
    pending = fixtures.read_unit(api, world["unit_id"])
    a.assert_date(pending["stability_posting_due_date"], "2026-08-14", "stability_posting_due_date")
    assert pending["governing_stability_verdict"] == STABILITY_ADEQUATE
    assert pending["compliance_posture"] == POSTURE_RESTRICTED

    fixtures.set_clock(api, "2026-08-20T00:00:00Z")
    frozen = fixtures.read_unit(api, world["unit_id"])
    a.assert_string_list(
        frozen["overdue_posting_types"], [POSTING_STABILITY_ASSESSMENT], "overdue_posting_types"
    )
    assert frozen["compliance_posture"] == POSTURE_FROZEN

    fixtures.post_document(
        api,
        world,
        POSTING_STABILITY_ASSESSMENT,
        "2026-08-20",
        document_uri=DOC_URI,
        document_sha256=DOC_SHA256_THIRD,
    )

    restored = fixtures.read_unit(api, world["unit_id"])
    a.assert_string_list(restored["overdue_posting_types"], [], "overdue_posting_types")
    assert restored["compliance_posture"] == POSTURE_RESTRICTED
    assert restored["location_restriction_verdict"] == VERDICT_DISQUALIFIED
    assert restored["demonstration_required"] is False
    assert restored["governing_stability_verdict"] == STABILITY_ADEQUATE
