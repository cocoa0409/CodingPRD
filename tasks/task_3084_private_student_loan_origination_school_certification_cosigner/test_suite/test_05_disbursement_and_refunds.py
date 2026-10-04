"""Disbursement scheduling, release, cancellation and school refunds."""
from test_helpers import (
    ERR_AMOUNT_OUT_OF_RANGE,
    ERR_DISBURSEMENT_BLOCKED,
    ERR_DISBURSEMENT_OVER_CERTIFIED,
    ERR_DISBURSEMENT_WINDOW_OVERLAP,
    TEST_USERS,
    file_and_certify,
    get_success_data,
    release_disbursement,
    schedule_disbursement,
    schedule_and_release,
    setup_certified_loan,
    validate_error,
    validate_success,
)
from test_helpers import api_client as client


def _loan(orig):
    return validate_success(client.get_loan(orig.loan["id"], TEST_USERS["servicer_headers"]))


def test_school_refund_nets_the_disbursed_total_and_restores_headroom(api):
    """PRD §3.4: "A successful refund sets the disbursement's `refund_status` to
    `REFUNDED`, stores the `remainder_credited_cents`, recomputes the loan's
    `disbursed_amount_cents` net of the refund, re-derives the loan's
    `principal_cents`, `current_balance_cents` and `certified_amount_cents`"

    Design: Difficulty/transitive_cascade/school_refund_cascade_unblocks_the_next_disbursement
    """
    orig = setup_certified_loan(disburse=True)
    first = orig.disbursement
    assert _loan(orig)["disbursed_amount_cents"] == 805000

    refunded = get_success_data(
        client.school_refund(first["id"], {"remainder_credited_cents": 50000},
                             orig.school_headers)
    )
    assert refunded["refund_status"] == "REFUNDED"
    assert refunded["remainder_credited_cents"] == 50000

    loan = _loan(orig)
    assert loan["disbursed_amount_cents"] == 755000, "805000 net of the 50000 credit"
    assert loan["principal_cents"] == 755000
    summary = validate_success(
        client.loan_summary(orig.loan["id"], TEST_USERS["servicer_headers"])
    )
    assert summary["certified_headroom_cents"] == 50000


def test_a_refund_credit_above_the_disbursement_amount_is_refused(api):
    """PRD §3.4: "the refund requires the disbursement to be `RELEASED`, requires
    that no refund has already been credited (`remainder_credited_cents` equal to
    zero), and requires that the credited amount does not exceed the disbursement's
    own `amount_cents` — a credit above that amount is refused with
    `ERR_AMOUNT_OUT_OF_RANGE`."

    Design: Difficulty/transitive_cascade/school_refund_cascade_unblocks_the_next_disbursement
    """
    orig = setup_certified_loan(disburse=True)
    response = client.school_refund(
        orig.disbursement["id"], {"remainder_credited_cents": 805001}, orig.school_headers
    )
    validate_error(response, ERR_AMOUNT_OUT_OF_RANGE)
    assert _loan(orig)["disbursed_amount_cents"] == 805000


def test_a_refund_exactly_equal_to_the_disbursement_is_accepted(api):
    """PRD §3.4: "requires that the credited amount does not exceed the
    disbursement's own `amount_cents`"
    PRD §2.7: "Round-half-up means that a value whose discarded portion is exactly
    one half is rounded away from zero"

    Design: Difficulty/transitive_cascade/school_refund_cascade_unblocks_the_next_disbursement
    """
    orig = setup_certified_loan(disburse=True)
    refunded = get_success_data(
        client.school_refund(orig.disbursement["id"], {"remainder_credited_cents": 805000},
                             orig.school_headers)
    )
    assert refunded["refund_status"] == "REFUNDED"
    loan = _loan(orig)
    assert loan["disbursed_amount_cents"] == 0, "the whole release was returned"


def test_release_beyond_the_certified_headroom_is_refused(api):
    """PRD §3.4: "Headroom is the loan's certified total minus its disbursed total,
    floored at zero, and a release whose amount would exceed that headroom is
    refused with `ERR_DISBURSEMENT_OVER_CERTIFIED`."

    Design: Corner/errors/releasing_beyond_the_certified_headroom_is_rejected
    """
    orig = setup_certified_loan(
        certified_amount_cents=805000,
        disbursement_amount_cents=700000,
        disburse=False,
    )
    # The release needs a live certification on its own period label, and filing
    # is only admitted while the application still holds a certifiable state, so
    # a zero-amount SPRING row is recorded before the FALL release moves the
    # application on. It leaves the 805000 ceiling exactly as it stands.
    file_and_certify(
        orig, academic_period_label="2027-SPRING", certified_amount_cents=0,
        period_end_date="2027-05-15T00:00:00Z",
    )
    first = schedule_disbursement(orig.loan["id"], amount_cents=700000)
    release_disbursement(first["id"])
    assert _loan(orig)["disbursed_amount_cents"] == 700000
    assert _loan(orig)["certified_amount_cents"] == 805000, "headroom is 105000"

    second = schedule_disbursement(
        orig.loan["id"], amount_cents=200000, academic_period_label="2027-SPRING",
        period_start_date="2027-01-06T00:00:00Z", period_end_date="2027-05-15T00:00:00Z",
        scheduled_date="2027-02-15T00:00:00Z",
    )
    response = client.release_disbursement(second["id"], TEST_USERS["servicer_headers"])
    validate_error(response, ERR_DISBURSEMENT_OVER_CERTIFIED)
    assert validate_success(
        client.get_disbursement(second["id"], TEST_USERS["servicer_headers"])
    )["disbursement_status"] == "SCHEDULED"


def test_cancelling_a_scheduled_disbursement_leaves_released_siblings_intact(api):
    """PRD §3.4: "A scheduled disbursement may be cancelled, in which case its
    `disbursement_status` moves to `CANCELLED` and the loan's blocked flag is
    recomputed."

    Design: Corner/endpoints/cancelling_a_scheduled_disbursement_leaves_released_siblings_untouched
    """
    orig = setup_certified_loan(disburse=True)
    second = schedule_disbursement(
        orig.loan["id"], amount_cents=100000, academic_period_label="2027-SPRING",
        period_start_date="2027-01-05T00:00:00Z", period_end_date="2027-05-15T00:00:00Z",
        scheduled_date="2027-02-15T00:00:00Z",
    )
    cancelled = validate_success(
        client.cancel_disbursement(second["id"], TEST_USERS["servicer_headers"])
    )
    assert cancelled["disbursement_status"] == "CANCELLED"
    assert validate_success(
        client.get_disbursement(orig.disbursement["id"], TEST_USERS["servicer_headers"])
    )["disbursement_status"] == "RELEASED"
    loan = _loan(orig)
    assert loan["disbursed_amount_cents"] == 805000, "the cancelled sibling never counted"
    rows = validate_success(
        client.list_disbursements(orig.loan["id"], TEST_USERS["servicer_headers"])
    )
    statuses = sorted(row["disbursement_status"] for row in rows)
    assert statuses == ["CANCELLED", "RELEASED"]


def test_releasing_a_disbursement_twice_is_refused(api):
    """PRD §3.4: "and that field progresses to `CANCELLED`, `RELEASED` or `FAILED`;
    `RELEASED` and `CANCELLED` are terminal."

    Design: Corner/state_machines/releasing_a_disbursement_twice_is_rejected
    """
    from test_helpers import ERR_INVALID_STATE

    orig = setup_certified_loan(disburse=True)
    response = client.release_disbursement(
        orig.disbursement["id"], TEST_USERS["servicer_headers"]
    )
    validate_error(response, ERR_INVALID_STATE)
    loan = _loan(orig)
    assert loan["disbursed_amount_cents"] == 805000, "no double credit"
    assert loan["principal_cents"] == 805000


def test_academic_period_windows_may_not_overlap_or_touch(api):
    """PRD §3.4: "A disbursement may also not be scheduled when its academic period
    window, from `period_start_date` to `period_end_date` inclusive, overlaps an
    existing non-cancelled disbursement on the same loan; this is
    `ERR_DISBURSEMENT_WINDOW_OVERLAP`, and an adjacency with zero gap — one period
    beginning exactly where another ends — counts as an overlap and is rejected."

    Design: Difficulty/resource_temporal_overlap/academic_period_windows_overlap_within_a_single_loan
    """
    orig = setup_certified_loan(disburse=True)
    spring = schedule_disbursement(
        orig.loan["id"], amount_cents=200000, academic_period_label="2027-SPRING",
        period_start_date="2027-01-05T00:00:00Z", period_end_date="2027-05-15T00:00:00Z",
        scheduled_date="2027-02-15T00:00:00Z",
    )
    assert spring["disbursement_status"] == "SCHEDULED"

    version = _loan(orig)["version"]
    adjacent = client.schedule_disbursement(
        orig.loan["id"],
        {
            "academic_period_label": "2027-SUMMER",
            "period_start_date": "2027-05-15T00:00:00Z",
            "period_end_date": "2027-08-20T00:00:00Z",
            "scheduled_date": "2027-06-01T00:00:00Z",
            "amount_cents": 100000,
            "expected_loan_version": version,
        },
        TEST_USERS["servicer_headers"],
    )
    validate_error(adjacent, ERR_DISBURSEMENT_WINDOW_OVERLAP)

    accepted = client.schedule_disbursement(
        orig.loan["id"],
        {
            "academic_period_label": "2027-FALL",
            "period_start_date": "2027-05-16T00:00:00Z",
            "period_end_date": "2027-08-20T00:00:00Z",
            "scheduled_date": "2027-06-01T00:00:00Z",
            "amount_cents": 100000,
            "expected_loan_version": version,
        },
        TEST_USERS["servicer_headers"],
    )
    scheduled = validate_success(accepted, expected_status=201)
    assert scheduled["disbursement_status"] == "SCHEDULED", "one day later is accepted"

def test_a_window_nested_inside_an_existing_one_is_also_an_overlap(api):
    """PRD §3.4: "A disbursement may also not be scheduled when its academic period
    window, from `period_start_date` to `period_end_date` inclusive, overlaps an
    existing non-cancelled disbursement on the same loan"

    Design: Difficulty/resource_temporal_overlap/academic_period_windows_overlap_within_a_single_loan
    """
    orig = setup_certified_loan(disburse=True)
    version = _loan(orig)["version"]
    response = client.schedule_disbursement(
        orig.loan["id"],
        {
            "academic_period_label": "2026-WINTER",
            "period_start_date": "2026-10-01T00:00:00Z",
            "period_end_date": "2026-11-01T00:00:00Z",
            "scheduled_date": "2026-10-05T00:00:00Z",
            "amount_cents": 100000,
            "expected_loan_version": version,
        },
        TEST_USERS["servicer_headers"],
    )
    validate_error(response, ERR_DISBURSEMENT_WINDOW_OVERLAP)
    rows = validate_success(
        client.list_disbursements(orig.loan["id"], TEST_USERS["servicer_headers"])
    )
    assert len(rows) == 1, "the nested window left the ledger untouched"
