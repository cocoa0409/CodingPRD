"""Endpoint kinds: the partial update, the action verbs and the computed read.

These cases are about the shape of the surface — what a PATCH leaves alone, what an
action endpoint does and does not touch, and what a computed read answers with when
its selector is omitted.
"""

from test_helpers import (
    CODE_SUPERVISION,
    DEFAULT_LOGICAL_CLOCK,
    admin_headers,
    assert_instant,
    assert_risk_assessment,
    assert_roster_flags,
    assert_score,
    factories as f,
    fixtures as fx,
    make_applicant_headers,
    supervisor_headers,
    validate_error,
    validate_success,
)

PRESCHOOL_ONLY = ["PRESCHOOL"]
VISIT_INSTANT = "2026-08-05T09:00:00Z"


class TestTheOnlyPartialUpdate:
    """§3.2: "Updating a room accepts any of `enrolled_count`,
    `staff_assigned_count` and `lead_staff_member_id`"."""

    def test_a_patch_that_names_one_field_leaves_the_others_where_they_were(
        self, api, catalog
    ):
        """The second PATCH carries only the staff count, and the enrolment and the
        null lead survive it while the version advances and the flags re-derive.

        PRD §3.2: "Updating a room accepts any of `enrolled_count`,
        `staff_assigned_count` and `lead_staff_member_id`, and re-derives the
        required staff count and all three compliance flags."

        Design: Corner/endpoints/endpoint_standard_crud_roster_patch_is_a_partial_update
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        base = fx.setup_licensed_provider(api, requested_capacity=10, catalog=catalog)
        ctx = base["ctx"]
        owner = make_applicant_headers(ctx.id)
        room = ctx.reload_roster("PRESCHOOL")
        assert room["approved_group_size"] == 10
        assert room["lead_staff_member_id"] is None
        first_version = room["version"]

        both = validate_success(
            api.patch_roster(
                room["id"], enrolled_count=5, staff_assigned_count=1, headers=owner
            )
        )
        assert both["required_staff_count"] == 1, "ceil(5 preschoolers / 10 per adult)"
        assert both["version"] == first_version + 1

        staff_only = validate_success(
            api.patch_roster(room["id"], staff_assigned_count=2, headers=owner)
        )
        assert staff_only["enrolled_count"] == 5, (
            "the second PATCH omitted enrolled_count and must not reset it"
        )
        assert staff_only["staff_assigned_count"] == 2
        assert staff_only["lead_staff_member_id"] is None
        assert staff_only["version"] == both["version"] + 1

        read_back = validate_success(
            api.get_roster(room["id"], headers=supervisor_headers())
        )
        assert_roster_flags(
            read_back,
            ratio_compliant=True,
            group_size_compliant=True,
            supervision_compliant=False,
            required_staff_count=1,
        )
        assert read_back["last_verified_at"] is None, (
            "a PATCH is not an explicit verification"
        )


class TestLeaveStatusIsForwardLookingOnly:
    """§3.1: "Going on leave does **not** void visits already scheduled"."""

    def test_going_on_leave_blocks_new_scheduling_and_nothing_else(self, api):
        """The standing visit survives, the next scheduling request is refused, and
        flipping back to ACTIVE lets the identical request through.

        PRD §3.1: "it blocks only *new* scheduling and *new* investigator
        assignment, each of which is refused with `ERR_INSPECTOR_ON_LEAVE` while the
        inspector is on leave. Every leave-status change increments the inspector's
        `version`."

        Design: Corner/endpoints/endpoint_action_endpoint_leave_status_blocks_new_scheduling_only
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        provider = fx.create_provider(api, requested_capacity=10)
        inspector = fx.register_inspector(api, certified_age_groups=PRESCHOOL_ONLY)
        standing = fx.schedule_visit(
            api,
            provider["id"],
            inspector["id"],
            "2026-08-10T09:00:00Z",
            inspection_type="ANNUAL",
            target_age_groups=PRESCHOOL_ONLY,
        )

        # the revision is read immediately before the leave change, because the
        # rule under test is that *that change* adds exactly one
        before_leave = validate_success(
            api.get_inspector(inspector["id"], headers=admin_headers())
        )
        on_leave = validate_success(
            api.set_inspector_leave_status(
                inspector["id"], "ON_LEAVE", headers=admin_headers()
            )
        )
        assert on_leave["status"] == "ON_LEAVE"
        assert on_leave["version"] == before_leave["version"] + 1

        untouched = validate_success(
            api.get_inspection(standing["id"], headers=admin_headers())
        )
        assert untouched["status"] == "SCHEDULED", "going on leave voids nothing"

        def next_visit():
            return api.create_inspection(
                f.inspection_payload(
                    provider["id"],
                    inspector["id"],
                    inspection_type="ANNUAL",
                    scheduled_for="2026-08-14T09:00:00Z",
                    target_age_groups=PRESCHOOL_ONLY,
                ),
                headers=supervisor_headers(),
            )

        validate_error(next_visit(), "ERR_INSPECTOR_ON_LEAVE", 409)
        during_leave = validate_success(
            api.get_inspector(inspector["id"], headers=admin_headers())
        )
        assert during_leave["scheduled_visit_count"] == 1

        back = validate_success(
            api.set_inspector_leave_status(
                inspector["id"], "ACTIVE", headers=admin_headers()
            )
        )
        assert back["status"] == "ACTIVE"
        validate_success(next_visit(), 201)

        after = validate_success(
            api.get_inspector(inspector["id"], headers=admin_headers())
        )
        assert after["scheduled_visit_count"] == 2


class TestTheCrossReferenceLink:
    """§3.9: "A finalized inspection of the right provider but the wrong type is
    therefore refused on the type, not the state"."""

    def test_only_the_pre_move_visit_may_be_attached_to_a_site_move(self, api, catalog):
        """The provider's finalized ANNUAL visit is refused on its type; its
        finalized AMENDMENT_PRE_MOVE visit links the amendment into SUBMITTED.

        PRD §3.9: "the inspection must exist (`ERR_INSPECTION_NOT_FOUND`), must
        belong to the same provider as the amendment
        (`ERR_VIOLATION_INSPECTION_MISMATCH`, HTTP 422), must be `FINALIZED`
        (`ERR_INVALID_INSPECTION_STATE`), and must have `inspection_type` equal to
        `AMENDMENT_PRE_MOVE` (`ERR_INVALID_INSPECTION_TYPE`, HTTP 409)."

        Design: Corner/endpoints/endpoint_cross_reference_link_amendment_needs_a_pre_move_inspection
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        provider = fx.create_provider(api, requested_capacity=10)
        inspector = fx.register_inspector(api, certified_age_groups=PRESCHOOL_ONLY)
        annual = fx.schedule_visit(
            api,
            provider["id"],
            inspector["id"],
            VISIT_INSTANT,
            inspection_type="ANNUAL",
            target_age_groups=PRESCHOOL_ONLY,
        )
        pre_move = fx.schedule_visit(
            api,
            provider["id"],
            inspector["id"],
            "2026-08-06T09:00:00Z",
            inspection_type="AMENDMENT_PRE_MOVE",
            target_age_groups=PRESCHOOL_ONLY,
        )
        for instant, inspection in (
            (VISIT_INSTANT, annual),
            ("2026-08-06T09:00:00Z", pre_move),
        ):
            fx.set_clock(api, instant)
            fx.start_visit(api, inspection["id"], inspector["id"])
            fx.submit_findings(
                api, inspection["id"], inspector["id"], "PASS", PRESCHOOL_ONLY
            )
            assert fx.finalize_visit(api, inspection["id"])["status"] == "FINALIZED"

        current = validate_success(
            api.get_provider(provider["id"], headers=make_applicant_headers(provider["id"]))
        )
        amendment = validate_success(
            api.create_amendment(
                f.amendment_payload(
                    provider["id"],
                    "SITE_MOVE",
                    current["version"],
                    new_site_address="88 Oak Ave",
                ),
                headers=make_applicant_headers(provider["id"]),
            ),
            201,
        )
        assert amendment["requires_inspection"] is True
        assert amendment["status"] == "PRE_INSPECTION_REQUIRED"
        assert amendment["effective_capacity_delta"] == 0
        assert amendment["pre_move_inspection_id"] is None

        validate_error(
            api.attach_pre_move_inspection(
                amendment["id"], annual["id"], headers=supervisor_headers()
            ),
            "ERR_INVALID_INSPECTION_TYPE",
            409,
        )
        refused = validate_success(
            api.get_amendment(amendment["id"], headers=supervisor_headers())
        )
        assert refused["pre_move_inspection_id"] is None
        assert refused["status"] == "PRE_INSPECTION_REQUIRED"
        assert refused["version"] == amendment["version"]

        linked = validate_success(
            api.attach_pre_move_inspection(
                amendment["id"], pre_move["id"], headers=supervisor_headers()
            )
        )
        assert linked["status"] == "SUBMITTED"
        assert linked["pre_move_inspection_id"] == pre_move["id"]
        assert linked["version"] == amendment["version"] + 1


class TestTheComputedRiskRead:
    """§4: "`variant` selects INTAKE_SCREENING or ENFORCEMENT_REVIEW and defaults to
    ENFORCEMENT_REVIEW when omitted"."""

    def test_the_read_defaults_to_enforcement_review_and_writes_nothing(
        self, api, catalog
    ):
        """Fifteen open points plus the critical-standing flat 10 make 25.00, which
        bands MODERATE, and the GET leaves the provider row alone.

        PRD §3.5: "Take the smaller of `open_violation_points` and 60, weighted at
        1.0. Add 8 points for each complaint counted in
        `substantiated_complaint_count_24mo`. Add the variant's inconclusive weight
        for each complaint counted in `inconclusive_complaint_count_24mo`. Add a
        flat 10 when `critical_violation_count_24mo` is at least 1."

        Design: Corner/endpoints/endpoint_computed_read_risk_assessment_defaults_to_enforcement_review
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        provider = fx.create_provider(api, requested_capacity=10)
        inspector = fx.register_inspector(api, certified_age_groups=PRESCHOOL_ONLY)
        inspection = fx.schedule_visit(
            api,
            provider["id"],
            inspector["id"],
            VISIT_INSTANT,
            inspection_type="ANNUAL",
            target_age_groups=PRESCHOOL_ONLY,
        )
        fx.set_clock(api, VISIT_INSTANT)
        fx.start_visit(api, inspection["id"], inspector["id"])
        fx.cite(
            api,
            inspection["id"],
            inspector["id"],
            catalog[CODE_SUPERVISION],
            primary_age_group="PRESCHOOL",
            narrative="Unsupervised nap room.",
        )
        fx.submit_findings(api, inspection["id"], inspector["id"], "FAIL", PRESCHOOL_ONLY)
        fx.finalize_visit(api, inspection["id"])

        before = validate_success(
            api.get_provider(provider["id"], headers=admin_headers())
        )
        assessment = validate_success(
            api.get_risk_assessment(provider["id"], headers=supervisor_headers())
        )
        assert_risk_assessment(
            assessment,
            "ENFORCEMENT_REVIEW",
            25.00,
            "MODERATE",
            open_violation_points=15,
            substantiated_complaint_count_24mo=0,
            inconclusive_complaint_count_24mo=0,
            critical_violation_count_24mo=1,
        )

        after = validate_success(
            api.get_provider(provider["id"], headers=admin_headers())
        )
        assert after["version"] == before["version"], "a computed read performs no write"


class TestPromotionNeedsBothGates:
    """§3.8: "**Promotion to full licensure** carries four preconditions and is
    refused with a different error for each"."""

    def test_promotion_waits_for_the_six_months_and_the_passing_annual_visit(
        self, api, catalog
    ):
        """At the licensure instant the promotion is premature; six months and one
        passing ANNUAL visit later the same call moves the licence to FULL.

        PRD §3.8: "the current instant must be at or after `provisional_started_at`
        plus 6 months, with the lower edge inclusive, so promoting exactly at the
        six-month instant succeeds and a moment earlier is
        `ERR_PROVISIONAL_PERIOD_NOT_ELAPSED`"

        Design: Corner/endpoints/endpoint_conditional_action_promote_to_full_needs_the_period_and_a_pass
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        base = fx.setup_licensed_provider(
            api,
            requested_capacity=10,
            inspector_certified_age_groups=PRESCHOOL_ONLY,
            initial_scheduled_for=VISIT_INSTANT,
            catalog=catalog,
        )
        ctx = base["ctx"]
        licensed = ctx.reload()
        assert licensed["license_status"] == "PROVISIONAL"
        # §3.8 stamps provisional_started_at with the instant of the ISSUE
        # decision, which the licensing walk takes at the unmoved clock
        assert_instant(
            licensed["provisional_started_at"],
            DEFAULT_LOGICAL_CLOCK,
            "provisional_started_at",
        )
        assert licensed["license_number"] == "LIC-01-0001"

        # the passing ANNUAL visit is finalized first — well inside the provisional
        # period — so the premature attempt below violates the six-month rule alone
        annual = fx.schedule_visit(
            api,
            ctx.id,
            base["inspector"]["id"],
            "2026-08-10T09:00:00Z",
            inspection_type="ANNUAL",
            target_age_groups=PRESCHOOL_ONLY,
        )
        fx.set_clock(api, "2026-08-10T09:00:00Z")
        fx.start_visit(api, annual["id"], base["inspector"]["id"])
        fx.submit_findings(
            api, annual["id"], base["inspector"]["id"], "PASS", PRESCHOOL_ONLY
        )
        finalized = fx.finalize_visit(api, annual["id"])
        assert finalized["status"] == "FINALIZED"
        assert_score(finalized["final_compliance_score"], 100.00, "final")

        validate_error(
            api.promote_to_full(ctx.id, headers=supervisor_headers()),
            "ERR_PROVISIONAL_PERIOD_NOT_ELAPSED",
            409,
        )
        assert ctx.reload()["license_status"] == "PROVISIONAL"

        # exactly provisional_started_at plus six months: the lower edge is inclusive
        fx.set_clock(api, "2027-02-01T00:00:00Z")
        promoted = validate_success(
            api.promote_to_full(ctx.id, headers=supervisor_headers())
        )
        assert promoted["license_status"] == "FULL"
        assert promoted["application_status"] == "LICENSED"
        assert promoted["licensed_capacity"] == 10
        assert promoted["open_violation_points"] == 0
        assert promoted["critical_open_count"] == 0
