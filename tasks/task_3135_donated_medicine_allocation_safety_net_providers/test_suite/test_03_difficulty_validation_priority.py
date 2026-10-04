"""Depth tests: validation priority pairs.

The PRD fixes a guard order, so when two guards both fail, the earlier one
must be the error returned.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import ALLOCATION_OFFICER_HEADERS, ApiErrorId as E
from test_helpers import fixtures


class TestStateBeforeSafety:
    """A VOID decision violates the DRAFT precondition before any safety rule."""

    def _setup_voided_controlled_decision(self, api):
        fixtures.set_clock(api)
        donor = fixtures.create_donor(api, dea_registration_no="BM1234567")
        lot = fixtures.create_and_release_lot(
            api,
            donor["id"],
            ndc_code="C1",
            product_name="Morphine",
            product_class="CONTROLLED",
            dosage_form="VIAL",
            unit_of_measure="VIAL",
            quantity_received=50,
            unit_acquisition_value_usd=5.00,
            unit_wholesale_value_usd=8.00,
        )
        site = fixtures.setup_qualified_site(api, has_dea_registration=False)
        request = fixtures.create_request(api, site["id"], quantity_requested=10, ndc_code="C1")
        fixtures.begin_review(api, request["id"])
        current = fixtures.get_request(api, request["id"])
        decision = fixtures.create_draft_decision(
            api, request["id"], [{"lot_id": lot["id"], "quantity": 10}]
        )
        get_success_data(api.void_decision(decision["id"], ALLOCATION_OFFICER_HEADERS))
        return lot, site, request, decision, current["version"]

    def test_finalize_voided_decision_returns_invalid_state(self, api):
        """PRD §3.5: "The checks, in order: the decision must be in `DRAFT` (else
        `ERR_INVALID_STATE`); the caller must be the same officer who drafted it —
        `reviewer_user_id` must equal `X-User-ID`, enforcing segregation of duties
        so a different officer may not finalize another's draft; the decision must
        carry at least one line; every line's lot must be `RELEASABLE` (else
        `ERR_LOT_NOT_RELEASABLE`); for every line whose lot requires cold chain,
        the site's cold-storage capability must suffice (else
        `ERR_COLD_CHAIN_INADEQUATE`); for every line whose lot is controlled, the
        site's `has_dea_registration` must be true (else
        `ERR_CONTROLLED_SITE_NOT_AUTHORIZED`); the sum of line quantities must not
        exceed `quantity_requested` (else `ERR_QUANTITY_INVALID`); the
        lot-availability invariant must hold (else `ERR_INSUFFICIENT_AVAILABLE`);
        and the request body must carry `expected_request_version` matching the
        request's current `version` (else `ERR_STALE_VERSION`)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_finalize_rejected_for_state_even_when_controlled_site_unauthorized
        """
        _, _, _, decision, req_version = self._setup_voided_controlled_decision(api)
        resp = api.finalize_decision(
            decision["id"],
            {"expected_request_version": req_version},
            ALLOCATION_OFFICER_HEADERS,
        )
        validate_error(resp, E.ERR_INVALID_STATE, 409)

    def test_rejected_finalize_leaves_decision_and_lot_untouched(self, api):
        """PRD §3.5: "A draft may alternatively be voided by its officer, moving
        it to the terminal `VOID` status with no quantity impact — the lines were
        never reserved."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_finalize_rejected_for_state_even_when_controlled_site_unauthorized
        """
        lot, _, _, decision, req_version = self._setup_voided_controlled_decision(api)
        api.finalize_decision(
            decision["id"],
            {"expected_request_version": req_version},
            ALLOCATION_OFFICER_HEADERS,
        )
        decision_after = fixtures.get_decision(api, decision["id"])
        assert decision_after["status"] == "VOID"
        lot_after = fixtures.get_lot(api, lot["id"])
        assert lot_after["quantity_committed"] == 0


class TestSafetyBeforeFiscal:
    """The controlled-site safety rule fires before the lot-availability check."""

    def _setup_overcommitted_controlled_decision(self, api):
        fixtures.set_clock(api)
        donor = fixtures.create_donor(api, dea_registration_no="BM1234567")
        lot = fixtures.create_and_release_lot(
            api,
            donor["id"],
            ndc_code="C1",
            product_name="Morphine",
            product_class="CONTROLLED",
            dosage_form="VIAL",
            unit_of_measure="VIAL",
            quantity_received=5,
            unit_acquisition_value_usd=5.00,
            unit_wholesale_value_usd=8.00,
        )
        site = fixtures.setup_qualified_site(api, has_dea_registration=False)
        request = fixtures.create_request(api, site["id"], quantity_requested=10, ndc_code="C1")
        fixtures.begin_review(api, request["id"])
        current = fixtures.get_request(api, request["id"])
        decision = fixtures.create_draft_decision(
            api, request["id"], [{"lot_id": lot["id"], "quantity": 10}]
        )
        return lot, decision, current["version"]

    def test_controlled_error_wins_over_availability_error(self, api):
        """PRD §3.5: "The checks, in order: the decision must be in `DRAFT` (else
        `ERR_INVALID_STATE`); the caller must be the same officer who drafted it —
        `reviewer_user_id` must equal `X-User-ID`, enforcing segregation of duties
        so a different officer may not finalize another's draft; the decision must
        carry at least one line; every line's lot must be `RELEASABLE` (else
        `ERR_LOT_NOT_RELEASABLE`); for every line whose lot requires cold chain,
        the site's cold-storage capability must suffice (else
        `ERR_COLD_CHAIN_INADEQUATE`); for every line whose lot is controlled, the
        site's `has_dea_registration` must be true (else
        `ERR_CONTROLLED_SITE_NOT_AUTHORIZED`); the sum of line quantities must not
        exceed `quantity_requested` (else `ERR_QUANTITY_INVALID`); the
        lot-availability invariant must hold (else `ERR_INSUFFICIENT_AVAILABLE`);
        and the request body must carry `expected_request_version` matching the
        request's current `version` (else `ERR_STALE_VERSION`)."

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_fiscal_finalize_controlled_over_budget_reports_controlled_first
        """
        lot, decision, req_version = self._setup_overcommitted_controlled_decision(api)
        resp = api.finalize_decision(
            decision["id"],
            {"expected_request_version": req_version},
            ALLOCATION_OFFICER_HEADERS,
        )
        validate_error(resp, E.ERR_CONTROLLED_SITE_NOT_AUTHORIZED, 422)

    def test_rejected_finalize_keeps_decision_draft_and_lot_uncommitted(self, api):
        """PRD §3.5: "A draft's lines carry no reservation yet — quantities are
        not committed against any lot until finalization."

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_fiscal_finalize_controlled_over_budget_reports_controlled_first
        """
        lot, decision, req_version = self._setup_overcommitted_controlled_decision(api)
        api.finalize_decision(
            decision["id"],
            {"expected_request_version": req_version},
            ALLOCATION_OFFICER_HEADERS,
        )
        decision_after = fixtures.get_decision(api, decision["id"])
        assert decision_after["status"] == "DRAFT"
        lot_after = fixtures.get_lot(api, lot["id"])
        assert lot_after["quantity_committed"] == 0
