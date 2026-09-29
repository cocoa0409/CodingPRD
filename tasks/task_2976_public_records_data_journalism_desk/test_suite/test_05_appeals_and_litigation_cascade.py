"""Appeals, the five-hop litigation cascade and the appeal gate ladder.

Every test here builds its own world through the endpoints of PRD S4 -- the
harness wipes the database before each test -- and re-asserts the conserved
fee-budget identity of PRD S2.7 after every mutation that moves money.
"""

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers import test_users as U
from test_helpers.api_errors import (
    ERR_APPEAL_NOT_RIPE,
    ERR_APPEAL_VENUE_MISMATCH,
    ERR_INVALID_APPEAL_STATE,
)
from test_helpers.assertions import (
    assert_deadline_stamp,
    assert_instant_equals,
    assert_ledger_columns,
    assert_ledger_identity,
    validate_created,
    validate_error,
    validate_ok,
    validate_paginated_page,
)

# The rationale the venue records when it upholds the withholding.
_DENIAL_RATIONALE = "Ombuds upheld the deliberative-process withholding."
_GRANT_RATIONALE = "Ombuds orders release of the aggregate tables."

# The tolled deadline of the PRD S3.2 worked example: a request submitted on
# 2026-08-03 against an agency owing ten business days is due at
# 2026-08-17T23:59:59.000Z.
_DUE_AT_TOLLED = "2026-08-17T23:59:59.000Z"
_ONE_MS_BEFORE_DUE = "2026-08-17T23:59:58.999Z"
_ONE_MS_AFTER_DUE = "2026-08-17T23:59:59.001Z"


def _denial_cascade_world(api):
    """Build the five entity types one appeal denial has to reach.

    Appeal -> RecordsRequest -> Desk -> Investigation (reachable only by joining
    a Dataset's ``request_id`` to its ``investigation_id``) -> EnclaveSession
    (reachable only through that investigation's datasets).
    """
    X.set_clock(api, C.STD_CLOCK)
    desk, agency = X.desk_and_agency(api)
    request = X.submitted_request(
        api,
        desk["id"],
        agency["id"],
        subject_summary="Section 8 inspection failures 2024-2025",
        estimated_page_count=120,
        waiver_requested=True,
        public_interest_score=85,
    )
    # Net fee 5250 committed, then settled by the partial release (PRD S3.3, S3.4).
    validate_ok(
        api.determine_fee(
            request["id"],
            F.fee_determination_payload(3.5, 120),
            U.coordinator_headers(),
        )
    )
    request = validate_ok(
        api.record_agency_decision(
            request["id"],
            F.agency_decision_payload(C.OUTCOME_RELEASED_PARTIAL),
            U.coordinator_headers(),
        )
    )
    investigation = X.create_investigation(
        api,
        desk["id"],
        C.MODE_FULL_DATA_RELEASE,
        headline="Inspectors cleared failing units",
    )
    dataset = X.clean_locked_dataset(
        api,
        request["id"],
        investigation["id"],
        record_count=500,
        field_specs=[{"field_name": "inspection_id", "reidentification_risk": 2}],
        negotiated_format=C.FORMAT_CSV,
        sensitivity_tier="CONFIDENTIAL",
    )
    run = X.create_run(
        api, investigation["id"], compute_cost_cents=5000, labor_hours=1.0
    )
    enclave = X.create_enclave(
        api, name="Reading Room A", max_documents=20, sanitization_buffer_minutes=30
    )
    session = X.book_session(api, enclave["id"], dataset["id"])
    appeal = X.file_appeal(
        api,
        request["id"],
        filing_fee_cents=4500,
        grounds="The withheld inspector narratives are not deliberative.",
    )
    return {
        "desk": desk,
        "agency": agency,
        "request": request,
        "investigation": investigation,
        "dataset": dataset,
        "run": run,
        "enclave": enclave,
        "session": session,
        "appeal": appeal,
    }


def _deny_appeal(api, appeal_id):
    """Record the venue's denial -- the trigger of the deepest cascade."""
    return validate_ok(
        api.decide_appeal(
            appeal_id,
            F.appeal_decision_payload(
                C.APPEAL_DENIED, decision_rationale=_DENIAL_RATIONALE
            ),
            U.coordinator_headers(),
        )
    )


def _booked_sessions_of(api, enclave_id):
    """The enclave's still-``BOOKED`` sessions, read through the PRD S4 listing.

    PRD S4 exposes no read surface for a ``SecureEnclave``, so the enclave's
    booked-session bookkeeping is observed through the session listing it
    filters, which PRD S4 declares "filterable by ``enclave_id``, ``dataset_id``
    and ``status``".
    """
    rows, meta = validate_paginated_page(
        api.list_enclave_sessions(
            U.legal_headers(),
            params={"enclave_id": enclave_id, "status": C.SESSION_BOOKED},
        )
    )
    return rows, meta


class TestAppealDenialFiveHopLitigationCascade:
    """One denial decision propagating across five entity types (PRD S3.5)."""

    def test_denial_moves_the_appeal_and_authorizes_litigation_on_the_request(
        self, api
    ):
        """Hops one and two: the appeal is denied and the request is terminal.

        PRD S3.5: "Hop one: the appeal moves FILED -> DENIED and the
        decision_rationale is recorded. Hop two: because the appeal is now
        denied, the parent request moves APPEAL_FILED -> LITIGATION_AUTHORIZED,
        which is terminal."

        Design: Difficulty/transitive_cascade/appeal_denial_five_hop_litigation_cascade
        """
        world = _denial_cascade_world(api)

        decided = _deny_appeal(api, world["appeal"]["id"])

        assert decided["status"] == C.APPEAL_DENIED
        assert decided["decision_rationale"] == _DENIAL_RATIONALE

        appeal = validate_ok(
            api.get_appeal(world["appeal"]["id"], U.legal_headers())
        )
        assert appeal["status"] == C.APPEAL_DENIED
        assert appeal["decision_rationale"] == _DENIAL_RATIONALE

        request = validate_ok(
            api.get_records_request(world["request"]["id"], U.coordinator_headers())
        )
        assert request["status"] == C.REQ_LITIGATION_AUTHORIZED

    def test_denial_raises_litigation_exposure_and_recomputes_the_posture(self, api):
        """Hop three: the desk's exposure counters and derived posture move.

        PRD S3.5: "Hop three: because the request entered LITIGATION_AUTHORIZED,
        the desk's litigation_exposure_count increments by 1, its
        open_request_count decrements by 1, and security_posture is recomputed
        -- landing on RESTRICTED unless a source-exposure incident has already
        forced LOCKDOWN."

        Design: Difficulty/transitive_cascade/appeal_denial_five_hop_litigation_cascade
        """
        world = _denial_cascade_world(api)

        _deny_appeal(api, world["appeal"]["id"])

        desk = validate_ok(api.get_desk(world["desk"]["id"], U.editor_headers()))
        assert desk["litigation_exposure_count"] == 1
        assert desk["security_posture"] == C.POSTURE_RESTRICTED
        assert desk["open_request_count"] == 0
        assert desk["open_appeal_count"] == 0
        assert_ledger_identity(desk)

    def test_denial_holds_the_reachable_investigation_and_cancels_its_session(
        self, api
    ):
        """Hops four and five: the legal hold and the cancelled reading session.

        PRD S3.5: "Hop four: ... every investigation named as the
        investigation_id of a dataset whose request_id is this request -- whose
        status is ANALYSIS, FINDINGS_LOCKED or CLEARED moves to
        HOLD_LEGAL_REVIEW with hold_reason_code set to LITIGATION_AUTHORIZED.
        Hop five: ... every enclave session whose dataset belongs to one of them
        and whose status is BOOKED moves to CANCELLED with
        cancellation_reason_code set to INVESTIGATION_LEGAL_HOLD, decrementing
        the owning enclave's booked_session_count."

        Design: Difficulty/transitive_cascade/appeal_denial_five_hop_litigation_cascade
        """
        world = _denial_cascade_world(api)

        _deny_appeal(api, world["appeal"]["id"])

        investigation = validate_ok(
            api.get_investigation(world["investigation"]["id"], U.editor_headers())
        )
        assert investigation["status"] == C.INV_HOLD_LEGAL_REVIEW
        assert investigation["hold_reason_code"] == C.HOLD_REASON_LITIGATION_AUTHORIZED

        session = validate_ok(
            api.get_enclave_session(world["session"]["id"], U.legal_headers())
        )
        assert session["status"] == C.SESSION_CANCELLED
        assert (
            session["cancellation_reason_code"]
            == C.CANCEL_REASON_INVESTIGATION_LEGAL_HOLD
        )

        rows, meta = _booked_sessions_of(api, world["enclave"]["id"])
        assert rows == []
        assert meta["total_count"] == 0

    def test_denial_settles_the_filing_fee_without_ledger_drift(self, api):
        """The money the cascade moves: 5250 already spent plus the 4500 filing fee.

        PRD S3.5: "Alongside the cascade the filing_fee_cents settles from the
        committed column to the spent column, open_appeal_count decrements by 1,
        and the desk's version increments by 1."

        Design: Difficulty/transitive_cascade/appeal_denial_five_hop_litigation_cascade
        """
        world = _denial_cascade_world(api)

        before = validate_ok(api.get_desk(world["desk"]["id"], U.editor_headers()))
        assert_ledger_columns(
            before, total=500000, available=490250, committed=4500, spent=5250
        )

        _deny_appeal(api, world["appeal"]["id"])

        desk = validate_ok(api.get_desk(world["desk"]["id"], U.editor_headers()))
        assert_ledger_columns(
            desk, total=500000, available=490250, committed=0, spent=9750
        )

    def test_denial_leaves_the_dataset_and_the_analysis_run_untouched(self, api):
        """A row the cascade only inspects keeps its own state (PRD S2.4).

        PRD S2.4: "A row that a cascade inspects but does not change is left
        untouched, including its version."

        Design: Difficulty/transitive_cascade/appeal_denial_five_hop_litigation_cascade
        """
        world = _denial_cascade_world(api)

        _deny_appeal(api, world["appeal"]["id"])

        dataset = validate_ok(
            api.get_dataset(world["dataset"]["id"], U.reporter_headers())
        )
        assert dataset["status"] == C.DS_CLEAN_LOCKED

        run = validate_ok(
            api.get_analysis_run(world["run"]["id"], U.reporter_headers())
        )
        assert run["code_review_status"] == C.REVIEW_PENDING


def _overdue_candidate(api):
    """A request submitted 2026-08-03 with no clarification rounds.

    Ten business days on the agency's basis put both deadline variants at
    2026-08-17T23:59:59.000Z (PRD S3.2), which is the instant the delay ground
    is measured against.
    """
    X.set_clock(api, C.STD_CLOCK)
    desk, agency = X.desk_and_agency(api)
    request = X.submitted_request(
        api,
        desk["id"],
        agency["id"],
        subject_summary="Overdue inspection records",
        estimated_page_count=100,
        waiver_requested=False,
        public_interest_score=70,
    )
    return desk, agency, request


def _delay_ground_appeal(api, request_id):
    """Attempt a delay-ground appeal; the caller decides what the answer means."""
    return api.create_appeal(
        F.appeal_payload(
            request_id,
            venue=C.VENUE_OMBUDS,
            filing_fee_cents=4500,
            grounds="The agency blew the statutory deadline.",
        ),
        U.legal_headers(),
    )


class TestAppealRipenessAtTheExactTolledDeadlineMillisecond:
    """The delay ground is strictly-after, at millisecond resolution (PRD S3.5)."""

    def test_submission_stamps_both_deadline_variants_at_the_same_instant(self, api):
        """With no tolling accrued the enforceable deadline equals the strict one.

        PRD S3.2: "At submission tolled_days_total is zero, so the two variants
        coincide."

        Design: Difficulty/boundary_precision_check/appeal_ripeness_at_the_exact_tolled_deadline_millisecond
        """
        _desk, _agency, request = _overdue_candidate(api)

        assert request["tolled_days_total"] == 0
        assert_deadline_stamp(request["due_at_tolled"], "2026-08-17", "due_at_tolled")
        assert_deadline_stamp(request["due_at_strict"], "2026-08-17", "due_at_strict")
        assert_instant_equals(
            request["due_at_tolled"], request["due_at_strict"], "due_at_tolled"
        )

    def test_one_millisecond_before_the_tolled_deadline_the_appeal_is_not_ripe(
        self, api
    ):
        """A millisecond short of the deadline is still inside the response window.

        PRD S3.5: "A request still in AWAITING_AGENCY_RESPONSE is appealable only
        on the delay ground, and only when the logical clock is strictly after
        due_at_tolled."

        Design: Difficulty/boundary_precision_check/appeal_ripeness_at_the_exact_tolled_deadline_millisecond
        """
        desk, _agency, request = _overdue_candidate(api)
        X.set_clock(api, _ONE_MS_BEFORE_DUE)

        validate_error(_delay_ground_appeal(api, request["id"]), ERR_APPEAL_NOT_RIPE)

        after = validate_ok(
            api.get_records_request(request["id"], U.coordinator_headers())
        )
        assert after["status"] == C.REQ_AWAITING_AGENCY_RESPONSE
        desk_after = validate_ok(api.get_desk(desk["id"], U.editor_headers()))
        assert desk_after["open_appeal_count"] == 0
        assert_ledger_columns(
            desk_after, total=500000, available=500000, committed=0, spent=0
        )

    def test_at_exactly_the_tolled_deadline_the_appeal_is_not_ripe(self, api):
        """The deadline instant itself is not yet actionable, and nothing is written.

        PRD S3.5: "at the deadline instant itself the appeal is not yet ripe."

        Design: Difficulty/boundary_precision_check/appeal_ripeness_at_the_exact_tolled_deadline_millisecond
        """
        desk, _agency, request = _overdue_candidate(api)
        X.set_clock(api, _DUE_AT_TOLLED)

        validate_error(_delay_ground_appeal(api, request["id"]), ERR_APPEAL_NOT_RIPE)

        after = validate_ok(
            api.get_records_request(request["id"], U.coordinator_headers())
        )
        assert after["status"] == C.REQ_AWAITING_AGENCY_RESPONSE
        desk_after = validate_ok(api.get_desk(desk["id"], U.editor_headers()))
        assert desk_after["open_appeal_count"] == 0
        assert desk_after["fee_budget_committed_cents"] == 0
        assert_ledger_identity(desk_after)

    def test_one_millisecond_after_the_tolled_deadline_the_appeal_is_ripe(self, api):
        """The very next millisecond flips the same payload from refused to filed.

        PRD S3.5: "Ripeness reads due_at_tolled and never due_at_strict. A
        request in any other status, or an overdue claim that does not clear the
        tolled deadline, is refused with ERR_APPEAL_NOT_RIPE."

        Design: Difficulty/boundary_precision_check/appeal_ripeness_at_the_exact_tolled_deadline_millisecond
        """
        desk, _agency, request = _overdue_candidate(api)

        X.set_clock(api, _DUE_AT_TOLLED)
        validate_error(_delay_ground_appeal(api, request["id"]), ERR_APPEAL_NOT_RIPE)

        X.set_clock(api, _ONE_MS_AFTER_DUE)
        appeal = validate_created(_delay_ground_appeal(api, request["id"]))

        assert appeal["status"] == C.APPEAL_FILED_STATUS
        assert appeal["ripeness_basis"] == C.RIPENESS_OVERDUE
        assert appeal["venue"] == C.VENUE_OMBUDS
        assert_instant_equals(appeal["filed_at"], _ONE_MS_AFTER_DUE, "filed_at")
        assert_deadline_stamp(
            appeal["decision_due_at"], "2026-09-15", "decision_due_at"
        )

        after = validate_ok(
            api.get_records_request(request["id"], U.coordinator_headers())
        )
        assert after["status"] == C.REQ_APPEAL_FILED

        desk_after = validate_ok(api.get_desk(desk["id"], U.editor_headers()))
        assert desk_after["open_appeal_count"] == 1
        assert_ledger_columns(
            desk_after, total=500000, available=495500, committed=4500, spent=0
        )


def _denied_request(api):
    """A request the agency has denied -- appealable on the denial ground."""
    X.set_clock(api, C.STD_CLOCK)
    desk, agency = X.desk_and_agency(api, desk_overrides={"retention_policy_days": 365})
    request = X.submitted_request(
        api,
        desk["id"],
        agency["id"],
        subject_summary="Appeal fork probe",
        estimated_page_count=10,
        waiver_requested=False,
        public_interest_score=10,
    )
    request = validate_ok(
        api.record_agency_decision(
            request["id"],
            F.agency_decision_payload(
                C.OUTCOME_DENIED, denial_reason_code="EXEMPT_PRIVACY"
            ),
            U.coordinator_headers(),
        )
    )
    return desk, agency, request


def _file_denial_ground_appeal(api, request_id):
    """File the appeal the denial makes ripe, as ``legal-001``."""
    return validate_created(
        api.create_appeal(
            F.appeal_payload(
                request_id,
                venue=C.VENUE_OMBUDS,
                filing_fee_cents=4500,
                grounds=(
                    "The privacy exemption does not reach aggregate inspection "
                    "outcomes."
                ),
            ),
            U.legal_headers(U.LEGAL_ID),
        )
    )


class TestAppealGrantedBranchReturnsTheRequestToAwaiting:
    """The GRANTED prong reopens the request and spends the filing fee (PRD S3.5)."""

    def test_denial_ground_filing_commits_the_fee_and_stamps_the_decision_deadline(
        self, api
    ):
        """The filing itself: ripeness basis, audit trail and committed fee.

        PRD S3.5: "A request in DENIED is appealable on the denial ground, giving
        a ripeness_basis of DENIED", and "decision_due_at is computed by
        advancing the filed_at date by the agency's appeal_decision_days on the
        agency's deadline_basis and stamping the result at 23:59:59.000Z."

        Design: Corner/state_machines/appeal_granted_branch_returns_the_request_to_awaiting_and_settles_the_filing_fee
        """
        desk, _agency, request = _denied_request(api)

        appeal = _file_denial_ground_appeal(api, request["id"])

        assert appeal["status"] == C.APPEAL_FILED_STATUS
        assert appeal["ripeness_basis"] == C.RIPENESS_DENIED
        assert appeal["filed_by_user_id"] == U.LEGAL_ID
        assert_instant_equals(appeal["filed_at"], C.STD_CLOCK, "filed_at")
        assert_deadline_stamp(
            appeal["decision_due_at"], "2026-08-31", "decision_due_at"
        )

        after = validate_ok(
            api.get_records_request(request["id"], U.coordinator_headers())
        )
        assert after["status"] == C.REQ_APPEAL_FILED

        desk_after = validate_ok(api.get_desk(desk["id"], U.legal_headers()))
        assert desk_after["open_appeal_count"] == 1
        assert_ledger_columns(
            desk_after, total=500000, available=495500, committed=4500, spent=0
        )

    def test_grant_returns_the_request_to_awaiting_with_the_deadline_unmoved(
        self, api
    ):
        """A grant reopens the request; a same-day decision accrues no tolling.

        PRD S3.5: "GRANTED moves the appeal FILED -> GRANTED, records the
        decision_rationale, and puts the request back in the agency's queue:
        APPEAL_FILED -> AWAITING_AGENCY_RESPONSE."

        Design: Corner/state_machines/appeal_granted_branch_returns_the_request_to_awaiting_and_settles_the_filing_fee
        """
        _desk, _agency, request = _denied_request(api)
        appeal = _file_denial_ground_appeal(api, request["id"])

        decided = validate_ok(
            api.decide_appeal(
                appeal["id"],
                F.appeal_decision_payload(
                    C.APPEAL_GRANTED, decision_rationale=_GRANT_RATIONALE
                ),
                U.coordinator_headers(),
            )
        )
        assert decided["status"] == C.APPEAL_GRANTED

        after = validate_ok(
            api.get_records_request(request["id"], U.coordinator_headers())
        )
        assert after["status"] == C.REQ_AWAITING_AGENCY_RESPONSE
        assert after["tolled_days_total"] == 0
        assert_deadline_stamp(after["due_at_tolled"], "2026-08-17", "due_at_tolled")
        assert_deadline_stamp(after["due_at_strict"], "2026-08-17", "due_at_strict")

    def test_grant_settles_the_filing_fee_and_fires_no_litigation_side_effect(
        self, api
    ):
        """The fee is spent, not refunded, and the desk stays fully open.

        PRD S3.5: "The filing_fee_cents settles, moving from the desk's committed
        column to its spent column, open_appeal_count decrements by 1 and the
        desk's version increments by 1."

        Design: Corner/state_machines/appeal_granted_branch_returns_the_request_to_awaiting_and_settles_the_filing_fee
        """
        desk, _agency, request = _denied_request(api)
        appeal = _file_denial_ground_appeal(api, request["id"])

        validate_ok(
            api.decide_appeal(
                appeal["id"],
                F.appeal_decision_payload(
                    C.APPEAL_GRANTED, decision_rationale=_GRANT_RATIONALE
                ),
                U.coordinator_headers(),
            )
        )

        desk_after = validate_ok(api.get_desk(desk["id"], U.legal_headers()))
        assert_ledger_columns(
            desk_after, total=500000, available=495500, committed=0, spent=4500
        )
        assert desk_after["open_appeal_count"] == 0
        assert desk_after["litigation_exposure_count"] == 0
        assert desk_after["security_posture"] == C.POSTURE_OPEN


# The first instant strictly after the tolled deadline, used by the priority
# ladder probes below.
_OVERDUE_CLOCK = "2026-08-18T00:00:00Z"
_OMBUDS_ORDER_RATIONALE = "The ombuds ordered a response within ten days."
_REVERSAL_RATIONALE = "Attempted reversal of the settled appeal."
_OVERDUE_GROUNDS = "The agency has blown the statutory deadline."


def _ombuds_only_request(api):
    """A submitted request against an agency whose statute routes appeals to OMBUDS."""
    X.set_clock(api, C.STD_CLOCK)
    desk = X.create_desk(api)
    agency = X.create_agency(
        api,
        name="Ombuds Reviewed Board",
        jurisdiction_code="CA-OMB",
        holiday_dates=F.OMIT,
    )
    request = X.submitted_request(
        api,
        desk["id"],
        agency["id"],
        subject_summary="Overdue response probe",
        estimated_page_count=10,
        waiver_requested=False,
        public_interest_score=40,
    )
    return desk, agency, request


def _overdue_appeal_attempt(api, request_id, venue):
    """The same delay-ground payload, aimed at a caller-chosen venue."""
    return api.create_appeal(
        F.appeal_payload(
            request_id,
            venue=venue,
            filing_fee_cents=4500,
            grounds=_OVERDUE_GROUNDS,
        ),
        U.legal_headers(),
    )


def _appeals_of_request(api, request_id):
    """Every appeal row recorded against one records request (PRD S4 listing)."""
    rows, _meta = validate_paginated_page(
        api.list_appeals(U.legal_headers(), params={"request_id": request_id})
    )
    return rows


class TestAppealRipenessIsCheckedBeforeVenueAndASettledAppealIsFinal:
    """The appeal ladder's ordering, and the finality of a decided appeal."""

    def test_ripeness_answers_before_the_venue_mismatch(self, api):
        """Both gates are violated at once; the earlier rung determines the answer.

        PRD S2.11: "the rules are evaluated in ascending priority order, and the
        first rule whose condition is violated determines the response", with
        "An appeal must be ripe on one of the three declared grounds" ranked
        ahead of "The appeal's venue must equal the agency's appeal_venue".

        Design: Corner/validations/appeal_ripeness_is_checked_before_venue_and_a_settled_appeal_is_final
        """
        desk, _agency, request = _ombuds_only_request(api)

        validate_error(
            _overdue_appeal_attempt(api, request["id"], C.VENUE_COURT),
            ERR_APPEAL_NOT_RIPE,
        )

        assert _appeals_of_request(api, request["id"]) == []
        after = validate_ok(
            api.get_records_request(request["id"], U.coordinator_headers())
        )
        assert after["status"] == C.REQ_AWAITING_AGENCY_RESPONSE
        desk_after = validate_ok(api.get_desk(desk["id"], U.editor_headers()))
        assert desk_after["open_appeal_count"] == 0
        assert_ledger_columns(
            desk_after, total=500000, available=500000, committed=0, spent=0
        )

    def test_once_ripe_the_venue_gate_becomes_the_answer(self, api):
        """The identical payload changes its rejection once the deadline passes.

        PRD S3.5: "the venue supplied must equal the appeal_venue declared by the
        request's agency, so an appeal aimed at COURT against an agency whose
        statute routes appeals to OMBUDS is refused with
        ERR_APPEAL_VENUE_MISMATCH."

        Design: Corner/validations/appeal_ripeness_is_checked_before_venue_and_a_settled_appeal_is_final
        """
        desk, _agency, request = _ombuds_only_request(api)
        X.set_clock(api, _OVERDUE_CLOCK)

        validate_error(
            _overdue_appeal_attempt(api, request["id"], C.VENUE_COURT),
            ERR_APPEAL_VENUE_MISMATCH,
        )

        assert _appeals_of_request(api, request["id"]) == []
        after = validate_ok(
            api.get_records_request(request["id"], U.coordinator_headers())
        )
        assert after["status"] == C.REQ_AWAITING_AGENCY_RESPONSE
        desk_after = validate_ok(api.get_desk(desk["id"], U.editor_headers()))
        assert desk_after["open_appeal_count"] == 0
        assert_ledger_columns(
            desk_after, total=500000, available=500000, committed=0, spent=0
        )

    def test_the_declared_venue_is_accepted_once_the_request_is_overdue(self, api):
        """Past the deadline, in the declared venue, the filing lands.

        PRD S3.5: "The appeal is created in FILED with the derived
        ripeness_basis. ... The parent request moves to APPEAL_FILED ... And
        open_appeal_count and the desk's version each increment by 1."

        Design: Corner/validations/appeal_ripeness_is_checked_before_venue_and_a_settled_appeal_is_final
        """
        desk, _agency, request = _ombuds_only_request(api)
        X.set_clock(api, _OVERDUE_CLOCK)

        appeal = validate_created(
            _overdue_appeal_attempt(api, request["id"], C.VENUE_OMBUDS)
        )

        assert appeal["status"] == C.APPEAL_FILED_STATUS
        assert appeal["ripeness_basis"] == C.RIPENESS_OVERDUE
        assert_instant_equals(appeal["filed_at"], _OVERDUE_CLOCK, "filed_at")
        assert_deadline_stamp(
            appeal["decision_due_at"], "2026-09-15", "decision_due_at"
        )

        after = validate_ok(
            api.get_records_request(request["id"], U.coordinator_headers())
        )
        assert after["status"] == C.REQ_APPEAL_FILED

        desk_after = validate_ok(api.get_desk(desk["id"], U.editor_headers()))
        assert desk_after["open_appeal_count"] == 1
        assert_ledger_columns(
            desk_after, total=500000, available=495500, committed=4500, spent=0
        )

    def test_a_decided_appeal_cannot_be_decided_again(self, api):
        """A settled appeal is final and no counter moves on the second attempt.

        PRD S3.5: "it is only declared against an appeal in FILED -- a second
        decision on a decided appeal is ERR_INVALID_APPEAL_STATE."

        Design: Corner/validations/appeal_ripeness_is_checked_before_venue_and_a_settled_appeal_is_final
        """
        desk, _agency, request = _ombuds_only_request(api)
        X.set_clock(api, _OVERDUE_CLOCK)
        appeal = validate_created(
            _overdue_appeal_attempt(api, request["id"], C.VENUE_OMBUDS)
        )

        granted = validate_ok(
            api.decide_appeal(
                appeal["id"],
                F.appeal_decision_payload(
                    C.APPEAL_GRANTED, decision_rationale=_OMBUDS_ORDER_RATIONALE
                ),
                U.coordinator_headers(),
            )
        )
        assert granted["status"] == C.APPEAL_GRANTED
        reopened = validate_ok(
            api.get_records_request(request["id"], U.coordinator_headers())
        )
        assert reopened["status"] == C.REQ_AWAITING_AGENCY_RESPONSE

        validate_error(
            api.decide_appeal(
                appeal["id"],
                F.appeal_decision_payload(
                    C.APPEAL_DENIED, decision_rationale=_REVERSAL_RATIONALE
                ),
                U.coordinator_headers(),
            ),
            ERR_INVALID_APPEAL_STATE,
        )

        final = validate_ok(api.get_appeal(appeal["id"], U.legal_headers()))
        assert final["status"] == C.APPEAL_GRANTED
        assert final["decision_rationale"] == _OMBUDS_ORDER_RATIONALE

        desk_after = validate_ok(api.get_desk(desk["id"], U.editor_headers()))
        assert_ledger_columns(
            desk_after, total=500000, available=495500, committed=0, spent=4500
        )
        assert desk_after["open_appeal_count"] == 0
        assert desk_after["litigation_exposure_count"] == 0
        assert desk_after["security_posture"] == C.POSTURE_OPEN
