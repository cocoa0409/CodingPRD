"""Degenerate panels, the strict excursion threshold and the inclusive day gate."""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (ERR_QUARANTINE_MINIMUM_NOT_MET,
                                     ERR_TEST_PANEL_INCOMPLETE)
from test_helpers.test_users import make_vet_headers


def _interstate_world_with_draft_certificate(api):
    """An executed US-CA to US-TX agreement with a DRAFT certificate and no tests."""
    world = fx.world_with_executed_agreement(api)
    world.set_clock(fx.CLOCK_DOCUMENTS)
    fx.open_certificate(world, exam_date="2026-08-20")
    return world


def _sign(world):
    return world.api.decide_document(
        world.cvi_id,
        f.document_decision_payload(outcome="ISSUE",
                                    document_number="CVI-2026-0021"),
        make_vet_headers(world.vet_b_id),
    )


class TestEmptyAndPartialTestPanel:
    """Zero and one-of-two recorded tests both fail the completeness gate."""

    def test_an_agreement_with_no_recorded_tests_fails_the_panel(self, api):
        """The empty collection is refused rather than vacuously satisfied.

        PRD: "A missing code, a stale sample, or an agreement with no recorded
        tests whatsoever is refused with `ERR_TEST_PANEL_INCOMPLETE` (HTTP 422);
        the empty-panel case fails here rather than trivially passing an empty-set
        test."

        Design: Difficulty/boundary_precision_check/empty_and_partial_test_panel_block_certificate_issue
        """
        world = _interstate_world_with_draft_certificate(api)
        assert world.read_agreement()["transfer_scope"] == "INTERSTATE"
        validate_error(_sign(world), ERR_TEST_PANEL_INCOMPLETE)
        assert world.read_document(world.cvi_id)["status"] == "DRAFT"

    def test_one_of_the_two_required_codes_fails_the_panel_identically(self, api):
        """A TB result alone leaves BRUCELLA missing, so the signature is refused.

        PRD: "Only afterwards is completeness assessed: the panel must contain one
        test for each `test_code` the scope requires, and each of those tests must
        have been collected within the sixty days running up to the examination"

        Design: Difficulty/boundary_precision_check/empty_and_partial_test_panel_block_certificate_issue
        """
        world = _interstate_world_with_draft_certificate(api)
        fx.record_panel(world, codes=["TB"], collected_on="2026-08-15")
        validate_error(_sign(world), ERR_TEST_PANEL_INCOMPLETE)
        assert world.read_document(world.cvi_id)["status"] == "DRAFT"

    def test_the_complete_interstate_panel_lets_the_certificate_issue(self, api):
        """With TB and BRUCELLA both negative the certificate issues to 2026-09-19.

        PRD: "An `ISSUE` outcome sets `status` to `ISSUED` and copies the supplied
        `document_number` onto the record, then fills the validity window."

        Design: Difficulty/boundary_precision_check/empty_and_partial_test_panel_block_certificate_issue
        """
        world = _interstate_world_with_draft_certificate(api)
        fx.record_panel(world, codes=["TB", "BRUCELLA"],
                        collected_on="2026-08-15")
        data = validate_success(_sign(world))
        assert data["status"] == "ISSUED"
        assert data["document_number"] == "CVI-2026-0021"
        assert str(data["valid_from"]).startswith("2026-08-20")
        assert str(data["valid_until"]).startswith("2026-09-19")


class TestExcursionThresholdAndClearanceDay:
    """The excursion threshold is strict where the clearance gate is inclusive."""

    @staticmethod
    def _delivered_at_ninety_minutes(api):
        """Three readings outside a 10.0 to 24.0 envelope, two exactly on its edges."""
        return fx.world_delivered(
            api,
            temperature_samples=[10.0, 24.0, 9.9, 24.1, 26.0, 17.0],
        )

    def test_exactly_ninety_excursion_minutes_keeps_the_standard_class(self, api):
        """Three out-of-envelope readings record 90 minutes and 30 required days.

        PRD: "The threshold is strict: where the delivering booking's
        `thermal_excursion_minutes` is greater than 90 minutes, the
        `isolation_class` becomes `ENHANCED` and `required_days` becomes 45; at
        exactly 90 minutes of excursion, and anywhere below, the class stays
        `STANDARD` and `required_days` stays 30."

        Design: Difficulty/boundary_precision_check/thermal_excursion_exact_max_and_inclusive_clearance_day
        """
        world = self._delivered_at_ninety_minutes(api)
        booking = world.read_booking()
        assert booking["thermal_excursion_minutes"] == 90
        assert booking["status"] == "DELIVERED"
        assert booking["delivered_at"].startswith("2026-09-01T20:00:00")
        occupancy = world.read_occupancy()
        assert occupancy["isolation_class"] == "STANDARD"
        assert occupancy["required_days"] == 30
        assert occupancy["phase"] == "ACTIVE"
        assert str(occupancy["actual_start_date"]).startswith("2026-09-01")

    def test_a_fourth_out_of_envelope_reading_escalates_the_isolation(self, api):
        """One more sampling interval past ninety minutes buys fifteen more days.

        PRD: "One further half-hour sampling interval past the ninety-minute mark
        therefore adds fifteen days of isolation."

        Design: Difficulty/boundary_precision_check/thermal_excursion_exact_max_and_inclusive_clearance_day
        """
        world = fx.world_delivered(
            api,
            temperature_samples=[10.0, 24.0, 9.9, 24.1, 26.0, 27.0, 17.0],
        )
        assert world.read_booking()["thermal_excursion_minutes"] == 120
        occupancy = world.read_occupancy()
        assert occupancy["isolation_class"] == "ENHANCED"
        assert occupancy["required_days"] == 45

    def test_a_clearance_on_the_twenty_ninth_day_is_refused(self, api):
        """Twenty-nine days served is not enough and nothing is persisted.

        PRD: "The duration gate is inclusive: the whole days elapsed from
        `actual_start_date` to the logical clock's date must be at least
        `required_days`, so serving exactly thirty days on a `STANDARD` occupancy
        is enough while twenty-nine days is not, and a premature clearance is
        refused with `ERR_QUARANTINE_MINIMUM_NOT_MET` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/thermal_excursion_exact_max_and_inclusive_clearance_day
        """
        world = self._delivered_at_ninety_minutes(api)
        world.set_clock("2026-09-30T09:00:00Z")
        response = api.clear_quarantine(
            world.occupancy_id, make_vet_headers(world.vet_c_id),
            {"clearance_note": "Attempt on day 29"},
        )
        validate_error(response, ERR_QUARANTINE_MINIMUM_NOT_MET)
        occupancy = world.read_occupancy()
        assert occupancy["phase"] == "ACTIVE"
        assert occupancy["cleared_on"] is None
        assert world.read_animal(world.m1_id)["location_status"] == "IN_QUARANTINE"

    def test_a_clearance_on_the_thirtieth_day_is_allowed(self, api):
        """Day thirty clears the animal and records the acting veterinarian.

        PRD: "A successful clearance, which may carry an optional
        `clearance_note`, sets `phase` to `CLEARED`, stamps `cleared_on` with the
        logical clock's date, records `clearing_veterinarian_id` as the acting
        `X-User-ID`, and moves the animal from `IN_QUARANTINE` to
        `AWAITING_INTRODUCTION`, incrementing both the occupancy's `version` and
        the animal's `version` by 1."

        Design: Difficulty/boundary_precision_check/thermal_excursion_exact_max_and_inclusive_clearance_day
        """
        world = self._delivered_at_ninety_minutes(api)
        world.set_clock("2026-09-30T09:00:00Z")
        validate_error(
            api.clear_quarantine(world.occupancy_id,
                                 make_vet_headers(world.vet_c_id),
                                 {"clearance_note": "Attempt on day 29"}),
            ERR_QUARANTINE_MINIMUM_NOT_MET,
        )
        world.set_clock("2026-10-01T09:00:00Z")
        data = validate_success(
            api.clear_quarantine(world.occupancy_id,
                                 make_vet_headers(world.vet_c_id),
                                 {"clearance_note": "Attempt on day 30"})
        )
        assert data["phase"] == "CLEARED"
        assert str(data["cleared_on"]).startswith("2026-10-01")
        assert data["clearing_veterinarian_id"] == world.vet_c_id
        assert world.read_animal(world.m1_id)["location_status"] == \
            "AWAITING_INTRODUCTION"
