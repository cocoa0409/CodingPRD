"""Logistics: booking, dispatch capacity, delivery, relocation, abort and return."""
import pytest

from test_helpers import (
    ApiErrorId,
    activate_lease,
    assert_logistics_job,
    attach_accessory_package,
    book_job,
    complete_job,
    create_branch,
    create_lease,
    create_unit,
    dispatch_job,
    get_branch,
    get_job,
    get_lease,
    get_unit,
    make_branch_ops_headers,
    make_leasing_agent_headers,
    set_clock,
    setup_dallas_catalog,
    setup_dallas_installed_lease,
    setup_rural_catalog,
    setup_rural_installed_lease,
    setup_rural_lease,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import AUSTIN_YARD, create_logistics_job_payload

RURAL_SITE = "9 County Road 12, Rural TX"


# ─── Screening ladder: ADA compliance outranks dispatch capacity ─────────────

def _dallas_two_leases_one_slot():
    """One yard with a single daily slot, one compliant lease and one not."""
    ctx = setup_dallas_catalog(
        unit_count=2, branch_overrides={"daily_dispatch_capacity": 1},
        customer_overrides={"credit_limit_cents": 9_000_000})
    ctx["lease_a"] = create_lease(
        ctx["customer"]["id"], ctx["units"][0]["id"], ctx["jurisdiction"]["id"],
        ctx["config"]["id"], site_address="400 Commerce St, Dallas TX",
        start_date="2026-09-01", term_months=12)
    ctx["package_a"] = attach_accessory_package(
        ctx["lease_a"]["id"], "COMBO", ramp_run_ft=36.0, landing_count=2,
        step_count=4)
    ctx["lease_b"] = create_lease(
        ctx["customer"]["id"], ctx["units"][1]["id"], ctx["jurisdiction"]["id"],
        ctx["config"]["id"], site_address="402 Commerce St, Dallas TX",
        start_date="2026-09-01", term_months=12)
    ctx["package_b"] = attach_accessory_package(
        ctx["lease_b"]["id"], "COMBO", ramp_run_ft=30.0, landing_count=1,
        step_count=4)
    ctx["job_a"] = book_job(ctx["lease_a"]["id"], ctx["branch"]["id"],
                            job_type="DELIVERY_INSTALL",
                            scheduled_date="2026-09-01", mileage_miles=180,
                            crew_hours=6.5)
    return ctx


def test_ada_compliance_is_reported_before_the_dispatch_capacity(api):
    """PRD §2.9: "The **first** check that fails decides the response, its error
    code is returned, and no lower-ranked check is consulted — this is what
    makes error responses predictable when a request is wrong in more than one
    way at once."
    PRD §3.8: "If the job is a `DELIVERY_INSTALL` into a jurisdiction whose
    `ada_ramp_required` is true, the lease must carry an accessory package
    scored `COMPLIANT`, or the booking is refused with
    `ERR_ADA_PACKAGE_NON_COMPLIANT`."
    PRD §3.8: "And the branch must have a dispatch slot free on the requested
    day: the number of jobs whose `origin_branch_id` is that branch, whose
    `scheduled_date` is exactly the requested calendar date, and whose status is
    either `SCHEDULED` or `DISPATCHED` must be strictly less than the branch's
    `daily_dispatch_capacity`, or the booking is refused with
    `ERR_BRANCH_DISPATCH_CAPACITY_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/ada_safety_beats_branch_day_capacity_on_job_creation
    """
    ctx = _dallas_two_leases_one_slot()

    assert ctx["package_a"]["compliance_status"] == "COMPLIANT"
    assert ctx["package_b"]["compliance_status"] == "NON_COMPLIANT", (
        f"a 30.0 ft run falls short of the required 36.0 ft, got "
        f"{ctx['package_b']['compliance_status']}")

    # This booking violates both the ADA rank (9) and the day-capacity rank (21).
    response = api.create_logistics_job(
        create_logistics_job_payload(ctx["lease_b"]["id"], ctx["branch"]["id"],
                                     job_type="DELIVERY_INSTALL",
                                     scheduled_date="2026-09-01",
                                     mileage_miles=180, crew_hours=6.5),
        make_branch_ops_headers(ctx["branch"]["id"]))
    validate_error(response, ApiErrorId.ERR_ADA_PACKAGE_NON_COMPLIANT.value)
    assert response.json()["data"]["error_id"] != (
        "ERR_BRANCH_DISPATCH_CAPACITY_EXCEEDED"), (
        "the rank-9 safety check must pre-empt the rank-21 capacity check")


def test_the_ada_rejected_booking_consumes_no_dispatch_slot(api):
    """PRD §3.8: "If the job is a `DELIVERY_INSTALL` into a jurisdiction whose
    `ada_ramp_required` is true, the lease must carry an accessory package
    scored `COMPLIANT`, or the booking is refused with
    `ERR_ADA_PACKAGE_NON_COMPLIANT`."
    PRD §3.5: "A lease with no package at all, or with a `NON_COMPLIANT` one, is
    refused at booking with `ERR_ADA_PACKAGE_NON_COMPLIANT`."

    Design: Difficulty/priority_pair_validation_conflict/ada_safety_beats_branch_day_capacity_on_job_creation
    """
    ctx = _dallas_two_leases_one_slot()

    validate_error(
        api.create_logistics_job(
            create_logistics_job_payload(ctx["lease_b"]["id"], ctx["branch"]["id"],
                                         job_type="DELIVERY_INSTALL",
                                         scheduled_date="2026-09-01",
                                         mileage_miles=180, crew_hours=6.5),
            make_branch_ops_headers(ctx["branch"]["id"])),
        ApiErrorId.ERR_ADA_PACKAGE_NON_COMPLIANT.value)

    jobs, meta = validate_paginated(api.list_logistics_jobs(
        make_branch_ops_headers(ctx["branch"]["id"]),
        params={"origin_branch_id": ctx["branch"]["id"],
                "scheduled_date": "2026-09-01"}))
    assert meta["total_count"] == 1, (
        f"only the compliant lease's job may hold the day's slot, got "
        f"{meta['total_count']}")
    assert jobs[0]["id"] == ctx["job_a"]["id"]


# ─── Dispatch capacity is a single-calendar-date bucket ──────────────────────

def _rural_three_leases_one_slot():
    ctx = setup_rural_catalog(
        unit_count=3, branch_overrides={"daily_dispatch_capacity": 1},
        customer_overrides={"credit_tier": "STANDARD",
                            "credit_limit_cents": 9_000_000})
    ctx["leases"] = [
        create_lease(ctx["customer"]["id"], ctx["units"][i]["id"],
                     ctx["jurisdiction"]["id"], ctx["config"]["id"],
                     site_address=f"{i + 1} Rig Road, Rural TX",
                     start_date="2026-11-05", term_months=12)
        for i in range(3)
    ]
    ctx["job_a"] = book_job(ctx["leases"][0]["id"], ctx["branch"]["id"],
                            job_type="DELIVERY_INSTALL",
                            scheduled_date="2026-11-02", mileage_miles=60,
                            crew_hours=4.0)
    return ctx


def test_a_second_job_on_a_full_dispatch_day_is_rejected(api):
    """PRD §3.8: "And the branch must have a dispatch slot free on the requested
    day: the number of jobs whose `origin_branch_id` is that branch, whose
    `scheduled_date` is exactly the requested calendar date, and whose status is
    either `SCHEDULED` or `DISPATCHED` must be strictly less than the branch's
    `daily_dispatch_capacity`, or the booking is refused with
    `ERR_BRANCH_DISPATCH_CAPACITY_EXCEEDED`."
    PRD §3.8: "The **mileage line** is banded on the marginal principle: the
    first 50 miles are included and cost nothing; the next 100 miles — that is,
    the portion of the haul lying above 50 miles and up to a ceiling of 150
    miles — are charged at $9.50 per mile; and every mile beyond 150 is charged
    at $14.50 per mile."

    PRD §3.8: "The **crew line** takes the booked `crew_hours`, rounds them
    **up** to a whole number of hours, multiplies by the origin branch's
    `labor_rate_cents_per_hour`, and applies a difficulty factor that depends on
    the job type — 1.0 for `DELIVERY_INSTALL`, 0.75 for `TEARDOWN_RETURN`, and
    1.5 for `RELOCATION`, since re-siting an occupied building is the most
    delicate of the three — with the product rounded half up to a whole cent."

    Design: Difficulty/resource_temporal_overlap/branch_day_capacity_counts_open_jobs_within_one_calendar_date
    """
    ctx = _rural_three_leases_one_slot()
    assert ctx["job_a"]["transport_cost_cents"] == 46_300, (
        f"Expected 10 band-two miles at 950 plus 4 crew hours at 9200 = 46300, "
        f"got {ctx['job_a']['transport_cost_cents']}")

    response = api.create_logistics_job(
        create_logistics_job_payload(ctx["leases"][1]["id"], ctx["branch"]["id"],
                                     job_type="DELIVERY_INSTALL",
                                     scheduled_date="2026-11-02",
                                     mileage_miles=60, crew_hours=4.0),
        make_branch_ops_headers(ctx["branch"]["id"]))
    validate_error(response,
                   ApiErrorId.ERR_BRANCH_DISPATCH_CAPACITY_EXCEEDED.value)

    _, meta = validate_paginated(api.list_logistics_jobs(
        make_branch_ops_headers(ctx["branch"]["id"]),
        params={"origin_branch_id": ctx["branch"]["id"]}))
    assert meta["total_count"] == 1, (
        f"the rejected booking must not persist, got {meta['total_count']}")


def test_the_next_calendar_day_has_its_own_dispatch_budget(api):
    """PRD §3.8: "The window is the single calendar date and nothing else — no
    adjacency, no buffer, no neighbouring days."
    PRD §3.8: "And the branch must have a dispatch slot free on the requested
    day: the number of jobs whose `origin_branch_id` is that branch, whose
    `scheduled_date` is exactly the requested calendar date, and whose status is
    either `SCHEDULED` or `DISPATCHED` must be strictly less than the branch's
    `daily_dispatch_capacity`, or the booking is refused with
    `ERR_BRANCH_DISPATCH_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/branch_day_capacity_counts_open_jobs_within_one_calendar_date
    """
    ctx = _rural_three_leases_one_slot()
    validate_error(
        api.create_logistics_job(
            create_logistics_job_payload(ctx["leases"][1]["id"], ctx["branch"]["id"],
                                         job_type="DELIVERY_INSTALL",
                                         scheduled_date="2026-11-02",
                                         mileage_miles=60, crew_hours=4.0),
            make_branch_ops_headers(ctx["branch"]["id"])),
        ApiErrorId.ERR_BRANCH_DISPATCH_CAPACITY_EXCEEDED.value)

    next_day = validate_success(
        api.create_logistics_job(
            create_logistics_job_payload(ctx["leases"][2]["id"], ctx["branch"]["id"],
                                         job_type="DELIVERY_INSTALL",
                                         scheduled_date="2026-11-03",
                                         mileage_miles=60, crew_hours=4.0),
            make_branch_ops_headers(ctx["branch"]["id"])),
        201)
    assert_logistics_job(next_day)
    assert next_day["scheduled_date"] == "2026-11-03", (
        f"Expected the job on the following day, got {next_day['scheduled_date']}")
    assert next_day["status"] == "SCHEDULED"

    _, meta = validate_paginated(api.list_logistics_jobs(
        make_branch_ops_headers(ctx["branch"]["id"]),
        params={"origin_branch_id": ctx["branch"]["id"]}))
    assert meta["total_count"] == 2, (
        f"Expected the two accepted bookings, got {meta['total_count']}")


# ─── Dispatch then abort conserves the yard count ────────────────────────────

def _rural_dispatched_delivery():
    ctx = setup_rural_catalog(unit_count=2)
    ctx["lease"] = create_lease(ctx["customer"]["id"], ctx["units"][0]["id"],
                                ctx["jurisdiction"]["id"], ctx["config"]["id"],
                                site_address="1 Rig Road, Rural TX",
                                start_date="2026-10-01", term_months=12)
    activate_lease(ctx["lease"]["id"])
    job = book_job(ctx["lease"]["id"], ctx["branch"]["id"],
                   job_type="DELIVERY_INSTALL", scheduled_date="2026-10-01",
                   mileage_miles=40, crew_hours=4.0)
    ctx["job"] = dispatch_job(job["id"], ctx["branch"]["id"])
    return ctx


def test_aborting_a_dispatched_delivery_restores_the_yard_count(api):
    """PRD §3.8: "A job already `DISPATCHED` may be cancelled only when it is a
    `DELIVERY_INSTALL` — the crew turns the load around before it is set —
    moving `DISPATCHED → CANCELLED`, taking the unit back
    `IN_TRANSIT → RESERVED`, incrementing the unit's `version`, and recomputing
    the custody branch's counters so that `units_in_yard` rises by one, exactly
    reversing what dispatch did; the dispatch slot is released here as well."
    PRD §2.10: "`units_in_yard` is the number of units whose `current_branch_id`
    is this branch and whose status is one of `IN_FLEET`, `RESERVED`,
    `RETURNED`, or `REFURBISHING`; those four statuses are collectively the "on
    the yard" statuses, while `IN_TRANSIT` and `ON_LEASE` are off-yard."

    Design: Difficulty/compensating_invariant/dispatch_then_abort_conserves_the_yard_unit_count
    """
    ctx = _rural_dispatched_delivery()
    before = get_branch(ctx["branch"]["id"])
    assert before["units_in_yard"] == 1, (
        f"one of the two units is in transit, so the yard holds 1; got "
        f"{before['units_in_yard']}")

    cancelled = validate_success(api.cancel_logistics_job(
        ctx["job"]["id"], make_branch_ops_headers(ctx["branch"]["id"]),
        {"cancellation_reason": "Site not ready"}))
    assert cancelled["status"] == "CANCELLED", (
        f"Expected CANCELLED, got {cancelled['status']}")

    after = get_branch(ctx["branch"]["id"])
    assert after["units_in_yard"] == 2, (
        f"the abort must restore the yard count to 2, got "
        f"{after['units_in_yard']}")
    assert after["units_available"] == 1, (
        f"the aborted unit returns to RESERVED, not IN_FLEET, so only the "
        f"untouched unit is available; got {after['units_available']}")
    assert float(after["utilization_pct"]) == pytest.approx(50.00, abs=0.005), (
        f"one of two assigned units is unavailable, so utilization is 50.00; "
        f"got {after['utilization_pct']}")


def test_aborted_delivery_returns_the_unit_to_reserved_without_unwinding_billing(api):
    """PRD §3.8: "A job already `DISPATCHED` may be cancelled only when it is a
    `DELIVERY_INSTALL` — the crew turns the load around before it is set —
    moving `DISPATCHED → CANCELLED`, taking the unit back
    `IN_TRANSIT → RESERVED`, incrementing the unit's `version`, and recomputing
    the custody branch's counters so that `units_in_yard` rises by one, exactly
    reversing what dispatch did; the dispatch slot is released here as well."
    PRD §3.7: "The billing axis moves on its own schedule, and nothing on the
    occupancy axis pushes it."

    Design: Difficulty/compensating_invariant/dispatch_then_abort_conserves_the_yard_unit_count
    """
    ctx = _rural_dispatched_delivery()

    validate_success(api.cancel_logistics_job(
        ctx["job"]["id"], make_branch_ops_headers(ctx["branch"]["id"]),
        {"cancellation_reason": "Site not ready"}))

    aborted_unit = get_unit(ctx["units"][0]["id"])
    assert aborted_unit["status"] == "RESERVED", (
        f"the aborted load goes back to RESERVED, got {aborted_unit['status']}")
    untouched_unit = get_unit(ctx["units"][1]["id"])
    assert untouched_unit["status"] == "IN_FLEET", (
        f"the second unit is unaffected, got {untouched_unit['status']}")

    lease = get_lease(ctx["lease"]["id"])
    assert lease["billing_status"] == "ACCRUING", (
        f"an aborted haul does not unwind billing, got {lease['billing_status']}")
    assert lease["occupancy_status"] == "PENDING", (
        f"the building never landed, so occupancy stays PENDING, got "
        f"{lease['occupancy_status']}")


# ─── Teardown completion cascades lease -> unit -> branch counters ───────────

def _dallas_dispatched_teardown_to_austin():
    ctx = setup_dallas_installed_lease()
    ctx["austin"] = create_branch(**AUSTIN_YARD)
    set_clock("2027-06-15T00:00:00Z")
    job = book_job(ctx["lease"]["id"], ctx["austin"]["id"],
                   job_type="TEARDOWN_RETURN", scheduled_date="2027-06-15",
                   mileage_miles=180, crew_hours=5.0,
                   destination_branch_id=ctx["austin"]["id"])
    ctx["teardown_job"] = dispatch_job(job["id"], ctx["austin"]["id"])
    return ctx


def test_teardown_completion_vacates_the_lease_and_moves_unit_custody(api):
    """PRD §3.8: "When there is room, the lease's occupancy axis moves
    `INSTALLED → VACATED` with `actual_vacated_date` stamped from the logical
    clock's calendar date and its `version` incremented; because the lease
    vacated, the unit moves `IN_TRANSIT → RETURNED` with its `current_branch_id`
    rewritten to the job's `destination_branch_id` and its `version`
    incremented; and because the unit re-entered a yard status at a new branch,
    the destination branch's `units_in_yard`, `units_available` and
    `utilization_pct` are all recomputed."
    PRD §3.8: "The lease's billing axis is not touched here — settlement waits
    for the damage inspection."

    Design: Difficulty/transitive_cascade/teardown_completion_cascades_lease_then_unit_then_branch_counters
    """
    ctx = _dallas_dispatched_teardown_to_austin()

    completed = validate_success(api.complete_logistics_job(
        ctx["teardown_job"]["id"], make_branch_ops_headers(ctx["austin"]["id"])))
    assert completed["status"] == "COMPLETED", (
        f"Expected COMPLETED, got {completed['status']}")
    assert completed["transport_cost_cents"] == 249_500, (
        f"Expected 138500 mileage + 33000 crew at Austin's 8800 rate + 78000 "
        f"oversize = 249500, got {completed['transport_cost_cents']}")

    lease = get_lease(ctx["lease"]["id"])
    assert lease["occupancy_status"] == "VACATED", (
        f"Expected VACATED, got {lease['occupancy_status']}")
    assert lease["actual_vacated_date"] == "2027-06-15", (
        f"Expected the clock's date stamped, got {lease['actual_vacated_date']}")
    assert lease["billing_status"] == "ACCRUING", (
        f"settlement waits for the inspection, got {lease['billing_status']}")

    unit = get_unit(ctx["unit"]["id"])
    assert unit["status"] == "RETURNED", (
        f"Expected RETURNED, got {unit['status']}")
    assert unit["current_branch_id"] == ctx["austin"]["id"], (
        f"custody must move to the receiving yard, got {unit['current_branch_id']}")


def test_teardown_completion_recomputes_both_branch_counter_sets(api):
    """PRD §2.10: "Each branch publishes three derived counters that must be
    recomputed from scratch — never incrementally patched — after every write
    that changes a unit's status or its custody branch."
    PRD §2.10: "And `utilization_pct` measures the share of the branch's
    assigned fleet that is not immediately leasable: take the total number of
    units whose `current_branch_id` is this branch, regardless of status;
    subtract `units_available` from that total; divide the difference by the
    total; multiply by one hundred; and round the result half up to two decimal
    places. When the branch has no units assigned at all, `utilization_pct` is
    0.00 and no division is attempted."

    Design: Difficulty/transitive_cascade/teardown_completion_cascades_lease_then_unit_then_branch_counters
    """
    ctx = _dallas_dispatched_teardown_to_austin()

    validate_success(api.complete_logistics_job(
        ctx["teardown_job"]["id"], make_branch_ops_headers(ctx["austin"]["id"])))

    austin = get_branch(ctx["austin"]["id"])
    assert austin["units_in_yard"] == 1, (
        f"the returned unit lands in Austin's yard, got {austin['units_in_yard']}")
    assert austin["units_available"] == 0, (
        f"a RETURNED unit is not leasable, got {austin['units_available']}")
    assert float(austin["utilization_pct"]) == pytest.approx(100.00, abs=0.005), (
        f"Austin's single assigned unit is unavailable, so utilization is "
        f"100.00; got {austin['utilization_pct']}")

    dallas = get_branch(ctx["branch"]["id"])
    assert dallas["units_in_yard"] == 0, (
        f"Dallas no longer holds the unit, got {dallas['units_in_yard']}")
    assert dallas["units_available"] == 0, (
        f"Dallas has nothing leasable left, got {dallas['units_available']}")
    assert float(dallas["utilization_pct"]) == pytest.approx(0.00, abs=0.005), (
        f"with no units assigned Dallas reports 0.00, got "
        f"{dallas['utilization_pct']}")


# ─── Corner coverage ─────────────────────────────────────────────────────────

def test_transport_band_three_is_empty_at_exactly_one_hundred_fifty_miles(api):
    """PRD §3.8: "The **mileage line** is banded on the marginal principle: the
    first 50 miles are included and cost nothing; the next 100 miles — that is,
    the portion of the haul lying above 50 miles and up to a ceiling of 150
    miles — are charged at $9.50 per mile; and every mile beyond 150 is charged
    at $14.50 per mile."
    PRD §3.8: "A haul of exactly 150 miles therefore produces one hundred
    chargeable band-two miles and zero band-three miles."

    PRD §3.8: "The **crew line** takes the booked `crew_hours`, rounds them
    **up** to a whole number of hours, multiplies by the origin branch's
    `labor_rate_cents_per_hour`, and applies a difficulty factor that depends on
    the job type — 1.0 for `DELIVERY_INSTALL`, 0.75 for `TEARDOWN_RETURN`, and
    1.5 for `RELOCATION`, since re-siting an occupied building is the most
    delicate of the three — with the product rounded half up to a whole cent."

    Design: Corner/calculations/transport_band_three_is_empty_at_exactly_one_hundred_fifty_miles
    """
    ctx = setup_rural_catalog(unit_count=2)
    lease_a = create_lease(ctx["customer"]["id"], ctx["units"][0]["id"],
                           ctx["jurisdiction"]["id"], ctx["config"]["id"],
                           site_address="1 Rig Road, Rural TX",
                           start_date="2026-10-01", term_months=12)
    lease_b = create_lease(ctx["customer"]["id"], ctx["units"][1]["id"],
                           ctx["jurisdiction"]["id"], ctx["config"]["id"],
                           site_address="2 Rig Road, Rural TX",
                           start_date="2026-10-01", term_months=12)

    at_ceiling = book_job(lease_a["id"], ctx["branch"]["id"],
                          job_type="DELIVERY_INSTALL", scheduled_date="2026-10-01",
                          mileage_miles=150, crew_hours=4.0)
    one_over = book_job(lease_b["id"], ctx["branch"]["id"],
                        job_type="DELIVERY_INSTALL", scheduled_date="2026-10-02",
                        mileage_miles=151, crew_hours=4.0)

    assert at_ceiling["transport_cost_cents"] == 131_800, (
        f"Expected 100 band-two miles at 950 plus 36800 crew = 131800, got "
        f"{at_ceiling['transport_cost_cents']}")
    assert one_over["transport_cost_cents"] == 133_250, (
        f"Expected one extra band-three mile at 1450, got "
        f"{one_over['transport_cost_cents']}")
    assert (one_over["transport_cost_cents"]
            - at_ceiling["transport_cost_cents"]) == 1_450, (
        "the 151st mile must cost exactly the band-three rate")


def test_completing_a_scheduled_job_is_refused(api):
    """PRD §3.8: "Dispatching a job that is not `SCHEDULED` is refused with
    `ERR_JOB_NOT_DISPATCHABLE`, while a job addressed for completion while it is
    still `SCHEDULED` — or from any state other than `DISPATCHED` — is refused
    with `ERR_INVALID_STATE`."
    PRD §3.8: "Completing a job moves it `DISPATCHED → COMPLETED` and is where
    the heaviest cascades in the system fire."

    Design: Corner/state_machines/complete_a_scheduled_job_returns_job_not_dispatchable
    """
    ctx = setup_rural_lease()
    validate_success(api.activate_lease(ctx["lease"]["id"],
                                        make_leasing_agent_headers()))
    job = book_job(ctx["lease"]["id"], ctx["branch"]["id"],
                   job_type="DELIVERY_INSTALL", scheduled_date="2026-10-01",
                   mileage_miles=40, crew_hours=4.0)

    response = api.complete_logistics_job(
        job["id"], make_branch_ops_headers(ctx["branch"]["id"]))
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    assert get_job(job["id"])["status"] == "SCHEDULED", (
        "the refused completion must leave the job SCHEDULED")
    assert get_unit(ctx["unit"]["id"])["status"] == "RESERVED", (
        "the refused completion must leave the unit RESERVED")
    assert get_lease(ctx["lease"]["id"])["occupancy_status"] == "PENDING", (
        "the refused completion must leave the lease PENDING")


def test_relocation_completion_resites_the_lease_without_touching_yard_counters(api):
    """PRD §3.8: "Completing a `RELOCATION` job requires the lease to be
    `INSTALLED` and drives the self-loop `ON_LEASE → ON_LEASE`, leaving the unit
    exactly where it was: the unit's `lifetime_relocations` is incremented by
    one, the lease's `site_address` is rewritten to the job's
    `new_site_address`, and the lease's `relocation_surcharge_cents` is
    increased by eighty-five percent of that job's `transport_cost_cents`,
    rounded half up to a whole cent — the lessor absorbs the remaining fifteen
    percent."
    PRD §3.8: "Both the unit's `version` and the lease's `version` are
    incremented, and no branch counter moves, because the building never
    re-enters a yard."

    PRD §3.8: "The **mileage line** is banded on the marginal principle: the
    first 50 miles are included and cost nothing; the next 100 miles — that is,
    the portion of the haul lying above 50 miles and up to a ceiling of 150
    miles — are charged at $9.50 per mile; and every mile beyond 150 is charged
    at $14.50 per mile."
    PRD §3.8: "The **crew line** takes the booked `crew_hours`, rounds them
    **up** to a whole number of hours, multiplies by the origin branch's
    `labor_rate_cents_per_hour`, and applies a difficulty factor that depends on
    the job type — 1.0 for `DELIVERY_INSTALL`, 0.75 for `TEARDOWN_RETURN`, and
    1.5 for `RELOCATION`, since re-siting an occupied building is the most
    delicate of the three — with the product rounded half up to a whole cent."

    Design: Corner/state_machines/relocation_completion_resites_lease_without_touching_yard_counters
    """
    ctx = setup_rural_installed_lease()
    assert get_branch(ctx["branch"]["id"])["units_in_yard"] == 0

    job = book_job(ctx["lease"]["id"], ctx["branch"]["id"], job_type="RELOCATION",
                   scheduled_date="2026-12-01", mileage_miles=200, crew_hours=6.0,
                   new_site_address="77 Pad 4, Rural TX")
    assert job["transport_cost_cents"] == 250_300, (
        f"Expected 167500 mileage plus 82800 crew at the 1.5 relocation factor "
        f"= 250300, got {job['transport_cost_cents']}")

    dispatch_job(job["id"], ctx["branch"]["id"])
    completed = complete_job(job["id"], ctx["branch"]["id"])
    assert completed["status"] == "COMPLETED"

    lease = get_lease(ctx["lease"]["id"])
    assert lease["site_address"] == "77 Pad 4, Rural TX", (
        f"the site address must be rewritten, got {lease['site_address']}")
    assert lease["relocation_surcharge_cents"] == 212_755, (
        f"Expected 85% of 250300 = 212755, got "
        f"{lease['relocation_surcharge_cents']}")
    assert lease["occupancy_status"] == "INSTALLED", (
        f"a relocation leaves the lease INSTALLED, got {lease['occupancy_status']}")

    unit = get_unit(ctx["unit"]["id"])
    assert unit["lifetime_relocations"] == 1, (
        f"Expected lifetime_relocations 1, got {unit['lifetime_relocations']}")
    assert unit["status"] == "ON_LEASE", (
        f"a relocation never re-enters a yard, got {unit['status']}")
    assert get_branch(ctx["branch"]["id"])["units_in_yard"] == 0, (
        "no branch counter may move on a relocation")


def test_suspended_origin_branch_cannot_book_a_logistics_job(api):
    """PRD §3.8: "The origin branch must be `OPERATIONAL`, or the booking is
    refused with `ERR_BRANCH_SUSPENDED`."
    PRD §3.1: "A branch also carries an operational posture in its `status`,
    which is either `OPERATIONAL` or `SUSPENDED` and defaults to `OPERATIONAL`
    when the caller omits it."

    Design: Corner/validations/suspended_origin_branch_cannot_book_a_logistics_job
    """
    ctx = setup_rural_lease()
    suspended = create_branch(name="Closed Yard", region_code="TX-W",
                              yard_capacity_units=5, daily_dispatch_capacity=2,
                              labor_rate_cents_per_hour=8_800, status="SUSPENDED")
    assert suspended["status"] == "SUSPENDED", (
        f"Expected the branch to be registered SUSPENDED, got {suspended['status']}")
    validate_success(api.activate_lease(ctx["lease"]["id"],
                                        make_leasing_agent_headers()))

    response = api.create_logistics_job(
        create_logistics_job_payload(ctx["lease"]["id"], suspended["id"],
                                     job_type="DELIVERY_INSTALL",
                                     scheduled_date="2026-10-01",
                                     mileage_miles=40, crew_hours=4.0),
        make_branch_ops_headers(suspended["id"]))
    validate_error(response, ApiErrorId.ERR_BRANCH_SUSPENDED.value)

    _, meta = validate_paginated(api.list_logistics_jobs(
        make_branch_ops_headers(suspended["id"]),
        params={"origin_branch_id": suspended["id"]}))
    assert meta["total_count"] == 0, (
        f"the refused booking must not persist, got {meta['total_count']}")


def test_teardown_into_a_full_yard_is_rejected(api):
    """PRD §3.8: "Completing a `TEARDOWN_RETURN` job first requires room in the
    receiving yard: the destination branch's `units_in_yard` must be strictly
    less than its `yard_capacity_units`, or the completion is refused with
    `ERR_YARD_CAPACITY_EXCEEDED` and the crew has nowhere to put the building."
    PRD §3.1: "A branch is registered with a display `name` and a `region_code`
    such as "TX-N", together with three operating capacities:
    `yard_capacity_units`, the hard ceiling on how many units may sit in the
    yard at one time; `daily_dispatch_capacity`, the number of logistics jobs
    the branch may hold against any one scheduled calendar day; and
    `labor_rate_cents_per_hour`, the crew labour rate that later drives both
    haulage pricing and refurbishment estimates."

    Design: Corner/validations/teardown_into_a_full_yard_is_rejected
    """
    ctx = setup_rural_installed_lease()
    small_yard = create_branch(name="Austin Yard", region_code="TX-C",
                               yard_capacity_units=1, daily_dispatch_capacity=3,
                               labor_rate_cents_per_hour=8_800)
    create_unit(ctx["spec"]["id"], small_yard["id"], serial_number="MSU-2050")
    assert get_branch(small_yard["id"])["units_in_yard"] == 1, (
        "the parked unit already fills the one-unit yard")

    set_clock("2026-10-20T00:00:00Z")
    job = book_job(ctx["lease"]["id"], small_yard["id"],
                   job_type="TEARDOWN_RETURN", scheduled_date="2026-10-20",
                   mileage_miles=40, crew_hours=4.0,
                   destination_branch_id=small_yard["id"])
    dispatch_job(job["id"], small_yard["id"])

    response = api.complete_logistics_job(
        job["id"], make_branch_ops_headers(small_yard["id"]))
    validate_error(response, ApiErrorId.ERR_YARD_CAPACITY_EXCEEDED.value)

    assert get_job(job["id"])["status"] == "DISPATCHED", (
        "the refused completion must leave the job DISPATCHED")
    lease = get_lease(ctx["lease"]["id"])
    assert lease["occupancy_status"] == "INSTALLED", (
        f"the lease must not vacate, got {lease['occupancy_status']}")
    assert lease["actual_vacated_date"] is None
    unit = get_unit(ctx["unit"]["id"])
    assert unit["status"] == "IN_TRANSIT", (
        f"the unit stays in transit, got {unit['status']}")
    assert unit["current_branch_id"] == ctx["branch"]["id"], (
        "custody may not move to a yard that had no room")
    assert get_branch(small_yard["id"])["units_in_yard"] == 1


def test_dispatching_before_activation_is_refused(api):
    """PRD §3.8: "For a `DELIVERY_INSTALL` job, the lease's billing axis must be
    `ACCRUING` — an unactivated lease is refused with `ERR_LEASE_NOT_ACTIVATED`
    — and, where the jurisdiction's `permit_required` is true, there must be a
    permit application on that lease sitting at `APPROVED`, failing which the
    dispatch is refused with `ERR_PERMIT_NOT_APPROVED`; a jurisdiction that does
    not require a permit imposes no such condition."
    PRD §3.8: "On success the unit moves `RESERVED → IN_TRANSIT`, its `version`
    is incremented, and its custody branch's `units_in_yard`, `units_available`
    and `utilization_pct` are all recomputed, with the in-yard count dropping by
    one as the building leaves the fence."

    Design: Corner/errors/dispatch_before_activation_returns_lease_not_activated
    """
    ctx = setup_rural_lease()
    assert ctx["lease"]["billing_status"] == "UNBILLED"
    job = book_job(ctx["lease"]["id"], ctx["branch"]["id"],
                   job_type="DELIVERY_INSTALL", scheduled_date="2026-10-01",
                   mileage_miles=40, crew_hours=4.0)

    response = api.dispatch_logistics_job(
        job["id"], make_branch_ops_headers(ctx["branch"]["id"]))
    validate_error(response, ApiErrorId.ERR_LEASE_NOT_ACTIVATED.value)

    assert get_job(job["id"])["status"] == "SCHEDULED", (
        "the refused dispatch must leave the job SCHEDULED")
    assert get_unit(ctx["unit"]["id"])["status"] == "RESERVED", (
        "the refused dispatch must leave the unit in the yard")
    assert get_branch(ctx["branch"]["id"])["units_in_yard"] == 1, (
        "the in-yard count must not drop for a refused dispatch")
