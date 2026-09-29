"""The rejection ladder: the higher rung is reported when two defects coexist."""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (ERR_AGREEMENT_INVALID_STATE,
                                     ERR_HEALTH_CERTIFICATE_EXPIRED,
                                     ERR_INSTITUTION_NOT_ACCREDITED,
                                     ERR_PERMIT_NOT_ISSUED)


class TestExecuteStateOutranksAccreditation:
    """A wrong agreement status is reported ahead of a suspended receiver."""

    def test_the_state_defect_is_reported_and_the_accreditation_defect_is_not(
            self, api):
        """An OFFERED agreement with a SUSPENDED receiver answers on state alone.

        PRD: "Where more than one condition holds on a single request, the
        precedence ladder of §2.9 decides which of them is reported."

        Design: Difficulty/priority_pair_validation_conflict/execute_state_50_outranks_accreditation_60
        """
        world = fx.base_pair(api)
        fx.endorsed_recommendation(world)
        fx.draft_agreement(world)
        fx.offered_agreement(world)
        validate_success(
            api.patch_institution(world.receiver_id,
                                  {"accreditation_status": "SUSPENDED"},
                                  world.admin)
        )
        response = api.execute_agreement(
            world.ta_id, world.sender,
            {"execution_note": "Premature execution attempt"},
        )
        validate_error(response, ERR_AGREEMENT_INVALID_STATE)
        agreement = world.read_agreement()
        assert agreement["status"] == "OFFERED"
        assert agreement["executed_at"] is None
        assert world.read_animal(world.m1_id)["location_status"] == "HELD"

    def test_the_accreditation_rule_still_bites_once_the_state_is_repaired(
            self, api):
        """From ACCEPTED the same suspended receiver yields the accreditation error.

        PRD: "The receiving institution must hold live accreditation,
        `ACCREDITED` or `PROVISIONAL` (`ERR_INSTITUTION_NOT_ACCREDITED`)."

        Design: Difficulty/priority_pair_validation_conflict/execute_state_50_outranks_accreditation_60
        """
        world = fx.world_with_accepted_agreement(api)
        validate_success(
            api.patch_institution(world.receiver_id,
                                  {"accreditation_status": "SUSPENDED"},
                                  world.admin)
        )
        world.set_clock(fx.CLOCK_EXECUTE)
        response = api.execute_agreement(
            world.ta_id, world.sender,
            {"execution_note": "Second execution attempt"},
        )
        validate_error(response, ERR_INSTITUTION_NOT_ACCREDITED)
        agreement = world.read_agreement()
        assert agreement["status"] == "ACCEPTED"
        assert agreement["executed_at"] is None
        assert world.read_animal(world.m1_id)["location_status"] == "HELD"

    def test_suspension_cascades_onto_nothing_it_only_guards_forward(self, api):
        """The accepted agreement is left standing untouched by the suspension.

        PRD: "Suspension cascades onto nothing: existing agreements are left
        exactly where they stand, and suspension acts purely as a forward guard
        that blocks acceptance and execution from that point on."

        Design: Difficulty/priority_pair_validation_conflict/execute_state_50_outranks_accreditation_60
        """
        world = fx.world_with_accepted_agreement(api)
        before = world.read_agreement()
        validate_success(
            api.patch_institution(world.receiver_id,
                                  {"accreditation_status": "SUSPENDED"},
                                  world.admin)
        )
        after = world.read_agreement()
        assert after["status"] == before["status"]
        assert after["version"] == before["version"]
        assert world.read_recommendation()["status"] == "ENDORSED"


class TestConfirmReferentialOutranksTemporal:
    """A missing permit is reported ahead of a certificate that lapses in flight."""

    @staticmethod
    def _world_with_lapsed_certificate_and_no_permit(api):
        return fx.world_ready_to_confirm(
            api, exam_date="2026-07-20", collected_on="2026-07-15",
            with_permit=False,
        )

    def test_the_certificate_window_closes_before_the_arrival_date(self, api):
        """An exam on 2026-07-20 yields a certificate good only to 2026-08-19.

        PRD: "For an `INTERSTATE_CVI`, `valid_from` is the `exam_date` and
        `valid_until` is the thirtieth day after the `exam_date`; for every permit
        type, `valid_from` is the logical clock's calendar date at the decision
        and `valid_until` is the date supplied in the decision payload."

        Design: Difficulty/priority_pair_validation_conflict/confirm_referential_71_outranks_temporal_74
        """
        world = self._world_with_lapsed_certificate_and_no_permit(api)
        certificate = world.read_document(world.cvi_id)
        assert certificate["status"] == "ISSUED"
        assert str(certificate["valid_from"]).startswith("2026-07-20")
        assert str(certificate["valid_until"]).startswith("2026-08-19")

    def test_the_missing_permit_is_reported_ahead_of_the_lapsed_certificate(
            self, api):
        """Both defects are present and only ERR_PERMIT_NOT_ISSUED surfaces.

        PRD: "It walks six gates in a fixed order, and the first failure is the
        one reported"

        Design: Difficulty/priority_pair_validation_conflict/confirm_referential_71_outranks_temporal_74
        """
        world = self._world_with_lapsed_certificate_and_no_permit(api)
        response = api.confirm_booking(
            world.booking_id, world.sender,
            {"confirmation_note": "First confirm attempt"},
        )
        validate_error(response, ERR_PERMIT_NOT_ISSUED)
        assert world.read_booking()["status"] == "RESERVED"

    def test_the_temporal_gate_bites_once_the_permit_is_issued(self, api):
        """With the permit in place the same confirm reports the expiry instead.

        PRD: "Note which end of the journey that last gate reads: expiry is
        measured against the `arrival_utc` date, not the departure date, so a
        certificate that is valid at take-off but lapses in flight is refused."

        Design: Difficulty/priority_pair_validation_conflict/confirm_referential_71_outranks_temporal_74
        """
        world = self._world_with_lapsed_certificate_and_no_permit(api)
        validate_error(
            api.confirm_booking(world.booking_id, world.sender,
                                {"confirmation_note": "First confirm attempt"}),
            ERR_PERMIT_NOT_ISSUED,
        )
        fx.issue_permit(world)
        response = api.confirm_booking(
            world.booking_id, world.sender,
            {"confirmation_note": "Second confirm attempt"},
        )
        validate_error(response, ERR_HEALTH_CERTIFICATE_EXPIRED)
        assert world.read_booking()["status"] == "RESERVED"

    def test_a_certificate_valid_through_arrival_lets_the_confirm_stand(self, api):
        """The same journey with an in-window certificate confirms cleanly.

        PRD: "`valid_until` is inclusive — a certificate is still good on its
        `valid_until` date."

        Design: Difficulty/priority_pair_validation_conflict/confirm_referential_71_outranks_temporal_74
        """
        world = fx.world_ready_to_confirm(api, exam_date="2026-08-02",
                                          collected_on="2026-08-01")
        certificate = world.read_document(world.cvi_id)
        assert str(certificate["valid_until"]).startswith("2026-09-01")
        confirmed = validate_success(
            api.confirm_booking(world.booking_id, world.sender,
                                {"confirmation_note": "Confirmed"})
        )
        assert confirmed["status"] == "CONFIRMED"
