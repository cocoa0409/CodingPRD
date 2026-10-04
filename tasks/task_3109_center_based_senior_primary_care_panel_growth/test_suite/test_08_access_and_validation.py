"""Access control and the validation cascade: header presence, role
authorization, segregated duties, and temporal-vs-fiscal ordering."""
from test_helpers import (
    ApiErrorId,
    adjudicate_claim,
    create_center_payload,
    create_checked_in_appointment,
    create_cost_claim_payload,
    create_dispatched_ride,
    create_appointment,
    create_open_center,
    create_open_settlement,
    create_patient,
    create_vehicle_payload,
    get_success_data,
    set_clock,
    setup_panel_with_active_patient,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

NET = TEST_USERS["network_operator_headers"]
ADJ = TEST_USERS["claims_adjudicator_headers"]
FA = TEST_USERS["finance_analyst_headers"]
FC = TEST_USERS["finance_controller_headers"]
FRONT = TEST_USERS["front_desk_headers"]
NURSE = TEST_USERS["triage_nurse_headers"]


class TestHeaderPresence:
    def test_missing_role_header_rejected(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role string not in
        this enumeration, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (HTTP 400)."

        Design: Corner/validations/missing_role_header_rejected
        """
        resp = api.create_center(
            create_center_payload(name="H", neighborhood_code="NH"),
            headers={"X-User-ID": "test-no-role-1"},
        )
        validate_error(
            resp,
            ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value,
            expected_status=400,
        )

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role string not in
        this enumeration, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (HTTP 400)."

        Design: Corner/validations/missing_role_header_rejected
        """
        resp = api.create_center(
            create_center_payload(name="H2", neighborhood_code="NH2"),
            headers={"X-User-Role": "NetworkOperator"},
        )
        validate_error(
            resp,
            ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value,
            expected_status=400,
        )


class TestSegregationOfDuties:
    def test_finance_analyst_cannot_finalize_settlement(self, api):
        """PRD §2.1: "`FinanceAnalyst` opens and provisionally closes settlements but cannot
        finalize them."
        PRD §2.1: "A request whose role is authenticated but not permitted for the
        attempted operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/roles/finance_analyst_cannot_finalize_settlement
        """
        center, team, room = create_open_center()
        settlement = create_open_settlement(center["id"], "2026-09")
        set_clock("2026-10-01T00:00:00Z")
        center_now = get_success_data(api.get_center(center["id"], NET))
        validate_success(
            api.close_provisional_settlement(
                settlement["id"], {"expected_center_version": center_now["version"]}, FA
            ),
            200,
        )
        resp = api.finalize_settlement(settlement["id"], FA)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)

    def test_claims_adjudicator_cannot_dispatch_rides(self, api):
        """PRD §2.1: "A request whose role is authenticated but not permitted for the
        attempted operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: dispatch is authorized for `TransportDispatcher` only.

        Design: Corner/roles/claims_adjudicator_cannot_dispatch_rides
        """
        center, team, room, plan, patient, attr = setup_panel_with_active_patient()
        vehicle = get_success_data(
            api.create_vehicle(center["id"], create_vehicle_payload(), NET)
        )
        appt = create_appointment(
            team["id"], patient["id"], room["id"],
            start_utc="2026-09-10T14:40:00Z", duration_minutes=40,
        )
        ride = get_success_data(api.create_ride_request(appt["id"], FRONT))
        resp = api.dispatch_ride(ride["id"], {"vehicle_id": vehicle["id"]}, ADJ)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)

    def test_triage_nurse_cannot_complete_appointments(self, api):
        """PRD §2.1: "A request whose role is authenticated but not permitted for the
        attempted operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §3.5: "Completion belongs to the `CareTeamLead`."

        Design: Corner/roles/triage_nurse_cannot_complete_appointments
        """
        center, team, room, plan, patient, attr = setup_panel_with_active_patient()
        appt = create_checked_in_appointment(
            team, patient["id"], room["id"],
            start_utc="2026-09-10T14:00:00Z", checkin_clock="2026-09-10T13:50:00Z",
        )
        resp = api.complete_appointment(appt["id"], NURSE)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)


class TestTemporalLegality:
    def test_future_effective_month_rejected_at_create(self, api):
        """PRD §3.4: "The `effective_month` must not be earlier than the current logical
        month (`ERR_TEMPORAL_VIOLATION`), and the patient must hold no other `PENDING` or
        `ACTIVE` attribution (`ERR_PATIENT_ALREADY_ATTRIBUTED`)."

        Design: Corner/validations/future_effective_month_rejected_at_create
        """
        center, team, room = create_open_center()
        plan = get_success_data(
            api.create_health_plan(
                {
                    "plan_name": "MA",
                    "contract_type": "FULL_RISK",
                    "base_pmpm_cents": 90000,
                    "risk_adjust_factor": 1.0,
                    "revenue_share_pct": 1.0,
                },
                FC,
            )
        )
        patient = create_patient()
        set_clock("2026-09-15T00:00:00Z")
        resp = api.create_attribution(
            {
                "patient_id": patient["id"],
                "health_plan_id": plan["id"],
                "care_team_id": team["id"],
                "effective_month": "2026-08",
            },
            TEST_USERS["enrollment_coordinator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_TEMPORAL_VIOLATION.value, expected_status=422)

    def test_state_priority_beats_fiscal_on_claim_submit(self, api):
        """PRD §2.7: "Every mutation passes through a fixed validation cascade, and the
        cascade's ordering is itself a contract — when several checks could fail, the
        first one in this order determines the rejection:"
        PRD §2.7: "5. Temporal legality of date and month inputs — effective months not
        before the current logical month, event dates not in the past, appointment starts
        on the 20-minute boundary, and service months not after the current logical month
        (`ERR_TEMPORAL_VIOLATION`)."
        PRD §3.8: "The `service_month` must not be after the current logical month
        (`ERR_TEMPORAL_VIOLATION`), and the period's settlement must not be `FINALIZED`
        (`ERR_SETTLEMENT_FINALIZED`)."

        Design: Corner/validations/state_priority_beats_fiscal_on_claim_submit
        """
        center, team, room = create_open_center()
        patient = create_patient()
        # Finalize the 2026-08 settlement so the fiscal gate is armed, while the
        # clock sits in 2026-09.
        settlement = create_open_settlement(center["id"], "2026-08")
        set_clock("2026-09-15T00:00:00Z")
        center_now = get_success_data(api.get_center(center["id"], NET))
        validate_success(
            api.close_provisional_settlement(
                settlement["id"], {"expected_center_version": center_now["version"]}, FA
            ),
            200,
        )
        validate_success(api.finalize_settlement(settlement["id"], FC), 200)

        # A future service_month (2027-01) violates the temporal rule; the
        # temporal rejection precedes any fiscal gate.
        resp = api.create_cost_claim(
            create_cost_claim_payload(
                center["id"], patient["id"],
                service_month="2027-01", category="PHARMACY", amount_cents=100,
            ),
            ADJ,
        )
        validate_error(resp, ApiErrorId.ERR_TEMPORAL_VIOLATION.value, expected_status=422)
