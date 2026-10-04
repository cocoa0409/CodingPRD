"""Invitation issuance: pinned snapshots, optimistic concurrency, the
opening-state gate, seat accounting boundaries, and the business gates."""

from datetime import datetime

import pytest

from test_helpers import (
    ApiErrorId,
    CLOCK_AFTER_ISSUE_DEADLINE,
    DEFAULT_CLOCK_START,
    TEST_USERS,
    api_client,
    assert_invitation,
    create_applicant,
    create_assignment_opening,
    create_country_program,
    create_invitation_payload,
    create_program_with_opening,
    get_application,
    get_opening,
    issue_invitation,
    run_applicant_to_accepted,
    run_applicant_to_evaluated,
    set_clock,
    PLACEMENT_OFFICER_ID,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
PLACER = TEST_USERS["placement_officer_headers"]


def _ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class TestIssuanceSnapshots:
    def test_invitation_pins_snapshot_fields_at_issuance(self):
        """PRD §2.6: "When an invitation is issued, three facts are
        snapshotted onto it and never change again: `pinned_country_program_id`
        identifies the program hosting the assignment,
        `pinned_country_medical_tier` records the program's medical support
        tier at issuance, and `pinned_departure_date` records the opening's
        planned departure date. The invitation also stamps `issued_at` from
        the logical clock, records the issuing officer in `issued_by`, and
        sets its `acceptance_deadline` exactly ten days after `issued_at`."

        Design: Corner/cross_cutting_layers/invitation_pins_snapshot_fields_at_issuance
        """
        set_clock(DEFAULT_CLOCK_START)
        program, opening = create_program_with_opening(
            program_overrides={"medical_support_tier": 3})
        ana = create_applicant()
        bundle = run_applicant_to_evaluated(
            ana, {"country_preference_ids": [program["id"]]})
        version = get_opening(opening["id"])["version"]
        resp = api_client.create_invitation(
            create_invitation_payload(
                bundle["application"]["id"], opening["id"], version),
            PLACER)
        invitation = validate_success(resp, 201)
        assert_invitation(invitation)
        assert invitation["status"] == "ISSUED"
        assert invitation["issued_by"] == PLACEMENT_OFFICER_ID, \
            "issued_by records the issuing officer's X-User-ID"
        assert invitation["pinned_country_program_id"] == program["id"]
        assert invitation["pinned_country_medical_tier"] == 3
        assert _ts(invitation["pinned_departure_date"]) == _ts("2027-01-15T00:00:00Z")
        assert _ts(invitation["issued_at"]) == _ts(DEFAULT_CLOCK_START)
        assert _ts(invitation["acceptance_deadline"]) == _ts("2026-09-11T00:00:00Z"), \
            "acceptance_deadline is exactly ten days after issued_at"


class TestOptimisticConcurrency:
    def test_occ_stale_version_rejected_then_retry_succeeds(self):
        """PRD §2.8: "The request must carry
        `expected_assignment_opening_version`, holding the `version` of the
        target assignment opening as the issuing officer last observed it. If
        that value does not match the opening's current `version`, the
        issuance is rejected with `ERR_STALE_OPENING_VERSION` (HTTP 412)."
        PRD §2.8: "the officer must re-read the opening and retry with the
        fresh version."
        PRD §2.5: "With one exception, every resource also carries
        `updated_at` — refreshed on any change to the resource — and
        `version`, an integer that increments on every mutation, including
        mutations performed by system cascades rather than by a direct client
        write on that resource."

        Design: Corner/cross_cutting_layers/occ_stale_version_rejected_then_retry_succeeds
        """
        set_clock(DEFAULT_CLOCK_START)
        program, opening = create_program_with_opening()
        stale_version = opening["version"]

        ana = create_applicant()
        bundle_a = run_applicant_to_evaluated(
            ana, {"country_preference_ids": [program["id"]]})
        bob = create_applicant()
        bundle_b = run_applicant_to_evaluated(
            bob, {"country_preference_ids": [program["id"]]})

        # Ana's issuance against the observed version succeeds.
        resp_a = api_client.create_invitation(
            create_invitation_payload(
                bundle_a["application"]["id"], opening["id"], stale_version),
            PLACER)
        validate_success(resp_a, 201)
        after_ana = get_opening(opening["id"])
        assert after_ana["version"] > stale_version, \
            "every mutation increments the opening's version"
        assert after_ana["seats_provisional"] == 1

        # Bob's issuance against the stale version is rejected (412) and
        # leaves no trace.
        validate_error(
            api_client.create_invitation(
                create_invitation_payload(
                    bundle_b["application"]["id"], opening["id"], stale_version),
                PLACER),
            ApiErrorId.ERR_STALE_OPENING_VERSION, 412)
        rejected = get_opening(opening["id"])
        assert rejected["version"] == after_ana["version"], \
            "a rejected issuance must not mutate the opening"
        assert rejected["seats_provisional"] == 1

        # Re-read and retry with the fresh version: succeeds.
        resp_b = api_client.create_invitation(
            create_invitation_payload(
                bundle_b["application"]["id"], opening["id"],
                rejected["version"]),
            PLACER)
        invitation_b = validate_success(resp_b, 201)
        assert invitation_b["status"] == "ISSUED"
        assert get_opening(opening["id"])["seats_provisional"] == 2


class TestOpeningStateGate:
    def test_issuance_rejected_when_opening_closed_by_sweep(self):
        """PRD §2.4: "Every assignment opening still `OPEN` whose
        `invitation_issue_deadline` is strictly earlier than the new reading
        becomes `CLOSED`."
        PRD §3.4: "The application must be `EVALUATED`, failing with
        `ERR_INVALID_APPLICATION_STATE` from any other state, and five
        business gates then apply: the opening must be `OPEN`
        (`ERR_OPENING_NOT_OPEN`); the applicant's strict coverage of its
        required skills must be exactly 1.0 (`ERR_SKILL_REQUIREMENTS_NOT_MET`);
        the application's latest completed interview must carry a `RECOMMEND`
        or `STRONGLY_RECOMMEND` recommendation
        (`ERR_RECOMMENDATION_INSUFFICIENT`); the opening's program must be
        compatible with the applicant's country preferences — automatic when
        the list is empty, otherwise the program must appear in it
        (`ERR_PREFERENCE_MISMATCH`); and a seat must remain
        (`ERR_NO_SEATS_AVAILABLE`)."

        Design: Difficulty/cross_entity_state_dependency/invitation_issuance_gated_by_opening_state
        """
        set_clock(DEFAULT_CLOCK_START)
        program, opening = create_program_with_opening()
        ana = create_applicant()
        bundle = run_applicant_to_evaluated(
            ana, {"country_preference_ids": [program["id"]]})

        set_clock(CLOCK_AFTER_ISSUE_DEADLINE)
        swept = get_opening(opening["id"])
        assert swept["status"] == "CLOSED", \
            "the sweep closes an OPEN opening past its issue deadline"

        # OCC passes (fresh version); the rejection comes from the state gate.
        validate_error(
            api_client.create_invitation(
                create_invitation_payload(
                    bundle["application"]["id"], opening["id"],
                    swept["version"]),
                PLACER),
            ApiErrorId.ERR_OPENING_NOT_OPEN, 409)
        assert get_application(bundle["application"]["id"])["status"] == "EVALUATED"
        assert get_opening(opening["id"])["seats_provisional"] == 0

    def test_issuance_rejected_when_opening_cancelled(self):
        """PRD §2.9: "State-machine guards run sixth, each with its dedicated
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

        Design: Difficulty/cross_entity_state_dependency/invitation_issuance_gated_by_opening_state
        """
        set_clock(DEFAULT_CLOCK_START)
        program, opening = create_program_with_opening()
        ana = create_applicant()
        bundle = run_applicant_to_evaluated(
            ana, {"country_preference_ids": [program["id"]]})

        cancelled = validate_success(
            api_client.cancel_assignment_opening(opening["id"], ADMIN), 200)
        assert cancelled["status"] == "CANCELLED"

        fresh = get_opening(opening["id"])
        validate_error(
            api_client.create_invitation(
                create_invitation_payload(
                    bundle["application"]["id"], opening["id"], fresh["version"]),
                PLACER),
            ApiErrorId.ERR_OPENING_NOT_OPEN, 409)
        assert get_application(bundle["application"]["id"])["status"] == "EVALUATED"


class TestSeatBoundaries:
    def test_last_provisional_seat_blocks_second_issuance(self):
        """PRD §2.7: "Both counters start at zero, and issuance is only
        possible while the sum of held and committed seats remains strictly
        below `seats_total`."
        PRD §3.4: "The application must be `EVALUATED`, failing with
        `ERR_INVALID_APPLICATION_STATE` from any other state, and five
        business gates then apply: the opening must be `OPEN`
        (`ERR_OPENING_NOT_OPEN`); the applicant's strict coverage of its
        required skills must be exactly 1.0 (`ERR_SKILL_REQUIREMENTS_NOT_MET`);
        the application's latest completed interview must carry a `RECOMMEND`
        or `STRONGLY_RECOMMEND` recommendation
        (`ERR_RECOMMENDATION_INSUFFICIENT`); the opening's program must be
        compatible with the applicant's country preferences — automatic when
        the list is empty, otherwise the program must appear in it
        (`ERR_PREFERENCE_MISMATCH`); and a seat must remain
        (`ERR_NO_SEATS_AVAILABLE`)."

        Design: Difficulty/boundary_precision_check/last_provisional_seat_blocks_second_issuance
        """
        set_clock(DEFAULT_CLOCK_START)
        program, opening = create_program_with_opening(
            opening_overrides={"seats_total": 1})
        ana = create_applicant()
        bundle_a = run_applicant_to_evaluated(
            ana, {"country_preference_ids": [program["id"]]})
        # First issuance: sum 0 < 1, allowed (open side of the boundary).
        issue_invitation(bundle_a["application"]["id"], opening["id"])
        assert get_opening(opening["id"])["seats_provisional"] == 1

        bob = create_applicant()
        bundle_b = run_applicant_to_evaluated(
            bob, {"country_preference_ids": [program["id"]]})
        # Second issuance: sum 1 >= 1, rejected.
        validate_error(
            api_client.create_invitation(
                create_invitation_payload(
                    bundle_b["application"]["id"], opening["id"],
                    get_opening(opening["id"])["version"]),
                PLACER),
            ApiErrorId.ERR_NO_SEATS_AVAILABLE, 409)
        after = get_opening(opening["id"])
        assert after["seats_provisional"] == 1
        assert after["seats_committed"] == 0
        assert get_application(bundle_b["application"]["id"])["status"] == "EVALUATED"

    def test_held_plus_committed_sum_blocks_issuance(self):
        """PRD §2.7: "`seats_provisional` counts the opening's invitations
        currently in `ISSUED` — seats held but not yet accepted — and
        `seats_committed` counts those in `ACCEPTED`. Both counters start at
        zero, and issuance is only possible while the sum of held and
        committed seats remains strictly below `seats_total`."

        Design: Difficulty/boundary_precision_check/last_provisional_seat_blocks_second_issuance
        """
        set_clock(DEFAULT_CLOCK_START)
        program, opening = create_program_with_opening(
            opening_overrides={"seats_total": 2})
        # One committed seat (accepted) and one held seat (issued): sum == 2.
        ana = create_applicant()
        run_applicant_to_accepted(ana, opening)
        assert get_opening(opening["id"])["seats_committed"] == 1

        carol = create_applicant()
        bundle_c = run_applicant_to_evaluated(
            carol, {"country_preference_ids": [program["id"]]})
        issue_invitation(bundle_c["application"]["id"], opening["id"])
        held = get_opening(opening["id"])
        assert held["seats_provisional"] == 1
        assert held["seats_committed"] == 1
        assert held["status"] == "OPEN"

        # The sum (not just the provisional count) gates the next issuance.
        bob = create_applicant()
        bundle_b = run_applicant_to_evaluated(
            bob, {"country_preference_ids": [program["id"]]})
        validate_error(
            api_client.create_invitation(
                create_invitation_payload(
                    bundle_b["application"]["id"], opening["id"],
                    get_opening(opening["id"])["version"]),
                PLACER),
            ApiErrorId.ERR_NO_SEATS_AVAILABLE, 409)
        assert get_application(bundle_b["application"]["id"])["status"] == "EVALUATED"


class TestIssuanceBusinessGates:
    def test_skill_requirements_not_met_blocks_invitation(self):
        """PRD §3.4: "The application must be `EVALUATED`, failing with
        `ERR_INVALID_APPLICATION_STATE` from any other state, and five
        business gates then apply: the opening must be `OPEN`
        (`ERR_OPENING_NOT_OPEN`); the applicant's strict coverage of its
        required skills must be exactly 1.0 (`ERR_SKILL_REQUIREMENTS_NOT_MET`);
        the application's latest completed interview must carry a `RECOMMEND`
        or `STRONGLY_RECOMMEND` recommendation
        (`ERR_RECOMMENDATION_INSUFFICIENT`); the opening's program must be
        compatible with the applicant's country preferences — automatic when
        the list is empty, otherwise the program must appear in it
        (`ERR_PREFERENCE_MISMATCH`); and a seat must remain
        (`ERR_NO_SEATS_AVAILABLE`)."

        Design: Corner/validations/skill_requirements_not_met_blocks_invitation
        """
        set_clock(DEFAULT_CLOCK_START)
        program, opening = create_program_with_opening()  # requires TEACHING_ENGLISH
        ana = create_applicant(skills=["NURSING"])
        bundle = run_applicant_to_evaluated(
            ana, {"country_preference_ids": [program["id"]]})

        validate_error(
            api_client.create_invitation(
                create_invitation_payload(
                    bundle["application"]["id"], opening["id"],
                    get_opening(opening["id"])["version"]),
                PLACER),
            ApiErrorId.ERR_SKILL_REQUIREMENTS_NOT_MET, 422)
        assert get_application(bundle["application"]["id"])["status"] == "EVALUATED"
        assert get_opening(opening["id"])["seats_provisional"] == 0

    def test_neutral_recommendation_blocks_invitation(self):
        """PRD §3.4: "The application must be `EVALUATED`, failing with
        `ERR_INVALID_APPLICATION_STATE` from any other state, and five
        business gates then apply: the opening must be `OPEN`
        (`ERR_OPENING_NOT_OPEN`); the applicant's strict coverage of its
        required skills must be exactly 1.0 (`ERR_SKILL_REQUIREMENTS_NOT_MET`);
        the application's latest completed interview must carry a `RECOMMEND`
        or `STRONGLY_RECOMMEND` recommendation
        (`ERR_RECOMMENDATION_INSUFFICIENT`); the opening's program must be
        compatible with the applicant's country preferences — automatic when
        the list is empty, otherwise the program must appear in it
        (`ERR_PREFERENCE_MISMATCH`); and a seat must remain
        (`ERR_NO_SEATS_AVAILABLE`)."
        PRD §3.3: "Otherwise an `overall_score` of at least 4.0 earns
        `STRONGLY_RECOMMEND`, at least 3.0 earns `RECOMMEND`, at least 2.5
        earns `NEUTRAL`, and anything below that earns `NOT_RECOMMENDED`."

        Design: Corner/validations/neutral_recommendation_blocks_invitation
        """
        set_clock(DEFAULT_CLOCK_START)
        program, opening = create_program_with_opening()
        ana = create_applicant()
        bundle = run_applicant_to_evaluated(
            ana,
            {"country_preference_ids": [program["id"]]},
            complete_overrides={
                "motivation_score": 3.0, "adaptability_score": 3.0,
                "skill_competency_score": 3.0, "cross_cultural_score": 2.0,
            },
        )
        interview = validate_success(
            api_client.list_interviews(bundle["application"]["id"], PLACER), 200
        )[0]
        # 0.30*3 + 0.25*3 + 0.25*3 + 0.20*2 = 2.80; min dimension 2.0 not < 2.0.
        assert interview["overall_score"] == pytest.approx(2.80, abs=1e-9)
        assert interview["recommendation"] == "NEUTRAL"

        validate_error(
            api_client.create_invitation(
                create_invitation_payload(
                    bundle["application"]["id"], opening["id"],
                    get_opening(opening["id"])["version"]),
                PLACER),
            ApiErrorId.ERR_RECOMMENDATION_INSUFFICIENT, 422)
        assert get_application(bundle["application"]["id"])["status"] == "EVALUATED"
        assert get_opening(opening["id"])["seats_provisional"] == 0

    def test_country_preference_mismatch_blocks_invitation(self):
        """PRD §3.4: "The application must be `EVALUATED`, failing with
        `ERR_INVALID_APPLICATION_STATE` from any other state, and five
        business gates then apply: the opening must be `OPEN`
        (`ERR_OPENING_NOT_OPEN`); the applicant's strict coverage of its
        required skills must be exactly 1.0 (`ERR_SKILL_REQUIREMENTS_NOT_MET`);
        the application's latest completed interview must carry a `RECOMMEND`
        or `STRONGLY_RECOMMEND` recommendation
        (`ERR_RECOMMENDATION_INSUFFICIENT`); the opening's program must be
        compatible with the applicant's country preferences — automatic when
        the list is empty, otherwise the program must appear in it
        (`ERR_PREFERENCE_MISMATCH`); and a seat must remain
        (`ERR_NO_SEATS_AVAILABLE`)."

        Design: Corner/validations/country_preference_mismatch_blocks_invitation
        """
        set_clock(DEFAULT_CLOCK_START)
        prog_pe = create_country_program(country_code="PE", name="Peru")
        prog_ec = create_country_program(country_code="EC", name="Ecuador",
                                         medical_support_tier=2)
        opening = create_assignment_opening(prog_pe["id"])
        ana = create_applicant()
        # Preferences list only EC; the opening sits in PE.
        bundle = run_applicant_to_evaluated(
            ana, {"country_preference_ids": [prog_ec["id"]]})

        validate_error(
            api_client.create_invitation(
                create_invitation_payload(
                    bundle["application"]["id"], opening["id"],
                    get_opening(opening["id"])["version"]),
                PLACER),
            ApiErrorId.ERR_PREFERENCE_MISMATCH, 422)
        assert get_application(bundle["application"]["id"])["status"] == "EVALUATED"
        assert get_opening(opening["id"])["seats_provisional"] == 0
