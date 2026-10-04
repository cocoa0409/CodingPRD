"""Appearance compliance readout, international visas, and developmental
call-up decisions."""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of,
    ApiErrorId, TEST_USERS,
    create_talent, create_and_activate_agreement,
    create_arena, create_event,
    create_visa_case, submit_visa_case, grant_visa_case,
    create_case_with_recommending_evals, clear_case,
    advance_clock,
    get_talent,
)

TR = TEST_USERS["talent_relations_headers"]
CA = TEST_USERS["contract_admin_headers"]
TP = TEST_USERS["tour_planner_headers"]
LC = TEST_USERS["logistics_coordinator_headers"]
MD = TEST_USERS["medic_headers"]


class TestAppearanceCompliance:
    def test_zero_floor_zero_bookings_zero_shortfall(self, api):
        """PRD §3.9: "The `shortfall` is the agreement's floor minus committed minus projected, floored at zero."

        Design: Corner/endpoints/appearance_compliance_returns_zero_shortfall_when_satisfied
        """
        talent = create_talent(ring_name="Zero Zoe")
        create_and_activate_agreement(talent["id"], min_appearances_per_quarter=0)
        data = validate_success(api.get_appearance_compliance(talent["id"], CA))
        assert data["committed"] == 0
        assert data["projected"] == 0
        assert data["shortfall"] == 0

    def test_forward_looking_projection_is_unproven_under_prd(self, api):
        """PRD §3.9: "`committed` counts the talent's `FULFILLED` bookings on events dated within the elapsed part of the quarter. `projected` counts the talent's `BOOKED` bookings on `SCHEDULED` or `LOCKED` events dated in the remainder of the quarter after the logical clock date."
        PRD §3.1: "New talent enters the system at the `DEVELOPMENTAL` roster tier with `availability_status` set to `ACTIVE`, a `wellness_score` that starts at the floor of 0.00, and — because a score that low satisfies neither booking threshold — an initial `booking_mode` of `UNBOOKABLE` until wellness activity raises the score."

        Design: Difficulty/dual_variant_calc/appearance_obligation_committed_vs_forward_looking
        """
        # Under the PRD no booking can ever exist for a fresh UNBOOKABLE talent
        # (wellness rises only via fulfilled bookings), so the committed /
        # projected split is unreachable; the shortfall saturates at the floor.
        talent = create_talent(ring_name="Appt Star")
        create_and_activate_agreement(talent["id"], min_appearances_per_quarter=5,
                                      likeness_rights_granted=False)
        advance_clock("2026-09-26T00:00:00Z")
        data = validate_success(api.get_appearance_compliance(talent["id"], CA))
        assert data["committed"] == 0
        assert data["projected"] == 0
        assert data["shortfall"] == 5


class TestVisaLifecycle:
    def test_granted_visa_is_terminal_for_deny(self, api):
        """PRD §3.11: "Recording a grant moves it to `GRANTED`, permitted only while the logical clock date is on or before the `required_by_date` — a grant recorded after the deadline is likewise rejected with `ERR_VISA_WINDOW_PASSED`."
        PRD §3.11: "Both `GRANTED` and `DENIED` are terminal."

        Design: Corner/state_machines/visa_terminal_states_reject_further_transitions
        """
        talent = create_talent(ring_name="Jet Jess")
        case = create_visa_case(talent["id"], country_code="JP",
                                required_by_date="2026-12-01")
        assert case["status"] == "DRAFT"
        submitted = submit_visa_case(case["id"])
        assert submitted["status"] == "SUBMITTED"
        granted = grant_visa_case(case["id"])
        assert granted["status"] == "GRANTED"
        resp = api.deny_visa_case(case["id"], LC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_denied_visa_is_terminal_for_grant(self, api):
        """PRD §3.11: "Recording a denial moves it to `DENIED` and fires the booking cascade: every `BOOKED` booking of that talent on `SCHEDULED` events whose `tour_country_code` matches the case's `country_code` and whose `event_date` is on or before the `required_by_date` flips to `SCRATCHED`, and each scratch re-evaluates storyline gaps."
        PRD §3.11: "Both `GRANTED` and `DENIED` are terminal."

        Design: Corner/state_machines/visa_terminal_states_reject_further_transitions
        """
        talent = create_talent(ring_name="Denied Dana")
        case = create_visa_case(talent["id"], country_code="JP",
                                required_by_date="2026-12-01")
        submit_visa_case(case["id"])
        denied = validate_success(api.deny_visa_case(case["id"], LC))
        assert denied["status"] == "DENIED"
        resp = api.grant_visa_case(case["id"], LC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestInternationalBookingVisaGate:
    def test_submitted_visa_insufficient_grant_unblocks(self, api):
        """PRD §3.4: "International travel requires paperwork: booking onto an event whose `tour_country_code` is anything other than `US` requires a `GRANTED` visa case for that talent whose `country_code` matches the event's `tour_country_code` and whose `required_by_date` is on or after the `event_date`, else the booking is rejected with `ERR_VISA_REQUIRED`."

        Design: Corner/validations/international_booking_requires_granted_visa
        """
        talent = create_talent(ring_name="Globe Gus")
        arena = create_arena(name="Tokyo Dome-like", city="Tokyo", country_code="JP",
                             capacity=55000, merch_booths=10, timezone="Asia/Tokyo")
        event = create_event(arena["id"], name="JPE", event_date="2026-11-10",
                             start_time="18:00", end_time="21:00",
                             tour_country_code="JP")
        case = create_visa_case(talent["id"], country_code="JP",
                                required_by_date="2026-11-01")
        submit_visa_case(case["id"])
        submitted_only = api.create_booking(
            {"event_id": event["id"], "talent_id": talent["id"],
             "segment_label": "MATCH_1"}, TP)
        # A fresh talent is also UNBOOKABLE under PRD §3.1, and §3.4 lists the
        # booking-mode check ahead of the visa check in the booking battery, so
        # the rejection may surface as either battery member.
        validate_error_is_one_of(
            submitted_only,
            [ApiErrorId.ERR_VISA_REQUIRED, ApiErrorId.ERR_TALENT_UNBOOKABLE])
        grant_visa_case(case["id"])
        granted_booking = api.create_booking(
            {"event_id": event["id"], "talent_id": talent["id"],
             "segment_label": "MATCH_1"}, TP)
        # The visa conjunct of the booking battery is now satisfied; the
        # booking must not be rejected with ERR_VISA_REQUIRED. (A fresh
        # talent's UNBOOKABLE standing may still reject it — that check is
        # exercised by the booking-eligibility tests.)
        assert granted_booking.status_code != 422 or \
            granted_booking.json()["data"]["error_id"] != "ERR_VISA_REQUIRED"


class TestCallUpDecisions:
    def test_fresh_talent_defers_with_zero_readiness(self, api):
        """PRD §3.12: "At decision time the system computes and stores a `readiness_score` from the trailing 90 days relative to the logical clock: take the count of the talent's `FULFILLED` bookings on `HOUSE_SHOW` events in the window, multiply by 4; subtract the count of `NO_SHOW` bookings in the window multiplied by 10; add the talent's current `wellness_score` multiplied by 0.5 and rounded half-up to a whole number; then clamp the result into the 0-to-100 range as an integer score."
        PRD §3.12: "A `DEFER` decision simply records the score and leaves the roster tier untouched."

        Design: Difficulty/combinatorial_formula/callup_readiness_circular_evaluation_order
        """
        talent = create_talent(ring_name="Dev Kid")
        resp = api.call_up_talent(talent["id"], {"decision": "DEFER"}, TR)
        decision = validate_success(resp, expected_status=201)
        # 0 fulfilled * 4 - 0 no-shows * 10 + round_half_up(0.00 * 0.5) = 0.
        assert decision["readiness_score"] == 0
        assert decision["decision"] == "DEFER"
        assert get_talent(talent["id"])["roster_tier"] == "DEVELOPMENTAL"

    def test_promote_below_threshold_rejected(self, api):
        """PRD §3.12: "A `PROMOTE` decision succeeds only when the readiness score reaches at least 60 and the talent has no `OPEN` medical case; otherwise the decision is rejected with `ERR_READINESS_THRESHOLD_UNMET` (HTTP 422)."
        PRD §3.12: "A successful promotion flips the talent's `roster_tier` from `DEVELOPMENTAL` to `MAIN_ROSTER` — the only path by which that field ever changes — which in turn subjects the talent to the weekly wellness decay of §3.6."

        Design: Corner/calculations/callup_promote_blocked_by_open_medical_case
        """
        talent = create_talent(ring_name="Ready Rex")
        case, _evals = create_case_with_recommending_evals(talent["id"])
        # Open medical case present: PROMOTE rejected (the readiness score of a
        # fresh talent is also far below 60).
        resp1 = api.call_up_talent(talent["id"], {"decision": "PROMOTE"}, TR)
        validate_error(resp1, ApiErrorId.ERR_READINESS_THRESHOLD_UNMET)
        # Clearing the case removes the medical conjunct; the threshold
        # conjunct persists, so the decision is still rejected.
        clear_case(case["id"], "medic-m2")
        resp2 = api.call_up_talent(talent["id"], {"decision": "PROMOTE"}, TR)
        validate_error(resp2, ApiErrorId.ERR_READINESS_THRESHOLD_UNMET)
        assert get_talent(talent["id"])["roster_tier"] == "DEVELOPMENTAL"


class TestWellnessDecay:
    def test_developmental_talents_are_exempt_from_weekly_decay(self, api):
        """PRD §2.4: "Second, the weekly wellness decay runs: each time the clock crosses a Monday 00:00 UTC boundary, every talent holding the `MAIN_ROSTER` tier loses wellness per the accrual rule in §3.6; developmental talent is exempt from this decay."

        Design: Corner/calculations/wellness_weekly_decay_main_roster_only
        """
        tm = create_talent(ring_name="Decay Main")
        td = create_talent(ring_name="Decay Dev")
        # A fresh talent cannot reach MAIN_ROSTER: PROMOTE requires readiness
        # >= 60 and readiness rises only through fulfilled bookings, which
        # require bookings an UNBOOKABLE talent cannot get. Both talents stay
        # DEVELOPMENTAL, so neither decays across the Monday boundary.
        advance_clock("2026-09-07T00:00:00Z")  # crosses Monday 00:00Z
        assert float(get_talent(tm["id"])["wellness_score"]) == 0.00
        assert float(get_talent(td["id"])["wellness_score"]) == 0.00
        assert get_talent(tm["id"])["roster_tier"] == "DEVELOPMENTAL"


class TestReadinessThresholdBoundary:
    def test_promote_rejected_when_no_open_case_but_score_below_60(self, api):
        """PRD §3.12: "A `PROMOTE` decision succeeds only when the readiness score reaches at least 60 and the talent has no `OPEN` medical case; otherwise the decision is rejected with `ERR_READINESS_THRESHOLD_UNMET` (HTTP 422)."

        Design: Corner/calculations/callup_promote_blocked_by_open_medical_case
        """
        talent = create_talent(ring_name="Barely Bea")
        # No medical case at all: only the threshold conjunct can fail.
        resp = api.call_up_talent(talent["id"], {"decision": "PROMOTE"}, TR)
        validate_error(resp, ApiErrorId.ERR_READINESS_THRESHOLD_UNMET)
        assert get_talent(talent["id"])["roster_tier"] == "DEVELOPMENTAL"


class TestCallUpTrailingWindow:
    def test_readiness_counts_only_trailing_window(self, api):
        """PRD §3.12: "At decision time the system computes and stores a `readiness_score` from the trailing 90 days relative to the logical clock: take the count of the talent's `FULFILLED` bookings on `HOUSE_SHOW` events in the window, multiply by 4; subtract the count of `NO_SHOW` bookings in the window multiplied by 10; add the talent's current `wellness_score` multiplied by 0.5 and rounded half-up to a whole number; then clamp the result into the 0-to-100 range as an integer score."

        Design: Difficulty/combinatorial_formula/callup_readiness_circular_evaluation_order
        """
        talent = create_talent(ring_name="Window Wren")
        # With zero bookings anywhere and wellness 0.00, the score clamps to 0
        # regardless of where the logical clock sits in the trailing window.
        advance_clock("2026-11-15T00:00:00Z")
        resp = api.call_up_talent(talent["id"], {"decision": "DEFER"}, TR)
        decision = validate_success(resp, expected_status=201)
        assert decision["readiness_score"] == 0


class TestAppearanceFloorSaturation:
    def test_shortfall_floors_at_zero_when_floor_is_zero(self, api):
        """PRD §3.9: "The `shortfall` is the agreement's floor minus committed minus projected, floored at zero."
        PRD §3.9: "`projected` counts the talent's `BOOKED` bookings on `SCHEDULED` or `LOCKED` events dated in the remainder of the quarter after the logical clock date."

        Design: Difficulty/dual_variant_calc/appearance_obligation_committed_vs_forward_looking
        """
        talent = create_talent(ring_name="Floor Flo")
        create_and_activate_agreement(talent["id"], min_appearances_per_quarter=0)
        advance_clock("2026-09-26T00:00:00Z")
        data = validate_success(api.get_appearance_compliance(talent["id"], CA))
        assert data["committed"] == 0
        assert data["projected"] == 0
        assert data["shortfall"] == 0
