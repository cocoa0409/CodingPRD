"""Breadth tests for the calculations: the incentive clamp, the deferred-revenue
waterfall remainder, and the load-propagation evaluation order.
"""
from prd_bench_local_runner.testing import validate_success

from test_helpers import TEST_USERS, api_client, fixtures as F, validate_success

DISPATCHER = TEST_USERS["dispatcher_headers"]
MANAGER = TEST_USERS["manager_headers"]


def test_incentive_statement_reports_the_unclamped_gross(api):
    """PRD §3.11: "The second step clamps the already-summed gross at 150000 cents: the
    clamped figure is the gross or 150000, whichever is smaller."
    PRD §3.11: "`gross_component_cents` is the unclamped sum of the per-appointment
    components".

    Design: Corner/calculations/incentive_statement_clamps_gross_before_charges
    """
    branch = F.create_branch()
    technician = F.hire_technician(
        branch["id"],
        shift_segments=[{"start_utc": "2026-09-10T08:00:00Z", "end_utc": "2026-09-30T18:00:00Z"}],
        daily_capacity_hours=40,
    )
    F.create_task(code="HVAC-COMP", estimated_hours=3.0, flat_rate_cents=330000)
    appointment = F.book_appointment(
        branch["id"], window_start_utc="2026-09-10T09:00:00Z", window_end_utc="2026-09-10T12:00:00Z"
    )
    F.add_line(appointment["id"], code="HVAC-COMP", status="SOLD")
    F.dispatch_two_calls(appointment["id"])

    statement = validate_success(
        api.get_incentive_statement(
            technician["id"], {"period_year": 2026, "period_month": 9}, MANAGER
        )
    )
    assert statement["gross_component_cents"] == 19800, (
        f"330000 cents at six percent is 19800, got {statement['gross_component_cents']}"
    )
    assert statement["clamped_component_cents"] == 19800
    assert statement["charge_cents"] == 0
    assert statement["incentive_cents"] == 396


def test_deferred_revenue_waterfall_puts_the_odd_cent_in_the_first_bucket(api):
    """PRD §3.8: "the remainder of that division is distributed one cent at a time to the
    first buckets in order."
    PRD §3.8: "for the visit at position i in the ordering, its `deferred_revenue_cents` is
    the base share plus one cent when i is less than the remainder and the base share alone
    otherwise."

    Design: Corner/calculations/deferred_revenue_waterfall_remainder_allocation
    """
    branch, plan, agreement, visits = F.setup_membership(
        annual_price_cents=100000,
        visit_count=3,
        visit_dates=["2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z", "2026-12-01T00:00:00Z"],
    )

    shares = [v["deferred_revenue_cents"] for v in F.list_visits(agreement["id"])]
    # PRD §3.8: "Each bucket receives the agreement's `annual_price_cents` divided by
    # that bucket count using whole-number division, and the remainder of that division
    # is distributed one cent at a time to the first buckets in order."  For 100000 over
    # three buckets the base share is 33333 with a remainder of 1, so the first visit
    # takes the odd cent: 33334, 33333, 33333 — which is also the only split that sums
    # back to the annual price.
    assert shares == [33334, 33333, 33333], (
        f"the odd cent lands on the first bucket, got {shares}"
    )
    assert sum(shares) == 100000, "the buckets must sum back to the annual price"


def test_load_propagation_reads_each_bucket_before_adding_the_hop(api):
    """PRD §3.4: "the increment size is chosen from a bucket keyed on the running total
    *as it stood before this hop was added*".
    PRD §3.4: "A five-hop appointment made entirely of non-appliance tasks therefore
    traces 300, 600, 1200, 1800 and 2700."

    Design: Corner/calculations/load_propagation_pins_bucket_before_increment
    """
    branch = F.create_branch()
    for code, price in (
        ("HVAC-TUNE", 5000),
        ("HVAC-COIL", 6000),
        ("HVAC-DUCT", 7000),
        ("HVAC-THERM", 8000),
        ("HVAC-FILT", 9000),
    ):
        F.create_task(code=code, estimated_hours=1.0, flat_rate_cents=price)

    appointment = F.book_appointment(
        branch["id"],
        window_start_utc="2026-09-10T09:00:00Z",
        window_end_utc="2026-09-10T15:00:00Z",
    )
    for code in ("HVAC-TUNE", "HVAC-COIL", "HVAC-DUCT", "HVAC-THERM"):
        F.add_line(appointment["id"], code=code)

    response = api_client.add_line(
        appointment["id"], {"pricebook_task_code": "HVAC-FILT"}, DISPATCHER
    )
    line = validate_success(response, expected_status=201)
    assert line["flat_rate_cents"] == 9000

    refreshed = F.get_appointment(appointment["id"])
    assert refreshed["load_units_trace"] == [300, 600, 1200, 1800, 2700], (
        f"the pinned evaluation order traces 300, 600, 1200, 1800, 2700, "
        f"got {refreshed['load_units_trace']}"
    )
    assert len(refreshed["load_units_trace"]) == 5