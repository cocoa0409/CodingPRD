"""Standing up the desk and its agency register (PRD S3.1).

This module covers the registry surface at the very bottom of the system: the
desk registration that opens the fee-budget ledger and the exposure counters,
the immutable agency profile and its bounded fee schedule, the signed budget
adjustment that must keep the conserved identity of PRD S2.7 intact, the shared
shape of every error envelope across the status classes of PRD S5, and the
role-exclusivity ladder of PRD S2.11.

The harness restarts the server and wipes the database before every test, so
each test builds all of its own preconditions through the endpoints of PRD S4.
"""

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_FEE_BUDGET_EXCEEDED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_REQUEST_STATE,
    ERR_REQUEST_NOT_FOUND,
    ERR_ROLE_NOT_PERMITTED,
    ERR_STALE_DESK_VERSION,
    ERR_TOLLING_NOT_PERMITTED,
    ERR_UNAUTHENTICATED,
)
from test_helpers.assertions import (
    assert_agency_has_no_mutable_common_fields,
    assert_audit_timestamp_format,
    assert_deadline_stamp,
    assert_ledger_columns,
    assert_ledger_identity,
    assert_version_is,
    validate_created,
    validate_error,
    validate_ok,
    validate_paginated_page,
)
from test_helpers.test_users import (
    coordinator_headers,
    editor_headers,
    headers_missing_role,
    legal_headers,
    peer_reviewer_headers,
    reporter_headers,
)

# --------------------------------------------------------------------------
# Module-private helpers (nothing here belongs in the shared helper modules)
# --------------------------------------------------------------------------


def _assert_error_envelope_shape(response):
    """Assert the three-part error envelope of PRD S2.2 on one refusal."""
    body = response.json()
    assert body["response_type"] == "error", (
        f"a refusal must set response_type to error, got {body['response_type']!r}"
    )
    assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}, (
        "an error meta block carries only api_request_id and "
        f"api_request_timestamp, got {sorted(body['meta'])}"
    )
    error_id = body["data"]["error_id"]
    message = body["data"]["message"]
    assert isinstance(error_id, str) and error_id, (
        f"error_id must be a non-empty string, got {error_id!r}"
    )
    assert isinstance(message, str) and message, (
        f"message must be a non-empty string, got {message!r}"
    )
    return error_id


# A fee schedule that bills only search time, so one search hour commits a
# round 4000 cents and the ledger arithmetic is unambiguous.
_LEDGER_AGENCY = {
    "name": "County Assessor",
    "jurisdiction_code": "CA-COUNTY",
    "statute_name": "CPRA",
    "initial_response_days": 10,
    "deadline_basis": C.BUSINESS_DAYS,
    "tolling_allowed": True,
    "appeal_venue": C.VENUE_INTERNAL,
    "appeal_decision_days": 20,
    "search_fee_cents_per_hour": 4000,
    "page_fee_cents": 0,
    "max_waiver_cents": 0,
}

_LEDGER_REQUEST = {
    "subject_summary": "Ledger probe",
    "estimated_page_count": 0,
    "waiver_requested": False,
    "public_interest_score": 0,
}


def _desk_with_one_commitment(api):
    """A 100000-cent desk carrying exactly 4000 cents of committed records fee.

    One search hour at 4000 cents per hour with no billed pages and no waiver
    requested makes the net fee 4000 cents, which PRD S3.3 commits against the
    desk, leaving the ledger at total 100000, available 96000, committed 4000.
    """
    X.set_clock(api, C.STD_CLOCK)
    desk = X.create_desk(api, fee_budget_total_cents=100000, retention_policy_days=365)
    agency = X.create_agency(api, **_LEDGER_AGENCY)
    X.fee_determined_request(
        api,
        desk["id"],
        agency["id"],
        search_hours=1.0,
        billed_page_count=0,
        request_overrides=dict(_LEDGER_REQUEST),
    )
    return X.read_desk(api, desk["id"])


def _thin_budget_setup(api):
    """A 1000-cent desk, a no-tolling agency and one submitted request.

    Returns ``(desk_id, agency_id, request_id, stale_desk_version)`` where the
    captured version was read *before* the records-request create bumped it.
    """
    X.set_clock(api, C.STD_CLOCK)
    desk = X.create_desk(
        api,
        name="Thin Budget Desk",
        fee_budget_total_cents=1000,
        retention_policy_days=365,
    )
    agency = X.create_agency(
        api,
        name="No Tolling Board",
        jurisdiction_code="CA-NOTL",
        tolling_allowed=False,
        appeal_venue=C.VENUE_INTERNAL,
        appeal_decision_days=15,
        max_waiver_cents=0,
    )
    stale_version = X.desk_version(api, desk["id"])
    request = X.submitted_request(
        api,
        desk["id"],
        agency["id"],
        subject_summary="Envelope probe",
        estimated_page_count=10,
        waiver_requested=False,
        public_interest_score=0,
    )
    return desk["id"], agency["id"], request["id"], stale_version


def _role_matrix_setup(api):
    """A desk, an agency, a released request, an investigation and a dataset.

    The dataset is delivered (so it sits in ``CLEANING``, which PRD S3.6 admits
    field documentation from) and carries two documented columns, which is what
    the shared field-suppression operation needs.
    """
    X.set_clock(api, C.STD_CLOCK)
    desk = X.create_desk(api)
    agency = X.create_agency(api)
    request = X.released_request(
        api,
        desk["id"],
        agency["id"],
        subject_summary="Role matrix probe",
        estimated_page_count=10,
        waiver_requested=False,
        public_interest_score=10,
    )
    investigation = X.create_investigation(
        api,
        desk["id"],
        C.MODE_METHODOLOGY_ONLY,
        headline="Role matrix probe",
    )
    dataset = X.delivered_dataset(
        api,
        request["id"],
        investigation["id"],
        record_count=300,
        name=F.unique_dataset_name("role-matrix"),
        expected_field_count=2,
        sensitivity_tier="RESTRICTED",
    )
    fields = X.document_fields(
        api,
        dataset["id"],
        [
            {
                "field_name": "unit_id",
                "reidentification_risk": 3,
                "null_rate_pct": 0.0,
            },
            {
                "field_name": "tenant_initials",
                "reidentification_risk": 5,
                "null_rate_pct": 0.0,
            },
        ],
    )
    return {
        "desk": desk,
        "agency": agency,
        "request": request,
        "investigation": investigation,
        "dataset": dataset,
        "fields": fields,
    }


class TestDeskRegistration:
    """The desk registration of PRD S3.1 and the envelope of PRD S2.2."""

    def test_desk_creation_returns_the_standard_success_envelope(self, api):
        """A desk registration answers 201 inside the standard success envelope.

        PRD S2.2: "The api_request_id is a server-generated unique identifier
        for the request that starts with req_."

        PRD S2.2: "The response_type is either "object" for a single resource or
        "array" for a list of resources."

        Design: Corner/entities/desk_creation_initializes_the_ledger_the_counters_and_the_envelope
        """
        X.set_clock(api, C.STD_CLOCK)
        response = api.create_desk(
            F.desk_payload(
                name="Metro Investigations Desk",
                fee_budget_total_cents=250000,
                retention_policy_days=400,
            ),
            editor_headers(),
        )
        desk = validate_created(response)
        body = response.json()

        request_id = body["meta"]["api_request_id"]
        assert isinstance(request_id, str) and request_id, (
            f"meta.api_request_id must be a non-empty string, got {request_id!r}"
        )
        assert request_id.startswith("req_"), (
            f"meta.api_request_id must start with req_, got {request_id!r}"
        )
        assert_audit_timestamp_format(
            body["meta"]["api_request_timestamp"], "meta.api_request_timestamp"
        )
        assert body["response_type"] == "object", (
            f"a single desk is an object response, got {body['response_type']!r}"
        )
        assert isinstance(desk["id"], str) and desk["id"], (
            f"desk id must be a non-empty string, got {desk['id']!r}"
        )
        assert desk["name"] == "Metro Investigations Desk"
        assert desk["retention_policy_days"] == 400

    def test_desk_creation_opens_the_ledger_fully_unencumbered(self, api):
        """The four ledger columns open with everything in the available column.

        PRD S3.1: "At registration the ledger opens fully unencumbered:
        fee_budget_available_cents equals fee_budget_total_cents while
        fee_budget_committed_cents and fee_budget_spent_cents are both zero".

        Design: Corner/entities/desk_creation_initializes_the_ledger_the_counters_and_the_envelope
        """
        X.set_clock(api, C.STD_CLOCK)
        desk = validate_created(
            api.create_desk(
                F.desk_payload(
                    name="Metro Investigations Desk",
                    fee_budget_total_cents=250000,
                    retention_policy_days=400,
                ),
                editor_headers(),
            )
        )
        assert desk["fee_budget_total_cents"] == 250000
        assert_ledger_columns(desk, 250000, 250000, 0, 0)

    def test_desk_creation_zeroes_the_counters_and_opens_the_posture(self, api):
        """All four exposure counters start at zero and the posture is OPEN.

        PRD S3.1: "open_request_count, open_appeal_count,
        litigation_exposure_count and source_exposure_incident_count are all
        zero, and security_posture is OPEN".

        Design: Corner/entities/desk_creation_initializes_the_ledger_the_counters_and_the_envelope
        """
        X.set_clock(api, C.STD_CLOCK)
        desk = validate_created(
            api.create_desk(
                F.desk_payload(
                    name="Metro Investigations Desk",
                    fee_budget_total_cents=250000,
                    retention_policy_days=400,
                ),
                editor_headers(),
            )
        )
        assert desk["open_request_count"] == 0
        assert desk["open_appeal_count"] == 0
        assert desk["litigation_exposure_count"] == 0
        assert desk["source_exposure_incident_count"] == 0
        assert desk["security_posture"] == C.POSTURE_OPEN

    def test_desk_creation_stamps_version_one_and_both_audit_timestamps(self, api):
        """A fresh desk is at version 1 with both audit instants stamped.

        PRD S2.4: "version, an integer that starts at 1 on creation and
        increases by exactly 1 on every mutation of the row".

        Design: Corner/entities/desk_creation_initializes_the_ledger_the_counters_and_the_envelope
        """
        X.set_clock(api, C.STD_CLOCK)
        desk = validate_created(
            api.create_desk(
                F.desk_payload(
                    name="Metro Investigations Desk",
                    fee_budget_total_cents=250000,
                    retention_policy_days=400,
                ),
                editor_headers(),
            )
        )
        assert_version_is(desk, 1, "desk")
        assert_audit_timestamp_format(desk["created_at"], "desk.created_at")
        assert_audit_timestamp_format(desk["updated_at"], "desk.updated_at")


class TestAgencyRegistrationValidation:
    """The bounded agency profile of PRD S3.1."""

    def test_a_lowercase_jurisdiction_code_is_rejected(self, api):
        """A jurisdiction code inside the length bound still fails the charset.

        PRD S3.1: "a jurisdiction_code of 2 to 16 characters containing only
        uppercase letters and hyphens".

        Design: Corner/entities/agency_creation_rejects_bad_enums_and_out_of_range_numbers
        """
        X.set_clock(api, C.STD_CLOCK)
        # "ca-state" is 8 characters, so only the charset rule can refuse it.
        validate_error(
            api.create_agency(
                F.agency_payload(jurisdiction_code="ca-state"),
                coordinator_headers(),
            ),
            ERR_INVALID_REQUEST,
        )

    def test_initial_response_days_above_its_maximum_is_rejected(self, api):
        """Sixty-one statutory response days is one past the declared ceiling.

        PRD S3.1: "the initial_response_days between 1 and 60 that the agency
        has to answer a submitted request".

        Design: Corner/entities/agency_creation_rejects_bad_enums_and_out_of_range_numbers
        """
        X.set_clock(api, C.STD_CLOCK)
        validate_error(
            api.create_agency(
                F.agency_payload(initial_response_days=61),
                coordinator_headers(),
            ),
            ERR_INVALID_REQUEST,
        )

    def test_a_deadline_basis_outside_the_enum_is_rejected(self, api):
        """A plausible but undeclared deadline basis is refused.

        PRD S2.6: "Each agency declares a deadline_basis of either
        CALENDAR_DAYS or BUSINESS_DAYS".

        Design: Corner/entities/agency_creation_rejects_bad_enums_and_out_of_range_numbers
        """
        X.set_clock(api, C.STD_CLOCK)
        validate_error(
            api.create_agency(
                F.agency_payload(deadline_basis="WEEKDAYS"),
                coordinator_headers(),
            ),
            ERR_INVALID_REQUEST,
        )

    def test_a_page_fee_above_its_maximum_is_rejected(self, api):
        """A per-page fee of 1001 cents is one cent past the declared ceiling.

        PRD S3.1: "a fee schedule made of search_fee_cents_per_hour (0 to
        50000), page_fee_cents (0 to 1000) and max_waiver_cents".

        Design: Corner/entities/agency_creation_rejects_bad_enums_and_out_of_range_numbers
        """
        X.set_clock(api, C.STD_CLOCK)
        validate_error(
            api.create_agency(
                F.agency_payload(page_fee_cents=1001),
                coordinator_headers(),
            ),
            ERR_INVALID_REQUEST,
        )

    def test_every_numeric_field_on_its_inclusive_bound_is_accepted(self, api):
        """The bounds are inclusive, so an agency sitting on all of them stands.

        PRD S3.1: "the appeal_decision_days between 1 and 90 that the venue has
        to decide a filed appeal".

        PRD S3.1: "a fee schedule made of search_fee_cents_per_hour (0 to
        50000), page_fee_cents (0 to 1000) and max_waiver_cents".

        Design: Corner/entities/agency_creation_rejects_bad_enums_and_out_of_range_numbers
        """
        X.set_clock(api, C.STD_CLOCK)
        agency = validate_created(
            api.create_agency(
                F.agency_payload(
                    name="Boundary Agency",
                    jurisdiction_code="CA-BOUND",
                    initial_response_days=60,
                    deadline_basis=C.CALENDAR_DAYS,
                    tolling_allowed=False,
                    appeal_venue=C.VENUE_COURT,
                    appeal_decision_days=90,
                    search_fee_cents_per_hour=50000,
                    page_fee_cents=1000,
                    max_waiver_cents=0,
                ),
                editor_headers(),
            )
        )
        assert agency["initial_response_days"] == 60
        assert agency["appeal_decision_days"] == 90
        assert agency["search_fee_cents_per_hour"] == 50000
        assert agency["page_fee_cents"] == 1000
        assert agency["max_waiver_cents"] == 0
        # The four refused shapes above persisted nothing, so this is the only
        # readable agency row.
        stored = validate_ok(api.get_agency(agency["id"], coordinator_headers()))
        assert stored["id"] == agency["id"]


class TestAgencyImmutability:
    """The agency exception to the common mutable fields of PRD S2.4."""

    def test_agency_read_echoes_every_registered_input(self, api):
        """Everything the registration declared comes back verbatim.

        PRD S3.1: "An optional holiday_dates array of YYYY-MM-DD strings
        declares the non-working dates excluded from business-day counting".

        Design: Corner/entities/agency_is_immutable_and_exposes_no_version_or_update_surface
        """
        X.set_clock(api, C.STD_CLOCK)
        payload = F.agency_payload()
        agency = validate_created(api.create_agency(payload, coordinator_headers()))
        stored = validate_ok(api.get_agency(agency["id"], legal_headers()))
        for field, expected in payload.items():
            assert stored[field] == expected, (
                f"agency.{field} should echo the registered value {expected!r}, "
                f"got {stored[field]!r}"
            )
        assert stored["holiday_dates"] == ["2026-09-07"]

    def test_agency_exposes_neither_version_nor_updated_at(self, api):
        """The agency row carries only id and created_at, never a version.

        PRD S2.4: "An agency is an immutable statutory reference row: it carries
        only id and created_at. It has no updated_at, no version, and no update
        endpoint at all."

        Design: Corner/entities/agency_is_immutable_and_exposes_no_version_or_update_surface
        """
        X.set_clock(api, C.STD_CLOCK)
        created = validate_created(
            api.create_agency(F.agency_payload(), coordinator_headers())
        )
        assert_agency_has_no_mutable_common_fields(created)
        assert_audit_timestamp_format(created["created_at"], "agency.created_at")

        stored = validate_ok(api.get_agency(created["id"], legal_headers()))
        assert_agency_has_no_mutable_common_fields(stored)

    def test_the_frozen_agency_row_stamps_the_statutory_deadline(self, api):
        """A submitted request is stamped from the agency profile as registered.

        PRD S3.2: "due_at_strict is the unforgiving statutory deadline: take the
        UTC calendar date of submitted_at, advance it by initial_response_days on
        the agency's basis, and stamp the result at 23:59:59.000Z."

        Design: Corner/entities/agency_is_immutable_and_exposes_no_version_or_update_surface
        """
        X.set_clock(api, C.STD_CLOCK)
        desk = X.create_desk(api)
        agency = X.create_agency(api)
        request = X.submitted_request(
            api,
            desk["id"],
            agency["id"],
            estimated_page_count=10,
            waiver_requested=False,
            public_interest_score=10,
        )
        assert_deadline_stamp(request["due_at_strict"], "2026-08-17", "due_at_strict")


class TestBudgetAdjustmentLedger:
    """The signed budget adjustment of PRD S3.1 against the ledger of PRD S2.7."""

    def test_a_signed_delta_moves_the_total_and_available_columns_together(self, api):
        """A top-up and its exact claw-back leave the ledger where it started.

        PRD S3.1: "the delta is added to fee_budget_total_cents and to
        fee_budget_available_cents alike, which is what keeps the conserved
        identity of §2.7 intact".

        Design: Corner/state_machines/budget_adjustments_keep_the_desk_ledger_identity_and_refuse_to_go_negative
        """
        desk = _desk_with_one_commitment(api)
        assert_ledger_columns(desk, 100000, 96000, 4000, 0)
        assert_ledger_identity(desk)

        topped_up = validate_ok(
            api.create_budget_adjustment(
                desk["id"],
                F.budget_adjustment_payload(25000),
                editor_headers(),
            )
        )
        assert_ledger_columns(topped_up, 125000, 121000, 4000, 0)
        assert_ledger_identity(topped_up)

        clawed_back = validate_ok(
            api.create_budget_adjustment(
                desk["id"],
                F.budget_adjustment_payload(-25000),
                editor_headers(),
            )
        )
        assert_ledger_columns(clawed_back, 100000, 96000, 4000, 0)
        assert_ledger_identity(clawed_back)

    def test_a_claw_back_one_cent_past_available_is_refused(self, api):
        """The committed 4000 cents cannot be clawed back out from under itself.

        PRD S3.1: "A negative delta large enough to drive the available column
        below zero is refused with ERR_FEE_BUDGET_EXCEEDED and nothing is
        written."

        Design: Corner/state_machines/budget_adjustments_keep_the_desk_ledger_identity_and_refuse_to_go_negative
        """
        desk = _desk_with_one_commitment(api)
        validate_error(
            api.create_budget_adjustment(
                desk["id"],
                F.budget_adjustment_payload(-96001),
                editor_headers(),
            ),
            ERR_FEE_BUDGET_EXCEEDED,
        )
        after = X.read_desk(api, desk["id"])
        assert_ledger_columns(after, 100000, 96000, 4000, 0)
        assert_ledger_identity(after)

    def test_a_claw_back_landing_available_exactly_on_zero_is_accepted(self, api):
        """Draining the available column to exactly zero is not "below zero".

        PRD S2.7: "Any commit whose amount is strictly greater than the current
        available column is refused with ERR_FEE_BUDGET_EXCEEDED (HTTP 402), and
        nothing is written."

        Design: Corner/state_machines/budget_adjustments_keep_the_desk_ledger_identity_and_refuse_to_go_negative
        """
        desk = _desk_with_one_commitment(api)
        drained = validate_ok(
            api.create_budget_adjustment(
                desk["id"],
                F.budget_adjustment_payload(-96000),
                editor_headers(),
            )
        )
        assert_ledger_columns(drained, 4000, 0, 4000, 0)
        assert_ledger_identity(drained)

    def test_only_accepted_adjustments_advance_the_desk_version(self, api):
        """Each accepted delta is one mutation; the refused one is not a mutation.

        PRD S2.4: "version, an integer that starts at 1 on creation and
        increases by exactly 1 on every mutation of the row".

        Design: Corner/state_machines/budget_adjustments_keep_the_desk_ledger_identity_and_refuse_to_go_negative
        """
        desk = _desk_with_one_commitment(api)
        baseline = desk["version"]

        first = validate_ok(
            api.create_budget_adjustment(
                desk["id"], F.budget_adjustment_payload(25000), editor_headers()
            )
        )
        assert_version_is(first, baseline + 1, "desk after the first adjustment")

        second = validate_ok(
            api.create_budget_adjustment(
                desk["id"], F.budget_adjustment_payload(-25000), editor_headers()
            )
        )
        assert_version_is(second, baseline + 2, "desk after the second adjustment")

        validate_error(
            api.create_budget_adjustment(
                desk["id"], F.budget_adjustment_payload(-96001), editor_headers()
            ),
            ERR_FEE_BUDGET_EXCEEDED,
        )
        assert_version_is(
            X.read_desk(api, desk["id"]),
            baseline + 2,
            "desk after the refused adjustment",
        )


class TestErrorEnvelopePerStatusClass:
    """One envelope shape across every status class of PRD S5."""

    def test_the_identity_and_schema_classes_share_the_error_envelope(self, api):
        """401, 403, 404 and 400 all answer in the same three-part envelope.

        PRD S2.2: "The error_id is a unique, machine-readable string that
        identifies the specific error."

        PRD S2.1: "If either header is absent or empty, or if X-User-Role does
        not name one of the six roles below, the request is rejected with
        ERR_UNAUTHENTICATED (HTTP 401)."

        Design: Corner/errors/every_status_class_returns_the_same_error_envelope_with_a_distinct_code
        """
        desk_id, _agency_id, _request_id, _stale = _thin_budget_setup(api)

        unauthenticated = api.get_desk(desk_id, headers_missing_role())
        validate_error(unauthenticated, ERR_UNAUTHENTICATED)
        _assert_error_envelope_shape(unauthenticated)

        forbidden = api.create_desk(
            F.desk_payload(name="Reporter Desk", fee_budget_total_cents=1000),
            reporter_headers(),
        )
        validate_error(forbidden, ERR_ROLE_NOT_PERMITTED)
        _assert_error_envelope_shape(forbidden)

        missing = api.get_records_request(C.UNRESOLVABLE_ID, coordinator_headers())
        validate_error(missing, ERR_REQUEST_NOT_FOUND)
        _assert_error_envelope_shape(missing)

        malformed = api.create_agency(
            F.agency_payload(
                name="Bad Enum Agency",
                jurisdiction_code="ca-lower",
                deadline_basis="WEEKDAYS",
            ),
            coordinator_headers(),
        )
        validate_error(malformed, ERR_INVALID_REQUEST)
        _assert_error_envelope_shape(malformed)

    def test_the_state_and_version_classes_share_the_error_envelope(self, api):
        """409 and 412 answer in the same envelope with their own codes.

        PRD S2.11: "The target entity must be in a state from which the requested
        transition is declared."

        PRD S2.8: "If that value does not equal the desk's current version, the
        create is rejected with ERR_STALE_DESK_VERSION (HTTP 412) and nothing is
        written."

        Design: Corner/errors/every_status_class_returns_the_same_error_envelope_with_a_distinct_code
        """
        desk_id, agency_id, request_id, stale_version = _thin_budget_setup(api)

        conflict = api.submit_records_request(request_id, coordinator_headers())
        validate_error(conflict, ERR_INVALID_REQUEST_STATE)
        _assert_error_envelope_shape(conflict)

        validate_ok(
            api.create_budget_adjustment(
                desk_id, F.budget_adjustment_payload(500), editor_headers()
            )
        )
        stale = api.create_records_request(
            F.records_request_payload(
                desk_id,
                agency_id,
                stale_version,
                subject_summary="Second ask on a stale version",
                estimated_page_count=10,
                waiver_requested=False,
                public_interest_score=0,
            ),
            coordinator_headers(),
        )
        validate_error(stale, ERR_STALE_DESK_VERSION)
        _assert_error_envelope_shape(stale)

    def test_the_budget_and_business_rule_classes_share_the_error_envelope(self, api):
        """402 and 422 answer in the same envelope with their own codes.

        PRD S2.7: "Any commit whose amount is strictly greater than the current
        available column is refused with ERR_FEE_BUDGET_EXCEEDED (HTTP 402), and
        nothing is written."

        PRD S3.4: "The agency's tolling_allowed must be true; where the statute
        grants no tolling, the round is refused with ERR_TOLLING_NOT_PERMITTED."

        Design: Corner/errors/every_status_class_returns_the_same_error_envelope_with_a_distinct_code
        """
        desk_id, _agency_id, request_id, _stale = _thin_budget_setup(api)
        validate_ok(
            api.create_budget_adjustment(
                desk_id, F.budget_adjustment_payload(500), editor_headers()
            )
        )

        # One search hour bills 3500 cents against 1500 cents of available budget.
        unaffordable = api.determine_fee(
            request_id,
            F.fee_determination_payload(search_hours=1.0, billed_page_count=0),
            coordinator_headers(),
        )
        validate_error(unaffordable, ERR_FEE_BUDGET_EXCEEDED)
        _assert_error_envelope_shape(unaffordable)

        untollable = api.request_clarification(
            request_id,
            F.clarification_request_payload(),
            coordinator_headers(),
        )
        validate_error(untollable, ERR_TOLLING_NOT_PERMITTED)
        _assert_error_envelope_shape(untollable)

    def test_the_eight_status_classes_use_distinct_codes_and_write_nothing(self, api):
        """Eight refusals, eight distinct codes, and no state left behind.

        PRD S2.2: "The message provides a human-readable explanation of what
        went wrong."

        Design: Corner/errors/every_status_class_returns_the_same_error_envelope_with_a_distinct_code
        """
        desk_id, agency_id, request_id, stale_version = _thin_budget_setup(api)

        refusals = [
            api.get_desk(desk_id, headers_missing_role()),
            api.create_desk(
                F.desk_payload(name="Reporter Desk", fee_budget_total_cents=1000),
                reporter_headers(),
            ),
            api.get_records_request(C.UNRESOLVABLE_ID, coordinator_headers()),
            api.create_agency(
                F.agency_payload(
                    name="Bad Enum Agency",
                    jurisdiction_code="ca-lower",
                    deadline_basis="WEEKDAYS",
                ),
                coordinator_headers(),
            ),
            api.submit_records_request(request_id, coordinator_headers()),
        ]
        validate_ok(
            api.create_budget_adjustment(
                desk_id, F.budget_adjustment_payload(500), editor_headers()
            )
        )
        refusals.extend(
            [
                api.create_records_request(
                    F.records_request_payload(
                        desk_id,
                        agency_id,
                        stale_version,
                        estimated_page_count=10,
                        waiver_requested=False,
                        public_interest_score=0,
                    ),
                    coordinator_headers(),
                ),
                api.determine_fee(
                    request_id,
                    F.fee_determination_payload(search_hours=1.0, billed_page_count=0),
                    coordinator_headers(),
                ),
                api.request_clarification(
                    request_id, F.clarification_request_payload(), coordinator_headers()
                ),
            ]
        )

        codes = []
        for response in refusals:
            _assert_error_envelope_shape(response)
            codes.append(response.json()["data"]["error_id"])
        assert len(set(codes)) == len(codes) == 8, (
            f"each status class needs its own code, got {codes}"
        )

        # Nothing above was written: one request, no fee, no commitment.
        rows, meta = validate_paginated_page(
            api.list_records_requests(coordinator_headers(), {"desk_id": desk_id})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == request_id
        assert rows[0]["fee_determined_at"] is None
        desk = X.read_desk(api, desk_id)
        assert_ledger_columns(desk, 1500, 1500, 0, 0)
        assert_ledger_identity(desk)


class TestExclusiveOperationsRbac:
    """Role exclusivity (PRD S4) under the precedence ladder of PRD S2.11."""

    def test_an_exclusive_create_is_refused_to_the_other_role(self, api):
        """Neither role may borrow the other's exclusive creation endpoint.

        PRD S2.1: "If the role is recognised but is not among the roles the
        target endpoint admits, the rejection is ERR_ROLE_NOT_PERMITTED (HTTP
        403)."

        Design: Corner/rbac/exclusive_operations_are_refused_to_every_other_role_before_existence_is_checked
        """
        X.set_clock(api, C.STD_CLOCK)
        validate_error(
            api.create_desk(
                F.desk_payload(name="Reporter Desk", fee_budget_total_cents=1000),
                reporter_headers(),
            ),
            ERR_ROLE_NOT_PERMITTED,
        )

        desk = X.create_desk(api)
        agency = X.create_agency(api)
        validate_error(
            api.create_records_request(
                F.records_request_payload(
                    desk["id"], agency["id"], desk["version"]
                ),
                editor_headers(),
            ),
            ERR_ROLE_NOT_PERMITTED,
        )
        assert X.read_desk(api, desk["id"])["open_request_count"] == 0

    def test_the_role_check_runs_before_the_path_check(self, api):
        """Five exclusive operations refuse the wrong role on ids that cannot resolve.

        PRD S2.11: "the rules are evaluated in ascending priority order, and the
        first rule whose condition is violated determines the response".

        PRD S2.11: "The named role must appear in the target endpoint's
        authorized roles — otherwise ERR_ROLE_NOT_PERMITTED."

        Design: Corner/rbac/exclusive_operations_are_refused_to_every_other_role_before_existence_is_checked
        """
        X.set_clock(api, C.STD_CLOCK)
        refusals = [
            api.create_appeal(
                F.appeal_payload(
                    C.UNRESOLVABLE_ID, venue=C.VENUE_INTERNAL, filing_fee_cents=4500
                ),
                coordinator_headers(),
            ),
            api.publish_investigation(
                C.UNRESOLVABLE_ID, F.publication_payload(), legal_headers()
            ),
            api.submit_peer_review(
                C.UNRESOLVABLE_ID,
                F.peer_review_payload(C.REVIEW_APPROVED),
                reporter_headers(),
            ),
            api.submit_verdict(
                C.UNRESOLVABLE_ID,
                F.verdict_payload(C.VERDICT_CONFIRMED),
                peer_reviewer_headers(),
            ),
            api.quarantine_dataset(
                C.UNRESOLVABLE_ID, F.quarantine_payload(), reporter_headers()
            ),
        ]
        for response in refusals:
            validate_error(response, ERR_ROLE_NOT_PERMITTED)
            _assert_error_envelope_shape(response)

        # The refused appeal filing wrote nothing at all.
        _rows, meta = validate_paginated_page(api.list_appeals(legal_headers()))
        assert meta["total_count"] == 0

    def test_a_shared_operation_admits_both_of_its_declared_roles(self, api):
        """The two roles that share an operation may each perform it.

        PRD S3.1: "Agencies are the other half of the setup, and either a
        RecordsCoordinator or a ManagingEditor may register one."

        PRD S3.6: "Ahead of any release, a DataReporter or a ManagingEditor may
        suppress a documented column by naming its field_definition_id and the
        suppression_method used".

        Design: Corner/rbac/exclusive_operations_are_refused_to_every_other_role_before_existence_is_checked
        """
        bundle = _role_matrix_setup(api)
        dataset_id = bundle["dataset"]["id"]
        first_field, second_field = bundle["fields"]

        validate_created(
            api.create_agency(
                F.agency_payload(name="Editor Registered Board", jurisdiction_code="CA-EDIT"),
                editor_headers(),
            )
        )

        by_reporter = api.suppress_field(
            dataset_id,
            F.field_suppression_payload(
                first_field["id"], suppression_method="DROP_COLUMN"
            ),
            reporter_headers(),
        )
        validate_ok(by_reporter)
        by_editor = api.suppress_field(
            dataset_id,
            F.field_suppression_payload(
                second_field["id"], suppression_method="HASH_REDACT"
            ),
            editor_headers(),
        )
        validate_ok(by_editor)

        rows, meta = validate_paginated_page(
            api.list_field_definitions(dataset_id, coordinator_headers())
        )
        assert meta["total_count"] == 2
        by_id = {row["id"]: row for row in rows}
        assert by_id[first_field["id"]]["suppression_applied"] is True
        assert by_id[first_field["id"]]["suppression_method"] == "DROP_COLUMN"
        assert by_id[second_field["id"]]["suppression_applied"] is True
        assert by_id[second_field["id"]]["suppression_method"] == "HASH_REDACT"

    def test_every_read_is_open_to_every_role(self, api):
        """Roles with no write access to a resource may still read it.

        PRD S2.1: "Read access is uniform. All six roles may call every read
        endpoint and may set the logical clock."

        Design: Corner/rbac/exclusive_operations_are_refused_to_every_other_role_before_existence_is_checked
        """
        bundle = _role_matrix_setup(api)
        dataset_id = bundle["dataset"]["id"]

        as_peer = validate_ok(api.get_dataset(dataset_id, peer_reviewer_headers()))
        as_legal = validate_ok(api.get_dataset(dataset_id, legal_headers()))
        assert as_peer["id"] == dataset_id
        assert as_legal["id"] == dataset_id
        assert as_peer["field_definition_count"] == 2
        assert as_legal["field_definition_count"] == 2
