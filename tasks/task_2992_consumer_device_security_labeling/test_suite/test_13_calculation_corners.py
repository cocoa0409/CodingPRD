"""Calculation corners: score input sets, pinned rounding order, program
evaluation rates and the retailer participation thresholds.

Every catalogue in this module is authored explicitly because the corner being
pinned depends on particular criterion weights, so the shared five-criterion
catalogue would not exercise it.
"""
from test_helpers import (
    CONSUMER_HEADERS,
    DEFAULT_CLOCK,
    api_client,
    assert_score,
    assert_status,
    factories,
    fixtures,
    validate_success,
)

# A tier whose approval bar sits at 70.00 so every claim in this module clears
# it and the assertion under test is the arithmetic, not the approval gate.
CALC_TIER_OVERRIDES = {"min_overall_score": 70.00}
CALC_CATEGORY_OVERRIDES = {"min_support_period_days": 180}

PRODUCT_OVERRIDES = {
    "model_name": "Speaker One",
    "sku": "SPK-001",
    "firmware_version": "1.0.0",
    "declared_support_period_end": "2029-08-01T00:00:00Z",
    "update_policy_disclosed": True,
    "retail_units_shipped": 1000,
}

SPONSOR_OVERRIDES = {
    "legal_name": "Acme Devices",
    "contact_email": "ops@acme.example",
    "enterprise_class": "SMALL",
    "annual_us_revenue_cents": 900000000,
}

# AUTH-2 carries weight 30 and is deliberately left unanswered below, so the
# AUTHENTICATION area is scored from AUTH-1 alone.
UNEVEN_AUTHENTICATION_CATALOGUE = [
    {
        "criterion_code": "AUTH-1",
        "practice_area": "AUTHENTICATION",
        "weight": 10,
        "requires_lab_verification": False,
        "criterion_text": "Unique per-device credentials",
    },
    {
        "criterion_code": "AUTH-2",
        "practice_area": "AUTHENTICATION",
        "weight": 30,
        "requires_lab_verification": False,
        "criterion_text": "Multi-factor administrative access",
    },
    {
        "criterion_code": "UPD-1",
        "practice_area": "SOFTWARE_UPDATE",
        "weight": 10,
        "requires_lab_verification": False,
        "criterion_text": "Signed firmware updates",
    },
    {
        "criterion_code": "DAT-1",
        "practice_area": "DATA_PROTECTION",
        "weight": 10,
        "requires_lab_verification": False,
        "criterion_text": "Encryption of data at rest",
    },
    {
        "criterion_code": "VLN-1",
        "practice_area": "VULN_DISCLOSURE",
        "weight": 10,
        "requires_lab_verification": False,
        "criterion_text": "Published disclosure contact",
    },
]

# AUTHENTICATION lands on 25/32 = 78.125 and DATA_PROTECTION on 20/30 =
# 66.6666..., the two ratios that expose the pinned rounding order.
HALF_CENT_CATALOGUE = [
    {
        "criterion_code": "AUTH-1",
        "practice_area": "AUTHENTICATION",
        "weight": 25,
        "requires_lab_verification": False,
        "criterion_text": "Unique per-device credentials",
    },
    {
        "criterion_code": "AUTH-2",
        "practice_area": "AUTHENTICATION",
        "weight": 7,
        "requires_lab_verification": False,
        "criterion_text": "Multi-factor administrative access",
    },
    {
        "criterion_code": "UPD-1",
        "practice_area": "SOFTWARE_UPDATE",
        "weight": 10,
        "requires_lab_verification": False,
        "criterion_text": "Signed firmware updates",
    },
    {
        "criterion_code": "DAT-1",
        "practice_area": "DATA_PROTECTION",
        "weight": 20,
        "requires_lab_verification": False,
        "criterion_text": "Encryption of data at rest",
    },
    {
        "criterion_code": "DAT-2",
        "practice_area": "DATA_PROTECTION",
        "weight": 10,
        "requires_lab_verification": False,
        "criterion_text": "Data minimisation in telemetry",
    },
    {
        "criterion_code": "VLN-1",
        "practice_area": "VULN_DISCLOSURE",
        "weight": 10,
        "requires_lab_verification": False,
        "criterion_text": "Published disclosure contact",
    },
]

# Four self-declared criteria of equal weight: every area scores 100.00, which
# keeps the arithmetic out of the way of the evaluation and retailer corners.
FLAT_CATALOGUE = [
    {
        "criterion_code": "AUTH-1",
        "practice_area": "AUTHENTICATION",
        "weight": 10,
        "requires_lab_verification": False,
        "criterion_text": "Unique per-device credentials",
    },
    {
        "criterion_code": "UPD-1",
        "practice_area": "SOFTWARE_UPDATE",
        "weight": 10,
        "requires_lab_verification": False,
        "criterion_text": "Signed firmware updates",
    },
    {
        "criterion_code": "DAT-1",
        "practice_area": "DATA_PROTECTION",
        "weight": 10,
        "requires_lab_verification": False,
        "criterion_text": "Encryption of data at rest",
    },
    {
        "criterion_code": "VLN-1",
        "practice_area": "VULN_DISCLOSURE",
        "weight": 10,
        "requires_lab_verification": False,
        "criterion_text": "Published disclosure contact",
    },
]


def _calc_program(criteria):
    """The self-attestation tier, one eligible category and `criteria`."""
    return fixtures.create_program(
        "SELF_ATTESTATION",
        tier_overrides=dict(CALC_TIER_OVERRIDES),
        category_overrides=dict(CALC_CATEGORY_OVERRIDES),
        criteria=criteria,
    )


def _acme():
    return fixtures.enrol_manufacturer(**SPONSOR_OVERRIDES)


def _submit_and_read(assessment_id, headers):
    """Submit the draft, then read the row back so the assertions see storage."""
    submitted = validate_success(api_client.submit_assessment(assessment_id, headers), 201)
    stored = validate_success(api_client.get_assessment(assessment_id, fixtures.ADMIN))
    assert stored["provisional_overall_score"] == submitted["provisional_overall_score"], (
        "the submit response and the stored assessment disagree on "
        f"provisional_overall_score: {submitted['provisional_overall_score']!r} "
        f"vs {stored['provisional_overall_score']!r}"
    )
    return stored


class TestConformanceScoreIgnoresUnansweredCriteria:
    """An unanswered criterion leaves the earned total and the possible total."""

    def test_unanswered_criterion_is_absent_from_both_sums_of_its_area(self):
        """AUTH-2 carries weight 30 and no response, so AUTHENTICATION is 100.00.

        PRD: "A criterion that has *no* response in this assessment is excluded from both the earned total and the possible total for its area — it does not silently score zero, it simply is not part of the denominator."
        Design: Corner/calculations/input_set_filtering_conformance_score_ignores_unanswered_criteria
        """
        fixtures.set_clock(DEFAULT_CLOCK)
        program = _calc_program(UNEVEN_AUTHENTICATION_CATALOGUE)
        sponsor = _acme()
        product = fixtures.register_product(program, sponsor, **PRODUCT_OVERRIDES)
        assessment = fixtures.open_assessment(program, sponsor, product)
        fixtures.attach_responses(
            program, sponsor, assessment, codes=["AUTH-1", "UPD-1", "DAT-1", "VLN-1"]
        )

        stored = _submit_and_read(assessment["id"], sponsor.headers)

        areas = stored["provisional_area_scores"]
        assert_score(areas["AUTHENTICATION"], 100.00, "provisional AUTHENTICATION")
        assert_score(areas["SOFTWARE_UPDATE"], 100.00, "provisional SOFTWARE_UPDATE")
        assert_score(areas["DATA_PROTECTION"], 100.00, "provisional DATA_PROTECTION")
        assert_score(areas["VULN_DISCLOSURE"], 100.00, "provisional VULN_DISCLOSURE")
        assert_score(stored["provisional_overall_score"], 100.00, "provisional_overall_score")
        assert_score(stored["decided_min_area_score"], 100.00, "decided_min_area_score")
        assert stored["gate_applied"] is False, (
            f"gate_applied must be false when every area is 100.00, got {stored['gate_applied']!r}"
        )
        assert_score(stored["decided_overall_score"], 100.00, "decided_overall_score")
        assert_status(stored, "grade", "A")


class TestAreaScoresAreRoundedBeforeWeighting:
    """The pinned rounding order of PRD 3.4 steps one and three."""

    def _submitted_claim(self):
        fixtures.set_clock(DEFAULT_CLOCK)
        program = _calc_program(HALF_CENT_CATALOGUE)
        sponsor = _acme()
        product = fixtures.register_product(program, sponsor, **PRODUCT_OVERRIDES)
        assessment = fixtures.open_assessment(program, sponsor, product)
        fixtures.attach_responses(
            program,
            sponsor,
            assessment,
            conformance={"AUTH-2": False, "DAT-2": False},
        )
        return _submit_and_read(assessment["id"], sponsor.headers)

    def test_each_area_score_is_rounded_half_up_to_two_decimals(self):
        """25/32 becomes 78.13 and 20/30 becomes 66.67 before anything is weighted.

        PRD: "The area's score is the earned total divided by the possible total, multiplied by 100, then rounded half up to two decimal places."
        Design: Corner/calculations/precision_area_scores_round_half_up_before_they_are_weighted
        """
        stored = self._submitted_claim()

        areas = stored["provisional_area_scores"]
        assert_score(areas["AUTHENTICATION"], 78.13, "provisional AUTHENTICATION")
        assert_score(areas["DATA_PROTECTION"], 66.67, "provisional DATA_PROTECTION")
        assert_score(areas["SOFTWARE_UPDATE"], 100.00, "provisional SOFTWARE_UPDATE")
        assert_score(areas["VULN_DISCLOSURE"], 100.00, "provisional VULN_DISCLOSURE")
        assert_score(stored["decided_min_area_score"], 66.67, "decided_min_area_score")
        assert stored["gate_applied"] is False, (
            "the weakest area is 66.67, which is above the floor, so gate_applied "
            f"must be false, got {stored['gate_applied']!r}"
        )

    def test_weighted_sum_reads_the_already_rounded_area_scores(self):
        """Weighting 78.13 and 66.67 gives 85.11, not the 85.10 the raw ratios give.

        PRD: "The rounding order here is pinned and must not be optimised away: round each area score first, then weight and sum, then round once more."
        Design: Corner/calculations/precision_area_scores_round_half_up_before_they_are_weighted
        """
        stored = self._submitted_claim()

        assert_score(stored["provisional_overall_score"], 85.11, "provisional_overall_score")
        assert_score(stored["decided_overall_score"], 85.11, "decided_overall_score")
        assert round(float(stored["provisional_overall_score"]), 2) != 85.10, (
            "85.10 is the result of weighting the unrounded area ratios, which the "
            "pinned rounding order forbids"
        )
        assert_status(stored, "grade", "B")


class TestProgramEvaluationRatesAndGrade:
    """Both denominators are non-empty and exactly one target is cleared."""

    def _seed(self):
        fixtures.set_clock(DEFAULT_CLOCK)
        program = _calc_program(FLAT_CATALOGUE)
        excluded = fixtures.add_excluded_category(
            program,
            category_code="MEDICAL_IMPLANT",
            display_name="Medical Implant",
            exclusion_reason="Regulated as a medical device outside the labelling program",
            min_support_period_days=180,
        )
        acme = _acme()
        beta = fixtures.enrol_manufacturer(
            legal_name="Beta Medical",
            contact_email="ops@beta.example",
            enterprise_class="LARGE",
            annual_us_revenue_cents=4000000000,
        )
        fixtures.register_product(
            program,
            beta,
            category_id=excluded["id"],
            model_name="Implant Link",
            sku="IMP-001",
            firmware_version="1.0.0",
            declared_support_period_end="2029-08-01T00:00:00Z",
            update_policy_disclosed=True,
            retail_units_shipped=50,
        )
        claim = fixtures.approved_claim(
            program=program, sponsor=acme, product_overrides=dict(PRODUCT_OVERRIDES)
        )
        fixtures.published_grant(
            claim,
            update_policy_url="https://acme.example/updates",
            vuln_disclosure_contact="security@acme.example",
        )
        fixtures.record_survey(
            survey_period_label="2026-H1",
            survey_period_end="2026-06-30T00:00:00Z",
            respondents_count=200,
            recognized_count=60,
        )
        fixtures.record_survey(
            survey_period_label="2026-07",
            survey_period_end="2026-07-31T00:00:00Z",
            respondents_count=100,
            recognized_count=40,
        )
        fixtures.record_survey(
            survey_period_label="2026-H2",
            survey_period_end="2026-12-31T00:00:00Z",
            respondents_count=1000,
            recognized_count=1000,
        )

    def test_one_target_cleared_of_two_grades_the_program_partial(self):
        """50.00 participation clears 40.00 while 33.33 recognition misses 35.00.

        PRD: "A program that clears exactly one of the two targets is graded `PARTIAL`."
        Design: Corner/calculations/correct_result_program_evaluation_rates_and_partial_grade
        """
        self._seed()

        evaluation = validate_success(api_client.get_program_evaluation(CONSUMER_HEADERS))

        assert evaluation["enrolled_manufacturer_count"] == 2, evaluation
        assert evaluation["participating_manufacturer_count"] == 1, evaluation
        assert_score(evaluation["manufacturer_participation_rate"], 50.00, "manufacturer_participation_rate")
        assert evaluation["eligible_product_count"] == 1, (
            "the excluded-category product must stay out of eligible_product_count"
        )
        assert evaluation["labeled_product_count"] == 1, evaluation
        assert evaluation["respondents_count"] == 300, evaluation
        assert evaluation["recognized_total"] == 100, evaluation
        assert_score(evaluation["consumer_recognition_rate"], 33.33, "consumer_recognition_rate")
        assert_status(evaluation, "evaluation_grade", "PARTIAL")

    def test_future_dated_wave_joins_the_aggregate_once_the_clock_reaches_it(self):
        """The 2026-12-31 wave is excluded at 2026-08-01 and included at 2026-12-31.

        PRD: "The upper bound is inclusive, so a wave whose `survey_period_end` equals the clock instant to the second is included, and future-dated waves are excluded until the clock reaches them."
        Design: Corner/calculations/correct_result_program_evaluation_rates_and_partial_grade
        """
        self._seed()

        before = validate_success(api_client.get_program_evaluation(CONSUMER_HEADERS))
        assert before["respondents_count"] == 300, (
            "the wave closing at 2026-12-31 must not be aggregated while the clock "
            "sits at 2026-08-01"
        )

        fixtures.set_clock("2026-12-31T00:00:00Z")
        after = validate_success(api_client.get_program_evaluation(CONSUMER_HEADERS))

        assert after["respondents_count"] == 1300, after
        assert after["recognized_total"] == 1100, after
        assert_score(after["consumer_recognition_rate"], 84.62, "consumer_recognition_rate")
        assert_score(after["manufacturer_participation_rate"], 50.00, "manufacturer_participation_rate")
        assert_status(after, "evaluation_grade", "MEETING_TARGET")


class TestRetailerParticipationThresholdsAreInclusive:
    """Exactly two authorized displays is GOLD; one is BASELINE."""

    def _gold_retailer(self):
        fixtures.set_clock(DEFAULT_CLOCK)
        program = _calc_program(FLAT_CATALOGUE)
        sponsor = _acme()
        claim = fixtures.approved_claim(
            program=program, sponsor=sponsor, product_overrides=dict(PRODUCT_OVERRIDES)
        )
        grant = fixtures.published_grant(
            claim,
            update_policy_url="https://acme.example/updates",
            vuln_disclosure_contact="security@acme.example",
        )
        store = fixtures.register_retailer(retailer_name="MegaMart")
        online = fixtures.authorize_display(
            grant,
            store,
            channel="ONLINE",
            display_from="2026-09-01T00:00:00Z",
            display_until="2026-12-31T00:00:00Z",
        )
        in_store = fixtures.authorize_display(
            grant,
            store,
            channel="IN_STORE",
            display_from="2026-09-01T00:00:00Z",
            display_until="2026-12-31T00:00:00Z",
        )
        return store, online, in_store

    def test_exactly_two_authorized_displays_reach_gold(self):
        """Two is the inclusive GOLD threshold and is still far below PLATINUM.

        PRD: "Then `participation_tier` is chosen: a retailer whose `education_materials_ack` is true and whose `active_display_count` is 5 or more is `PLATINUM`; failing that, a retailer whose `education_materials_ack` is true and whose `active_display_count` is 2 or more is `GOLD`; every other retailer is `BASELINE`."
        Design: Corner/calculations/constants_applied_retailer_participation_thresholds_are_inclusive
        """
        store, _online, _in_store = self._gold_retailer()

        retailer = validate_success(api_client.get_retailer(store.id, store.headers))
        assert retailer["active_display_count"] == 2, retailer
        assert retailer["education_materials_ack"] is True, retailer
        assert_status(retailer, "participation_tier", "GOLD")

    def test_withdrawing_one_display_demotes_straight_to_baseline(self):
        """Dropping from two to one skips every intermediate tier.

        PRD: "Withdrawal drives `AUTHORIZED → WITHDRAWN`, decrements the retailer's `active_display_count` and re-derives its `participation_tier`."
        Design: Corner/calculations/constants_applied_retailer_participation_thresholds_are_inclusive
        """
        store, online, in_store = self._gold_retailer()

        response = api_client.withdraw_display_authorization(
            in_store["id"], factories.withdraw_authorization_payload(), store.headers
        )
        withdrawn = validate_success(response, 201)

        assert_status(withdrawn, "status", "WITHDRAWN")
        assert_status(withdrawn, "withdrawal_reason", "RETAILER_REQUEST")

        surviving = validate_success(api_client.get_display_authorization(online["id"], store.headers))
        assert_status(surviving, "status", "AUTHORIZED")

        retailer = validate_success(api_client.get_retailer(store.id, store.headers))
        assert retailer["active_display_count"] == 1, retailer
        assert retailer["education_materials_ack"] is True, (
            "the demotion must be driven by the count alone, not by the acknowledgement"
        )
        assert_status(retailer, "participation_tier", "BASELINE")
