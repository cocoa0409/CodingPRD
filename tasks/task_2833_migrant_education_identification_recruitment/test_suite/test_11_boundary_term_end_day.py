"""The last eligible day is inclusive, so the sweep warns on it and expires after it."""

from test_helpers import fixtures
from test_helpers.assertions import (
    assert_date_equals,
    assert_int_equals,
    assert_is_null,
)
from test_helpers.constants import (
    ELIGIBILITY_CONTINUATION,
    ELIGIBILITY_TERM_EXPIRED,
    TERM_EXPIRED,
    TERM_EXPIRING,
)


def _term_ending_mid_2029(client):
    """A certified child whose term runs 2026-07-01 through the inclusive 2029-06-30."""
    bundle = fixtures.certified_child(
        client, coe_overrides={"residency_date": "2026-07-01", "qc_hold_exempt": True}
    )
    term = fixtures.only_term_for(client, bundle.student["id"])
    assert_date_equals(term["term_end_on"], "2029-06-30", "term.term_end_on")
    bundle.term = term
    return bundle


def test_a_clock_sitting_on_the_last_eligible_day_only_warns(client):
    """On the closing day itself the term becomes EXPIRING rather than EXPIRED.

    "Because `term_end_on` is the inclusive last eligible day, a clock sitting exactly on
    `term_end_on` never expires the term."

    Design: Difficulty/boundary_precision_check/term_end_on_is_the_inclusive_last_eligible_day_of_the_sweep
    """
    bundle = _term_ending_mid_2029(client)
    fixtures.set_clock(client, "2029-06-30T23:59:59Z")

    result = fixtures.sweep(client)

    assert_int_equals(result["swept_count"], 1, "sweep.swept_count")
    assert_int_equals(result["expiring_count"], 1, "sweep.expiring_count")
    assert_int_equals(result["expired_count"], 0, "sweep.expired_count")
    assert_int_equals(result["lapsed_count"], 0, "sweep.lapsed_count")
    assert_int_equals(result["expired_term_ids"], [], "sweep.expired_term_ids")

    term = fixtures.read_term(client, bundle.term["id"])
    assert_int_equals(term["status"], TERM_EXPIRING, "term.status")
    assert_is_null(term["reidentification_due_on"], "term.reidentification_due_on")

    student = fixtures.read_student(client, bundle.student["id"])
    assert_int_equals(
        student["eligibility_status"],
        ELIGIBILITY_CONTINUATION,
        "student.eligibility_status",
    )
    assert_date_equals(
        student["eligibility_expires_on"], "2029-06-30", "student.eligibility_expires_on"
    )


def test_the_first_clock_past_the_last_eligible_day_expires_the_term(client):
    """One day later the same term expires and the grace period is dated.

    "The first branch handles expiry and covers both `ACTIVE` -> `EXPIRED` and `EXPIRING`
    -> `EXPIRED`: when a term is `ACTIVE` or `EXPIRING` and the clock date is **strictly
    later** than its `term_end_on`, the term becomes `EXPIRED`."

    Design: Difficulty/boundary_precision_check/term_end_on_is_the_inclusive_last_eligible_day_of_the_sweep
    """
    bundle = _term_ending_mid_2029(client)
    fixtures.set_clock(client, "2029-06-30T23:59:59Z")
    warning = fixtures.sweep(client)
    assert_int_equals(warning["expired_term_ids"], [], "the warning sweep expires nothing")

    fixtures.set_clock(client, "2029-07-01T00:00:00Z")
    result = fixtures.sweep(client)

    assert_int_equals(result["swept_count"], 1, "sweep.swept_count")
    assert_int_equals(result["expired_count"], 1, "sweep.expired_count")
    assert_int_equals(result["expiring_count"], 0, "sweep.expiring_count")
    assert_int_equals(
        result["expired_term_ids"], [bundle.term["id"]], "sweep.expired_term_ids"
    )

    term = fixtures.read_term(client, bundle.term["id"])
    assert_int_equals(term["status"], TERM_EXPIRED, "term.status")
    assert_date_equals(
        term["reidentification_due_on"], "2029-08-14", "term.reidentification_due_on"
    )

    student = fixtures.read_student(client, bundle.student["id"])
    assert_int_equals(
        student["eligibility_status"],
        ELIGIBILITY_TERM_EXPIRED,
        "student.eligibility_status",
    )
    assert_is_null(student["eligibility_expires_on"], "student.eligibility_expires_on")
