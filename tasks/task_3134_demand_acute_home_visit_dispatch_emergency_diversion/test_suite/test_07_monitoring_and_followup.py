"""Monitoring check-ins, follow-up notices, market open-visit-count invariant."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_market,
    create_patient,
    create_triage_assessment_payload,
    create_visit_request_payload,
    get_success_data,
    set_clock,
    setup_dispositioned_home_visit,
    validate_error,
    validate_success,
    RED_FLAG_VITALS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
NURSE = TEST_USERS["triage_nurse_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


class TestOpenVisitCountInvariant:
    def test_intake_increments_and_diversion_restores(self, api):
        """PRD §3.1: "Each market maintains a computed `open_visit_count` —
        the number of its visit requests currently in any non-terminal status
        ... which rises by one at intake and falls by one whenever a visit
        reaches `EMS_DIVERTED`, `DECLINED`, or `CLOSED`."

        Design: Difficulty/compensating_invariant/market_open_visit_count_invariant_on_terminal_transitions
        """
        set_clock("2026-09-15T10:00:00Z")
        market = create_market()
        before = validate_success(api.get_market(market["id"], DISPATCHER))
        assert before["open_visit_count"] == 0
        patient = create_patient(
            full_name="Pam P", member_id="M1700", pcp_npi="9999999990"
        )
        vr = get_success_data(
            api.create_visit_request(
                create_visit_request_payload(
                    patient["id"], market["id"],
                    chief_complaint="crushing chest pain",
                ),
                NURSE,
            )
        )
        after_intake = validate_success(api.get_market(market["id"], DISPATCHER))
        assert after_intake["open_visit_count"] == 1
        trg = get_success_data(
            api.create_triage_assessment(
                vr["id"], create_triage_assessment_payload(**RED_FLAG_VITALS), NURSE
            )
        )
        get_success_data(
            api.submit_triage_assessment(
                trg["id"], {"outcome": "EMERGENCY_DIVERTED"}, NURSE
            )
        )
        after_divert = validate_success(api.get_market(market["id"], DISPATCHER))
        assert after_divert["open_visit_count"] == 0
        vr_after = validate_success(api.get_visit_request(vr["id"], DISPATCHER))
        assert vr_after["status"] == "EMS_DIVERTED"

    def test_decline_also_decrements_count(self, api):
        """PRD §3.1: "falls by one whenever a visit reaches `EMS_DIVERTED`,
        `DECLINED`, or `CLOSED`."
        PRD §3.3: "An `INAPPROPRIATE` submission sets the band to `NON_ACUTE`,
        moves the visit to the terminal `DECLINED` state, and decrements the
        market's `open_visit_count` by one."

        Design: Difficulty/compensating_invariant/market_open_visit_count_invariant_on_terminal_transitions
        """
        set_clock("2026-09-15T10:00:00Z")
        market = create_market()
        patient = create_patient(
            full_name="Pam Q", member_id="M1701", pcp_npi="9999999981",
            comorbidity_count=0,
        )
        vr = get_success_data(
            api.create_visit_request(
                create_visit_request_payload(
                    patient["id"], market["id"], chief_complaint="mild cold"
                ),
                NURSE,
            )
        )
        assert validate_success(
            api.get_market(market["id"], DISPATCHER)
        )["open_visit_count"] == 1
        trg = get_success_data(
            api.create_triage_assessment(
                vr["id"],
                create_triage_assessment_payload(
                    heart_rate=80, systolic_bp=120, spo2_pct=99,
                    is_chest_pain=False, is_stroke_signs=False,
                    is_severe_trauma=False, is_altered_mental_status=False,
                ),
                NURSE,
            )
        )
        get_success_data(
            api.submit_triage_assessment(
                trg["id"], {"outcome": "INAPPROPRIATE"}, NURSE
            )
        )
        assert validate_success(
            api.get_market(market["id"], DISPATCHER)
        )["open_visit_count"] == 0


class TestMonitoringCheckInCascade:
    def test_emergent_completion_spawns_new_visit(self, api):
        """PRD §3.8: "Completing a check-in with outcome `EMERGENT`, or
        escalating a `MISSED` check-in, automatically creates a new
        **VisitRequest** for the same patient with `requestor_role` set to
        `PROVIDER`, starting fresh in `INTAKE` — the transitive cascade from a
        post-visit signal into a new episode."
        PRD §3.1: "Each market maintains a computed `open_visit_count` ...
        which rises by one at intake".

        Design: Difficulty/transitive_cascade/monitoring_checkin_emergent_spawns_new_visit_cascade
        """
        ctx = setup_dispositioned_home_visit(
            app_user="app-G", tech_user="tech-G", with_contract=True
        )
        checkins = validate_success(
            api.list_visit_monitoring_checkins(ctx["vr"]["id"], NURSE)
        )
        assert len(checkins) == 2
        chk = sorted(checkins, key=lambda c: c["scheduled_at"])[0]
        # Advance the logical clock past the +24h check-in.
        set_clock("2026-09-16T11:00:00Z")
        completed = validate_success(
            api.complete_monitoring_checkin(chk["id"], {"outcome": "EMERGENT"}, NURSE)
        )
        assert completed["status"] == "COMPLETED"
        visits = validate_success(
            api.list_patient_visit_requests(ctx["patient"]["id"], NURSE)
        )
        spawned = [v for v in visits if v["id"] != ctx["vr"]["id"]]
        assert len(spawned) == 1
        assert spawned[0]["requestor_role"] == "PROVIDER"
        assert spawned[0]["status"] == "INTAKE"
        market_after = validate_success(
            api.get_market(ctx["market"]["id"], DISPATCHER)
        )
        # Original visit still open (DISPOSITIONED) plus the spawned visit.
        assert market_after["open_visit_count"] == 2

    def test_stable_completion_does_not_spawn_new_visit(self, api):
        """PRD §3.8: "Completing a check-in with outcome `EMERGENT`, or
        escalating a `MISSED` check-in, automatically creates a new
        **VisitRequest** for the same patient with `requestor_role` set to
        `PROVIDER`, starting fresh in `INTAKE`".
        PRD §3.8: "Completing a check-in requires the logical clock to have
        reached its `scheduled_at` ... and a recorded `outcome` of `STABLE`,
        `WORSENING`, or `EMERGENT`; the row then moves to `COMPLETED` with
        `completed_at` stamped."

        Design: Difficulty/transitive_cascade/monitoring_checkin_emergent_spawns_new_visit_cascade
        """
        ctx = setup_dispositioned_home_visit(
            app_user="app-G2", tech_user="tech-G2", with_contract=True
        )
        checkins = validate_success(
            api.list_visit_monitoring_checkins(ctx["vr"]["id"], NURSE)
        )
        chk = sorted(checkins, key=lambda c: c["scheduled_at"])[0]
        set_clock("2026-09-16T11:00:00Z")
        completed = validate_success(
            api.complete_monitoring_checkin(chk["id"], {"outcome": "STABLE"}, NURSE)
        )
        assert completed["status"] == "COMPLETED"
        assert completed["completed_at"] is not None
        visits = validate_success(
            api.list_patient_visit_requests(ctx["patient"]["id"], NURSE)
        )
        assert len(visits) == 1, "a STABLE completion must not spawn a new visit"

    def test_complete_before_due_rejected(self, api):
        """PRD §3.8: "Completing a check-in requires the logical clock to have
        reached its `scheduled_at` — completing early is rejected with
        `ERR_CHECKIN_NOT_DUE` (HTTP 409)".

        Design: Corner/validations/checkin_complete_before_due_returns_not_due
        """
        ctx = setup_dispositioned_home_visit(
            app_user="app-E", tech_user="tech-E", with_contract=True
        )
        checkins = validate_success(
            api.list_visit_monitoring_checkins(ctx["vr"]["id"], NURSE)
        )
        chk = sorted(checkins, key=lambda c: c["scheduled_at"])[0]
        # Logical clock is still at disposition time; check-in due at +24h.
        resp = api.complete_monitoring_checkin(
            chk["id"], {"outcome": "STABLE"}, NURSE
        )
        validate_error(resp, ApiErrorId.ERR_CHECKIN_NOT_DUE)


class TestFollowUpNotice:
    def test_pcp_mismatch_rejected(self, api):
        """PRD §3.8: "a `TriageNurse` queues a **FollowUpNotice** against the
        visit, supplying the `pcp_npi` the notice is routed to — which must
        equal the patient's recorded `pcp_npi`, else `ERR_PCP_MISMATCH`
        (HTTP 422)".

        Design: Corner/validations/pcp_mismatch_on_follow_up_notice
        """
        ctx = setup_dispositioned_home_visit(
            app_user="app-D", tech_user="tech-D", with_contract=True
        )
        resp = api.create_follow_up_notice(
            ctx["vr"]["id"],
            {
                "pcp_npi": "9999999999",
                "payload_summary": (
                    "Visit summary; patient stable; discharged with "
                    "precautions reviewed thoroughly."
                ),
            },
            NURSE,
        )
        validate_error(resp, ApiErrorId.ERR_PCP_MISMATCH)
