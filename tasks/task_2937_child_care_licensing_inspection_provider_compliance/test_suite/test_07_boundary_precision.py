"""Boundaries that sit one unit apart (PRD §3.2, §3.8, §3.9, §3.5).

Each class pins the last accepted value and the first refused one on the same
metric: one child, one point, one second, or the third decimal place of a
deduction line.
"""

from test_helpers import (
    CODE_FACILITY,
    CODE_NUTRITION,
    CODE_RATIO,
    CODE_SUPERVISION,
    CODE_SUPERVISION_PLAN,
    DEFAULT_LOGICAL_CLOCK,
    assert_cents,
    assert_compliance_score_read,
    assert_instant,
    assert_point_ledger,
    assert_points,
    assert_score,
    factories as f,
    fixtures as fx,
    make_applicant_headers,
    make_inspector_headers,
    supervisor_headers,
    validate_error,
    validate_success,
)

ALL_AGE_GROUPS = ["INFANT", "TODDLER", "PRESCHOOL", "SCHOOL_AGE"]
ROOMS = [
    {"age_group": "INFANT", "requested_group_size": 8},
    {"age_group": "TODDLER", "requested_group_size": 12},
    {"age_group": "PRESCHOOL", "requested_group_size": 20},
    {"age_group": "SCHOOL_AGE", "requested_group_size": 20},
]


def _licensed_infant_room_of_eight(api, catalog):
    """Rosewood Center licensed over 60 slots, its INFANT room approved for 8
    places and led by the cleared director, with no children enrolled yet."""
    fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
    base = fx.setup_licensed_provider(
        api,
        legal_name="Rosewood Center",
        requested_capacity=60,
        rooms=ROOMS,
        inspector_certified_age_groups=ALL_AGE_GROUPS,
        catalog=catalog,
    )
    ctx = base["ctx"]
    applicant = make_applicant_headers(ctx.id)
    infant = validate_success(
        api.patch_roster(
            ctx.rosters["INFANT"]["id"],
            lead_staff_member_id=ctx.director["id"],
            headers=applicant,
        )
    )
    return {
        "ctx": ctx,
        "applicant": applicant,
        "inspector": make_inspector_headers(base["inspector"]["id"]),
        "infant_id": infant["id"],
        "infant": infant,
    }


class TestRatioAndGroupSizeCountsOnRosterPatch:
    """§3.2: "a single extra child adds a whole adult"."""

    def test_the_empty_room_verifies_with_no_staff_at_all(self, api, catalog):
        """Approved for eight places and holding no children, the room needs zero
        adults and passes an explicit verification.

        PRD §3.2: "An infant room with 8 approved places and no children enrolled
        verifies successfully with zero staff assigned, because zero children
        require zero adults; the same room with one child enrolled and no staff
        assigned requires one adult and is refused as ratio-noncompliant; with four
        children and one adult it is compliant, and with five children and one
        adult it requires two adults and is refused."

        Design: Difficulty/boundary_precision_check/boundary_ratio_and_group_size_counts_on_roster_patch
        """
        ctx = _licensed_infant_room_of_eight(api, catalog)
        room = ctx["infant"]
        assert room["approved_group_size"] == 8
        assert room["enrolled_count"] == 0
        assert room["staff_assigned_count"] == 0
        assert room["required_staff_count"] == 0
        assert room["ratio_compliant"] is True
        assert room["group_size_compliant"] is True
        assert room["supervision_compliant"] is True
        assert (
            validate_success(
                api.get_provider(ctx["ctx"].id, headers=supervisor_headers())
            )["licensed_capacity"]
            == 60
        )

        verified = validate_success(
            api.verify_ratio(ctx["infant_id"], headers=ctx["inspector"])
        )
        assert_instant(
            verified["last_verified_at"], DEFAULT_LOGICAL_CLOCK, "last_verified_at"
        )

    def test_the_ratio_boundary_falls_between_four_and_five_infants(self, api, catalog):
        """Four infants to one adult is compliant; the fifth infant demands a
        second adult and the patch is refused.

        PRD §3.2: "From the first of those, `required_staff_count` is the enrolled
        count divided by the ratio for the room's age band and rounded **up** to a
        whole number, so a single extra child adds a whole adult; when no children
        are enrolled the required count is exactly 0. The room is ratio-compliant
        when its assigned staff count is greater than or equal to the required
        staff count — equality is compliant."

        Design: Difficulty/boundary_precision_check/boundary_ratio_and_group_size_counts_on_roster_patch
        """
        ctx = _licensed_infant_room_of_eight(api, catalog)
        four = validate_success(
            api.patch_roster(
                ctx["infant_id"],
                enrolled_count=4,
                staff_assigned_count=1,
                headers=ctx["applicant"],
            )
        )
        assert four["required_staff_count"] == 1
        assert four["ratio_compliant"] is True

        validate_error(
            api.patch_roster(
                ctx["infant_id"], enrolled_count=5, headers=ctx["applicant"]
            ),
            "ERR_RATIO_NONCOMPLIANT",
            409,
        )

        unchanged = validate_success(
            api.get_roster(ctx["infant_id"], headers=supervisor_headers())
        )
        assert unchanged["enrolled_count"] == 4
        assert unchanged["staff_assigned_count"] == 1
        assert unchanged["version"] == four["version"], (
            "a refused room update must not advance the room revision"
        )

        five = validate_success(
            api.patch_roster(
                ctx["infant_id"],
                enrolled_count=5,
                staff_assigned_count=2,
                headers=ctx["applicant"],
            )
        )
        assert five["required_staff_count"] == 2
        assert five["ratio_compliant"] is True

    def test_the_group_size_boundary_falls_one_child_higher_at_eight_and_nine(
        self, api, catalog
    ):
        """Eight infants exactly fill the approved cap; the ninth is refused even
        with a third adult on the floor.

        PRD §3.2: "It is group-size-compliant when the enrolled count is at most
        the smaller of the approved group size and the statutory maximum for the age
        band, which means that while the approved group size is still 0 the check
        degenerates into requiring zero enrolled children."

        Design: Difficulty/boundary_precision_check/boundary_ratio_and_group_size_counts_on_roster_patch
        """
        ctx = _licensed_infant_room_of_eight(api, catalog)
        eight = validate_success(
            api.patch_roster(
                ctx["infant_id"],
                enrolled_count=8,
                staff_assigned_count=2,
                headers=ctx["applicant"],
            )
        )
        assert eight["enrolled_count"] == 8
        assert eight["group_size_compliant"] is True
        assert eight["required_staff_count"] == 2
        assert eight["ratio_compliant"] is True

        validate_error(
            api.patch_roster(
                ctx["infant_id"],
                enrolled_count=9,
                staff_assigned_count=3,
                headers=ctx["applicant"],
            ),
            "ERR_GROUP_SIZE_EXCEEDED",
            409,
        )

        room = validate_success(
            api.get_roster(ctx["infant_id"], headers=supervisor_headers())
        )
        assert room["enrolled_count"] == 8, (
            "nine infants exceed the eight approved places even though "
            "ceil(9/4) == 3 satisfies the ratio rule"
        )
        assert room["staff_assigned_count"] == 2
        assert room["version"] == eight["version"]

        verified = validate_success(
            api.verify_ratio(ctx["infant_id"], headers=ctx["inspector"])
        )
        assert verified["enrolled_count"] == 8
        assert verified["required_staff_count"] == 2
        assert_instant(
            verified["last_verified_at"], DEFAULT_LOGICAL_CLOCK, "last_verified_at"
        )


def _complaint_visit(api, provider_id, inspector_id, catalog, day, specs, outcome):
    complaint = fx.intake_complaint(
        api,
        provider_id,
        intake_channel="WALK_IN",
        allegation_category="FACILITY",
        affected_age_group="PRESCHOOL",
        narrative=f"Walk-in report of hazards and thin staffing, visit {day}.",
        anonymous=True,
    )
    return fx.run_visit(
        api,
        provider_id,
        inspector_id,
        f"2026-08-{day}T09:00:00Z",
        inspection_type="COMPLAINT",
        target_age_groups=["PRESCHOOL"],
        duration_minutes=120,
        complaint_id=complaint["id"],
        catalog=catalog,
        citations=specs,
        outcome=outcome,
    )


def _provider_at_fourteen_open_points(api, catalog):
    """Thornhill Center carrying 8 + 4 + 1 + 1 = 14 open points.

    The visit is finalized, because §3.5 makes every provider point counter read
    only violations "whose owning inspection is `FINALIZED`".
    """
    fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
    ada = fx.register_inspector(
        api,
        full_name="Ada Inspector",
        certified_age_groups=["PRESCHOOL"],
        max_daily_visits=3,
    )
    provider = fx.create_provider(
        api,
        legal_name="Thornhill Center",
        site_address="51 Thornhill Rd",
        program_type="CENTER",
        requested_capacity=20,
    )
    _complaint_visit(
        api,
        provider["id"],
        ada["id"],
        catalog,
        "05",
        [
            {"code": CODE_RATIO, "narrative": "Preschool room over ratio."},
            {"code": CODE_FACILITY, "narrative": "Loose decking board."},
            {"code": CODE_NUTRITION, "narrative": "Menu not posted in the hallway."},
            {"code": CODE_NUTRITION, "narrative": "Menu not posted in the classroom."},
        ],
        "CONDITIONAL_PASS",
    )
    return {"provider_id": provider["id"], "ada": ada}


def _add_one_minor(api, ctx, catalog):
    """A second finalized visit carrying one more MINOR finding: 14 -> 15."""
    return _complaint_visit(
        api,
        ctx["provider_id"],
        ctx["ada"]["id"],
        catalog,
        "06",
        [{"code": CODE_NUTRITION, "narrative": "Menu not posted in the kitchen."}],
        "CONDITIONAL_PASS",
    )


def _add_one_critical(api, ctx, catalog):
    """A third finalized visit carrying one CRITICAL finding: 15 -> 30."""
    return _complaint_visit(
        api,
        ctx["provider_id"],
        ctx["ada"]["id"],
        catalog,
        "07",
        [{"code": CODE_SUPERVISION_PLAN, "narrative": "No written supervision plan."}],
        "FAIL",
    )


def _propose(api, ctx, action_type, rationale):
    return api.create_enforcement_action(
        f.enforcement_action_payload(
            ctx["provider_id"], action_type, rationale=rationale
        ),
        headers=supervisor_headers(),
    )


class TestEnforcementPointThresholdsOnProposal:
    """§3.8: "**The agency may under-enforce but never over-enforce**"."""

    def test_fourteen_points_carry_no_statutory_basis_at_all(self, api, catalog):
        """One point below the warning threshold, even a warning proposal is
        refused.

        PRD §3.8: "First, the points must be at least 15; below that there is no
        statutory basis at all and the proposal is refused with
        `ERR_NO_ENFORCEMENT_BASIS` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/boundary_enforcement_point_thresholds_on_proposal
        """
        ctx = _provider_at_fourteen_open_points(api, catalog)
        provider = validate_success(
            api.get_provider(ctx["provider_id"], headers=supervisor_headers())
        )
        assert_point_ledger(provider, 14, 0, 14)
        assert provider["current_ladder_step"] == 0

        validate_error(
            _propose(api, ctx, "WARNING", "Fourteen open points."),
            "ERR_NO_ENFORCEMENT_BASIS",
            409,
        )

    def test_fifteen_points_recommend_a_warning_and_nothing_higher(self, api, catalog):
        """Exactly at the warning threshold a probation proposal over-enforces,
        while the warning is accepted at a first-tier fine.

        PRD §3.8: "the recommended rung is derived from the points by inclusive
        thresholds — revocation at 60 or more, else suspension at 45 or more, else
        probation at 30 or more, else warning at 15 or more — and the requested
        rung's number may not exceed the recommended rung's number."

        Design: Difficulty/boundary_precision_check/boundary_enforcement_point_thresholds_on_proposal
        """
        ctx = _provider_at_fourteen_open_points(api, catalog)
        _add_one_minor(api, ctx, catalog)
        provider = validate_success(
            api.get_provider(ctx["provider_id"], headers=supervisor_headers())
        )
        assert_point_ledger(provider, 15, 0, 15)

        validate_error(
            _propose(api, ctx, "PROBATION", "Fifteen open points; probation requested."),
            "ERR_LADDER_STEP_SKIP",
            409,
        )

        warning = validate_success(
            _propose(api, ctx, "WARNING", "Fifteen open points; warning issued."), 201
        )
        assert warning["ladder_step"] == 1
        assert_points(warning["basis_points"], 15, "basis_points")
        assert_cents(warning["fine_amount_cents"], 37500)

    def test_thirty_points_open_the_probation_rung_exactly(self, api, catalog):
        """The critical finding takes the provider to the probation threshold, and
        the accepted proposal prices a second-tier fine.

        PRD §3.8: "At 30 points, probation is exactly recommended and a probation
        proposal is accepted; at 29 points the recommendation is only a warning, so
        a probation proposal is refused while a warning proposal succeeds; at 14
        points every proposal fails on the basis test."

        Design: Difficulty/boundary_precision_check/boundary_enforcement_point_thresholds_on_proposal
        """
        ctx = _provider_at_fourteen_open_points(api, catalog)
        _add_one_minor(api, ctx, catalog)
        _add_one_critical(api, ctx, catalog)
        provider = validate_success(
            api.get_provider(ctx["provider_id"], headers=supervisor_headers())
        )
        assert_point_ledger(provider, 30, 0, 30)
        assert provider["critical_open_count"] == 1

        probation = validate_success(
            _propose(api, ctx, "PROBATION", "Thirty open points."), 201
        )
        assert probation["ladder_step"] == 2
        assert_points(probation["basis_points"], 30, "basis_points")
        assert_cents(probation["fine_amount_cents"], 130625)
        assert probation["status"] == "PROPOSED"
        assert (
            validate_success(
                api.get_provider(ctx["provider_id"], headers=supervisor_headers())
            )["current_ladder_step"]
            == 0
        ), "a PROPOSED action moves no ladder"

    def test_vacating_one_minor_point_closes_the_probation_rung_again(
        self, api, catalog
    ):
        """Twenty-nine live points refuse probation even though a 30-point
        proposal already exists, because the threshold is re-read from the
        provider, and the frozen basis of that older action does not move.

        PRD §3.8: "Two tests run against the provider's `open_violation_points`
        read at that instant."

        Design: Difficulty/boundary_precision_check/boundary_enforcement_point_thresholds_on_proposal
        """
        ctx = _provider_at_fourteen_open_points(api, catalog)
        minor = _add_one_minor(api, ctx, catalog)["violations"][0]
        _add_one_critical(api, ctx, catalog)
        probation = validate_success(
            _propose(api, ctx, "PROBATION", "Thirty open points."), 201
        )

        validate_success(
            api.disposition_violation(
                minor["id"],
                "VACATED",
                vacated_reason="The kitchen menu was posted inside the pantry door.",
                headers=supervisor_headers(),
            )
        )

        provider = validate_success(
            api.get_provider(ctx["provider_id"], headers=supervisor_headers())
        )
        assert_point_ledger(provider, 29, 0, 29)

        validate_error(
            _propose(api, ctx, "PROBATION", "Twenty-nine points; probation again."),
            "ERR_LADDER_STEP_SKIP",
            409,
        )
        warning = validate_success(
            _propose(api, ctx, "WARNING", "Twenty-nine open points; warning issued."),
            201,
        )
        assert_points(warning["basis_points"], 29, "basis_points")
        assert_cents(warning["fine_amount_cents"], 72500)

        frozen = validate_success(
            api.get_enforcement_action(probation["id"], headers=supervisor_headers())
        )
        assert_points(frozen["basis_points"], 30, "basis_points")
        assert_cents(frozen["fine_amount_cents"], 130625)


def _never_inspected_provider(api):
    """Lakeshore Center, with no finalized inspection at all, so the late-report
    cascade always has an empty candidate set."""
    fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
    provider = fx.create_provider(
        api,
        legal_name="Lakeshore Center",
        site_address="61 Lakeshore Blvd",
        program_type="CENTER",
        requested_capacity=20,
    )
    return provider["id"]


class TestIncidentReportingDeadlineInclusiveInstant:
    """§3.7: "compared on the exact instant to second resolution"."""

    def test_a_fatality_filed_at_the_two_hour_deadline_is_timely(self, api):
        """Filing exactly at noon for a ten o'clock fatality is timely; one second
        later is late.

        PRD §3.7: "A fatality occurring at 2026-08-05T10:00:00Z is due by
        2026-08-05T12:00:00Z, and one second past noon is late."

        Design: Difficulty/boundary_precision_check/boundary_incident_reporting_deadline_inclusive_instant
        """
        provider_id = _never_inspected_provider(api)

        fx.set_clock(api, "2026-08-05T12:00:00Z")
        on_time = fx.file_incident_report(
            api,
            provider_id,
            incident_type="FATALITY",
            occurred_at="2026-08-05T10:00:00Z",
            affected_child_age_group="INFANT",
            narrative="An infant was found unresponsive during nap time.",
        )
        assert_instant(
            on_time["reporting_deadline_at"],
            "2026-08-05T12:00:00Z",
            "reporting_deadline_at",
        )
        assert_instant(on_time["reported_at"], "2026-08-05T12:00:00Z", "reported_at")
        assert on_time["reporting_timeliness"] == "TIMELY"
        assert on_time["status"] == "REPORTED"

        fx.set_clock(api, "2026-08-05T12:00:01Z")
        late = fx.file_incident_report(
            api,
            provider_id,
            incident_type="FATALITY",
            occurred_at="2026-08-05T10:00:00Z",
            affected_child_age_group="INFANT",
            narrative="Duplicate filing of the same fatality, one second late.",
        )
        assert_instant(
            late["reporting_deadline_at"],
            "2026-08-05T12:00:00Z",
            "reporting_deadline_at",
        )
        assert late["reporting_timeliness"] == "LATE_REPORT"

    def test_the_twenty_four_and_seventy_two_hour_windows_behave_the_same_way(
        self, api
    ):
        """A serious injury is due 24 hours out and a communicable disease 72, and
        both are timely when filed exactly at the deadline.

        PRD §3.7: "`reporting_deadline_at` is `occurred_at` plus the type's
        reporting window: 2 hours for a fatality, 2 hours for a missing child, 24
        hours for a serious injury, 24 hours for a medication error, 72 hours for a
        communicable disease."

        Design: Difficulty/boundary_precision_check/boundary_incident_reporting_deadline_inclusive_instant
        """
        provider_id = _never_inspected_provider(api)

        fx.set_clock(api, "2026-08-06T00:00:00Z")
        injury_ok = fx.file_incident_report(
            api,
            provider_id,
            incident_type="SERIOUS_INJURY",
            occurred_at="2026-08-05T00:00:00Z",
            affected_child_age_group="TODDLER",
            narrative="A toddler required stitches after a fall from the climber.",
        )
        assert_instant(
            injury_ok["reporting_deadline_at"],
            "2026-08-06T00:00:00Z",
            "reporting_deadline_at",
        )
        assert injury_ok["reporting_timeliness"] == "TIMELY"

        fx.set_clock(api, "2026-08-06T00:00:01Z")
        injury_late = fx.file_incident_report(
            api,
            provider_id,
            incident_type="SERIOUS_INJURY",
            occurred_at="2026-08-05T00:00:00Z",
            affected_child_age_group="TODDLER",
            narrative="Second filing of the same injury, one second late.",
        )
        assert injury_late["reporting_timeliness"] == "LATE_REPORT"

        fx.set_clock(api, "2026-08-08T00:00:00Z")
        disease = fx.file_incident_report(
            api,
            provider_id,
            incident_type="COMMUNICABLE_DISEASE",
            occurred_at="2026-08-05T00:00:00Z",
            affected_child_age_group="SCHOOL_AGE",
            narrative="A confirmed pertussis case in the school-age group.",
        )
        assert_instant(
            disease["reporting_deadline_at"],
            "2026-08-08T00:00:00Z",
            "reporting_deadline_at",
        )
        assert disease["reporting_timeliness"] == "TIMELY"

    def test_an_incident_one_second_in_the_future_is_refused(self, api):
        """The occurrence instant may equal the clock but never exceed it.

        PRD §3.7: "An `occurred_at` strictly after the logical clock is refused
        with `ERR_INCIDENT_OCCURRED_IN_FUTURE` (HTTP 422); an incident occurring
        exactly at the current instant is accepted."

        Design: Difficulty/boundary_precision_check/boundary_incident_reporting_deadline_inclusive_instant
        """
        provider_id = _never_inspected_provider(api)
        fx.set_clock(api, "2026-08-06T00:00:01Z")

        validate_error(
            api.create_incident_report(
                f.incident_report_payload(
                    provider_id,
                    incident_type="MEDICATION_ERROR",
                    occurred_at="2026-08-06T00:00:02Z",
                    affected_child_age_group="PRESCHOOL",
                    narrative="A dose recorded one second in the future.",
                ),
                headers=make_applicant_headers(provider_id),
            ),
            "ERR_INCIDENT_OCCURRED_IN_FUTURE",
            422,
        )

        at_the_clock = fx.file_incident_report(
            api,
            provider_id,
            incident_type="MEDICATION_ERROR",
            occurred_at="2026-08-06T00:00:01Z",
            affected_child_age_group="PRESCHOOL",
            narrative="A dose recorded at exactly the current instant.",
        )
        assert at_the_clock["status"] == "REPORTED"
        assert at_the_clock["reporting_timeliness"] == "TIMELY"

    def test_a_late_filing_cites_nothing_when_the_provider_has_never_been_inspected(
        self, api
    ):
        """The conditional cascade finds no finalized inspection, so the flag stays
        false and no points land.

        PRD §3.7: "If the set is **empty** — a brand-new provider that has never
        been inspected — nothing is cited, `late_report_violation_created` stays
        false, and the report itself is still created successfully."

        Design: Difficulty/boundary_precision_check/boundary_incident_reporting_deadline_inclusive_instant
        """
        provider_id = _never_inspected_provider(api)
        fx.set_clock(api, "2026-08-05T12:00:01Z")

        late = fx.file_incident_report(
            api,
            provider_id,
            incident_type="FATALITY",
            occurred_at="2026-08-05T10:00:00Z",
            affected_child_age_group="INFANT",
            narrative="A fatality filed one second past the two-hour window.",
        )
        assert late["reporting_timeliness"] == "LATE_REPORT"
        assert late["late_report_violation_created"] is False
        assert late["generated_complaint_id"] is None

        provider = validate_success(
            api.get_provider(provider_id, headers=supervisor_headers())
        )
        assert_point_ledger(provider, 0, 0, 0)


def _visit_whose_lines_all_end_in_five(api, catalog):
    """Stonebridge Center: one finalized FAIL visit whose three deduction lines
    are 30.705, 13.125 and 0.875 — every one of them exactly on a half at the
    third decimal."""
    fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
    ada = fx.register_inspector(
        api,
        full_name="Ada Inspector",
        certified_age_groups=["INFANT", "SCHOOL_AGE"],
        max_daily_visits=3,
    )
    provider = fx.create_provider(
        api,
        legal_name="Stonebridge Center",
        site_address="71 Stonebridge Ln",
        program_type="CENTER",
        requested_capacity=28,
    )
    complaint = fx.intake_complaint(
        api,
        provider["id"],
        intake_channel="WEB",
        allegation_category="SUPERVISION",
        affected_age_group="INFANT",
        narrative="Web report of unsupervised infants and missing paperwork.",
        alleged_serious_harm=True,
        anonymous=True,
    )
    fx.screen_complaint(api, complaint["id"], "SCREEN_IN")
    visit = fx.run_visit(
        api,
        provider["id"],
        ada["id"],
        "2026-08-05T09:00:00Z",
        inspection_type="COMPLAINT",
        target_age_groups=["INFANT", "SCHOOL_AGE"],
        age_groups_observed=["INFANT", "SCHOOL_AGE"],
        duration_minutes=120,
        complaint_id=complaint["id"],
        catalog=catalog,
        citations=[
            {
                "code": CODE_SUPERVISION,
                "primary_age_group": "INFANT",
                "narrative": "Infant room unattended.",
            },
            {
                "code": CODE_SUPERVISION_PLAN,
                "primary_age_group": "SCHOOL_AGE",
                "narrative": "No written supervision plan for the school-age group.",
            },
            {
                "code": CODE_NUTRITION,
                "primary_age_group": "SCHOOL_AGE",
                "narrative": "Menu not posted for the school-age group.",
            },
        ],
        outcome="FAIL",
    )
    return {"provider_id": provider["id"], "inspection": visit["inspection"], "violations": visit["violations"]}


class TestRoundHalfUpAtTwoDecimalsInTheComplianceScore:
    """§3.5: "**The rounding mode is normative: round each line, then sum.**" """

    def test_each_line_rounds_its_trailing_half_upward(self, api, catalog):
        """The three points assessments are 23, 15 and 1, so the lines are 30.705,
        13.125 and 0.875, and each rounds up.

        PRD §3.5: "the line deduction is the violation's `assessed_points`
        multiplied by the exposure weight of its `primary_age_group` — 1.335 for
        `INFANT`, 1.150 for `TODDLER`, 1.000 for `PRESCHOOL`, 0.875 for
        `SCHOOL_AGE` — multiplied by that violation's status factor, and the product
        is rounded to two decimal places with halves going up."

        Design: Difficulty/boundary_precision_check/boundary_round_half_up_at_two_decimals_in_compliance_score
        """
        ctx = _visit_whose_lines_all_end_in_five(api, catalog)
        infant, school_age_critical, school_age_minor = ctx["violations"]

        assert_points(infant["assessed_points"], 23, "assessed_points")
        assert infant["infant_exposure"] is True
        assert_points(school_age_critical["assessed_points"], 15, "assessed_points")
        assert school_age_critical["infant_exposure"] is False
        assert_points(school_age_minor["assessed_points"], 1, "assessed_points")
        assert school_age_minor["infant_exposure"] is False

        inspection = validate_success(
            api.get_inspection(ctx["inspection"]["id"], headers=supervisor_headers())
        )
        assert inspection["violation_count"] == 3
        assert_score(
            inspection["raw_deduction_points"], 44.72, "raw_deduction_points"
        )
        assert inspection["raw_deduction_points"] != 44.69, (
            "44.69 is the sum of truncated lines 30.70 + 13.12 + 0.87"
        )
        assert inspection["raw_deduction_points"] != 44.71, (
            "44.71 is the single end-of-sum rounding of 30.705 + 13.125 + 0.875"
        )

    def test_the_stored_scores_and_the_computed_read_agree_on_fifty_five_point_two_eight(
        self, api, catalog
    ):
        """Both stored scores read 55.28, and so does the on-demand computation in
        either variant, because every finding is CORRECTION_PENDING.

        PRD §3.5: "`raw_deduction_points` is the sum of those already-rounded line
        deductions, itself rounded to two decimals. The score is 100 minus the raw
        deduction, floored at 0, rounded to two decimals."

        Design: Difficulty/boundary_precision_check/boundary_round_half_up_at_two_decimals_in_compliance_score
        """
        ctx = _visit_whose_lines_all_end_in_five(api, catalog)
        inspection = validate_success(
            api.get_inspection(ctx["inspection"]["id"], headers=supervisor_headers())
        )
        assert_score(
            inspection["final_compliance_score"], 55.28, "final_compliance_score"
        )
        assert_score(
            inspection["preliminary_compliance_score"],
            55.28,
            "preliminary_compliance_score",
        )
        for wrong in (55.31, 55.29):
            assert inspection["final_compliance_score"] != wrong, (
                f"{wrong} comes from rounding at the wrong stage or in the wrong "
                "direction"
            )

        final_read = validate_success(
            api.get_compliance_score(
                ctx["inspection"]["id"], variant="FINAL", headers=supervisor_headers()
            )
        )
        assert_compliance_score_read(final_read, "FINAL", 55.28, 44.72, 3)
        preliminary_read = validate_success(
            api.get_compliance_score(
                ctx["inspection"]["id"],
                variant="PRELIMINARY",
                headers=supervisor_headers(),
            )
        )
        assert_compliance_score_read(preliminary_read, "PRELIMINARY", 55.28, 44.72, 3)
