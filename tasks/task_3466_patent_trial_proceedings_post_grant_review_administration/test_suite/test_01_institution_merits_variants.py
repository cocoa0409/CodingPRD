"""Institution merits: operative per-ground maximum vs advisory aggregate
variant, and fixed-days vs anniversary deadline variants (PRD §3.4, §3.8).
"""
from test_helpers import (
    PANEL,
    api_client,
    assert_petition,
    assert_proceeding,
    assert_same_instant,
    decide_institution,
    get_petition,
    get_proceeding,
    new_world,
    per_ground_scores,
    file_petition,
    accord,
    validate_success,
)


def _filed_ipr_petition(world, challenged=(1, 2, 3)):
    return file_petition(
        world["petitioner"]["id"], world["patent"]["id"],
        challenged_claims=list(challenged),
    )


class TestMeritsPerGroundMaxVsAdvisoryAggregate:
    def test_max_score_governs_institution_when_aggregate_would_deny(self):
        """PRD §3.4: "The merits are met when the maximum score is at least
        the threshold — a top score of exactly 40 institutes an `IPR`, while
        39 does not."
        PRD §3.4: "The aggregate is a panel-screening metric reported on the
        record only and never decides institution".

        Design: Difficulty/dual_variant_calc/merits_per_ground_max_decides_while_weighted_aggregate_would_deny
        """
        world = new_world(total_claims=5)
        petition = _filed_ipr_petition(world)
        accord(petition["id"])
        scores = per_ground_scores((1, 40), (2, 0, "OBVIOUSNESS_103"), (3, 0))
        resp = api_client.decide_institution(
            petition["id"],
            {"per_ground_scores": scores, "lead_judge_user_id": "judge-alice"},
            PANEL,
        )
        data = validate_success(resp, 201)
        # Operative rule: max 40 >= 40 institutes, even though the advisory
        # aggregate over [40, 0, 0] is far below the threshold.
        assert data["outcome"] == "INSTITUTED"
        assert data["merits_max_score"] == 40
        assert data["threshold_used"] == 40
        assert data["proceeding_id"]

    def test_decision_record_carries_advisory_aggregate_value(self):
        """PRD §3.4: "the decision record carries an advisory
        `advisory_aggregate_score`: seven-tenths of the maximum score plus
        three-tenths of the mean of all scores, rounded half-up to an integer."

        Design: Difficulty/dual_variant_calc/merits_per_ground_max_decides_while_weighted_aggregate_would_deny
        """
        world = new_world(total_claims=5)
        petition = _filed_ipr_petition(world)
        accord(petition["id"])
        scores = per_ground_scores((1, 40), (2, 0, "OBVIOUSNESS_103"), (3, 0))
        # round_half_up(0.7*40 + 0.3*(40/3)) = round_half_up(28 + 4) = 32,
        # which is below the 40 threshold: the advisory variant would NOT
        # have instituted these same inputs.
        data = validate_success(
            api_client.decide_institution(
                petition["id"],
                {"per_ground_scores": scores, "lead_judge_user_id": "judge-alice"},
                PANEL,
            ),
            201,
        )
        assert data["advisory_aggregate_score"] == 32
        petition_after = get_petition(petition["id"])
        assert_petition(petition_after)
        assert petition_after["status"] == "INSTITUTED"
        assert petition_after["merits_max_score"] == 40
        assert petition_after["advisory_aggregate_score"] == 32


class TestFwdDeadlineVariantsAcrossLeapDay:
    def _instituted_on_leap_span(self):
        world = new_world(
            total_claims=3, clock="2027-03-10T00:00:00Z",
            petitioner_name="P2 Corp", owner_name="O2 Corp",
        )
        petition = file_petition(
            world["petitioner"]["id"], world["patent"]["id"],
            challenged_claims=[1, 2],
            grounds=[
                {"claim_number": 1, "basis": "ANTICIPATION_102"},
                {"claim_number": 2, "basis": "OBVIOUSNESS_103"},
            ],
            prior_art=[{"reference_type": "PRINTED_PUBLICATION",
                        "citation": "IEEE 2019"}],
        )
        accord(petition["id"])
        decision = decide_institution(
            petition["id"],
            per_ground_scores((1, 75), (2, 60, "OBVIOUSNESS_103")),
            "judge-bob",
        )
        return get_proceeding(decision["proceeding_id"])

    def test_operative_fixed_days_deadline_is_365_days_out(self):
        """PRD §3.8: "a proceeding instituted on 2027-03-10 shows an operative
        deadline of 2028-03-09 against an advisory anniversary of 2028-03-10,
        and every deadline check in the system uses the operative value."

        Design: Difficulty/dual_variant_calc/fwd_deadline_fixed_days_vs_calendar_anniversary_across_leap_day
        """
        proceeding = self._instituted_on_leap_span()
        assert_proceeding(proceeding)
        # institution_date 2027-03-10 + 365 days spans 2028-02-29 -> 2028-03-09.
        assert_same_instant(
            proceeding["fwd_due_date"], "2028-03-09T00:00:00Z", "fwd_due_date"
        )

    def test_advisory_anniversary_variant_is_12_calendar_months_out(self):
        """PRD §3.8: "An advisory anniversary value,
        `advisory_anniversary_date`, is maintained alongside it —
        `institution_date` plus 12 calendar months, plus 6 further calendar
        months if extended — for schedule-order display only; it never gates
        any transition."

        Design: Difficulty/dual_variant_calc/fwd_deadline_fixed_days_vs_calendar_anniversary_across_leap_day
        """
        proceeding = self._instituted_on_leap_span()
        assert_same_instant(
            proceeding["advisory_anniversary_date"],
            "2028-03-10T00:00:00Z",
            "advisory_anniversary_date",
        )
        # The two absolute pins (2028-03-09 vs 2028-03-10) sit exactly one
        # day apart: both variants are computed from the same institution
        # instant across the leap day.
