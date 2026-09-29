"""Re-entrant paths through the two non-linear machines.

A gross-to-net run that is returned and repaired re-enters the cleared branch,
and a filing's penalty dimension returns to assessment when a dispute round is
rejected. Both machines can therefore visit the same state twice.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import (
    CYCLE_INPUTS_LOCKED,
    DECISION_REJECT,
    FILING_LATE,
    FILING_TYPE_INCOME_TAX_WITHHOLDING,
    GTN_CLEARED,
    GTN_ESCALATED,
    GTN_RETURNED,
    PENALTY_ASSESSED,
    PENALTY_DISPUTED,
    PENALTY_OWNER_PROVIDER,
    PROVIDER_ACTIVE,
    VARIANCE_BASIS_ABSOLUTE_TOTAL,
)
from test_helpers.test_users import CONTROLLER_HEADERS, OPS_HEADERS

# A second period 15 percent larger than its baseline in both headcount and cash.
_ESCALATING_EXTRACT = {"record_count": 230, "gross_declared_minor": 10800000}
_ESCALATING_RUN = {
    "gross_minor": 11500000,
    "net_minor": 7400000,
    "employer_cost_minor": 2300000,
    "provider_fee_minor": 170000,
    "employee_count": 230,
}
# The repaired figures land exactly on the baseline gross, so the movement is nil.
_REPAIRED_RUN = {
    "gross_minor": 10000000,
    "net_minor": 6500000,
    "employer_cost_minor": 2000000,
    "provider_fee_minor": 150000,
    "employee_count": 230,
}

_LATE_FILING_COUNTRY = {
    "country_code": "IT",
    "required_filing_types": [FILING_TYPE_INCOME_TAX_WITHHOLDING],
    "penalty_daily_rate_minor": 15000,
}
_SOLVENT_PROVIDER = {
    "legal_name": "BellaPay SpA",
    "annual_fee_minor": 6000000,
    "indemnity_cap_pct": 25.0,
}


def _returned_run(api):
    """An escalated run of the second period that the controller sent back."""
    ctx = fx.setup_baseline_and_locked_second_period(
        api, second_extract_overrides=_ESCALATING_EXTRACT
    )
    run = fx.submit_run(
        api,
        ctx["cycle_id"],
        ctx["input_file_id"],
        ctx["provider_id"],
        ctx["cycle_version"],
        **_ESCALATING_RUN,
    )
    assert run["status"] == GTN_ESCALATED, (
        f"the 15.00 percent move must escalate, got {run['status']}"
    )
    returned = fx.return_run(api, run["id"])
    assert returned["status"] == GTN_RETURNED, (
        f"a RETURN decision returns the run, got {returned['status']}"
    )
    return ctx, returned


def _resubmit_repaired(api, ctx, run_id):
    """Replace the figures of the returned run at the cycle's current version."""
    cycle = fx.read_cycle(api, ctx["cycle_id"])
    return validate_success(
        api.resubmit_gtn_run(
            run_id,
            f.gtn_resubmit_payload(cycle["version"], **_REPAIRED_RUN),
            ctx["provider_headers"],
        )
    )


def _rejected_dispute(api):
    """A wholly provider-owned late penalty whose first dispute round is rejected."""
    ctx = fx.setup_results_approved_cycle(
        api,
        country_overrides=_LATE_FILING_COUNTRY,
        provider_overrides=_SOLVENT_PROVIDER,
    )
    fx.set_clock(api, "2026-09-13T12:00:00Z")
    swept = fx.sweep_filings(api, ctx["cycle_id"])
    filing = a.find_by(swept, "filing_type", FILING_TYPE_INCOME_TAX_WITHHOLDING)
    disputed = fx.open_penalty_dispute(api, filing["id"], ctx["provider_id"])
    return ctx, disputed


def test_returned_run_reenters_the_cleared_branch_on_resubmission(api):
    """The repaired figures are rescored in the resubmission request itself, so the
    run leaves `RETURNED` and re-enters `CLEARED`, a state it had never reached.

    PRD 3.5: "On success the run moves `RETURNED → SUBMITTED`, `return_reason` is
    cleared to null, the cycle's `version` is incremented by 1, and the variance is
    recomputed from the new figures, so the run immediately re-branches to `CLEARED`
    or `ESCALATED` exactly as a first submission would."

    Design: Difficulty/non_linear_state_machine/gtn_run_returned_then_resubmitted_reenters_cleared
    """
    ctx, returned = _returned_run(api)

    repaired = _resubmit_repaired(api, ctx, returned["id"])

    assert repaired["status"] == GTN_CLEARED, (
        f"the repaired run clears, got {repaired['status']}"
    )
    a.assert_minor_amount(repaired["gross_minor"], 10000000, "gross_minor")
    a.assert_variance_analysis(
        repaired,
        variance_basis=VARIANCE_BASIS_ABSOLUTE_TOTAL,
        variance_pct=0.00,
        headcount_drift_pct=15.00,
        variance_material=False,
    )
    assert repaired["return_reason"] is None, (
        f"resubmission clears return_reason, got {repaired['return_reason']!r}"
    )


def test_reentered_run_is_still_the_cycles_only_run(api):
    """Repairing a returned run does not open a second run, and the cycle it
    belongs to never left the locked state through the whole detour.

    PRD 3.5: "and the cycle itself stays in `INPUTS_LOCKED`, since nothing has been
    approved."

    Design: Difficulty/non_linear_state_machine/gtn_run_returned_then_resubmitted_reenters_cleared
    """
    ctx, returned = _returned_run(api)

    _resubmit_repaired(api, ctx, returned["id"])

    cycle = fx.read_cycle(api, ctx["cycle_id"])
    a.assert_cycle_state(cycle, CYCLE_INPUTS_LOCKED)
    a.assert_minor_amount(cycle["gross_total_minor"], 0, "gross_total_minor")

    runs, meta = validate_paginated(
        api.list_gtn_runs(CONTROLLER_HEADERS, {"cycle_id": ctx["cycle_id"]})
    )
    a.assert_pagination_meta(meta, expected_total=1, expected_has_more=False)
    assert runs[0]["id"] == returned["id"], (
        "the repaired run is the same resource as the returned one"
    )


def test_rejected_dispute_returns_the_penalty_dimension_to_assessed(api):
    """A rejected dispute round walks the penalty dimension back to `ASSESSED`,
    counting the round and clearing the reason for the next attempt.

    PRD 3.7: "A `REJECT` decision moves `penalty_status` `DISPUTED → ASSESSED`,
    increases `dispute_round` by 1 and clears `dispute_reason` to null; the provider
    may try again only while `dispute_round` remains below 2, which gives it at most
    two rejected rounds before the door closes."

    Design: Difficulty/non_linear_state_machine/filing_penalty_dimension_cycles_disputed_back_to_assessed
    """
    ctx, disputed = _rejected_dispute(api)

    decided = fx.decide_penalty_dispute(api, disputed["id"], DECISION_REJECT)

    assert decided["penalty_status"] == PENALTY_ASSESSED, (
        f"the dimension returns to ASSESSED, got {decided['penalty_status']}"
    )
    assert decided["dispute_round"] == 1, (
        f"expected dispute_round 1, got {decided['dispute_round']}"
    )
    assert decided["dispute_reason"] is None, (
        f"the reason is cleared, got {decided['dispute_reason']!r}"
    )
    a.assert_penalty_assessment(
        decided,
        late_days=3,
        base_penalty_minor=70000,
        surcharge_minor=7000,
        total_penalty_minor=77000,
        provider_share_minor=77000,
        client_share_minor=0,
        penalty_owner=PENALTY_OWNER_PROVIDER,
    )
    provider = fx.read_provider(api, ctx["provider_id"])
    a.assert_provider_standing(
        provider, status=PROVIDER_ACTIVE, open_penalty_minor=77000
    )


def test_dispute_round_never_disturbs_the_lodgement_dimension(api):
    """Through the dispute and its rejection the lodgement dimension stays at
    `LATE` and every penalty amount is preserved.

    PRD 3.7: "A successful dispute moves `penalty_status` `ASSESSED → DISPUTED`,
    leaves every penalty amount unchanged, and leaves the lodgement `status`
    entirely alone."

    Design: Difficulty/non_linear_state_machine/filing_penalty_dimension_cycles_disputed_back_to_assessed
    """
    _, disputed = _rejected_dispute(api)

    assert disputed["penalty_status"] == PENALTY_DISPUTED, (
        f"the dispute moves the penalty dimension, got {disputed['penalty_status']}"
    )
    assert disputed["status"] == FILING_LATE, (
        f"the lodgement dimension is untouched, got {disputed['status']}"
    )
    a.assert_minor_amount(disputed["total_penalty_minor"], 77000, "total_penalty_minor")
    a.assert_minor_amount(
        disputed["provider_share_minor"], 77000, "provider_share_minor"
    )

    decided = fx.decide_penalty_dispute(api, disputed["id"], DECISION_REJECT)
    assert decided["status"] == FILING_LATE, (
        f"deciding the dispute leaves the lodgement alone, got {decided['status']}"
    )
    filed = fx.read_filing(api, disputed["id"], OPS_HEADERS)
    assert filed["status"] == FILING_LATE, (
        f"the persisted lodgement state is still LATE, got {filed['status']}"
    )
