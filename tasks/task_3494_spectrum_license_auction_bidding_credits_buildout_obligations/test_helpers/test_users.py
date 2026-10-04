"""Pre-built role headers for every role in the PRD.

Role identity (PRD access-control section):
- AuctionAdmin / TransferReviewer: X-User-ID is an opaque operator identifier,
  never compared to any resource id. Shared constants are canonical.
- Bidder: X-User-ID IS the acting Applicant's id (entity-backed). The shared
  constant is a BOOTSTRAP identity usable only for self-registration
  (POST /applicants) and for non-ownership calls; every ownership-gated call
  (disclosure PATCH, upfront-payments, resubmit, withdraw, bids,
  assignment-bids, settlement-payments, milestone file-notice, transfer
  filing / PROVIDE_INFO / withdraw, renewal filing) MUST use
  make_bidder_headers(applicant["id"]).
- IncumbentOperator: X-User-ID IS the Incumbent's id (entity-backed). The
  shared constant is only for non-ownership calls (e.g. negative RBAC
  probes); transition calls MUST use
  make_incumbent_operator_headers(incumbent["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — canonical shared form.
    "auction_admin_headers": build_user_headers("test-auction-admin-1", "AuctionAdmin"),
    "transfer_reviewer_headers": build_user_headers("test-transfer-reviewer-1", "TransferReviewer"),
    # Entity-backed roles — shared constants are BOOTSTRAP / non-ownership
    # fallbacks only; see module docstring.
    "bidder_headers": build_user_headers("test-bidder-bootstrap-1", "Bidder"),
    "incumbent_operator_headers": build_user_headers(
        "test-incumbent-bootstrap-1", "IncumbentOperator"
    ),
}


def make_bidder_headers(applicant_id: str) -> dict:
    """Bidder headers for the specific Applicant. Pass the applicant's own id
    on every ownership-gated call; the bid's bidder_applicant_id is always the
    caller, and license/milestone/transfer ownership checks compare the
    resource's applicant FK against this id."""
    return build_user_headers(applicant_id, "Bidder")


def make_incumbent_operator_headers(incumbent_id: str) -> dict:
    """IncumbentOperator headers for the specific Incumbent. Pass the
    incumbent's own id on every transition call (SUBMIT_PLAN, DISPUTE,
    RESUBMIT_PLAN, CONFIRM_CLEARED)."""
    return build_user_headers(incumbent_id, "IncumbentOperator")


def make_auction_admin_headers(operator_id: str = "test-auction-admin-1") -> dict:
    """AuctionAdmin headers; the id is opaque and never ownership-checked."""
    return build_user_headers(operator_id, "AuctionAdmin")


def make_transfer_reviewer_headers(operator_id: str = "test-transfer-reviewer-1") -> dict:
    """TransferReviewer headers; the id is opaque and never ownership-checked."""
    return build_user_headers(operator_id, "TransferReviewer")
