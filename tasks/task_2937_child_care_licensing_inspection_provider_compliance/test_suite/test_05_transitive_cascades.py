"""Two depth-four cascades where every link is caused by the link before it
(PRD §3.7, §3.3).

A substantiated determination mints a citation, the citation alone re-derives the
provider counters and the inspection score, and the new point total alone mints an
enforcement proposal.  A single disqualifying result bars a person, the bar alone
strips every room they lead, and the lost clearance alone reverts the application.
"""

from test_helpers import (
    CODE_RATIO,
    CODE_SUPERVISION,
    DEFAULT_LOGICAL_CLOCK,
    assert_cents,
    assert_instant,
    assert_point_ledger,
    assert_points,
    assert_risk,
    assert_risk_assessment,
    assert_score,
    fixtures as fx,
    make_applicant_headers,
    supervisor_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

TODDLER_AND_PRESCHOOL = ["TODDLER", "PRESCHOOL"]
ALL_AGE_GROUPS = ["INFANT", "TODDLER", "PRESCHOOL", "SCHOOL_AGE"]


def _complaint_ready_to_determine(api, catalog, *, citations, outcome):
    """A FINALIZED COMPLAINT visit plus its complaint under investigation.

    Ada works the visit and Ben takes the casework, because §3.7 bars an
    investigator who finalized a visit of the same provider inside twelve months.
    """
    fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
    ada = fx.register_inspector(
        api,
        full_name="Ada Inspector",
        certified_age_groups=TODDLER_AND_PRESCHOOL,
        max_daily_visits=3,
    )
    ben = fx.register_inspector(
        api,
        full_name="Ben Investigator",
        certified_age_groups=TODDLER_AND_PRESCHOOL,
        max_daily_visits=3,
    )
    provider = fx.create_provider(
        api,
        legal_name="Sunfield Center",
        site_address="7 Sunfield Way",
        program_type="CENTER",
        requested_capacity=60,
    )
    complaint = fx.intake_complaint(
        api,
        provider["id"],
        intake_channel="MANDATED_REPORTER",
        allegation_category="SUPERVISION",
        affected_age_group="PRESCHOOL",
        narrative="Preschool room left without any adult for several minutes.",
        alleged_serious_harm=True,
        anonymous=False,
        complainant_name="N. Nurse",
    )
    fx.screen_complaint(api, complaint["id"], "SCREEN_IN")
    visit = fx.run_visit(
        api,
        provider["id"],
        ada["id"],
        "2026-08-05T09:00:00Z",
        inspection_type="COMPLAINT",
        target_age_groups=["PRESCHOOL", "TODDLER"],
        age_groups_observed=["PRESCHOOL", "TODDLER"],
        duration_minutes=120,
        complaint_id=complaint["id"],
        catalog=catalog,
        citations=citations,
        outcome=outcome,
    )
    fx.assign_investigator(api, complaint["id"], ben["id"])
    return {
        "provider_id": provider["id"],
        "complaint_id": complaint["id"],
        "inspection": visit["inspection"],
        "violations": visit["violations"],
        "ada": ada,
        "ben": ben,
    }


SEEDED_CITATIONS = [
    {
        "code": CODE_SUPERVISION,
        "primary_age_group": "PRESCHOOL",
        "narrative": "Preschool room unattended at 09:40.",
    },
    {
        "code": CODE_RATIO,
        "primary_age_group": "TODDLER",
        "narrative": "Toddler room at 14 children to two staff.",
    },
]


class TestSubstantiationCascade:
    """§3.7: "**The determination is the deepest cascade in the service.**" """

    def test_link_one_determines_the_complaint_on_time(self, api, catalog):
        """The determination stores itself and flags timeliness against the P2
        deadline, forty-five days out from a 2026-08-01 intake.

        PRD §3.7: "Link one always runs: `status` becomes `DETERMINED`, the
        `determination` is stored, `determined_at` is stamped, and
        `timeliness_flag` is set to `ON_TIME` when `determined_at` is at or before
        `investigation_due_at` — the edge is inclusive — and to `LATE` otherwise."

        Design: Difficulty/transitive_cascade/cascade_substantiation_to_auto_violation_to_counters_to_enforcement
        """
        ctx = _complaint_ready_to_determine(
            api, catalog, citations=SEEDED_CITATIONS, outcome="FAIL"
        )
        before = validate_success(
            api.get_provider(ctx["provider_id"], headers=supervisor_headers())
        )
        assert_point_ledger(before, 23, 0, 23)
        assert before["critical_open_count"] == 1
        baseline = validate_success(
            api.get_inspection(ctx["inspection"]["id"], headers=supervisor_headers())
        )
        assert_score(
            baseline["preliminary_compliance_score"], 75.80, "preliminary_compliance_score"
        )
        assert baseline["violation_count"] == 2

        determined = fx.record_determination(
            api, ctx["complaint_id"], ctx["ben"]["id"], "SUBSTANTIATED"
        )

        assert determined["status"] == "DETERMINED"
        assert determined["determination"] == "SUBSTANTIATED"
        assert_instant(determined["determined_at"], DEFAULT_LOGICAL_CLOCK, "determined_at")
        assert_instant(
            determined["investigation_due_at"],
            "2026-09-15T00:00:00Z",
            "investigation_due_at",
        )
        assert determined["timeliness_flag"] == "ON_TIME"

    def test_link_two_mints_exactly_one_auto_generated_citation(self, api, catalog):
        """The category maps to SU-101, the citation lands on the finalized
        complaint visit already in CORRECTION_PENDING, and its infant exposure is
        false because INFANT was never observed.

        PRD §3.7: "It is created directly in `CORRECTION_PENDING` rather than
        `CITED`, because the inspection carrying it is already finalized."

        Design: Difficulty/transitive_cascade/cascade_substantiation_to_auto_violation_to_counters_to_enforcement
        """
        ctx = _complaint_ready_to_determine(
            api, catalog, citations=SEEDED_CITATIONS, outcome="FAIL"
        )
        seeded_ids = {violation["id"] for violation in ctx["violations"]}

        fx.record_determination(api, ctx["complaint_id"], ctx["ben"]["id"], "SUBSTANTIATED")

        rows, _meta = validate_paginated(
            api.list_violations(
                inspection_id=ctx["inspection"]["id"], headers=supervisor_headers()
            )
        )
        auto = [row for row in rows if row["id"] not in seeded_ids]
        assert len(auto) == 1, f"expected exactly one auto citation, got {len(auto)}"
        citation = auto[0]

        assert citation["auto_generated"] is True
        assert citation["inspection_id"] == ctx["inspection"]["id"]
        assert citation["checklist_item_id"] == catalog[CODE_SUPERVISION]
        assert citation["primary_age_group"] == "PRESCHOOL"
        assert citation["severity"] == "CRITICAL"
        assert_points(citation["assessed_points"], 15, "assessed_points")
        assert citation["infant_exposure"] is False
        assert citation["status"] == "CORRECTION_PENDING"
        assert citation["repeat_of_violation_id"] is None
        assert_instant(
            citation["correction_due_date"], "2026-08-04T00:00:00Z", "correction_due_date"
        )

    def test_link_three_re_derives_the_counters_and_leaves_the_preliminary_frozen(
        self, api, catalog
    ):
        """The new citation alone moves the provider to 38 open points and 56.00
        risk, and moves the inspection's final score without touching the frozen
        preliminary one.

        PRD §3.7: "Note that the frozen `preliminary_compliance_score` of that
        inspection is not touched, so a cascade citation makes the two scores
        diverge."

        Design: Difficulty/transitive_cascade/cascade_substantiation_to_auto_violation_to_counters_to_enforcement
        """
        ctx = _complaint_ready_to_determine(
            api, catalog, citations=SEEDED_CITATIONS, outcome="FAIL"
        )
        fx.record_determination(api, ctx["complaint_id"], ctx["ben"]["id"], "SUBSTANTIATED")

        provider = validate_success(
            api.get_provider(ctx["provider_id"], headers=supervisor_headers())
        )
        assert_point_ledger(provider, 38, 0, 38)
        assert provider["critical_open_count"] == 2
        assert provider["critical_violation_count_24mo"] == 2
        assert provider["substantiated_complaint_count_24mo"] == 1
        assert_risk(provider, 56.00, "HIGH")

        inspection = validate_success(
            api.get_inspection(ctx["inspection"]["id"], headers=supervisor_headers())
        )
        assert inspection["violation_count"] == 3
        assert_score(inspection["raw_deduction_points"], 39.20, "raw_deduction_points")
        assert_score(inspection["final_compliance_score"], 60.80, "final_compliance_score")
        assert_score(
            inspection["preliminary_compliance_score"],
            75.80,
            "preliminary_compliance_score",
        )

        read = validate_success(
            api.get_risk_assessment(
                ctx["provider_id"],
                variant="ENFORCEMENT_REVIEW",
                headers=supervisor_headers(),
            )
        )
        assert_risk_assessment(
            read,
            "ENFORCEMENT_REVIEW",
            56.00,
            "HIGH",
            open_violation_points=38,
            substantiated_complaint_count_24mo=1,
            critical_violation_count_24mo=2,
        )

    def test_link_four_mints_a_probation_proposal_nobody_asked_for(self, api, catalog):
        """Thirty-eight recomputed points cross the threshold, so the cascade
        creates a PROPOSED probation carrying a fine of 151525 while the provider's
        own ladder step stays at 0.

        PRD §3.7: "one enforcement action is auto-created in `PROPOSED`, with
        `source_inspection_id` set to the target inspection, `action_type` and
        `ladder_step` taken from the ladder rule, `basis_points` set to the
        recomputed `open_violation_points`, and `fine_amount_cents` computed from
        the fine rule."

        Design: Difficulty/transitive_cascade/cascade_substantiation_to_auto_violation_to_counters_to_enforcement
        """
        ctx = _complaint_ready_to_determine(
            api, catalog, citations=SEEDED_CITATIONS, outcome="FAIL"
        )
        fx.record_determination(api, ctx["complaint_id"], ctx["ben"]["id"], "SUBSTANTIATED")

        actions, _meta = validate_paginated(
            api.list_enforcement_actions(
                provider_id=ctx["provider_id"], headers=supervisor_headers()
            )
        )
        assert len(actions) == 1, f"expected one auto-created action, got {len(actions)}"
        action = actions[0]

        assert action["status"] == "PROPOSED"
        assert action["action_type"] == "PROBATION"
        assert action["ladder_step"] == 2
        assert_points(action["basis_points"], 38, "basis_points")
        assert action["source_inspection_id"] == ctx["inspection"]["id"]
        assert_cents(action["fine_amount_cents"], 151525)

        provider = validate_success(
            api.get_provider(ctx["provider_id"], headers=supervisor_headers())
        )
        assert provider["current_ladder_step"] == 0, (
            "a PROPOSED action has not been effectuated and moves no ladder"
        )

    def test_the_chain_stops_after_link_three_without_the_seeded_findings(
        self, api, catalog
    ):
        """The same determination on a visit that cited nothing leaves 15 open
        points, below the threshold, so link four never fires.

        PRD §3.7: "If the points stay below 30, or the provider is already at
        ladder step 2 or higher, the chain stops after link three and no action is
        created."

        Design: Difficulty/transitive_cascade/cascade_substantiation_to_auto_violation_to_counters_to_enforcement
        """
        ctx = _complaint_ready_to_determine(api, catalog, citations=None, outcome="PASS")
        fx.record_determination(api, ctx["complaint_id"], ctx["ben"]["id"], "SUBSTANTIATED")

        provider = validate_success(
            api.get_provider(ctx["provider_id"], headers=supervisor_headers())
        )
        assert_point_ledger(provider, 15, 0, 15)

        actions, _meta = validate_paginated(
            api.list_enforcement_actions(
                provider_id=ctx["provider_id"], headers=supervisor_headers()
            )
        )
        assert actions == [], (
            "fifteen open points are below the 30-point threshold, so the cascade "
            f"must stop after link three; got {actions!r}"
        )


ROOM_SPECS = [
    ("INFANT", 8, 2),
    ("TODDLER", 12, 2),
    ("PRESCHOOL", 20, 2),
    ("SCHOOL_AGE", 20, 0),
]


def _cleared_provider_awaiting_its_initial_visit(api, catalog):
    """Harborview Center: one cleared director leading all four empty rooms, the
    application at CHECKS_CLEARED, a SCHEDULED INITIAL visit, and a third
    STATE_CRIMINAL check on the director still SUBMITTED."""
    fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
    ada = fx.register_inspector(
        api,
        full_name="Ada Inspector",
        certified_age_groups=ALL_AGE_GROUPS,
        max_daily_visits=3,
    )
    provider = fx.create_provider(
        api,
        legal_name="Harborview Center",
        site_address="8 Harborview Rd",
        program_type="CENTER",
        requested_capacity=60,
    )
    provider_id = provider["id"]
    applicant = make_applicant_headers(provider_id)

    director = fx.attach_staff(
        api,
        provider_id,
        full_name="Dana Director",
        member_type="DIRECTOR",
        qualified_age_groups=ALL_AGE_GROUPS,
        role_title="Center Director",
    )
    required_checks = fx.clear_person(api, director["id"])

    rosters = {}
    for age_group, size, staff in ROOM_SPECS:
        rosters[age_group] = fx.add_roster(
            api,
            provider_id,
            age_group=age_group,
            requested_group_size=size,
            enrolled_count=0,
            staff_assigned_count=staff,
            lead_staff_member_id=director["id"],
        )

    validate_success(api.submit_application(provider_id, headers=applicant))
    validate_success(api.clear_checks(provider_id, headers=supervisor_headers()))

    inspection = fx.schedule_visit(
        api,
        provider_id,
        ada["id"],
        "2026-08-05T09:00:00Z",
        inspection_type="INITIAL",
        target_age_groups=ALL_AGE_GROUPS,
        duration_minutes=120,
    )
    state_criminal = fx.open_check(api, director["id"], "STATE_CRIMINAL")

    return {
        "provider_id": provider_id,
        "applicant": applicant,
        "director": director,
        "required_checks": required_checks,
        "rosters": rosters,
        "inspection": inspection,
        "state_criminal": state_criminal,
    }


def _disqualify_permanently(api, ctx):
    return fx.record_result(
        api, ctx["state_criminal"]["id"], "DISQUALIFIED", tier="TIER_1_PERMANENT"
    )


class TestDisqualificationCascade:
    """§3.3: "**A disqualification is not a single write — it is a four-link
    chain, each link caused by the link before it, not by the request.**" """

    def test_link_one_disqualifies_only_the_third_check(self, api, catalog):
        """The STATE_CRIMINAL result lands with no expiry, and the two required
        checks behind the clearance are untouched.

        PRD §3.3: "Link one records the result: the check becomes `DISQUALIFIED`."

        Design: Difficulty/transitive_cascade/cascade_disqualification_to_barred_staff_to_rosters_to_application_revert
        """
        ctx = _cleared_provider_awaiting_its_initial_visit(api, catalog)
        before = validate_success(
            api.get_provider(ctx["provider_id"], headers=supervisor_headers())
        )
        assert before["clearance_complete"] is True
        assert before["application_status"] == "CHECKS_CLEARED"
        assert (
            validate_success(
                api.get_inspection(ctx["inspection"]["id"], headers=supervisor_headers())
            )["status"]
            == "SCHEDULED"
        )
        for age_group in ctx["rosters"]:
            room = validate_success(
                api.get_roster(ctx["rosters"][age_group]["id"], headers=supervisor_headers())
            )
            assert room["supervision_compliant"] is True, age_group

        disqualified = _disqualify_permanently(api, ctx)

        assert disqualified["status"] == "DISQUALIFIED"
        assert disqualified["check_type"] == "STATE_CRIMINAL"
        assert disqualified["disqualifying_offense_tier"] == "TIER_1_PERMANENT"
        assert_instant(disqualified["decided_at"], DEFAULT_LOGICAL_CLOCK, "decided_at")
        assert disqualified["expires_at"] is None

        for check_type, check in ctx["required_checks"].items():
            still = validate_success(
                api.get_background_check(check["id"], headers=supervisor_headers())
            )
            assert still["status"] == "CLEARED", check_type
            assert_instant(
                still["expires_at"], "2031-08-01T00:00:00Z", f"{check_type}.expires_at"
            )

    def test_link_two_bars_the_person_one_bad_result_beats_two_good_ones(
        self, api, catalog
    ):
        """The director is BARRED at the permanent tier even though both required
        clearances are still good.

        PRD §3.3: "A disqualification therefore outranks everything, and one bad
        result bars a person who has ten good ones."

        Design: Difficulty/transitive_cascade/cascade_disqualification_to_barred_staff_to_rosters_to_application_revert
        """
        ctx = _cleared_provider_awaiting_its_initial_visit(api, catalog)
        _disqualify_permanently(api, ctx)

        person = validate_success(
            api.get_staff_member(ctx["director"]["id"], headers=supervisor_headers())
        )
        assert person["clearance_status"] == "BARRED"
        assert person["supervision_eligible"] is False
        assert person["barred_offense_tier"] == "TIER_1_PERMANENT"

    def test_link_three_strips_every_room_the_barred_person_led(self, api, catalog):
        """All four rooms lose their lead and each assigned-staff count drops by
        one, except the SCHOOL_AGE room already at zero, which holds the floor.

        PRD §3.3: "`lead_staff_member_id` is set to null, `staff_assigned_count` is
        decremented by one but never below zero, and `required_staff_count`,
        `ratio_compliant` and `supervision_compliant` are recomputed on each such
        room."

        Design: Difficulty/transitive_cascade/cascade_disqualification_to_barred_staff_to_rosters_to_application_revert
        """
        ctx = _cleared_provider_awaiting_its_initial_visit(api, catalog)
        _disqualify_permanently(api, ctx)

        expected_staff = {"INFANT": 1, "TODDLER": 1, "PRESCHOOL": 1, "SCHOOL_AGE": 0}
        for age_group, expected in expected_staff.items():
            room = validate_success(
                api.get_roster(
                    ctx["rosters"][age_group]["id"], headers=supervisor_headers()
                )
            )
            assert room["lead_staff_member_id"] is None, age_group
            assert room["staff_assigned_count"] == expected, (
                f"{age_group}: expected {expected} assigned staff after the sweep, "
                f"got {room['staff_assigned_count']}"
            )
            assert room["enrolled_count"] == 0, age_group
            assert room["required_staff_count"] == 0, (
                f"{age_group}: no children are enrolled, so the required count is 0"
            )
            assert room["ratio_compliant"] is True, (
                f"{age_group}: zero assigned staff still meets a zero requirement"
            )
            assert room["supervision_compliant"] is True, (
                f"{age_group}: §3.2 makes a room supervision-compliant 'when no "
                "children are enrolled', which the lead sweep cannot change"
            )

    def test_link_four_reverts_the_application_and_voids_the_initial_visit(
        self, api, catalog
    ):
        """The lost clearance walks the application back along its cyclic edge and
        voids the SCHEDULED initial inspection, on one provider version bump.

        PRD §3.3: "Link four, *because* the provider's `clearance_complete` has
        flipped from true to false, reverts `application_status` from
        `CHECKS_CLEARED` to `SUBMITTED` — the cyclic edge of that dimension — and
        voids every `INITIAL` inspection of that provider whose status is
        `SCHEDULED` or `IN_PROGRESS`."

        Design: Difficulty/transitive_cascade/cascade_disqualification_to_barred_staff_to_rosters_to_application_revert
        """
        ctx = _cleared_provider_awaiting_its_initial_visit(api, catalog)
        before = validate_success(
            api.get_provider(ctx["provider_id"], headers=supervisor_headers())
        )

        _disqualify_permanently(api, ctx)

        after = validate_success(
            api.get_provider(ctx["provider_id"], headers=supervisor_headers())
        )
        assert after["clearance_complete"] is False
        assert after["application_status"] == "SUBMITTED"
        assert after["license_status"] == "NONE"
        assert after["version"] == before["version"] + 1, (
            "the whole cascade is one provider write, so the version advances "
            f"exactly once: {before['version']} -> {after['version']}"
        )

        inspection = validate_success(
            api.get_inspection(ctx["inspection"]["id"], headers=supervisor_headers())
        )
        assert inspection["status"] == "VOIDED"

    def test_a_permanent_bar_can_never_enter_the_waiver_loop(self, api, catalog):
        """The owning applicant's waiver request is refused on the tier, and no
        link of the chain is undone.

        PRD §3.3: "a check whose `disqualifying_offense_tier` is
        `TIER_1_PERMANENT` can never enter this path at all: it is refused with
        `ERR_PERMANENT_BAR_NOT_WAIVABLE` (HTTP 409)."

        Design: Difficulty/transitive_cascade/cascade_disqualification_to_barred_staff_to_rosters_to_application_revert
        """
        ctx = _cleared_provider_awaiting_its_initial_visit(api, catalog)
        _disqualify_permanently(api, ctx)

        validate_error(
            api.request_waiver(
                ctx["state_criminal"]["id"],
                "The offense is thirty years old and unrelated to child care.",
                headers=ctx["applicant"],
            ),
            "ERR_PERMANENT_BAR_NOT_WAIVABLE",
            409,
        )

        check = validate_success(
            api.get_background_check(
                ctx["state_criminal"]["id"], headers=supervisor_headers()
            )
        )
        assert check["status"] == "DISQUALIFIED"
        assert check["waiver_requested_at"] is None
        person = validate_success(
            api.get_staff_member(ctx["director"]["id"], headers=supervisor_headers())
        )
        assert person["clearance_status"] == "BARRED"
        provider = validate_success(
            api.get_provider(ctx["provider_id"], headers=supervisor_headers())
        )
        assert provider["application_status"] == "SUBMITTED"

    def test_the_provider_cannot_re_enter_checks_cleared(self, api, catalog):
        """Clearance is recomputed before it is required, so the supervisor's
        second advance is refused while the bar stands.

        PRD §3.3: "the supervisor's clearance advance, which moves
        `application_status` from `SUBMITTED` to `CHECKS_CLEARED` and recomputes
        the flag before requiring it to be true ... In all three, a false flag is
        `ERR_CLEARANCE_INCOMPLETE` (HTTP 409)."

        Design: Difficulty/transitive_cascade/cascade_disqualification_to_barred_staff_to_rosters_to_application_revert
        """
        ctx = _cleared_provider_awaiting_its_initial_visit(api, catalog)
        _disqualify_permanently(api, ctx)

        validate_error(
            api.clear_checks(ctx["provider_id"], headers=supervisor_headers()),
            "ERR_CLEARANCE_INCOMPLETE",
            409,
        )

        provider = validate_success(
            api.get_provider(ctx["provider_id"], headers=supervisor_headers())
        )
        assert provider["application_status"] == "SUBMITTED"
        assert provider["clearance_complete"] is False
