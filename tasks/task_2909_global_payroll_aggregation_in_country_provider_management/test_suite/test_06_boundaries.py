"""Values placed exactly on an inclusive threshold.

One test pair sits a variance exactly on the country's materiality percentage; the
other submits an HR extract at the very millisecond of the input cutoff. Both
boundaries are inclusive, so both requests must be treated as inside the rule.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import (
    CYCLE_DRAFT,
    CYCLE_INPUTS_LOCKED,
    GTN_ESCALATED,
    INPUT_FILE_RECEIVED,
    VARIANCE_BASIS_ABSOLUTE_TOTAL,
)
from test_helpers.test_users import OPS_HEADERS, OPS_USER_ID

# 10 500 000 against a 10 000 000 baseline is exactly 5.00 percent, the country's
# materiality percentage, on an unchanged headcount of 200.
_THRESHOLD_EXTRACT = {"record_count": 200, "gross_declared_minor": 10500000}
_THRESHOLD_RUN = {
    "gross_minor": 10500000,
    "net_minor": 6800000,
    "employer_cost_minor": 2100000,
    "provider_fee_minor": 155000,
    "employee_count": 200,
}

_CUTOFF_INSTANT = "2026-08-26T17:00:00.000Z"


def _threshold_run(api):
    """A second period whose gross moved by exactly the materiality percentage."""
    ctx = fx.setup_baseline_and_locked_second_period(
        api, second_extract_overrides=_THRESHOLD_EXTRACT
    )
    run = fx.submit_run(
        api,
        ctx["cycle_id"],
        ctx["input_file_id"],
        ctx["provider_id"],
        ctx["cycle_version"],
        **_THRESHOLD_RUN,
    )
    return ctx, run


def _extract_at_the_cutoff(api):
    """Move the clock onto the resolved cutoff instant and feed the cycle."""
    ctx = fx.setup_draft_cycle(api)
    fx.set_clock(api, _CUTOFF_INSTANT)
    response = api.create_input_file(f.input_file_payload(ctx["cycle_id"]), OPS_HEADERS)
    return ctx, response


def test_variance_exactly_on_the_materiality_percentage_is_material(api):
    """A movement equal to — not above — the country's materiality percentage, with
    the cash floor also met, makes the variance material.

    PRD 3.5: "`variance_material` is true when the absolute value of the rounded
    `variance_pct` is greater than or equal to the country's `materiality_pct` **and**
    that gross delta is greater than or equal to the country's
    `materiality_floor_minor`."

    Design: Difficulty/boundary_precision_check/variance_material_at_exactly_the_materiality_threshold
    """
    _, run = _threshold_run(api)

    a.assert_variance_analysis(
        run,
        variance_basis=VARIANCE_BASIS_ABSOLUTE_TOTAL,
        variance_pct=5.00,
        headcount_drift_pct=0.00,
        variance_material=True,
    )
    assert run["status"] == GTN_ESCALATED, (
        f"a material run escalates, got {run['status']}"
    )


def test_variance_on_the_threshold_stays_below_the_incident_trigger(api):
    """Escalation alone raises no incident: that needs twice the materiality
    percentage, which a movement sitting exactly on the threshold does not reach.

    PRD 3.5: "A material run moves `SUBMITTED → ESCALATED`, and if in addition the
    absolute value of `variance_pct` is greater than or equal to twice the country's
    `materiality_pct`, a service-level incident is raised automatically for the
    cycle's engagement with `incident_type` `VARIANCE_ESCALATION`, `severity` `SEV3`,
    `status` `OPEN` and `occurred_at` stamped from the current logical clock."

    Design: Difficulty/boundary_precision_check/variance_material_at_exactly_the_materiality_threshold
    """
    ctx, _ = _threshold_run(api)

    incidents, meta = validate_paginated(
        api.list_incidents(OPS_HEADERS, {"engagement_id": ctx["engagement_id"]})
    )
    a.assert_pagination_meta(meta, expected_total=0, expected_has_more=False)
    assert incidents == [], f"no incident should exist, got {incidents}"

    cycle = fx.read_cycle(api, ctx["cycle_id"])
    a.assert_cycle_state(cycle, CYCLE_INPUTS_LOCKED)


def test_extract_submitted_at_exactly_the_cutoff_instant_is_accepted(api):
    """Submitting at the cutoff instant itself is inside the window, and the extract
    is stamped with that same instant.

    PRD 3.4: "The current logical clock must not be strictly after the cycle's
    resolved `input_cutoff_at`; submitting at exactly the cutoff instant is accepted,
    and submitting even one millisecond later is rejected with
    `ERR_INPUT_CUTOFF_PASSED` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/input_file_accepted_exactly_at_the_cutoff_instant
    """
    _, response = _extract_at_the_cutoff(api)

    extract = validate_success(response, 201)
    assert extract["status"] == INPUT_FILE_RECEIVED, (
        f"a submitted extract opens in RECEIVED, got {extract['status']}"
    )
    a.assert_instant_equals(extract["submitted_at"], _CUTOFF_INSTANT, "submitted_at")
    assert extract["validated_record_count"] == 0, (
        f"nothing is validated yet, got {extract['validated_record_count']}"
    )
    a.assert_null_fields(extract, ["rejection_code"])


def test_cutoff_instant_is_the_landed_working_day_at_seventeen_hundred(api):
    """The accepting cycle's cutoff carries millisecond precision at 17:00:00.000Z,
    and the submission stamps the acting principal onto the cycle.

    PRD 3.3: "The resolved instant always carries millisecond precision and its
    time-of-day component is always exactly 17:00:00.000Z."

    Design: Difficulty/boundary_precision_check/input_file_accepted_exactly_at_the_cutoff_instant
    """
    ctx, _ = _extract_at_the_cutoff(api)

    cycle = fx.read_cycle(api, ctx["cycle_id"])
    a.assert_instant_equals(cycle["input_cutoff_at"], _CUTOFF_INSTANT, "input_cutoff_at")
    a.assert_instant_format(cycle["input_cutoff_at"], "input_cutoff_at")
    assert cycle["input_submitter_user_id"] == OPS_USER_ID, (
        "the submitting principal is recorded on the cycle, got "
        f"{cycle['input_submitter_user_id']!r}"
    )
    a.assert_cycle_state(cycle, CYCLE_DRAFT)
