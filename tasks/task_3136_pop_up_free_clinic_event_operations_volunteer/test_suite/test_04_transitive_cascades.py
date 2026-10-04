"""Transitive cascades: suspend -> assignment release -> coverage recompute ->
posture boundary, and agreement confirm -> supersede -> event reassignment."""

from test_helpers import (
    TEST_USERS,
    confirm_agreement,
    create_agreement,
    create_event,
    create_vetted_site,
    get_success_data,
    setup_event_ready_at_coverage_boundary,
    submit_agreement,
    suspend_payload,
    validate_paginated,
    validate_success,
)

ED = TEST_USERS["event_director_headers"]
LC = TEST_USERS["logistics_coordinator_headers"]
VC = TEST_USERS["volunteer_coordinator_headers"]


class TestSuspendCascadeCoveragePostureBoundary:
    def test_suspend_releases_assignment_and_recomputes_coverage(self, api):
        """PRD §3.3: "Suspension cascades: every `ROSTERED` or `CONFIRMED`
        `DisciplineAssignment` for that volunteer transitions to `RELEASED`,
        coverage is recomputed, and if the loss of coverage drops the event
        below its coverage floor the posture regresses from `READY` back to
        `STAFFING`."

        Design: Difficulty/transitive_cascade/volunteer_suspend_releases_assignments_regresses_posture
        """
        ctx = setup_event_ready_at_coverage_boundary()
        assert ctx["posture"] == "READY"
        first_dental = ctx["dental_volunteer_ids"][0]

        get_success_data(
            api.suspend_volunteer(
                first_dental, suspend_payload(ctx["id"], "audit"), VC
            )
        )

        assignments, _ = validate_paginated(
            api.list_event_assignments(ctx["id"], VC)
        )
        suspended_assignment = [
            a for a in assignments if a["volunteer_id"] == first_dental
        ]
        assert len(suspended_assignment) == 1
        assert suspended_assignment[0]["status"] == "RELEASED"

    def test_score_at_exact_floor_holds_ready(self, api):
        """PRD §3.4: "An event's coverage floor is 60: the recompute that moves
        `STAFFING → READY` requires a score of at least 60, and a suspension
        that drags the score below 60 while the event is `READY` regresses it
        to `STAFFING`." Suspending one of two DENTAL volunteers drops DENTAL
        coverage from 1.0 to 0.5 and the score from 85.0 to exactly 60.0,
        which still meets the floor, so the posture holds at READY.

        Design: Difficulty/transitive_cascade/volunteer_suspend_releases_assignments_regresses_posture
        """
        ctx = setup_event_ready_at_coverage_boundary()
        assert ctx["posture"] == "READY"

        get_success_data(
            api.suspend_volunteer(
                ctx["dental_volunteer_ids"][0], suspend_payload(ctx["id"]), VC
            )
        )

        event_now = validate_success(api.get_event(ctx["id"], ED))
        assert event_now["posture"] == "READY"


class TestAgreementConfirmSupersedeCascade:
    def _event_with_confirmed_agreement(self, api):
        site_a = create_vetted_site(
            site_type="ARENA",
            state_code="TN",
            square_footage=30000,
            has_loading_dock=True,
            sterilization_capable=True,
        )
        event = create_event(
            host_state_code="TN",
            service_date="2026-12-05",
            doors_open_utc="2026-12-05T10:00:00Z",
            total_patient_capacity=200,
        )
        agreement_a = create_agreement(
            {"id": event["id"], "version": event["version"]},
            site_a["id"],
            host_org_name="Arena",
            liability_cap_cents=9_000_000,
            insurance_certificate_ref="C8A",
        )
        submit_agreement(event["id"], agreement_a["id"])
        confirm_agreement(event["id"], agreement_a["id"])
        return event, agreement_a

    def test_confirm_successor_supersedes_prior_and_reassigns_event(self, api):
        """PRD §3.2: "If the confirmed agreement named a
        `supersedes_agreement_id` pointing at a prior `CONFIRMED` agreement,
        that prior agreement is transitioned `CONFIRMED → SUPERSEDED` as part
        of the same operation and `confirmed_site_agreement_id` is reassigned
        to the successor."

        Design: Difficulty/transitive_cascade/agreement_confirm_supersedes_prior_reassigns_event
        """
        event, agreement_a = self._event_with_confirmed_agreement(api)
        site_b = create_vetted_site(
            site_type="SCHOOL", state_code="TN", square_footage=9000
        )
        event_now = validate_success(api.get_event(event["id"], ED))
        agreement_b = create_agreement(
            {"id": event["id"], "version": event_now["version"]},
            site_b["id"],
            host_org_name="School Board",
            liability_cap_cents=3_000_000,
            insurance_certificate_ref="C8B",
            supersedes_agreement_id=agreement_a["id"],
        )
        submit_agreement(event["id"], agreement_b["id"])
        confirm_agreement(event["id"], agreement_b["id"])

        agreements, _ = validate_paginated(
            api.list_event_agreements(event["id"], LC)
        )
        by_id = {a["id"]: a for a in agreements}
        assert by_id[agreement_a["id"]]["status"] == "SUPERSEDED"
        assert by_id[agreement_b["id"]]["status"] == "CONFIRMED"

        event_after = validate_success(api.get_event(event["id"], ED))
        assert event_after["confirmed_site_agreement_id"] == agreement_b["id"]

    def test_successor_cost_share_computed_from_its_own_site(self, api):
        """PRD §3.2: "A confirmed agreement becomes the event's single
        confirmed site: `confirmed_site_agreement_id` is set to it, the final
        `cost_share_cents` is computed with the liability cap applied". A
        SCHOOL venue at 9000 square feet prices at the 300000 base with no
        surcharge tier filled.

        Design: Difficulty/transitive_cascade/agreement_confirm_supersedes_prior_reassigns_event
        """
        event, agreement_a = self._event_with_confirmed_agreement(api)
        site_b = create_vetted_site(
            site_type="SCHOOL", state_code="TN", square_footage=9000
        )
        event_now = validate_success(api.get_event(event["id"], ED))
        agreement_b = create_agreement(
            {"id": event["id"], "version": event_now["version"]},
            site_b["id"],
            host_org_name="School Board",
            liability_cap_cents=3_000_000,
            insurance_certificate_ref="C8B",
            supersedes_agreement_id=agreement_a["id"],
        )
        submit_agreement(event["id"], agreement_b["id"])
        confirmed = confirm_agreement(event["id"], agreement_b["id"])
        assert confirmed["cost_share_cents"] == 300_000
