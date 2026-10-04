"""Vessel nomination, berth acceptance, arrival sequence, and berth windows."""
import pytest

from test_helpers import (
    CM,
    MS,
    OP,
    ApiErrorId,
    add_cargo_slot,
    begin_turnaround_at,
    create_berth_payload,
    create_commercial_train,
    create_confirmed_adp_with_slots,
    create_customer,
    create_draft_adp,
    create_spa_payload,
    create_vessel_nomination_payload,
    get_success_data,
    make_customer_rep_headers,
    nominate_vessel_call,
    propose_and_approve_turnaround,
    setup_departed_call,
    setup_nominated_call,
    validate_error,
    validate_success,
)


class TestVesselNominationGating:
    def test_vessel_nomination_requires_confirmed_adp(self, api):
        """PRD §3.4: "When the owning ADP is `CONFIRMED` or `LOCKED`, the buyer's
        `CustomerRep` nominates a vessel against a `SCHEDULED` slot"."

        Design: Difficulty/cross_entity_state_dependency/vessel_nomination_requires_confirmed_adp
        """
        # Build an ADP that is PROPOSED but never confirmed.
        customer = create_customer(legal_name="Nu Bulk Energy")
        create_commercial_train()
        spa = get_success_data(
            api.create_spa(create_spa_payload(customer["id"]), CM)
        )
        spa = get_success_data(api.commence_spa_deliveries(spa["id"], CM))
        adp = create_draft_adp(spa["id"], spa["version"])
        slot = add_cargo_slot(
            adp["id"],
            window_start="2027-01-10T00:00:00Z",
            window_end="2027-01-17T00:00:00Z",
        )
        get_success_data(api.propose_adp(adp["id"], CM))
        resp = api.nominate_vessel(
            slot["id"],
            create_vessel_nomination_payload(slot["version"]),
            make_customer_rep_headers(customer["id"]),
        )
        err = validate_error(resp, ApiErrorId.ERR_ADP_INVALID_STATE.value)
        assert err["error_id"] == "ERR_ADP_INVALID_STATE"

    def test_vessel_nomination_on_proposed_adp_leaves_slot_scheduled(self, api):
        """PRD §3.4: "When the owning ADP is `CONFIRMED` or `LOCKED`, the buyer's
        `CustomerRep` nominates a vessel against a `SCHEDULED` slot, supplying
        `vessel_name`, `imo_number`, `vessel_loa_m`, `vessel_dwt_t`, the contract
        `demurrage_rate_usd_per_day` (greater than zero), and
        `expected_cargo_slot_version` per §2.8. This creates a `VesselCall` in
        `NOMINATED` linked to the slot and moves the slot's `lift_status` from
        `SCHEDULED` to `VESSEL_NOMINATED`, incrementing the slot's `version`."

        Design: Difficulty/cross_entity_state_dependency/vessel_nomination_requires_confirmed_adp
        """
        customer = create_customer(legal_name="Nu Bulk Energy")
        create_commercial_train()
        spa = get_success_data(api.create_spa(create_spa_payload(customer["id"]), CM))
        spa = get_success_data(api.commence_spa_deliveries(spa["id"], CM))
        adp = create_draft_adp(spa["id"], spa["version"])
        slot = add_cargo_slot(
            adp["id"],
            window_start="2027-01-10T00:00:00Z",
            window_end="2027-01-17T00:00:00Z",
        )
        get_success_data(api.propose_adp(adp["id"], CM))
        resp = api.nominate_vessel(
            slot["id"],
            create_vessel_nomination_payload(slot["version"]),
            make_customer_rep_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ADP_INVALID_STATE.value)
        slot_after = get_success_data(api.get_cargo_slot(slot["id"], CM))
        assert slot_after["lift_status"] == "SCHEDULED", (
            f"rejected nomination must leave the slot SCHEDULED, got "
            f"{slot_after['lift_status']}"
        )

    def test_occ_stale_vessel_nomination_version(self, api):
        """PRD §2.8: "creating a vessel nomination against a cargo slot requires
        the request to carry `expected_cargo_slot_version` matching the cargo
        slot's current `version`. A nomination legitimately supersedes a prior
        `NOMINATED` vessel call, so a request carrying a stale expected version
        must fail rather than supersede a call the client never saw."
        PRD §2.8: "the version-check failure, when it occurs, carries HTTP status
        412 and the error id `ERR_STALE_VERSION`."

        Design: Corner/cross_cutting_layers/occ_stale_vessel_nomination_version
        """
        ctx = setup_nominated_call(
            slot_spec={
                "window_start": "2027-01-10T00:00:00Z",
                "window_end": "2027-01-17T00:00:00Z",
            }
        )
        slot = ctx["slot"]
        call1 = ctx["call"]
        assert call1["status"] == "NOMINATED"
        # second nomination replaying the now-stale captured version
        resp = api.nominate_vessel(
            slot["id"],
            create_vessel_nomination_payload(
                slot["version"],
                vessel_name="Gas Second",
                imo_number="9111002",
                demurrage_rate_usd_per_day=90000,
            ),
            ctx["rep"],
        )
        err = validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
        assert err["error_id"] == "ERR_STALE_VERSION"
        assert resp.status_code == 412

    def test_occ_expression_stale_minus_one(self, api):
        """PRD §2.8: "creating a vessel nomination against a cargo slot requires
        the request to carry `expected_cargo_slot_version` matching the cargo
        slot's current `version`." PRD §2.8: "the version-check failure, when it
        occurs, carries HTTP status 412 and the error id `ERR_STALE_VERSION`."

        Design: Corner/cross_cutting_layers/occ_expression_stale_minus_one
        """
        ctx = create_confirmed_adp_with_slots(
            [
                {
                    "window_start": "2027-01-10T00:00:00Z",
                    "window_end": "2027-01-17T00:00:00Z",
                }
            ]
        )
        slot = get_success_data(api.get_cargo_slot(ctx["slots"][0]["id"], ctx["rep"]))
        stale_version = slot["version"] - 1
        resp = api.nominate_vessel(
            slot["id"],
            create_vessel_nomination_payload(stale_version),
            ctx["rep"],
        )
        err = validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
        assert err["error_id"] == "ERR_STALE_VERSION"
        assert resp.status_code == 412
        slot_after = get_success_data(api.get_cargo_slot(slot["id"], CM))
        assert slot_after["lift_status"] == "SCHEDULED"

    def test_cancelled_slot_nomination_rejected(self, api):
        """PRD §3.4: "Nominating against a `CANCELLED` or `LOADED` slot is rejected
        with `ERR_SLOT_INVALID_STATE`."

        Design: Corner/state_machines/cancelled_slot_nomination_rejected
        """
        ctx = create_confirmed_adp_with_slots(
            [{"quantity_mmbtu": 3600000}]
        )
        slot = ctx["slots"][0]
        get_success_data(api.set_clock("2027-04-15T00:00:00Z", OP))
        get_success_data(api.cancel_cargo_slot(slot["id"], ctx["rep"]))
        slot_after = get_success_data(api.get_cargo_slot(slot["id"], ctx["rep"]))
        assert slot_after["lift_status"] == "CANCELLED"
        resp = api.nominate_vessel(
            slot["id"],
            create_vessel_nomination_payload(slot_after["version"]),
            ctx["rep"],
        )
        err = validate_error(resp, ApiErrorId.ERR_SLOT_INVALID_STATE.value)
        assert err["error_id"] == "ERR_SLOT_INVALID_STATE"
        slot_after = get_success_data(api.get_cargo_slot(slot["id"], CM))
        assert slot_after["lift_status"] == "CANCELLED"


class TestBerthAcceptance:
    def test_berth_window_changeover_buffer_overlap(self, api):
        """PRD §3.4: "The assigned window must lie within the cargo slot's
        flexibility window and must not conflict with any other accepted-or-later
        call on the same berth under the berth-window overlap rule of §3.5, with
        conflicts rejected as `ERR_BERTH_WINDOW_OVERLAP`." PRD §5:
        "`ERR_BERTH_WINDOW_OVERLAP` ... (half-open windows, 2h changeover buffer)".

        Design: Difficulty/resource_temporal_overlap/berth_window_changeover_buffer_overlap
        """
        # Three slots on one confirmed ADP, three nominated calls, one berth.
        ctx = create_confirmed_adp_with_slots(
            [
                {
                    "window_start": "2027-01-10T00:00:00Z",
                    "window_end": "2027-01-20T00:00:00Z",
                },
                {
                    "window_start": "2027-01-10T00:00:00Z",
                    "window_end": "2027-01-20T00:00:00Z",
                },
                {
                    "window_start": "2027-01-10T00:00:00Z",
                    "window_end": "2027-01-20T00:00:00Z",
                },
            ]
        )
        berth = get_success_data(
            api.create_berth(create_berth_payload(), OP)
        )
        calls = []
        for slot in ctx["slots"]:
            slot = get_success_data(api.get_cargo_slot(slot["id"], ctx["rep"]))
            calls.append(nominate_vessel_call(slot, ctx["rep"]))
        get_success_data(
            api.accept_vessel_call(
                calls[0]["id"],
                {
                    "berth_id": berth["id"],
                    "window_start": "2027-01-12T00:00:00Z",
                    "window_end": "2027-01-14T00:00:00Z",
                },
                MS,
            )
        )
        # 1h changeover gap (01-14T01:00) — rejected
        resp = api.accept_vessel_call(
            calls[1]["id"],
            {
                "berth_id": berth["id"],
                "window_start": "2027-01-14T01:00:00Z",
                "window_end": "2027-01-15T01:00:00Z",
            },
            MS,
        )
        err = validate_error(resp, ApiErrorId.ERR_BERTH_WINDOW_OVERLAP.value)
        assert err["error_id"] == "ERR_BERTH_WINDOW_OVERLAP"

        # exactly 2h changeover gap (01-14T02:00) — accepted
        call3 = get_success_data(
            api.accept_vessel_call(
                calls[2]["id"],
                {
                    "berth_id": berth["id"],
                    "window_start": "2027-01-14T02:00:00Z",
                    "window_end": "2027-01-15T02:00:00Z",
                },
                MS,
            )
        )
        assert call3["status"] == "ACCEPTED", (
            f"a 2h changeover gap must be accepted, got {call3['status']}"
        )

    def test_berth_window_exact_2h_gap_accepted(self, api):
        """PRD §3.4: "The assigned window must lie within the cargo slot's
        flexibility window and must not conflict with any other accepted-or-later
        call on the same berth under the berth-window overlap rule of §3.5, with
        conflicts rejected as `ERR_BERTH_WINDOW_OVERLAP`." PRD §5:
        "`ERR_BERTH_WINDOW_OVERLAP` ... (half-open windows, 2h changeover buffer)".

        Design: Difficulty/resource_temporal_overlap/berth_window_changeover_buffer_overlap
        """
        ctx = create_confirmed_adp_with_slots(
            [
                {
                    "window_start": "2027-01-10T00:00:00Z",
                    "window_end": "2027-01-20T00:00:00Z",
                },
                {
                    "window_start": "2027-01-10T00:00:00Z",
                    "window_end": "2027-01-20T00:00:00Z",
                },
            ]
        )
        berth = get_success_data(api.create_berth(create_berth_payload(), OP))
        slot1 = get_success_data(api.get_cargo_slot(ctx["slots"][0]["id"], ctx["rep"]))
        slot2 = get_success_data(api.get_cargo_slot(ctx["slots"][1]["id"], ctx["rep"]))
        call1 = nominate_vessel_call(slot1, ctx["rep"])
        call2 = nominate_vessel_call(slot2, ctx["rep"])
        get_success_data(
            api.accept_vessel_call(
                call1["id"],
                {
                    "berth_id": berth["id"],
                    "window_start": "2027-01-12T00:00:00Z",
                    "window_end": "2027-01-14T00:00:00Z",
                },
                MS,
            )
        )
        call2 = get_success_data(
            api.accept_vessel_call(
                call2["id"],
                {
                    "berth_id": berth["id"],
                    "window_start": "2027-01-14T02:00:00Z",
                    "window_end": "2027-01-15T02:00:00Z",
                },
                MS,
            )
        )
        assert call2["status"] == "ACCEPTED"

    def test_safety_beats_temporal_on_berth_accept(self, api):
        """PRD §2.9: "the system evaluates them in a fixed order so that the
        surfaced error is deterministic: ... then business checks in their declared
        sequence — physical safety compatibility, berth-window overlap, turnaround
        interval overlap, cancellation-notice sufficiency, ...". (The declared
        sequence places physical safety compatibility ahead of berth-window
        overlap, so an oversized vessel whose window also collides surfaces the
        compatibility error.)
        PRD §3.4: "The vessel must physically fit: its `vessel_loa_m` must not
        exceed the berth's `max_loa_m` and its `vessel_dwt_t` must not exceed the
        berth's `max_dwt_t`, with violations rejected as
        `ERR_VESSEL_BERTH_INCOMPATIBLE`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_berth_accept
        """
        ctx = create_confirmed_adp_with_slots(
            [
                {
                    "window_start": "2027-01-10T00:00:00Z",
                    "window_end": "2027-01-17T00:00:00Z",
                },
                {
                    "window_start": "2027-01-10T00:00:00Z",
                    "window_end": "2027-01-17T00:00:00Z",
                },
            ]
        )
        berth = get_success_data(api.create_berth(create_berth_payload(), OP))
        slot1 = get_success_data(api.get_cargo_slot(ctx["slots"][0]["id"], ctx["rep"]))
        slot2 = get_success_data(api.get_cargo_slot(ctx["slots"][1]["id"], ctx["rep"]))
        call1 = nominate_vessel_call(slot1, ctx["rep"])
        get_success_data(
            api.accept_vessel_call(
                call1["id"],
                {
                    "berth_id": berth["id"],
                    "window_start": "2027-01-12T00:00:00Z",
                    "window_end": "2027-01-14T00:00:00Z",
                },
                MS,
            )
        )
        # oversized vessel (LOA 330 > berth max 320) AND an overlapping window
        call2 = nominate_vessel_call(
            slot2,
            ctx["rep"],
            vessel_name="Oversize Carrier",
            imo_number="9111002",
            vessel_loa_m=330,
            vessel_dwt_t=100000,
            demurrage_rate_usd_per_day=90000,
        )
        resp = api.accept_vessel_call(
            call2["id"],
            {
                "berth_id": berth["id"],
                "window_start": "2027-01-13T00:00:00Z",
                "window_end": "2027-01-15T00:00:00Z",
            },
            MS,
        )
        err = validate_error(resp, ApiErrorId.ERR_VESSEL_BERTH_INCOMPATIBLE.value)
        assert err["error_id"] == "ERR_VESSEL_BERTH_INCOMPATIBLE"
        call2_after = get_success_data(api.get_vessel_call(call2["id"], MS))
        assert call2_after["status"] == "NOMINATED"

    def test_oversized_vessel_rejected_on_free_berth(self, api):
        """PRD §3.4: "The vessel must physically fit: its `vessel_loa_m` must not
        exceed the berth's `max_loa_m` and its `vessel_dwt_t` must not exceed the
        berth's `max_dwt_t`, with violations rejected as
        `ERR_VESSEL_BERTH_INCOMPATIBLE`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_berth_accept
        """
        ctx = setup_nominated_call(
            slot_spec={
                "window_start": "2027-01-10T00:00:00Z",
                "window_end": "2027-01-17T00:00:00Z",
            }
        )
        # re-nominate with an oversized vessel (the first call is superseded)
        slot = get_success_data(api.get_cargo_slot(ctx["slot"]["id"], ctx["rep"]))
        call2 = nominate_vessel_call(
            slot,
            ctx["rep"],
            vessel_name="Oversize Carrier",
            imo_number="9111002",
            vessel_loa_m=330,
            vessel_dwt_t=100000,
        )
        resp = api.accept_vessel_call(
            call2["id"],
            {
                "berth_id": ctx["berth"]["id"],
                "window_start": "2027-01-12T00:00:00Z",
                "window_end": "2027-01-14T00:00:00Z",
            },
            MS,
        )
        err = validate_error(resp, ApiErrorId.ERR_VESSEL_BERTH_INCOMPATIBLE.value)
        assert err["error_id"] == "ERR_VESSEL_BERTH_INCOMPATIBLE"

    def test_berth_accept_while_out_of_service_rejected(self, api):
        """PRD §3.4: "The berth must exist and be `IN_SERVICE` — a berth knocked
        out by a turnaround in progress yields `ERR_BERTH_NOT_SERVICEABLE`."
        PRD §2.10: "While any maintenance turnaround on any train is in progress,
        every berth is taken `OUT_OF_SERVICE` and every pipeline enters `OUTAGE`".

        Design: Corner/validations/berth_accept_while_out_of_service_rejected
        """
        ctx = create_confirmed_adp_with_slots([{"quantity_mmbtu": 3600000}])
        berth = get_success_data(api.create_berth(create_berth_payload(), OP))
        # The fixture's commercial train is in COMMERCIAL_OPERATION; propose a
        # turnaround on it via a train we control explicitly.
        train = create_commercial_train()
        ta = propose_and_approve_turnaround(
            train["id"],
            "2027-03-01",
            "2027-03-05",
        )
        begin_turnaround_at(ta["id"], "2027-03-01T00:00:00Z")
        # slot window is June, so it is NOT shifted; nominate after the begin
        slot = get_success_data(api.get_cargo_slot(ctx["slots"][0]["id"], ctx["rep"]))
        call = nominate_vessel_call(slot, ctx["rep"])
        resp = api.accept_vessel_call(
            call["id"],
            {
                "berth_id": berth["id"],
                "window_start": "2027-06-02T00:00:00Z",
                "window_end": "2027-06-04T00:00:00Z",
            },
            MS,
        )
        err = validate_error(resp, ApiErrorId.ERR_BERTH_NOT_SERVICEABLE.value)
        assert err["error_id"] == "ERR_BERTH_NOT_SERVICEABLE"
        call_after = get_success_data(api.get_vessel_call(call["id"], MS))
        assert call_after["status"] == "NOMINATED"

    def test_gas_scheduler_cannot_accept_vessel_call(self, api):
        """PRD §2.1: "A request whose role is not listed for the target endpoint is
        rejected with `ERR_FORBIDDEN` (HTTP 403)." PRD §4: POST
        `/api/vessel-calls/{id}/accept` is listed for `MarineScheduler`.

        Design: Corner/rbac/gas_scheduler_cannot_accept_vessel_call
        """
        ctx = setup_nominated_call(
            slot_spec={
                "window_start": "2027-01-10T00:00:00Z",
                "window_end": "2027-01-17T00:00:00Z",
            }
        )
        from test_helpers import GS

        resp = api.accept_vessel_call(
            ctx["call"]["id"],
            {
                "berth_id": ctx["berth"]["id"],
                "window_start": "2027-01-12T00:00:00Z",
                "window_end": "2027-01-14T00:00:00Z",
            },
            GS,
        )
        err = validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
        assert err["error_id"] == "ERR_FORBIDDEN"
        call = get_success_data(api.get_vessel_call(ctx["call"]["id"], MS))
        assert call["status"] == "NOMINATED"


class TestArrivalSequence:
    def test_vessel_call_depart_before_berth_rejected(self, api):
        """PRD §3.4: "Attempting any of these out of order — berthing before NOR,
        departing before berthed — is rejected with `ERR_CALL_INVALID_STATE`."

        Design: Corner/state_machines/vessel_call_depart_before_berth_rejected
        """
        ctx = setup_nominated_call(
            slot_spec={
                "window_start": "2027-01-10T00:00:00Z",
                "window_end": "2027-01-17T00:00:00Z",
            }
        )
        resp = api.depart_vessel_call(ctx["call"]["id"], MS)
        err = validate_error(resp, ApiErrorId.ERR_CALL_INVALID_STATE.value)
        assert err["error_id"] == "ERR_CALL_INVALID_STATE"
        call = get_success_data(api.get_vessel_call(ctx["call"]["id"], MS))
        assert call["status"] == "NOMINATED"

    def test_immediate_consistency_visible_in_response(self, api):
        """PRD §2.5: "`updated_at` (string): an ISO 8601 UTC timestamp refreshed on
        every mutation of the resource." PRD §3.4: "Departure is the billing pivot:
        the slot's `lift_status` moves from `BERTH_ASSIGNED` to `LOADED`, its
        provisional invoice is computed per §3.5, and its `billing_status` moves
        from `UNBILLED` to `PROVISIONALLY_INVOICED`".

        Design: Corner/consistency_model/immediate_consistency_visible_in_response
        """
        ctx = setup_departed_call(
            nor_time="2027-01-12T06:00:00Z",
            berth_time="2027-01-12T14:00:00Z",
            depart_time="2027-01-13T08:00:00Z",
        )
        call = ctx["call"]
        assert call["departed_at"] == "2027-01-13T08:00:00Z", (
            f"depart response must carry departed_at from the logical clock, got "
            f"{call['departed_at']}"
        )
        slot = get_success_data(api.get_cargo_slot(ctx["slot"]["id"], CM))
        assert slot["lift_status"] == "LOADED"
        assert slot["provisional_invoice_usd"] == pytest.approx(24399000.00, abs=0.01), (
            f"provisional invoice must be readable immediately after departure, got "
            f"{slot['provisional_invoice_usd']}"
        )
