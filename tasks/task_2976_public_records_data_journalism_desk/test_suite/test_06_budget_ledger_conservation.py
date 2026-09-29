"""The desk fee-budget ledger as a conserved quantity across a withdrawal.

PRD S2.7 makes the four-column ledger satisfy one identity after *every single
mutation*: the total equals the sum of the available, committed and spent
columns, and no column ever goes negative. These tests walk a request through
the whole fiscal chain -- a determination that commits, a denial that releases,
an appeal filing that commits again -- and then compensate it with a withdrawal,
re-asserting the identity after every hop.
"""

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers import test_users as U
from test_helpers.assertions import (
    assert_ledger_columns,
    assert_ledger_identity,
    validate_created,
    validate_ok,
)

# The gross and net fee of the PRD S3.3 worked case where the agency ceiling
# binds: 3.5 search hours at 3500 cents plus 120 pages at 25 cents.
_GROSS_FEE_CENTS = 15250
_NET_FEE_CENTS = 5250
_FILING_FEE_CENTS = 4500
_OPENING_BUDGET_CENTS = 500000

_APPEAL_GROUNDS = (
    "The privacy exemption does not cover aggregate inspection outcomes."
)
_WITHDRAWAL_REASON = "The story was killed; we are dropping the request."


def _fee_chain_with_filed_appeal(api):
    """Drive the whole fiscal chain up to an appeal in ``FILED``.

    A fee determination commits the 5250 net fee, the agency's denial *releases*
    it, and the appeal filing commits a fresh 4500 -- so the request's own
    ``fee_committed_cents`` is already back to zero before the withdrawal, which
    is exactly what an implementation that double-releases gets wrong.
    """
    X.set_clock(api, C.STD_CLOCK)
    desk, agency = X.desk_and_agency(api)
    request = X.submitted_request(
        api,
        desk["id"],
        agency["id"],
        subject_summary="Section 8 inspection failures 2024-2025",
        estimated_page_count=120,
        waiver_requested=True,
        public_interest_score=85,
    )
    determined = validate_ok(
        api.determine_fee(
            request["id"],
            F.fee_determination_payload(3.5, 120),
            U.coordinator_headers(),
        )
    )
    denied = validate_ok(
        api.record_agency_decision(
            request["id"],
            F.agency_decision_payload(
                C.OUTCOME_DENIED, denial_reason_code="EXEMPT_PRIVACY"
            ),
            U.coordinator_headers(),
        )
    )
    appeal = validate_created(
        api.create_appeal(
            F.appeal_payload(
                request["id"],
                venue=C.VENUE_OMBUDS,
                filing_fee_cents=_FILING_FEE_CENTS,
                grounds=_APPEAL_GROUNDS,
            ),
            U.legal_headers(),
        )
    )
    return {
        "desk": desk,
        "agency": agency,
        "request": request,
        "determined": determined,
        "denied": denied,
        "appeal": appeal,
    }


def _withdraw(api, request_id):
    """Withdraw the request -- the compensating action of PRD S3.4."""
    return validate_ok(
        api.withdraw_records_request(
            request_id,
            F.withdrawal_payload(reason=_WITHDRAWAL_REASON),
            U.coordinator_headers(),
        )
    )


class TestFeeChainLedgerConservation:
    """Every money-moving hop before the withdrawal, checked one at a time."""

    def test_commit_release_and_commit_again_each_preserve_the_identity(self, api):
        """The three money hops that precede the withdrawal, hop by hop.

        PRD S2.7: "The governing invariant is a conserved quantity that must hold
        after every single mutation, with no drift: the total equals the sum of
        the available, committed and spent columns."

        Design: Difficulty/compensating_invariant/request_withdrawal_restores_the_desk_fee_ledger_without_drift
        """
        X.set_clock(api, C.STD_CLOCK)
        desk, agency = X.desk_and_agency(api)
        opening = validate_ok(api.get_desk(desk["id"], U.editor_headers()))
        assert_ledger_columns(
            opening,
            total=_OPENING_BUDGET_CENTS,
            available=_OPENING_BUDGET_CENTS,
            committed=0,
            spent=0,
        )

        request = X.submitted_request(
            api,
            desk["id"],
            agency["id"],
            subject_summary="Section 8 inspection failures 2024-2025",
            estimated_page_count=120,
            waiver_requested=True,
            public_interest_score=85,
        )

        # Commit: the net fee leaves available for committed (PRD S2.7, S3.3).
        determined = validate_ok(
            api.determine_fee(
                request["id"],
                F.fee_determination_payload(3.5, 120),
                U.coordinator_headers(),
            )
        )
        assert determined["fee_committed_cents"] == _NET_FEE_CENTS
        after_commit = validate_ok(api.get_desk(desk["id"], U.editor_headers()))
        assert_ledger_columns(
            after_commit,
            total=_OPENING_BUDGET_CENTS,
            available=_OPENING_BUDGET_CENTS - _NET_FEE_CENTS,
            committed=_NET_FEE_CENTS,
            spent=0,
        )

        # Release: a denial charges the desk nothing (PRD S3.4).
        denied = validate_ok(
            api.record_agency_decision(
                request["id"],
                F.agency_decision_payload(
                    C.OUTCOME_DENIED, denial_reason_code="EXEMPT_PRIVACY"
                ),
                U.coordinator_headers(),
            )
        )
        assert denied["fee_committed_cents"] == 0
        after_release = validate_ok(api.get_desk(desk["id"], U.editor_headers()))
        assert_ledger_columns(
            after_release,
            total=_OPENING_BUDGET_CENTS,
            available=_OPENING_BUDGET_CENTS,
            committed=0,
            spent=0,
        )

        # Commit again: the appeal's filing fee (PRD S2.7, S3.5).
        validate_created(
            api.create_appeal(
                F.appeal_payload(
                    request["id"],
                    venue=C.VENUE_OMBUDS,
                    filing_fee_cents=_FILING_FEE_CENTS,
                    grounds=_APPEAL_GROUNDS,
                ),
                U.legal_headers(),
            )
        )
        after_second_commit = validate_ok(
            api.get_desk(desk["id"], U.editor_headers())
        )
        assert_ledger_columns(
            after_second_commit,
            total=_OPENING_BUDGET_CENTS,
            available=_OPENING_BUDGET_CENTS - _FILING_FEE_CENTS,
            committed=_FILING_FEE_CENTS,
            spent=0,
        )
        assert after_second_commit["open_appeal_count"] == 1


class TestWithdrawalRestoresTheLedgerWithoutDrift:
    """The three-hop withdrawal of a request sitting in ``APPEAL_FILED``."""

    def test_withdrawal_cascades_through_the_filed_appeal(self, api):
        """Hops one and two: the request and then its filed appeal are withdrawn.

        PRD S3.5: "Hop one: the request moves APPEAL_FILED -> WITHDRAWN, its
        fee_committed_cents returns from the desk's committed column to the
        available column and is then zeroed. Hop two: because the request is
        withdrawn, its appeal in FILED moves to WITHDRAWN."

        Design: Difficulty/compensating_invariant/request_withdrawal_restores_the_desk_fee_ledger_without_drift
        """
        world = _fee_chain_with_filed_appeal(api)
        before = validate_ok(
            api.get_records_request(world["request"]["id"], U.coordinator_headers())
        )
        assert before["status"] == C.REQ_APPEAL_FILED

        withdrawn = _withdraw(api, world["request"]["id"])

        assert withdrawn["status"] == C.REQ_WITHDRAWN
        assert withdrawn["fee_committed_cents"] == 0

        request = validate_ok(
            api.get_records_request(world["request"]["id"], U.coordinator_headers())
        )
        assert request["status"] == C.REQ_WITHDRAWN
        assert request["fee_committed_cents"] == 0

        appeal = validate_ok(
            api.get_appeal(world["appeal"]["id"], U.legal_headers())
        )
        assert appeal["status"] == C.APPEAL_WITHDRAWN

    def test_withdrawal_restores_the_exact_opening_triple(self, api):
        """Hop three: the filing fee is refunded, not spent, and nothing drifts.

        PRD S3.5: "Hop three: because the appeal is withdrawn, its
        filing_fee_cents returns from the committed column to the available
        column and open_appeal_count decrements by 1."

        Design: Difficulty/compensating_invariant/request_withdrawal_restores_the_desk_fee_ledger_without_drift
        """
        world = _fee_chain_with_filed_appeal(api)

        before = validate_ok(api.get_desk(world["desk"]["id"], U.editor_headers()))
        assert_ledger_columns(
            before,
            total=_OPENING_BUDGET_CENTS,
            available=_OPENING_BUDGET_CENTS - _FILING_FEE_CENTS,
            committed=_FILING_FEE_CENTS,
            spent=0,
        )
        assert before["open_appeal_count"] == 1

        _withdraw(api, world["request"]["id"])

        desk = validate_ok(api.get_desk(world["desk"]["id"], U.editor_headers()))
        assert_ledger_columns(
            desk,
            total=_OPENING_BUDGET_CENTS,
            available=_OPENING_BUDGET_CENTS,
            committed=0,
            spent=0,
        )
        assert desk["open_appeal_count"] == 0
        assert desk["open_request_count"] == 0

    def test_withdrawal_does_not_double_release_the_requests_own_commitment(
        self, api
    ):
        """The denial already released the net fee, so the withdrawal must not again.

        PRD S2.7: "All four are integers in cents and none may ever go negative",
        and the total "equals the sum of the available, committed and spent
        columns" -- so a second release of the same 5250 would drive available
        past the total.

        Design: Difficulty/compensating_invariant/request_withdrawal_restores_the_desk_fee_ledger_without_drift
        """
        world = _fee_chain_with_filed_appeal(api)
        assert world["denied"]["fee_committed_cents"] == 0

        _withdraw(api, world["request"]["id"])

        desk = validate_ok(api.get_desk(world["desk"]["id"], U.editor_headers()))
        assert_ledger_identity(desk)
        assert desk["fee_budget_available_cents"] == _OPENING_BUDGET_CENTS
        assert desk["fee_budget_available_cents"] <= desk["fee_budget_total_cents"]
        assert desk["fee_budget_spent_cents"] == 0

    def test_withdrawal_is_not_a_litigation_event(self, api):
        """Abandoning a request leaves the desk's exposure counters alone.

        PRD S2.9: "litigation_exposure_count is the number of the desk's records
        requests whose status is LITIGATION_AUTHORIZED", and "if
        litigation_exposure_count is at least 1 the posture is RESTRICTED;
        otherwise the posture is OPEN".

        Design: Difficulty/compensating_invariant/request_withdrawal_restores_the_desk_fee_ledger_without_drift
        """
        world = _fee_chain_with_filed_appeal(api)

        _withdraw(api, world["request"]["id"])

        desk = validate_ok(api.get_desk(world["desk"]["id"], U.editor_headers()))
        assert desk["litigation_exposure_count"] == 0
        assert desk["security_posture"] == C.POSTURE_OPEN
        assert desk["open_request_count"] == 0
        assert desk["open_appeal_count"] == 0
        assert_ledger_identity(desk)

    def test_withdrawal_keeps_the_fee_determination_as_recorded_history(self, api):
        """Only the encumbrance is compensated; the agency's bill stays on the row.

        PRD S3.3: "net_fee_cents is the gross fee minus waiver_amount_cents. That
        net amount is then committed against the desk", and PRD S2.7: the
        request's "fee_committed_cents mirrors the desk-side encumbrance
        attributable to that one request, and it is set to zero whenever that
        encumbrance is settled or released."

        Design: Difficulty/compensating_invariant/request_withdrawal_restores_the_desk_fee_ledger_without_drift
        """
        world = _fee_chain_with_filed_appeal(api)
        assert world["determined"]["gross_fee_cents"] == _GROSS_FEE_CENTS
        assert world["determined"]["net_fee_cents"] == _NET_FEE_CENTS

        _withdraw(api, world["request"]["id"])

        request = validate_ok(
            api.get_records_request(world["request"]["id"], U.coordinator_headers())
        )
        assert request["gross_fee_cents"] == _GROSS_FEE_CENTS
        assert request["net_fee_cents"] == _NET_FEE_CENTS
        assert request["fee_committed_cents"] == 0
        assert request["fee_determined_at"] is not None

    def test_withdrawal_after_the_filing_fee_settled_does_not_claw_it_back(self, api):
        """A withdrawal releases what is still committed and never unspends money.

        PRD S3.5: "The filing_fee_cents settles, moving from the desk's committed
        column to its spent column", and PRD S3.4: "From AWAITING_AGENCY_RESPONSE
        the same happens, plus the request's fee_committed_cents returns from the
        committed column to the available column and is zeroed."

        Design: Difficulty/compensating_invariant/request_withdrawal_restores_the_desk_fee_ledger_without_drift
        """
        world = _fee_chain_with_filed_appeal(api)

        # A granted appeal spends the filing fee and reopens the request, which is
        # a status withdrawal is declared from (PRD S3.4, S3.5).
        validate_ok(
            api.decide_appeal(
                world["appeal"]["id"],
                F.appeal_decision_payload(C.APPEAL_GRANTED),
                U.coordinator_headers(),
            )
        )
        after_grant = validate_ok(
            api.get_desk(world["desk"]["id"], U.editor_headers())
        )
        assert_ledger_columns(
            after_grant,
            total=_OPENING_BUDGET_CENTS,
            available=_OPENING_BUDGET_CENTS - _FILING_FEE_CENTS,
            committed=0,
            spent=_FILING_FEE_CENTS,
        )

        withdrawn = _withdraw(api, world["request"]["id"])
        assert withdrawn["status"] == C.REQ_WITHDRAWN
        assert withdrawn["fee_committed_cents"] == 0

        desk = validate_ok(api.get_desk(world["desk"]["id"], U.editor_headers()))
        assert_ledger_columns(
            desk,
            total=_OPENING_BUDGET_CENTS,
            available=_OPENING_BUDGET_CENTS - _FILING_FEE_CENTS,
            committed=0,
            spent=_FILING_FEE_CENTS,
        )
        assert desk["open_request_count"] == 0
        assert desk["open_appeal_count"] == 0

        # Only an appeal in FILED is swept into WITHDRAWN (PRD S3.5, hop two).
        appeal = validate_ok(
            api.get_appeal(world["appeal"]["id"], U.legal_headers())
        )
        assert appeal["status"] == C.APPEAL_GRANTED
