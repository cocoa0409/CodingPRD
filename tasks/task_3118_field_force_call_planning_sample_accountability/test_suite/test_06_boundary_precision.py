"""Boundary precision: the disciplinary-tier percentage boundary and the
zero-quantity / empty-denominator edges.

Queue A — difficulty design rule ``boundary_precision_check``.
"""

from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_district_manager_headers,
    make_field_rep_headers,
    validate_error,
    validate_paginated,
)
from test_helpers import fixtures as fx
from test_helpers import factories as f
from test_helpers.test_users import COMPLIANCE_HEADERS


class TestVarianceTierBoundaryAtTwoPercent:
    """At exactly 2.00% the tier is COUNSELING; at 1.99% it is NONE."""

    def _run_session(self, api, ctx, counted, window_start, window_end):
        session = fx.open_count_session(
            api,
            ctx["custodian"],
            ctx["counter"],
            ctx["manager"],
            window_start=window_start,
            window_end=window_end,
        )
        fx.submit_full_count(
            api, session["id"], ctx["counter"], {ctx["lot"]["id"]: counted}
        )
        fx.reconcile_session(api, session["id"], ctx["manager"])
        return get_success_data(
            api.get_count_session(session["id"], headers=COMPLIANCE_HEADERS)
        )

    def test_variance_1_99_yields_tier_none(self, api):
        """PRD section 3.6: "below 2.0 the tier is NONE."

        Design: Difficulty/boundary_precision_check/variance_pct_2_00_exact_triggers_counseling_but_1_99_does_not
        """
        ctx = fx.setup_count_session_cast(
            api,
            custodian_issue_qty=10000,
            lot_quantity=30000,
            annual_max_units_per_prescriber=20000,
        )
        session = self._run_session(
            api, ctx, 9801, "2026-09-03T00:00:00Z", "2026-09-04T00:00:00Z"
        )
        assert session["variance_pct"] == 1.99
        assert session["disciplinary_tier"] == "NONE"

    def test_variance_2_00_yields_tier_counseling(self, api):
        """PRD section 3.6: "The disciplinary_tier is then assigned from variance_pct
        with the lower edge of each band inclusive: ... at least 2.0 and below 5.0 it
        is COUNSELING."

        Design: Difficulty/boundary_precision_check/variance_pct_2_00_exact_triggers_counseling_but_1_99_does_not
        """
        ctx = fx.setup_count_session_cast(
            api,
            custodian_issue_qty=10000,
            lot_quantity=30000,
            annual_max_units_per_prescriber=20000,
        )
        session = self._run_session(
            api, ctx, 9800, "2026-09-03T00:00:00Z", "2026-09-04T00:00:00Z"
        )
        assert session["variance_pct"] == 2.00
        assert session["disciplinary_tier"] == "COUNSELING"


class TestZeroQuantityAndEmptyDenominator:
    """quantity 0 is a malformed request; a custodian with no stock opens a
    session with no count lines."""

    def test_zero_quantity_transfer_rejected_as_invalid_request(self, api):
        """PRD section 2.6: "request-body well-formedness — required fields present,
        enum values within their declared sets, quantity at least 1 where a quantity
        is supplied, and documentation_note at least 20 characters where supplied —
        producing ERR_INVALID_REQUEST."

        Design: Difficulty/boundary_precision_check/zero_quantity_transfer_and_empty_expected_denominator
        """
        ctx = fx.setup_two_reps_with_lot(api, sender_issued=10, lot_quantity=50)
        response = api.create_sample_transfer(
            f.create_sample_transfer_payload(
                ctx["receiver"]["id"],
                ctx["lot"]["id"],
                0,
                fx.fresh_lot_version(api, ctx["lot"]["id"]),
            ),
            headers=make_field_rep_headers(ctx["sender"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

    def test_empty_balance_custodian_session_has_no_lines(self, api):
        """PRD section 3.6: "the system auto-creates one CountLine per lot for which
        the custodian's balance has a qty_available_forward greater than zero,
        snapshotting that figure into the line's expected_qty at open time."

        Design: Difficulty/boundary_precision_check/zero_quantity_transfer_and_empty_expected_denominator
        """
        ctx = fx.setup_count_session_cast(api, custodian_issue_qty=0)
        session = fx.open_count_session(
            api,
            ctx["custodian"],
            ctx["counter"],
            ctx["manager"],
            window_start="2026-09-07T00:00:00Z",
            window_end="2026-09-08T00:00:00Z",
        )
        assert session["status"] == "OPEN"
        lines, meta = validate_paginated(
            api.list_session_count_lines(session["id"], headers=COMPLIANCE_HEADERS)
        )
        assert lines == []
        assert meta["total_count"] == 0
