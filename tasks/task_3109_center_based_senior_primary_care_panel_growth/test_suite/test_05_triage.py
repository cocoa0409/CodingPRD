"""Triage claims: severity safety gates, urgent-slot gating, ED-referral
counter, and self-care exclusion from the diversion rate."""
from test_helpers import (
    ApiErrorId,
    create_appointment,
    create_triage_case_payload,
    get_success_data,
    set_clock,
    setup_panel_with_active_patient,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

NET = TEST_USERS["network_operator_headers"]
NURSE = TEST_USERS["triage_nurse_headers"]


class TestSafetyGates:
    def test_high_severity_divert_rejected(self, api):
        """PRD §2.11: "A case with `severity` of `HIGH` must go to the emergency department:
        diverting a `HIGH` case to urgent care is rejected with
        `ERR_SEVERITY_REQUIRES_ED`."

        Design: Difficulty/cross_entity_state_dependency/triage_divert_gated_on_urgent_appointment_state
        """
        center, team, room, plan, patient, attr = setup_panel_with_active_patient()
        appt = create_appointment(
            team["id"], patient["id"], room["id"],
            start_utc="2026-09-05T14:00:00Z", duration_minutes=40, kind="PRIMARY",
        )
        case = get_success_data(
            api.create_triage_case(
                create_triage_case_payload(
                    patient["id"], channel="AFTER_HOURS_LINE", severity="HIGH"
                ),
                NURSE,
            )
        )
        resp = api.divert_triage_case(case["id"], {"urgent_appointment_id": appt["id"]}, NURSE)
        validate_error(resp, ApiErrorId.ERR_SEVERITY_REQUIRES_ED.value, expected_status=422)
        case_after = get_success_data(api.get_triage_case(case["id"], NURSE))
        assert case_after["status"] == "OPEN"

    def test_self_care_requires_low_severity(self, api):
        """PRD §2.11: "Self-care advice is permitted only for `LOW` severity; advising
        self-care on a `MODERATE` or `HIGH` case is rejected with
        `ERR_SEVERITY_TOO_HIGH_FOR_SELF_CARE`."

        Design: Difficulty/cross_entity_state_dependency/triage_divert_gated_on_urgent_appointment_state
        """
        center, team, room, plan, patient, attr = setup_panel_with_active_patient()
        case = get_success_data(
            api.create_triage_case(
                create_triage_case_payload(
                    patient["id"], channel="WALK_IN", severity="MODERATE"
                ),
                NURSE,
            )
        )
        resp = api.advise_self_care_triage_case(case["id"], NURSE)
        validate_error(
            resp, ApiErrorId.ERR_SEVERITY_TOO_HIGH_FOR_SELF_CARE.value, expected_status=422
        )
        case_after = get_success_data(api.get_triage_case(case["id"], NURSE))
        assert case_after["status"] == "OPEN"


class TestUrgentSlotGate:
    def test_triage_divert_gated_on_urgent_appointment_state(self, api):
        """PRD §3.7: "The payload's `urgent_appointment_id` must reference a `SCHEDULED`
        appointment of `kind` `PRIMARY`, at the same center, starting within the next
        twenty-four hours of the logical clock — a missing, non-scheduled, wrong-kind,
        cross-center, or too-distant slot is `ERR_URGENT_SLOT_INVALID`."

        Design: Difficulty/cross_entity_state_dependency/triage_divert_gated_on_urgent_appointment_state
        """
        center, team, room, plan, patient, attr = setup_panel_with_active_patient()
        case = get_success_data(
            api.create_triage_case(
                create_triage_case_payload(
                    patient["id"], channel="WALK_IN", severity="MODERATE"
                ),
                NURSE,
            )
        )
        appt = create_appointment(
            team["id"], patient["id"], room["id"],
            start_utc="2026-09-05T14:00:00Z", duration_minutes=40, kind="PRIMARY",
        )
        # Cancel the slot so it is no longer SCHEDULED.
        validate_success(api.cancel_appointment(appt["id"], TEST_USERS["front_desk_headers"]), 200)

        resp = api.divert_triage_case(case["id"], {"urgent_appointment_id": appt["id"]}, NURSE)
        validate_error(resp, ApiErrorId.ERR_URGENT_SLOT_INVALID.value, expected_status=422)
        case_after = get_success_data(api.get_triage_case(case["id"], NURSE))
        assert case_after["status"] == "OPEN"

    def test_triage_divert_to_scheduled_primary_slot_succeeds(self, api):
        """PRD §3.7: "The payload's `urgent_appointment_id` must reference a `SCHEDULED`
        appointment of `kind` `PRIMARY`, at the same center, starting within the next
        twenty-four hours of the logical clock — a missing, non-scheduled, wrong-kind,
        cross-center, or too-distant slot is `ERR_URGENT_SLOT_INVALID`."
        PRD §3.7: "Success moves the case to `RESOLVED_DIVERTED` with `disposition` set to
        `URGENT_CARE_BOOKED`, and the linked appointment is internally flagged as
        urgent-fill without any state change."

        Design: Difficulty/cross_entity_state_dependency/triage_divert_gated_on_urgent_appointment_state
        """
        center, team, room, plan, patient, attr = setup_panel_with_active_patient()
        appt = create_appointment(
            team["id"], patient["id"], room["id"],
            start_utc="2026-09-01T14:00:00Z", duration_minutes=40, kind="PRIMARY",
        )
        case = get_success_data(
            api.create_triage_case(
                create_triage_case_payload(
                    patient["id"], channel="AFTER_HOURS_LINE", severity="MODERATE"
                ),
                NURSE,
            )
        )
        resolved = validate_success(
            api.divert_triage_case(case["id"], {"urgent_appointment_id": appt["id"]}, NURSE),
            200,
        )
        assert resolved["status"] == "RESOLVED_DIVERTED"
        assert resolved["disposition"] == "URGENT_CARE_BOOKED"


class TestEdReferralCounter:
    def test_ed_referral_threshold_breach_flags_profitability_review(self, api):
        """PRD §2.11: "The center tracks an ED-referral counter,
        `ed_referral_count_current_month`, counting triage cases resolving `RESOLVED_ED`
        or `EXPIRED` for patients attributed to the center within the current logical
        month."
        PRD §2.11: "When the count of `RESOLVED_ED` plus `EXPIRED` cases in a period rises
        strictly above the monthly floor of 10 — from the eleventh such case onward — the
        center's profitability review is flagged at the next close."

        Design: Difficulty/transitive_cascade/ed_referral_threshold_breach_flags_profitability_review
        """
        center, team, room, plan, patient, attr = setup_panel_with_active_patient()
        for i in range(11):
            case = get_success_data(
                api.create_triage_case(
                    create_triage_case_payload(
                        patient["id"], channel="AFTER_HOURS_LINE", severity="HIGH"
                    ),
                    NURSE,
                )
            )
            validate_success(api.refer_ed_triage_case(case["id"], NURSE), 200)

        center_after = get_success_data(api.get_center(center["id"], NET))
        assert center_after["ed_referral_count_current_month"] == 11

    def test_ed_referral_counter_at_floor_not_above(self, api):
        """PRD §2.11: "When the count of `RESOLVED_ED` plus `EXPIRED` cases in a period rises
        strictly above the monthly floor of 10 — from the eleventh such case onward — the
        center's profitability review is flagged at the next close."
        PRD §3.7: "The case moves to `RESOLVED_ED` with `disposition` `ED_REFERRED` and
        `diversion_success` false, and the patient's center
        `ed_referral_count_current_month` increments by 1, subject to the monthly floor
        described in §2.11."

        Design: Difficulty/transitive_cascade/ed_referral_threshold_breach_flags_profitability_review
        """
        center, team, room, plan, patient, attr = setup_panel_with_active_patient()
        for i in range(10):
            case = get_success_data(
                api.create_triage_case(
                    create_triage_case_payload(
                        patient["id"], channel="WALK_IN", severity="HIGH"
                    ),
                    NURSE,
                )
            )
            validate_success(api.refer_ed_triage_case(case["id"], NURSE), 200)

        center_after = get_success_data(api.get_center(center["id"], NET))
        # Exactly at the floor of 10 — not strictly above.
        assert center_after["ed_referral_count_current_month"] == 10


class TestDiversionRateInputSet:
    def test_diversion_rate_excludes_self_care(self, api):
        """PRD §2.11: "`RESOLVED_SELF_CARE` cases are excluded from both the numerator and
        denominator of the diversion rate."
        PRD §3.7: "The center-month **ED diversion rate** divides `RESOLVED_DIVERTED`
        cases by the sum of `RESOLVED_DIVERTED`, `RESOLVED_ED`, and `EXPIRED` cases,
        carried at 4 decimal places with round-half-up; `RESOLVED_SELF_CARE` cases enter
        neither numerator nor denominator."
        PRD §3.7: "Self-care requires an `OPEN` case (`ERR_TRIAGE_NOT_OPEN`) and
        `severity` exactly `LOW` (`ERR_SEVERITY_TOO_HIGH_FOR_SELF_CARE`). The case moves
        to `RESOLVED_SELF_CARE` with `disposition` `SELF_CARE_ADVISED`."

        Design: Corner/calculations/diversion_rate_excludes_self_care
        """
        center, team, room, plan, patient, attr = setup_panel_with_active_patient()

        def _open_case(severity):
            return get_success_data(
                api.create_triage_case(
                    create_triage_case_payload(
                        patient["id"], channel="AFTER_HOURS_LINE", severity=severity
                    ),
                    NURSE,
                )
            )

        def _urgent_slot(start_utc):
            return create_appointment(
                team["id"], patient["id"], room["id"],
                start_utc=start_utc, duration_minutes=40, kind="PRIMARY",
            )

        # 2 diverted
        d1 = _open_case("MODERATE")
        s1 = _urgent_slot("2026-09-01T14:00:00Z")
        validate_success(
            api.divert_triage_case(d1["id"], {"urgent_appointment_id": s1["id"]}, NURSE), 200
        )
        d2 = _open_case("LOW")
        s2 = _urgent_slot("2026-09-01T15:00:00Z")
        validate_success(
            api.divert_triage_case(d2["id"], {"urgent_appointment_id": s2["id"]}, NURSE), 200
        )
        # 1 ED-referred
        e1 = _open_case("HIGH")
        validate_success(api.refer_ed_triage_case(e1["id"], NURSE), 200)
        # 3 self-care (must be LOW)
        for _ in range(3):
            sc = _open_case("LOW")
            validate_success(api.advise_self_care_triage_case(sc["id"], NURSE), 200)
        # 1 expired: OPEN for more than 24h, then the clock advances.
        x1 = _open_case("LOW")
        set_clock("2026-09-03T00:00:00Z")
        expired = get_success_data(api.get_triage_case(x1["id"], NURSE))
        assert expired["status"] == "EXPIRED"
        assert expired["disposition"] is None

        # ed_referral_count_current_month counts RESOLVED_ED + EXPIRED = 2;
        # the 3 self-care resolutions are excluded.
        center_after = get_success_data(api.get_center(center["id"], NET))
        assert center_after["ed_referral_count_current_month"] == 2
