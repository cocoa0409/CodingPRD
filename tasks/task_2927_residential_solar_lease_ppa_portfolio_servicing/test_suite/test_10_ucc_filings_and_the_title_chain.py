"""UCC fixture filings: subordination, termination and title clearance.

Whether a closing may clear title is decided entirely by the state of other
rows — the liens recorded against the same agreement — and the distinction is
three-valued: a filing that is merely requested for subordination is no better
than one still filed. Termination is its own two-step recording, stamped from
the clock and, unlike subordination, open to a single person.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import test_users as U
from test_helpers.fixtures import (
    activate,
    book_ppa,
    make_buyer,
    make_filing,
    make_homeowner,
    make_tariff,
    open_assumption,
    read_agreement,
    run_credit_review,
    set_clock,
)

A1_TERMS = {
    "contract_start_date": "2025-01-01",
    "escalator_pct": 0.029,
    "base_ppa_rate_per_kwh_millicents": 14750,
    "guaranteed_annual_kwh": 9600,
    "guarantee_band_pct": 0.05,
}


def _active_ppa(api, homeowner_id, tariff_id, **overrides):
    terms = dict(A1_TERMS)
    terms.update(overrides)
    agreement = book_ppa(api, homeowner_id, tariff_id, **terms)
    activate(api, agreement["id"])
    return read_agreement(api, agreement["id"])


def _one_active_ppa(api, clock="2026-08-01T00:00:00Z"):
    set_clock(api, clock)
    owner = make_homeowner(api)
    schedule = make_tariff(api)
    return owner, _active_ppa(api, owner["id"], schedule["id"])


def _read_case(api, transfer_case_id):
    return validate_success(
        api.get_transfer_case(transfer_case_id, U.agent_headers()), 200
    )


def _read_filing(api, ucc_filing_id):
    return validate_success(api.get_ucc_filing(ucc_filing_id, U.title_headers()), 200)


def _approved_assumption(api, agreement_id, closing_date="2026-09-01"):
    """An assumption case sitting in CREDIT_APPROVED on an 86.67 composite."""
    buyer = make_buyer(
        api, fico_score=760, dti_ratio=0.05, monthly_income_cents=3000000
    )
    case = open_assumption(api, agreement_id, closing_date, buyer["id"])
    reviewed = run_credit_review(api, case["id"])
    assert reviewed["status"] == C.TRANSFER_CREDIT_APPROVED
    assert float(reviewed["credit_composite_score"]) == 86.67
    assert reviewed["credit_decision"] == C.CREDIT_APPROVED
    assert reviewed["required_deposit_cents"] == 0
    return reviewed


def _agreement_with_a_filed_lien(api):
    """One active agreement, one lien in `FILED`, and an approved assumption."""
    _, agreement = _one_active_ppa(api)
    filing = make_filing(api, agreement["id"], "2025-01-15")
    assert filing["status"] == C.FILING_FILED
    assert filing["terminated_date"] is None
    assert filing["requested_by_transfer_case_id"] is None
    return agreement, filing, _approved_assumption(api, agreement["id"])


def test_only_a_recorded_subordination_lets_the_closing_through(api):
    """Filed is not clear, requested is not clear, and recorded finally is.

    §3.8: "On the assumption arm the case moves `CREDIT_APPROVED →
    TITLE_CLEARED`, and every `UccFiling` recorded against the agreement must be
    either `SUBORDINATED` or `TERMINATED` — a subordination is enough, because the
    lien survives the transfer under the new owner." §3.8: "Under either arm, a
    filing still `FILED` or still `SUBORDINATION_REQUESTED` blocks clearance with
    `ERR_TITLE_NOT_CLEAR`." §3.9: "A `TitleAgent` or `ServicingAgent` requests it,
    moving the filing `FILED → SUBORDINATION_REQUESTED`, but only while there is an
    actual closing to serve ... and that case's identifier is stamped into
    `requested_by_transfer_case_id`."

    Design: Difficulty/cross_entity_state_dependency/clear_title_requires_every_ucc_filing_subordinated
    """
    agreement, filing, case = _agreement_with_a_filed_lien(api)

    validate_error(
        api.clear_title(case["id"], U.title_headers(U.TITLE_2)),
        E.ERR_TITLE_NOT_CLEAR,
        422,
    )

    requested = validate_success(
        api.request_subordination(filing["id"], U.agent_headers()), 200
    )
    assert requested["status"] == C.FILING_SUBORDINATION_REQUESTED
    assert requested["requested_by_transfer_case_id"] == case["id"]

    validate_error(
        api.clear_title(case["id"], U.title_headers(U.TITLE_2)),
        E.ERR_TITLE_NOT_CLEAR,
        422,
    )

    recorded = validate_success(
        api.record_subordination(filing["id"], U.title_headers(U.TITLE_2)), 200
    )
    assert recorded["status"] == C.FILING_SUBORDINATED

    cleared = validate_success(
        api.clear_title(case["id"], U.title_headers(U.TITLE_2)), 200
    )
    assert cleared["status"] == C.TRANSFER_TITLE_CLEARED
    assert cleared["title_cleared_by_user_id"] == U.TITLE_2
    assert (
        read_agreement(api, agreement["id"])["lifecycle_state"]
        == C.LIFECYCLE_TRANSFER_PENDING
    )


def test_a_blocked_clearance_writes_nothing_on_either_side(api):
    """Both refusals leave the case, the lien and the agreement byte for byte.

    §2.4: "`version`, an integer that begins at 1 and increases by exactly one on
    every mutation of that resource." §3.8: "Clearance stamps
    `title_cleared_by_user_id` with the acting `X-User-ID`, stamps
    `requested_by_transfer_case_id` on every filing it touches for this closing,
    computes `payoff_method` and `payoff_quote_cents` on the prepayment and
    relocation arms".

    Design: Difficulty/cross_entity_state_dependency/clear_title_requires_every_ucc_filing_subordinated
    """
    agreement, filing, case = _agreement_with_a_filed_lien(api)
    case_version = case["version"]
    filing_version = filing["version"]
    agreement_version = read_agreement(api, agreement["id"])["version"]

    validate_error(
        api.clear_title(case["id"], U.title_headers(U.TITLE_2)),
        E.ERR_TITLE_NOT_CLEAR,
        422,
    )

    untouched_case = _read_case(api, case["id"])
    assert untouched_case["status"] == C.TRANSFER_CREDIT_APPROVED
    assert untouched_case["title_cleared_by_user_id"] is None
    assert untouched_case["payoff_method"] == C.PAYOFF_NONE
    assert untouched_case["payoff_quote_cents"] == 0
    assert untouched_case["version"] == case_version

    untouched_filing = _read_filing(api, filing["id"])
    assert untouched_filing["status"] == C.FILING_FILED
    assert untouched_filing["version"] == filing_version
    assert untouched_filing["requested_by_transfer_case_id"] is None

    validate_success(api.request_subordination(filing["id"], U.agent_headers()), 200)
    validate_error(
        api.clear_title(case["id"], U.title_headers(U.TITLE_2)),
        E.ERR_TITLE_NOT_CLEAR,
        422,
    )

    still_requested = _read_filing(api, filing["id"])
    assert still_requested["status"] == C.FILING_SUBORDINATION_REQUESTED
    assert still_requested["version"] == filing_version + 1
    assert _read_case(api, case["id"])["version"] == case_version
    assert read_agreement(api, agreement["id"])["version"] == agreement_version


def _stale_closing_over_an_open_lien(api):
    """An approved assumption closing 2026-08-15 with its lien still in FILED."""
    _, agreement = _one_active_ppa(api)
    filing = make_filing(api, agreement["id"], "2025-01-15")
    case = _approved_assumption(api, agreement["id"], "2026-08-15")
    assert _read_filing(api, filing["id"])["status"] == C.FILING_FILED
    return agreement, filing, case


def test_a_stale_closing_is_reported_ahead_of_the_unsubordinated_lien(api):
    """Two rungs are violated at once and only the temporal one is heard.

    §2.10: "When a single request violates several rules at once, exactly one
    error is reported: the one belonging to the lowest-numbered rung of the
    following ladder. Evaluation stops at the first violated rung." §2.10 rung 11:
    "**Business-temporal rules.** All carry HTTP 422: `ERR_ELECTION_WINDOW_CLOSED`,
    `ERR_CLOSING_DATE_IN_PAST`". §2.10 rung 12: "**Business-referential rules.** All
    carry HTTP 422: `ERR_TITLE_NOT_CLEAR`".

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_referential_on_stale_closing_with_open_filing
    """
    agreement, filing, case = _stale_closing_over_an_open_lien(api)
    set_clock(api, "2026-08-20T00:00:00Z")

    validate_error(
        api.clear_title(case["id"], U.title_headers(U.TITLE_1)),
        E.ERR_CLOSING_DATE_IN_PAST,
        422,
    )

    assert _read_case(api, case["id"])["status"] == C.TRANSFER_CREDIT_APPROVED
    assert _read_filing(api, filing["id"])["status"] == C.FILING_FILED
    assert (
        read_agreement(api, agreement["id"])["lifecycle_state"]
        == C.LIFECYCLE_TRANSFER_PENDING
    )


def test_the_same_request_reports_the_lien_while_the_closing_is_still_current(api):
    """With the clock left alone the lower rung finally becomes the answer.

    §3.8: "The `closing_date` is re-checked here against the clock and a closing
    that has slipped into the past is rejected with `ERR_CLOSING_DATE_IN_PAST`."
    §3.8: "Under either arm, a filing still `FILED` or still
    `SUBORDINATION_REQUESTED` blocks clearance with `ERR_TITLE_NOT_CLEAR`."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_referential_on_stale_closing_with_open_filing
    """
    _, filing, case = _stale_closing_over_an_open_lien(api)

    validate_error(
        api.clear_title(case["id"], U.title_headers(U.TITLE_1)),
        E.ERR_TITLE_NOT_CLEAR,
        422,
    )

    assert _read_case(api, case["id"])["status"] == C.TRANSFER_CREDIT_APPROVED
    assert _read_filing(api, filing["id"])["status"] == C.FILING_FILED


def test_a_subordination_request_needs_a_closing_to_serve(api):
    """With no transfer case anywhere, the request has no edge to take.

    §3.9: "A `TitleAgent` or `ServicingAgent` requests it, moving the filing
    `FILED → SUBORDINATION_REQUESTED`, but only while there is an actual closing to
    serve: a `TransferCase` on the same agreement must be `INITIATED`,
    `CREDIT_REVIEW` or `CREDIT_APPROVED`, and that case's identifier is stamped into
    `requested_by_transfer_case_id`." §2.10 rung 8: "HTTP 409 on every action
    endpoint whose target is not in a state from which the requested transition
    exists."

    Design: Corner/state_machines/request_subordination_without_an_open_transfer_case_is_rejected
    """
    _, agreement = _one_active_ppa(api)
    filing = make_filing(api, agreement["id"], "2025-01-15")
    assert filing["version"] == 1

    validate_error(
        api.request_subordination(filing["id"], U.title_headers(U.TITLE_1)),
        E.ERR_INVALID_STATE_TRANSITION,
        409,
    )

    unchanged = _read_filing(api, filing["id"])
    assert unchanged["status"] == C.FILING_FILED
    assert unchanged["version"] == 1
    assert unchanged["requested_by_transfer_case_id"] is None


def test_termination_is_a_two_step_recording_stamped_from_the_clock(api):
    """The request perfects nothing, and the stamp comes from the recording day.

    §3.9: "Termination is the path that removes the lien altogether. A
    `TitleAgent` or `ServicingAgent` requests it, and the request is reachable from
    two places: `FILED → TERMINATION_REQUESTED` for a lien that was never
    subordinated, and `SUBORDINATED → TERMINATION_REQUESTED` for one that was
    subordinated for an earlier closing and is now being released. Recording the
    termination is exclusive to the `TitleAgent`, moves the filing
    `TERMINATION_REQUESTED → TERMINATED`, and stamps `terminated_date` with the
    current clock date." §3.9: "`TERMINATED` is the only terminal state."

    Design: Corner/endpoints/ucc_termination_is_a_two_step_recording_stamped_from_the_clock
    """
    _, agreement = _one_active_ppa(api)
    filing = make_filing(api, agreement["id"], "2026-07-15")
    assert filing["status"] == C.FILING_FILED
    assert filing["terminated_date"] is None
    assert filing["requested_by_transfer_case_id"] is None
    first_version = filing["version"]

    validate_error(
        api.terminate_ucc_filing(filing["id"], U.title_headers(U.TITLE_1)),
        E.ERR_INVALID_STATE_TRANSITION,
        409,
    )
    still_filed = _read_filing(api, filing["id"])
    assert still_filed["status"] == C.FILING_FILED
    assert still_filed["version"] == first_version
    assert still_filed["terminated_date"] is None

    requested = validate_success(
        api.request_termination(filing["id"], U.title_headers(U.TITLE_1)), 200
    )
    assert requested["status"] == C.FILING_TERMINATION_REQUESTED
    assert requested["version"] == first_version + 1
    assert requested["terminated_date"] is None

    validate_error(
        api.terminate_ucc_filing(filing["id"], U.agent_headers()),
        E.ERR_UNAUTHORIZED,
        403,
    )

    set_clock(api, "2026-08-05T09:30:00Z")
    terminated = validate_success(
        api.terminate_ucc_filing(filing["id"], U.title_headers(U.TITLE_1)), 200
    )
    assert terminated["status"] == C.FILING_TERMINATED
    assert terminated["version"] == first_version + 2
    assert terminated["terminated_date"] == "2026-08-05"
    assert terminated["requested_by_transfer_case_id"] is None

    validate_error(
        api.terminate_ucc_filing(filing["id"], U.title_headers(U.TITLE_1)),
        E.ERR_INVALID_STATE_TRANSITION,
        409,
    )

    rows, meta = validate_paginated(
        api.list_ucc_filings(
            U.title_headers(),
            {"agreement_id": agreement["id"], "status": C.FILING_TERMINATED},
        )
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert [row["id"] for row in rows] == [filing["id"]]


def test_a_filing_number_is_unique_across_the_whole_portfolio(api):
    """A different agreement, a different county and a different type cannot reuse it.

    §3.9: "A `TitleAgent` or `PortfolioAdmin` records one against an agreement by
    supplying the `filing_number` assigned by the recording office (between 1 and 32
    characters, not blank, and unique across the whole portfolio — a repeat is
    rejected with `ERR_DUPLICATE_FILING_NUMBER`)". §3.9: "The filing lands in
    `status` `FILED` with `terminated_date` and `requested_by_transfer_case_id` both
    null."

    Design: Corner/validations/reusing_a_filing_number_on_another_agreement_is_rejected
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    owner = make_homeowner(api)
    schedule = make_tariff(api)
    first = _active_ppa(api, owner["id"], schedule["id"])
    second = _active_ppa(
        api, owner["id"], schedule["id"], site_address="924 Alder Way, Fremont, CA"
    )
    make_filing(api, first["id"], "2025-01-15", filing_number="UCC-2025-88120")

    reused = F.ucc_filing_payload(
        second["id"],
        "2025-02-14",
        filing_number="UCC-2025-88120",
        jurisdiction_code="CA-SANTACLARA",
        filing_type=C.FILING_TYPE_AMENDMENT,
    )
    validate_error(
        api.create_ucc_filing(reused, U.title_headers()),
        E.ERR_DUPLICATE_FILING_NUMBER,
        409,
    )

    _, meta = validate_paginated(
        api.list_ucc_filings(U.title_headers(), {"agreement_id": second["id"]})
    )
    assert meta["total_count"] == 0

    reused["filing_number"] = "UCC-2025-88121"
    accepted = validate_success(api.create_ucc_filing(reused, U.title_headers()), 201)
    assert accepted["status"] == C.FILING_FILED
    assert accepted["filing_number"] == "UCC-2025-88121"
    assert accepted["jurisdiction_code"] == "CA-SANTACLARA"
    assert accepted["filing_type"] == C.FILING_TYPE_AMENDMENT


def test_the_requesting_user_may_not_record_their_own_subordination(api):
    """The two-person check on the recording outranks the state check above it.

    §3.9: "Recording the executed subordination is exclusive to the `TitleAgent`
    and moves the filing `SUBORDINATION_REQUESTED → SUBORDINATED`, and the acting
    `X-User-ID` must differ from the user who requested it — the same person may not
    both ask for and record a subordination, and an attempt to do so is refused with
    `ERR_SEGREGATION_OF_DUTIES`." §2.1: "All five rejections carry
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and this check runs ahead of every state
    check".

    Design: Corner/rbac/the_requesting_user_cannot_record_their_own_subordination
    """
    _, agreement = _one_active_ppa(api)
    filing = make_filing(api, agreement["id"], "2025-01-15")
    buyer = make_buyer(api)
    case = open_assumption(api, agreement["id"], "2026-09-01", buyer["id"])
    assert case["status"] == C.TRANSFER_CREDIT_REVIEW

    requested = validate_success(
        api.request_subordination(filing["id"], U.title_headers(U.TITLE_1)), 200
    )
    assert requested["status"] == C.FILING_SUBORDINATION_REQUESTED
    assert requested["requested_by_transfer_case_id"] == case["id"]
    requested_version = requested["version"]

    validate_error(
        api.record_subordination(filing["id"], U.title_headers(U.TITLE_1)),
        E.ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    blocked = _read_filing(api, filing["id"])
    assert blocked["status"] == C.FILING_SUBORDINATION_REQUESTED
    assert blocked["version"] == requested_version

    recorded = validate_success(
        api.record_subordination(filing["id"], U.title_headers(U.TITLE_2)), 200
    )
    assert recorded["status"] == C.FILING_SUBORDINATED
    assert recorded["version"] == requested_version + 1

    validate_error(
        api.record_subordination(filing["id"], U.title_headers(U.TITLE_1)),
        E.ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    validate_error(
        api.record_subordination(filing["id"], U.title_headers(U.TITLE_2)),
        E.ERR_INVALID_STATE_TRANSITION,
        409,
    )
    assert _read_filing(api, filing["id"])["version"] == requested_version + 1
