"""Lender suspension cascade (cascade B), reinstatement reversal, and the
endorsed-volume reconciliation invariant."""
import pytest

from test_helpers import (
    ApiErrorId,
    attach_appraisal,
    create_case,
    create_escrow,
    endorse_case,
    get_case,
    get_lender,
    lender_action,
    list_escrows,
    set_clock,
    setup_approved_lender,
    setup_endorsed_case,
    submit_case,
    validate_error,
    validate_success,
)
from test_helpers import api_client
from test_helpers.test_users import (
    make_approver_headers,
    make_reviewer_headers,
)


def _suspend(lender_id):
    return api_client.lender_status_change(
        lender_id, {"action": "SUSPEND"}, make_approver_headers("app-1")
    )


def _reinstate(lender_id):
    return api_client.lender_status_change(
        lender_id, {"action": "REINSTATE"}, make_approver_headers("app-1")
    )


def test_endorsement_on_blocked_case_returns_case_blocked(api):
    """PRD §3.2: "A case that has been driven into `BLOCKED` by a lender suspension
    cannot be endorsed at all — the review is rejected with `ERR_CASE_BLOCKED`."

    Design: Corner/validations/endorsement_on_blocked_case_returns_case_blocked
    """
    lender = setup_approved_lender(lender_overrides={"legal_name": "Blocked Co"})
    case = create_case(lender["id"], borrower_reference="BLK-1")
    attach_appraisal(case["id"], lender["id"])
    submit_case(case["id"], lender["id"])
    _suspend(lender["id"])
    assert get_case(case["id"])["status"] == "BLOCKED"
    response = api_client.endorsement_review(
        case["id"], {"decision": "ENDORSE"}, make_reviewer_headers("rev-1")
    )
    validate_error(response, ApiErrorId.ERR_CASE_BLOCKED)
    assert get_case(case["id"])["status"] == "BLOCKED"


def test_suspension_cascade_blocks_cases_and_freezes_escrows(api):
    """PRD §3.6: "An `FhaApprover` moves a lender from `APPROVED` to `SUSPENDED`, and
    the suspension cascades in two hops: every loan case of the lender sitting in
    `UNDERWRITE_SUBMITTED` moves to `BLOCKED`, and — caused by the first hop — every
    `OPEN` repair escrow of each newly blocked case is frozen with `freeze_origin` set
    to `SUSPENSION`."

    Design: Corner/cross_cutting_layers/suspension_cascade_blocks_cases_and_freezes_escrows
    """
    lender = setup_approved_lender(lender_overrides={"legal_name": "Cascade B Co"})
    case = create_case(lender["id"], borrower_reference="CB-1")
    escrow = create_escrow(case["id"], lender["id"])
    submit_case(case["id"], lender["id"])
    validate_success(_suspend(lender["id"]))
    assert get_lender(lender["id"])["status"] == "SUSPENDED"
    assert get_case(case["id"])["status"] == "BLOCKED"
    escrow_after = {e["id"]: e for e in list_escrows(case["id"])}[escrow["id"]]
    assert escrow_after["status"] == "FROZEN"
    assert escrow_after["freeze_origin"] == "SUSPENSION"


def test_reinstate_reverses_suspension_cascade(api):
    """PRD §3.6: "Reinstating reverses the same cascade: the lender moves from
    `SUSPENDED` back to `APPROVED`, every `BLOCKED` case of the lender returns to
    `UNDERWRITE_SUBMITTED`, and every escrow frozen with `freeze_origin` `SUSPENSION`
    on those cases returns to `OPEN` with its `freeze_origin` cleared."

    Design: Corner/cross_cutting_layers/reinstate_reverses_suspension_cascade
    """
    lender = setup_approved_lender(
        lender_overrides={"legal_name": "Cascade Reverse Co"}
    )
    case = create_case(lender["id"], borrower_reference="CR-1")
    escrow = create_escrow(case["id"], lender["id"])
    submit_case(case["id"], lender["id"])
    _suspend(lender["id"])
    validate_success(_reinstate(lender["id"]))
    assert get_lender(lender["id"])["status"] == "APPROVED"
    assert get_case(case["id"])["status"] == "UNDERWRITE_SUBMITTED"
    escrow_after = {e["id"]: e for e in list_escrows(case["id"])}[escrow["id"]]
    assert escrow_after["status"] == "OPEN"
    assert escrow_after["freeze_origin"] is None


def test_derived_field_reconciliation_after_void(api):
    """PRD §3.2: "A lender's `endorsed_volume_cents` is defined as the sum of
    `base_loan_amount_cents` over its cases in `ENDORSED`, `IN_DEFAULT`, or
    `CLAIM_FILED` status."
    PRD §3.2: "The compensating invariant is exact: endorsing and then voiding returns
    the lender's endorsed volume and the case's retained premiums to their
    pre-endorsement totals."

    Design: Corner/cross_cutting_layers/derived_field_reconciliation_after_void
    """
    lender = setup_approved_lender(lender_overrides={"legal_name": "Reconcile Co"})
    assert get_lender(lender["id"])["endorsed_volume_cents"] == 0
    case = create_case(lender["id"], borrower_reference="REC-V")
    attach_appraisal(case["id"], lender["id"])
    submit_case(case["id"], lender["id"])
    endorse_case(case["id"], reviewer="rev-1")
    assert get_lender(lender["id"])["endorsed_volume_cents"] == 30_000_000
    api_client.void_endorsement(
        case["id"], {"reason": "erroneous endorsement"},
        make_approver_headers("app-1"),
    )
    assert get_lender(lender["id"])["endorsed_volume_cents"] == 0


def test_immediate_consistency_cascade_visible_in_same_read(api):
    """PRD §3.6: "the suspension cascades in two hops: every loan case of the lender
    sitting in `UNDERWRITE_SUBMITTED` moves to `BLOCKED`, and — caused by the first hop
    — every `OPEN` repair escrow of each newly blocked case is frozen with
    `freeze_origin` set to `SUSPENSION`."

    Design: Corner/consistency_model/immediate_consistency_cascade_visible_in_same_read
    """
    lender = setup_approved_lender(lender_overrides={"legal_name": "Immediate Co"})
    case = create_case(lender["id"], borrower_reference="IMM-1")
    escrow = create_escrow(case["id"], lender["id"])
    submit_case(case["id"], lender["id"])
    response = _suspend(lender["id"])
    assert validate_success(response)["status"] == "SUSPENDED"
    # The very next reads already reflect both cascade hops; no settling window.
    assert get_case(case["id"])["status"] == "BLOCKED"
    escrow_after = {e["id"]: e for e in list_escrows(case["id"])}[escrow["id"]]
    assert escrow_after["status"] == "FROZEN"


# ---------------------------------------------------------------------------
# Difficulty: suspension cascade reaches only in-flight cases
# ---------------------------------------------------------------------------
def _setup_suspend_with_two_cases(api):
    """One ENDORSED case holding an OPEN escrow plus one UNDERWRITE_SUBMITTED case;
    the lender is then suspended."""
    lender = setup_approved_lender(lender_overrides={"legal_name": "Two Case Co"})
    _lender, endorsed_case = setup_endorsed_case(
        lender=lender, case_overrides={"borrower_reference": "DONE-1"}
    )
    escrow = create_escrow(endorsed_case["id"], lender["id"])
    inflight = create_case(lender["id"], borrower_reference="BOR-INFLIGHT",
                           base_loan_amount_cents=15_000_000,
                           appraised_value_cents=18_000_000)
    submit_case(inflight["id"], lender["id"])
    return lender, endorsed_case, escrow, inflight


def test_suspension_blocks_inflight_case_and_leaves_endorsed_escrow_open(api):
    """PRD §3.6: "the suspension cascades in two hops: every loan case of the lender
    sitting in `UNDERWRITE_SUBMITTED` moves to `BLOCKED`, and — caused by the first hop
    — every `OPEN` repair escrow of each newly blocked case is frozen with
    `freeze_origin` set to `SUSPENSION`."

    Design: Difficulty/transitive_cascade/lender_suspension_cascades_case_block_escrow_freeze
    """
    lender, endorsed_case, escrow, inflight = _setup_suspend_with_two_cases(api)
    validate_success(_suspend(lender["id"]))
    # Hop 1 fires only for the in-flight case.
    assert get_case(inflight["id"])["status"] == "BLOCKED"
    # Hop 2 follows hop 1: the ENDORSED case never blocked, so its escrow stays OPEN.
    escrow_after = {e["id"]: e for e in list_escrows(endorsed_case["id"])}[escrow["id"]]
    assert escrow_after["status"] == "OPEN"
    # The blocked case cannot be endorsed while suspended.
    response = api_client.endorsement_review(
        inflight["id"], {"decision": "ENDORSE"}, make_reviewer_headers("rev-1")
    )
    validate_error(response, ApiErrorId.ERR_CASE_BLOCKED)


def test_reinstate_unblocks_inflight_case(api):
    """PRD §3.6: "Reinstating reverses the same cascade: the lender moves from
    `SUSPENDED` back to `APPROVED`, every `BLOCKED` case of the lender returns to
    `UNDERWRITE_SUBMITTED`"

    Design: Difficulty/transitive_cascade/lender_suspension_cascades_case_block_escrow_freeze
    """
    lender, _endorsed_case, _escrow, inflight = _setup_suspend_with_two_cases(api)
    _suspend(lender["id"])
    validate_success(_reinstate(lender["id"]))
    assert get_lender(lender["id"])["status"] == "APPROVED"
    assert get_case(inflight["id"])["status"] == "UNDERWRITE_SUBMITTED"
