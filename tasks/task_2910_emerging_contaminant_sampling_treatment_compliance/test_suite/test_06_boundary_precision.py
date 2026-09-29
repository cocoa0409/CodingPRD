"""Edges that must be inclusive on one side and exclusive on the other.

A holding time of exactly 336 hours is inside the limit; a determination built
from exactly zero quarters is not something that can be issued.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import ERR_HOLDING_TIME_EXCEEDED, ERR_NO_QUALIFYING_RESULTS
from test_helpers.assertions import (
    assert_decimal,
    assert_entry_point_posture,
    assert_equals,
    assert_instant_equals,
    assert_is_null,
    assert_status,
    assert_total_count,
)
from test_helpers.fixtures import (
    build_registry,
    draft_determination,
    read_determination,
    read_entry_point,
    read_sample,
    received_sample,
    register_contaminant,
    register_entry_point,
)
from test_helpers.test_users import COMPLIANCE_OFFICER_HEADERS

_COLLECTED_AT = "2026-04-10T08:00:00.000Z"
_EXACTLY_336_HOURS_LATER = "2026-04-24T08:00:00.000Z"
_ONE_HOUR_TOO_LATE = "2026-04-24T09:00:00.000Z"


def _received_sample_awaiting_results(api):
    registry = build_registry(api)
    sample = received_sample(
        api,
        registry["entry_point_id"],
        [registry["contaminant_id"]],
        registry["laboratory_id"],
        monitoring_period="2026Q2",
        collected_at=_COLLECTED_AT,
        preservative_lot="LOT-HT",
    )
    return registry, sample


def test_an_analysis_exactly_at_the_holding_time_limit_is_accepted(api):
    """Fourteen days to the second is inside the METHOD_533 tolerance.

    A sample collected at 2026-04-10T08:00:00.000Z and analysed at
    2026-04-24T08:00:00.000Z has an elapsed holding time of exactly 336 hours,
    which the method tolerates, so the result is created in SUBMITTED status and
    the parent sample stays RECEIVED because nothing has been accepted yet.

    PRD: "An elapsed time exactly equal to the method's limit passes; anything
    greater is refused with `ERR_HOLDING_TIME_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/holding_time_of_exactly_336_hours_is_accepted_and_337_hours_is_refused
    """
    registry, sample = _received_sample_awaiting_results(api)

    result = validate_success(
        api.create_lab_result(
            f.lab_result_payload(
                sample["id"],
                registry["contaminant_id"],
                method="METHOD_533",
                reported_ng_per_l=3.00,
                detection_limit_ng_per_l=1.00,
                analyzed_at=_EXACTLY_336_HOURS_LATER,
            ),
            registry["lab_headers"],
        ),
        201,
    )

    assert_status(result, "SUBMITTED")
    assert_instant_equals(result["analyzed_at"], _EXACTLY_336_HOURS_LATER, label="analyzed_at")
    assert_equals(result, "censored", False)
    assert_decimal(result["compliance_value_ng_per_l"], 3.00, label="compliance_value_ng_per_l")
    assert_status(read_sample(api, sample["id"]), "RECEIVED")
    assert_total_count(
        api.list_lab_results(COMPLIANCE_OFFICER_HEADERS, params={"sample_id": sample["id"]}), 1
    )


def test_one_hour_past_the_holding_time_limit_is_refused(api):
    """337 hours is outside the tolerance, so the comparison cannot be inclusive.

    Moving the analysis instant one hour later than the boundary case puts the
    elapsed holding time at 337 hours under a method that tolerates 336, and the
    submission is refused outright with no result row left behind.

    PRD: "`METHOD_533` and `METHOD_537_1` each tolerate 336 hours — fourteen days
    — while `METHOD_1633` tolerates 720 hours, or thirty days."

    Design: Difficulty/boundary_precision_check/holding_time_of_exactly_336_hours_is_accepted_and_337_hours_is_refused
    """
    registry, sample = _received_sample_awaiting_results(api)

    validate_error(
        api.create_lab_result(
            f.lab_result_payload(
                sample["id"],
                registry["contaminant_id"],
                method="METHOD_533",
                reported_ng_per_l=3.00,
                detection_limit_ng_per_l=1.00,
                analyzed_at=_ONE_HOUR_TOO_LATE,
            ),
            registry["lab_headers"],
        ),
        ERR_HOLDING_TIME_EXCEEDED,
        422,
    )

    assert_status(read_sample(api, sample["id"]), "RECEIVED")
    assert_total_count(
        api.list_lab_results(COMPLIANCE_OFFICER_HEADERS, params={"sample_id": sample["id"]}), 0
    )


def _empty_window_determination(api):
    """A DRAFT determination at an entry point that has never had a result."""
    contaminant = register_contaminant(api)
    entry_point = register_entry_point(api)
    determination = draft_determination(
        api, entry_point["id"], contaminant["id"], period_end="2026Q2"
    )
    return entry_point, determination


def test_issuing_a_determination_with_no_contributing_quarters_is_refused(api):
    """An empty input set is not a compliant average of zero.

    The draft froze zero quarters, so there is nothing to determine and issuance
    is refused; the determination stays in DRAFT with issued_at still null, no
    notification is created and the entry point's violation counter never moves.

    PRD: "Issuance requires `DRAFT` status, else
    `ERR_DETERMINATION_STATE_INVALID`, and requires `quarters_used` to be at
    least one — a determination frozen over an empty window has nothing to
    determine and is refused with `ERR_NO_QUALIFYING_RESULTS`."

    Design: Difficulty/boundary_precision_check/issuing_a_determination_built_from_zero_quarters_is_refused
    """
    entry_point, determination = _empty_window_determination(api)

    validate_error(
        api.issue_determination(determination["id"], {}, COMPLIANCE_OFFICER_HEADERS),
        ERR_NO_QUALIFYING_RESULTS,
        422,
    )

    stored = read_determination(api, determination["id"])
    assert_status(stored, "DRAFT")
    assert_is_null(stored, "issued_at")
    assert_total_count(
        api.list_notifications(
            COMPLIANCE_OFFICER_HEADERS, params={"determination_id": determination["id"]}
        ),
        0,
    )
    assert_entry_point_posture(
        read_entry_point(api, entry_point["id"]),
        open_violation_count=0,
        max_compliance_ratio=0.0,
        monitoring_status="INITIAL",
    )


def test_a_zero_quarter_draft_is_still_created_with_zero_averages(api):
    """The empty window is drawable, and it reads as a verdict of no violation.

    Drafting against an entry point with no accepted results freezes
    quarters_used at zero and all three frozen figures at 0.00, and because the
    entry point is still on INITIAL monitoring rather than QUARTERLY the verdict
    is NO_VIOLATION rather than a monitoring violation.

    PRD: "The average is 0.00 when no period is kept, and otherwise the sum of
    the values across the kept periods divided by the number of periods kept,
    rounded half-up to two decimal places."

    Design: Difficulty/boundary_precision_check/issuing_a_determination_built_from_zero_quarters_is_refused
    """
    _, determination = _empty_window_determination(api)

    assert_equals(determination, "quarters_used", 0)
    assert_decimal(determination["lraa_ng_per_l"], 0.00, label="lraa_ng_per_l")
    assert_decimal(determination["planning_lraa_ng_per_l"], 0.00, label="planning_lraa_ng_per_l")
    assert_decimal(determination["hazard_index"], 0.00, label="hazard_index")
    assert_equals(determination, "determination", "NO_VIOLATION")
    assert_equals(determination, "violation_type", "NONE")
    assert_status(determination, "DRAFT")
    assert_is_null(determination, "issued_at")
