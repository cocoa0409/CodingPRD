"""State-machine corners: initial states, guarded edges, terminal lockdowns and cascades."""
import pytest

from test_helpers import (
    ENFORCEMENT_OFFICER,
    PROGRAM_ADMIN,
    STATE_DATA_STEWARD,
    ApiErrorId,
    acknowledgement_payload,
    add_station_hours,
    add_watercraft,
    api_client,
    assert_inspection_record,
    assert_instant_equals,
    assert_seal_inventory_conserved,
    assert_strike_posture,
    breach_report_payload,
    campaign_evaluation_payload,
    campaign_status_payload,
    create_station,
    create_water_body,
    disposition_payload,
    draft_detection_report,
    dry_verification_payload,
    enforcement_payload,
    enroll_inspector,
    fetch_campaign,
    fetch_decon_order,
    fetch_detection_report,
    fetch_inspector,
    fetch_quarantine_order,
    fetch_record,
    fetch_station,
    fetch_water_body,
    fetch_watercraft,
    inspection_record_payload,
    inspector_status_payload,
    make_decon_technician_headers,
    make_inspector_headers,
    make_release_verifier_headers,
    move_station,
    order_decon,
    plan_campaign,
    release_decision_payload,
    release_request_payload,
    report_breach,
    screening_payload,
    set_clock,
    setup_decon_order,
    setup_decon_required,
    setup_inspection,
    setup_program,
    setup_quarantined_record,
    setup_treated_order,
    station_status_payload,
    treat_order,
    treatment_payload,
    validate_error,
    validate_success,
    verify_dry,
)

ARRIVAL = "2026-08-05T09:00:00Z"
SEASON_START = "2026-07-01T00:00:00Z"
SEASON_END = "2026-10-01T00:00:00Z"


class TestNewInspectionRecordInitialState:
    """Both dimensions of a fresh record are initialised in the same response."""

    def test_a_freshly_opened_record_starts_initiated_and_none(self):
        """The creation response carries INITIATED, NONE and every null and zero.

        PRD: "A freshly opened record is deliberately empty of judgement.
        `inspection_status` — one of `INITIATED`, `SCREENED`, `PASSED`,
        `DECON_REQUIRED`, `DECON_COMPLETED`, `DECON_FAILED_ABANDONED` or
        `REFUSED` — starts `INITIATED`, and `enforcement_status` — one of `NONE`,
        `REFERRED`, `CITED` or `DISMISSED` — starts `NONE`; these are the two
        independent dimensions described below."

        Design: Corner/state_machines/initial_state_new_inspection_record_starts_initiated_and_none
        """
        ctx = setup_program(mandatory_inspection=True, decon_bay_count=2,
                            seal_stock_initial_count=3)
        watercraft = add_watercraft(ctx)
        set_clock(ARRIVAL)

        data = validate_success(
            api_client.create_inspection_record(
                inspection_record_payload(ctx["station"]["id"], watercraft["id"], ARRIVAL),
                make_inspector_headers(ctx["inspector_a"]["id"]),
            ),
            201,
        )

        assert_inspection_record(data)
        assert data["inspection_status"] == "INITIATED"
        assert data["enforcement_status"] == "NONE"
        assert data["screening_completed_at"] is None
        assert data["referral_reason"] is None
        assert data["agency_code"] is None
        assert data["honored_agreement_id"] is None
        assert data["reciprocity_seal_honored"] is False
        assert data["dry_credit_points"] == 0
        assert data["risk_score"] == 0
        assert data["total_fee_cents"] == 0
        assert data["decon_mandatory"] is False
        assert data["quarantine_warranted"] is False
        assert data["risk_band"] == "LOW"

        reread = fetch_record(data["id"])
        assert reread["inspection_status"] == "INITIATED"
        assert reread["enforcement_status"] == "NONE"


def _planned_station(**overrides):
    """A PLANNED water-body access station, hours not yet declared."""
    set_clock("2026-08-01T00:00:00Z")
    water_body = create_water_body(risk_tier="HIGH")
    payload = {"name": "Polson Access", "water_body_id": water_body["id"],
               "seal_stock_initial_count": 3}
    payload.update(overrides)
    return water_body, create_station(**payload)


class TestStationOpeningSeedsSealStock:
    """The declared PLANNED -> OPEN edge seeds the seal shelf exactly once."""

    def test_opening_a_planned_station_seeds_the_seal_stock_and_bumps_the_version(self):
        """Three delivered seals land on the shelf with nothing in circulation.

        PRD: "`PLANNED → OPEN` opens the station for the season and is permitted
        only when at least one hours window has already been declared for it; an
        attempt to open a station with no declared hours is rejected with
        `ERR_INVALID_STATION_STATE`. Opening also re-initialises the seal stock,
        recomputes `decon_service_available`, and advances the station's
        `version` by 1."

        Design: Corner/state_machines/valid_transition_station_planned_to_open_seeds_seal_stock
        """
        _water_body, station = _planned_station(hot_water_capable=True, decon_bay_count=1)
        add_station_hours(station["id"], opens_at=SEASON_START, closes_at=SEASON_END)
        before = fetch_station(station["id"])

        data = validate_success(
            api_client.set_station_status(
                station["id"], station_status_payload("OPEN", reason="season start"),
                PROGRAM_ADMIN,
            ),
            200,
        )

        assert data["status"] == "OPEN"
        assert data["seal_stock_count"] == 3
        assert data["seals_in_circulation_count"] == 0
        assert data["seals_retired_count"] == 0
        assert_seal_inventory_conserved(data)
        assert data["version"] == before["version"] + 1
        assert data["certified_inspector_count"] == 0
        assert data["decon_service_available"] is False


class TestStationCannotOpenWithoutDeclaredHours:
    """The opening edge carries a child-row precondition, not just a status test."""

    def test_opening_a_station_with_no_hours_window_is_refused(self):
        """Zero hours rows make the OPEN call a 409 and leave the station PLANNED.

        PRD: "`PLANNED → OPEN` opens the station for the season and is permitted
        only when at least one hours window has already been declared for it; an
        attempt to open a station with no declared hours is rejected with
        `ERR_INVALID_STATION_STATE`."

        Design: Corner/state_machines/precondition_enforcement_station_cannot_open_without_hours_rejected
        """
        _water_body, station = _planned_station()
        before = fetch_station(station["id"])

        response = api_client.set_station_status(
            station["id"], station_status_payload("OPEN"), PROGRAM_ADMIN
        )

        validate_error(response, ApiErrorId.ERR_INVALID_STATION_STATE)
        after = fetch_station(station["id"])
        assert after["status"] == "PLANNED"
        assert after["version"] == before["version"]
        assert after["seals_in_circulation_count"] == 0
        assert after["seals_retired_count"] == 0
        assert after["decon_service_available"] is False

    def test_declaring_one_window_makes_the_identical_call_succeed(self):
        """The same OPEN call is accepted the moment a window exists.

        PRD: "Operating hours are declared one window at a time, each window
        naming the station in `station_id` and carrying an inclusive `opens_at`
        and an exclusive `closes_at` as ISO 8601 UTC instants with three
        fractional digits, plus an optional `staffing_level` of `SINGLE` or
        `DOUBLE` that defaults to `SINGLE`."

        Design: Corner/state_machines/precondition_enforcement_station_cannot_open_without_hours_rejected
        """
        _water_body, station = _planned_station()
        validate_error(
            api_client.set_station_status(
                station["id"], station_status_payload("OPEN"), PROGRAM_ADMIN
            ),
            ApiErrorId.ERR_INVALID_STATION_STATE,
        )
        add_station_hours(station["id"], opens_at=SEASON_START, closes_at=SEASON_END)

        data = validate_success(
            api_client.set_station_status(
                station["id"], station_status_payload("OPEN"), PROGRAM_ADMIN
            ),
            200,
        )

        assert data["status"] == "OPEN"
        assert data["seal_stock_count"] == 3


def _closed_station():
    """Walk a station PLANNED -> OPEN -> CLOSED with no record ever opened there."""
    _water_body, station = _planned_station()
    add_station_hours(station["id"], opens_at=SEASON_START, closes_at=SEASON_END)
    move_station(station["id"], "OPEN")
    return move_station(station["id"], "CLOSED")


class TestClosedStationIsTerminal:
    """CLOSED is the station machine's only terminal state and it is absolute."""

    @pytest.mark.parametrize("target_status", ["OPEN", "SUSPENDED", "CLOSED"])
    def test_every_status_call_against_a_closed_station_is_refused(self, target_status):
        """Reopening, suspending and re-closing are all 409s with no version bump.

        PRD: "`CLOSED` is terminal: any subsequent status call against a closed
        station, whatever `target_status` it names, is rejected with
        `ERR_INVALID_STATION_STATE`, no field changes, and the station's
        `version` is *not* bumped."

        Design: Corner/state_machines/terminal_state_lockdown_closed_station_rejects_every_status_call
        """
        closed = _closed_station()
        assert closed["status"] == "CLOSED"

        response = api_client.set_station_status(
            closed["id"], station_status_payload(target_status), PROGRAM_ADMIN
        )

        validate_error(response, ApiErrorId.ERR_INVALID_STATION_STATE)
        after = fetch_station(closed["id"])
        assert after["status"] == "CLOSED"
        assert after["version"] == closed["version"]
        assert after["seal_stock_count"] == closed["seal_stock_count"]


def _initiated_record():
    """A HIGH-risk lake record opened but deliberately left unscreened."""
    return setup_inspection(screen=False, arrived_at=ARRIVAL, mandatory_inspection=True)


class TestDispositionBeforeScreeningIsRefused:
    """No disposition edge leaves INITIATED, and the miss has its own 409."""

    def test_disposing_an_unscreened_record_is_refused_and_books_no_fee(self):
        """A PASS on an INITIATED record is ERR_RECORD_NOT_SCREENED, not ALREADY_DISPOSED.

        PRD: "The record must already be in `SCREENED`; a disposition attempted
        on a record still in `INITIATED` is rejected with
        `ERR_RECORD_NOT_SCREENED`, and one attempted on a record that has already
        been disposed is rejected with `ERR_RECORD_ALREADY_DISPOSED`."

        Design: Corner/state_machines/invalid_transition_disposition_before_screening_rejected
        """
        ctx = _initiated_record()
        record = ctx["record"]
        assert record["inspection_status"] == "INITIATED"

        response = api_client.dispose_inspection_record(
            record["id"], disposition_payload("PASS"),
            make_inspector_headers(ctx["inspector_a"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_RECORD_NOT_SCREENED)
        after = fetch_record(record["id"])
        assert after["inspection_status"] == "INITIATED"
        assert after["version"] == record["version"]
        assert after["total_fee_cents"] == 0
        assert fetch_station(ctx["station"]["id"])["collected_fees_cents"] == 0

    def test_screening_first_unblocks_the_identical_disposition_call(self):
        """Once the record is SCREENED the disposition is accepted and billed.

        PRD: "`SCREENED → DECON_REQUIRED` opens the decontamination pathway of
        §3.6 and leaves the record's fee open for the treatment charge still to
        come."

        Design: Corner/state_machines/invalid_transition_disposition_before_screening_rejected
        """
        ctx = _initiated_record()
        headers = make_inspector_headers(ctx["inspector_a"]["id"])
        validate_error(
            api_client.dispose_inspection_record(
                ctx["record"]["id"], disposition_payload("DECON"), headers
            ),
            ApiErrorId.ERR_RECORD_NOT_SCREENED,
        )
        vessel_version = fetch_watercraft(ctx["watercraft"]["id"])["version"]

        screened = validate_success(
            api_client.screen_inspection_record(
                ctx["record"]["id"],
                screening_payload(vessel_version, residual_water_present=True,
                                  standing_water_ml=500),
                headers,
            ),
            200,
        )
        assert screened["risk_score"] == 65
        assert screened["risk_band"] == "HIGH"
        assert screened["decon_mandatory"] is True

        disposed = validate_success(
            api_client.dispose_inspection_record(
                ctx["record"]["id"], disposition_payload("DECON"), headers
            ),
            200,
        )
        assert disposed["inspection_status"] == "DECON_REQUIRED"
        assert disposed["total_fee_cents"] == 2500


def _passed_record():
    """A clean-lake record screened dry (score 5, LOW band) and disposed PASS."""
    return setup_inspection(
        risk_tier="LOW", infestation_status="CLEAN", mandatory_inspection=True,
        arrived_at=ARRIVAL, screen_at=ARRIVAL, residual_water_present=False,
        disposition="PASS",
    )


class TestSecondDispositionOnAPassedRecordIsRefused:
    """PASSED is terminal on the inspection dimension, so the replay is a 409."""

    def test_replaying_the_pass_is_refused_and_the_fee_is_not_booked_twice(self):
        """The station ledger stays at one 2,500-cent booking.

        PRD: "The record must already be in `SCREENED`; a disposition attempted
        on a record still in `INITIATED` is rejected with
        `ERR_RECORD_NOT_SCREENED`, and one attempted on a record that has already
        been disposed is rejected with `ERR_RECORD_ALREADY_DISPOSED`."

        Design: Corner/state_machines/idempotency_second_disposition_on_a_passed_record_rejected
        """
        ctx = _passed_record()
        passed = ctx["record"]
        assert passed["inspection_status"] == "PASSED"
        assert passed["risk_score"] == 5
        assert passed["risk_band"] == "LOW"
        assert passed["inspection_fee_cents"] == 2500
        assert passed["surcharge_cents"] == 0
        assert passed["total_fee_cents"] == 2500

        response = api_client.dispose_inspection_record(
            passed["id"], disposition_payload("PASS"),
            make_inspector_headers(ctx["inspector_a"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_RECORD_ALREADY_DISPOSED)
        after = fetch_record(passed["id"])
        assert after["inspection_status"] == "PASSED"
        assert after["version"] == passed["version"]
        assert after["total_fee_cents"] == 2500
        assert fetch_station(ctx["station"]["id"])["collected_fees_cents"] == 2500

    def test_re_screening_a_passed_record_is_refused_with_the_same_error(self):
        """Re-screening is only legal from SCREENED, so a PASSED record refuses it.

        PRD: "Screening a record whose `inspection_status` has already left
        `SCREENED` is rejected with `ERR_RECORD_ALREADY_DISPOSED`."

        Design: Corner/state_machines/idempotency_second_disposition_on_a_passed_record_rejected
        """
        ctx = _passed_record()
        vessel_version = fetch_watercraft(ctx["watercraft"]["id"])["version"]

        response = api_client.screen_inspection_record(
            ctx["record"]["id"], screening_payload(vessel_version),
            make_inspector_headers(ctx["inspector_a"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_RECORD_ALREADY_DISPOSED)
        assert fetch_record(ctx["record"]["id"])["inspection_status"] == "PASSED"


class TestDryVerificationOnAnOrderedOrderIsRefused:
    """Every dry-verification edge starts at TREATED, so ORDERED refuses all three."""

    @pytest.mark.parametrize("outcome", ["VERIFIED", "ABANDON"])
    def test_verifying_an_untreated_order_is_refused(self, outcome):
        """Even the dry-time-exempt ABANDON outcome cannot leave ORDERED.

        PRD: "The order must be in `TREATED`: verification aimed at an order
        still in `ORDERED` or already back in `RETREAT_REQUIRED` is
        `ERR_DECON_NOT_TREATED`, while verification aimed at an order already in
        `VERIFIED` or `ABANDONED` is `ERR_DECON_ALREADY_TERMINAL`, so the two
        409s never both apply to the same call."

        Design: Corner/state_machines/invalid_transition_dry_verification_on_ordered_order_rejected
        """
        ctx = setup_decon_order()
        order = ctx["decon_order"]
        assert order["status"] == "ORDERED"
        assert order["attempt_count"] == 0
        assert order["band_at_order"] == "HIGH"
        assert order["dry_until"] is None

        response = api_client.verify_decon_dry_time(
            order["id"], dry_verification_payload(outcome),
            make_release_verifier_headers(ctx["inspector_c"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_DECON_NOT_TREATED)
        after = fetch_decon_order(order["id"])
        assert after["status"] == "ORDERED"
        assert after["verified_by_inspector_id"] is None
        assert after["version"] == order["version"]
        assert fetch_record(ctx["record"]["id"])["inspection_status"] == "DECON_REQUIRED"

    def test_the_state_gate_is_announced_ahead_of_the_dry_time_gate(self):
        """dry_until is null on an ORDERED order, yet the 409 names the state.

        PRD: "And because the state-transition check sits at step 14, ahead of
        every safety gate, a dry verification aimed at an order that is still
        `ORDERED` reports `ERR_DECON_NOT_TREATED` rather than complaining that
        the dry time has not elapsed."

        Design: Corner/state_machines/invalid_transition_dry_verification_on_ordered_order_rejected
        """
        ctx = setup_decon_order()
        assert ctx["decon_order"]["dry_until"] is None

        response = api_client.verify_decon_dry_time(
            ctx["decon_order"]["id"], dry_verification_payload("RETREAT"),
            make_release_verifier_headers(ctx["inspector_c"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_DECON_NOT_TREATED)


def _verified_order():
    """A HIGH-band order treated at the thresholds and then verified at 04:00Z."""
    ctx = setup_treated_order()
    set_clock("2026-08-06T04:00:00Z")
    ctx["decon_order"] = verify_dry(
        ctx["decon_order"]["id"], ctx["inspector_c"]["id"], "VERIFIED"
    )
    return ctx


class TestVerifiedDeconOrderIsFrozen:
    """VERIFIED is terminal on the order machine, and it beats the attempt cap."""

    def test_retreating_a_verified_order_is_refused_and_bills_nothing(self):
        """The station ledger stays at 3,400 cents and attempt_count stays 1.

        PRD: "`ERR_DECON_ALREADY_TERMINAL` when treatment or verification is
        requested on an order already in `VERIFIED` or `ABANDONED`, which is why
        those two 409s never both apply to one call."

        Design: Corner/state_machines/terminal_state_lockdown_verified_decon_order_rejects_retreatment
        """
        ctx = _verified_order()
        verified = ctx["decon_order"]
        assert verified["status"] == "VERIFIED"
        assert verified["attempt_count"] == 1
        assert float(verified["treatment_effectiveness_pct"]) == 100.00
        assert verified["base_dry_hours"] == 72
        assert verified["required_dry_hours"] == 18
        assert_instant_equals(verified["treated_at"], "2026-08-05T09:02:00Z", "treated_at")
        assert_instant_equals(verified["dry_until"], "2026-08-06T03:02:00Z", "dry_until")
        assert fetch_record(ctx["record"]["id"])["inspection_status"] == "DECON_COMPLETED"

        response = api_client.treat_decon_order(
            verified["id"], treatment_payload(140, 3000, 120),
            make_decon_technician_headers(ctx["inspector_b"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_DECON_ALREADY_TERMINAL)
        after = fetch_decon_order(verified["id"])
        assert after["status"] == "VERIFIED"
        assert after["attempt_count"] == 1
        assert after["version"] == verified["version"]
        assert fetch_station(ctx["station"]["id"])["collected_fees_cents"] == 3400

    def test_a_second_dry_verification_on_a_verified_order_is_refused(self):
        """A RETREAT verdict on the frozen order draws the same terminal 409.

        PRD: "Both `VERIFIED` and `ABANDONED` are terminal."

        Design: Corner/state_machines/terminal_state_lockdown_verified_decon_order_rejects_retreatment
        """
        ctx = _verified_order()

        response = api_client.verify_decon_dry_time(
            ctx["decon_order"]["id"], dry_verification_payload("RETREAT"),
            make_release_verifier_headers(ctx["inspector_c"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_DECON_ALREADY_TERMINAL)
        assert fetch_decon_order(ctx["decon_order"]["id"])["status"] == "VERIFIED"


class TestCitationBeforeReferralIsRefused:
    """CITE and DISMISS both start from REFERRED, so NONE refuses them both."""

    @pytest.mark.parametrize("action", ["CITE", "DISMISS"])
    def test_an_enforcement_action_out_of_order_is_refused(self, action):
        """Citing or dismissing a record still at NONE prices no penalty.

        PRD: "An action not declared from the record's current enforcement
        standing — citing a record still at `NONE`, dismissing one already
        `CITED` — is rejected with `ERR_INVALID_ENFORCEMENT_STATE`."

        Design: Corner/state_machines/invalid_transition_citation_before_referral_rejected
        """
        ctx = _passed_record()
        passed = ctx["record"]
        assert passed["enforcement_status"] == "NONE"

        response = api_client.enforce_inspection_record(
            passed["id"], enforcement_payload(action, agency_code="MT-FWP"),
            ENFORCEMENT_OFFICER,
        )

        validate_error(response, ApiErrorId.ERR_INVALID_ENFORCEMENT_STATE)
        after = fetch_record(passed["id"])
        assert after["enforcement_status"] == "NONE"
        assert after["penalty_cents"] == 0
        assert after["version"] == passed["version"]
        assert_strike_posture(fetch_watercraft(ctx["watercraft"]["id"]), 0)

    def test_a_referral_is_accepted_on_the_same_passed_record(self):
        """Only CITE was out of order: REFER moves the independent dimension.

        PRD: "`enforcement_status` advances on its own transition set with no
        reference whatsoever to `inspection_status`, and neither dimension gates
        the other. A record may sit in terminal `PASSED` while its enforcement
        dimension travels `NONE → REFERRED → CITED`, and a record may be `CITED`
        while its inspection dimension is still `DECON_REQUIRED`."

        Design: Corner/state_machines/invalid_transition_citation_before_referral_rejected
        """
        ctx = _passed_record()

        data = validate_success(
            api_client.enforce_inspection_record(
                ctx["record"]["id"],
                enforcement_payload("REFER", referral_reason="SEAL_TAMPER",
                                    agency_code="MT-FWP"),
                ENFORCEMENT_OFFICER,
            ),
            200,
        )

        assert data["enforcement_status"] == "REFERRED"
        assert data["inspection_status"] == "PASSED"
        assert data["referral_reason"] == "SEAL_TAMPER"
        assert data["agency_code"] == "MT-FWP"
        assert data["penalty_cents"] == 0
        assert_strike_posture(fetch_watercraft(ctx["watercraft"]["id"]), 1)


def _sealed_order():
    """A MODERATE-band order sealed at 09:00Z off a confirmed-infested reservoir."""
    return setup_quarantined_record(
        risk_tier="LOW", infestation_status="CONFIRMED_INFESTED",
        residual_water_present=False, standing_water_ml=0,
        seal_stock_initial_count=3, arrived_at=ARRIVAL, screen_at=ARRIVAL,
    )


class TestReleaseVerificationBeforeTheRequestIsRefused:
    """Both release outcomes leave RELEASE_REQUESTED, so SEALED refuses them."""

    @pytest.mark.parametrize("outcome", ["APPROVED", "REJECTED"])
    def test_deciding_a_still_sealed_order_is_refused(self, outcome):
        """The seal stays in circulation and no verifier is recorded.

        PRD: "The order must be in `RELEASE_REQUESTED`, or the call is
        `ERR_QUARANTINE_RELEASE_NOT_REQUESTED`."

        Design: Corner/state_machines/invalid_transition_release_verification_before_request_rejected
        """
        ctx = _sealed_order()
        record = ctx["record"]
        order = ctx["quarantine_order"]
        assert record["risk_score"] == 35
        assert record["risk_band"] == "MODERATE"
        assert record["decon_mandatory"] is False
        assert record["quarantine_warranted"] is True
        assert order["status"] == "SEALED"
        assert order["band_at_issue"] == "MODERATE"
        assert order["hold_hours_required"] == 48
        assert order["rejected_release_count"] == 0
        assert_instant_equals(order["hold_until"], "2026-08-07T09:00:00Z", "hold_until")

        response = api_client.decide_quarantine_release(
            order["id"], release_decision_payload(outcome),
            make_release_verifier_headers(ctx["inspector_c"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_QUARANTINE_RELEASE_NOT_REQUESTED)
        after = fetch_quarantine_order(order["id"])
        assert after["status"] == "SEALED"
        assert after["release_verified_by_inspector_id"] is None
        assert after["version"] == order["version"]
        station = fetch_station(ctx["station"]["id"])
        assert station["seal_stock_count"] == 2
        assert station["seals_in_circulation_count"] == 1
        assert station["seals_retired_count"] == 0
        assert_seal_inventory_conserved(station)


def _voided_order():
    """Seal a vessel, then void the order with a breach report an hour later."""
    ctx = _sealed_order()
    set_clock("2026-08-05T10:00:00Z")
    ctx["quarantine_order"] = report_breach(ctx["quarantine_order"]["id"])
    return ctx


class TestReleaseRequestOnAVoidedOrderIsRefused:
    """A breach-voided order is dead, and its own issuer cannot revive it."""

    def test_the_breach_void_retires_the_seal_and_clears_the_vessel_hold(self):
        """Voiding forfeits the seal, refers the record and drops the hold.

        PRD: "The side effects are identical from both origins: the station's
        `seals_in_circulation_count` is decremented by 1 and `seals_retired_count`
        incremented by 1, because a breached seal is forfeited rather than
        returned; the vessel's `quarantine_hold_until` is cleared, since a voided
        order is no longer in `SEALED` or `RELEASE_REQUESTED` and therefore holds
        nothing; and the parent record's enforcement dimension is driven
        `NONE → REFERRED` with `referral_reason` set to `SEAL_TAMPER`, but only
        when that record's `enforcement_status` is still `NONE`."

        Design: Corner/state_machines/invalid_transition_release_request_on_voided_order_rejected
        """
        ctx = _voided_order()

        assert ctx["quarantine_order"]["status"] == "VOIDED_BREACH"
        record = fetch_record(ctx["record"]["id"])
        assert record["enforcement_status"] == "REFERRED"
        assert record["referral_reason"] == "SEAL_TAMPER"
        station = fetch_station(ctx["station"]["id"])
        assert station["seal_stock_count"] == 2
        assert station["seals_in_circulation_count"] == 0
        assert station["seals_retired_count"] == 1
        assert_seal_inventory_conserved(station)
        assert fetch_watercraft(ctx["watercraft"]["id"])["quarantine_hold_until"] is None

    def test_the_issuing_inspectors_release_request_is_refused_on_state(self):
        """The 409 names the state even though the hold has not elapsed either.

        PRD: "A request aimed at an order in a state that does not permit it is
        rejected with `ERR_QUARANTINE_NOT_SEALED`."

        Design: Corner/state_machines/invalid_transition_release_request_on_voided_order_rejected
        """
        ctx = _voided_order()
        voided = ctx["quarantine_order"]

        response = api_client.request_quarantine_release(
            voided["id"], release_request_payload(notes="owner asks for release"),
            make_inspector_headers(ctx["inspector_a"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_QUARANTINE_NOT_SEALED)
        after = fetch_quarantine_order(voided["id"])
        assert after["status"] == "VOIDED_BREACH"
        assert after["version"] == voided["version"]

    def test_a_second_breach_report_is_refused(self):
        """The void is terminal, so it is not re-enterable.

        PRD: "Both `RELEASED` and `VOIDED_BREACH` are terminal."

        Design: Corner/state_machines/invalid_transition_release_request_on_voided_order_rejected
        """
        ctx = _voided_order()

        response = api_client.report_quarantine_breach(
            ctx["quarantine_order"]["id"], breach_report_payload(), ENFORCEMENT_OFFICER
        )

        validate_error(response, ApiErrorId.ERR_QUARANTINE_NOT_SEALED)
        station = fetch_station(ctx["station"]["id"])
        assert station["seals_retired_count"] == 1
        assert_seal_inventory_conserved(station)


def _drafted_report():
    """One LIVE_ORGANISM report drafted against a HIGH-risk lake inspection."""
    ctx = setup_inspection(
        arrived_at=ARRIVAL, screen_at=ARRIVAL, mandatory_inspection=True,
        residual_water_present=True, standing_water_ml=500,
    )
    ctx["detection_report"] = draft_detection_report(
        ctx["record"]["id"], ctx["inspector_a"]["id"], "LIVE_ORGANISM",
        species_code="DREISSENA_POLYMORPHA", observed_at="2026-08-05T09:05:00Z",
    )
    return ctx


class TestAcknowledgingADraftReportIsRefused:
    """The state database can only rule on a SUBMITTED report."""

    def test_accepting_a_draft_report_is_refused_and_starts_no_cascade(self):
        """The water body's counters and the station's posting are untouched.

        PRD: "The report must be in `SUBMITTED`, or the call is
        `ERR_REPORT_INVALID_STATE`, and the acknowledging steward may not be the
        inspector who filed the report — a collision is
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/state_machines/invalid_transition_acknowledging_a_draft_report_rejected
        """
        ctx = _drafted_report()
        report = ctx["detection_report"]
        assert report["status"] == "DRAFT"
        assert report["submission_count"] == 0
        assert report["water_body_id"] == ctx["water_body"]["id"]

        response = api_client.acknowledge_detection_report(
            report["id"], acknowledgement_payload("ACCEPTED", state_db_ack_id="ACK-1"),
            STATE_DATA_STEWARD,
        )

        validate_error(response, ApiErrorId.ERR_REPORT_INVALID_STATE)
        after = fetch_detection_report(report["id"])
        assert after["status"] == "DRAFT"
        assert after["state_db_ack_id"] is None
        assert after["version"] == report["version"]
        water_body = fetch_water_body(ctx["water_body"]["id"])
        assert water_body["detection_count"] == 0
        assert water_body["live_detection_count"] == 0
        assert water_body["infestation_status"] == "CLEAN"
        assert fetch_station(ctx["station"]["id"])["mandatory_inspection"] is True

    def test_rejecting_a_draft_report_is_refused_with_the_same_error(self):
        """A REJECTED verdict on a DRAFT is equally out of order.

        PRD: "The report must be in `SUBMITTED`, or the call is
        `ERR_REPORT_INVALID_STATE`, and the acknowledging steward may not be the
        inspector who filed the report — a collision is
        `ERR_SEGREGATION_OF_DUTIES`."  PRD: "A `REJECTED` verdict is the cheap
        case: it sets `status` to `REJECTED`, stores the supplied
        `rejection_reason`, touches no water body counter whatsoever, and
        advances the report's `version` by 1."

        Design: Corner/state_machines/invalid_transition_acknowledging_a_draft_report_rejected
        """
        ctx = _drafted_report()

        response = api_client.acknowledge_detection_report(
            ctx["detection_report"]["id"],
            acknowledgement_payload("REJECTED", rejection_reason="insufficient photos"),
            STATE_DATA_STEWARD,
        )

        validate_error(response, ApiErrorId.ERR_REPORT_INVALID_STATE)
        assert fetch_detection_report(ctx["detection_report"]["id"])["status"] == "DRAFT"
        assert fetch_water_body(ctx["water_body"]["id"])["detection_count"] == 0


def _planned_campaign():
    """A never-launched campaign whose window has already closed."""
    set_clock("2026-08-01T00:00:00Z")
    water_body = create_water_body(risk_tier="HIGH")
    station = create_station(
        name="Polson Access", water_body_id=water_body["id"], mandatory_inspection=True
    )
    campaign = plan_campaign(
        water_body["id"], "2026-08-01T00:00:00Z", "2026-08-31T00:00:00Z", 100000,
        name="Clean Drain Dry 2026", evaluation_method="PRE_POST",
    )
    set_clock("2026-09-01T00:00:00Z")
    return {"water_body": water_body, "station": station, "campaign": campaign}


class TestEvaluatingAPlannedCampaignIsRefused:
    """Evaluation leaves RUNNING only, and the state gate precedes the window gate."""

    def test_evaluating_a_campaign_that_never_launched_is_refused(self):
        """Past end_at the 409 still names the state, not the window.

        PRD: "`ERR_INVALID_CAMPAIGN_STATE` when a campaign transition is not
        declared from its current status, evaluation of a campaign that is not
        running included."

        Design: Corner/state_machines/invalid_transition_evaluating_a_planned_campaign_rejected
        """
        ctx = _planned_campaign()
        campaign = ctx["campaign"]
        assert campaign["status"] == "PLANNED"
        assert campaign["station_allocations"] == []

        response = api_client.evaluate_campaign(
            campaign["id"], campaign_evaluation_payload(impressions=5000), PROGRAM_ADMIN
        )

        validate_error(response, ApiErrorId.ERR_INVALID_CAMPAIGN_STATE)
        after = fetch_campaign(campaign["id"])
        assert after["status"] == "PLANNED"
        assert after["effectiveness_score"] is None
        assert after["alternate_effectiveness_score"] is None
        assert after["version"] == campaign["version"]
        assert fetch_station(ctx["station"]["id"])["campaign_allocated_cents"] == 0

    def test_cancelling_the_planned_campaign_is_the_one_move_left(self):
        """PLANNED -> CANCELLED is accepted and touches no station.

        PRD: "`PLANNED → CANCELLED` touches no station at all, because nothing
        was ever allocated; it merely sets `status` to `CANCELLED` and advances
        the campaign's `version` by 1."

        Design: Corner/state_machines/invalid_transition_evaluating_a_planned_campaign_rejected
        """
        ctx = _planned_campaign()

        data = validate_success(
            api_client.set_campaign_status(
                ctx["campaign"]["id"], campaign_status_payload("CANCELLED"), PROGRAM_ADMIN
            ),
            200,
        )

        assert data["status"] == "CANCELLED"
        assert data["station_allocations"] == []
        assert data["version"] == ctx["campaign"]["version"] + 1
        assert fetch_station(ctx["station"]["id"])["campaign_allocated_cents"] == 0


def _active_level_one_inspector():
    """One 8-hour passed module at 2026-08-01Z, read back at 2026-08-05T09:00Z."""
    set_clock("2026-08-01T00:00:00Z")
    water_body = create_water_body(risk_tier="HIGH")
    station = create_station(name="Polson Access", water_body_id=water_body["id"])
    inspector = enroll_inspector(
        station["id"], credited_hours=8, completed_at="2026-08-01T00:00:00Z",
        full_name="Ada Field",
    )
    set_clock(ARRIVAL)
    return inspector


class TestReactivatingAnActiveInspectorIsRefused:
    """ACTIVE is reachable from SUSPENDED or EXPIRED, never from ACTIVE."""

    def test_re_activating_an_active_inspector_does_not_renew_the_certification(self):
        """The 409 leaves certification_expires_at at its original stamp.

        PRD: "An inspector transition that is not declared from the inspector's
        current standing is rejected with `ERR_INVALID_INSPECTOR_STATE`."

        Design: Corner/state_machines/invalid_transition_activating_an_already_active_inspector_rejected
        """
        inspector = _active_level_one_inspector()
        assert inspector["status"] == "ACTIVE"
        assert inspector["certification_level"] == "LEVEL_1"
        assert float(inspector["training_hours_total"]) == 8.00
        assert_instant_equals(
            inspector["certification_expires_at"], "2027-08-01T00:00:00Z",
            "certification_expires_at",
        )

        response = api_client.set_inspector_status(
            inspector["id"],
            inspector_status_payload("ACTIVE", reason="double-activation attempt"),
            PROGRAM_ADMIN,
        )

        validate_error(response, ApiErrorId.ERR_INVALID_INSPECTOR_STATE)
        after = fetch_inspector(inspector["id"])
        assert after["status"] == "ACTIVE"
        assert_instant_equals(
            after["certification_expires_at"], "2027-08-01T00:00:00Z",
            "certification_expires_at",
        )
        assert after["version"] == inspector["version"]

    def test_the_suspend_and_reinstate_loop_is_still_open(self):
        """SUSPENDED then ACTIVE both return 200 — the machine has no terminal state.

        PRD: "Reinstatement `SUSPENDED → ACTIVE` requires two things: the
        inspector's `certification_level` must not be `TRAINEE`, and the current
        logical time must be strictly before their `certification_expires_at`."

        Design: Corner/state_machines/invalid_transition_activating_an_already_active_inspector_rejected
        """
        inspector = _active_level_one_inspector()

        suspended = validate_success(
            api_client.set_inspector_status(
                inspector["id"], inspector_status_payload("SUSPENDED", reason="review"),
                PROGRAM_ADMIN,
            ),
            200,
        )
        assert suspended["status"] == "SUSPENDED"

        reinstated = validate_success(
            api_client.set_inspector_status(
                inspector["id"], inspector_status_payload("ACTIVE"), PROGRAM_ADMIN
            ),
            200,
        )
        assert reinstated["status"] == "ACTIVE"
        assert reinstated["version"] == suspended["version"] + 1


class TestSuspendReopenCycleDoesNotReseedSealStock:
    """OPEN -> SUSPENDED -> OPEN restores intake without re-seeding the seal shelf."""

    def test_the_second_opening_leaves_the_consumed_seal_consumed(self):
        """Stock stays 2 with 1 in circulation, never back at 3.

        PRD: "`seal_stock_count` is set equal to `seal_stock_initial_count` — the
        same initialisation is applied again at the moment the station first
        leaves `PLANNED`, so the two are always consistent — while
        `seals_in_circulation_count`, `seals_retired_count`,
        `certified_inspector_count`, `collected_fees_cents`,
        `refunded_fees_cents` and `campaign_allocated_cents` all start at 0."

        Design: Corner/state_machines/cyclic_station_suspend_reopen_does_not_reseed_seal_stock
        """
        ctx = _sealed_order()
        station_id = ctx["station"]["id"]
        sealed = fetch_station(station_id)
        assert sealed["seal_stock_count"] == 2
        assert sealed["seals_in_circulation_count"] == 1
        suspended = move_station(station_id, "SUSPENDED")
        assert suspended["status"] == "SUSPENDED"

        data = validate_success(
            api_client.set_station_status(
                station_id, station_status_payload("OPEN", reason="smoke cleared"),
                PROGRAM_ADMIN,
            ),
            200,
        )

        assert data["status"] == "OPEN"
        assert data["version"] == suspended["version"] + 1
        assert data["seal_stock_count"] == 2
        assert data["seals_in_circulation_count"] == 1
        assert data["seals_retired_count"] == 0
        assert data["seal_stock_initial_count"] == 3
        assert_seal_inventory_conserved(data)

    def test_suspension_blocks_new_intake_and_reopening_restores_it(self):
        """The same record creation is a 409 while SUSPENDED and a 201 after reopening.

        PRD: "From `OPEN` the station may go to `SUSPENDED`, and from `SUSPENDED`
        back to `OPEN`, each transition advancing `version` by 1; the pair forms
        the operating cycle `OPEN → SUSPENDED → OPEN` and a station may be
        suspended and resumed any number of times. Suspension blocks the opening
        of new inspections at that station but leaves in-flight records and their
        decontamination orders entirely alone."

        Design: Corner/state_machines/cyclic_station_suspend_reopen_does_not_reseed_seal_stock
        """
        ctx = _sealed_order()
        station_id = ctx["station"]["id"]
        quarantine_order_id = ctx["quarantine_order"]["id"]
        next_vessel = add_watercraft(ctx)
        move_station(station_id, "SUSPENDED")
        payload = inspection_record_payload(station_id, next_vessel["id"], ARRIVAL)
        headers = make_inspector_headers(ctx["inspector_a"]["id"])

        blocked = api_client.create_inspection_record(payload, headers)

        validate_error(blocked, ApiErrorId.ERR_STATION_NOT_OPEN)
        assert fetch_quarantine_order(quarantine_order_id)["status"] == "SEALED"

        move_station(station_id, "OPEN")
        reopened = validate_success(
            api_client.create_inspection_record(payload, headers), 201
        )

        assert reopened["inspection_status"] == "INITIATED"
        assert reopened["station_id"] == station_id
        assert fetch_quarantine_order(quarantine_order_id)["status"] == "SEALED"


def _screened_clean_record():
    """A LOW-band clean, dry screening: score 5 and no decontamination owed."""
    return setup_inspection(
        risk_tier="LOW", infestation_status="CLEAN", mandatory_inspection=True,
        arrived_at=ARRIVAL, screen_at=ARRIVAL, residual_water_present=False,
    )


class TestRefusalBooksAFeeAReferralAndAStrike:
    """One REFUSE disposition fires three side effects in a single response."""

    def test_the_refusal_response_carries_both_dimensions_and_the_full_fee(self):
        """REFUSED and REFERRED arrive together with 2500 cents still billed.

        PRD: "`SCREENED → REFUSED` records a boater who declined to be inspected
        — the situation the program's mandatory-inspection posting exists to
        address — and it does more than close the inspection: it immediately
        drives the record's enforcement dimension from `NONE` to `REFERRED` with
        `referral_reason` set to `INSPECTION_REFUSAL`, acting as the system rather
        than as a named officer, and with it the full strike cascade onto the
        vessel described later in this subsection."  PRD: "A refused inspection
        is still a billable inspection."

        Design: Corner/state_machines/side_effect_execution_refusal_books_a_fee_a_referral_and_a_strike
        """
        ctx = _screened_clean_record()
        record = ctx["record"]
        assert record["inspection_status"] == "SCREENED"
        assert record["risk_score"] == 5
        assert record["risk_band"] == "LOW"
        assert record["decon_mandatory"] is False

        data = validate_success(
            api_client.dispose_inspection_record(
                record["id"],
                disposition_payload("REFUSE", notes="boater declined inspection"),
                make_inspector_headers(ctx["inspector_a"]["id"]),
            ),
            200,
        )

        assert_inspection_record(data)
        assert data["inspection_status"] == "REFUSED"
        assert data["enforcement_status"] == "REFERRED"
        assert data["referral_reason"] == "INSPECTION_REFUSAL"
        assert data["inspection_fee_cents"] == 2500
        assert data["decon_fee_cents"] == 0
        assert data["surcharge_cents"] == 0
        assert data["total_fee_cents"] == 2500
        assert data["penalty_cents"] == 0
        assert data["version"] == record["version"] + 1

    def test_the_refusal_debits_the_station_ledger_and_strikes_the_vessel(self):
        """The station banks 2500 cents and the vessel takes its first strike.

        PRD: "The referral then cascades onto the vessel in three linked hops:
        the vessel's `compliance_strikes` is incremented by 1; because of that
        increment, `watchlist_status` flips from `CLEAR` to `WATCHLISTED` once
        `compliance_strikes` has reached 2; and because of that flip,
        `mandatory_decon_flag` is set true."

        Design: Corner/state_machines/side_effect_execution_refusal_books_a_fee_a_referral_and_a_strike
        """
        ctx = _screened_clean_record()

        validate_success(
            api_client.dispose_inspection_record(
                ctx["record"]["id"], disposition_payload("REFUSE"),
                make_inspector_headers(ctx["inspector_a"]["id"]),
            ),
            200,
        )

        assert fetch_station(ctx["station"]["id"])["collected_fees_cents"] == 2500
        watercraft = fetch_watercraft(ctx["watercraft"]["id"])
        assert_strike_posture(watercraft, 1)
        assert watercraft["watchlist_status"] == "CLEAR"
        assert watercraft["mandatory_decon_flag"] is False


def _record_with_two_orders():
    """A HIGH-band record carrying two decontamination orders, A then B."""
    ctx = setup_decon_required(arrived_at=ARRIVAL, screen_at=ARRIVAL)
    ctx["rec_v1"] = ctx["record"]["version"]
    ctx["order_a"] = order_decon(
        ctx["record"]["id"], ctx["inspector_a"]["id"], ctx["rec_v1"]
    )
    ctx["rec_v2"] = fetch_record(ctx["record"]["id"])["version"]
    ctx["order_b"] = order_decon(
        ctx["record"]["id"], ctx["inspector_a"]["id"], ctx["rec_v2"]
    )
    return ctx


class TestAbandoningASecondOrderSkipsTheRecordCascade:
    """The parent cascade is skipped once the record has left DECON_REQUIRED."""

    def test_the_sibling_verification_completes_the_record_first(self):
        """Order A's VERIFIED moves the record on and stamps the vessel.

        PRD: "`TREATED → VERIFIED` sets the order's `status` to `VERIFIED` and
        `verified_by_inspector_id` from `X-User-ID`, and then cascades twice. The
        parent record moves `DECON_REQUIRED → DECON_COMPLETED`, and that record
        transition in turn stamps the vessel's `last_decon_verified_at` at the
        current logical time and clears the vessel's `mandatory_decon_flag`."

        Design: Corner/state_machines/conditional_cascade_abandoning_a_second_order_skips_the_record_cascade
        """
        ctx = _record_with_two_orders()
        assert ctx["record"]["risk_score"] == 65
        assert ctx["rec_v2"] == ctx["rec_v1"] + 1
        set_clock(ARRIVAL)
        treat_order(ctx["order_a"]["id"], ctx["inspector_b"]["id"])
        set_clock("2026-08-06T04:00:00Z")

        order = verify_dry(ctx["order_a"]["id"], ctx["inspector_c"]["id"], "VERIFIED")

        assert order["status"] == "VERIFIED"
        assert fetch_record(ctx["record"]["id"])["inspection_status"] == "DECON_COMPLETED"
        watercraft = fetch_watercraft(ctx["watercraft"]["id"])
        assert_instant_equals(
            watercraft["last_decon_verified_at"], "2026-08-06T04:00:00Z",
            "last_decon_verified_at",
        )
        assert watercraft["mandatory_decon_flag"] is False

    def test_abandoning_the_superseded_order_refunds_nothing(self):
        """Order B reaches ABANDONED while the record stays DECON_COMPLETED.

        PRD: "Because a record awaiting decontamination may carry more than one
        order, the parent-record cascade fires from whichever order the call
        targets, and it is **skipped outright** when the parent record has already
        left `DECON_REQUIRED` — the decontamination order's own transition still
        completes normally in that case. A second, superseded order can therefore
        be verified or abandoned after the record has already been completed by
        its sibling, without disturbing the record."

        Design: Corner/state_machines/conditional_cascade_abandoning_a_second_order_skips_the_record_cascade
        """
        ctx = _record_with_two_orders()
        set_clock(ARRIVAL)
        treat_order(ctx["order_a"]["id"], ctx["inspector_b"]["id"])
        set_clock("2026-08-06T04:00:00Z")
        verify_dry(ctx["order_a"]["id"], ctx["inspector_c"]["id"], "VERIFIED")
        treated_b = treat_order(ctx["order_b"]["id"], ctx["inspector_b"]["id"])
        assert treated_b["status"] == "TREATED"
        assert fetch_record(ctx["record"]["id"])["decon_fee_cents"] == 900

        data = validate_success(
            api_client.verify_decon_dry_time(
                ctx["order_b"]["id"],
                dry_verification_payload("ABANDON", notes="owner walked away"),
                make_release_verifier_headers(ctx["inspector_c"]["id"]),
            ),
            200,
        )

        assert data["status"] == "ABANDONED"
        assert data["verified_by_inspector_id"] == ctx["inspector_c"]["id"]
        record = fetch_record(ctx["record"]["id"])
        assert record["inspection_status"] == "DECON_COMPLETED"
        assert record["fee_refunded_cents"] == 0
        assert record["total_fee_cents"] == 3400
        station = fetch_station(ctx["station"]["id"])
        assert station["collected_fees_cents"] == 3400
        assert station["refunded_fees_cents"] == 0
        assert fetch_decon_order(ctx["order_a"]["id"])["status"] == "VERIFIED"
