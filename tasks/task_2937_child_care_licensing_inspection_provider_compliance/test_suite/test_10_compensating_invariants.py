"""Two conserved quantities and their compensating actions (PRD §3.5, §3.8).

Violation points must satisfy lifetime == open + resolved after every mutation: a
correction moves points between the two buckets, a vacatur removes them from both.
Authorised capacity slots must satisfy licensed + suspended == constant across a
suspension, its appeal and a vacated decision, and the vacatur restores the slots
without restoring the fine, the ladder or the history.
"""

from test_helpers import (
    ADMIN_2,
    CODE_RATIO,
    CODE_SUPERVISION_PLAN,
    DEFAULT_LOGICAL_CLOCK,
    admin_headers,
    assert_capacity_slots,
    assert_capacity_total_preserved,
    assert_cents,
    assert_compliance_score_read,
    assert_instant,
    assert_point_conservation,
    assert_point_ledger,
    assert_points,
    assert_risk,
    assert_score,
    fixtures as fx,
    make_inspector_headers,
    supervisor_headers,
    validate_success,
)

PRESCHOOL = ["PRESCHOOL"]


def _marlowe_with_one_critical_and_one_serious(api, catalog):
    """Marlowe Center's COMPLAINT visit cites SU-102 (15 points) and RA-201
    (8 points) and is left IN_PROGRESS, before any of them has landed."""
    fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
    ada = fx.register_inspector(
        api,
        full_name="Ada Inspector",
        certified_age_groups=PRESCHOOL,
        max_daily_visits=3,
    )
    provider = fx.create_provider(
        api,
        legal_name="Marlowe Center",
        site_address="31 Marlowe St",
        program_type="CENTER",
        requested_capacity=20,
    )
    complaint = fx.intake_complaint(
        api,
        provider["id"],
        intake_channel="WEB",
        allegation_category="RATIO",
        affected_age_group="PRESCHOOL",
        narrative="Web report of thin staffing in the preschool room.",
        anonymous=True,
    )
    fx.screen_complaint(api, complaint["id"], "SCREEN_IN")
    inspection = fx.schedule_visit(
        api,
        provider["id"],
        ada["id"],
        "2026-08-05T09:00:00Z",
        inspection_type="COMPLAINT",
        target_age_groups=PRESCHOOL,
        duration_minutes=120,
        complaint_id=complaint["id"],
    )
    fx.start_visit(api, inspection["id"], ada["id"])
    critical, serious = fx.cite_all(
        api,
        inspection["id"],
        ada["id"],
        catalog,
        [
            {
                "code": CODE_SUPERVISION_PLAN,
                "primary_age_group": "PRESCHOOL",
                "narrative": "No written supervision plan on file.",
            },
            {
                "code": CODE_RATIO,
                "primary_age_group": "PRESCHOOL",
                "narrative": "Preschool room over ratio at mid-morning.",
            },
        ],
    )
    return {
        "provider_id": provider["id"],
        "inspection_id": inspection["id"],
        "critical": critical,
        "serious": serious,
        "ada": ada,
    }


def _finalized(api, catalog):
    ctx = _marlowe_with_one_critical_and_one_serious(api, catalog)
    fx.submit_findings(api, ctx["inspection_id"], ctx["ada"]["id"], "FAIL", PRESCHOOL)
    ctx["inspection"] = fx.finalize_visit(api, ctx["inspection_id"])
    return ctx


def _provider(api, provider_id):
    return validate_success(api.get_provider(provider_id, headers=supervisor_headers()))


class TestViolationPointsLifetimeEqualsOpenPlusResolved:
    """§3.5: "The lifetime balance must always equal the open balance plus the
    resolved balance"."""

    def test_the_points_land_only_at_finalization(self, api, catalog):
        """Both citations sit on an unfinalized visit, so all three counters are still
        zero, and the finalize moves the ledger to 23 open in one step.

        PRD §3.5: "Because all four counters read only finalized inspections, a
        citation recorded during a visit that has not yet been finalized contributes
        nothing to the provider's totals; finalization is the moment the points land."

        Design: Difficulty/compensating_invariant/invariant_violation_points_lifetime_equals_open_plus_resolved
        """
        ctx = _marlowe_with_one_critical_and_one_serious(api, catalog)
        assert_points(ctx["critical"]["assessed_points"], 15, "assessed_points")
        assert_points(ctx["serious"]["assessed_points"], 8, "assessed_points")

        before = _provider(api, ctx["provider_id"])
        assert_point_ledger(before, 0, 0, 0)
        assert_point_conservation(before)

        fx.submit_findings(
            api, ctx["inspection_id"], ctx["ada"]["id"], "FAIL", PRESCHOOL
        )
        finalized = fx.finalize_visit(api, ctx["inspection_id"])

        after = _provider(api, ctx["provider_id"])
        assert_point_ledger(after, 23, 0, 23)
        assert_point_conservation(after)
        assert after["critical_open_count"] == 1
        assert after["critical_violation_count_24mo"] == 1
        assert_risk(after, 33.00, "MODERATE")
        assert_score(
            finalized["preliminary_compliance_score"],
            77.00,
            "preliminary_compliance_score",
        )
        assert_score(
            finalized["final_compliance_score"], 77.00, "final_compliance_score"
        )

    def test_a_correction_moves_points_and_conserves_the_total(self, api, catalog):
        """Verifying the critical finding shifts its 15 points from open to resolved
        and leaves the lifetime balance at 23.

        PRD §3.5: "verifying a correction subtracts those points from the open balance
        and adds them to the resolved balance, leaving the lifetime balance untouched"

        Design: Difficulty/compensating_invariant/invariant_violation_points_lifetime_equals_open_plus_resolved
        """
        ctx = _finalized(api, catalog)

        corrected = validate_success(
            api.disposition_violation(
                ctx["critical"]["id"],
                "VERIFIED_CORRECTED",
                headers=make_inspector_headers(ctx["ada"]["id"]),
            )
        )
        assert corrected["status"] == "VERIFIED_CORRECTED"
        assert corrected["corrected_at"] is not None

        provider = _provider(api, ctx["provider_id"])
        assert_point_ledger(provider, 8, 15, 23)
        assert_point_conservation(provider)
        assert provider["critical_open_count"] == 0
        assert provider["critical_violation_count_24mo"] == 1, (
            "the 24-month critical counter counts citations, and this one was "
            "corrected rather than vacated"
        )

        live = validate_success(
            api.get_compliance_score(
                ctx["inspection_id"], variant="FINAL", headers=supervisor_headers()
            )
        )
        assert_compliance_score_read(live, "FINAL", 86.00, raw_deduction=14.00)

    def test_a_vacatur_removes_points_from_both_sides(self, api, catalog):
        """Vacating the serious finding shrinks the lifetime balance by exactly 8 and
        empties the open balance, and the invariant still holds.

        PRD §3.5: "vacating a violation — from `CITED`, from `CORRECTION_PENDING` or
        from `UNCORRECTED` — subtracts its points from both the open and the lifetime
        balance while leaving the resolved balance alone."

        Design: Difficulty/compensating_invariant/invariant_violation_points_lifetime_equals_open_plus_resolved
        """
        ctx = _finalized(api, catalog)
        validate_success(
            api.disposition_violation(
                ctx["critical"]["id"],
                "VERIFIED_CORRECTED",
                headers=make_inspector_headers(ctx["ada"]["id"]),
            )
        )
        before = _provider(api, ctx["provider_id"])

        vacated = validate_success(
            api.disposition_violation(
                ctx["serious"]["id"],
                "VACATED",
                vacated_reason="The ratio finding was recorded against the wrong classroom.",
                headers=supervisor_headers(),
            )
        )
        assert vacated["status"] == "VACATED"

        after = _provider(api, ctx["provider_id"])
        assert_point_ledger(after, 0, 15, 15)
        assert_point_conservation(after)
        assert (
            before["lifetime_violation_points"] - after["lifetime_violation_points"]
            == 8
        )
        assert after["resolved_violation_points"] == before["resolved_violation_points"]

        inspection = validate_success(
            api.get_inspection(ctx["inspection_id"], headers=supervisor_headers())
        )
        assert inspection["violation_count"] == 1, (
            "a vacation decrements the inspection's violation_count by one"
        )
        assert_score(
            inspection["final_compliance_score"], 94.00, "final_compliance_score"
        )
        assert_score(
            inspection["preliminary_compliance_score"],
            77.00,
            "stored preliminary_compliance_score",
        )

    def test_the_live_preliminary_view_disagrees_with_the_frozen_field(
        self, api, catalog
    ):
        """After both dispositions the live preliminary read drops the vacated row and
        forces factor 1.000 on the survivor for 85.00, while the stored field stays
        at 77.00 and the risk score falls to its critical-history floor.

        PRD §3.5: "Its input set **excludes** violations whose status is `VACATED`,
        and every included violation's status factor is forced to 1.000 regardless of
        its real status."

        Design: Difficulty/compensating_invariant/invariant_violation_points_lifetime_equals_open_plus_resolved
        """
        ctx = _finalized(api, catalog)
        validate_success(
            api.disposition_violation(
                ctx["critical"]["id"],
                "VERIFIED_CORRECTED",
                headers=make_inspector_headers(ctx["ada"]["id"]),
            )
        )
        validate_success(
            api.disposition_violation(
                ctx["serious"]["id"],
                "VACATED",
                vacated_reason="The ratio finding was recorded against the wrong classroom.",
                headers=supervisor_headers(),
            )
        )

        live_preliminary = validate_success(
            api.get_compliance_score(
                ctx["inspection_id"],
                variant="PRELIMINARY",
                headers=supervisor_headers(),
            )
        )
        assert_compliance_score_read(
            live_preliminary, "PRELIMINARY", 85.00, raw_deduction=15.00
        )
        stored = validate_success(
            api.get_inspection(ctx["inspection_id"], headers=supervisor_headers())
        )
        assert_score(
            stored["preliminary_compliance_score"],
            77.00,
            "stored preliminary_compliance_score",
        )

        risk = validate_success(
            api.get_risk_assessment(
                ctx["provider_id"],
                variant="ENFORCEMENT_REVIEW",
                headers=admin_headers(),
            )
        )
        assert_score(risk["risk_score"], 10.00, "risk_score")
        assert risk["risk_tier"] == "LOW"
        assert_risk(_provider(api, ctx["provider_id"]), 10.00, "LOW")


ROOMS_SIXTY = [
    {"age_group": "TODDLER", "requested_group_size": 10},
    {"age_group": "PRESCHOOL", "requested_group_size": 20},
    {"age_group": "SCHOOL_AGE", "requested_group_size": 30},
]
THREE_GROUPS = ["TODDLER", "PRESCHOOL", "SCHOOL_AGE"]


def _northgate_licensed_with_forty_eight_open_points(api, catalog):
    """Northgate holds a provisional licence over 60 slots and a finalized ANNUAL
    visit carrying six SERIOUS ratio findings worth 48 points."""
    fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
    base = fx.setup_licensed_provider(
        api,
        requested_capacity=60,
        rooms=ROOMS_SIXTY,
        legal_name="Northgate Center",
        inspector_certified_age_groups=THREE_GROUPS,
        initial_scheduled_for="2026-08-05T09:00:00Z",
        catalog=catalog,
    )
    ctx = base["ctx"]
    inspector_id = base["inspector"]["id"]

    fx.set_clock(api, "2026-08-11T00:00:00Z")
    annual = fx.schedule_visit(
        api,
        ctx.id,
        inspector_id,
        "2026-08-12T09:00:00Z",
        inspection_type="ANNUAL",
        target_age_groups=PRESCHOOL,
        duration_minutes=120,
    )
    fx.set_clock(api, "2026-08-12T09:00:00Z")
    fx.start_visit(api, annual["id"], inspector_id)
    fx.cite_all(
        api,
        annual["id"],
        inspector_id,
        catalog,
        [
            {
                "code": CODE_RATIO,
                "primary_age_group": "PRESCHOOL",
                "narrative": f"Ratio breach observed in room {n}.",
            }
            for n in range(1, 7)
        ],
    )
    fx.submit_findings(api, annual["id"], inspector_id, "CONDITIONAL_PASS", PRESCHOOL)
    annual = fx.finalize_visit(api, annual["id"])

    fx.set_clock(api, "2026-08-20T00:00:00Z")
    return {"ctx": ctx, "inspector": base["inspector"], "annual": annual}


def _probation_effective(api, bundle):
    action = fx.propose_action(
        api,
        bundle["ctx"].id,
        "PROBATION",
        source_inspection_id=bundle["annual"]["id"],
        rationale="Forty-eight open points across six ratio findings.",
    )
    fx.issue_action(api, action["id"])
    return action, fx.effectuate_action(api, action["id"])


def _suspension_effective(api, bundle):
    action = fx.propose_action(
        api,
        bundle["ctx"].id,
        "SUSPENSION",
        source_inspection_id=bundle["annual"]["id"],
        rationale="No corrections filed; suspension proposed.",
    )
    fx.issue_action(api, action["id"])
    return action, fx.effectuate_action(api, action["id"])


class TestCapacitySlotsConservedAcrossSuspensionAndAppeal:
    """§3.8: "The sum of licensed and suspended capacity is unchanged by the move —
    the slots are frozen, not destroyed"."""

    def test_the_probation_rung_moves_no_slots_at_all(self, api, catalog):
        """Forty-eight open points price the probation at 177650 and its effectuation
        changes the licence without touching either capacity field.

        PRD §3.8: "**Probation** sets `license_status` to `PROBATION`, raises
        `current_ladder_step` to the greater of its current value and 2, and
        increments `probation_cycle_count`."

        Design: Difficulty/compensating_invariant/invariant_capacity_slots_conserved_across_suspension_and_appeal
        """
        bundle = _northgate_licensed_with_forty_eight_open_points(api, catalog)
        licensed = bundle["ctx"].reload()
        assert licensed["license_status"] == "PROVISIONAL"
        assert_capacity_slots(licensed, 60, 0)
        assert_point_ledger(licensed, 48, 0, 48)
        assert licensed["critical_open_count"] == 0
        assert_score(
            bundle["annual"]["final_compliance_score"], 52.00, "final_compliance_score"
        )

        proposed, effective = _probation_effective(api, bundle)
        assert_points(proposed["basis_points"], 48, "basis_points")
        assert proposed["ladder_step"] == 2
        assert_cents(proposed["fine_amount_cents"], 177650)
        assert effective["status"] == "EFFECTIVE"

        provider = bundle["ctx"].reload()
        assert provider["license_status"] == "PROBATION"
        assert provider["current_ladder_step"] == 2
        assert provider["probation_cycle_count"] == 1
        assert_capacity_slots(provider, 60, 0)
        assert_capacity_total_preserved(licensed, provider)

    def test_the_suspension_freezes_every_slot_without_destroying_one(
        self, api, catalog
    ):
        """The suspension holds all 60 slots, moves them out of licensed capacity into
        suspended capacity, and leaves the sum untouched.

        PRD §3.8: "**Suspension** sets `license_status` to `SUSPENDED`, raises
        `current_ladder_step` to the greater of its current value and 3, records
        `capacity_held_slots` as the provider's `licensed_capacity`, adds those slots
        to `suspended_capacity`, and sets `licensed_capacity` to 0."

        Design: Difficulty/compensating_invariant/invariant_capacity_slots_conserved_across_suspension_and_appeal
        """
        bundle = _northgate_licensed_with_forty_eight_open_points(api, catalog)
        _probation_effective(api, bundle)
        before = bundle["ctx"].reload()

        proposed, effective = _suspension_effective(api, bundle)
        assert proposed["ladder_step"] == 3
        assert_cents(proposed["fine_amount_cents"], 282150)
        assert effective["capacity_held_slots"] == 60

        provider = bundle["ctx"].reload()
        assert provider["license_status"] == "SUSPENDED"
        assert provider["current_ladder_step"] == 3
        assert_capacity_slots(provider, 0, 60)
        assert_capacity_total_preserved(before, provider)
        assert_risk(provider, 63.00, "HIGH")

    def test_filing_the_appeal_stays_nothing(self, api, catalog):
        """The appeal is filed inside a window that opened 15 days after issuance and
        leaves every licence and capacity field exactly as the effectuation left them.

        PRD §3.8: "**Filing an appeal does not stay the action**: the provider's
        `license_status`, `licensed_capacity` and `suspended_capacity` are all left
        exactly as the effectuation left them."

        Design: Difficulty/compensating_invariant/invariant_capacity_slots_conserved_across_suspension_and_appeal
        """
        bundle = _northgate_licensed_with_forty_eight_open_points(api, catalog)
        _probation_effective(api, bundle)
        action, _effective = _suspension_effective(api, bundle)
        suspended = bundle["ctx"].reload()

        appealed = validate_success(
            api.appeal_action(
                action["id"],
                "The six findings describe one staffing event and are duplicative.",
                headers=bundle["ctx"].headers,
            )
        )
        assert appealed["status"] == "APPEALED"
        assert_instant(
            appealed["appeal_deadline_at"], "2026-09-04T00:00:00Z", "appeal_deadline_at"
        )
        assert_instant(appealed["appealed_at"], "2026-08-20T00:00:00Z", "appealed_at")

        during = bundle["ctx"].reload()
        assert during["license_status"] == "SUSPENDED"
        assert_capacity_slots(during, 0, 60)
        assert_capacity_total_preserved(suspended, during)

    def test_vacating_returns_the_slots_but_not_the_fine_or_the_history(
        self, api, catalog
    ):
        """The vacated suspension hands all 60 slots back and drops the licence to
        probation, while the fine, the points and the probation tally stand.

        PRD §3.8: "Vacating a **suspension** adds `capacity_held_slots` back to
        `licensed_capacity`, subtracts the same number from `suspended_capacity`,
        resets `capacity_held_slots` to 0, sets `license_status` to `PROBATION` —
        never directly back to `FULL` — and sets `current_ladder_step` to 2."

        Design: Difficulty/compensating_invariant/invariant_capacity_slots_conserved_across_suspension_and_appeal
        """
        bundle = _northgate_licensed_with_forty_eight_open_points(api, catalog)
        probation, _probation_effect = _probation_effective(api, bundle)
        action, _effective = _suspension_effective(api, bundle)
        issued = validate_success(
            api.get_enforcement_action(action["id"], headers=supervisor_headers())
        )
        validate_success(
            api.appeal_action(
                action["id"],
                "The six findings describe one staffing event and are duplicative.",
                headers=bundle["ctx"].headers,
            )
        )
        before = bundle["ctx"].reload()

        vacated = validate_success(
            api.decide_appeal(
                action["id"], "VACATED", headers=admin_headers(ADMIN_2)
            )
        )
        assert vacated["status"] == "VACATED"
        assert vacated["capacity_held_slots"] == 0
        assert vacated["resolved_at"] is not None
        assert issued["issued_by_user_id"] != ADMIN_2, (
            "the deciding operator must not be the action's issued_by_user_id"
        )

        after = bundle["ctx"].reload()
        assert_capacity_slots(after, 60, 0)
        assert_capacity_total_preserved(before, after)
        assert after["license_status"] == "PROBATION"
        assert after["current_ladder_step"] == 2
        assert after["probation_cycle_count"] == 1
        assert_point_ledger(after, 48, 0, 48)
        assert_cents(vacated["fine_amount_cents"], 282150)
        assert (
            validate_success(
                api.get_enforcement_action(
                    probation["id"], headers=supervisor_headers()
                )
            )["status"]
            == "EFFECTIVE"
        ), "vacating the suspension does not disturb the earlier rung"
