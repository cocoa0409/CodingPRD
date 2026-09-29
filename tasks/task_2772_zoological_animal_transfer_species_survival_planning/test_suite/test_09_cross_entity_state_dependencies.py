"""Gates that live on a sibling entity the acting row only references."""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (ERR_INSTITUTION_NOT_ACCREDITED,
                                     ERR_QUARANTINE_NOT_SCHEDULED,
                                     ERR_VET_LICENSE_INVALID)
from test_helpers.test_users import make_vet_headers


def _offered(api, receiver_overrides=None):
    world = fx.base_pair(api, receiver_overrides=receiver_overrides)
    fx.endorsed_recommendation(world)
    fx.draft_agreement(world)
    fx.offered_agreement(world)
    return world


class TestAcceptGatedOnReceivingAccreditation:
    """Acceptance reads the receiving institution's standing, not its own fields."""

    def test_a_suspended_receiver_cannot_accept_the_standing_offer(self, api):
        """The agreement's own fields are valid yet the accept is refused.

        PRD: "Two further conditions hold at acceptance: the receiving
        institution's `accreditation_status` must be `ACCREDITED` or
        `PROVISIONAL`, else `ERR_INSTITUTION_NOT_ACCREDITED`, and the founding
        recommendation must still be `ENDORSED`, else
        `ERR_RECOMMENDATION_NOT_ENDORSED`."

        Design: Difficulty/cross_entity_state_dependency/accept_gated_on_receiving_institution_accreditation
        """
        world = _offered(api)
        validate_success(
            api.patch_institution(world.receiver_id,
                                  {"accreditation_status": "SUSPENDED"},
                                  world.admin)
        )
        response = api.accept_agreement(world.ta_id, world.receiver,
                                        {"acceptance_note": "Terms accepted"})
        validate_error(response, ERR_INSTITUTION_NOT_ACCREDITED)
        agreement = world.read_agreement()
        assert agreement["status"] == "OFFERED"
        assert agreement["round_number"] == 1

    def test_the_identical_call_succeeds_against_an_accredited_receiver(self, api):
        """Nothing about the agreement row differs, only the sibling institution.

        PRD: "The party that did **not** act last accepts the terms standing on
        the table, moving the agreement from `OFFERED` or from `COUNTERED` to
        `ACCEPTED`, optionally recording an `acceptance_note`."

        Design: Difficulty/cross_entity_state_dependency/accept_gated_on_receiving_institution_accreditation
        """
        world = _offered(api)
        assert world.read_institution(world.receiver_id)["accreditation_status"] \
            == "ACCREDITED"
        data = validate_success(
            api.accept_agreement(world.ta_id, world.receiver,
                                 {"acceptance_note": "Terms accepted"})
        )
        assert data["status"] == "ACCEPTED"
        assert data["round_number"] == 1

    def test_a_provisional_receiver_still_holds_live_accreditation(self, api):
        """Provisional standing is live standing for the purposes of acceptance.

        PRD: "From `ACCREDITED` an institution may be moved to `PROVISIONAL`, and
        any institution that is not already `TERMINATED` may be placed on
        provisional standing."

        Design: Difficulty/cross_entity_state_dependency/accept_gated_on_receiving_institution_accreditation
        """
        world = _offered(api)
        validate_success(
            api.patch_institution(world.receiver_id,
                                  {"accreditation_status": "PROVISIONAL"},
                                  world.admin)
        )
        data = validate_success(
            api.accept_agreement(world.ta_id, world.receiver,
                                 {"acceptance_note": "Terms accepted"})
        )
        assert data["status"] == "ACCEPTED"


class TestCertificateGatedOnSigningVetLicence:
    """A veterinarian's licence state decides whether a document may leave DRAFT."""

    @staticmethod
    def _world_with_panel(api):
        world = fx.world_with_executed_agreement(api)
        world.set_clock(fx.CLOCK_DOCUMENTS)
        fx.record_panel(world, collected_on="2026-08-15")
        return world

    def test_a_lapsed_signature_cannot_move_the_document_out_of_draft(self, api):
        """Dr D Fell's lapsed licence leaves the certificate in DRAFT with no window.

        PRD: "The signing veterinarian's `license_status` must be `ACTIVE` and
        their `license_jurisdiction` must match the sending institution's
        `jurisdiction_code`, else `ERR_VET_LICENSE_INVALID`."

        Design: Difficulty/cross_entity_state_dependency/certificate_issue_gated_on_signing_vet_license_state
        """
        world = self._world_with_panel(api)
        fx.open_certificate(world, issuing_veterinarian_id=world.vet_d_id,
                            exam_date="2026-08-20")
        lapsed_id = world.cvi_id
        response = api.decide_document(
            lapsed_id,
            f.document_decision_payload(outcome="ISSUE",
                                        document_number="CVI-2026-0031"),
            make_vet_headers(world.vet_d_id),
        )
        validate_error(response, ERR_VET_LICENSE_INVALID)
        document = world.read_document(lapsed_id)
        assert document["status"] == "DRAFT"
        assert document["valid_until"] is None
        assert document["document_number"] is None

    def test_an_active_signature_on_the_identical_document_issues_it(self, api):
        """Dr B Sund signs the same panel and agreement, and the window is filled.

        PRD: "an `INTERSTATE_CVI` may be decided only by a `Veterinarian`, and
        only by the very veterinarian the document names in
        `issuing_veterinarian_id`, while every permit type may be decided only by
        an `AccreditationAdmin`."

        Design: Difficulty/cross_entity_state_dependency/certificate_issue_gated_on_signing_vet_license_state
        """
        world = self._world_with_panel(api)
        fx.open_certificate(world, issuing_veterinarian_id=world.vet_b_id,
                            exam_date="2026-08-20")
        data = validate_success(
            api.decide_document(
                world.cvi_id,
                f.document_decision_payload(outcome="ISSUE",
                                            document_number="CVI-2026-0032"),
                make_vet_headers(world.vet_b_id),
            )
        )
        assert data["status"] == "ISSUED"
        assert data["issuing_veterinarian_id"] == world.vet_b_id
        assert str(data["valid_until"]).startswith("2026-09-19")


class TestConfirmGatedOnScheduledQuarantine:
    """Confirmation waits on a room the booking does not reference at all."""

    def test_a_booking_cannot_be_confirmed_without_a_room_at_the_receiver(
            self, api):
        """Every document gate is satisfied, so only the missing room is reported.

        PRD: "a `SCHEDULED` quarantine occupancy waiting at the receiving
        institution for this agreement (`ERR_QUARANTINE_NOT_SCHEDULED`)"

        Design: Difficulty/cross_entity_state_dependency/booking_confirm_gated_on_scheduled_quarantine_at_receiver
        """
        world = fx.world_ready_to_confirm(api, with_quarantine=False)
        response = api.confirm_booking(world.booking_id, world.sender,
                                       {"confirmation_note": "First attempt"})
        validate_error(response, ERR_QUARANTINE_NOT_SCHEDULED)
        assert world.read_booking()["status"] == "RESERVED"

    def test_reserving_the_room_opens_the_gate_for_the_same_call(self, api):
        """A SCHEDULED occupancy at the receiver lets the identical confirm through.

        PRD: "An occupancy opens with `phase` at `SCHEDULED`, `isolation_class` at
        `STANDARD`, `required_days` at 30, and `actual_start_date`, `cleared_on`
        and `clearing_veterinarian_id` all null."

        Design: Difficulty/cross_entity_state_dependency/booking_confirm_gated_on_scheduled_quarantine_at_receiver
        """
        world = fx.world_ready_to_confirm(api, with_quarantine=False)
        validate_error(
            api.confirm_booking(world.booking_id, world.sender,
                                {"confirmation_note": "First attempt"}),
            ERR_QUARANTINE_NOT_SCHEDULED,
        )
        occupancy = fx.schedule_quarantine(world)
        assert occupancy["phase"] == "SCHEDULED"
        assert occupancy["institution_id"] == world.receiver_id
        assert occupancy["actual_start_date"] is None
        data = validate_success(
            api.confirm_booking(world.booking_id, world.sender,
                                {"confirmation_note": "Second attempt"})
        )
        assert data["status"] == "CONFIRMED"
