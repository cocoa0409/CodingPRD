"""Due process, stay-put arbitration, the documentation packet and the federal cap.

Every test in this module translates exactly one instance of the difficulty or
corner design index; the trailing `Design:` line of each docstring names it.
"""

from test_helpers import (
    CANON_AWARD_COMPUTED_MINUTES_MFM,
    CANON_BUDGET_CODE,
    CANON_DELIVERY_DEADLINE_DATE,
    CANON_MAKEUP_CHARGE_60_MIN,
    CLOCK_POST_SESSION,
    SEVERITY_FACTOR_MID,
    SPED_DIRECTOR_USER_ID,
    ApiErrorId,
    assert_award,
    assert_award_remaining_identity,
    assert_due_process_record,
    assert_makeup_session,
    fixtures,
    make_case_manager_headers,
    make_compliance_officer_headers,
    make_parent_guardian_headers,
    make_related_service_provider_headers,
    make_sped_director_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CM = make_case_manager_headers()
CO = make_compliance_officer_headers()
DIR = make_sped_director_headers()

LOCAL_ALLOCATION = {
    "fund_source": "LOCAL_GENERAL",
    "budget_code": "LOC-ESY-01",
    "authorized_amount_cents": 25000000,
}


def _refresh_record(api, student_id: str, record_id: str):
    """Re-read one due-process record through the student's record list."""
    rows, _meta = validate_paginated(
        api.list_student_due_process_records(student_id, CO, {"limit": 100})
    )
    for row in rows:
        if row["id"] == record_id:
            return row
    raise AssertionError(f"record {record_id} is not listed under student {student_id}")


class TestArbitrationUnderStayPut:
    """An OPEN COMPLAINT freezes arbitration; an OPEN MEDIATION_AGREEMENT does not."""

    def _disputed_award(self, api):
        context = fixtures.setup_baseline(api)
        student_id = context["student"]["id"]
        award = fixtures.open_award(api, student_id, context["program"]["id"])
        award = validate_success(
            api.propose_award(
                award["id"],
                {"proposed_minutes": CANON_AWARD_COMPUTED_MINUTES_MFM},
                CM,
            )
        )
        fixtures.set_clock(api, CLOCK_POST_SESSION)
        award = validate_success(
            api.award_parent_response(
                award["id"],
                {"response": "DISPUTE"},
                make_parent_guardian_headers(student_id),
            )
        )
        assert award["negotiation_status"] == "DISPUTED"
        assert award["dispute_round_count"] == 1
        assert award["computed_minutes"] == CANON_AWARD_COMPUTED_MINUTES_MFM
        assert award["agreed_minutes"] is None

        mediation = fixtures.file_due_process_record(
            api,
            student_id,
            record_type="MEDIATION_AGREEMENT",
            allegation_summary="Mediated terms: 85 compensatory minutes offered.",
        )
        assert mediation["stay_put_active"] is False
        assert fixtures.refresh_student(api, student_id)["stay_put_active"] is False

        complaint = fixtures.file_due_process_record(
            api,
            student_id,
            record_type="COMPLAINT",
            allegation_summary="Parent alleges ESY minutes were not delivered.",
        )
        assert_due_process_record(complaint)
        assert complaint["status"] == "OPEN"
        assert complaint["stay_put_active"] is True
        assert fixtures.refresh_student(api, student_id)["stay_put_active"] is True

        context = dict(context)
        context["award"] = award
        context["mediation"] = mediation
        context["complaint"] = complaint
        return context

    def test_an_open_complaint_blocks_the_directors_arbitration(self, api):
        """100 minutes inside the band is still refused while the filing is live.

        "Stay-put freezes exactly three operations, and it freezes them hard." One
        of the three is this endpoint: "While a student's `stay_put_active` reads
        true, that student's service commitments may not be suspended and may not be
        terminated, and any compensatory award of that student may not be arbitrated
        by a director." and "All three attempts answer `ERR_STAY_PUT_BLOCKED`." The
        flag is raised by the record type, not by the mere existence of a filing:
        "Each record's `status` starts at `OPEN`, and its own `stay_put_active` flag
        reads true exactly when its `status` is `OPEN` and its `record_type` is
        `COMPLAINT` or `DUE_PROCESS_HEARING`." The offer itself is unimpeachable —
        "The submitted `arbitrated_minutes` must fall inside the same band as a
        proposal, from `computed_minutes` up to the whole-number part below one and
        one-half times `computed_minutes`, inclusive at both ends, or the request
        draws `ERR_PROPOSAL_OUT_OF_RANGE`." — and 100 lies between 85 and 127, so
        the stay-put error is the only one available.

        Design: Difficulty/cross_entity_state_dependency/dispute_arbitration_blocked_by_open_due_process_record
        """
        context = self._disputed_award(api)
        award_id = context["award"]["id"]

        validate_error(
            api.resolve_award_dispute(award_id, {"arbitrated_minutes": 100}, DIR),
            ApiErrorId.STAY_PUT_BLOCKED,
            409,
        )

        award = fixtures.refresh_award(api, award_id)
        assert award["negotiation_status"] == "DISPUTED"
        assert award["agreed_minutes"] is None
        assert award["resolved_by_user_id"] is None
        assert award["remaining_owed_minutes"] == 0
        assert_award_remaining_identity(award)

        student = fixtures.refresh_student(api, context["student"]["id"])
        assert student["stay_put_active"] is True
        assert student["outstanding_owed_minutes"] == 0

    def test_resolving_the_complaint_releases_the_arbitration(self, api):
        """Closing the record drops the flag and the identical body is imposed.

        "Resolving a record moves it `OPEN → RESOLVED`, sets its `resolved_at` to
        the current logical-clock instant, and drops its own `stay_put_active` to
        false; the student's `stay_put_active` is then recomputed and the student's
        `version` increments, which is what unblocks commitment suspension,
        commitment termination and award arbitration again." The still-open
        mediation record cannot hold the flag up on its own, because "a `COMPLAINT`
        and a `DUE_PROCESS_HEARING` assert **stay-put** protection the moment they
        are filed, while a `MEDIATION_AGREEMENT` does not." Arbitration then does
        the full set of things: "On success `agreed_minutes` is set to
        `arbitrated_minutes`, `resolved_by_user_id` records the arbitrating
        director, `delivery_deadline_date` is set to the current logical clock's
        calendar date plus one hundred and eighty days, the student's
        `outstanding_owed_minutes` is recomputed with the student's `version`
        incremented by one, and the award's `version` increments."

        Design: Difficulty/cross_entity_state_dependency/dispute_arbitration_blocked_by_open_due_process_record
        """
        context = self._disputed_award(api)
        award_id = context["award"]["id"]
        student_id = context["student"]["id"]

        resolved = fixtures.close_due_process_record(
            api,
            context["complaint"]["id"],
            resolution_note="Complaint withdrawn after facilitated meeting",
        )
        assert resolved["status"] == "RESOLVED"
        assert resolved["stay_put_active"] is False
        assert resolved["resolved_at"] is not None

        assert _refresh_record(api, student_id, context["mediation"]["id"])[
            "status"
        ] == "OPEN"
        assert fixtures.refresh_student(api, student_id)["stay_put_active"] is False

        arbitrated = validate_success(
            api.resolve_award_dispute(award_id, {"arbitrated_minutes": 100}, DIR)
        )
        assert_award(arbitrated)
        assert arbitrated["negotiation_status"] == "AGREED"
        assert arbitrated["agreed_minutes"] == 100
        assert arbitrated["resolved_by_user_id"] == SPED_DIRECTOR_USER_ID
        assert arbitrated["delivery_deadline_date"] == CANON_DELIVERY_DEADLINE_DATE
        assert arbitrated["remaining_owed_minutes"] == 100
        assert arbitrated["delivery_status"] == "NOT_STARTED"
        assert_award_remaining_identity(arbitrated)

        student = fixtures.refresh_student(api, student_id)
        assert student["outstanding_owed_minutes"] == 100
        assert student["stay_put_active"] is False


class TestFederalSupplantCap:
    """A quarter of the federal authorization is all compensatory work may draw."""

    def test_a_delivery_over_the_quarter_ceiling_is_refused(self, api):
        """A 9720-cent charge cannot land on a 30000-cent federal grant.

        The two chargeable operations select their bucket the same way: "The selected
        allocation is the **first** candidate in that order whose `available_cents`
        is greater than or equal to `base_cost_cents`." The assignment's base cost of
        206100 cents is far beyond the small federal grant, so it falls to the local
        bucket and prices at the local rate — "Both federal streams carry an
        eight-percent indirect rate; `LOCAL_GENERAL` carries fourteen and a half
        percent." — for 235985 cents encumbered. The 60-minute makeup delivery is
        small enough to select the federal grant, and there it meets a ceiling the
        assignment never had to clear: "For makeup sessions **only**, one further
        test runs before the posting: when the selected allocation's `fund_source` is
        either `IDEA_611_FEDERAL` or `IDEA_619_FEDERAL`, and the allocation's
        existing `compensatory_expended_cents` plus `total_charge_cents` would exceed
        one quarter of its `authorized_amount_cents` (that ceiling being the
        authorized amount multiplied by twenty-five hundredths, rounded half up to a
        whole cent), the request is rejected with `ERR_SUPPLANT_RESTRICTION`." One
        quarter of 30000 is 7500, and 9720 is more, so nothing is posted at all.

        Design: Corner/errors/compensatory_charge_above_the_federal_supplant_cap_rejected
        """
        context = fixtures.setup_scheduled_session(
            api,
            minutes_planned=60,
            allocation_overrides={"authorized_amount_cents": 30000},
            extra_allocations=[LOCAL_ALLOCATION],
        )
        federal, local = context["allocations"][0], context["allocations"][1]
        session_id = context["session"]["id"]
        provider_id = context["provider"]["id"]

        assignment = context["assignment"]
        assert assignment["charged_fund_source"] == "LOCAL_GENERAL"
        assert assignment["charged_budget_code"] == "LOC-ESY-01"
        assert assignment["total_charge_cents"] == 235985
        assert assignment["indirect_cost_cents"] == 29885

        local_row = fixtures.refresh_allocation(api, context["program"]["id"], local["id"])
        assert local_row["encumbered_amount_cents"] == 235985

        validate_error(
            api.log_makeup_outcome(
                session_id,
                {"outcome": "DELIVERED", "minutes_delivered": 60},
                make_related_service_provider_headers(provider_id),
            ),
            ApiErrorId.SUPPLANT_RESTRICTION,
            422,
        )

        session = fixtures.refresh_session(api, session_id)
        assert session["status"] == "SCHEDULED"
        assert session["minutes_delivered"] == 0
        assert session["charge_cents"] == 0
        assert session["charged_fund_source"] is None

        federal_row = fixtures.refresh_allocation(
            api, context["program"]["id"], federal["id"]
        )
        assert federal_row["fund_source"] == "IDEA_611_FEDERAL"
        assert federal_row["authorized_amount_cents"] == 30000
        assert federal_row["expended_amount_cents"] == 0
        assert federal_row["compensatory_expended_cents"] == 0
        assert federal_row["encumbered_amount_cents"] == 0

        award = fixtures.refresh_award(api, context["award"]["id"])
        assert award["delivered_minutes"] == 0
        assert award["remaining_owed_minutes"] == CANON_AWARD_COMPUTED_MINUTES_MFM
        assert award["delivery_status"] == "SCHEDULING"


class TestMakeupOutcomeOwnership:
    """Only the session's own provider may report what happened."""

    def test_another_provider_cannot_log_this_sessions_outcome(self, api):
        """PR2 is refused and PR1's identical body is accepted.

        "The provider ownership check guards exactly two operations: logging the
        outcome of a makeup session, and creating a service log." The comparison is
        against the addressed row, not against any general staffing list: "In both, a
        `RelatedServiceProvider` whose `X-User-ID` does not equal the `provider_id`
        of the addressed makeup session, or of the assignment covering the service
        log's commitment, is rejected with `ERR_NOT_ASSIGNED_PROVIDER` (HTTP 403)."
        The same rule is restated on the outcome endpoint itself: "All three require
        the session to be `SCHEDULED` and require the acting
        `RelatedServiceProvider`'s `X-User-ID` to equal the session's `provider_id`,
        failing which the request answers `ERR_NOT_ASSIGNED_PROVIDER`." Once the
        right provider reports it, the 60 minutes are credited against the 85 owed.

        Design: Corner/rbac/related_service_provider_cannot_log_another_providers_makeup_outcome
        """
        context = fixtures.setup_scheduled_session(api, minutes_planned=60)
        session_id = context["session"]["id"]
        own_provider_id = context["provider"]["id"]

        other = fixtures.register_provider(
            api, full_name="Owen Blake", role_type="SLP"
        )
        assert other["status"] == "ACTIVE"

        validate_error(
            api.log_makeup_outcome(
                session_id,
                {"outcome": "DELIVERED", "minutes_delivered": 60},
                make_related_service_provider_headers(other["id"]),
            ),
            ApiErrorId.NOT_ASSIGNED_PROVIDER,
            403,
        )

        untouched = fixtures.refresh_session(api, session_id)
        assert untouched["status"] == "SCHEDULED"
        assert untouched["minutes_delivered"] == 0
        assert untouched["charge_cents"] == 0

        delivered = validate_success(
            api.log_makeup_outcome(
                session_id,
                {"outcome": "DELIVERED", "minutes_delivered": 60},
                make_related_service_provider_headers(own_provider_id),
            )
        )
        assert_makeup_session(delivered)
        assert delivered["status"] == "DELIVERED"
        assert delivered["minutes_delivered"] == 60
        assert delivered["charge_cents"] == CANON_MAKEUP_CHARGE_60_MIN
        assert delivered["charged_fund_source"] == "IDEA_611_FEDERAL"
        assert delivered["charged_budget_code"] == CANON_BUDGET_CODE

        award = fixtures.refresh_award(api, context["award"]["id"])
        assert award["delivered_minutes"] == 60
        assert award["scheduled_minutes"] == 0
        assert award["remaining_owed_minutes"] == 25
        assert award["delivery_status"] == "IN_PROGRESS"
        assert_award_remaining_identity(award)

        student = fixtures.refresh_student(api, context["student"]["id"])
        assert student["outstanding_owed_minutes"] == 25
        assert student["delivered_makeup_minutes_total"] == 60


class TestDocumentationPacket:
    """The packet is the only read that counts a student's OPEN filings."""

    def test_the_packet_aggregates_the_award_ledger_and_the_open_filing_count(self, api):
        """Two OPEN records of three are counted, alongside the whole arithmetic trail.

        "For an investigator or a hearing officer, the service offers a computed
        **documentation packet** for one award, readable by a `SpedDirector` or a
        `ComplianceOfficer` only." Its shape is fixed field by field: "Rather than
        the stored award record, the packet returns a flat purpose-built summary:
        `award_id` and `student_id` identifying the case; `calculation_variant` and
        `severity_factor` showing which remedy formula ran and at what scale;
        `computed_minutes`, `proposed_minutes` and `agreed_minutes` tracing the
        arithmetic through the negotiation; `delivered_minutes`, `scheduled_minutes`,
        `forfeited_minutes` and `remaining_owed_minutes` showing where the debt
        stands; `verified_missed_log_count` and `excluded_log_count` proving which
        service logs were counted and how many were set aside; `dispute_round_count`
        and `parent_no_show_count` recording the negotiation and attendance history;
        `negotiation_status`, `delivery_status` and `delivery_deadline_date` giving
        both state dimensions and the clock they run against; and
        `open_due_process_record_count`, the number of due-process records of that
        student still sitting in `OPEN`." The dismissed record drops out of that last
        count and the parent-caused log stays out of the input set, since
        "`excluded_log_count` records how many logs of the same student and the same
        program were passed over — those with `status` `VOIDED`, and those whose
        outcome was `DELIVERED`, `MISSED_PARENT` or `MISSED_STUDENT_ABSENT`."

        Design: Corner/endpoints/due_process_packet_computed_read_aggregates_the_documentation_fields
        """
        context = fixtures.setup_agreed_award(api)
        award_id = context["award"]["id"]
        student_id = context["student"]["id"]

        fixtures.file_due_process_record(
            api,
            student_id,
            record_type="COMPLAINT",
            allegation_summary="Parent alleges ESY minutes were not delivered.",
        )
        fixtures.file_due_process_record(
            api,
            student_id,
            record_type="MEDIATION_AGREEMENT",
            allegation_summary="Mediated terms: 85 compensatory minutes offered.",
        )
        dismissed_record = fixtures.file_due_process_record(
            api,
            student_id,
            record_type="DUE_PROCESS_HEARING",
            allegation_summary="Hearing request naming the same ESY minutes.",
        )
        dismissed = fixtures.close_due_process_record(
            api,
            dismissed_record["id"],
            status="DISMISSED",
            resolution_note="Duplicate of the pending complaint",
        )
        assert dismissed["status"] == "DISMISSED"

        packet = validate_success(api.get_due_process_packet(award_id, DIR))
        assert packet["award_id"] == award_id
        assert packet["student_id"] == student_id
        assert packet["calculation_variant"] == "MINUTE_FOR_MINUTE"
        assert float(packet["severity_factor"]) == SEVERITY_FACTOR_MID
        assert packet["computed_minutes"] == CANON_AWARD_COMPUTED_MINUTES_MFM
        assert packet["proposed_minutes"] == CANON_AWARD_COMPUTED_MINUTES_MFM
        assert packet["agreed_minutes"] == CANON_AWARD_COMPUTED_MINUTES_MFM
        assert packet["delivered_minutes"] == 0
        assert packet["scheduled_minutes"] == 0
        assert packet["forfeited_minutes"] == 0
        assert packet["remaining_owed_minutes"] == CANON_AWARD_COMPUTED_MINUTES_MFM
        assert packet["verified_missed_log_count"] == 2
        assert packet["excluded_log_count"] == 1
        assert packet["dispute_round_count"] == 0
        assert packet["parent_no_show_count"] == 0
        assert packet["negotiation_status"] == "AGREED"
        assert packet["delivery_status"] == "NOT_STARTED"
        assert packet["delivery_deadline_date"] == CANON_DELIVERY_DEADLINE_DATE
        assert packet["open_due_process_record_count"] == 2

        also_readable = validate_success(api.get_due_process_packet(award_id, CO))
        assert also_readable["open_due_process_record_count"] == 2


class TestResolvedRecordIsTerminal:
    """RESOLVED is the end of the line for a due-process record."""

    def test_a_resolved_record_refuses_a_later_dismissal(self, api):
        """A second close asking for DISMISSED is a state error, and nothing moves.

        "A `ComplianceOfficer` closes a record by supplying a `status` of either
        `RESOLVED` or `DISMISSED`, with an optional `resolution_note`; both branches
        require the record to be `OPEN` and both are terminal." The first PATCH
        consumed the only transition out of `OPEN`: "Resolving a record moves it
        `OPEN → RESOLVED`, sets its `resolved_at` to the current logical-clock
        instant, and drops its own `stay_put_active` to false; the student's
        `stay_put_active` is then recomputed and the student's `version` increments,
        which is what unblocks commitment suspension, commitment termination and
        award arbitration again." The dismissal branch would need the same source
        state — "Dismissing a record moves it `OPEN → DISMISSED` with the identical
        downstream effect: `stay_put_active` becomes false, the student's flag is
        recomputed, the student's `version` increments, and the record's `version`
        increments." — so the request is refused and the stored
        `resolution_note` from the resolution survives untouched.

        Design: Corner/state_machines/resolved_due_process_record_rejects_further_status_change
        """
        fixtures.set_clock(api)
        student = fixtures.register_student(api)
        record = fixtures.file_due_process_record(
            api,
            student["id"],
            record_type="COMPLAINT",
            allegation_summary="Parent alleges ESY minutes were not delivered.",
        )
        assert record["status"] == "OPEN"

        resolved = fixtures.close_due_process_record(
            api,
            record["id"],
            resolution_note="Investigation closed with corrective action.",
        )
        assert resolved["status"] == "RESOLVED"
        assert resolved["stay_put_active"] is False
        settled_version = resolved["version"]

        validate_error(
            api.patch_due_process_record(
                record["id"],
                {"status": "DISMISSED", "resolution_note": "Reclassified as dismissed."},
                CO,
            ),
            ApiErrorId.INVALID_STATE,
            409,
        )

        after = _refresh_record(api, student["id"], record["id"])
        assert_due_process_record(after)
        assert after["status"] == "RESOLVED"
        assert after["resolution_note"] == "Investigation closed with corrective action."
        assert after["version"] == settled_version
        assert after["stay_put_active"] is False
        assert fixtures.refresh_student(api, student["id"])["stay_put_active"] is False
