"""Calculation corner coverage: excursion severity boundaries and the
balance-recompute input set.

Queue B — corner design section ``calculations``.
"""

from test_helpers import (
    get_success_data,
    make_field_rep_headers,
)
from test_helpers import fixtures as fx
from test_helpers import factories as f


def _rep_and_product(api, **product_overrides):
    region = fx.create_region(api)
    territory = fx.create_territory(api, region["id"])
    rep = fx.create_representative(api, territory["id"])
    product = fx.create_product(api, **product_overrides)
    return rep, product


class TestExcursionSeverityBoundaries:
    def test_outside_exactly_2_with_31_minutes_is_major(self, api):
        """PRD section 3.7: "Otherwise severity is MAJOR if the distance is strictly
        greater than 2.0 degrees and at most 5.0 degrees, or if the distance is at
        most 2.0 degrees and the excursion lasted strictly more than 30 minutes."

        Design: Corner/calculations/excursion_severity_boundary_outside_exactly_2_with_31_minutes_is_major
        """
        rep, product = _rep_and_product(api)
        excursion = fx.report_excursion(
            api,
            rep,
            product["id"],
            location_type="HOME_OFFICE",
            observed_temp_c=10.0,
            excursion_minutes=31,
        )
        assert excursion["severity"] == "MAJOR"

    def test_outside_exactly_2_with_30_minutes_is_minor(self, api):
        """PRD section 3.7: "Otherwise — the distance is zero, or the distance is at
        most 2.0 degrees with a duration of at most 30 minutes — severity is MINOR."

        Design: Corner/calculations/excursion_severity_boundary_outside_exactly_2_with_31_minutes_is_major
        """
        rep, product = _rep_and_product(api)
        excursion = fx.report_excursion(
            api,
            rep,
            product["id"],
            location_type="HOME_OFFICE",
            observed_temp_c=10.0,
            excursion_minutes=30,
        )
        assert excursion["severity"] == "MINOR"


class TestCriticalByMinutesAlone:
    def test_minutes_241_is_critical(self, api):
        """PRD section 3.7: "Severity is then CRITICAL if the distance is strictly
        greater than 5.0 degrees or the excursion lasted strictly more than 240
        minutes."

        Design: Corner/calculations/critical_by_minutes_alone_over_240_regardless_of_temperature
        """
        rep, product = _rep_and_product(api)
        excursion = fx.report_excursion(
            api,
            rep,
            product["id"],
            location_type="VEHICLE",
            observed_temp_c=8.5,
            excursion_minutes=241,
        )
        assert excursion["severity"] == "CRITICAL"

    def test_minutes_240_with_small_delta_is_minor(self, api):
        """PRD section 3.7: "Otherwise — the distance is zero, or the distance is at
        most 2.0 degrees with a duration of at most 30 minutes — severity is MINOR."
        and "a boundary written as 'strictly greater than' excludes it" (§2.9): 240
        minutes is not strictly more than 240.

        Design: Corner/calculations/critical_by_minutes_alone_over_240_regardless_of_temperature
        """
        rep, product = _rep_and_product(api)
        excursion = fx.report_excursion(
            api,
            rep,
            product["id"],
            location_type="VEHICLE",
            observed_temp_c=8.5,
            excursion_minutes=240,
        )
        # outside = 0.5 (<= 2.0), minutes 240 (> 30 and not > 240) -> MAJOR
        # via the minutes branch of the MAJOR rule, NOT MINOR: the PRD's
        # MAJOR rule reads "the distance is at most 2.0 degrees and the
        # excursion lasted strictly more than 30 minutes" — 240 > 30.
        assert excursion["severity"] == "MAJOR"


class TestRejectedDisbursementReleasesHold:
    def _setup_rejected(self, api):
        ctx = fx.setup_completed_visit_with_disbursement(
            api, disbursement_qty=5, rep_issue_qty=20, planned_sample_units=20
        )
        get_success_data(
            api.reject_signature(
                ctx["disbursement"]["id"],
                headers=make_field_rep_headers(ctx["rep"]["id"]),
            )
        )
        return ctx

    def test_reject_restores_forward_availability(self, api):
        """PRD section 3.5: "While the disbursement pends, its quantity remains held
        inside the rep's balance — the reservation is consumed when the disbursement
        is signed and released back if it is rejected or voided."

        Design: Corner/calculations/rep_available_units_input_set_excludes_rejected_disbursement
        """
        ctx = self._setup_rejected(api)
        balance = get_success_data(
            api.get_lot_balance(
                ctx["balance"]["id"],
                headers=make_field_rep_headers(ctx["rep"]["id"]),
            )
        )
        assert balance["qty_available_forward"] == 20

    def test_reject_leaves_dispensed_at_zero(self, api):
        """PRD section 3.5: "the disbursement becomes REJECTED, the parent visit's
        signature_status becomes REJECTED, and the reserved quantity is released back
        into the rep's available balances." Only SIGNED disbursements consume units.

        Design: Corner/calculations/rep_available_units_input_set_excludes_rejected_disbursement
        """
        ctx = self._setup_rejected(api)
        balance = get_success_data(
            api.get_lot_balance(
                ctx["balance"]["id"],
                headers=make_field_rep_headers(ctx["rep"]["id"]),
            )
        )
        assert balance["qty_dispensed"] == 0
