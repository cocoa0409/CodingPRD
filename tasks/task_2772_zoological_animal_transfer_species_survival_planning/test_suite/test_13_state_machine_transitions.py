"""Initial states, guarded transitions, turn-taking and terminal lockdown."""

from __future__ import annotations

from prd_bench_local_runner.testing import (validate_error, validate_paginated,
                                            validate_success)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (ERR_AGREEMENT_INVALID_STATE,
                                     ERR_NOT_COUNTERPARTY_TURN,
                                     ERR_PROGRAM_PLAN_NOT_PUBLISHED,
                                     ERR_RECOMMENDATION_EXPIRED,
                                     ERR_RECOMMENDATION_NOT_ENDORSED)


def _draft_world(api):
    world = fx.base_pair(api)
    fx.endorsed_recommendation(world)
    fx.draft_agreement(world)
    return world


def _unpublished_world_with_animal(api):
    world = fx.base_world(api, publish=False)
    animal = fx.accession(world, world.sender_id, "CR-101", "MALE",
                          "2019-05-10", 12.45)
    world.m1_id, world.m1_version = animal["id"], animal["version"]
    return world


def _hold_recommendation(world, **overrides):
    return fx.propose_recommendation(world, recommendation_type="HOLD",
                                     paired_animal_id=None, **overrides)


class TestAgreementInitialState:
    """A founded agreement has negotiated nothing and been valued at nothing."""

    def test_a_founded_agreement_opens_in_draft_with_no_negotiation_history(
            self, api):
        """round_number is 0, the last actor is null and both valuations are null.

        PRD: "A new agreement opens with `status` at `DRAFT`, `round_number` at 0,
        `last_action_institution_id` null, and both `provisional_credit_points`
        and `final_credit_points` null."

        Design: Corner/state_machines/transfer_agreement_initial_state_is_draft
        """
        world = fx.base_pair(api)
        fx.endorsed_recommendation(world)
        data = fx.draft_agreement(world)
        assert data["status"] == "DRAFT"
        assert data["round_number"] == 0
        assert data["last_action_institution_id"] is None
        assert data["provisional_credit_points"] is None
        assert data["final_credit_points"] is None
        assert data["executed_at"] is None
        assert data["version"] == 1

    def test_the_scope_is_derived_from_the_two_jurisdiction_codes(self, api):
        """A Californian sender and a Texan receiver make the transfer INTERSTATE.

        PRD: "So `US-CA` to `US-CA` is intra-jurisdiction, `US-CA` to `US-TX` is
        interstate, and `US-CA` to `CA-ON` is international."

        Design: Corner/state_machines/transfer_agreement_initial_state_is_draft
        """
        world = _draft_world(api)
        assert world.read_agreement()["transfer_scope"] == "INTERSTATE"


class TestPlanPublication:
    """Publication is the gate that lets directives exist at all."""

    def test_publishing_keeps_the_first_cycle_and_unlocks_recommendations(
            self, api):
        """plan_status becomes PUBLISHED, the cycle stays 1 and a directive lands.

        PRD: "A first publication out of `DRAFT` leaves `current_plan_cycle` at 1."

        Design: Corner/state_machines/publish_plan_moves_program_to_published_and_unlocks_recommendations
        """
        world = _unpublished_world_with_animal(api)
        published = validate_success(
            api.publish_plan(world.program_id, world.coordinator)
        )
        assert published["plan_status"] == "PUBLISHED"
        assert published["current_plan_cycle"] == 1
        assert published["cycle_closed_on"] is None
        assert published["version"] == 2

        recommendation = _hold_recommendation(world)
        assert recommendation["status"] == "PROPOSED"
        assert recommendation["plan_cycle"] == 1
        program = world.read_program()
        assert program["open_recommendation_count"] == 1
        assert program["plan_status"] == "PUBLISHED"

    def test_a_directive_against_an_unpublished_plan_is_refused(self, api):
        """A perfectly valid body is still refused while the plan sits at DRAFT.

        PRD: "Raising a recommendation against a programme whose `plan_status` is
        `DRAFT` or `CYCLE_CLOSED` is refused with `ERR_PROGRAM_PLAN_NOT_PUBLISHED`
        (HTTP 409)."

        Design: Corner/state_machines/create_recommendation_before_publish_returns_plan_not_published
        """
        world = _unpublished_world_with_animal(api)
        response = api.create_recommendation(
            f.recommendation_payload(world.program_id, world.m1_id,
                                     world.m1_version,
                                     recommendation_type="HOLD"),
            world.coordinator,
        )
        validate_error(response, ERR_PROGRAM_PLAN_NOT_PUBLISHED)
        _, meta = validate_paginated(api.list_recommendations(world.admin))
        assert meta["total_count"] == 0
        animal = world.read_animal()
        assert animal["pending_recommendation_id"] is None
        assert animal["version"] == 1


class TestInvalidAgreementTransitions:
    """Acceptance is not a shortcut out of DRAFT."""

    def test_accepting_a_never_offered_agreement_is_a_state_conflict(self, api):
        """The DRAFT row admits no accept, so nothing about it moves.

        PRD: "Attempting a negotiation act from a status that does not admit it —
        countering a `DRAFT` agreement, offering on an `ACCEPTED` one — is refused
        with `ERR_AGREEMENT_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/accept_on_draft_agreement_returns_agreement_invalid_state
        """
        world = _draft_world(api)
        response = api.accept_agreement(world.ta_id, world.receiver,
                                        {"acceptance_note": "we agree"})
        validate_error(response, ERR_AGREEMENT_INVALID_STATE)
        agreement = world.read_agreement()
        assert agreement["status"] == "DRAFT"
        assert agreement["round_number"] == 0
        assert agreement["version"] == 1


class TestTurnTaking:
    """One party alone cannot advance the round counter."""

    def test_the_offering_party_may_not_counter_its_own_standing_terms(self, api):
        """The sender's counter on its own OFFERED agreement is refused.

        PRD: "Turn-taking is enforced on every negotiation act other than the
        opening offer: the acting institution must not be the agreement's current
        `last_action_institution_id`."

        Design: Corner/state_machines/counter_by_offering_party_returns_not_counterparty_turn
        """
        world = _draft_world(api)
        fx.offered_agreement(world)
        response = api.counter_agreement(world.ta_id, world.sender,
                                         f.terms_payload(20.0))
        validate_error(response, ERR_NOT_COUNTERPARTY_TURN)
        agreement = world.read_agreement()
        assert agreement["status"] == "OFFERED"
        assert agreement["round_number"] == 1
        assert agreement["last_action_institution_id"] == world.sender_id
        assert float(agreement["transport_cost_share_pct"]) == 51.0


class TestTerminalLockdown:
    """TERMINATED admits no further trigger and keeps its first reason."""

    def test_a_second_termination_is_refused_and_the_first_reason_stands(
            self, api):
        """The reason recorded by the receiver survives the sender's later attempt.

        PRD: "Termination is available from `OFFERED`, `COUNTERED`, `ACCEPTED` and
        `EXECUTED`; a `DRAFT` agreement that has never been offered, and one
        already `COMPLETED` or `TERMINATED`, cannot be terminated and the attempt
        is refused with `ERR_AGREEMENT_INVALID_STATE`."

        Design: Corner/state_machines/terminate_twice_locks_the_terminated_agreement
        """
        world = _draft_world(api)
        fx.offered_agreement(world)
        first = validate_success(
            api.terminate_agreement(world.ta_id, world.receiver,
                                    f.termination_payload("receiver withdrew"))
        )
        assert first["status"] == "TERMINATED"
        assert first["termination_reason"] == "receiver withdrew"

        response = api.terminate_agreement(
            world.ta_id, world.sender,
            f.termination_payload("second thoughts"),
        )
        validate_error(response, ERR_AGREEMENT_INVALID_STATE)
        agreement = world.read_agreement()
        assert agreement["termination_reason"] == "receiver withdrew"
        assert world.read_animal()["location_status"] == "HELD"


class TestEndorsementIsNotIdempotent:
    """Only a PROPOSED directive can be endorsed."""

    def test_a_second_endorsement_of_the_same_directive_is_refused(self, api):
        """The already-ENDORSED row is left exactly as the first endorsement made it.

        PRD: "Only a `PROPOSED` recommendation can be endorsed; an attempt against
        one that has already been endorsed, fulfilled, declined, superseded or
        expired is refused with `ERR_RECOMMENDATION_NOT_ENDORSED` (HTTP 409)."

        Design: Corner/state_machines/endorse_same_recommendation_twice_returns_recommendation_not_endorsed
        """
        world = _unpublished_world_with_animal(api)
        validate_success(api.publish_plan(world.program_id, world.coordinator))
        _hold_recommendation(world)
        first = validate_success(
            api.endorse_recommendation(world.rec_id, world.sender,
                                       {"endorsement_note": "first"})
        )
        assert first["status"] == "ENDORSED"
        endorsed_version = first["version"]
        designation = world.read_animal()["genetic_designation"]
        assert designation == "HOLD_NO_BREED"

        response = api.endorse_recommendation(world.rec_id, world.sender,
                                              {"endorsement_note": "again"})
        validate_error(response, ERR_RECOMMENDATION_NOT_ENDORSED)
        recommendation = world.read_recommendation()
        assert recommendation["status"] == "ENDORSED"
        assert recommendation["version"] == endorsed_version
        program = world.read_program()
        assert program["open_recommendation_count"] == 1
        assert program["plan_status"] == "PUBLISHED"


class TestDisplacementOfAStandingDirective:
    """A newer directive for the same animal and cycle supersedes the older one."""

    def test_the_second_proposal_supersedes_the_first_and_repoints_the_animal(
            self, api):
        """The first row goes SUPERSEDED and the animal points at the newer row.

        PRD: "Any recommendation for the same `subject_animal_id` in the same
        `plan_cycle` that is still `PROPOSED` moves to `SUPERSEDED`, and the
        subject animal's `pending_recommendation_id` is repointed at the newer
        recommendation."

        Design: Corner/state_machines/newer_recommendation_supersedes_the_standing_proposed_one
        """
        world = _unpublished_world_with_animal(api)
        validate_success(api.publish_plan(world.program_id, world.coordinator))
        first = _hold_recommendation(world, priority_rank=3)
        second = _hold_recommendation(world, priority_rank=1)

        assert world.read_recommendation(first["id"])["status"] == "SUPERSEDED"
        assert second["status"] == "PROPOSED"
        assert second["plan_cycle"] == 1
        assert world.read_animal()["pending_recommendation_id"] == second["id"]
        program = world.read_program()
        assert program["open_recommendation_count"] == 1
        assert program["plan_status"] == "PUBLISHED"
        assert program["cycle_closed_on"] is None


class TestLapseIsRecordedNotMerelyReported:
    """A failing endorsement still commits the expiry it discovered."""

    def test_endorsing_after_the_expiry_date_persists_the_expired_status(
            self, api):
        """The request fails and yet the directive is left EXPIRED and unpointed.

        PRD: "The lapse is recorded rather than merely reported — the
        recommendation's `status` becomes `EXPIRED` and the subject animal's
        `pending_recommendation_id` is cleared to null, both persisted, and only
        then does the request itself fail with `ERR_RECOMMENDATION_EXPIRED` (HTTP
        422)."

        Design: Corner/state_machines/expired_recommendation_endorse_persists_expiry_then_fails
        """
        world = _unpublished_world_with_animal(api)
        validate_success(api.publish_plan(world.program_id, world.coordinator))
        _hold_recommendation(world, expires_on="2026-08-05")
        world.set_clock("2026-08-06T09:00:00Z")

        response = api.endorse_recommendation(world.rec_id, world.sender)
        validate_error(response, ERR_RECOMMENDATION_EXPIRED)
        assert world.read_recommendation()["status"] == "EXPIRED"
        assert world.read_animal()["pending_recommendation_id"] is None
        program = world.read_program()
        assert program["open_recommendation_count"] == 0
        assert program["plan_status"] == "CYCLE_CLOSED"
        assert str(program["cycle_closed_on"]).startswith("2026-08-06T09:00:00")
