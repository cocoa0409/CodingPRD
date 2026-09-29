"""The fee determination, the public-interest waiver and the desk ledger.

Covers the eight pinned steps of PRD S3.3 against every worked case the PRD
computes, the rejection precedence of PRD S2.11 where the request-state gate and
the fee-budget gate are both violated, and the at-most-once discipline the
determination endpoint enforces.
"""

import pytest

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_FEE_ALREADY_DETERMINED,
    ERR_FEE_BUDGET_EXCEEDED,
    ERR_INVALID_REQUEST_STATE,
)
from test_helpers.assertions import (
    assert_field_absent_or_null,
    assert_instant_equals,
    assert_ledger_columns,
    validate_error,
    validate_ok,
)
from test_helpers.test_users import coordinator_headers

# The instant every worked case of PRD S3.3 is recorded at.
_FEE_CLOCK = "2026-08-03T09:00:00Z"


def _read_request(api, request_id):
    """GET /records-desk/records-requests/{id} (PRD S4)."""
    return validate_ok(api.get_records_request(request_id, coordinator_headers()))


def _fee_schedule_agency(api, **overrides):
    """The agency of the PRD S3.3 worked cases: 3500/hour, 25/page, cap 10000."""
    return X.create_agency(
        api,
        search_fee_cents_per_hour=3500,
        page_fee_cents=25,
        max_waiver_cents=10000,
        **overrides,
    )


def _awaiting_request(api, desk_id, agency_id, **overrides):
    """A request sitting in `AWAITING_AGENCY_RESPONSE`, ready to be billed."""
    request = X.draft_request(api, desk_id, agency_id, **overrides)
    return validate_ok(
        api.submit_records_request(request["id"], coordinator_headers())
    )


class TestFeeWaiverEightPinnedSteps:
    """The eight steps of PRD S3.3, applied in exactly the pinned order."""

    @staticmethod
    def _billable_request(api, waiver_requested=True, public_interest_score=85):
        """Desk with 500000 cents, standard fee-schedule agency, request submitted."""
        X.set_clock(api, _FEE_CLOCK)
        desk = X.create_desk(
            api,
            name="Metro Investigations Desk",
            fee_budget_total_cents=500000,
            retention_policy_days=1095,
        )
        agency = _fee_schedule_agency(api)
        request = _awaiting_request(
            api,
            desk["id"],
            agency["id"],
            subject_summary="Section 8 inspection failures 2024-2025",
            estimated_page_count=120,
            waiver_requested=waiver_requested,
            public_interest_score=public_interest_score,
        )
        return desk, agency, request

    def test_the_agency_cap_binds_and_pins_the_net_fee_at_5250(self, api):
        """3.5 hours and 120 pages at score 85: the statutory ceiling binds.

        PRD S3.3: "**The cap binding:** 3.5 search hours and 120 pages with a
        waiver requested and a public-interest score of 85 gives a search fee of
        12250, a duplication fee of 3000 and a gross fee of 15250; the tier is
        three quarters because 15250 sits above 5000 and at or below 20000, plus a
        one-tenth bonus for a score of at least 80, so `waiver_pct` is 0.85; 15250
        multiplied by 0.85 is 12962.5, which rounds half up to 12963; the agency
        ceiling pulls that back to 10000; the residual of 5250 is not below 1500,
        so `waiver_amount_cents` is 10000 and `net_fee_cents` is 5250."

        Design: Difficulty/combinatorial_formula/fee_waiver_eight_step_pinned_order_cap_binds
        """
        _, _, request = self._billable_request(api)

        determined = validate_ok(
            api.determine_fee(
                request["id"],
                F.fee_determination_payload(search_hours=3.5, billed_page_count=120),
                coordinator_headers(),
            )
        )

        assert determined["search_fee_cents"] == 12250
        assert determined["duplication_fee_cents"] == 3000
        assert determined["gross_fee_cents"] == 15250
        assert determined["waiver_pct"] == pytest.approx(0.85, abs=0.01)
        assert determined["waiver_amount_cents"] == 10000
        assert determined["net_fee_cents"] == 5250
        assert determined["fee_committed_cents"] == 5250
        assert_instant_equals(
            determined["fee_determined_at"], _FEE_CLOCK, "fee_determined_at"
        )

    def test_the_capped_net_fee_is_committed_against_the_desk_ledger(self, api):
        """The 5250 net fee moves from the available column to the committed one.

        PRD S3.3: "That net amount is then committed against the desk under the
        ledger rules of §2.7: the net fee is subtracted from
        `fee_budget_available_cents`, added to `fee_budget_committed_cents`, and
        mirrored into the request's own `fee_committed_cents`."

        Design: Difficulty/combinatorial_formula/fee_waiver_eight_step_pinned_order_cap_binds
        """
        desk, _, request = self._billable_request(api)

        validate_ok(
            api.determine_fee(
                request["id"],
                F.fee_determination_payload(search_hours=3.5, billed_page_count=120),
                coordinator_headers(),
            )
        )

        final_desk = X.read_desk(api, desk["id"])
        assert_ledger_columns(
            final_desk, total=500000, available=494750, committed=5250, spent=0
        )

    def test_the_de_minimis_rule_waives_the_whole_gross_fee(self, api):
        """1.0 hour and 100 pages: the residual of 900 falls under 1500.

        PRD S3.3: "**The de-minimis rule binding:** 1.0 search hours and 100 pages
        with the same waiver request and score gives 3500 plus 2500, a gross fee
        of 6000; 0.85 of 6000 is exactly 5100, under the 10000 ceiling; the
        residual of 900 is below 1500, so the entire 6000 is waived and
        `net_fee_cents` is 0."

        Design: Difficulty/combinatorial_formula/fee_waiver_eight_step_pinned_order_cap_binds
        """
        desk, _, request = self._billable_request(api)

        determined = validate_ok(
            api.determine_fee(
                request["id"],
                F.fee_determination_payload(search_hours=1.0, billed_page_count=100),
                coordinator_headers(),
            )
        )

        assert determined["search_fee_cents"] == 3500
        assert determined["duplication_fee_cents"] == 2500
        assert determined["gross_fee_cents"] == 6000
        assert determined["waiver_pct"] == pytest.approx(0.85, abs=0.01)
        assert determined["waiver_amount_cents"] == 6000
        assert determined["net_fee_cents"] == 0
        assert determined["fee_committed_cents"] == 0

        final_desk = X.read_desk(api, desk["id"])
        assert_ledger_columns(
            final_desk, total=500000, available=500000, committed=0, spent=0
        )

    def test_no_waiver_requested_leaves_the_whole_gross_fee_payable(self, api):
        """With `waiver_requested` false the score is irrelevant to the net fee.

        PRD S3.3: "**No waiver requested:** 3.5 hours and 120 pages with
        `waiver_requested` false gives a gross fee of 15250, a
        `waiver_amount_cents` of 0 and a `net_fee_cents` of 15250, regardless of
        how high the public-interest score is."

        Design: Difficulty/combinatorial_formula/fee_waiver_eight_step_pinned_order_cap_binds
        """
        desk, _, request = self._billable_request(
            api, waiver_requested=False, public_interest_score=85
        )

        determined = validate_ok(
            api.determine_fee(
                request["id"],
                F.fee_determination_payload(search_hours=3.5, billed_page_count=120),
                coordinator_headers(),
            )
        )

        assert determined["search_fee_cents"] == 12250
        assert determined["duplication_fee_cents"] == 3000
        assert determined["gross_fee_cents"] == 15250
        assert determined["waiver_amount_cents"] == 0
        assert determined["net_fee_cents"] == 15250
        assert determined["fee_committed_cents"] == 15250

        final_desk = X.read_desk(api, desk["id"])
        assert_ledger_columns(
            final_desk, total=500000, available=484750, committed=15250, spent=0
        )

    def test_the_waiver_percentage_ceiling_clamps_tier_plus_bonus(self, api):
        """6.0 hours and 200 pages: the 0.95 ceiling clamps a 1.00 sum.

        PRD S3.3: "**The percentage ceiling binding:** 6.0 hours and 200 pages
        gives 21000 plus 5000 for a gross fee of 26000, where the nine-tenths tier
        plus the one-tenth bonus would reach 1.00 and is therefore clamped to
        0.95; 0.95 of 26000 is 24700, the agency ceiling pulls it to 10000, the
        residual of 16000 clears the de-minimis threshold, and the net fee is
        16000."

        Design: Difficulty/combinatorial_formula/fee_waiver_eight_step_pinned_order_cap_binds
        """
        desk, _, request = self._billable_request(api)

        determined = validate_ok(
            api.determine_fee(
                request["id"],
                F.fee_determination_payload(search_hours=6.0, billed_page_count=200),
                coordinator_headers(),
            )
        )

        assert determined["search_fee_cents"] == 21000
        assert determined["duplication_fee_cents"] == 5000
        assert determined["gross_fee_cents"] == 26000
        assert determined["waiver_pct"] == pytest.approx(C.MAX_WAIVER_PCT, abs=0.01)
        assert determined["waiver_amount_cents"] == 10000
        assert determined["net_fee_cents"] == 16000
        assert determined["fee_committed_cents"] == 16000

        final_desk = X.read_desk(api, desk["id"])
        assert_ledger_columns(
            final_desk, total=500000, available=484000, committed=16000, spent=0
        )


class TestRequestStateGateBeatsFeeBudgetGate:
    """A determination that breaks the state gate and the fiscal gate at once."""

    @staticmethod
    def _shoestring_desk_with_draft(api):
        """A desk holding 1000 cents and a request deliberately left in DRAFT."""
        X.set_clock(api, _FEE_CLOCK)
        desk = X.create_desk(
            api,
            name="Shoestring Desk",
            fee_budget_total_cents=1000,
            retention_policy_days=365,
        )
        agency = _fee_schedule_agency(api)
        request = X.draft_request(
            api,
            desk["id"],
            agency["id"],
            subject_summary="Section 8 inspection failures 2024-2025",
            estimated_page_count=120,
            waiver_requested=True,
            public_interest_score=85,
        )
        return desk, request

    _BILLING = {"search_hours": 3.5, "billed_page_count": 120}

    def test_the_state_gate_answers_first_on_a_draft_request(self, api):
        """A DRAFT request that is also unaffordable is refused for its state.

        PRD S2.11: "When more than one rule could reject a request, the outcome is
        fully determined: the rules are evaluated in ascending priority order, and
        the first rule whose condition is violated determines the response. No
        later rule is evaluated, so a caller never sees a downstream error masking
        an upstream one."

        Design: Difficulty/priority_pair_validation_conflict/request_state_priority_100_beats_fee_budget_priority_270
        """
        _, request = self._shoestring_desk_with_draft(api)

        validate_error(
            api.determine_fee(
                request["id"],
                F.fee_determination_payload(**self._BILLING),
                coordinator_headers(),
            ),
            ERR_INVALID_REQUEST_STATE,
        )

    def test_the_state_refusal_writes_no_fee_field_and_no_ledger_column(self, api):
        """The rejected determination leaves the request and the desk untouched.

        PRD S3.3: "The request must be sitting in `AWAITING_AGENCY_RESPONSE` — any
        other status is `ERR_INVALID_REQUEST_STATE` — and the determination may be
        recorded **at most once** per request: if `fee_determined_at` is already
        set, the second attempt is refused with `ERR_FEE_ALREADY_DETERMINED`."

        Design: Difficulty/priority_pair_validation_conflict/request_state_priority_100_beats_fee_budget_priority_270
        """
        desk, request = self._shoestring_desk_with_draft(api)

        validate_error(
            api.determine_fee(
                request["id"],
                F.fee_determination_payload(**self._BILLING),
                coordinator_headers(),
            ),
            ERR_INVALID_REQUEST_STATE,
        )

        after = _read_request(api, request["id"])
        assert after["status"] == C.REQ_DRAFT
        assert_field_absent_or_null(after, "gross_fee_cents", "gross_fee_cents")
        assert_field_absent_or_null(after, "net_fee_cents", "net_fee_cents")
        assert after["fee_committed_cents"] == 0

        final_desk = X.read_desk(api, desk["id"])
        assert_ledger_columns(
            final_desk, total=1000, available=1000, committed=0, spent=0
        )

    def test_the_fiscal_gate_answers_once_the_state_gate_is_satisfied(self, api):
        """The same billing on the same desk is refused on affordability alone.

        PRD S3.3: "If the net fee is strictly greater than
        `fee_budget_available_cents` the whole determination is refused with
        `ERR_FEE_BUDGET_EXCEEDED` and nothing at all is written — no fee fields, no
        `fee_determined_at`, no ledger movement."

        Design: Difficulty/priority_pair_validation_conflict/request_state_priority_100_beats_fee_budget_priority_270
        """
        desk, request = self._shoestring_desk_with_draft(api)

        validate_ok(api.submit_records_request(request["id"], coordinator_headers()))

        validate_error(
            api.determine_fee(
                request["id"],
                F.fee_determination_payload(**self._BILLING),
                coordinator_headers(),
            ),
            ERR_FEE_BUDGET_EXCEEDED,
        )

        after = _read_request(api, request["id"])
        assert after["status"] == C.REQ_AWAITING_AGENCY_RESPONSE
        assert_field_absent_or_null(after, "fee_determined_at", "fee_determined_at")
        assert after["fee_committed_cents"] == 0

        final_desk = X.read_desk(api, desk["id"])
        assert_ledger_columns(
            final_desk, total=1000, available=1000, committed=0, spent=0
        )


class TestFeeDeterminationCommitsOnce:
    """The determination endpoint accepts exactly one bill per records request."""

    _FIRST_BILL = {"search_hours": 1.0, "billed_page_count": 100}
    _SECOND_BILL = {"search_hours": 9.0, "billed_page_count": 900}

    @staticmethod
    def _submitted_probe(api):
        """A submitted, unwaived request against an internal-appeal agency."""
        X.set_clock(api, _FEE_CLOCK)
        desk = X.create_desk(
            api,
            name="Metro Investigations Desk",
            fee_budget_total_cents=500000,
            retention_policy_days=1095,
        )
        agency = _fee_schedule_agency(
            api,
            tolling_allowed=False,
            appeal_venue=C.VENUE_INTERNAL,
            appeal_decision_days=15,
            holiday_dates=[],
        )
        request = _awaiting_request(
            api,
            desk["id"],
            agency["id"],
            subject_summary="Single-shot fee probe",
            estimated_page_count=100,
            waiver_requested=False,
            public_interest_score=0,
        )
        return desk, request

    def test_the_first_determination_records_and_commits_the_bill(self, api):
        """One hour and 100 unwaived pages bill 6000 cents in full.

        PRD S3.3: "On success `fee_determined_at` is stamped from the logical clock,
        and both the request's `version` and the desk's `version` increment by 1."

        Design: Corner/endpoints/fee_determination_commits_once_and_the_second_call_is_refused
        """
        _, request = self._submitted_probe(api)

        determined = validate_ok(
            api.determine_fee(
                request["id"],
                F.fee_determination_payload(**self._FIRST_BILL),
                coordinator_headers(),
            )
        )

        assert determined["search_fee_cents"] == 3500
        assert determined["duplication_fee_cents"] == 2500
        assert determined["gross_fee_cents"] == 6000
        assert determined["waiver_amount_cents"] == 0
        assert determined["net_fee_cents"] == 6000
        assert determined["fee_committed_cents"] == 6000
        assert_instant_equals(
            determined["fee_determined_at"], _FEE_CLOCK, "fee_determined_at"
        )

    def test_the_second_determination_is_refused_and_changes_no_fee_field(self, api):
        """A richer second bill cannot overwrite the bill already on file.

        PRD S2.11: "A fee determination may be performed at most once per records
        request: `fee_determined_at` must still be null — otherwise
        `ERR_FEE_ALREADY_DETERMINED`."

        Design: Corner/endpoints/fee_determination_commits_once_and_the_second_call_is_refused
        """
        _, request = self._submitted_probe(api)

        first = validate_ok(
            api.determine_fee(
                request["id"],
                F.fee_determination_payload(**self._FIRST_BILL),
                coordinator_headers(),
            )
        )

        validate_error(
            api.determine_fee(
                request["id"],
                F.fee_determination_payload(**self._SECOND_BILL),
                coordinator_headers(),
            ),
            ERR_FEE_ALREADY_DETERMINED,
        )

        after = _read_request(api, request["id"])
        assert after["gross_fee_cents"] == 6000
        assert after["net_fee_cents"] == 6000
        assert after["fee_committed_cents"] == 6000
        assert after["version"] == first["version"]
        assert_instant_equals(
            after["fee_determined_at"], _FEE_CLOCK, "fee_determined_at"
        )

    def test_the_refused_determination_performs_no_ledger_write(self, api):
        """Only the first bill reaches the desk's committed column.

        PRD S3.3: "That net amount is then committed against the desk under the
        ledger rules of §2.7: the net fee is subtracted from
        `fee_budget_available_cents`, added to `fee_budget_committed_cents`, and
        mirrored into the request's own `fee_committed_cents`."

        Design: Corner/endpoints/fee_determination_commits_once_and_the_second_call_is_refused
        """
        desk, request = self._submitted_probe(api)

        validate_ok(
            api.determine_fee(
                request["id"],
                F.fee_determination_payload(**self._FIRST_BILL),
                coordinator_headers(),
            )
        )
        desk_after_first = X.read_desk(api, desk["id"])

        validate_error(
            api.determine_fee(
                request["id"],
                F.fee_determination_payload(**self._SECOND_BILL),
                coordinator_headers(),
            ),
            ERR_FEE_ALREADY_DETERMINED,
        )

        final_desk = X.read_desk(api, desk["id"])
        assert_ledger_columns(
            final_desk, total=500000, available=494000, committed=6000, spent=0
        )
        assert final_desk["version"] == desk_after_first["version"]
