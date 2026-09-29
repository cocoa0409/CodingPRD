"""Writes refused because of the state of a *different* entity.

A round blocked by its petition's status, a batch blocked by its assignment's
status, and a determination blocked by a fraud referral that names the petition.
Each pair is checked twice: refused, then admitted once the other entity moves.
"""
from test_helpers import (
    api_client,
    create_assignment,
    create_batch_payload,
    create_round_payload,
    determination_payload,
    file_batch_with_lines,
    issue_determination,
    make_county_clerk_headers,
    make_examiner_headers,
    make_proponent_headers,
    make_sos_admin_headers,
    open_referral,
    read_assignment,
    read_batch,
    read_circulator,
    read_petition,
    read_referral,
    refer_referral_to_ag,
    adjudicate_referral,
    close_circulation,
    open_round,
    run_verification_round,
    setup_circulation_ready,
    terminate_assignment,
    validate_error,
    validate_paginated,
)
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.fixtures import set_clock
from test_helpers.test_users import EXAMINER_USER_ID

TWO_ACTIVE_VOTERS = [
    {"voter_id_number": "VA1", "registration_status": "ACTIVE"},
    {"voter_id_number": "VA2", "registration_status": "ACTIVE"},
]


class TestRoundBlockedByPetitionState:
    """A verification round depends on the petition having closed circulation
    first."""

    def _cleared_with_verified_batch(self):
        set_clock(CLOCK_EPOCH)
        world = setup_circulation_ready(
            counties=[("ALPHA", 20)], voters=TWO_ACTIVE_VOTERS
        )
        file_batch_with_lines(world, ["VA1", "VA2"], batch_key="b1")
        assert read_petition(world["petition"]["id"])["status"] == "CLEARED"
        return world

    def test_a_round_cannot_be_opened_while_the_petition_is_still_cleared(self):
        """The batch is affidavit-verified and the pool would be non-empty, but
        the petition has not reached SIGNATURES_FILED.

        PRD §3.5: "Opening a round drives the petition's lifecycle. From
        SIGNATURES_FILED, a RANDOM_SAMPLE round moves the petition to
        SAMPLE_VERIFICATION and a FULL_CHECK round moves it directly to
        FULL_CHECK." PRD §2.11: "10. State preconditions ... The signals are
        ERR_INVALID_PETITION_STATE ... all HTTP 409."

        Design: Difficulty/cross_entity_state_dependency/round_creation_blocked_by_petition_not_yet_filed
        """
        world = self._cleared_with_verified_batch()

        validate_error(
            api_client.create_verification_round(
                world["petition"]["id"],
                create_round_payload("RANDOM_SAMPLE"),
                make_examiner_headers(),
            ),
            "ERR_INVALID_PETITION_STATE",
            409,
        )

        assert read_petition(world["petition"]["id"])["status"] == "CLEARED"
        rounds, _meta = validate_paginated(
            api_client.list_verification_rounds(
                make_examiner_headers(), params={"petition_id": world["petition"]["id"]}
            )
        )
        assert rounds == [], "no round was created"

    def test_filing_signatures_unlocks_the_first_round(self):
        """Closing circulation moves the petition to SIGNATURES_FILED and fixes
        the accepted pool, after which the same request is admitted as round one.

        PRD §3.5: "Rounds are assigned a 1-based round_index in creation order
        within their petition, begin at OPEN, and are readable individually and as
        a list narrowable by petition_id."

        Design: Difficulty/cross_entity_state_dependency/round_creation_blocked_by_petition_not_yet_filed
        """
        world = self._cleared_with_verified_batch()

        filed = close_circulation(world["petition"]["id"])
        assert filed["status"] == "SIGNATURES_FILED"
        assert filed["accepted_raw_total"] == 2

        opened = open_round(world["petition"]["id"], round_type="RANDOM_SAMPLE")
        assert opened["round_index"] == 1
        assert opened["eligible_pool_size"] == 2
        assert opened["status"] == "OPEN"

        rounds, _meta = validate_paginated(
            api_client.list_verification_rounds(
                make_examiner_headers(), params={"petition_id": world["petition"]["id"]}
            )
        )
        assert len(rounds) == 1
        assert rounds[0]["round_index"] == 1


class TestBatchBlockedByTerminatedAssignment:
    """Filing depends on an ACTIVE assignment, and termination releases the
    interval it occupied."""

    WINDOW_FROM = "2026-08-01T00:00:00Z"
    WINDOW_TO = "2026-08-31T00:00:00Z"

    def _terminated_assignment_world(self):
        set_clock(CLOCK_EPOCH)
        world = setup_circulation_ready(
            counties=[("ALPHA", 20)],
            voters=TWO_ACTIVE_VOTERS,
            effective_from=self.WINDOW_FROM,
            effective_to=self.WINDOW_TO,
        )
        terminated = terminate_assignment(world["assignments"]["c1"]["id"])
        assert terminated["status"] == "TERMINATED"
        set_clock("2026-08-10T00:00:00Z")
        return world

    def test_a_batch_cannot_be_filed_under_a_terminated_assignment(self):
        """The circulator is still REGISTERED, but its only assignment has been
        ended, so there is no active linkage to file against.

        PRD §3.4: "That circulator must hold an ACTIVE CirculationAssignment for
        this petition; if none was ever created, or the only one is SUSPENDED or
        TERMINATED, the filing is refused with ERR_NO_ACTIVE_ASSIGNMENT."

        Design: Difficulty/cross_entity_state_dependency/batch_creation_blocked_by_terminated_assignment
        """
        world = self._terminated_assignment_world()

        validate_error(
            api_client.create_signature_batch(
                create_batch_payload(
                    world["petition"]["id"],
                    world["circulators"]["c1"]["id"],
                    world["counties"]["ALPHA"]["id"],
                ),
                make_proponent_headers(),
            ),
            "ERR_NO_ACTIVE_ASSIGNMENT",
            409,
        )

        assert read_circulator(world["circulators"]["c1"]["id"])["registration_status"] == (
            "REGISTERED"
        )
        assert read_assignment(world["assignments"]["c1"]["id"])["status"] == "TERMINATED"
        assert read_petition(world["petition"]["id"])["raw_signature_count"] == 0

    def test_a_replacement_assignment_over_the_released_interval_unlocks_filing(self):
        """Because a TERMINATED interval occupies nothing, an identical window is
        admissible again, and filing succeeds under the new assignment.

        PRD §3.3: "Intervals of TERMINATED assignments do not occupy anything,
        which is the point of termination: ending an assignment early ... releases
        its interval so that a later overlapping assignment becomes admissible,
        and blocks any further batch filing under it."

        Design: Difficulty/cross_entity_state_dependency/batch_creation_blocked_by_terminated_assignment
        """
        world = self._terminated_assignment_world()

        replacement = create_assignment(
            world["petition"]["id"],
            world["circulators"]["c1"]["id"],
            assigned_county_codes=["ALPHA"],
            effective_from=self.WINDOW_FROM,
            effective_to=self.WINDOW_TO,
        )
        assert replacement["status"] == "ACTIVE"

        record = file_batch_with_lines(world, [], batch_key="b1", verify=False)
        assert read_batch(record["batch"]["id"])["status"] == "RECEIVED"


class TestDeterminationBlockedByOpenReferral:
    """The fraud gate of §3.8 holds the determination until the referral is
    adjudicated — being referred to the Attorney General is not enough."""

    def _certifiable_with_referral(self):
        """A petition in PENDING_CERTIFICATION whose ALPHA county clerk has
        opened a FORGED_SIGNATURES referral naming no batch."""
        set_clock(CLOCK_EPOCH)
        world = setup_circulation_ready(
            counties=[("ALPHA", 20)], voters=TWO_ACTIVE_VOTERS
        )
        file_batch_with_lines(world, ["VA1", "VA2"], batch_key="b1")
        closed = run_verification_round(
            world, round_type="FULL_CHECK", examiner_id=EXAMINER_USER_ID
        )
        assert closed["determination"] == "SUFFICIENT"
        petition = read_petition(world["petition"]["id"])
        assert petition["verified_valid_count"] == 2
        assert petition["qualifying_county_count"] == 1
        assert petition["status"] == "PENDING_CERTIFICATION"

        world["referral"] = open_referral(
            world["petition"]["id"],
            world["circulators"]["c1"]["id"],
            referral_type="FORGED_SIGNATURES",
            opener_headers=make_county_clerk_headers(world["counties"]["ALPHA"]["id"]),
        )
        assert world["referral"]["status"] == "OPENED"
        return world

    def test_certification_is_blocked_while_the_referral_is_open_or_with_the_ag(self):
        """Both OPENED and REFERRED_TO_AG count as open for the fraud gate.

        PRD §3.8: "The second gate is the fraud dimension: no FraudReferral
        naming this petition may have a status of OPENED or REFERRED_TO_AG, else
        the request is refused with ERR_FRAUD_REFERRAL_OPEN."

        Design: Difficulty/cross_entity_state_dependency/determination_blocked_by_open_fraud_referral
        """
        world = self._certifiable_with_referral()
        petition_id = world["petition"]["id"]

        validate_error(
            api_client.issue_determination(
                petition_id, determination_payload("CERTIFY"), make_sos_admin_headers()
            ),
            "ERR_FRAUD_REFERRAL_OPEN",
            409,
        )

        referred = refer_referral_to_ag(world["referral"]["id"])
        assert referred["status"] == "REFERRED_TO_AG"

        validate_error(
            api_client.issue_determination(
                petition_id, determination_payload("CERTIFY"), make_sos_admin_headers()
            ),
            "ERR_FRAUD_REFERRAL_OPEN",
            409,
        )

        assert read_petition(petition_id)["status"] == "PENDING_CERTIFICATION"

    def test_certification_proceeds_once_the_referral_is_unsubstantiated(self):
        """An UNSUBSTANTIATED finding cascades nowhere and unblocks the
        determination, leaving the counters exactly as the tally left them.

        PRD §3.9: "An UNSUBSTANTIATED finding cascades nowhere. It records the
        finding, and because the referral is no longer open the petition's
        determination unblocks and the circulator's provisional open-referral
        penalty falls away."

        Design: Difficulty/cross_entity_state_dependency/determination_blocked_by_open_fraud_referral
        """
        world = self._certifiable_with_referral()
        petition_id = world["petition"]["id"]

        refer_referral_to_ag(world["referral"]["id"])
        adjudicated = adjudicate_referral(
            world["referral"]["id"],
            "UNSUBSTANTIATED",
            adjudicator_headers=make_examiner_headers(),
        )
        assert adjudicated["status"] == "UNSUBSTANTIATED"
        assert adjudicated["voided_signature_count"] == 0

        certified = issue_determination(petition_id, "CERTIFY")
        assert certified["status"] == "CERTIFIED"
        assert certified["verified_valid_count"] == 2
        assert certified["qualifying_county_count"] == 1
        assert read_circulator(world["circulators"]["c1"]["id"])[
            "misconduct_strike_count"
        ] == 0
        assert read_referral(world["referral"]["id"])["status"] == "UNSUBSTANTIATED"
