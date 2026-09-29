"""
The two dual-variant calculations: the non-installation evidence score computed
under each detection method, and the two claim settlement figures taken at two
different moments.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import ADJUSTER_A, ADJUSTER_B, OPERATOR


def _evidence_env(api, runtime_minutes: int):
    """
    Fixture A plus a delivered shipment and two telemetry windows whose
    pressure drop rises 100 -> 120 Pa across 2026-08-07 -> 2026-08-09.
    """
    env = fx.build_base_env(api)
    fx.deliver_first_shipment(api, env.subscription_id, "2026-08-06T00:00:00Z")
    fx.add_runtime_reading(
        api,
        env.unit_id,
        "2026-08-07T00:00:00Z",
        "2026-08-08T00:00:00Z",
        runtime_minutes,
        100,
        "PRESSURE_SENSOR",
    )
    fx.add_runtime_reading(
        api,
        env.unit_id,
        "2026-08-08T00:00:00Z",
        "2026-08-09T00:00:00Z",
        runtime_minutes,
        120,
        "PRESSURE_SENSOR",
    )
    fx.set_clock(api, "2026-08-09T00:00:00Z")
    return env


class TestEvidenceScoreVariants:
    """The same physical fixture scored under both detection methods."""

    def test_survey_and_runtime_variants_produce_different_scores_and_thresholds(self, api):
        """
        The renewal-survey variant scores 70 against thresholds 55/80 while the
        runtime-analytics variant scores 62 against thresholds 40/60 — on one and
        the same fixture, so the two variants are genuinely different arithmetic
        rather than one formula with a relabelled threshold.

        PRD §3.6: "The method chosen selects one of two genuinely different scoring variants: they read different evidence bearing on the same physical question, they produce different integer scores, and they carry different confirmation thresholds."

        Design: Difficulty/dual_variant_calc/non_install_evidence_runtime_variant_vs_survey_variant_diverge
        """
        env = _evidence_env(api, 168)
        fx.submit_renewal_survey(
            api,
            env.subscription_id,
            installed_last_shipment=False,
            filters_on_hand_count=0,
            self_reported_change_date="2026-08-08",
        )

        survey_case = validate_success(
            api.create_non_install_evaluation(
                env.subscription_id,
                f.non_install_evaluation_payload("RENEWAL_SURVEY", "2026-08-09"),
                OPERATOR,
            ),
            201,
        )
        assert survey_case["detection_method"] == "RENEWAL_SURVEY"
        assert survey_case["evidence_score"] == 70
        assert survey_case["suspect_threshold"] == 55
        assert survey_case["confirm_threshold"] == 80

        # Clear the suspicion the survey raised so the runtime evaluation is read
        # on its own terms.
        validate_success(api.close_case_unsubstantiated(survey_case["id"], OPERATOR))
        assert (
            validate_success(api.get_non_install_case(survey_case["id"], OPERATOR))["status"]
            == "CLOSED_UNSUBSTANTIATED"
        )

        runtime_case = validate_success(
            api.create_non_install_evaluation(
                env.subscription_id,
                f.non_install_evaluation_payload("RUNTIME_ANALYTICS", "2026-08-09"),
                OPERATOR,
            ),
            201,
        )
        assert runtime_case["detection_method"] == "RUNTIME_ANALYTICS"
        assert runtime_case["evidence_score"] == 62
        assert runtime_case["suspect_threshold"] == 40
        assert runtime_case["confirm_threshold"] == 60

        # The divergence is the point: identical evidence, different numbers, and
        # only the runtime case clears its own confirmation bar.
        assert runtime_case["evidence_score"] != survey_case["evidence_score"]
        assert survey_case["evidence_score"] < survey_case["confirm_threshold"]
        assert runtime_case["evidence_score"] >= runtime_case["confirm_threshold"]

    def test_latest_evidence_fields_carry_the_most_recent_variant_only(self, api):
        """
        The second evaluation overwrites the subscription's latest_evidence_score
        and latest_detection_method with the runtime variant's figures, leaving no
        trace of the survey variant that ran first, and drives the posture to
        NON_INSTALL_SUSPECTED.

        PRD §3.6: "The evaluation also writes the score onto the subscription as `latest_evidence_score` and the method as `latest_detection_method`, overwriting whatever the previous evaluation left there, and increments the subscription's `version`."

        Design: Difficulty/dual_variant_calc/non_install_evidence_runtime_variant_vs_survey_variant_diverge
        """
        env = _evidence_env(api, 168)
        fx.submit_renewal_survey(
            api,
            env.subscription_id,
            installed_last_shipment=False,
            filters_on_hand_count=0,
            self_reported_change_date="2026-08-08",
        )

        survey_case = validate_success(
            api.create_non_install_evaluation(
                env.subscription_id,
                f.non_install_evaluation_payload("RENEWAL_SURVEY", "2026-08-09"),
                OPERATOR,
            ),
            201,
        )
        after_survey = fx.read_subscription(api, env.subscription_id)
        assert after_survey["latest_evidence_score"] == 70
        assert after_survey["latest_detection_method"] == "RENEWAL_SURVEY"

        validate_success(api.close_case_unsubstantiated(survey_case["id"], OPERATOR))
        validate_success(
            api.create_non_install_evaluation(
                env.subscription_id,
                f.non_install_evaluation_payload("RUNTIME_ANALYTICS", "2026-08-09"),
                OPERATOR,
            ),
            201,
        )

        after_runtime = fx.read_subscription(api, env.subscription_id)
        assert after_runtime["latest_evidence_score"] == 62
        assert after_runtime["latest_detection_method"] == "RUNTIME_ANALYTICS"
        assert after_runtime["installation_posture"] == "NON_INSTALL_SUSPECTED"


class TestClaimSettlementVariants:
    """provisional_amount_cents at triage against approved_amount_cents at decision."""

    def _claim_env(self, api):
        env = fx.build_base_env(api)
        claim = fx.file_claim(
            api,
            env.subscription_id,
            claim_type="DAMAGE_WAIVER",
            incident_date="2026-08-05",
            requested_amount_cents=40000,
            description="Return grille torn during filter change",
        )
        fx.triage_claim(api, claim["id"], ADJUSTER_A)

        fx.deliver_first_shipment(api, env.subscription_id, "2026-08-06T00:00:00Z")
        fx.add_runtime_reading(
            api, env.unit_id, "2026-08-07T00:00:00Z", "2026-08-08T00:00:00Z", 144, 100, "PRESSURE_SENSOR"
        )
        fx.add_runtime_reading(
            api, env.unit_id, "2026-08-08T00:00:00Z", "2026-08-09T00:00:00Z", 144, 120, "PRESSURE_SENSOR"
        )
        fx.set_clock(api, "2026-08-09T00:00:00Z")
        case = fx.open_case(api, env.subscription_id, "RUNTIME_ANALYTICS", "2026-08-09")
        return env, claim, case

    def test_provisional_frozen_at_triage_ignores_the_later_suspicion(self, api):
        """
        The claim is triaged while the posture is still UNVERIFIED, so
        provisional_amount_cents freezes at the undiscounted base of 30000; a
        runtime evaluation that afterwards raises NON_INSTALL_SUSPECTED does not
        move that frozen figure.

        PRD §3.7: "The provisional figure reads the subscription's `monthly_fee_cents` exactly as it stands at the triage instant, and it applies **no** non-installation reduction whatever the subscription's `installation_posture` happens to be — it is the shared base and nothing more."

        Design: Difficulty/dual_variant_calc/claim_settlement_provisional_at_triage_vs_final_at_decision_diverge
        """
        env, claim, case = self._claim_env(api)

        assert case["evidence_score"] == 60
        assert fx.read_subscription(api, env.subscription_id)["installation_posture"] == (
            "NON_INSTALL_SUSPECTED"
        )

        after = validate_success(api.get_claim(claim["id"], ADJUSTER_A))
        assert after["status"] == "UNDER_REVIEW"
        assert after["provisional_amount_cents"] == 30000
        assert after["triaged_by_user_id"] == "adj-001"
        assert after["approved_amount_cents"] is None

    def test_approved_amount_recomputed_at_decision_applies_the_suspicion_haircut(self, api):
        """
        Approving the same claim after the suspicion was raised recomputes from
        scratch and halves the base, so approved_amount_cents is 15000 against a
        provisional_amount_cents of 30000 on one and the same claim row.

        PRD §3.7: "At adjudication, the approving path recomputes from scratch: it re-reads `monthly_fee_cents` and `installation_posture` at the decision instant, and applies a fifty-percent reduction to the base when the posture is `NON_INSTALL_SUSPECTED`, or no reduction otherwise, rounding the reduced figure half up to whole cents in the single rounding this calculation performs."

        Design: Difficulty/dual_variant_calc/claim_settlement_provisional_at_triage_vs_final_at_decision_diverge
        """
        env, claim, _case = self._claim_env(api)

        decided = validate_success(
            api.decide_claim(
                claim["id"],
                f.decide_payload("APPROVE", "Waiver applies; non-install suspicion open"),
                ADJUSTER_B,
            )
        )
        assert decided["status"] == "APPROVED"
        assert decided["provisional_amount_cents"] == 30000
        assert decided["approved_amount_cents"] == 15000
        assert decided["provisional_amount_cents"] != decided["approved_amount_cents"]
        assert decided["triaged_by_user_id"] == "adj-001"
        assert decided["decided_by_user_id"] == "adj-002"
        assert fx.read_subscription(api, env.subscription_id)["installation_posture"] == (
            "NON_INSTALL_SUSPECTED"
        )
