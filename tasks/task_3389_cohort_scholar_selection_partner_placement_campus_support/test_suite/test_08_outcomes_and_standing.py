"""Partner outcome rates (census vs rolling) and standing derivation
(PRD §3.9)."""
import pytest

from test_helpers import (
    TEST_USERS,
    accept_offer,
    activate_agreement,
    api_client,
    assert_outcomes,
    complete_all_training,
    create_cohort,
    create_mentor,
    create_offer,
    create_selected_nominee,
    draft_agreement,
    get_scholar_for_nominee,
    scholar_lifecycle,
    setup_city_with_partner,
    setup_college,
    validate_success,
)

_ADMIN = TEST_USERS["program_admin_headers"]


class TestEmptyOutcomes:
    def test_outcomes_null_when_no_completed_cohort(self, api):
        """PRD §3.9: "the rate is null when the variant's set is empty."
        PRD §3.9: "A null census retention — an empty census — never changes
        standing."
        PRD §3.3: "the college starts in `ACTIVE` status with
        `renewed_cycles_count` at 0."

        Design: Corner/calculations/outcomes_null_when_no_completed_cohort
        """
        college = setup_college()
        outcomes = validate_success(api.get_college_outcomes(college["id"], _ADMIN))
        assert_outcomes(outcomes)
        assert outcomes["retention_bps_census"] is None
        assert outcomes["graduation_bps_census"] is None
        assert outcomes["retention_bps_rolling"] is None
        assert outcomes["graduation_bps_rolling"] is None
        assert outcomes["college_status"] == "ACTIVE", "a null census never moves standing"


def _setup_census_rolling_divergence(api):
    """One college, two cohorts (cycles 2027 and 2028), same city program.

    Cohort 1: A,B fully trained and matriculated; C withdrawn at the training
    gate (never matriculated); A then RETAINED -> GRADUATED; B then WITHDRAWN
    post-matriculation -> cohort 1 COMPLETED (census retention 5000 -> the
    college flips to PROBATION).
    Cohort 2: D fully trained and matriculated; E,F withdrawn at the gate;
    cohort 2 stays MATRICULATED (D non-terminal).
    Returns the college dict."""
    program, partner = setup_city_with_partner(quota=20)
    college = setup_college()
    agr1 = draft_agreement(college, cycle="2027", cohort_size=3)
    activate_agreement(agr1["id"])
    agr2 = draft_agreement(college, cycle="2028", cohort_size=3)
    activate_agreement(agr2["id"])
    mentor = create_mentor(college["id"])
    coh1 = create_cohort(agr1, program, mentor)
    coh2 = create_cohort(agr2, program, mentor)

    scholars = {}
    for name, cohort in (
        ("A", coh1), ("B", coh1), ("C", coh1),
        ("D", coh2), ("E", coh2), ("F", coh2),
    ):
        nominee = create_selected_nominee(program, partner, f"Nom {name}")
        offer = create_offer(nominee["id"], cohort["id"])
        accept_offer(offer)
        scholars[name] = get_scholar_for_nominee(nominee["id"])

    for name in ("A", "B", "D"):
        complete_all_training(scholars[name]["id"])

    validate_success(api.matriculate_cohort(coh1["id"], _ADMIN))
    validate_success(api.matriculate_cohort(coh2["id"], _ADMIN))

    scholar_lifecycle(scholars["A"]["id"], to_enrollment_status="RETAINED")
    scholar_lifecycle(scholars["A"]["id"], to_enrollment_status="GRADUATED")
    scholar_lifecycle(scholars["B"]["id"], to_enrollment_status="WITHDRAWN")
    return college


class TestCensusVsRollingDivergence:
    def test_census_rates_and_probation_standing(self, api):
        """PRD §3.9: "The census variant counts only scholars whose cohort has
        reached `COMPLETED`; it is the authoritative variant, driving both
        standing derivation and renewal decisions."
        PRD §3.9: "For each variant, the retention rate in basis points is the
        count of the variant's scholars whose `enrollment_status` is
        `RETAINED` or `GRADUATED`, multiplied by 10000, divided by the
        variant's total scholar count, and rounded half-up to an integer".
        PRD §3.9: "An `ACTIVE` college whose census retention falls below 7000
        basis points moves to `PROBATION`".

        Design: Difficulty/dual_variant_calc/partner_outcomes_census_vs_rolling_divergence
        """
        college = _setup_census_rolling_divergence(api)
        outcomes = validate_success(api.get_college_outcomes(college["id"], _ADMIN))
        assert_outcomes(outcomes)
        # Census set = {A GRADUATED, B WITHDRAWN} over the COMPLETED cohort.
        assert outcomes["retention_bps_census"] == 5000, (
            "round_half_up(10000 * 1 / 2); C never matriculated and is excluded"
        )
        assert outcomes["graduation_bps_census"] == 5000, (
            "graduation set {A, B}: 1 GRADUATED of 2"
        )
        assert outcomes["college_status"] == "PROBATION", (
            "cohort-1 completion left census retention 5000 < 7000"
        )

    def test_rolling_variant_diverges_on_uncompleted_cohort(self, api):
        """PRD §3.9: "The rolling variant counts scholars of cohorts in any
        status — `FORMING`, `LOCKED`, `MATRICULATED`, or `COMPLETED` — giving a
        live dashboard view that diverges from census whenever a
        not-yet-completed cohort has matriculated scholars."
        PRD §3.9: "Only scholars with `ever_matriculated` set to true enter any
        outcome set: a scholar who withdrew during the `PRE_COLLEGIATE` phase
        never matriculated and is excluded from every numerator and every
        denominator."

        Design: Difficulty/dual_variant_calc/partner_outcomes_census_vs_rolling_divergence
        """
        college = _setup_census_rolling_divergence(api)
        outcomes = validate_success(api.get_college_outcomes(college["id"], _ADMIN))
        # Rolling set = {A, B, D} (D matriculated in the still-MATRICULATED
        # cohort 2); C, E, F withdrew pre-matriculation and are excluded.
        assert outcomes["retention_bps_rolling"] == 3333, (
            "round_half_up(10000 * 1 / 3) over S={A,B,D}"
        )
        assert outcomes["graduation_bps_rolling"] == 5000, (
            "D has no terminal outcome, so the graduation set is {A,B} in both variants"
        )
        assert outcomes["retention_bps_rolling"] != outcomes["retention_bps_census"], (
            "the two variants diverge (3333 vs 5000) on one consistent database"
        )
