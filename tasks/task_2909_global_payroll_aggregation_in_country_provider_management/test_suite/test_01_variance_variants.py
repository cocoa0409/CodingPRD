"""The two variance variants and the two provider-score variants.

Each test drives the estate through the PRD's own endpoints and then reads the
figures the specification derives, so the arithmetic path is what is under test
rather than the plumbing that produced it.
"""

from prd_bench_local_runner.testing import validate_paginated

from test_helpers import assertions as a
from test_helpers import fixtures as fx
from test_helpers.constants import (
    CYCLE_CLOSED,
    CYCLE_INPUTS_LOCKED,
    GTN_CLEARED,
    INCIDENT_CONFIRMED,
    PROVIDER_ACTIVE,
    SCORE_VARIANT_ENGAGEMENT_TO_DATE,
    SCORE_VARIANT_ROLLING_WINDOW,
    SEV1,
    VARIANCE_BASIS_HEADCOUNT_NORMALIZED,
)
from test_helpers.test_users import CONTROLLER_HEADERS, OPS_HEADERS

# A run of 10 500 000 over 210 employees against a baseline of 10 000 000 over
# 200: the totals moved 5.00 percent but the per-head amount did not move at all.
_SECOND_RUN = {
    "gross_minor": 10500000,
    "net_minor": 6800000,
    "employer_cost_minor": 2100000,
    "provider_fee_minor": 155000,
    "employee_count": 210,
}


def _normalized_second_run(api):
    """A locked second period whose extract carries 210 records, then the run."""
    ctx = fx.setup_baseline_and_locked_second_period(
        api, second_extract_overrides={"record_count": 210}
    )
    run = fx.submit_run(
        api,
        ctx["cycle_id"],
        ctx["input_file_id"],
        ctx["provider_id"],
        ctx["cycle_version"],
        **_SECOND_RUN,
    )
    return ctx, run


def _flipped_variant_estate(api):
    """An estate carrying one aged CONFIRMED incident and a closable cycle."""
    ctx = fx.setup_active_engagement(api)
    aged = fx.confirmed_incident(
        api, ctx["engagement_id"], SEV1, occurred_at="2026-04-01T00:00:00Z"
    )
    ctx = dict(ctx)
    ctx["aged_incident_id"] = aged["id"]
    return fx.drive_cycle_to_closable(api, ctx)


def test_headcount_normalized_variant_masks_a_five_percent_absolute_move(api):
    """A 5.00 percent headcount drift selects the per-employee comparison, which
    reads a 5.00 percent movement in the totals as no movement at all.

    PRD 3.5: "When the drift is at least 3.00 and at most 10.00 — both bounds
    inclusive — the `HEADCOUNT_NORMALIZED` variant applies."

    PRD 3.5: "Divide this run's `gross_minor` by its `employee_count` to obtain the
    per-head amount, and divide the baseline's `gross_minor` by the baseline's
    `employee_count` to obtain the baseline per-head amount."

    Design: Difficulty/dual_variant_calc/variance_basis_headcount_normalized_masks_five_pct_absolute_move
    """
    _, run = _normalized_second_run(api)

    a.assert_variance_analysis(
        run,
        variance_basis=VARIANCE_BASIS_HEADCOUNT_NORMALIZED,
        variance_pct=0.00,
        headcount_drift_pct=5.00,
        variance_material=False,
    )
    assert run["status"] == GTN_CLEARED, (
        f"an immaterial run clears, got {run['status']}"
    )


def test_headcount_normalized_clearance_raises_no_escalation_incident(api):
    """Because the normalized reading is immaterial, the cycle stays locked and no
    service-level incident is opened for the engagement.

    PRD 3.5: "An immaterial run moves `SUBMITTED → CLEARED`, and no service-level
    incident is created on that branch."

    Design: Difficulty/dual_variant_calc/variance_basis_headcount_normalized_masks_five_pct_absolute_move
    """
    ctx, _ = _normalized_second_run(api)

    cycle = fx.read_cycle(api, ctx["cycle_id"])
    a.assert_cycle_state(cycle, CYCLE_INPUTS_LOCKED)

    incidents, meta = validate_paginated(
        api.list_incidents(OPS_HEADERS, {"engagement_id": ctx["engagement_id"]})
    )
    a.assert_pagination_meta(meta, expected_total=0, expected_has_more=False)
    assert incidents == [], f"no incident should exist, got {incidents}"


def test_first_cycle_close_flips_the_score_variant_to_rolling_window(api):
    """Closing the first cycle of an engagement flips the provider's score variant
    and, with it, ages a pre-window failure out of the reckoning.

    PRD 3.9: "That increment is a scoring event: the engaged provider's
    `service_score` is recomputed immediately, and because the provider now has an
    engagement with at least one closed cycle, `score_variant_applied` flips to
    `ROLLING_WINDOW` at the first such closure."

    PRD 3.8: "Under `ROLLING_WINDOW`, the window opens 90 calendar days before the
    current logical clock: an incident qualifies when its `occurred_at` is at or
    after that window start, and a late filing qualifies when its `due_at` is at or
    after that window start; anything older drops out of the reckoning."

    Design: Difficulty/dual_variant_calc/provider_score_variant_flips_to_rolling_window_on_first_cycle_close
    """
    ctx = _flipped_variant_estate(api)

    before = fx.read_provider(api, ctx["provider_id"])
    a.assert_provider_standing(
        before,
        status=PROVIDER_ACTIVE,
        service_score=75.00,
        score_variant_applied=SCORE_VARIANT_ENGAGEMENT_TO_DATE,
    )

    fx.close_cycle(api, ctx["cycle_id"])

    after = fx.read_provider(api, ctx["provider_id"])
    a.assert_provider_standing(
        after,
        status=PROVIDER_ACTIVE,
        service_score=100.00,
        open_penalty_minor=0,
        score_variant_applied=SCORE_VARIANT_ROLLING_WINDOW,
    )


def test_first_cycle_close_leaves_the_aged_incident_row_untouched(api):
    """Only the variant changed: the closed cycle is counted on the engagement and
    the aged incident keeps its confirmed weight.

    PRD 3.9: "A successful close moves the cycle `FUNDED → CLOSED`, which is
    terminal, and increases the owning engagement's `closed_cycle_count` by 1."

    Design: Difficulty/dual_variant_calc/provider_score_variant_flips_to_rolling_window_on_first_cycle_close
    """
    ctx = _flipped_variant_estate(api)

    closed = fx.close_cycle(api, ctx["cycle_id"], CONTROLLER_HEADERS)
    a.assert_cycle_state(closed, CYCLE_CLOSED)

    engagement = fx.read_engagement(api, ctx["engagement_id"])
    assert engagement["closed_cycle_count"] == 1, (
        f"expected closed_cycle_count 1, got {engagement['closed_cycle_count']}"
    )

    aged = fx.read_incident(api, ctx["aged_incident_id"])
    assert aged["status"] == INCIDENT_CONFIRMED, (
        f"the incident set is unchanged, got {aged['status']}"
    )
    a.assert_pct(aged["weight_points"], 25.00, "weight_points")
