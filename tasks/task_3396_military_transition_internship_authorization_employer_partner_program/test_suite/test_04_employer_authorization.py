"""Employer authorization: the pending gate, the suspend/remediate cycle, and
the strictly-greater lapse boundary."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import ApiErrorId, assert_instant, factories, fixtures, make_employer_rep_headers
from test_helpers.test_users import PROGRAM_OFFICE_HEADERS


def test_authorize_requires_pending_employer(api):
    """PRD §3.3: "the ProgramOffice authorizes an employer currently in
    `PENDING_AUTHORIZATION` — any other status yields
    `ERR_EMPLOYER_NOT_PENDING_AUTHORIZATION` — which moves the employer to
    `AUTHORIZED`, stamps `authorized_at` from the logical clock, and sets
    `next_review_due_date` to the logical clock date plus the 180-day review
    interval (`REVIEW_INTERVAL_DAYS`)."
    PRD §3.3: "Calling review on a `PENDING_AUTHORIZATION` or `REVOKED` employer is
    rejected with `ERR_EMPLOYER_NOT_AUTHORIZED`."
    PRD §3.4: "The owning employer must be `AUTHORIZED` at posting time, otherwise
    `ERR_EMPLOYER_NOT_AUTHORIZED`."

    Design: Corner/validations/authorize_requires_pending_employer
    """
    employer = fixtures.create_employer(api)
    assert employer["authorization_status"] == "PENDING_AUTHORIZATION"

    premature_review = api.periodic_review(
        employer["id"], factories.periodic_review_payload("PASS", "premature"), PROGRAM_OFFICE_HEADERS
    )
    validate_error(premature_review, ApiErrorId.ERR_EMPLOYER_NOT_AUTHORIZED)

    premature_opening = api.create_opening(
        factories.create_opening_payload(employer["id"], title="Premature Opening"),
        make_employer_rep_headers(employer["id"]),
    )
    validate_error(premature_opening, ApiErrorId.ERR_EMPLOYER_NOT_AUTHORIZED)

    authorized = fixtures.authorize_employer(api, employer["id"])
    assert authorized["authorization_status"] == "AUTHORIZED"
    # Authorized at the default clock 2026-09-01 plus the 180-day review interval.
    assert_instant(authorized["next_review_due_date"], "2027-02-28", "next_review_due_date")

    second = api.authorize_employer(employer["id"], PROGRAM_OFFICE_HEADERS)
    validate_error(second, ApiErrorId.ERR_EMPLOYER_NOT_PENDING_AUTHORIZATION)

    opening = get_success_data(
        api.create_opening(
            factories.create_opening_payload(employer["id"]),
            make_employer_rep_headers(employer["id"]),
        ),
        201,
    )
    assert opening["status"] == "OPEN"
    assert opening["filled_count"] == 0


def test_employer_suspend_remediate_cycle(api):
    """PRD §3.3: "FAIL is accepted while the employer is `AUTHORIZED` or
    `AUTHORIZATION_LAPSED` and moves it to `SUSPENDED`."
    PRD §3.3: "PASS is accepted while the employer is `AUTHORIZED`, `SUSPENDED`, or
    `AUTHORIZATION_LAPSED`; it (re-)moves the employer to `AUTHORIZED`, restamps
    `authorized_at`, and refreshes `next_review_due_date` to the clock date plus
    180 days."

    Design: Difficulty/non_linear_state_machine/employer_suspend_remediate_cycle
    """
    employer = fixtures.create_employer(api)
    authorized = fixtures.authorize_employer(api, employer["id"])
    assert authorized["authorization_status"] == "AUTHORIZED"
    assert_instant(authorized["next_review_due_date"], "2027-02-28", "initial review horizon")

    suspended = fixtures.review_employer(api, employer["id"], "FAIL", "missing documentation")
    assert suspended["authorization_status"] == "SUSPENDED"

    remediated = fixtures.review_employer(api, employer["id"], "PASS", "remediated")
    assert remediated["authorization_status"] == "AUTHORIZED", "remediation edge of the cycle"
    # Clock never moved, so the refreshed horizon is again 2026-09-01 + 180 days.
    assert_instant(remediated["next_review_due_date"], "2027-02-28", "refreshed review horizon")


def test_employer_lapse_boundary_strictly_greater(api):
    """PRD §3.3: "The boundary is exact: a clock date exactly equal to
    `next_review_due_date` keeps the employer `AUTHORIZED`, because the comparison
    is strictly-greater."
    PRD §3.3: "When a clock-set sweep finds an `AUTHORIZED` employer whose
    `next_review_due_date` is not null and whose date is strictly earlier than the
    logical clock date, the employer moves to `AUTHORIZATION_LAPSED`."

    Design: Difficulty/non_linear_state_machine/employer_suspend_remediate_cycle
    """
    employer = fixtures.create_authorized_employer(api)

    at_due = fixtures.set_clock(api, "2027-02-28T00:00:00Z")
    assert at_due["employers_lapsed"] == 0
    assert fixtures.get_employer(api, employer["id"])["authorization_status"] == "AUTHORIZED"

    past_due = fixtures.set_clock(api, "2027-03-01T00:00:00Z")
    assert past_due["employers_lapsed"] == 1
    assert fixtures.get_employer(api, employer["id"])["authorization_status"] == "AUTHORIZATION_LAPSED"

    late_pass = fixtures.review_employer(api, employer["id"], "PASS", "late review accepted")
    assert late_pass["authorization_status"] == "AUTHORIZED"
    # 2027-03-01 plus the 180-day review interval.
    assert_instant(late_pass["next_review_due_date"], "2027-08-28", "late review horizon")
