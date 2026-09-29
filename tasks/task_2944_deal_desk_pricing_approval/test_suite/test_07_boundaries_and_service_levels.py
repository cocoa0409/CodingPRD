"""Inclusive-lower/exclusive-upper band membership and the strict lateness instant."""
import pytest

from test_helpers import (
    assert_instant_equals,
    latest_approval_request,
    pending_step_of_request,
    read_quote,
    read_step,
    run_sla_sweep,
    set_clock,
    setup_single_line_quote,
    submit_quote,
)


def _two_boundary_quotes(api, base):
    quote_a, line_a = setup_single_line_quote(
        api, base, "support", 10, 0.25, term_months=12, title="Boundary Quote A",
        payment_terms_days=30, billing_frequency="ANNUAL",
    )
    quote_b, line_b = setup_single_line_quote(
        api, base, "support", 10, 0.24, term_months=12, title="Boundary Quote B",
        payment_terms_days=30, billing_frequency="ANNUAL",
    )
    return (quote_a, line_a), (quote_b, line_b)


def test_a_blended_discount_exactly_on_a_band_boundary_belongs_to_the_upper_band(api, base):
    """PRD §3.3: "The approval matrix is read from `final_blended_discount_pct`: the
    **matrix level** is the `tier_level` of the single band of the pinned revision whose
    `min_discount_pct` is at or below that figure and whose `max_discount_pct` is strictly
    above it."
    PRD §3.3: "Band membership is tested on the already-rounded six-decimal value, with the
    lower bound inclusive and the upper bound exclusive."

    Design: Difficulty/boundary_precision_check/blended_discount_exactly_at_tier_three_lower_bound_selects_level_three
    """
    (quote_a, line_a), (quote_b, line_b) = _two_boundary_quotes(api, base)

    assert line_a["final_net_cents"] == 225000
    submitted_a = submit_quote(api, quote_a["id"])
    quote_a = read_quote(api, quote_a["id"])
    assert quote_a["final_blended_discount_pct"] == pytest.approx(0.250000, abs=1e-9)
    assert quote_a["final_margin_pct"] == pytest.approx(0.733333, abs=1e-9)
    assert submitted_a["required_approval_level"] == 3, "0.250000 is the tier-3 lower bound"

    assert line_b["final_net_cents"] == 228000
    submitted_b = submit_quote(api, quote_b["id"])
    quote_b = read_quote(api, quote_b["id"])
    assert quote_b["final_blended_discount_pct"] == pytest.approx(0.240000, abs=1e-9)
    assert quote_b["final_margin_pct"] == pytest.approx(0.736842, abs=1e-9)
    assert submitted_b["required_approval_level"] == 2, "one six-decimal step lower stays in tier 2"


def test_the_request_copies_the_boundary_level_and_still_starts_at_level_one(api, base):
    """PRD §3.7: "It then cascades downward and creates exactly one **approval request** for
    this submit cycle, in `status` `OPEN`, with its own `submitted_at` at the same logical
    instant, `quote_id` naming the quote, `required_level` copied from the quote's freshly
    computed `required_approval_level`, `escalation_count` at zero, `at_backstop` false,
    `sla_state` `ON_TRACK`, `decided_at` and `total_turnaround_hours` unset, and
    `requires_cfo_cosign` set to whether the quote's `terms_risk_score_dominant` is at or
    above the pinned revision's `terms_cfo_risk_threshold`."
    PRD §3.7: "When the discount axis lands on `PENDING`, the submission also creates the
    first **approval step** — one row, at `level` 1, with `decision` `PENDING`,
    `assigned_role` copied from the `required_role` of the pinned revision's approval matrix
    band at `tier_level` 1"

    Design: Difficulty/boundary_precision_check/blended_discount_exactly_at_tier_three_lower_bound_selects_level_three
    """
    (quote_a, _), (quote_b, _) = _two_boundary_quotes(api, base)
    submit_quote(api, quote_a["id"])
    submit_quote(api, quote_b["id"])

    request_a = latest_approval_request(api, quote_a["id"])
    request_b = latest_approval_request(api, quote_b["id"])

    assert request_a["required_level"] == 3
    assert request_b["required_level"] == 2
    assert request_a["current_level"] == 1, "the ladder always starts at the bottom"
    assert request_b["current_level"] == 1


def _submit_inside_the_surge_window(api, base):
    set_clock(api, "2026-09-21T00:00:00Z")
    quote, _ = setup_single_line_quote(
        api, base, "support", 10, 0.20, term_months=12, title="Quarter End Surge Deal",
        payment_terms_days=30, billing_frequency="ANNUAL",
    )
    submit_quote(api, quote["id"])
    request = latest_approval_request(api, quote["id"])
    step = pending_step_of_request(api, request["id"])
    return quote, request, step


def test_a_sweep_at_exactly_the_surge_adjusted_due_instant_escalates_nothing(api, base):
    """PRD §3.8: "`sla_hours_effective` is the `sla_hours` configured on the pinned
    revision's matrix band for the step's `level`, multiplied by the pinned revision's
    `surge_sla_multiplier` when `in_surge_window` is true and multiplied by one otherwise,
    rounded half up to two decimal places."
    PRD §3.8: "Breach is strict: a step is late only when the logical clock is strictly past
    its `sla_due_at`, and a clock reading exactly equal to `sla_due_at` is on time."

    Design: Difficulty/boundary_precision_check/sla_sweep_at_exact_surge_adjusted_due_instant_is_not_a_breach
    """
    quote, request, step = _submit_inside_the_surge_window(api, base)
    assert_instant_equals(quote["expires_at"], "2026-10-21T00:00:00.000Z", "expires_at")
    assert step["in_surge_window"] is True
    assert step["sla_hours_effective"] == pytest.approx(4.00, abs=1e-9), "8 hours halved"
    assert_instant_equals(step["sla_due_at"], "2026-09-21T04:00:00.000Z", "sla_due_at")

    set_clock(api, "2026-09-21T04:00:00Z")
    sweep = run_sla_sweep(api)
    assert sweep["escalated_step_ids"] == []
    assert sweep["created_step_ids"] == []

    assert read_step(api, step["id"])["decision"] == "PENDING"
    request = latest_approval_request(api, quote["id"])
    assert request["sla_state"] == "ON_TRACK"
    assert request["escalation_count"] == 0


def test_a_sweep_one_second_later_escalates_two_levels_out_of_the_surge_window(api, base):
    """PRD §3.8: "It then creates a replacement step whose `escalated_from_step_level`
    records the breached step's `level`, and whose own `level` depends on when the breached
    step was created: a step created inside the surge window jumps **two** levels rather
    than one, so the replacement level is the breached level plus two, and otherwise it is
    the breached level plus one — with either result capped at 4, the highest level the
    matrix defines."
    PRD §3.8: "The request's `current_level` is set to the replacement's level, and its
    `required_level` is raised to the greater of its existing `required_level` and that
    replacement level — an escalated deal never falls back to needing less authority than it
    has already been pushed to."

    Design: Difficulty/boundary_precision_check/sla_sweep_at_exact_surge_adjusted_due_instant_is_not_a_breach
    """
    quote, request, step = _submit_inside_the_surge_window(api, base)
    set_clock(api, "2026-09-21T04:00:00Z")
    run_sla_sweep(api)

    set_clock(api, "2026-09-21T04:00:01Z")
    sweep = run_sla_sweep(api)
    assert sweep["escalated_step_ids"] == [step["id"]]

    assert read_step(api, step["id"])["decision"] == "ESCALATED"

    replacement = pending_step_of_request(api, request["id"])
    assert replacement["level"] == 3
    assert replacement["assigned_role"] == "VPSales"
    assert replacement["escalated_from_step_level"] == 1
    assert replacement["sla_hours_effective"] == pytest.approx(12.00, abs=1e-9)
    assert_instant_equals(replacement["sla_due_at"], "2026-09-21T16:00:01.000Z", "sla_due_at")

    request = latest_approval_request(api, quote["id"])
    assert request["escalation_count"] == 1
    assert request["sla_state"] == "BREACHED"
    assert request["required_level"] == 3
    assert request["current_level"] == 3
    assert request["at_backstop"] is False
    assert request["status"] == "OPEN"
    assert read_quote(api, quote["id"])["status"] == "PENDING_APPROVAL"
