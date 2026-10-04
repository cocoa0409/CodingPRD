"""Difficulty rule: combinatorial_formula — configuration lead time is the
max over per-module (family base + fabric delta) sums plus a queue tier keyed
on total units, and the install-date gate is inclusive (PRD §3.4, §3.5)."""

from test_helpers import (
    ApiErrorId,
    create_and_lock_configuration,
    create_order,
    make_dealer_headers,
    make_submit_payload,
    setup_dealer_world,
    submit_order,
    validate_error,
)

# 10 x WORKSTATION_6X6 (B) + 4 x TASK_CHAIR_SET (C) + 2 x STORAGE_WALL:
# per-module leads 42+7=49, 28+14=42, 21+0=21 -> max 49; total_units 16 ->
# 3 queue days; max_lead_time_days = 52. Earliest install from the
# 2026-09-01 default clock is 2026-09-01 + 52 = 2026-10-23.
MODULES = [
    {"module_type": "WORKSTATION_6X6", "fabric_grade": "B", "qty": 10},
    {"module_type": "TASK_CHAIR_SET", "fabric_grade": "C", "qty": 4},
    {"module_type": "STORAGE_WALL", "fabric_grade": None, "qty": 2},
]


def _locked_mixed_world(api):
    ctx = setup_dealer_world(
        api,
        family_specs=(
            ("SYS-7500", "SYSTEMS", 42),
            ("SEAT-2200", "SEATING", 28),
            ("STOR-1100", "STORAGE", 21),
        ),
    )
    spec = create_and_lock_configuration(
        api, ctx["dealer"]["id"], modules=[dict(m) for m in MODULES]
    )
    return ctx, spec


def test_lead_time_is_max_module_lead_plus_queue_tier(api):
    """PRD §3.4: "The configuration's manufacturing lead is the maximum of
    those per-module sums, taken over all module entries" and "`max_lead_time_days`
    is the manufacturing lead plus the queue days" — max(49, 42, 21) + 3 =
    52 for 16 total units.

    Design: Difficulty/combinatorial_formula/lead_time_max_over_modules_plus_unit_queue_tier
    """
    _ctx, spec = _locked_mixed_world(api)
    assert spec["max_lead_time_days"] == 52
    assert spec["total_units"] == 16


def test_install_one_day_before_earliest_rejected(api):
    """PRD §3.5: "the `requested_install_date` must be at least the clock
    date plus the spec's `max_lead_time_days` (else
    `ERR_LEAD_TIME_VIOLATION`)" — 2026-10-22 is one day short of
    2026-09-01 + 52.

    Design: Difficulty/combinatorial_formula/lead_time_max_over_modules_plus_unit_queue_tier
    """
    ctx, spec = _locked_mixed_world(api)
    order = create_order(
        api, ctx["agreement"]["id"], spec["id"], ctx["dealer"]["id"],
        requested_install_date="2026-10-22",
    )
    resp = api.submit_project_order(
        order["id"], make_submit_payload(order["version"]),
        make_dealer_headers(ctx["dealer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_LEAD_TIME_VIOLATION)


def test_install_on_earliest_date_accepted(api):
    """PRD §3.5: "the `requested_install_date` must be at least the clock
    date plus the spec's `max_lead_time_days` (else
    `ERR_LEAD_TIME_VIOLATION`)" — 2026-10-23 is exactly the boundary and the
    gate is inclusive (>=), so the submit succeeds.

    Design: Difficulty/combinatorial_formula/lead_time_max_over_modules_plus_unit_queue_tier
    """
    ctx, spec = _locked_mixed_world(api)
    order = create_order(
        api, ctx["agreement"]["id"], spec["id"], ctx["dealer"]["id"],
        requested_install_date="2026-10-23",
    )
    submitted = submit_order(api, order, ctx["dealer"]["id"])
    assert submitted["status"] == "SUBMITTED"
