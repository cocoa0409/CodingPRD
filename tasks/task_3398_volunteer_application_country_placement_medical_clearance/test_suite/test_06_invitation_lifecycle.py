"""Invitation lifecycle: decline, expiry, rescission cascades, seat
conservation, and immediate read-after-write consistency."""

import pytest

from test_helpers import (
    ApiErrorId,
    CLOCK_AFTER_INVITATION_EXPIRY,
    DEFAULT_CLOCK_START,
    TEST_USERS,
    accept_invitation,
    api_client,
    assert_seat_accounting_invariants,
    complete_interview_payload,
    create_applicant,
    create_medical_clearance,
    create_program_with_opening,
    determine_medical_payload,
    get_application,
    get_opening,
    issue_invitation,
    make_applicant_headers,
    run_applicant_to_evaluated,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
PLACER = TEST_USERS["placement_officer_headers"]
MEDIC = TEST_USERS["medical_officer_headers"]


class TestDeclineAndCancel:
    def test_invitation_decline_releases_seat_and_locks(self):
        """PRD §3.4: "Decline moves the invitation to `DECLINED`, releases
        the held seat, and returns the application from `INVITED` to
        `UNDER_REVIEW` — the re-matching loop, in which the application may
        be interviewed again or invited to another opening."
        PRD §3.4: "`ACCEPTED`, `DECLINED`, `EXPIRED`, and `RESCINDED` are all
        terminal for the invitation."
        PRD §2.9: "State-machine guards run sixth, each with its dedicated
        error where one exists — `ERR_INVALID_APPLICATION_STATE` for
        application transitions attempted from a state that does not offer
        them, `ERR_OPENING_NOT_OPEN` for issuance against a non-`OPEN`
        opening or cancellation of a `CLOSED` or `CANCELLED` one,
        `ERR_INVITATION_NOT_ACTIONABLE` for answering an invitation no longer
        `ISSUED`, `ERR_MEDICAL_CLEARANCE_NOT_REVIEWABLE` for determining a
        clearance no longer `SUBMITTED`, `ERR_ENROLLMENT_NOT_ASSESSABLE` for
        assessment, remediation, or swearing-in attempted from the wrong
        enrollment state, and `ERR_SERVICE_NOT_ACTIVE` for service-scoped
        actions against a service that is not `ACTIVE`."

        Design: Corner/state_machines/invitation_decline_releases_seat_and_locks
        """
        set_clock(DEFAULT_CLOCK_START)
        program, opening = create_program_with_opening(
            opening_overrides={"seats_total": 1})
        ana = create_applicant()
        bundle = run_applicant_to_evaluated(
            ana, {"country_preference_ids": [program["id"]]})
        invitation = issue_invitation(bundle["application"]["id"], opening["id"])
        assert get_opening(opening["id"])["seats_provisional"] == 1

        declined = validate_success(
            api_client.decline_invitation(
                invitation["id"], make_applicant_headers(ana["id"])), 200)
        assert declined["status"] == "DECLINED"
        assert get_opening(opening["id"])["seats_provisional"] == 0, \
            "the held seat is released"
        assert get_application(bundle["application"]["id"])["status"] == "UNDER_REVIEW"

        # DECLINED is terminal: neither a second decline nor an accept works.
        validate_error(
            api_client.decline_invitation(
                invitation["id"], make_applicant_headers(ana["id"])),
            ApiErrorId.ERR_INVITATION_NOT_ACTIONABLE, 409)
        validate_error(
            api_client.accept_invitation(
                invitation["id"], make_applicant_headers(ana["id"])),
            ApiErrorId.ERR_INVITATION_NOT_ACTIONABLE, 409)

    def test_opening_cancel_cascades_issued_invitation(self):
        """PRD §3.1: "Available from `OPEN` or `FILLED` — attempting it on a
        `CLOSED` or `CANCELLED` opening is rejected with
        `ERR_OPENING_NOT_OPEN` — cancellation moves the opening to `CANCELLED`
        and fires the full rescission cascade. Every invitation still
        `ISSUED` becomes `RESCINDED`, releasing its held seat and returning
        its application from `INVITED` to `UNDER_REVIEW`."

        Design: Corner/state_machines/opening_cancel_cascades_issued_invitation
        """
        set_clock(DEFAULT_CLOCK_START)
        program, opening = create_program_with_opening(
            opening_overrides={"seats_total": 2})
        ana = create_applicant()
        bundle = run_applicant_to_evaluated(
            ana, {"country_preference_ids": [program["id"]]})
        invitation = issue_invitation(bundle["application"]["id"], opening["id"])
        assert get_opening(opening["id"])["seats_provisional"] == 1
        assert get_application(bundle["application"]["id"])["status"] == "INVITED"

        cancelled = validate_success(
            api_client.cancel_assignment_opening(opening["id"], ADMIN), 200)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["seats_provisional"] == 0

        inv = validate_success(api_client.get_invitation(invitation["id"], PLACER), 200)
        assert inv["status"] == "RESCINDED"
        assert get_application(bundle["application"]["id"])["status"] == "UNDER_REVIEW"


class TestExpiredInvitationPriorityPair:
    def _expired_invitation(self):
        """Ana INVITED; clock passes the acceptance deadline so the sweep
        expires the invitation. Returns (ana, bob, app_id, invitation_id,
        opening_id)."""
        set_clock(DEFAULT_CLOCK_START)
        program, opening = create_program_with_opening(
            opening_overrides={"seats_total": 2})
        ana = create_applicant()
        bundle = run_applicant_to_evaluated(
            ana, {"country_preference_ids": [program["id"]]})
        invitation = issue_invitation(bundle["application"]["id"], opening["id"])
        bob = create_applicant()
        set_clock(CLOCK_AFTER_INVITATION_EXPIRY)
        expired = validate_success(
            api_client.get_invitation(invitation["id"], PLACER), 200)
        assert expired["status"] == "EXPIRED"
        assert get_application(bundle["application"]["id"])["status"] == "UNDER_REVIEW"
        assert get_opening(opening["id"])["seats_provisional"] == 0
        return ana, bob, bundle["application"]["id"], invitation["id"], opening["id"]

    def test_non_owner_accept_beats_state_check(self):
        """PRD §2.9: "A single request can violate several rules at once, so
        the system evaluates checks in a fixed priority order and reports
        only the first failure: authentication (missing or malformed headers,
        `ERR_UNAUTHENTICATED`); role authorization (`ERR_FORBIDDEN`);
        applicant ownership (`ERR_NOT_OWNER`); resource existence; optimistic
        concurrency (`ERR_STALE_OPENING_VERSION`); state-machine guards;
        compliance gates; business-constraint gates; the temporal gate on
        service completion; and finally field-shape validation
        (`ERR_VALIDATION`)."
        PRD §2.4: "Every invitation still `ISSUED` whose
        `acceptance_deadline` is strictly earlier than the new reading
        becomes `EXPIRED`; its opening's `seats_provisional` is decremented,
        and its application moves from `INVITED` back to `UNDER_REVIEW`."

        Design: Difficulty/priority_pair_validation_conflict/expired_invitation_ownership_check_beats_state_check
        """
        ana, bob, app_id, inv_id, opening_id = self._expired_invitation()

        # Bob violates ownership (priority 3) AND state (priority 6): the
        # ownership error must win.
        validate_error(
            api_client.accept_invitation(inv_id, make_applicant_headers(bob["id"])),
            ApiErrorId.ERR_NOT_OWNER, 403)
        # Ana violates only the state guard: the state error surfaces.
        validate_error(
            api_client.accept_invitation(inv_id, make_applicant_headers(ana["id"])),
            ApiErrorId.ERR_INVITATION_NOT_ACTIONABLE, 409)

        inv = validate_success(api_client.get_invitation(inv_id, PLACER), 200)
        assert inv["status"] == "EXPIRED", "rejected accepts must not mutate"
        opening = get_opening(opening_id)
        assert opening["seats_provisional"] == 0
        assert opening["seats_committed"] == 0

    def test_non_owner_decline_beats_state_check(self):
        """PRD §2.1: "Seven applicant-scoped operations enforce this
        ownership check and reject a mismatched caller with `ERR_NOT_OWNER`
        (HTTP 403): submitting an application, withdrawing an application,
        accepting an invitation, declining an invitation, creating a medical
        clearance, resubmitting a medical clearance, and reading the match
        list of an application."
        PRD §2.9: "A single request can violate several rules at once, so the
        system evaluates checks in a fixed priority order and reports only
        the first failure: authentication (missing or malformed headers,
        `ERR_UNAUTHENTICATED`); role authorization (`ERR_FORBIDDEN`);
        applicant ownership (`ERR_NOT_OWNER`); resource existence; optimistic
        concurrency (`ERR_STALE_OPENING_VERSION`); state-machine guards;
        compliance gates; business-constraint gates; the temporal gate on
        service completion; and finally field-shape validation
        (`ERR_VALIDATION`)."

        Design: Difficulty/priority_pair_validation_conflict/expired_invitation_ownership_check_beats_state_check
        """
        ana, bob, app_id, inv_id, opening_id = self._expired_invitation()

        validate_error(
            api_client.decline_invitation(inv_id, make_applicant_headers(bob["id"])),
            ApiErrorId.ERR_NOT_OWNER, 403)
        validate_error(
            api_client.decline_invitation(inv_id, make_applicant_headers(ana["id"])),
            ApiErrorId.ERR_INVITATION_NOT_ACTIONABLE, 409)

        inv = validate_success(api_client.get_invitation(inv_id, PLACER), 200)
        assert inv["status"] == "EXPIRED"
        assert get_opening(opening_id)["seats_provisional"] == 0


class TestSeatConservation:
    def test_seat_conservation_accept_then_denial_rescission(self):
        """PRD §2.7: "Acceptance converts a hold into a commitment:
        `seats_provisional` is decremented and `seats_committed` incremented,
        and when the committed count reaches `seats_total` the opening
        becomes `FILLED`. The machine is cyclic — a rescission that drops the
        committed count of a `FILLED` opening back below `seats_total`
        reopens it to `OPEN`."
        PRD §3.5: "A `DENIED` determination fires the full denial cascade:
        the application's accepted invitation becomes `RESCINDED`; that
        rescission returns the application from `ACCEPTED` to `UNDER_REVIEW`
        and releases the committed seat, reopening the opening from `FILLED`
        to `OPEN` if the committed count has fallen below `seats_total`; and
        the application's legal clearance lifecycle becomes `VOID`."

        Design: Difficulty/compensating_invariant/seat_conservation_accept_then_denial_rescission
        """
        set_clock(DEFAULT_CLOCK_START)
        program, opening = create_program_with_opening(
            opening_overrides={"seats_total": 1})
        ana = create_applicant()
        bundle = run_applicant_to_evaluated(
            ana, {"country_preference_ids": [program["id"]]})

        invitation = issue_invitation(bundle["application"]["id"], opening["id"])
        after_issue = get_opening(opening["id"])
        assert (after_issue["seats_provisional"], after_issue["seats_committed"]) == (1, 0)
        assert_seat_accounting_invariants(after_issue)

        accept_invitation(invitation["id"], ana["id"])
        after_accept = get_opening(opening["id"])
        assert (after_accept["seats_provisional"], after_accept["seats_committed"]) == (0, 1)
        assert after_accept["status"] == "FILLED"
        assert_seat_accounting_invariants(after_accept)

        clearance = create_medical_clearance(
            bundle["application"]["id"], ana["id"],
            conditions=[{"condition_code": "CARDIAC_STABLE", "severity": 2,
                         "required_support_tier": 3}])
        denied = validate_success(
            api_client.determine_medical_clearance(
                clearance["id"], determine_medical_payload(determination="DENIED"),
                MEDIC), 200)
        assert denied["status"] == "DENIED"

        # The compensating cascade returns both counters to their pre-issuance
        # values and reopens the opening.
        after_denial = get_opening(opening["id"])
        assert (after_denial["seats_provisional"], after_denial["seats_committed"]) == (0, 0)
        assert after_denial["status"] == "OPEN"
        assert_seat_accounting_invariants(after_denial)
        still_accepted = validate_success(
            api_client.list_invitations(
                PLACER, params={"assignment_opening_id": opening["id"],
                                "status": "ACCEPTED"}), 200)
        assert still_accepted == [], \
            "no ACCEPTED invitations may remain after the rescission"

    def test_seat_conservation_issue_then_decline(self):
        """PRD §2.7: "Declines, expiries, and rescissions of still-`ISSUED`
        invitations simply release the hold by decrementing
        `seats_provisional`."
        PRD §2.7: "`seats_provisional` counts the opening's invitations
        currently in `ISSUED` — seats held but not yet accepted — and
        `seats_committed` counts those in `ACCEPTED`."

        Design: Difficulty/compensating_invariant/seat_conservation_accept_then_denial_rescission
        """
        set_clock(DEFAULT_CLOCK_START)
        program, opening = create_program_with_opening(
            opening_overrides={"seats_total": 1})
        ana = create_applicant()
        bundle = run_applicant_to_evaluated(
            ana, {"country_preference_ids": [program["id"]]})

        invitation = issue_invitation(bundle["application"]["id"], opening["id"])
        assert get_opening(opening["id"])["seats_provisional"] == 1

        validate_success(
            api_client.decline_invitation(
                invitation["id"], make_applicant_headers(ana["id"])), 200)
        after = get_opening(opening["id"])
        assert (after["seats_provisional"], after["seats_committed"]) == (0, 0)
        assert after["status"] == "OPEN"
        assert_seat_accounting_invariants(after)
        still_issued = validate_success(
            api_client.list_invitations(
                PLACER, params={"assignment_opening_id": opening["id"],
                                "status": "ISSUED"}), 200)
        assert still_issued == [], \
            "seats_provisional must equal the count of ISSUED invitations (0)"


class TestImmediateConsistency:
    def test_computed_fields_visible_immediately_in_write_responses(self):
        """PRD §2.2: "Unless otherwise noted, operations that create or
        modify a resource will return the created or updated resource object
        in the data field."
        PRD §3.4: "Acceptance — possible only while the invitation is
        `ISSUED`, and otherwise rejected with `ERR_INVITATION_NOT_ACTIONABLE`
        — moves it to `ACCEPTED`, converts the held seat into a committed one
        (decrementing `seats_provisional`, incrementing `seats_committed`,
        and marking the opening `FILLED` when the committed count reaches
        `seats_total`), moves the application from `INVITED` to `ACCEPTED`,
        and auto-creates the application's legal clearance with both
        dimensions `PENDING` and lifecycle `ACTIVE`."

        Design: Corner/consistency_model/computed_fields_visible_immediately_in_write_responses
        """
        set_clock(DEFAULT_CLOCK_START)
        program, opening = create_program_with_opening(
            opening_overrides={"seats_total": 2})
        ana = create_applicant()
        # Drive to INTERVIEWING.
        app = validate_success(
            api_client.create_application(
                {"applicant_id": ana["id"], "sector_preferences": ["EDUCATION"],
                 "country_preference_ids": [program["id"]]},
                make_applicant_headers(ana["id"])), 201)
        validate_success(
            api_client.submit_application(
                app["id"], make_applicant_headers(ana["id"])), 200)
        validate_success(api_client.begin_review_application(app["id"], PLACER), 200)
        interview = validate_success(
            api_client.create_interview(
                app["id"],
                {"interviewer_id": "officer-1",
                 "scheduled_start": "2026-09-05T14:00:00Z",
                 "scheduled_end": "2026-09-05T15:00:00Z"},
                PLACER), 201)

        # The complete call's own response carries the computed fields.
        completed = validate_success(
            api_client.complete_interview(
                interview["id"], complete_interview_payload(), PLACER), 200)
        assert completed["overall_score"] == pytest.approx(3.30, abs=1e-9)
        assert completed["recommendation"] == "RECOMMEND"

        invitation = issue_invitation(app["id"], opening["id"])
        # The accept call's own response shows the new state.
        accepted = validate_success(
            api_client.accept_invitation(
                invitation["id"], make_applicant_headers(ana["id"])), 200)
        assert accepted["status"] == "ACCEPTED"

        # The very next read already reflects the committed seat.
        opening_now = get_opening(opening["id"])
        assert opening_now["seats_committed"] == 1
        assert opening_now["seats_provisional"] == 0
        assert opening_now["status"] == "OPEN", \
            "two seats, one committed: the opening must not be FILLED"
