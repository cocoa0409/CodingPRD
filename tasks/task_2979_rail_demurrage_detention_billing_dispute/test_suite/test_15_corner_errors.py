"""Queue B - corner section ``errors``.

Nine instances, eight of which the §1.8 difficulty queue already triggers with
their higher-priority companions; the one remaining code is the dispute's own
409, reached by reviewing a dispute that was never submitted.

Two rendering conventions apply to the PRD quotations in the docstrings below:
the PRD's em dashes are written as ASCII hyphens and its transition arrows as
``->``.  Nothing else is altered, so every quoted sentence is greppable in
``workspace/PRD.md`` once those two substitutions are made.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_DISPUTE_INVALID_STATE
from test_helpers.assertions import (
    assert_error_meta_is_minimal,
    assert_subset_equal,
)
from test_helpers.constants import (
    CHARGE_DISPUTED,
    CHARGE_FINAL,
    CLOCK_AT_SUBMIT,
    CYCLE_A_GROSS_CENTS,
    DECISION_PENDING,
    DISPUTE_DRAFT,
    DISPUTE_SUBMITTED,
    DISPUTE_UNDER_REVIEW,
    EVIDENCE_SWITCH_LIST,
    EVIDENCE_WEIGHT_POINTS,
    INVOICE_ISSUED,
    INVOICE_PARTIALLY_DISPUTED,
    SCOPE_WHOLE_INVOICE,
)
from test_helpers.test_users import make_adjudicator_headers, make_customer_headers

ADJUDICATOR_EARLY_REVIEW = "adj-c9x1-a"


# ===========================================================================
# instance: begin_review_on_a_draft_dispute_returns_dispute_invalid_state
# ===========================================================================
def test_reviewing_a_dispute_that_was_never_submitted_is_a_409(api):
    """The role is right and the dispute exists; only its state is wrong.

    PRD 2.8: "On every action endpoint, the addressed resource must currently be
    in a state from which the requested transition exists, or the addressed
    entity's own invalid-state code at HTTP 409 - `ERR_INVALID_MOVEMENT_STATE` for
    a movement action on a placement cycle, and `ERR_INVOICE_NOT_DISPUTABLE`,
    `ERR_INVOICE_INVALID_STATE`, `ERR_DISPUTE_INVALID_STATE`,
    `ERR_CHARGE_INVALID_STATE`, `ERR_CLAIM_INVALID_STATE`,
    `ERR_AGREEMENT_INVALID_STATE`, `ERR_COMPLAINT_INVALID_STATE` or
    `ERR_TARIFF_INVALID_STATE` for the others."

    Design: Corner/errors/begin_review_on_a_draft_dispute_returns_dispute_invalid_state
    """
    world = fx.reference_world(api)
    cycle = fx.released_cycle_a(api, world)
    invoice = fx.issued_invoice(api, world)
    assert_subset_equal(
        invoice,
        {"status": INVOICE_ISSUED, "total_gross_cents": CYCLE_A_GROSS_CENTS},
    )

    dispute = fx.evidenced_dispute(
        api,
        invoice,
        world["customer_id"],
        CYCLE_A_GROSS_CENTS,
        scope=SCOPE_WHOLE_INVOICE,
    )
    assert_subset_equal(
        dispute,
        {
            "status": DISPUTE_DRAFT,
            "decision": DECISION_PENDING,
            "round_number": 1,
            "first_level_adjudicator_id": None,
            "appeal_adjudicator_id": None,
            "submitted_at": None,
            "adjudication_due_at": None,
            "evidence_weight": EVIDENCE_WEIGHT_POINTS[EVIDENCE_SWITCH_LIST],
        },
    )

    headers = make_adjudicator_headers(ADJUDICATOR_EARLY_REVIEW)
    refused = api.begin_review(dispute["id"], headers)
    validate_error(refused, ERR_DISPUTE_INVALID_STATE)
    # A DemurrageAdjudicator is exactly the role this endpoint wants, so the
    # role band above cannot be what answered: the state band did.
    assert refused.status_code == 409
    assert_error_meta_is_minimal(refused)

    frozen = fx.get_dispute(api, dispute["id"])
    assert frozen == dispute
    assert_subset_equal(
        frozen,
        {
            "status": DISPUTE_DRAFT,
            "first_level_adjudicator_id": None,
            "version": dispute["version"],
        },
    )
    # Nothing financial had happened yet and nothing happened now.
    assert fx.charge_of_cycle(api, cycle["id"])["status"] == CHARGE_FINAL
    assert fx.get_invoice(api, invoice["id"])["status"] == INVOICE_ISSUED

    # PRD 3.8: "it takes a `SUBMITTED` dispute to `UNDER_REVIEW` and equally
    # takes an `APPEALED` one to `UNDER_REVIEW`."
    fx.set_clock(api, CLOCK_AT_SUBMIT)
    submitted = get_success_data(
        api.submit_dispute(dispute["id"], make_customer_headers(world["customer_id"]))
    )
    assert submitted["status"] == DISPUTE_SUBMITTED

    reviewed = get_success_data(api.begin_review(dispute["id"], headers))
    assert_subset_equal(
        reviewed,
        {
            "status": DISPUTE_UNDER_REVIEW,
            "first_level_adjudicator_id": ADJUDICATOR_EARLY_REVIEW,
            "appeal_adjudicator_id": None,
            "round_number": 1,
            "version": submitted["version"] + 1,
        },
    )
    assert fx.charge_of_cycle(api, cycle["id"])["status"] == CHARGE_DISPUTED
    assert fx.get_invoice(api, invoice["id"])["status"] == INVOICE_PARTIALLY_DISPUTED
