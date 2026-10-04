"""Dual-variant calculations: skills scoring thresholds and card expiry arms.

The same inputs flow through two formula variants selected by server-side
context (attempt number / is_renewal), yielding different outcomes.
"""
import pytest

from test_helpers import (
    ADMIN,
    TC,
    align_instructor,
    complete_session,
    create_legacy_certified_instructor,
    create_scheduled_session,
    enroll_student,
    get_success_data,
    make_instructor_headers,
    record_passing_evaluation,
    setup_teaching_scenario,
    start_session,
    validate_success,
)


def _items(passed: int, failed: int) -> list:
    """Checklist of `passed` passed items and `failed` failed items; the
    critical item is always first and always passes."""
    items = [{"item_code": "I01", "critical": True, "passed": True}]
    for i in range(2, passed + 1):
        items.append({"item_code": f"I{i:02d}", "critical": False,
                      "passed": True})
    for j in range(1, failed + 1):
        items.append({"item_code": f"F{j:02d}", "critical": False,
                      "passed": False})
    return items


# 21/25 items passed, all criticals pass -> score 84.00 exactly.
ITEMS_84 = _items(passed=21, failed=4)


class TestSkillsScoringInitialVsRemediation:
    def test_identical_84_passes_initial_and_fails_retest(self, api):
        """PRD §3.6: "An initial attempt yields `PASS` when no critical item has
        `passed` false *and* `score_percent` is at least 84.00; otherwise it
        yields `REMEDIATION_REQUIRED`. A remediation retest — permitted only when
        a prior attempt on this roster entry returned `REMEDIATION_REQUIRED` —
        yields `PASS` when no critical item failed *and* `score_percent` is at
        least 90.00; otherwise it yields `FAIL`, which is terminal."

        Design: Difficulty/dual_variant_calc/skills_scoring_initial_vs_remediation_threshold
        """
        ctx = setup_teaching_scenario()
        session = create_scheduled_session(ctx)
        entry_a = enroll_student(session["id"], "Sam Student", "sam@x.example")
        entry_b = enroll_student(session["id"], "Rita Rescuer", "rita@x.example")
        start_session(session["id"])
        lead_headers = make_instructor_headers(ctx["lead"]["id"])

        # Entry A: initial attempt at exactly 84.00 -> PASS -> PASSED.
        eval_a = validate_success(
            api.create_skills_evaluation(
                entry_a["id"], {"items": ITEMS_84}, lead_headers),
            expected_status=201)
        assert eval_a["score_percent"] == pytest.approx(84.0, abs=0.001)
        assert eval_a["outcome"] == "PASS"
        assert eval_a["is_remediation_retest"] is False
        refreshed_a = validate_success(api.get_roster_entry(entry_a["id"], TC))
        assert refreshed_a["status"] == "PASSED"

        # Entry B: initial attempt at 80.00 (below the 84.00 initial
        # threshold, no critical failures) -> REMEDIATION_REQUIRED.
        items_80 = _items(passed=20, failed=5)
        eval_b1 = validate_success(
            api.create_skills_evaluation(
                entry_b["id"], {"items": items_80}, lead_headers),
            expected_status=201)
        assert eval_b1["score_percent"] == pytest.approx(80.0, abs=0.001)
        assert eval_b1["outcome"] == "REMEDIATION_REQUIRED"
        refreshed_b = validate_success(api.get_roster_entry(entry_b["id"], TC))
        assert refreshed_b["status"] == "ENROLLED"
        assert refreshed_b["remediation_used"] is True

        # Entry B: the 84.00 checklist — a score that PASSED entry A
        # initially — as the retest -> FAIL, since the retest threshold is
        # 90.00.
        eval_b2 = validate_success(
            api.create_skills_evaluation(
                entry_b["id"], {"items": ITEMS_84}, lead_headers),
            expected_status=201)
        assert eval_b2["is_remediation_retest"] is True
        assert eval_b2["score_percent"] == pytest.approx(84.0, abs=0.001)
        assert eval_b2["outcome"] == "FAIL"
        refreshed_b2 = validate_success(api.get_roster_entry(entry_b["id"], TC))
        assert refreshed_b2["status"] == "FAILED"

    def test_remediation_retest_at_90_passes_and_marks_remediation(self, api):
        """PRD §3.6: "A remediation retest — permitted only when a prior attempt
        on this roster entry returned `REMEDIATION_REQUIRED` — yields `PASS` when
        no critical item failed *and* `score_percent` is at least 90.00."
        PRD §3.6: "A `PASS` outcome moves the roster entry from `ENROLLED` to
        `PASSED`; when the passing attempt was the remediation retest, the
        entry's `remediation_used` flag is set to `true` as part of the same
        transition."

        Design: Difficulty/dual_variant_calc/skills_scoring_initial_vs_remediation_threshold
        """
        ctx = setup_teaching_scenario()
        session = create_scheduled_session(ctx)
        entry = enroll_student(session["id"])
        start_session(session["id"])
        lead_headers = make_instructor_headers(ctx["lead"]["id"])

        # Attempt 1: a failed critical item -> REMEDIATION_REQUIRED at 80%.
        eval1 = validate_success(
            api.create_skills_evaluation(
                entry["id"],
                {"items": [
                    {"item_code": "SCENE", "critical": True, "passed": False},
                    {"item_code": "COMP", "critical": False, "passed": True},
                    {"item_code": "VENT", "critical": False, "passed": True},
                    {"item_code": "AED", "critical": False, "passed": True},
                    {"item_code": "TEAM", "critical": False, "passed": True},
                ]},
                lead_headers),
            expected_status=201)
        assert eval1["outcome"] == "REMEDIATION_REQUIRED"

        # Attempt 2 (retest): 9/10 = 90.00 -> PASS at the retest threshold.
        items_90 = _items(passed=9, failed=1)
        eval2 = validate_success(
            api.create_skills_evaluation(
                entry["id"], {"items": items_90}, lead_headers),
            expected_status=201)
        assert eval2["is_remediation_retest"] is True
        assert eval2["score_percent"] == pytest.approx(90.0, abs=0.001)
        assert eval2["outcome"] == "PASS"
        refreshed = validate_success(api.get_roster_entry(entry["id"], TC))
        assert refreshed["status"] == "PASSED"
        assert refreshed["remediation_used"] is True


class TestCardExpiryInitialVsRenewal:
    def test_renewal_card_anchors_expiry_on_prior_card(self, api):
        """PRD §3.7: "For a renewal card (`is_renewal` true), the system first
        checks whether the prior card's `expires_at` is still in the future
        relative to the new card's `issued_at`. If it is, the new card's
        `expires_at` is computed by adding twenty-four months to the *prior
        card's* `expires_at` and then end-of-month snapping the result — renewal
        extends the chain, it does not reset it."
        PRD §3.7: "For an initial-issue card (`is_renewal` false), `expires_at`
        is computed by adding twenty-four months to `issued_at` and then snapping
        the result to the last day of that month at 23:59:59 UTC."

        Design: Difficulty/dual_variant_calc/card_expiry_initial_vs_renewal_reissue
        """
        ctx = setup_teaching_scenario()
        session = create_scheduled_session(ctx)
        entry = enroll_student(session["id"], "Sam Student", "sam@x.example")
        start_session(session["id"])
        lead_headers = make_instructor_headers(ctx["lead"]["id"])
        # All-passing initial attempt -> PASS.
        record_passing_evaluation(entry["id"], ctx["lead"]["id"])
        complete_session(session["id"], ctx["lead"]["id"])
        card1 = get_success_data(
            api.list_roster_entry_cards(entry["id"], TC))[0]
        # Initial issue: 2026-09-01 + 24 months -> snap to 2028-09-30T23:59:59Z.
        assert card1["expires_at"] == "2028-09-30T23:59:59Z"
        assert card1["is_renewal"] is False

        # Move the clock inside the prior card's validity and re-enroll.
        get_success_data(api.set_clock("2028-08-15T00:00:00Z", ADMIN))
        session2 = create_scheduled_session(
            ctx, start_at="2028-08-20T14:00:00Z", end_at="2028-08-20T18:00:00Z")
        entry_r = enroll_student(
            session2["id"], "Sam Student", "sam@x.example",
            prior_card_id=card1["id"])
        start_session(session2["id"])
        record_passing_evaluation(entry_r["id"], ctx["lead"]["id"])
        complete_session(session2["id"], ctx["lead"]["id"])
        card2 = get_success_data(
            api.list_roster_entry_cards(entry_r["id"], TC))[0]
        assert card2["is_renewal"] is True
        assert card2["issued_at"] == "2028-08-15T00:00:00Z"
        assert card2["prior_card_id"] == card1["id"]
        # Renewal arm: prior expiry 2028-09-30 + 24 months -> 2030-09-30.
        assert card2["expires_at"] == "2030-09-30T23:59:59Z"
        # The initial-issue arm for the same issued_at would give 2030-08-31.
        assert card2["expires_at"] != "2030-08-31T23:59:59Z"

    def test_renewal_after_prior_expired_falls_back_to_initial_issue(self, api):
        """PRD §3.7: "If the prior card has already expired by the time the new
        card is issued, the renewal falls back to the initial-issue rule:
        twenty-four months from `issued_at`, end-of-month snapped."

        Design: Difficulty/dual_variant_calc/card_expiry_initial_vs_renewal_reissue
        """
        ctx = setup_teaching_scenario()
        session = create_scheduled_session(ctx)
        entry = enroll_student(session["id"], "Sam Student", "sam@x.example")
        start_session(session["id"])
        record_passing_evaluation(entry["id"], ctx["lead"]["id"])
        complete_session(session["id"], ctx["lead"]["id"])
        card1 = get_success_data(
            api.list_roster_entry_cards(entry["id"], TC))[0]
        assert card1["expires_at"] == "2028-09-30T23:59:59Z"

        # Move past the prior card's expiry (the sweep expires it).
        get_success_data(api.set_clock("2028-11-01T00:00:00Z", ADMIN))
        expired = validate_success(api.get_card(card1["id"], TC))
        assert expired["status"] == "EXPIRED"

        # The original lead's certification also expired in the sweep, so
        # register a fresh legacy-certified lead at the new clock instant.
        lead2 = create_legacy_certified_instructor(
            ctx["center"]["id"], full_name="Dana Relief",
            email="dana@x.example")
        align_instructor(ctx["center"]["id"], lead2["id"])
        ctx2 = {**ctx, "lead": lead2}

        session2 = create_scheduled_session(
            ctx2, start_at="2028-11-10T14:00:00Z", end_at="2028-11-10T18:00:00Z")
        entry_r = enroll_student(
            session2["id"], "Sam Student", "sam@x.example",
            prior_card_id=card1["id"])
        start_session(session2["id"])
        record_passing_evaluation(entry_r["id"], lead2["id"])
        complete_session(session2["id"], lead2["id"])
        card2 = get_success_data(
            api.list_roster_entry_cards(entry_r["id"], TC))[0]
        assert card2["is_renewal"] is True
        # Fallback: 2028-11-01 + 24 months -> snap to 2030-11-30T23:59:59Z.
        assert card2["expires_at"] == "2030-11-30T23:59:59Z"
