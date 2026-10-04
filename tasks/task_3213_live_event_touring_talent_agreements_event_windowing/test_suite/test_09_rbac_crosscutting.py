"""Role-based access denial and cross-cutting observables (suspension cycle,
reverse FK lookups, immediate consistency, wellness band floor)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_talent, create_arena, create_event, create_event_payload,
    create_storyline, create_chapter, activate_storyline,
    create_agreement_payload, create_merch_sale_payload,
    create_medical_case, add_evaluation,
    get_storyline,
    setup_premium_event_with_spanning_right,
    create_distribution_window_payload,
)

CA = TEST_USERS["contract_admin_headers"]
TP = TEST_USERS["tour_planner_headers"]
TR = TEST_USERS["talent_relations_headers"]
SE = TEST_USERS["storyline_editor_headers"]
MO = TEST_USERS["merch_ops_headers"]
MD = TEST_USERS["medic_headers"]
DM = TEST_USERS["distribution_manager_headers"]


class TestCrossRoleDenial:
    def test_exclusive_operations_reject_foreign_roles(self, api):
        """PRD §2.1: "Once authenticated, the role is checked against the endpoint's authorization matrix (§4); an authenticated operator attempting an operation outside their role's remit is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/rbac_cross_role_denial_matrix
        """
        talent = create_talent(ring_name="Role Rob")
        arena = create_arena(name="RBAC Arena")
        event = create_event(arena["id"], name="RBE", event_date="2026-09-05")
        # MerchOps cannot draft agreements.
        r1 = api.create_agreement(
            create_agreement_payload(talent["id"]), MO)
        validate_error(r1, ApiErrorId.ERR_FORBIDDEN)
        # TourPlanner cannot record merch sales.
        r2 = api.create_merch_sale(
            create_merch_sale_payload(event["id"], talent["id"]), TP)
        validate_error(r2, ApiErrorId.ERR_FORBIDDEN)
        # ContractAdmin cannot schedule events.
        r3 = api.create_event(
            create_event_payload(arena["id"], name="RBE2", event_date="2026-09-06"), CA)
        validate_error(r3, ApiErrorId.ERR_FORBIDDEN)

    def test_talent_relations_cannot_create_storylines(self, api):
        """PRD §2.1: "Once authenticated, the role is checked against the endpoint's authorization matrix (§4); an authenticated operator attempting an operation outside their role's remit is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/rbac_cross_role_denial_matrix
        """
        resp = api.create_storyline({"title": "Forbidden Feud"}, TR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestSuspensionCycle:
    def test_suspend_then_reinstate_restores_active(self, api):
        """PRD §3.1: "Suspending a talent — the request carries a free-text `reason` — flips `availability_status` to `SUSPENDED` and re-derives `booking_mode`."
        PRD §3.1: "Reinstating flips `availability_status` back from `SUSPENDED` to `ACTIVE`, unless a medical case for the talent is still `OPEN`, in which case the talent comes back as `INJURED` instead; either way `booking_mode` is re-derived."
        PRD §3.1: "The derivation is strictly ordered: a talent whose `availability_status` is `SUSPENDED` is `UNBOOKABLE`"

        Design: Corner/state_machines/talent_suspend_reinstate_cycle
        """
        talent = create_talent(ring_name="Susp Sid")
        suspended = validate_success(
            api.suspend_talent(talent["id"], {"reason": "wellness hold"}, TR))
        assert suspended["availability_status"] == "SUSPENDED"
        assert suspended["booking_mode"] == "UNBOOKABLE"
        reinstated = validate_success(api.reinstate_talent(talent["id"], TR))
        assert reinstated["availability_status"] == "ACTIVE"
        # wellness 0.00 < 40.00 -> UNBOOKABLE per the §3.1 derivation order.
        assert reinstated["booking_mode"] == "UNBOOKABLE"


class TestReverseLookups:
    def test_booking_chapter_evaluation_reverse_lists(self, api):
        """PRD §2.9: "Reverse-lookup listings (a talent's agreements, a storyline's chapters, an event's merch sales, and so on) follow the same rule for their single path identifier."

        Design: Corner/endpoints/fk_reverse_reachability_sweep
        """
        talent = create_talent(ring_name="Rev Rick")
        arena = create_arena(name="Rev Arena")
        event = create_event(arena["id"], name="REV", event_date="2026-09-05")
        # A fresh talent is UNBOOKABLE under the PRD, so no booking can be
        # created; assert the booking reverse list resolves and is empty.
        bookings, meta = validate_paginated(
            api.list_bookings(TP, params={"talent_id": talent["id"]}))
        assert meta["total_count"] == 0
        # Chapter reverse lookups by storyline and by event.
        storyline = create_storyline(title="Rev Feud")
        chapter = create_chapter(storyline["id"], event["id"])
        by_storyline, _ = validate_paginated(
            api.list_storyline_chapters(storyline["id"], SE))
        assert any(c["id"] == chapter["id"] for c in by_storyline)
        by_event, _ = validate_paginated(api.list_event_chapters(event["id"], TP))
        assert any(c["id"] == chapter["id"] for c in by_event)
        # Evaluation reverse lookup on the case.
        case = create_medical_case(talent["id"], severity="MINOR")
        evaluation = add_evaluation(case["id"], "medic-m1",
                                    recommends_clearance=False, findings="bruised")
        evals, _ = validate_paginated(api.list_medical_evaluations(case["id"], MD))
        assert any(e["id"] == evaluation["id"] for e in evals)


class TestImmediateConsistency:
    def test_cancel_effects_visible_in_immediate_reads(self, api):
        """PRD §3.5: "Cancelling a `SCHEDULED` event unwinds everything downstream. Every `BOOKED` booking flips to `SCRATCHED`; every `PLANNED` chapter flips to `MISSED` with the gap-count increments and shelving rule of §3.4; and every distribution window on the event still `PROVISIONAL` or `PUBLISHED` flips to `REVOKED`."

        Design: Corner/consistency_model/immediate_visibility_of_cascade_in_same_read
        """
        # A fresh talent is UNBOOKABLE under the PRD, so the BOOKED-booking leg
        # of this cascade is unreachable; the chapter and window legs are
        # asserted immediately after the cancel in the same test.
        event, partner, _right = setup_premium_event_with_spanning_right(
            partner_name="ICCo", partner_code="IC")
        storyline = create_storyline(title="IC Feud")
        chapter = create_chapter(storyline["id"], event["id"])
        activate_storyline(storyline["id"])
        window = validate_success(api.create_distribution_window(
            create_distribution_window_payload(event["id"], partner["id"]), DM),
            expected_status=201)
        validate_success(api.publish_distribution_window(window["id"], DM))
        validate_success(api.cancel_event(event["id"], TP))
        chapters, _ = validate_paginated(api.list_event_chapters(event["id"], SE))
        assert chapters[0]["id"] == chapter["id"]
        assert chapters[0]["status"] == "MISSED"
        assert get_storyline(storyline["id"])["gap_count"] == 1
        win = validate_success(api.get_distribution_window(window["id"], DM))
        assert win["status"] == "REVOKED"


class TestWellnessBandFloor:
    def test_fresh_talent_below_limited_floor_is_unbookable(self, api):
        """PRD §3.1: "otherwise a score of at least 40.00 makes them `LIMITED`; anything below 40.00 is `UNBOOKABLE`."

        Design: Corner/cross_cutting_layers/rate_threshold_booking_mode_band_boundaries
        """
        talent = create_talent(ring_name="Band Ben")
        assert float(talent["wellness_score"]) == 0.00
        assert talent["booking_mode"] == "UNBOOKABLE"
        arena = create_arena(name="Band Arena")
        event = create_event(arena["id"], name="BND1", event_date="2026-09-05")
        resp = api.create_booking(
            {"event_id": event["id"], "talent_id": talent["id"],
             "segment_label": "MATCH_1"}, TP)
        validate_error(resp, ApiErrorId.ERR_TALENT_UNBOOKABLE)
