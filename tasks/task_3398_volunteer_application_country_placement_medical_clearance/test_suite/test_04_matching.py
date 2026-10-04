"""The match-list selector: strict vs preference-weighted score variants,
the empty-requirements boundary, and the eligibility filter."""

import pytest

from test_helpers import (
    DEFAULT_CLOCK_START,
    TEST_USERS,
    api_client,
    create_applicant,
    create_application,
    create_assignment_opening,
    create_country_program,
    set_clock,
    submit_application,
    validate_success,
)

PLACER = TEST_USERS["placement_officer_headers"]


def _matches(application_id):
    resp = api_client.get_application_matches(application_id, PLACER)
    data = validate_success(resp, 200)
    return data["matches"]


class TestStrictVsWeightedDivergence:
    def test_strict_one_weighted_lower_at_rank_one(self):
        """PRD §3.4: "The weighted score blends in preference signals:
        seven-tenths of the strict coverage, plus two-tenths of a sector
        bonus that is 1.0 when the opening's `sector` appears among the
        application's `sector_preferences` and 0.0 otherwise, plus one-tenth
        of a country bonus, the sum rounded half-up to two decimal places."
        PRD §3.4: "a program ranked first earns 1.0, and each step down the
        ranking deducts one-quarter — 0.75 for the second choice, 0.5 for the
        third, 0.25 for the fourth — and a program absent from a non-empty
        list earns nothing."

        Design: Difficulty/dual_variant_calc/skill_match_strict_vs_preference_weighted_divergence
        """
        set_clock(DEFAULT_CLOCK_START)
        prog_ec = create_country_program(country_code="EC", name="Ecuador",
                                         medical_support_tier=2)
        prog_pe = create_country_program(country_code="PE", name="Peru",
                                         medical_support_tier=3)
        opening = create_assignment_opening(prog_pe["id"])
        ana = create_applicant()
        app = create_application(
            ana["id"],
            sector_preferences=["EDUCATION"],
            country_preference_ids=[prog_ec["id"], prog_pe["id"]],
        )
        submit_application(app["id"], ana["id"])

        matches = _matches(app["id"])
        assert len(matches) == 1, "EC has no openings; only the PE opening is eligible"
        match = matches[0]
        assert match["assignment_opening_id"] == opening["id"]
        assert match["country_program_id"] == prog_pe["id"]
        assert match["strict_score"] == pytest.approx(1.0, abs=1e-9)
        # 0.7*1.0 + 0.2*1.0 + 0.1*0.75 = 0.975 -> round half-up to 0.98.
        assert match["weighted_score"] == pytest.approx(0.98, abs=1e-9)
        assert match["strict_score"] != match["weighted_score"], \
            "the two variants must diverge on identical inputs"

    def test_strict_one_weighted_lower_at_rank_two(self):
        """PRD §3.4: "Strict coverage is the fraction of the opening's
        `required_skills` that the applicant's `skills` list covers — the
        number of skills appearing in both lists divided by the number of
        required skills, with an empty requirements list defined as exactly
        1.0."
        PRD §3.4: "a program ranked first earns 1.0, and each step down the
        ranking deducts one-quarter — 0.75 for the second choice, 0.5 for the
        third, 0.25 for the fourth — and a program absent from a non-empty
        list earns nothing."

        Design: Difficulty/dual_variant_calc/skill_match_strict_vs_preference_weighted_divergence
        """
        set_clock(DEFAULT_CLOCK_START)
        prog_ec = create_country_program(country_code="EC", name="Ecuador",
                                         medical_support_tier=2)
        prog_co = create_country_program(country_code="CO", name="Colombia",
                                         medical_support_tier=2)
        prog_pe = create_country_program(country_code="PE", name="Peru",
                                         medical_support_tier=3)
        opening = create_assignment_opening(prog_pe["id"])
        ana = create_applicant()
        app = create_application(
            ana["id"],
            sector_preferences=["EDUCATION"],
            country_preference_ids=[prog_ec["id"], prog_co["id"], prog_pe["id"]],
        )
        submit_application(app["id"], ana["id"])

        matches = _matches(app["id"])
        assert len(matches) == 1
        match = matches[0]
        assert match["assignment_opening_id"] == opening["id"]
        assert match["strict_score"] == pytest.approx(1.0, abs=1e-9)
        # PE is the third choice: 0.7*1.0 + 0.2*1.0 + 0.1*0.5 = 0.95.
        assert match["weighted_score"] == pytest.approx(0.95, abs=1e-9)
        assert match["strict_score"] != match["weighted_score"]


class TestEmptyRequiredSkillsBoundary:
    def test_empty_required_skills_with_open_country_preferences(self):
        """PRD §3.4: "Strict coverage is the fraction of the opening's
        `required_skills` that the applicant's `skills` list covers — the
        number of skills appearing in both lists divided by the number of
        required skills, with an empty requirements list defined as exactly
        1.0."
        PRD §3.4: "The country bonus rewards ranked preference: an empty
        preference list earns one-half, reflecting willingness to serve
        anywhere; a program ranked first earns 1.0, and each step down the
        ranking deducts one-quarter — 0.75 for the second choice, 0.5 for the
        third, 0.25 for the fourth — and a program absent from a non-empty
        list earns nothing."

        Design: Difficulty/boundary_precision_check/empty_required_skills_match_defined_as_full_coverage
        """
        set_clock(DEFAULT_CLOCK_START)
        program = create_country_program(country_code="PE", name="Peru")
        opening = create_assignment_opening(
            program["id"], sector="HEALTH", title="Community Health Promoter",
            required_skills=[], seats_total=1)
        ana = create_applicant(skills=["NURSING"])
        app = create_application(ana["id"], sector_preferences=["HEALTH"])
        submit_application(app["id"], ana["id"])

        matches = _matches(app["id"])
        assert len(matches) == 1, \
            "an empty required_skills list must not exclude the opening"
        match = matches[0]
        assert match["assignment_opening_id"] == opening["id"]
        assert match["strict_score"] == pytest.approx(1.0, abs=1e-9), \
            "empty requirements are defined as full coverage"
        # 0.7*1.0 + 0.2*1.0 + 0.1*0.5 (empty country preferences) = 0.95.
        assert match["weighted_score"] == pytest.approx(0.95, abs=1e-9)

    def test_empty_required_skills_with_preferred_country(self):
        """PRD §3.4: "Strict coverage is the fraction of the opening's
        `required_skills` that the applicant's `skills` list covers — the
        number of skills appearing in both lists divided by the number of
        required skills, with an empty requirements list defined as exactly
        1.0."
        PRD §3.4: "a program ranked first earns 1.0, and each step down the
        ranking deducts one-quarter — 0.75 for the second choice, 0.5 for the
        third, 0.25 for the fourth — and a program absent from a non-empty
        list earns nothing."

        Design: Difficulty/boundary_precision_check/empty_required_skills_match_defined_as_full_coverage
        """
        set_clock(DEFAULT_CLOCK_START)
        program = create_country_program(country_code="PE", name="Peru")
        opening = create_assignment_opening(
            program["id"], sector="HEALTH", title="Community Health Promoter",
            required_skills=[], seats_total=1)
        ana = create_applicant(skills=["NURSING"])
        app = create_application(
            ana["id"],
            sector_preferences=["HEALTH"],
            country_preference_ids=[program["id"]],
        )
        submit_application(app["id"], ana["id"])

        matches = _matches(app["id"])
        assert len(matches) == 1
        match = matches[0]
        assert match["assignment_opening_id"] == opening["id"]
        assert match["strict_score"] == pytest.approx(1.0, abs=1e-9)
        # 0.7*1.0 + 0.2*1.0 + 0.1*1.0 (rank-1 country) = 1.00.
        assert match["weighted_score"] == pytest.approx(1.0, abs=1e-9)


class TestEligibilityFilter:
    def test_matches_excludes_skill_gap_and_unpreferred_country(self):
        """PRD §3.4: "The list is a selector over every assignment opening in
        the system: an opening is a candidate when it is `OPEN`, its
        `invitation_issue_deadline` has not passed — which the sweep of §2.4
        guarantees for every `OPEN` opening — its held plus committed seats
        remain strictly below `seats_total`, the applicant's strict skill
        coverage of it is exactly 1.0, and the applicant's country
        preferences are either empty or contain the opening's program."

        Design: Corner/calculations/matches_excludes_skill_gap_and_unpreferred_country
        """
        set_clock(DEFAULT_CLOCK_START)
        prog_pe = create_country_program(country_code="PE", name="Peru")
        prog_ec = create_country_program(country_code="EC", name="Ecuador",
                                         medical_support_tier=2)
        o1 = create_assignment_opening(prog_pe["id"], title="O1")  # eligible
        create_assignment_opening(
            prog_pe["id"], sector="HEALTH", title="O2",
            required_skills=["NURSING"], seats_total=1)  # skill gap
        create_assignment_opening(
            prog_ec["id"], sector="HEALTH", title="O3",
            required_skills=[], seats_total=1)  # country not preferred
        ana = create_applicant()  # skills: [TEACHING_ENGLISH]
        app = create_application(
            ana["id"],
            sector_preferences=["EDUCATION", "HEALTH"],
            country_preference_ids=[prog_pe["id"]],
        )
        submit_application(app["id"], ana["id"])

        matches = _matches(app["id"])
        assert [m["assignment_opening_id"] for m in matches] == [o1["id"]], \
            "skill-gapped and country-mismatched openings must be filtered out"
