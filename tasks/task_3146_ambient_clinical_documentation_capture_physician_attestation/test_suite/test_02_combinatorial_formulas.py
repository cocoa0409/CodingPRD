"""Combinatorial formulas: tiered completeness penalties with the CRITICAL
cap, and the pinned round-per-line-then-sum billing order.
"""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import factories as f
from test_helpers.fixtures import create_draft, ready_world


class TestCompletenessTieredPenaltyWithCriticalCap:
    """Empty 3-field draft: raw penalty 40 would give 60, but the CRITICAL
    cap forces 49; filling the CRITICAL field lifts the cap entirely."""

    def _world(self, client):
        return ready_world(
            client,
            field_specs=[
                f.field_spec("chief_complaint", "CRITICAL", True),
                f.field_spec("hpi", "MAJOR", True),
                f.field_spec("ros", "MINOR", True),
            ],
            template_overrides={"completeness_multiplier": 1.0},
        )

    def test_empty_draft_is_capped_at_49(self, client):
        """PRD 3.4: "If any missing field is `CRITICAL`, the result is capped
        at 49 no matter how small the arithmetic penalty."
        PRD 3.4: "Each missing field carries a penalty by importance: 25
        points for `CRITICAL`, 10 for `MAJOR`, 5 for `MINOR`."

        Design: Difficulty/combinatorial_formula/completeness_tiered_penalty_with_critical_cap
        """
        world = self._world(client)
        draft = create_draft(
            client, world["encounter"], world["physician"], world["template"]
        )
        assert draft["completeness_score"] == 49, (
            "raw 100-(25+10+5)=60, but a missing CRITICAL field caps at 49; "
            "got {0}".format(draft["completeness_score"])
        )

    def test_filling_critical_field_lifts_the_cap(self, client):
        """PRD 3.4: "Each penalty is multiplied by the template's
        `completeness_multiplier`; the products are summed and the sum is
        rounded half-up; that rounded total is subtracted from 100."
        PRD 3.4: "If any missing field is `CRITICAL`, the result is capped
        at 49 no matter how small the arithmetic penalty."

        Design: Difficulty/combinatorial_formula/completeness_tiered_penalty_with_critical_cap
        """
        world = self._world(client)
        draft = create_draft(
            client, world["encounter"], world["physician"], world["template"]
        )
        resp = client.patch_note_draft(
            draft["id"],
            f.patch_note_draft_payload(
                draft["version"], [f.field_update("chief_complaint", "palpitations")]
            ),
            headers=world["physician_headers"],
        )
        body = validate_success(resp)
        assert body["completeness_score"] == 85, (
            "missing MAJOR 10 + MINOR 5 = 85 with no CRITICAL missing; got "
            "{0}".format(body["completeness_score"])
        )


class TestBillingPerLineRoundingThenSum:
    """Two lines of round_half_up(1000*1*1.004)=1000 sum to 2000; the
    rejected sum-then-round order would give 2001."""

    def _world_with_two_lines_confirmed(self, client):
        world = ready_world(
            client,
            field_specs=[
                f.field_spec("chief_complaint", "CRITICAL", True),
                f.field_spec("hpi", "MAJOR", True),
            ],
        )
        draft = create_draft(
            client, world["encounter"], world["physician"], world["template"]
        )
        headers = world["physician_headers"]
        suggestions = validate_success(
            client.create_code_suggestions(
                draft["id"],
                {
                    "suggestions": [
                        f.billing_suggestion_payload(
                            "B3001", confidence=1.0, unit_fee_cents=1000,
                            adjustment_pct=1.004,
                        ),
                        f.billing_suggestion_payload(
                            "B3002", confidence=1.0, unit_fee_cents=1000,
                            adjustment_pct=1.004,
                        ),
                    ]
                },
                headers=headers,
            ),
            201,
        )
        for suggestion in suggestions:
            get_success_data(
                client.confirm_suggestion(suggestion["id"], headers=headers)
            )
        return world, draft, suggestions

    def test_each_line_rounds_to_1000(self, client):
        """PRD 3.6: "Each suggestion's `line_total_cents` is computed per
        line, before any summation: the `unit_fee_cents` is multiplied by the
        `quantity` and by the `adjustment_pct`, and the product is rounded
        half-up to integer cents."

        Design: Difficulty/combinatorial_formula/billing_per_line_rounding_then_sum
        """
        world, draft, suggestions = self._world_with_two_lines_confirmed(client)
        for suggestion in suggestions:
            assert suggestion["line_total_cents"] == 1000, (
                "round_half_up(1000*1*1.004)=1000 per line, got {0}".format(
                    suggestion["line_total_cents"]
                )
            )

    def test_final_total_sums_rounded_lines(self, client):
        """PRD 3.6: "Rounding order is pinned — each line is rounded first,
        then the confidence weighting is applied and rounded again, then the
        lines are summed; summing first and rounding once is the rejected
        alternative."

        Design: Difficulty/combinatorial_formula/billing_per_line_rounding_then_sum
        """
        world, draft, suggestions = self._world_with_two_lines_confirmed(client)
        body = validate_success(
            client.get_note_draft(draft["id"], headers=world["physician_headers"])
        )
        assert body["billing_final_cents"] == 2000, (
            "per-line-then-sum gives 2000; sum-then-round would give 2001; "
            "got {0}".format(body["billing_final_cents"])
        )
