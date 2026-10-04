"""Safety analysis sections and the RAI dialogue: reopen cycles, the
cross-entity regression cascade, segregation of duties, section gating, and
response timeliness."""

from test_helpers import (
    ApiErrorId,
    APPLICANT,
    NON_EXISTENT_UUID,
    REVIEWER,
    REVIEWER_2,
    assert_rai,
    assert_sar,
    create_dca,
    create_rai,
    create_responded_rai,
    create_sar,
    create_sar_ready_with_responded_rai,
    create_sar_under_review,
    make_reviewer_headers,
    rai_payload,
    rai_response_payload,
    read_rai,
    read_sar,
    sar_payload,
    set_clock,
    validate_error,
    validate_success,
)


class TestRaiReopenCycle:
    """The RAI cycle RESPONSE_SUBMITTED -> REOPENED -> RESPONSE_SUBMITTED and
    its cross-entity regression of a READY parent section."""

    def test_reopen_regresses_ready_section(self, api):
        """PRD §3.2: "Alternatively, a reviewer may reopen a responded RAI —
        `RESPONSE_SUBMITTED → REOPENED` — and this is the regression cascade:
        if the parent section was sitting at `READY_FOR_PHASE_ADVANCE`, it
        falls back to `UNDER_REVIEW` with its own `version` incremented, and
        the owning application's `version` increments as the regression
        bubbles upward, though the application's lifecycle phase does not
        change."

        Design: Difficulty/non_linear_state_machine/rai_reopen_cycle_regresses_sar
        """
        world = create_sar_ready_with_responded_rai(api, docket_number="52-300")
        sar, rai = world["sar"], world["rai"]
        assert sar["status"] == "READY_FOR_PHASE_ADVANCE"
        assert rai["status"] == "RESPONSE_SUBMITTED"

        reopened = validate_success(api.reopen_rai(rai["id"], REVIEWER))
        assert reopened["status"] == "REOPENED"
        # The section regressed across the entity boundary.
        assert read_sar(api, sar["id"])["status"] == "UNDER_REVIEW"

    def test_reopened_rai_cycles_back_to_response_submitted(self, api):
        """PRD §3.2: "Responding is also the path out of `REOPENED`: a second
        response moves `REOPENED → RESPONSE_SUBMITTED`, refreshing
        `responded_at` and recomputing `late_response` against the same
        original `due_date`."

        Design: Difficulty/non_linear_state_machine/rai_reopen_cycle_regresses_sar
        """
        world = create_sar_ready_with_responded_rai(api, docket_number="52-301")
        sar, rai = world["sar"], world["rai"]
        validate_success(api.reopen_rai(rai["id"], REVIEWER))
        # Second response completes the cycle back to RESPONSE_SUBMITTED.
        second = validate_success(
            api.respond_rai(rai["id"], rai_response_payload("Amended response."), APPLICANT)
        )
        assert second["status"] == "RESPONSE_SUBMITTED"
        # The section was regressed by the reopen and stays UNDER_REVIEW until
        # re-advanced.
        assert read_sar(api, sar["id"])["status"] == "UNDER_REVIEW"


class TestRaiReopenThreeHopCascade:
    """reopen -> RAI REOPENED -> SAR UNDER_REVIEW -> advance-phase blocked."""

    def test_reopen_blocks_phase_advance(self, api):
        """PRD §3.2: "if the parent section was sitting at
        `READY_FOR_PHASE_ADVANCE`, it falls back to `UNDER_REVIEW` with its
        own `version` incremented, and the owning application's `version`
        increments as the regression bubbles upward, though the application's
        lifecycle phase does not change."
        PRD §3.1: "Advancing from `SAFETY_REVIEW` to `ADVANCED_REVIEW` demands
        more: every section must be `READY_FOR_PHASE_ADVANCE`, and every RAI on
        the application must have reached a terminal state — `ACCEPTED` or
        `SUPERSEDED`."

        Design: Difficulty/transitive_cascade/rai_reopen_three_hop_cascade
        """
        world = create_sar_ready_with_responded_rai(api, docket_number="52-400")
        dca, sar, rai = world["dca"], world["sar"], world["rai"]
        validate_success(api.enter_safety_review(dca["id"], REVIEWER))

        # Hop 1: the RAI reopens.
        validate_success(api.reopen_rai(rai["id"], REVIEWER))
        assert read_rai(api, rai["id"])["status"] == "REOPENED"
        # Hop 2: the section regresses.
        assert read_sar(api, sar["id"])["status"] == "UNDER_REVIEW"
        # Hop 3: the phase gate now fails because the section is not READY and
        # the RAI is not terminal.
        resp = api.advance_phase(dca["id"], REVIEWER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_resolved_reopened_rai_reopens_the_gate(self, api):
        """PRD §3.2: "Responding is also the path out of `REOPENED`: a second
        response moves `REOPENED → RESPONSE_SUBMITTED`, refreshing
        `responded_at` and recomputing `late_response` against the same
        original `due_date`."
        PRD §3.1: "Advancing from `SAFETY_REVIEW` to `ADVANCED_REVIEW` demands
        more: every section must be `READY_FOR_PHASE_ADVANCE`, and every RAI on
        the application must have reached a terminal state — `ACCEPTED` or
        `SUPERSEDED`."

        Design: Difficulty/transitive_cascade/rai_reopen_three_hop_cascade
        """
        world = create_sar_ready_with_responded_rai(api, docket_number="52-402")
        dca, sar, rai = world["dca"], world["sar"], world["rai"]
        validate_success(api.enter_safety_review(dca["id"], REVIEWER))
        validate_success(api.reopen_rai(rai["id"], REVIEWER))
        blocked = api.advance_phase(dca["id"], REVIEWER)
        validate_error(blocked, ApiErrorId.ERR_INVALID_STATE)

        # Walk the chain back: respond again, accept (different reviewer than
        # the author), re-advance the section, and the gate opens.
        validate_success(api.respond_rai(rai["id"], rai_response_payload("A2b"), APPLICANT))
        validate_success(api.accept_rai(rai["id"], REVIEWER_2))
        validate_success(api.advance_sar(sar["id"], REVIEWER))
        advanced = validate_success(api.advance_phase(dca["id"], REVIEWER))
        assert advanced["status"] == "ADVANCED_REVIEW"


class TestRaiSegregationOfDuties:
    """The authoring reviewer may not accept the response to their own RAI."""

    def test_author_accept_forbidden_other_reviewer_succeeds(self, api):
        """PRD §3.2: "Acceptance is reserved for the regulator, with
        segregation of duties: the reviewer accepting a `RESPONSE_SUBMITTED`
        RAI must not be the reviewer whose `X-User-ID` is recorded in
        `authored_by_user_id`; a self-acceptance attempt is rejected with
        `ERR_SELF_ACCEPT_FORBIDDEN`."

        Design: Corner/state_machines/rai_accept_by_author_forbidden_segregation_of_duties
        """
        dca = create_dca(api, docket_number="52-920")
        create_sar(api, dca["id"])
        rai = create_rai(api, dca["id"], reviewer_headers=REVIEWER)
        validate_success(api.respond_rai(rai["id"], rai_response_payload("A"), APPLICANT))

        # The RAI was authored by REVIEWER's user id; that same identity may
        # not accept it.
        denied = api.accept_rai(rai["id"], REVIEWER)
        validate_error(denied, ApiErrorId.ERR_SELF_ACCEPT_FORBIDDEN, 403)
        # A different reviewer accepts.
        accepted = validate_success(api.accept_rai(rai["id"], REVIEWER_2))
        assert accepted["status"] == "ACCEPTED"

    def test_authored_by_user_id_is_recorded_at_creation(self, api):
        """PRD §3.2: "At creation, the server records the authoring reviewer's
        `X-User-ID` into `authored_by_user_id`, and the parent section's
        `open_rais` is recomputed."

        Design: Corner/state_machines/rai_accept_by_author_forbidden_segregation_of_duties
        """
        dca = create_dca(api, docket_number="52-925")
        sar = create_sar(api, dca["id"])
        author = make_reviewer_headers("rev-author-9")
        rai = create_rai(api, dca["id"], reviewer_headers=author)
        assert_rai(rai)
        assert rai["authored_by_user_id"] == "rev-author-9"
        assert read_sar(api, sar["id"])["open_rais"] == 1


class TestSarOpenRaiGate:

    def test_open_rai_blocks_advance_supersede_clears(self, api):
        """PRD §3.2: "later advances it `UNDER_REVIEW →
        READY_FOR_PHASE_ADVANCE` — but only while the section's `open_rais`
        counter is zero."
        PRD §3.2: "Finally, a reviewer may supersede an RAI in either `OPEN`
        or `REOPENED` status, moving it to the terminal `SUPERSEDED` state and
        recomputing the parent section's counter."

        Design: Corner/validations/sar_advance_blocked_by_open_rai
        """
        dca = create_dca(api, docket_number="52-940")
        sar = create_sar_under_review(api, dca["id"])
        rai = create_rai(api, dca["id"], sar_section_code=sar["section_code"])

        blocked = api.advance_sar(sar["id"], REVIEWER)
        validate_error(blocked, ApiErrorId.ERR_INVALID_STATE)

        validate_success(api.supersede_rai(rai["id"], REVIEWER))
        advanced = validate_success(api.advance_sar(sar["id"], REVIEWER))
        assert advanced["status"] == "READY_FOR_PHASE_ADVANCE"

    def test_open_rais_counter_counts_open_and_responded(self, api):
        """PRD §3.2: "That counter is computed continuously as the number of
        RAIs on the same application whose `sar_section_code` equals this
        section's code and whose status is `OPEN`, `RESPONSE_SUBMITTED`, or
        `REOPENED`."

        Design: Corner/validations/sar_advance_blocked_by_open_rai
        """
        dca = create_dca(api, docket_number="52-944")
        sar = create_sar_under_review(api, dca["id"])
        rai = create_rai(api, dca["id"], sar_section_code=sar["section_code"])
        assert read_sar(api, sar["id"])["open_rais"] == 1
        # A responded RAI still counts as open, so advance stays blocked.
        validate_success(api.respond_rai(rai["id"], rai_response_payload("A"), APPLICANT))
        assert read_sar(api, sar["id"])["open_rais"] == 1
        blocked = api.advance_sar(sar["id"], REVIEWER)
        validate_error(blocked, ApiErrorId.ERR_INVALID_STATE)


class TestRaiSectionTargeting:
    """An RAI must name a section that exists on the same application."""

    def test_unknown_section_rejected(self, api):
        """PRD §3.2: "The section code must match an existing safety analysis
        report of the same application; a question aimed at a section the
        application does not contain is rejected with
        `ERR_SAR_SECTION_UNKNOWN` (HTTP 422)."

        Design: Corner/validations/rai_unknown_sar_section_rejected
        """
        dca = create_dca(api, docket_number="52-941")
        create_sar(api, dca["id"], section_code="CH03")
        resp = api.create_rai(
            dca["id"],
            rai_payload(sar_section_code="CH15"),
            REVIEWER,
        )
        validate_error(resp, ApiErrorId.ERR_SAR_SECTION_UNKNOWN, 422)

    def test_known_section_accepted(self, api):
        """PRD §3.2: "The section code must match an existing safety analysis
        report of the same application; a question aimed at a section the
        application does not contain is rejected with
        `ERR_SAR_SECTION_UNKNOWN` (HTTP 422)."

        Design: Corner/validations/rai_unknown_sar_section_rejected
        """
        dca = create_dca(api, docket_number="52-942")
        create_sar(api, dca["id"], section_code="CH15")
        rai = create_rai(api, dca["id"], sar_section_code="CH15")
        assert_rai(rai)
        assert rai["sar_section_code"] == "CH15"
        assert rai["status"] == "OPEN"


class TestRaiTimeliness:
    """The inclusive due-date boundary for RAI response lateness."""

    def test_response_exactly_at_due_date_is_timely(self, api):
        """PRD §3.2: "the boundary is inclusive, so a response whose
        `responded_at` is exactly at `due_date` is timely, and only a strictly
        later response counts as late."

        Design: Corner/calculations/rai_late_response_boundary_inclusive_due_date
        """
        set_clock(api, "2026-10-01T00:00:00Z")
        dca = create_dca(api, docket_number="52-932")
        create_sar(api, dca["id"])
        rai = create_rai(
            api, dca["id"], due_date="2026-10-01T00:00:00Z", question_text="Q1"
        )
        answered = validate_success(
            api.respond_rai(rai["id"], rai_response_payload("on time"), APPLICANT)
        )
        assert answered["late_response"] is False

    def test_response_one_second_after_due_date_is_late(self, api):
        """PRD §3.2: "the boundary is inclusive, so a response whose
        `responded_at` is exactly at `due_date` is timely, and only a strictly
        later response counts as late."
        PRD §3.2: "A late response is still accepted; lateness is
        informational, recorded on the record, and never a rejection."

        Design: Corner/calculations/rai_late_response_boundary_inclusive_due_date
        """
        set_clock(api, "2026-10-01T00:00:01Z")
        dca = create_dca(api, docket_number="52-933")
        create_sar(api, dca["id"])
        rai = create_rai(
            api, dca["id"], due_date="2026-10-01T00:00:00Z", question_text="Q2"
        )
        answered = validate_success(
            api.respond_rai(rai["id"], rai_response_payload("late"), APPLICANT)
        )
        assert answered["status"] == "RESPONSE_SUBMITTED"
        assert answered["late_response"] is True


class TestRaiTerminalLockdown:
    """Terminal RAI states accept no further transitions."""

    def test_respond_to_accepted_rai_rejected(self, api):
        """PRD §3.2: "Acceptance moves the RAI to the terminal `ACCEPTED`
        state and recomputes the parent section's `open_rais`."

        Design: Corner/state_machines/rai_terminal_accepted_rejects_respond
        """
        dca = create_dca(api, docket_number="52-922")
        create_sar(api, dca["id"])
        rai = create_responded_rai(api, dca["id"])
        validate_success(api.accept_rai(rai["id"], REVIEWER_2))

        resp = api.respond_rai(rai["id"], rai_response_payload("A2"), APPLICANT)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_accepted_rai_cannot_be_reopened(self, api):
        """PRD §3.2: "Acceptance moves the RAI to the terminal `ACCEPTED`
        state and recomputes the parent section's `open_rais`."

        Design: Corner/state_machines/rai_terminal_accepted_rejects_respond
        """
        dca = create_dca(api, docket_number="52-923")
        create_sar(api, dca["id"])
        rai = create_responded_rai(api, dca["id"])
        validate_success(api.accept_rai(rai["id"], REVIEWER_2))

        resp = api.reopen_rai(rai["id"], REVIEWER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


class TestValidationOrdering:
    """Authentication and authorization are evaluated before domain rules."""

    def test_wrong_role_on_rai_create_beats_section_check(self, api):
        """PRD §2.7: "Authentication comes first (`ERR_UNAUTHENTICATED`), then
        role authorization (`ERR_UNAUTHORIZED`), then existence of
        path-templated ids and request-body foreign keys (`ERR_NOT_FOUND`),
        then whether the target resource is in a state from which the
        requested transition exists (`ERR_INVALID_STATE`, HTTP 409). Only
        after those structural checks pass do the domain rules engage —
        segregation of duties on RAI acceptance, the procurement gate,
        audit-date overlap, the hearing windows, chronological test recording,
        section-code matching, capacity and escalation gates, the OCC version
        match, and uniqueness constraints."

        Design: Difficulty/priority_pair_validation_conflict/auth_vs_business_referential_on_rai_create
        """
        dca = create_dca(api, docket_number="52-501")
        create_sar(api, dca["id"], section_code="CH03")
        # DcaApplicant is not an authorized RAI creator; even though the
        # section code is bogus, authorization fires first.
        resp = api.create_rai(
            dca["id"],
            rai_payload(sar_section_code="CH99"),
            APPLICANT,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)

    def test_wrong_role_with_valid_section_still_unauthorized(self, api):
        """PRD §2.7: "Authentication comes first (`ERR_UNAUTHENTICATED`), then
        role authorization (`ERR_UNAUTHORIZED`), then existence of
        path-templated ids and request-body foreign keys (`ERR_NOT_FOUND`),
        then whether the target resource is in a state from which the
        requested transition exists (`ERR_INVALID_STATE`, HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/auth_vs_business_referential_on_rai_create
        """
        dca = create_dca(api, docket_number="52-502")
        create_sar(api, dca["id"], section_code="CH03")
        resp = api.create_rai(
            dca["id"],
            rai_payload(sar_section_code="CH03"),
            APPLICANT,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)

