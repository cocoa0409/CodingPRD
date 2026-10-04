"""Registration review cases and data call-ins: window overlap semantics,
state gates on completion and issuance, terminal DCI lockdown, and cross-DCI
study parentage (PRD §3.7).
"""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_iso_instant_equal,
    complete_case,
    create_dci_study,
    create_manual_review_case,
    create_registered_product,
    get_dci,
    get_review_case,
    issue_dci,
    list_product_review_cases,
    make_data_call_in_payload,
    make_dci_response_payload,
    make_review_case_payload,
    respond_dci,
    set_clock,
    setup_case_with_dci,
    setup_satisfied_dci,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
REGISTRANT = TEST_USERS["registrant_alice_headers"]
REVIEWER = TEST_USERS["reviewer_1_headers"]


def test_review_case_half_open_interval_adjacency(api):
    """PRD §3.7: "The half-open window from `opened_at` (inclusive) to `due_at`
    (exclusive) must not intersect the window of any other non-terminal case of
    the same product — touching endpoints are permitted — or the creation fails
    `ERR_REVIEW_CASE_WINDOW_OVERLAP` (HTTP 409)."
    PRD §3.7: "its `cycle_number` is one plus the count of pre-existing cases for
    the product, so creation order (`created_at` ascending) fully determines cycle
    order and identifiers never participate."

    Design: Difficulty/resource_temporal_overlap/review_case_half_open_interval_adjacency
    """
    ctx = create_registered_product()
    product_id = ctx["product"]["id"]
    case_a = create_manual_review_case(product_id, "2027-01-01T00:00:00Z",
                                       "2027-07-01T00:00:00Z", REVIEWER)
    assert case_a["status"] == "SCHEDULED"
    assert case_a["cycle_number"] == 2  # cycle 1 was auto-created at approval

    # [2027-06-01, 2027-11-28) intersects [2027-01-01, 2027-07-01).
    resp = api_client.create_review_case(
        make_review_case_payload(product_id, "2027-06-01T00:00:00Z",
                                 "2027-11-28T00:00:00Z"),
        REVIEWER)
    validate_error(resp, ApiErrorId.ERR_REVIEW_CASE_WINDOW_OVERLAP)

    # opened exactly at the other's due_at is adjacency, not intersection.
    case_b = create_manual_review_case(product_id, "2027-07-01T00:00:00Z",
                                       "2027-12-28T00:00:00Z", REVIEWER)
    assert case_b["status"] == "SCHEDULED"
    assert case_b["cycle_number"] == 3


def test_review_case_complete_from_scheduled_returns_not_completable(api):
    """PRD §3.7: "A reviewer completes a case that is `OPEN` or `UNDER_REVIEW`,
    optionally recording a `completion_summary`; a case in any other status fails
    `ERR_CASE_NOT_COMPLETABLE`"
    PRD §3.4: "the first registration review case is auto-created: `cycle_number`
    1, born `SCHEDULED`, with `opened_at` exactly 5,475 days — fifteen years —
    after the approval instant and `due_at` 180 days after it opens"

    Design: Corner/state_machines/review_case_complete_from_scheduled_returns_not_completable
    """
    ctx = create_registered_product()
    case = ctx["review_case"]
    assert case["status"] == "SCHEDULED"

    resp = api_client.complete_review_case(case["id"], REVIEWER, payload={})
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_COMPLETABLE)

    case = get_review_case(case["id"])
    assert case["status"] == "SCHEDULED"
    assert_iso_instant_equal(case["opened_at"], "2041-08-28T00:00:00Z", "opened_at")
    assert_iso_instant_equal(case["due_at"], "2042-02-24T00:00:00Z", "due_at")


def test_dci_create_on_scheduled_case_returns_case_not_open(api):
    """PRD §3.7: "Issuance stamps `issued_at`, births the call-in in `ISSUED`,
    and moves the case to `DCI_PENDING`; issuing against a case in any other
    status fails `ERR_CASE_NOT_OPEN`."

    Design: Corner/errors/dci_create_on_scheduled_case_returns_case_not_open
    """
    ctx = create_registered_product()
    case = ctx["review_case"]  # SCHEDULED, opens 2041-08-28
    resp = api_client.create_data_call_in(
        make_data_call_in_payload(case["id"], ["TOXICOLOGY"],
                                  "2028-01-01T00:00:00Z"),
        REVIEWER)
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_OPEN)
    assert get_review_case(case["id"])["status"] == "SCHEDULED"


def test_case_complete_with_issued_dci_returns_dci_outstanding(api):
    """PRD §3.7: "any call-in of the case still in `ISSUED`, `RESPONDED`,
    `DEFICIENT`, or `DELINQUENT` blocks completion with `ERR_DCI_OUTSTANDING`."
    PRD §3.7: "Because a `DCI_PENDING` case always has at least one unsatisfied
    call-in, that call-in check is the one that fires there — successful
    completion is reachable only from `OPEN` (no call-ins yet) or `UNDER_REVIEW`."

    Design: Corner/errors/case_complete_with_issued_dci_returns_dci_outstanding
    """
    ctx = create_registered_product()
    bundle = setup_case_with_dci(ctx["product"]["id"], ["TOXICOLOGY"],
                                 response_deadline="2028-01-01T00:00:00Z")
    case_id = bundle["case"]["id"]
    assert bundle["case"]["status"] == "DCI_PENDING"

    resp = api_client.complete_review_case(case_id, REVIEWER, payload={})
    validate_error(resp, ApiErrorId.ERR_DCI_OUTSTANDING)
    assert get_review_case(case_id)["status"] == "DCI_PENDING"


def test_dci_respond_after_satisfied_returns_not_respondable(api):
    """PRD §3.7: "Responding is permitted from `ISSUED`, from `RESPONDED`
    (additional studies), from `DEFICIENT` (a cure response), and even from
    `DELINQUENT` — a late cure, which is accepted on its merits but does not undo
    the suspension the delinquency already fired, and the case stays `REFERRED`;
    only a `SATISFIED` call-in refuses further response, with
    `ERR_DCI_NOT_RESPONDABLE`."

    Design: Corner/state_machines/dci_respond_after_satisfied_returns_not_respondable
    """
    ctx = create_registered_product()
    bundle = setup_satisfied_dci(ctx["product"]["id"], ["TOXICOLOGY"])
    dci = bundle["dci"]
    assert dci["status"] == "SATISFIED"
    assert bundle["case"]["status"] == "UNDER_REVIEW"

    late_study = create_dci_study(dci["id"], "TOXICOLOGY", REGISTRANT)
    resp = api_client.respond_data_call_in(
        dci["id"], make_dci_response_payload([late_study["id"]]), REGISTRANT)
    validate_error(resp, ApiErrorId.ERR_DCI_NOT_RESPONDABLE)
    assert get_dci(dci["id"])["status"] == "SATISFIED"


def test_dci_respond_with_study_of_another_dci_returns_parent_mismatch(api):
    """PRD §3.7: "The registrant answers by responding with a
    `study_submission_ids` array. Every id must exist, must already bear this
    call-in's `data_call_in_id`, and must belong to the responding registrant's
    own product — any mismatch fails `ERR_STUDY_PARENT_MISMATCH`."

    Design: Corner/errors/dci_respond_with_study_of_another_dci_returns_parent_mismatch
    """
    ctx = create_registered_product()
    product_id = ctx["product"]["id"]
    case_a = create_manual_review_case(product_id, "2027-01-05T00:00:00Z",
                                       "2027-07-04T00:00:00Z", REVIEWER)
    case_b = create_manual_review_case(product_id, "2027-08-01T00:00:00Z",
                                       "2028-01-28T00:00:00Z", REVIEWER)

    set_clock("2027-01-05T00:00:00Z")  # opens case A
    dci_a = issue_dci(case_a["id"], ["TOXICOLOGY"], "2028-01-01T00:00:00Z", REVIEWER)
    study = create_dci_study(dci_a["id"], "TOXICOLOGY", REGISTRANT)

    set_clock("2027-08-01T00:00:00Z")  # opens case B; dci_a deadline still ahead
    dci_b = issue_dci(case_b["id"], ["EFFICACY"], "2028-06-01T00:00:00Z", REVIEWER)

    resp = api_client.respond_data_call_in(
        dci_b["id"], make_dci_response_payload([study["id"]]), REGISTRANT)
    validate_error(resp, ApiErrorId.ERR_STUDY_PARENT_MISMATCH)
    assert get_dci(dci_b["id"])["status"] == "ISSUED"
