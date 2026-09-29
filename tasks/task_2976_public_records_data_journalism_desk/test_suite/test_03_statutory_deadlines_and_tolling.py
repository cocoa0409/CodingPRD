"""Statutory deadlines, the clarification cycle and tolling accrual.

Covers the two deadline variants of PRD S3.2, the bounded clarification cycle and
the tolling gate of PRD S3.4, the day arithmetic of PRD S2.6, and the terminal
lockdown of a withdrawn request.
"""

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_CLARIFICATION_LIMIT_REACHED,
    ERR_INVALID_REQUEST_STATE,
    ERR_TOLLING_NOT_PERMITTED,
)
from test_helpers.assertions import (
    assert_deadline_stamp,
    assert_field_absent_or_null,
    assert_instant_equals,
    assert_ledger_columns,
    validate_error,
    validate_ok,
)
from test_helpers.test_users import coordinator_headers

# The submission instant of the PRD S3.2 worked example: Monday 2026-08-03.
_SUBMIT_CLOCK = "2026-08-03T09:00:00Z"

# Ten business days forward from 2026-08-03 (PRD S3.2).
_DUE_STRICT_DATE = "2026-08-17"


def _standard_desk(api, retention_policy_days: int = 1095):
    """Register the desk of the PRD S3.2 worked example."""
    return X.create_desk(
        api,
        name="Metro Investigations Desk",
        fee_budget_total_cents=500000,
        retention_policy_days=retention_policy_days,
    )


def _read_request(api, request_id):
    """GET /records-desk/records-requests/{id} (PRD S4)."""
    return validate_ok(api.get_records_request(request_id, coordinator_headers()))


def _submitted(api, desk_id, agency_id, **overrides):
    """Draft and submit one request, returning the submit response payload."""
    request = X.draft_request(api, desk_id, agency_id, **overrides)
    return validate_ok(
        api.submit_records_request(request["id"], coordinator_headers())
    )


def _open_round(api, request_id, at_instant, question_text):
    """Park the clock and record the agency's clarification question."""
    X.set_clock(api, at_instant)
    return validate_ok(
        api.request_clarification(
            request_id,
            F.clarification_request_payload(question_text=question_text),
            coordinator_headers(),
        )
    )


def _close_round(api, request_id, at_instant, answer_text):
    """Park the clock and answer the agency, closing the round."""
    X.set_clock(api, at_instant)
    return validate_ok(
        api.respond_clarification(
            request_id,
            F.clarification_response_payload(answer_text=answer_text),
            coordinator_headers(),
        )
    )


class TestStrictVersusTolledDeadlineVariants:
    """The two deadline variants on one RecordsRequest row (PRD S3.2)."""

    def test_two_closed_rounds_separate_the_variants_by_six_business_days(self, api):
        """Two closed clarification rounds accrue six tolled business days.

        PRD S3.2: "After a first clarification round opened on `2026-08-05` and
        answered on `2026-08-11` accrues 4 business days, and a second round
        opened on `2026-08-12` and answered on `2026-08-14` accrues 2 more,
        `tolled_days_total` is 6; sixteen business days from the original
        `2026-08-03` lands on Tuesday `2026-08-25`, so `due_at_tolled` reads
        `2026-08-25T23:59:59.000Z` while `due_at_strict` still reads
        `2026-08-17T23:59:59.000Z`."

        Design: Difficulty/dual_variant_calc/statutory_deadline_strict_versus_tolled_variant
        """
        X.set_clock(api, _SUBMIT_CLOCK)
        desk = _standard_desk(api)
        agency = X.create_agency(api)
        submitted = _submitted(
            api,
            desk["id"],
            agency["id"],
            subject_summary="Section 8 inspection failures 2024-2025",
            estimated_page_count=120,
            waiver_requested=True,
            public_interest_score=85,
        )
        request_id = submitted["id"]

        _open_round(
            api, request_id, "2026-08-05T10:00:00Z", "Narrow to inspections closed in 2025."
        )
        _close_round(
            api,
            request_id,
            "2026-08-11T10:00:00Z",
            "Limited to inspections closed between 2025-01-01 and 2025-12-31.",
        )
        _open_round(
            api,
            request_id,
            "2026-08-12T09:00:00Z",
            "Confirm whether re-inspections are included.",
        )
        answered = _close_round(
            api, request_id, "2026-08-14T09:00:00Z", "Re-inspections are included."
        )

        assert answered["tolled_days_total"] == 6
        assert_deadline_stamp(answered["due_at_strict"], _DUE_STRICT_DATE, "due_at_strict")
        assert_deadline_stamp(answered["due_at_tolled"], "2026-08-25", "due_at_tolled")
        assert answered["due_at_strict"] != answered["due_at_tolled"]

        reread = _read_request(api, request_id)
        assert reread["tolled_days_total"] == 6
        assert_deadline_stamp(reread["due_at_strict"], _DUE_STRICT_DATE, "due_at_strict")
        assert_deadline_stamp(reread["due_at_tolled"], "2026-08-25", "due_at_tolled")

    def test_closing_the_second_round_returns_the_request_to_the_agency_queue(self, api):
        """The round-closing transition restores the loop's rest state.

        PRD S3.4: "Answering the agency, with an `answer_text` payload, closes
        the round and returns the request `CLARIFICATION_REQUESTED →
        AWAITING_AGENCY_RESPONSE`."

        Design: Difficulty/dual_variant_calc/statutory_deadline_strict_versus_tolled_variant
        """
        X.set_clock(api, _SUBMIT_CLOCK)
        desk = _standard_desk(api)
        agency = X.create_agency(api)
        submitted = _submitted(
            api,
            desk["id"],
            agency["id"],
            subject_summary="Section 8 inspection failures 2024-2025",
            estimated_page_count=120,
            waiver_requested=True,
            public_interest_score=85,
        )
        request_id = submitted["id"]

        _open_round(api, request_id, "2026-08-05T10:00:00Z", "Narrow the date range.")
        _close_round(api, request_id, "2026-08-11T10:00:00Z", "2025 only.")
        _open_round(
            api, request_id, "2026-08-12T09:00:00Z", "Confirm re-inspections."
        )
        answered = _close_round(
            api, request_id, "2026-08-14T09:00:00Z", "Re-inspections are included."
        )

        assert answered["status"] == C.REQ_AWAITING_AGENCY_RESPONSE
        assert answered["clarification_round_count"] == 2
        assert_field_absent_or_null(
            answered, "clarification_opened_at", "records request"
        )

    def test_strict_variant_is_the_instant_stamped_at_submission(self, api):
        """The strict deadline stamped at submission survives both rounds intact.

        PRD S3.2: "It is written once at submission and is never revised
        afterwards, no matter how many clarification rounds or granted appeals
        intervene".

        Design: Difficulty/dual_variant_calc/statutory_deadline_strict_versus_tolled_variant
        """
        X.set_clock(api, _SUBMIT_CLOCK)
        desk = _standard_desk(api)
        agency = X.create_agency(api)
        submitted = _submitted(
            api,
            desk["id"],
            agency["id"],
            subject_summary="Section 8 inspection failures 2024-2025",
            estimated_page_count=120,
            waiver_requested=True,
            public_interest_score=85,
        )
        request_id = submitted["id"]
        strict_at_submission = submitted["due_at_strict"]
        assert_deadline_stamp(strict_at_submission, _DUE_STRICT_DATE, "due_at_strict")
        assert submitted["tolled_days_total"] == 0
        assert_instant_equals(
            submitted["due_at_tolled"], strict_at_submission, "due_at_tolled"
        )

        _open_round(api, request_id, "2026-08-05T10:00:00Z", "Narrow the date range.")
        _close_round(api, request_id, "2026-08-11T10:00:00Z", "2025 only.")
        _open_round(api, request_id, "2026-08-12T09:00:00Z", "Confirm re-inspections.")
        answered = _close_round(
            api, request_id, "2026-08-14T09:00:00Z", "Re-inspections are included."
        )

        assert_instant_equals(
            answered["due_at_strict"], strict_at_submission, "due_at_strict"
        )

    def test_tolled_variant_is_recomputed_from_the_original_submission_date(self, api):
        """Each round re-bases the tolled deadline on the original submitted date.

        PRD S3.2: "Every later tolling event recomputes `due_at_tolled` from the
        original submission date and the new accumulated total — never
        incrementally from the previous due date — while leaving `due_at_strict`
        alone."

        Design: Difficulty/dual_variant_calc/statutory_deadline_strict_versus_tolled_variant
        """
        X.set_clock(api, _SUBMIT_CLOCK)
        desk = _standard_desk(api)
        agency = X.create_agency(api)
        submitted = _submitted(
            api,
            desk["id"],
            agency["id"],
            subject_summary="Section 8 inspection failures 2024-2025",
            estimated_page_count=120,
            waiver_requested=True,
            public_interest_score=85,
        )
        request_id = submitted["id"]

        _open_round(api, request_id, "2026-08-05T10:00:00Z", "Narrow the date range.")
        after_first = _close_round(
            api, request_id, "2026-08-11T10:00:00Z", "2025 only."
        )
        # Four tolled business days: fourteen business days from 2026-08-03.
        assert after_first["tolled_days_total"] == 4
        assert_deadline_stamp(after_first["due_at_tolled"], "2026-08-21", "due_at_tolled")
        assert_deadline_stamp(
            after_first["due_at_strict"], _DUE_STRICT_DATE, "due_at_strict"
        )

        _open_round(api, request_id, "2026-08-12T09:00:00Z", "Confirm re-inspections.")
        after_second = _close_round(
            api, request_id, "2026-08-14T09:00:00Z", "Re-inspections are included."
        )
        assert after_second["tolled_days_total"] == 6
        assert_deadline_stamp(
            after_second["due_at_tolled"], "2026-08-25", "due_at_tolled"
        )
        assert_deadline_stamp(
            after_second["due_at_strict"], _DUE_STRICT_DATE, "due_at_strict"
        )


class TestClarificationCycleBoundedAtThreeRounds:
    """The cyclic clarification loop and its three-round ceiling (PRD S3.4)."""

    @staticmethod
    def _three_completed_rounds(api):
        """Submit one request and take it through three complete rounds."""
        X.set_clock(api, _SUBMIT_CLOCK)
        desk = _standard_desk(api)
        agency = X.create_agency(api)
        submitted = _submitted(
            api,
            desk["id"],
            agency["id"],
            subject_summary="Section 8 inspection failures 2024-2025",
            estimated_page_count=120,
            waiver_requested=True,
            public_interest_score=85,
        )
        request_id = submitted["id"]
        _open_round(
            api, request_id, "2026-08-05T10:00:00Z", "Round 1: narrow the date range."
        )
        first = _close_round(
            api, request_id, "2026-08-11T10:00:00Z", "Round 1 answer: 2025 only."
        )
        _open_round(
            api, request_id, "2026-08-12T09:00:00Z", "Round 2: confirm re-inspections."
        )
        second = _close_round(
            api, request_id, "2026-08-14T09:00:00Z", "Round 2 answer: included."
        )
        _open_round(
            api, request_id, "2026-08-17T09:00:00Z", "Round 3: preferred delimiter."
        )
        third = _close_round(
            api,
            request_id,
            "2026-08-19T09:00:00Z",
            "Round 3 answer: pipe-delimited is acceptable.",
        )
        return request_id, (first, second, third)

    def test_fourth_round_is_refused_at_the_three_round_ceiling(self, api):
        """A fourth entry into the loop is refused once three rounds have run.

        PRD S3.4: "And `clarification_round_count` must be strictly less than
        three — three rounds is the ceiling on any single request — otherwise the
        round is refused with `ERR_CLARIFICATION_LIMIT_REACHED`."

        Design: Difficulty/non_linear_state_machine/records_request_clarification_cycle_bounded_at_three_rounds
        """
        request_id, _ = self._three_completed_rounds(api)

        X.set_clock(api, "2026-08-19T09:00:00Z")
        response = api.request_clarification(
            request_id,
            F.clarification_request_payload(
                question_text="Round 4: one more question."
            ),
            coordinator_headers(),
        )
        validate_error(response, ERR_CLARIFICATION_LIMIT_REACHED)

    def test_refused_fourth_round_leaves_the_loop_in_its_rest_state(self, api):
        """The refused attempt neither advances the state nor the round counter.

        PRD S3.4: "On success `clarification_opened_at` is stamped from the
        logical clock and `clarification_round_count` increments by 1."

        Design: Difficulty/non_linear_state_machine/records_request_clarification_cycle_bounded_at_three_rounds
        """
        request_id, _ = self._three_completed_rounds(api)

        validate_error(
            api.request_clarification(
                request_id,
                F.clarification_request_payload(
                    question_text="Round 4: one more question."
                ),
                coordinator_headers(),
            ),
            ERR_CLARIFICATION_LIMIT_REACHED,
        )

        reread = _read_request(api, request_id)
        assert reread["status"] == C.REQ_AWAITING_AGENCY_RESPONSE
        assert reread["clarification_round_count"] == C.MAX_CLARIFICATION_ROUNDS
        assert_field_absent_or_null(
            reread, "clarification_opened_at", "records request"
        )

    def test_three_rounds_accrue_eight_tolled_business_days(self, api):
        """Three closed rounds accrue 4 + 2 + 2 tolled business days.

        PRD S2.6: "given an opening instant and a closing instant, the accrual is
        the count of whole days from the UTC calendar date of the opening instant
        inclusive up to the UTC calendar date of the closing instant exclusive".

        Design: Difficulty/non_linear_state_machine/records_request_clarification_cycle_bounded_at_three_rounds
        """
        request_id, _ = self._three_completed_rounds(api)

        validate_error(
            api.request_clarification(
                request_id,
                F.clarification_request_payload(
                    question_text="Round 4: one more question."
                ),
                coordinator_headers(),
            ),
            ERR_CLARIFICATION_LIMIT_REACHED,
        )

        reread = _read_request(api, request_id)
        assert reread["tolled_days_total"] == 8
        # Eighteen business days from the original 2026-08-03.
        assert_deadline_stamp(reread["due_at_tolled"], "2026-08-27", "due_at_tolled")
        assert_deadline_stamp(
            reread["due_at_strict"], _DUE_STRICT_DATE, "due_at_strict"
        )

    def test_state_alone_cannot_tell_round_one_from_round_three(self, api):
        """Every round returns to the same rest state while the counters grow.

        PRD S3.4: "Because the request is back in `AWAITING_AGENCY_RESPONSE`, a
        second and a third round may follow the same path, each accruing more
        tolled days — the cycle is intentional, and the round ceiling is the only
        thing that ends it."

        Design: Difficulty/non_linear_state_machine/records_request_clarification_cycle_bounded_at_three_rounds
        """
        _, rounds = self._three_completed_rounds(api)

        expected_counts = (1, 2, 3)
        expected_tolled = (4, 6, 8)
        expected_tolled_dates = ("2026-08-21", "2026-08-25", "2026-08-27")
        for index, closed in enumerate(rounds):
            assert closed["status"] == C.REQ_AWAITING_AGENCY_RESPONSE
            assert closed["clarification_round_count"] == expected_counts[index]
            assert closed["tolled_days_total"] == expected_tolled[index]
            assert_deadline_stamp(
                closed["due_at_tolled"],
                expected_tolled_dates[index],
                "due_at_tolled",
            )
            assert_deadline_stamp(
                closed["due_at_strict"], _DUE_STRICT_DATE, "due_at_strict"
            )
            assert_field_absent_or_null(
                closed, "clarification_opened_at", "records request"
            )


class TestDeadlineBasisAndHolidayCounting:
    """Calendar days, business days and declared holidays (PRD S2.6)."""

    @staticmethod
    def _submit_one_per_basis(api):
        """Submit one request against each of three differently-based agencies."""
        X.set_clock(api, _SUBMIT_CLOCK)
        desk = _standard_desk(api, retention_policy_days=365)
        calendar_agency = X.create_agency(
            api,
            name="Calendar Basis Board",
            jurisdiction_code="CA-CAL",
            initial_response_days=30,
            deadline_basis=C.CALENDAR_DAYS,
            tolling_allowed=False,
            appeal_venue=C.VENUE_INTERNAL,
            appeal_decision_days=30,
            search_fee_cents_per_hour=0,
            page_fee_cents=0,
            max_waiver_cents=0,
            holiday_dates=[],
        )
        business_agency = X.create_agency(
            api,
            name="Business Basis Board",
            jurisdiction_code="CA-BIZ",
            initial_response_days=10,
            deadline_basis=C.BUSINESS_DAYS,
            tolling_allowed=False,
            appeal_venue=C.VENUE_INTERNAL,
            appeal_decision_days=30,
            search_fee_cents_per_hour=0,
            page_fee_cents=0,
            max_waiver_cents=0,
            holiday_dates=[],
        )
        holiday_agency = X.create_agency(
            api,
            name="Business Basis Board With Holiday",
            jurisdiction_code="CA-HOL",
            initial_response_days=10,
            deadline_basis=C.BUSINESS_DAYS,
            tolling_allowed=False,
            appeal_venue=C.VENUE_INTERNAL,
            appeal_decision_days=30,
            search_fee_cents_per_hour=0,
            page_fee_cents=0,
            max_waiver_cents=0,
            holiday_dates=["2026-08-14"],
        )
        submitted = {}
        for key, agency, summary in (
            ("calendar", calendar_agency, "Calendar basis probe"),
            ("business", business_agency, "Business basis probe"),
            ("holiday", holiday_agency, "Holiday basis probe"),
        ):
            submitted[key] = _submitted(
                api,
                desk["id"],
                agency["id"],
                subject_summary=summary,
                estimated_page_count=0,
                waiver_requested=False,
                public_interest_score=0,
            )
        return submitted

    def test_calendar_basis_simply_adds_the_declared_number_of_days(self, api):
        """Thirty calendar days from 2026-08-03 lands on 2026-09-02.

        PRD S2.6: "Advancing a start date by a number of days on the
        `CALENDAR_DAYS` basis simply adds that many days."

        Design: Corner/calculations/statutory_deadline_counts_calendar_days_and_business_days_differently
        """
        submitted = self._submit_one_per_basis(api)

        assert_deadline_stamp(
            submitted["calendar"]["due_at_strict"], "2026-09-02", "due_at_strict"
        )

    def test_business_basis_counts_only_weekdays(self, api):
        """Ten business days from Monday 2026-08-03 lands on Monday 2026-08-17.

        PRD S2.6: "Advancing on the `BUSINESS_DAYS` basis steps forward one day at
        a time and counts a step only when the day it lands on is neither a
        Saturday nor a Sunday and its date does not appear in `holiday_dates`,
        repeating until the required number of countable days has been consumed."

        Design: Corner/calculations/statutory_deadline_counts_calendar_days_and_business_days_differently
        """
        submitted = self._submit_one_per_basis(api)

        assert_deadline_stamp(
            submitted["business"]["due_at_strict"], _DUE_STRICT_DATE, "due_at_strict"
        )

    def test_a_declared_holiday_does_not_consume_one_of_the_counted_days(self, api):
        """Friday 2026-08-14 as a holiday pushes the deadline one day further.

        PRD S2.6: "counts a step only when the day it lands on is neither a
        Saturday nor a Sunday and its date does not appear in `holiday_dates`".

        Design: Corner/calculations/statutory_deadline_counts_calendar_days_and_business_days_differently
        """
        submitted = self._submit_one_per_basis(api)

        assert_deadline_stamp(
            submitted["holiday"]["due_at_strict"], "2026-08-18", "due_at_strict"
        )
        strict_dates = {
            key: submitted[key]["due_at_strict"]
            for key in ("calendar", "business", "holiday")
        }
        assert len(set(strict_dates.values())) == 3, (
            "the three deadlines must be pairwise different: " f"{strict_dates}"
        )

    def test_both_variants_coincide_at_submission_on_every_basis(self, api):
        """At submission the tolled variant equals the strict one on every basis.

        PRD S3.2: "At submission `tolled_days_total` is zero, so the two variants
        coincide."

        Design: Corner/calculations/statutory_deadline_counts_calendar_days_and_business_days_differently
        """
        submitted = self._submit_one_per_basis(api)

        for key in ("calendar", "business", "holiday"):
            request = submitted[key]
            assert_instant_equals(
                request["submitted_at"], _SUBMIT_CLOCK, f"{key}.submitted_at"
            )
            assert request["tolled_days_total"] == 0
            assert_instant_equals(
                request["due_at_tolled"],
                request["due_at_strict"],
                f"{key}.due_at_tolled",
            )
            for field in ("due_at_strict", "due_at_tolled"):
                assert request[field].endswith(C.DEADLINE_TIME_OF_DAY), (
                    f"{key}.{field} must be stamped at exactly "
                    f"{C.DEADLINE_TIME_OF_DAY}, got {request[field]}"
                )


class TestClarificationRequiresTollingPermission:
    """A round may only be opened where the statute grants tolling (PRD S3.4)."""

    @staticmethod
    def _two_submitted_requests(api):
        """One submitted request per agency, differing only in `tolling_allowed`."""
        X.set_clock(api, _SUBMIT_CLOCK)
        desk = _standard_desk(api)
        no_tolling_agency = X.create_agency(
            api,
            name="No Tolling Board",
            jurisdiction_code="CA-NOTL",
            tolling_allowed=False,
            appeal_venue=C.VENUE_INTERNAL,
            appeal_decision_days=15,
            holiday_dates=[],
        )
        tolling_agency = X.create_agency(
            api,
            name="Tolling Board",
            jurisdiction_code="CA-TOLL",
            tolling_allowed=True,
            appeal_venue=C.VENUE_INTERNAL,
            appeal_decision_days=15,
            holiday_dates=[],
        )
        no_tolling_request = _submitted(
            api,
            desk["id"],
            no_tolling_agency["id"],
            subject_summary="Tolling probe A",
            estimated_page_count=10,
            waiver_requested=False,
            public_interest_score=10,
        )
        tolling_request = _submitted(
            api,
            desk["id"],
            tolling_agency["id"],
            subject_summary="Tolling probe B",
            estimated_page_count=10,
            waiver_requested=False,
            public_interest_score=10,
        )
        return no_tolling_request, tolling_request

    # The one payload both branches send, byte-identical.
    _QUESTION = "Please confirm the date range covered by the responsive records."

    def test_round_is_refused_where_the_statute_grants_no_tolling(self, api):
        """A clarification round against a non-tolling agency is refused.

        PRD S3.4: "The agency's `tolling_allowed` must be true; where the statute
        grants no tolling, the round is refused with
        `ERR_TOLLING_NOT_PERMITTED`."

        Design: Corner/validations/clarification_round_is_permitted_only_when_the_agency_allows_tolling
        """
        no_tolling_request, _ = self._two_submitted_requests(api)

        validate_error(
            api.request_clarification(
                no_tolling_request["id"],
                F.clarification_request_payload(question_text=self._QUESTION),
                coordinator_headers(),
            ),
            ERR_TOLLING_NOT_PERMITTED,
        )

    def test_refused_round_leaves_the_request_row_untouched(self, api):
        """The refused round writes neither the counter nor the opened instant.

        PRD S3.4: "On success `clarification_opened_at` is stamped from the
        logical clock and `clarification_round_count` increments by 1."

        Design: Corner/validations/clarification_round_is_permitted_only_when_the_agency_allows_tolling
        """
        no_tolling_request, _ = self._two_submitted_requests(api)
        version_after_submit = no_tolling_request["version"]

        validate_error(
            api.request_clarification(
                no_tolling_request["id"],
                F.clarification_request_payload(question_text=self._QUESTION),
                coordinator_headers(),
            ),
            ERR_TOLLING_NOT_PERMITTED,
        )

        reread = _read_request(api, no_tolling_request["id"])
        assert reread["status"] == C.REQ_AWAITING_AGENCY_RESPONSE
        assert reread["clarification_round_count"] == 0
        assert_field_absent_or_null(
            reread, "clarification_opened_at", "records request"
        )
        assert reread["version"] == version_after_submit

    def test_the_same_payload_opens_a_round_against_a_tolling_agency(self, api):
        """The identical payload is accepted where `tolling_allowed` is true.

        PRD S3.4: "On success `clarification_opened_at` is stamped from the
        logical clock and `clarification_round_count` increments by 1."

        Design: Corner/validations/clarification_round_is_permitted_only_when_the_agency_allows_tolling
        """
        _, tolling_request = self._two_submitted_requests(api)

        opened = validate_ok(
            api.request_clarification(
                tolling_request["id"],
                F.clarification_request_payload(question_text=self._QUESTION),
                coordinator_headers(),
            )
        )

        assert opened["status"] == C.REQ_CLARIFICATION_REQUESTED
        assert opened["clarification_round_count"] == 1
        assert_instant_equals(
            opened["clarification_opened_at"], _SUBMIT_CLOCK, "clarification_opened_at"
        )

    def test_opening_a_round_tolls_nothing_yet(self, api):
        """Opening a round leaves both deadline variants exactly where they were.

        PRD S3.4: "The clock is understood to be paused from that instant, but
        `due_at_tolled` is deliberately **not** revised yet: the accrual is only
        known once the round closes."

        Design: Corner/validations/clarification_round_is_permitted_only_when_the_agency_allows_tolling
        """
        _, tolling_request = self._two_submitted_requests(api)
        strict_at_submission = tolling_request["due_at_strict"]
        assert_deadline_stamp(strict_at_submission, _DUE_STRICT_DATE, "due_at_strict")

        opened = validate_ok(
            api.request_clarification(
                tolling_request["id"],
                F.clarification_request_payload(question_text=self._QUESTION),
                coordinator_headers(),
            )
        )

        assert_deadline_stamp(opened["due_at_strict"], _DUE_STRICT_DATE, "due_at_strict")
        assert_instant_equals(
            opened["due_at_strict"], strict_at_submission, "due_at_strict"
        )
        assert_instant_equals(
            opened["due_at_tolled"], opened["due_at_strict"], "due_at_tolled"
        )
        assert opened["tolled_days_total"] == 0


class TestWithdrawnRequestIsTerminal:
    """A withdrawn request accepts no further trigger (PRD S3.2, S3.4)."""

    @staticmethod
    def _withdrawn_request(api):
        """A request withdrawn straight out of `DRAFT`; returns (desk, request)."""
        X.set_clock(api, _SUBMIT_CLOCK)
        desk = _standard_desk(api, retention_policy_days=365)
        agency = X.create_agency(api)
        request = X.draft_request(
            api,
            desk["id"],
            agency["id"],
            subject_summary="Terminal state probe",
            estimated_page_count=10,
            waiver_requested=False,
            public_interest_score=10,
        )
        withdrawn = validate_ok(
            api.withdraw_records_request(
                request["id"],
                F.withdrawal_payload(
                    reason="Superseded by a narrower FOIA strategy."
                ),
                coordinator_headers(),
            )
        )
        return desk, withdrawn

    def test_every_trigger_on_a_withdrawn_request_is_refused(self, api):
        """Submit, withdraw, fee-determine and dispose all fail from `WITHDRAWN`.

        PRD S3.2: "Withdrawal accepts a `reason` and is declared from `DRAFT`,
        `AWAITING_AGENCY_RESPONSE`, `CLARIFICATION_REQUESTED` and `APPEAL_FILED`;
        from a terminal status it is `ERR_INVALID_REQUEST_STATE`."

        Design: Corner/state_machines/a_withdrawn_request_accepts_no_further_trigger
        """
        _, withdrawn = self._withdrawn_request(api)
        request_id = withdrawn["id"]

        validate_error(
            api.submit_records_request(request_id, coordinator_headers()),
            ERR_INVALID_REQUEST_STATE,
        )
        validate_error(
            api.withdraw_records_request(
                request_id,
                F.withdrawal_payload(reason="Second withdrawal attempt."),
                coordinator_headers(),
            ),
            ERR_INVALID_REQUEST_STATE,
        )
        validate_error(
            api.determine_fee(
                request_id,
                F.fee_determination_payload(search_hours=1.0, billed_page_count=10),
                coordinator_headers(),
            ),
            ERR_INVALID_REQUEST_STATE,
        )
        validate_error(
            api.record_agency_decision(
                request_id,
                F.agency_decision_payload(C.OUTCOME_RELEASED_FULL),
                coordinator_headers(),
            ),
            ERR_INVALID_REQUEST_STATE,
        )

    def test_the_withdrawn_request_keeps_its_terminal_state(self, api):
        """No refused trigger moves the status or the mirrored encumbrance.

        PRD S3.4: "From `DRAFT` there is nothing to unwind: the status becomes
        `WITHDRAWN`, `open_request_count` decrements by 1 and the desk's
        `version` increments by 1."

        Design: Corner/state_machines/a_withdrawn_request_accepts_no_further_trigger
        """
        _, withdrawn = self._withdrawn_request(api)
        request_id = withdrawn["id"]
        assert withdrawn["status"] == C.REQ_WITHDRAWN

        for call in (
            lambda: api.submit_records_request(request_id, coordinator_headers()),
            lambda: api.withdraw_records_request(
                request_id,
                F.withdrawal_payload(reason="Second withdrawal attempt."),
                coordinator_headers(),
            ),
            lambda: api.determine_fee(
                request_id,
                F.fee_determination_payload(search_hours=1.0, billed_page_count=10),
                coordinator_headers(),
            ),
            lambda: api.record_agency_decision(
                request_id,
                F.agency_decision_payload(C.OUTCOME_RELEASED_FULL),
                coordinator_headers(),
            ),
        ):
            validate_error(call(), ERR_INVALID_REQUEST_STATE)

        reread = _read_request(api, request_id)
        assert reread["status"] == C.REQ_WITHDRAWN
        assert reread["fee_committed_cents"] == 0

    def test_no_refused_trigger_moves_a_cent_or_the_desk_version(self, api):
        """The desk ledger and its counters are exactly as the withdrawal left them.

        PRD S2.7: "The governing invariant is a conserved quantity that must hold
        after every single mutation, with no drift: the total equals the sum of
        the available, committed and spent columns."

        Design: Corner/state_machines/a_withdrawn_request_accepts_no_further_trigger
        """
        desk, withdrawn = self._withdrawn_request(api)
        request_id = withdrawn["id"]
        desk_after_withdrawal = X.read_desk(api, desk["id"])
        version_after_withdrawal = desk_after_withdrawal["version"]

        for call in (
            lambda: api.submit_records_request(request_id, coordinator_headers()),
            lambda: api.withdraw_records_request(
                request_id,
                F.withdrawal_payload(reason="Second withdrawal attempt."),
                coordinator_headers(),
            ),
            lambda: api.determine_fee(
                request_id,
                F.fee_determination_payload(search_hours=1.0, billed_page_count=10),
                coordinator_headers(),
            ),
            lambda: api.record_agency_decision(
                request_id,
                F.agency_decision_payload(C.OUTCOME_RELEASED_FULL),
                coordinator_headers(),
            ),
        ):
            validate_error(call(), ERR_INVALID_REQUEST_STATE)

        final_desk = X.read_desk(api, desk["id"])
        assert_ledger_columns(
            final_desk, total=500000, available=500000, committed=0, spent=0
        )
        assert final_desk["open_request_count"] == 0
        assert final_desk["version"] == version_after_withdrawal
