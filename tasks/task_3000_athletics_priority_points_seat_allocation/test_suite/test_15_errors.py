"""Error reachability: every collection's own 404, proved from an empty store.

Section 2.7 gives each collection its own not-found code and section 2.8 puts
the path-existence sweep at step 5 — above the body contract, above the version
stamp and above every state gate. Each test here fires one request at an id
that was never minted, choosing a caller and a payload that clear every check
sitting *above* step 5 so that the collection-specific 404 is the only verdict
the specification allows.
"""

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_GIFT_NOT_FOUND,
    ERR_LEDGER_ENTRY_NOT_FOUND,
    ERR_RECALCULATION_NOT_FOUND,
    ERR_RELOCATION_REQUEST_NOT_FOUND,
    ERR_SEAT_ASSIGNMENT_NOT_FOUND,
    ERR_SEAT_NOT_FOUND,
    ERR_SELECTION_EVENT_NOT_FOUND,
    ERR_SELECTION_SLOT_NOT_FOUND,
    ERR_TRANSFER_NOT_FOUND,
)
from test_helpers.assertions import validate_error
from test_helpers.constants import DECISION_DENY, GIFT_RECEIVED
from test_helpers.test_users import ANALYST, CERTIFIER, OFFICER, POLICY

# Probe identifiers: well-formed UUIDs that no factory ever mints, so the store
# cannot contain them however the tests are ordered.
MISSING_GIFT_ID = "00000000-0000-4000-8000-000000000101"
MISSING_RECALCULATION_ID = "00000000-0000-4000-8000-000000000102"
MISSING_LEDGER_ENTRY_ID = "00000000-0000-4000-8000-000000000103"
MISSING_TRANSFER_ID = "00000000-0000-4000-8000-000000000104"
MISSING_SEAT_ID = "00000000-0000-4000-8000-000000000105"
MISSING_ASSIGNMENT_ID = "00000000-0000-4000-8000-000000000106"
MISSING_EVENT_ID = "00000000-0000-4000-8000-000000000107"
MISSING_SLOT_ID = "00000000-0000-4000-8000-000000000108"
MISSING_RELOCATION_REQUEST_ID = "00000000-0000-4000-8000-000000000109"


class TestAnUnknownPathIdOutranksEveryStateGate:
    """Step 5 fires before steps 9, 10, 21 and 23, so 404 beats 409 and 422."""

    def test_settling_an_unknown_gift_reports_the_gift_code_not_a_state_error(
        self, client
    ):
        """Settling is state-gated, but a gift that does not exist has no state.

        PRD 2.8: "Checks run strictly in the sequence below; the **first** rule
        that a request violates determines the response, and no later rule is
        evaluated."

        PRD 2.8: "Every path identifier resolves, checked left to right — on
        every endpoint that has path parameters."

        PRD 2.8: "The target resource's current state admits the requested
        transition — on every state-transition endpoint. Violation:
        `ERR_INVALID_STATE` (409)."

        PRD 2.7: "Each collection has its own not-found code:
        `ERR_DONOR_NOT_FOUND`, `ERR_GIFT_NOT_FOUND`,
        `ERR_RECALCULATION_NOT_FOUND`, `ERR_LEDGER_ENTRY_NOT_FOUND`,
        `ERR_DISPUTE_NOT_FOUND`, `ERR_TRANSFER_NOT_FOUND`,
        `ERR_SECTION_NOT_FOUND`, `ERR_SEAT_NOT_FOUND`,
        `ERR_SEAT_ASSIGNMENT_NOT_FOUND`, `ERR_SELECTION_EVENT_NOT_FOUND`,
        `ERR_SELECTION_SLOT_NOT_FOUND` and `ERR_RELOCATION_REQUEST_NOT_FOUND`,
        each carrying HTTP 404."

        Design: Corner/errors/settling_an_unknown_gift_returns_gift_not_found_before_any_state_check
        """
        refused = client.settle_gift(
            MISSING_GIFT_ID, f.settle_gift_payload(GIFT_RECEIVED), headers=OFFICER
        )
        validate_error(refused, ERR_GIFT_NOT_FOUND, 404)

    def test_running_an_unknown_recalculation_reports_the_recalculation_code(
        self, client
    ):
        """The run action is the shortest path to the recalculation's own 404.

        PRD 2.8: "Every path identifier resolves, checked left to right — on
        every endpoint that has path parameters."

        PRD 2.8: "The target resource's current state admits the requested
        transition — on every state-transition endpoint. Violation:
        `ERR_INVALID_STATE` (409)."

        PRD 2.7: "Each collection has its own not-found code:
        `ERR_DONOR_NOT_FOUND`, `ERR_GIFT_NOT_FOUND`,
        `ERR_RECALCULATION_NOT_FOUND`, `ERR_LEDGER_ENTRY_NOT_FOUND`,
        `ERR_DISPUTE_NOT_FOUND`, `ERR_TRANSFER_NOT_FOUND`,
        `ERR_SECTION_NOT_FOUND`, `ERR_SEAT_NOT_FOUND`,
        `ERR_SEAT_ASSIGNMENT_NOT_FOUND`, `ERR_SELECTION_EVENT_NOT_FOUND`,
        `ERR_SELECTION_SLOT_NOT_FOUND` and `ERR_RELOCATION_REQUEST_NOT_FOUND`,
        each carrying HTTP 404."

        Design: Corner/errors/running_an_unknown_recalculation_returns_recalculation_not_found
        """
        refused = client.run_recalculation(
            MISSING_RECALCULATION_ID, {}, headers=OFFICER
        )
        validate_error(refused, ERR_RECALCULATION_NOT_FOUND, 404)

    def test_publishing_slots_for_an_unknown_event_reports_the_event_code(
        self, client
    ):
        """Neither the certification gate nor the overflow gate can be reached.

        PRD 2.8: "Every path identifier resolves, checked left to right — on
        every endpoint that has path parameters."

        PRD 2.8: "The recalculation the operation depends on is in `CERTIFIED`.
        This applies to publishing slots for a selection event, starting a
        section's reseating, and reading a recalculation's retention analysis.
        Violation: `ERR_RECALCULATION_NOT_CERTIFIED` (409)."

        PRD 2.8: "The last computed slot's `slot_end` does not fall after the
        event's `window_end`. This applies to publishing slots. Violation:
        `ERR_SLOT_WINDOW_OVERFLOW` (422)."

        PRD 2.7: "Each collection has its own not-found code:
        `ERR_DONOR_NOT_FOUND`, `ERR_GIFT_NOT_FOUND`,
        `ERR_RECALCULATION_NOT_FOUND`, `ERR_LEDGER_ENTRY_NOT_FOUND`,
        `ERR_DISPUTE_NOT_FOUND`, `ERR_TRANSFER_NOT_FOUND`,
        `ERR_SECTION_NOT_FOUND`, `ERR_SEAT_NOT_FOUND`,
        `ERR_SEAT_ASSIGNMENT_NOT_FOUND`, `ERR_SELECTION_EVENT_NOT_FOUND`,
        `ERR_SELECTION_SLOT_NOT_FOUND` and `ERR_RELOCATION_REQUEST_NOT_FOUND`,
        each carrying HTTP 404."

        Design: Corner/errors/publishing_slots_for_an_unknown_event_returns_selection_event_not_found
        """
        refused = client.publish_slots(MISSING_EVENT_ID, {}, headers=OFFICER)
        validate_error(refused, ERR_SELECTION_EVENT_NOT_FOUND, 404)

    def test_deciding_an_unknown_relocation_request_reports_the_request_code(
        self, client
    ):
        """A DENY carries no target seat, so only step 5 has anything to say.

        PRD 2.8: "Every path identifier resolves, checked left to right — on
        every endpoint that has path parameters."

        PRD 2.8: "A granted relocation supplies `target_seat_id`, and that seat
        belongs to `target_section_id`. This applies to a relocation decision.
        Violation: `ERR_RELOCATION_TARGET_INVALID` (422)."

        PRD 2.7: "Each collection has its own not-found code:
        `ERR_DONOR_NOT_FOUND`, `ERR_GIFT_NOT_FOUND`,
        `ERR_RECALCULATION_NOT_FOUND`, `ERR_LEDGER_ENTRY_NOT_FOUND`,
        `ERR_DISPUTE_NOT_FOUND`, `ERR_TRANSFER_NOT_FOUND`,
        `ERR_SECTION_NOT_FOUND`, `ERR_SEAT_NOT_FOUND`,
        `ERR_SEAT_ASSIGNMENT_NOT_FOUND`, `ERR_SELECTION_EVENT_NOT_FOUND`,
        `ERR_SELECTION_SLOT_NOT_FOUND` and `ERR_RELOCATION_REQUEST_NOT_FOUND`,
        each carrying HTTP 404."

        Design: Corner/errors/deciding_an_unknown_relocation_request_returns_relocation_request_not_found
        """
        refused = client.decide_relocation_request(
            MISSING_RELOCATION_REQUEST_ID,
            f.relocation_decision_payload(
                DECISION_DENY,
                decision_note="probe for a request that does not exist",
            ),
            headers=OFFICER,
        )
        validate_error(refused, ERR_RELOCATION_REQUEST_NOT_FOUND, 404)


class TestAnUnknownPathIdIsReportedOnceTheRoleGatesPass:
    """Steps 2 and 3 sit above step 5, so the caller must be entitled to hear it."""

    def test_the_ledger_entrys_own_code_reaches_a_dispute_analyst(self, client):
        """A ledger entry is append-only, so its singleton read is the only probe.

        PRD 2.8: "`X-User-Role` is one of the roles listed for the endpoint — on
        every endpoint."

        PRD 2.8: "Every path identifier resolves, checked left to right — on
        every endpoint that has path parameters."

        PRD 2.7: "Each collection has its own not-found code:
        `ERR_DONOR_NOT_FOUND`, `ERR_GIFT_NOT_FOUND`,
        `ERR_RECALCULATION_NOT_FOUND`, `ERR_LEDGER_ENTRY_NOT_FOUND`,
        `ERR_DISPUTE_NOT_FOUND`, `ERR_TRANSFER_NOT_FOUND`,
        `ERR_SECTION_NOT_FOUND`, `ERR_SEAT_NOT_FOUND`,
        `ERR_SEAT_ASSIGNMENT_NOT_FOUND`, `ERR_SELECTION_EVENT_NOT_FOUND`,
        `ERR_SELECTION_SLOT_NOT_FOUND` and `ERR_RELOCATION_REQUEST_NOT_FOUND`,
        each carrying HTTP 404."

        Design: Corner/errors/reading_an_unknown_ledger_entry_returns_ledger_entry_not_found
        """
        refused = client.get_point_ledger_entry(
            MISSING_LEDGER_ENTRY_ID, headers=ANALYST
        )
        validate_error(refused, ERR_LEDGER_ENTRY_NOT_FOUND, 404)

    def test_approving_an_unknown_transfer_as_its_only_role_reports_the_transfer_code(
        self, client
    ):
        """Approval is exclusive to the certifier, so no other role can see this.

        PRD 2.8: "`X-User-Role` is one of the roles listed for the endpoint — on
        every endpoint."

        PRD 2.8: "Every path identifier resolves, checked left to right — on
        every endpoint that has path parameters."

        PRD 2.7: "Each collection has its own not-found code:
        `ERR_DONOR_NOT_FOUND`, `ERR_GIFT_NOT_FOUND`,
        `ERR_RECALCULATION_NOT_FOUND`, `ERR_LEDGER_ENTRY_NOT_FOUND`,
        `ERR_DISPUTE_NOT_FOUND`, `ERR_TRANSFER_NOT_FOUND`,
        `ERR_SECTION_NOT_FOUND`, `ERR_SEAT_NOT_FOUND`,
        `ERR_SEAT_ASSIGNMENT_NOT_FOUND`, `ERR_SELECTION_EVENT_NOT_FOUND`,
        `ERR_SELECTION_SLOT_NOT_FOUND` and `ERR_RELOCATION_REQUEST_NOT_FOUND`,
        each carrying HTTP 404."

        Design: Corner/errors/approving_an_unknown_transfer_returns_transfer_not_found
        """
        refused = client.approve_point_transfer(
            MISSING_TRANSFER_ID, {}, headers=CERTIFIER
        )
        validate_error(refused, ERR_TRANSFER_NOT_FOUND, 404)

    def test_an_officer_forfeiting_an_unknown_slot_reports_the_slot_code(
        self, client
    ):
        """The ownership check binds the Donor role only, so an officer clears it.

        PRD 2.8: "For a caller acting as `Donor`, `X-User-ID` equals the
        `donor_id` of the targeted dispute, selection slot, relocation request or
        seat assignment. This applies to exactly five operations: filing a point
        dispute, providing information on a dispute, picking a seat through a
        selection slot, forfeiting a selection slot, and creating a relocation
        request. Violation: `ERR_NOT_RESOURCE_OWNER` (403)."

        PRD 2.8: "Every path identifier resolves, checked left to right — on
        every endpoint that has path parameters."

        PRD 2.7: "Each collection has its own not-found code:
        `ERR_DONOR_NOT_FOUND`, `ERR_GIFT_NOT_FOUND`,
        `ERR_RECALCULATION_NOT_FOUND`, `ERR_LEDGER_ENTRY_NOT_FOUND`,
        `ERR_DISPUTE_NOT_FOUND`, `ERR_TRANSFER_NOT_FOUND`,
        `ERR_SECTION_NOT_FOUND`, `ERR_SEAT_NOT_FOUND`,
        `ERR_SEAT_ASSIGNMENT_NOT_FOUND`, `ERR_SELECTION_EVENT_NOT_FOUND`,
        `ERR_SELECTION_SLOT_NOT_FOUND` and `ERR_RELOCATION_REQUEST_NOT_FOUND`,
        each carrying HTTP 404."

        Design: Corner/errors/forfeiting_an_unknown_slot_as_an_officer_returns_selection_slot_not_found
        """
        refused = client.forfeit_slot(
            MISSING_SLOT_ID,
            f.forfeit_payload(reason="probe for a slot that does not exist"),
            headers=OFFICER,
        )
        validate_error(refused, ERR_SELECTION_SLOT_NOT_FOUND, 404)


class TestAPathIdIsNeverReportedAsABodyReferenceOrAVersionFailure:
    """Step 5 owns path ids; steps 7 and 8 own body ids and version stamps."""

    def test_reading_an_unknown_seat_reports_the_seat_code(self, client):
        """The same id inside a pick body would be a reference failure instead.

        PRD 2.7: "Identifiers supplied inside a request body are a separate
        concern and report a separate code."

        PRD 2.8: "Every path identifier resolves, checked left to right — on
        every endpoint that has path parameters."

        PRD 2.7: "Each collection has its own not-found code:
        `ERR_DONOR_NOT_FOUND`, `ERR_GIFT_NOT_FOUND`,
        `ERR_RECALCULATION_NOT_FOUND`, `ERR_LEDGER_ENTRY_NOT_FOUND`,
        `ERR_DISPUTE_NOT_FOUND`, `ERR_TRANSFER_NOT_FOUND`,
        `ERR_SECTION_NOT_FOUND`, `ERR_SEAT_NOT_FOUND`,
        `ERR_SEAT_ASSIGNMENT_NOT_FOUND`, `ERR_SELECTION_EVENT_NOT_FOUND`,
        `ERR_SELECTION_SLOT_NOT_FOUND` and `ERR_RELOCATION_REQUEST_NOT_FOUND`,
        each carrying HTTP 404."

        Design: Corner/errors/reading_an_unknown_seat_returns_seat_not_found
        """
        refused = client.get_seat(MISSING_SEAT_ID, headers=OFFICER)
        validate_error(refused, ERR_SEAT_NOT_FOUND, 404)

    def test_reading_an_unknown_seat_assignment_reports_the_assignment_code(
        self, client
    ):
        """No version stamp is on offer, so step 8 cannot pre-empt step 5.

        PRD 2.8: "The supplied version stamp equals the parent's current
        `version`. This applies to a donor status change, a household link,
        certification, transfer creation, a section reprice, a renovation action,
        a seat pick, an occupancy change, and relocation-request creation.
        Violation: `ERR_STALE_VERSION` (412)."

        PRD 2.8: "Every path identifier resolves, checked left to right — on
        every endpoint that has path parameters."

        PRD 2.7: "Each collection has its own not-found code:
        `ERR_DONOR_NOT_FOUND`, `ERR_GIFT_NOT_FOUND`,
        `ERR_RECALCULATION_NOT_FOUND`, `ERR_LEDGER_ENTRY_NOT_FOUND`,
        `ERR_DISPUTE_NOT_FOUND`, `ERR_TRANSFER_NOT_FOUND`,
        `ERR_SECTION_NOT_FOUND`, `ERR_SEAT_NOT_FOUND`,
        `ERR_SEAT_ASSIGNMENT_NOT_FOUND`, `ERR_SELECTION_EVENT_NOT_FOUND`,
        `ERR_SELECTION_SLOT_NOT_FOUND` and `ERR_RELOCATION_REQUEST_NOT_FOUND`,
        each carrying HTTP 404."

        Design: Corner/errors/reading_an_unknown_seat_assignment_returns_seat_assignment_not_found
        """
        refused = client.get_seat_assignment(MISSING_ASSIGNMENT_ID, headers=POLICY)
        validate_error(refused, ERR_SEAT_ASSIGNMENT_NOT_FOUND, 404)
