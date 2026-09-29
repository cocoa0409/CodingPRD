"""Secure enclave occupancy: the buffered half-open span of PRD S3.9.

An enclave session occupies ``start_at`` inclusive up to ``end_at`` plus the
enclave's ``sanitization_buffer_minutes``, exclusive, and conflict is pairwise
exclusion against each ``BOOKED`` session individually -- deliberately the
opposite of the closed-interval aggregate capacity rule for reviewers in PRD
S3.8. The enclave's own ``booked_session_count`` has no read surface in PRD S4,
so occupancy is observed the way a caller can observe it: through which later
bookings are accepted or refused, and through the session listing.
"""

from typing import Any, Dict

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_ENCLAVE_DOCUMENT_LIMIT,
    ERR_ENCLAVE_NOT_FOUND,
    ERR_ENCLAVE_SESSION_OVERLAP,
    ERR_INVALID_DATASET_STATE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_SESSION_STATE,
)
from test_helpers.assertions import (
    assert_field_absent_or_null,
    assert_version_is,
    validate_created,
    validate_error,
    validate_ok,
    validate_paginated_page,
)
from test_helpers.test_users import legal_headers, reporter_headers
from test_helpers import test_users as U


# --------------------------------------------------------------------------
# Private helpers (this module owns them; nothing here is shared)
# --------------------------------------------------------------------------


def _book(api, enclave_id, dataset_id, start_at, end_at, document_count, purpose,
          headers=None):
    """Raw booking call, so refusals can be inspected as well as successes."""
    return api.create_enclave_session(
        F.enclave_session_payload(
            enclave_id,
            dataset_id,
            start_at,
            end_at,
            document_count,
            purpose=purpose,
        ),
        headers if headers is not None else legal_headers(),
    )


def _sessions_of(api, enclave_id):
    """The enclave's session listing -- the only read surface on its occupancy."""
    return validate_paginated_page(
        api.list_enclave_sessions(
            legal_headers(),
            {"enclave_id": enclave_id, "limit": 10, "offset": 0},
        )
    )


def _statuses_of(api, enclave_id):
    """The multiset of session statuses currently recorded for the enclave."""
    rows, meta = _sessions_of(api, enclave_id)
    return sorted(row["status"] for row in rows), meta


def _buffered_world(api) -> Dict[str, Any]:
    """A 30-minute-buffer enclave holding one ``BOOKED`` session 09:00-11:00.

    The session's buffered occupancy therefore runs up to ``11:30:00Z``,
    exclusive -- the instant PRD S3.9's worked example turns on.
    """
    X.set_clock(api, C.STD_CLOCK)
    desk = X.create_desk(api)
    agency = X.create_agency(api)
    request = X.released_request(
        api,
        desk["id"],
        agency["id"],
        subject_summary="Sensitive inspector narratives",
        requested_format=C.FORMAT_PDF_SCAN,
        estimated_page_count=200,
        waiver_requested=False,
        public_interest_score=75,
    )
    investigation = X.create_investigation(
        api, desk["id"], C.MODE_METHODOLOGY_ONLY, headline="What the narratives hid"
    )
    dataset = X.clean_locked_dataset(
        api,
        request["id"],
        investigation["id"],
        record_count=500,
        field_specs=[{"field_name": "narrative_text", "reidentification_risk": 7}],
        negotiated_format=C.FORMAT_PDF_SCAN,
        delivered_format=C.FORMAT_PDF_SCAN,
        sensitivity_tier="SOURCE_LINKED",
    )
    enclave = X.create_enclave(
        api, max_documents=20, sanitization_buffer_minutes=30
    )
    first_session = X.book_session(
        api,
        enclave["id"],
        dataset["id"],
        "2026-08-20T09:00:00Z",
        "2026-08-20T11:00:00Z",
        document_count=5,
        purpose="First pass over the narratives.",
    )
    return {
        "dataset": dataset,
        "enclave": enclave,
        "first_session": first_session,
    }


class TestEnclaveHalfOpenSpanWithSanitizationBuffer:
    """PRD S3.9's 11:29 / 11:30 worked example, to the minute."""

    def test_a_booking_one_minute_inside_the_buffer_is_refused(self, api):
        """11:29 falls strictly before the buffered upper bound of 11:30.

        PRD S3.9: "a candidate starting at `11:29:00Z` is refused because 11:29
        falls strictly before 11:30".

        Design: Difficulty/resource_temporal_overlap/enclave_session_half_open_span_with_sanitization_buffer
        """
        world = _buffered_world(api)
        response = _book(
            api,
            world["enclave"]["id"],
            world["dataset"]["id"],
            "2026-08-20T11:29:00Z",
            "2026-08-20T13:00:00Z",
            3,
            "Second pass, one minute inside the sanitization buffer.",
            headers=reporter_headers(),
        )
        validate_error(response, ERR_ENCLAVE_SESSION_OVERLAP)

        statuses, meta = _statuses_of(api, world["enclave"]["id"])
        assert meta["total_count"] == 1
        assert statuses == [C.SESSION_BOOKED]

    def test_a_booking_at_exactly_the_buffer_end_is_accepted(self, api):
        """11:30 is not strictly before 11:30, so the span is genuinely half-open.

        PRD S3.9: "a candidate starting at exactly `11:30:00Z` is accepted
        because 11:30 is not strictly before 11:30".

        Design: Difficulty/resource_temporal_overlap/enclave_session_half_open_span_with_sanitization_buffer
        """
        world = _buffered_world(api)
        second = validate_created(
            _book(
                api,
                world["enclave"]["id"],
                world["dataset"]["id"],
                "2026-08-20T11:30:00Z",
                "2026-08-20T13:00:00Z",
                3,
                "Second pass, exactly at the end of the sanitization buffer.",
                headers=reporter_headers(),
            )
        )
        assert second["status"] == C.SESSION_BOOKED

        statuses, meta = _statuses_of(api, world["enclave"]["id"])
        assert meta["total_count"] == 2
        assert statuses == [C.SESSION_BOOKED, C.SESSION_BOOKED]

    def test_closing_the_incumbent_reconciles_it_and_never_cancels_it(self, api):
        """Closure accounts for all five documents and leaves the room in ``CLOSED``.

        PRD S3.9: "it drives `BOOKED -> CLOSED`, decrements the enclave's
        `booked_session_count` by 1, increments the enclave's `version` by 1, and
        releases the occupancy span so a later booking may reuse it."

        Design: Difficulty/resource_temporal_overlap/enclave_session_half_open_span_with_sanitization_buffer
        """
        world = _buffered_world(api)
        validate_created(
            _book(
                api,
                world["enclave"]["id"],
                world["dataset"]["id"],
                "2026-08-20T11:30:00Z",
                "2026-08-20T13:00:00Z",
                3,
                "Second pass, exactly at the end of the sanitization buffer.",
                headers=reporter_headers(),
            )
        )
        closed = X.close_session(api, world["first_session"]["id"], 5)
        assert closed["status"] == C.SESSION_CLOSED
        assert closed["documents_returned_count"] == 5
        assert_field_absent_or_null(
            closed, "cancellation_reason_code", "closed session"
        )

        statuses, meta = _statuses_of(api, world["enclave"]["id"])
        assert meta["total_count"] == 2
        assert statuses == [C.SESSION_BOOKED, C.SESSION_CLOSED]

    def test_the_vacated_span_becomes_bookable_again(self, api):
        """A window inside the closed session's old span is now free.

        PRD S3.9: "Sessions in `CLOSED` or `CANCELLED` status never conflict."

        Design: Difficulty/resource_temporal_overlap/enclave_session_half_open_span_with_sanitization_buffer
        """
        world = _buffered_world(api)
        validate_created(
            _book(
                api,
                world["enclave"]["id"],
                world["dataset"]["id"],
                "2026-08-20T11:30:00Z",
                "2026-08-20T13:00:00Z",
                3,
                "Second pass, exactly at the end of the sanitization buffer.",
                headers=reporter_headers(),
            )
        )
        X.close_session(api, world["first_session"]["id"], 5)

        third = validate_created(
            _book(
                api,
                world["enclave"]["id"],
                world["dataset"]["id"],
                "2026-08-20T10:00:00Z",
                "2026-08-20T10:30:00Z",
                2,
                "Short check inside the span S1 has now vacated.",
                headers=reporter_headers(),
            )
        )
        assert third["status"] == C.SESSION_BOOKED

        statuses, meta = _statuses_of(api, world["enclave"]["id"])
        assert meta["total_count"] == 3
        assert statuses == [
            C.SESSION_BOOKED,
            C.SESSION_BOOKED,
            C.SESSION_CLOSED,
        ]


_GATE_START = "2026-09-10T09:00:00Z"
_GATE_END = "2026-09-10T11:00:00Z"


def _gate_world(api) -> Dict[str, Any]:
    """One ``CLEAN_LOCKED`` dataset, one still ``CLEANING``, and a 5-document room."""
    X.set_clock(api, C.STD_CLOCK)
    desk = X.create_desk(api)
    agency = X.create_agency(
        api,
        name="Sealed Records Office",
        jurisdiction_code="CA-SEAL",
        tolling_allowed=False,
        appeal_venue=C.VENUE_INTERNAL,
        appeal_decision_days=15,
        holiday_dates=F.OMIT,
    )
    request = X.released_request(
        api,
        desk["id"],
        agency["id"],
        subject_summary="Sealed intake logs",
        requested_format=C.FORMAT_PDF_SCAN,
        estimated_page_count=40,
        waiver_requested=False,
        public_interest_score=50,
    )
    investigation = X.create_investigation(
        api, desk["id"], C.MODE_METHODOLOGY_ONLY, headline="Sealed intake logs probe"
    )
    locked_dataset = X.clean_locked_dataset(
        api,
        request["id"],
        investigation["id"],
        record_count=120,
        field_specs=[{"field_name": "intake_id", "reidentification_risk": 2}],
        negotiated_format=C.FORMAT_PDF_SCAN,
        delivered_format=C.FORMAT_PDF_SCAN,
        sensitivity_tier="CONFIDENTIAL",
    )
    cleaning_dataset = X.delivered_dataset(
        api,
        request["id"],
        investigation["id"],
        record_count=60,
        delivered_format=C.FORMAT_PDF_SCAN,
        negotiated_format=C.FORMAT_PDF_SCAN,
        expected_field_count=1,
        sensitivity_tier="CONFIDENTIAL",
    )
    enclave = X.create_enclave(
        api, max_documents=5, sanitization_buffer_minutes=30
    )
    return {
        "locked_dataset": locked_dataset,
        "cleaning_dataset": cleaning_dataset,
        "enclave": enclave,
    }


class TestEnclaveBookingGatesDatasetStateAndDocumentCeiling:
    """The four booking gates of PRD S3.9, in ascending order."""

    def test_an_unresolvable_enclave_is_reported_before_any_business_gate(
        self, api
    ):
        """The referential check on ``enclave_id`` answers first.

        PRD S2.5: "Each entity has its own not-found code, all at HTTP 404: ...
        `ERR_ENCLAVE_NOT_FOUND` (raised for the supplied `enclave_id`)".

        Design: Corner/validations/enclave_booking_gates_read_the_dataset_state_and_the_document_ceiling
        """
        world = _gate_world(api)
        response = _book(
            api,
            C.UNRESOLVABLE_ID,
            world["locked_dataset"]["id"],
            _GATE_START,
            _GATE_END,
            3,
            "Unresolvable enclave probe.",
        )
        validate_error(response, ERR_ENCLAVE_NOT_FOUND)

        _, meta = _sessions_of(api, world["enclave"]["id"])
        assert meta["total_count"] == 0

    def test_a_still_cleaning_dataset_is_refused(self, api):
        """``CLEANING`` is outside the admissible set of two states.

        PRD S3.9: "And the dataset must be `CLEAN_LOCKED` or `QUARANTINED` -- a
        raw or in-cleaning dataset has no reviewable document set -- otherwise
        `ERR_INVALID_DATASET_STATE`."

        Design: Corner/validations/enclave_booking_gates_read_the_dataset_state_and_the_document_ceiling
        """
        world = _gate_world(api)
        response = _book(
            api,
            world["enclave"]["id"],
            world["cleaning_dataset"]["id"],
            _GATE_START,
            _GATE_END,
            3,
            "Still-cleaning dataset probe.",
        )
        validate_error(response, ERR_INVALID_DATASET_STATE)

    def test_the_document_ceiling_answers_before_the_dataset_state(self, api):
        """Six documents against a ceiling of five wins over the state gate.

        PRD S3.9: "The `document_count` must not exceed the enclave's
        `max_documents`, otherwise `ERR_ENCLAVE_DOCUMENT_LIMIT`."

        Design: Corner/validations/enclave_booking_gates_read_the_dataset_state_and_the_document_ceiling
        """
        world = _gate_world(api)
        both_gates = _book(
            api,
            world["enclave"]["id"],
            world["cleaning_dataset"]["id"],
            _GATE_START,
            _GATE_END,
            6,
            "Both gates violated at once.",
        )
        validate_error(both_gates, ERR_ENCLAVE_DOCUMENT_LIMIT)

        ceiling_only = _book(
            api,
            world["enclave"]["id"],
            world["locked_dataset"]["id"],
            _GATE_START,
            _GATE_END,
            6,
            "One document over the ceiling.",
        )
        validate_error(ceiling_only, ERR_ENCLAVE_DOCUMENT_LIMIT)

    def test_exactly_at_the_ceiling_books_and_the_refusals_left_no_rows(self, api):
        """Five documents is admissible, and the four refusals persisted nothing.

        PRD S3.9: "A booked session opens in `BOOKED` with `opened_by_user_id`
        from `X-User-ID` and `documents_returned_count` and
        `cancellation_reason_code` both null, and increments the enclave's
        `booked_session_count` and `version` by 1."

        Design: Corner/validations/enclave_booking_gates_read_the_dataset_state_and_the_document_ceiling
        """
        world = _gate_world(api)
        validate_error(
            _book(
                api,
                C.UNRESOLVABLE_ID,
                world["locked_dataset"]["id"],
                _GATE_START,
                _GATE_END,
                3,
                "Unresolvable enclave probe.",
            ),
            ERR_ENCLAVE_NOT_FOUND,
        )
        validate_error(
            _book(
                api,
                world["enclave"]["id"],
                world["cleaning_dataset"]["id"],
                _GATE_START,
                _GATE_END,
                3,
                "Still-cleaning dataset probe.",
            ),
            ERR_INVALID_DATASET_STATE,
        )
        validate_error(
            _book(
                api,
                world["enclave"]["id"],
                world["cleaning_dataset"]["id"],
                _GATE_START,
                _GATE_END,
                6,
                "Both gates violated at once.",
            ),
            ERR_ENCLAVE_DOCUMENT_LIMIT,
        )
        validate_error(
            _book(
                api,
                world["enclave"]["id"],
                world["locked_dataset"]["id"],
                _GATE_START,
                _GATE_END,
                6,
                "One document over the ceiling.",
            ),
            ERR_ENCLAVE_DOCUMENT_LIMIT,
        )

        booked = validate_created(
            _book(
                api,
                world["enclave"]["id"],
                world["locked_dataset"]["id"],
                _GATE_START,
                _GATE_END,
                5,
                "Re-check the intake narratives.",
            )
        )
        assert booked["status"] == C.SESSION_BOOKED
        assert booked["opened_by_user_id"] == U.LEGAL_ID
        assert_field_absent_or_null(
            booked, "documents_returned_count", "new session"
        )
        assert_field_absent_or_null(
            booked, "cancellation_reason_code", "new session"
        )

        rows, meta = _sessions_of(api, world["enclave"]["id"])
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert [row["id"] for row in rows] == [booked["id"]]


_SECOND_START = "2026-09-10T11:15:00Z"
_SECOND_END = "2026-09-10T12:00:00Z"


def _closure_world(api) -> Dict[str, Any]:
    """A ``BOOKED`` session over 09:00-11:00 checking out four documents."""
    world = _gate_world(api)
    world["session"] = X.book_session(
        api,
        world["enclave"]["id"],
        world["locked_dataset"]["id"],
        _GATE_START,
        _GATE_END,
        document_count=4,
        purpose="First read of the intake logs.",
    )
    return world


def _close(api, session_id, documents_returned_count):
    """Raw closure call, so a reconciliation failure can be inspected."""
    return api.close_enclave_session(
        session_id,
        F.session_closure_payload(documents_returned_count),
        legal_headers(),
    )


def _second_booking(api, world):
    """The candidate that sits inside the incumbent's sanitization buffer."""
    return _book(
        api,
        world["enclave"]["id"],
        world["locked_dataset"]["id"],
        _SECOND_START,
        _SECOND_END,
        2,
        "Second read, inside the sanitization buffer.",
        headers=reporter_headers(),
    )


class TestEnclaveClosureReconcilesThenFreesTheWindow:
    """Closure is a reconciliation first and a release second (PRD S3.9)."""

    def test_an_unreconciled_closure_is_refused_and_moves_nothing(self, api):
        """Three documents returned against four checked out is a refusal.

        PRD S3.9: "Closing it is shared between `LegalCounsel` and `DataReporter`
        and requires the `documents_returned_count` supplied to equal the
        session's `document_count` exactly -- every document accounted for --
        otherwise `ERR_INVALID_REQUEST`."

        Design: Corner/endpoints/enclave_closure_reconciles_the_document_count_and_then_frees_the_window
        """
        world = _closure_world(api)
        validate_error(_close(api, world["session"]["id"], 3), ERR_INVALID_REQUEST)

        session = validate_ok(
            api.get_enclave_session(world["session"]["id"], legal_headers())
        )
        assert session["status"] == C.SESSION_BOOKED
        assert_version_is(session, 1, "unreconciled session")
        assert_field_absent_or_null(
            session, "documents_returned_count", "unreconciled session"
        )

    def test_the_still_booked_session_holds_its_buffered_window(self, api):
        """11:15 falls inside the buffer that runs the occupancy out to 11:30.

        PRD S3.9: "A candidate conflicts with an existing `BOOKED` session when
        the candidate's `start_at` is strictly before that session's
        end-plus-buffer **and** that session's `start_at` is strictly before the
        candidate's own end-plus-buffer."

        Design: Corner/endpoints/enclave_closure_reconciles_the_document_count_and_then_frees_the_window
        """
        world = _closure_world(api)
        validate_error(_close(api, world["session"]["id"], 3), ERR_INVALID_REQUEST)
        validate_error(_second_booking(api, world), ERR_ENCLAVE_SESSION_OVERLAP)

        statuses, meta = _statuses_of(api, world["enclave"]["id"])
        assert meta["total_count"] == 1
        assert statuses == [C.SESSION_BOOKED]

    def test_closure_succeeds_once_and_the_replay_is_a_refusal(self, api):
        """A closed session accepts no second closure, idempotent or otherwise.

        PRD S3.9: "Closure is only declared from `BOOKED`, otherwise
        `ERR_INVALID_SESSION_STATE`".

        Design: Corner/endpoints/enclave_closure_reconciles_the_document_count_and_then_frees_the_window
        """
        world = _closure_world(api)
        closed = validate_ok(_close(api, world["session"]["id"], 4))
        assert closed["status"] == C.SESSION_CLOSED
        assert closed["documents_returned_count"] == 4
        assert_version_is(closed, 2, "closed session")

        validate_error(
            _close(api, world["session"]["id"], 4), ERR_INVALID_SESSION_STATE
        )
        replayed = validate_ok(
            api.get_enclave_session(world["session"]["id"], legal_headers())
        )
        assert replayed["status"] == C.SESSION_CLOSED
        assert replayed["documents_returned_count"] == 4
        assert_version_is(replayed, 2, "closed session after the replay")

    def test_the_released_window_accepts_the_previously_refused_booking(self, api):
        """The identical payload that was refused is now accepted.

        PRD S3.9: "it drives `BOOKED -> CLOSED`, decrements the enclave's
        `booked_session_count` by 1, increments the enclave's `version` by 1, and
        releases the occupancy span so a later booking may reuse it."

        Design: Corner/endpoints/enclave_closure_reconciles_the_document_count_and_then_frees_the_window
        """
        world = _closure_world(api)
        validate_error(_second_booking(api, world), ERR_ENCLAVE_SESSION_OVERLAP)
        validate_ok(_close(api, world["session"]["id"], 4))

        reopened = validate_created(_second_booking(api, world))
        assert reopened["status"] == C.SESSION_BOOKED

        statuses, meta = _statuses_of(api, world["enclave"]["id"])
        assert meta["total_count"] == 2
        assert statuses == [C.SESSION_BOOKED, C.SESSION_CLOSED]
