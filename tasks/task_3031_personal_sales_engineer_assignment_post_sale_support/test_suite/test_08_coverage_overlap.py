"""Depth: half-open coverage intervals and the sequence-indexed reassignment rule."""
from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers.api_client import api_client
from test_helpers.fixtures import (
    SALES_OPS,
    accept_assignment,
    create_assignment,
    create_customer,
    create_engineer,
    end_assignment,
    list_assignments_for,
    set_clock,
)


def _customer_with_ended_temporary_coverage():
    """Customer C has one engineer assigned for TEMPORARY_COVERAGE over
    [2026-06-01, 2026-07-01), which has since ended."""
    set_clock("2026-06-01T00:00:00.000Z")
    cover_engineer = create_engineer("Ada Chen", "ada.chen@sweetwater.example", "WEST")
    transfer_engineer = create_engineer("Dana Riggs", "dana.riggs@sweetwater.example",
                                        "MIDWEST")
    customer = create_customer()
    coverage = create_assignment(
        customer, cover_engineer, reason_code="TEMPORARY_COVERAGE",
        effective_until="2026-07-01T00:00:00.000Z",
    )
    accept_assignment(coverage)
    # End it at the far bound of its window so the covered interval is the
    # half-open [2026-06-01, 2026-07-01) the tests below reason about.
    set_clock("2026-07-01T00:00:00.000Z")
    end_assignment(coverage, SALES_OPS)
    return {"customer": customer, "cover_engineer": cover_engineer,
            "transfer_engineer": transfer_engineer, "coverage": coverage}


def test_new_window_inside_a_later_ended_interval_is_rejected():
    """PRD 2.4: "A requested coverage window may not overlap the half-open
    interval of any already-`ENDED` `Assignment` for the same customer that
    carries a later `sequence` value." PRD 2.4: "A genuine overlap surfaces as
    `ERR_ASSIGNMENT_COVERAGE_OVERLAP` at HTTP 409."

    Design: Difficulty/resource_temporal_overlap/assignment_coverage_overlap_with_lower_bound_inclusion
    """
    world = _customer_with_ended_temporary_coverage()
    customer = world["customer"]
    set_clock("2026-06-15T00:00:00.000Z")

    resp = api_client.create_assignment(
        {"customer_id": customer["id"], "engineer_id": world["transfer_engineer"]["id"],
         "reason_code": "PERMANENT_TRANSFER",
         "expected_customer_version": customer_version(customer["id"])},
        SALES_OPS,
    )
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_COVERAGE_OVERLAP)


def test_new_window_adjacent_to_the_closed_bound_is_admitted():
    """PRD 2.4: "Adjacency is permitted: an interval that ends at exactly the
    instant the next one begins is not an overlap."

    Design: Difficulty/resource_temporal_overlap/assignment_coverage_overlap_with_lower_bound_inclusion
    """
    world = _customer_with_ended_temporary_coverage()
    customer = world["customer"]
    set_clock("2026-07-01T00:00:00.000Z")

    created = create_assignment(
        customer, world["transfer_engineer"], reason_code="PERMANENT_TRANSFER",
    )
    assert created["status"] == "PENDING_ACCEPT"


def test_new_window_starts_exactly_when_the_prior_window_opened_is_rejected():
    """PRD 2.4: "An assignment's coverage window is the half-open interval that
    begins at the instant the assignment became `ACTIVE` and ends at the instant
    it was ended, tracked as `assigned_at` and the instant the row left
    `ACTIVE`."

    Design: Difficulty/resource_temporal_overlap/assignment_coverage_overlap_with_lower_bound_inclusion
    """
    world = _customer_with_ended_temporary_coverage()
    customer = world["customer"]
    set_clock("2026-06-01T00:00:00.000Z")

    resp = api_client.create_assignment(
        {"customer_id": customer["id"], "engineer_id": world["transfer_engineer"]["id"],
         "reason_code": "PERMANENT_TRANSFER",
         "expected_customer_version": customer_version(customer["id"])},
        SALES_OPS,
    )
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_COVERAGE_OVERLAP)


def test_rejected_overlap_leaves_no_assignment_row_behind():
    """PRD 2.4: "A requested coverage window may not overlap the half-open
    interval of any already-`ENDED` `Assignment` for the same customer that
    carries a later `sequence` value."

    Design: Difficulty/resource_temporal_overlap/assignment_coverage_overlap_with_lower_bound_inclusion
    """
    world = _customer_with_ended_temporary_coverage()
    customer = world["customer"]
    set_clock("2026-06-15T00:00:00.000Z")
    assert len(list_assignments_for(customer["id"])) == 1

    api_client.create_assignment(
        {"customer_id": customer["id"], "engineer_id": world["transfer_engineer"]["id"],
         "reason_code": "PERMANENT_TRANSFER",
         "expected_customer_version": customer_version(customer["id"])},
        SALES_OPS,
    )
    assert len(list_assignments_for(customer["id"])) == 1


def customer_version(customer_id):
    return validate_success(api_client.get_customer(customer_id, SALES_OPS))["version"]