"""Depth-2 cascade from dispute opening: work UNDER_DISPUTE, line DISPUTE_HELD."""
from test_helpers import (
    TEST_USERS, make_member_headers, validate_success,
    setup_pending_claim,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]


def _open_dispute():
    # PRD §3.6's contested branch seeds a dispute from the claim being
    # validated, i.e. a PENDING claim: "when a dispute is opened manually over
    # the claimed share, the claim instead moves to DISPUTED".
    dsp, report, line, accrual, member, work, claim = setup_pending_claim(
        title="Harrier", plays=200)
    dispute = validate_success(api_client.create_dispute({
        "work_id": work["id"],
        "share_context": "Alder Publishing 100%",
        "initiating_claim_id": claim["id"],
    }, make_member_headers(member["id"])), expected_status=201)
    return work, line, claim, dispute


def test_dispute_open_moves_work_to_under_dispute(api):
    """PRD §3.6: "Opening a dispute moves it to `OPEN`, moves the initiating
    claim to `DISPUTED`, moves the work to `UNDER_DISPUTE`, and freezes any
    affected line's postings by moving it to `DISPUTE_HELD`."

    Design: Difficulty/transitive_cascade/dispute_open_freeze_cascade
    """
    work, _line, claim, dispute = _open_dispute()
    work_after = validate_success(api_client.get_work(work["id"], ADMIN))
    assert work_after["status"] == "UNDER_DISPUTE", (
        f"dispute open bubbles up to the work; got {work_after['status']}")
    claim_after = validate_success(api_client.get_claim(claim["id"], ADMIN))
    assert claim_after["status"] == "DISPUTED"
    assert dispute["claim_ids"][0] == claim["id"], (
        f"the initiating claim is element zero of claim_ids; got {dispute['claim_ids']}")


def test_dispute_open_freezes_claimed_line(api):
    """PRD §3.6: "Opening a dispute moves it to `OPEN`, moves the initiating
    claim to `DISPUTED`, moves the work to `UNDER_DISPUTE`, and freezes any
    affected line's postings by moving it to `DISPUTE_HELD`."

    Design: Difficulty/transitive_cascade/dispute_open_freeze_cascade
    """
    _work, line, _claim, _dispute = _open_dispute()
    line_after = validate_success(api_client.get_usage_line(line["id"], ADMIN))
    assert line_after["status"] == "DISPUTE_HELD", (
        f"the claim fold-in freezes the contested line; got {line_after['status']}")
