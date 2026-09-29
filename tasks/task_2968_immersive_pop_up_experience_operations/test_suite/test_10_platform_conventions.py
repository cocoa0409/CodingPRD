"""The conventions every endpoint shares: the ladder, the initial symbols, the clock and the roles."""

from test_helpers import (
    BLANK_ROLE_HEADERS,
    BLANK_USER_ID_HEADERS,
    UNDECLARED_ROLE_HEADERS,
    UNKNOWN_UUID,
    UNKNOWN_UUID_ALT,
    ApiErrorId,
    api_client,
    assert_agreement,
    assert_guest,
    assert_inspection,
    assert_kit,
    assert_order,
    assert_row_inert,
    assert_run,
    assert_shift,
    assert_slot,
    assert_slot_ledger,
    assert_staff_member,
    assert_statement,
    assert_submission,
    assert_total_count,
    assert_venue,
    factories as f,
    fixtures as fx,
    make_guest_headers,
    validate_error,
    validate_object,
    validate_success,
)

PRODUCER = fx.PRODUCER
PRODUCER_OTHER = fx.PRODUCER_OTHER
VOM = fx.VOM
LM = fx.LM
REP = fx.REP
REP_OTHER = fx.REP_OTHER
OFFICER = fx.OFFICER
AGENT = fx.AGENT


class TestBodyForeignKeysAnswerBeforeTheStateGates:
    """A reference the caller typed into the body is resolved, and it is resolved early."""

    @staticmethod
    def _world():
        bundle = fx.run_with_room()
        run_id = bundle["run"]["id"]
        bundle["slot"] = fx.open_slot(run_id)
        bundle["guest"] = fx.create_guest()
        bundle["staff"] = fx.enrol_staff(run_id)
        return bundle

    def test_a_bogus_reference_in_the_body_names_the_kind_that_is_missing(self):
        """Five bodies, five different 404s, and not one refused call leaves a trace.

        PRD: "Every foreign key supplied in the request body resolves to a stored row"
        PRD: "The codes available at this rung are `ERR_VENUE_NOT_FOUND`,
        `ERR_AGREEMENT_NOT_FOUND`, `ERR_RUN_NOT_FOUND`, `ERR_ROOM_NOT_FOUND`,
        `ERR_SLOT_NOT_FOUND`, `ERR_GUEST_NOT_FOUND`, `ERR_STAFF_NOT_FOUND` and
        `ERR_KIT_NOT_FOUND`, each at HTTP 404."
        PRD: "This rung guards the creation of experience runs, themed rooms,
        timed-entry slots, ticket orders, creative submissions, staff members,
        staff shifts, safety inspections, build kits and royalty statements."
        PRD: "A cascade never partially applies — if the triggering request is
        rejected at any rung of §2.7, none of the cascade's effects occur."

        Design: Corner/entities/body_foreign_keys_are_rejected_after_the_path_identifier_resolves
        """
        world = self._world()
        run_id = world["run"]["id"]
        agreement_id = world["agreement"]["id"]
        kit_id = world["kit"]["id"]
        slot_id = world["slot"]["id"]
        guest_id = world["guest"]["id"]
        kit_before = fx.read_kit(kit_id)
        slot_before = fx.read_slot(slot_id)
        assert kit_before["status"] == "DEPLOYED"

        validate_error(
            api_client.create_run(
                f.run_payload(UNKNOWN_UUID, agreement_id, kit_id, run_name="Ghost venue"),
                PRODUCER,
            ),
            ApiErrorId.ERR_VENUE_NOT_FOUND.value,
            404,
        )
        validate_error(
            api_client.create_run(
                f.run_payload(
                    world["venue"]["id"], UNKNOWN_UUID, kit_id, run_name="Ghost licence"
                ),
                PRODUCER,
            ),
            ApiErrorId.ERR_AGREEMENT_NOT_FOUND.value,
            404,
        )
        validate_error(
            api_client.create_run(
                f.run_payload(
                    world["venue"]["id"], agreement_id, UNKNOWN_UUID_ALT,
                    run_name="Ghost kit",
                ),
                PRODUCER,
            ),
            ApiErrorId.ERR_KIT_NOT_FOUND.value,
            404,
        )
        assert_kit(fx.read_kit(kit_id))
        assert_row_inert(kit_before, fx.read_kit(kit_id))

        validate_error(
            api_client.create_order(f.order_payload(UNKNOWN_UUID, guest_id), AGENT),
            ApiErrorId.ERR_SLOT_NOT_FOUND.value,
            404,
        )
        validate_error(
            api_client.create_order(f.order_payload(slot_id, UNKNOWN_UUID), AGENT),
            ApiErrorId.ERR_GUEST_NOT_FOUND.value,
            404,
        )
        slot = fx.read_slot(slot_id)
        assert_slot_ledger(slot, 20, 0, 0, 20)
        assert_row_inert(slot_before, slot)

        validate_error(
            api_client.create_statement(
                f.statement_payload(UNKNOWN_UUID, fx.run_version(run_id)), LM
            ),
            ApiErrorId.ERR_RUN_NOT_FOUND.value,
            404,
        )
        assert_total_count(api_client.list_statements(LM, {"run_id": run_id}), 0)
        assert_total_count(api_client.list_runs(PRODUCER, {"venue_id": world["venue"]["id"]}), 1)

    def test_the_body_key_answers_before_the_state_gate_it_would_hide_behind(self):
        """A shift for a phantom person, and a shift into a phantom room for a person who is not cleared.

        PRD: "Checks are grouped into rungs and evaluated in the ascending order listed below"
        PRD: "Every foreign key supplied in the request body resolves to a stored row"
        PRD: "the staff member is not `CLEARED` when a shift is scheduled for them
        (`ERR_STAFF_NOT_CLEARED`)"
        PRD: "A `themed_room_id` naming a room that belongs to a different run is
        treated exactly like an identifier that names nothing at all and is refused
        with `ERR_ROOM_NOT_FOUND`."

        Design: Corner/entities/body_foreign_keys_are_rejected_after_the_path_identifier_resolves
        """
        world = self._world()
        run_id = world["run"]["id"]
        staff_id = world["staff"]["id"]
        staff_before = fx.read_staff_member(staff_id)
        assert staff_before["status"] == "CANDIDATE"

        validate_error(
            api_client.create_shift(f.shift_payload(UNKNOWN_UUID), PRODUCER),
            ApiErrorId.ERR_STAFF_NOT_FOUND.value,
            404,
        )
        validate_error(
            api_client.create_shift(
                f.shift_payload(staff_id, themed_room_id=UNKNOWN_UUID), PRODUCER
            ),
            ApiErrorId.ERR_ROOM_NOT_FOUND.value,
            404,
        )
        assert_total_count(api_client.list_shifts(PRODUCER, {"run_id": run_id}), 0)
        assert_staff_member(fx.read_staff_member(staff_id))
        assert_row_inert(staff_before, fx.read_staff_member(staff_id))


class TestEveryEntityLandsInItsDeclaredInitialState:
    """Eleven machines, eleven opening symbols, and a run that opens on two dimensions at once."""

    def test_the_registry_rows_are_born_in_the_symbols_their_machines_declare(self):
        """A venue, a licence, a kit and a guest each start where the PRD says, and a run starts twice.

        PRD: "A new venue starts in `DRAFT` with `permitted_occupancy_load` at 0,
        `permit_submission_round` at 0, `permit_conditions_note`,
        `permit_denial_reason`, `permit_issued_at` and `lease_activated_at` all null"
        PRD: "A fresh agreement sits in `DRAFT` with `open_submission_count` and
        `approved_submission_count` at 0."
        PRD: "A new kit is `READY` and already `LOCALIZED` for its first city, with
        `condition_score` equal to `initial_condition_score`, `reuse_cycle_count` and
        `refurb_count` at 0, `last_city_code` null and `localization_cost_cents` at 0."
        PRD: "A new account is `ACTIVE` with `no_show_strikes`, `visit_count` and
        `experience_credit_cents` at 0."
        PRD: "`run_status` is the operational dimension — `PLANNED`, `OPEN`,
        `EXTENDED`, `CLOSING`, terminating at `CLOSED` — and only deliberate producer
        actions advance it."
        PRD: "`clearance_status` is the compliance dimension — `UNCLEARED`,
        `CLEARED`, `SUSPENDED` — and it is never set directly by an operator command;
        it is derived from creative approvals and staffing, or forced by a failed
        safety inspection, and it has no terminal state."
        PRD: "A new run starts with `effective_capacity` and `effective_capacity_cap`
        at 0, `royalty_statement_count` and `extension_days_granted` at 0,
        `demand_index` at 0.00, and `demand_index_at_extension`, `opened_at`,
        `closing_started_at`, `closed_at`, `suspended_at` and
        `suspending_inspection_id` all null."

        Design: Corner/state_machines/every_entity_lands_in_its_declared_initial_state
        """
        run = fx.run_with_room()["run"]
        assert_run(run)
        assert run["run_status"] == "PLANNED"
        assert run["clearance_status"] == "UNCLEARED"
        assert run["effective_capacity_cap"] == 0
        assert run["royalty_statement_count"] == 0
        assert run["extension_days_granted"] == 0
        assert run["demand_index"] == 0.00
        for field in ("demand_index_at_extension", "opened_at", "closing_started_at",
                      "closed_at", "suspended_at", "suspending_inspection_id"):
            assert run[field] is None, field

        venue = validate_success(
            api_client.create_venue(
                f.venue_payload(
                    city_code="AUS", site_name="Warehouse 12",
                    lease_start_date="2026-11-01", lease_end_date="2027-04-30",
                ),
                VOM,
            ),
            201,
        )
        assert_venue(venue)
        assert venue["status"] == "DRAFT"
        assert venue["permitted_occupancy_load"] == 0
        assert venue["permit_submission_round"] == 0
        for field in ("permit_conditions_note", "permit_denial_reason",
                      "permit_issued_at", "lease_activated_at"):
            assert venue[field] is None, field

        agreement = validate_success(
            api_client.create_agreement(
                f.agreement_payload(
                    ip_title="Neon Atrium II", territory_city_codes=["AUS"],
                    term_start_date="2026-11-01", term_end_date="2027-03-31",
                ),
                LM,
            ),
            201,
        )
        assert_agreement(agreement)
        assert agreement["status"] == "DRAFT"
        assert agreement["open_submission_count"] == 0
        assert agreement["approved_submission_count"] == 0

        kit = validate_success(
            api_client.create_kit(
                f.kit_payload(
                    code=f.kit_code(fx.next_seq()), module_count=14,
                    initial_condition_score=95.00,
                ),
                VOM,
            ),
            201,
        )
        assert_kit(kit)
        assert kit["status"] == "READY"
        assert kit["localization_status"] == "LOCALIZED"
        assert kit["condition_score"] == 95.00
        assert kit["reuse_cycle_count"] == 0
        assert kit["refurb_count"] == 0
        assert kit["last_city_code"] is None
        assert kit["localization_cost_cents"] == 0

        guest = validate_success(
            api_client.create_guest(
                f.guest_payload(email=f"opening{fx.next_seq()}@example.com"), AGENT
            ),
            201,
        )
        assert_guest(guest)
        assert guest["status"] == "ACTIVE"
        assert guest["no_show_strikes"] == 0
        assert guest["visit_count"] == 0
        assert guest["experience_credit_cents"] == 0

    def test_the_operational_rows_are_born_where_their_machines_start(self):
        """A window, an order, a person, a shift, an inspection, an asset and a statement.

        PRD: "A new slot lands in `DRAFT` with `released_capacity`, `held_capacity`,
        `sold_capacity`, `available_capacity` and `wheelchair_sold` all at 0,
        `buyout_order_id` and `released_at` null."
        PRD: "A new order is `PENDING` with `net_collected_cents`, `refunded_cents`
        and `credit_issued_cents` at 0 and `refund_pct` at 0.00"
        PRD: "A new enrolment lands in `CANDIDATE` with `training_score`,
        `completed_rehearsal_count`, `scheduled_rehearsal_count`, `cert_coverage_pct`,
        `readiness_score_preflight` and `readiness_score_audit` all at zero."
        PRD: "the shift's `run_id` is copied from that person's own `run_id` rather
        than supplied by the client"
        PRD: "`COMPLETE` moves `SCHEDULED → COMPLETED` and is admissible only once
        the logical clock has reached `shift_end_utc`"
        PRD: "A new inspection is `SCHEDULED` with `outcome` null,
        `measured_egress_width_cm` at 0, `findings_count` at 0, `severity` at `NONE`,
        `allowed_occupancy_cap` at 0, and `findings_note`, `finalized_by_user_id` and
        `finalized_at` all null."
        PRD: "A new row lands in `SUBMITTED` with `revision_round` at 0,
        `submitted_by_user_id` copied from the filing `X-User-ID`,
        `superseded_by_submission_id` null"
        PRD: "A new statement lands in `DRAFT` with
        `provisional_royalty_cents_prev`, `truedown_cents`, `final_royalty_cents`,
        `mg_prorated_cents`, `minimum_guarantee_shortfall_cents` and
        `amount_due_cents` all at 0 and `superseded_by_statement_id` null."
        PRD: "The statement's `license_agreement_id` is copied from the run rather
        than named by the client, so a statement can never be pointed at an agreement
        the run does not stage."

        Design: Corner/state_machines/every_entity_lands_in_its_declared_initial_state
        """
        world = fx.selling_world(
            slot_overrides={
                "slot_start_utc": "2026-08-25T14:00:00Z",
                "slot_end_utc": "2026-08-25T14:45:00Z",
                "base_capacity": 20,
                "wheelchair_positions": 2,
            }
        )
        run_id = world["run"]["id"]
        agreement_id = world["agreement"]["id"]

        slot = validate_success(
            api_client.create_slot(
                f.slot_payload(
                    run_id, slot_start_utc="2026-08-26T14:00:00Z",
                    slot_end_utc="2026-08-26T14:45:00Z", base_capacity=20,
                ),
                PRODUCER,
            ),
            201,
        )
        assert_slot(slot)
        assert slot["status"] == "DRAFT"
        assert_slot_ledger(slot, 0, 0, 0, 0)
        assert slot["wheelchair_sold"] == 0
        assert slot["buyout_order_id"] is None
        assert slot["released_at"] is None

        order = validate_success(
            api_client.create_order(
                f.order_payload(world["slot"]["id"], world["guest"]["id"]), AGENT
            ),
            201,
        )
        assert_order(order)
        assert order["status"] == "PENDING"
        assert order["net_collected_cents"] == 0
        assert order["refunded_cents"] == 0
        assert order["credit_issued_cents"] == 0
        assert order["refund_pct"] == 0.00

        member = validate_success(
            api_client.create_staff_member(f.staff_member_payload(run_id), PRODUCER), 201
        )
        assert_staff_member(member)
        assert member["status"] == "CANDIDATE"
        assert member["training_score"] == 0
        assert member["completed_rehearsal_count"] == 0
        assert member["scheduled_rehearsal_count"] == 0
        assert member["cert_coverage_pct"] == 0.00
        assert member["readiness_score_preflight"] == 0.00
        assert member["readiness_score_audit"] == 0.00

        shift = validate_success(
            api_client.create_shift(
                f.shift_payload(world["roster"]["performer"]["id"]), PRODUCER
            ),
            201,
        )
        assert_shift(shift)
        assert shift["status"] == "SCHEDULED"
        assert shift["run_id"] == run_id

        inspection = validate_success(
            api_client.create_inspection(
                f.inspection_payload(run_id, "ACCESSIBILITY"), OFFICER
            ),
            201,
        )
        assert_inspection(inspection)
        assert inspection["status"] == "SCHEDULED"
        assert inspection["outcome"] is None
        assert inspection["measured_egress_width_cm"] == 0
        assert inspection["findings_count"] == 0
        assert inspection["severity"] == "NONE"
        assert inspection["allowed_occupancy_cap"] == 0
        for field in ("findings_note", "finalized_by_user_id", "finalized_at"):
            assert inspection[field] is None, field

        submission = validate_success(
            api_client.create_submission(
                f.submission_payload(
                    agreement_id, run_id, fx.agreement_version(agreement_id),
                    asset_code="ATRIUM-OPENING-01",
                ),
                PRODUCER,
            ),
            201,
        )
        assert_submission(submission)
        assert submission["status"] == "SUBMITTED"
        assert submission["revision_round"] == 0
        assert submission["submitted_by_user_id"] == "producer-1"
        assert submission["superseded_by_submission_id"] is None

        statement = validate_success(
            api_client.create_statement(
                f.statement_payload(run_id, fx.run_version(run_id)), LM
            ),
            201,
        )
        assert_statement(statement)
        assert statement["status"] == "DRAFT"
        assert statement["license_agreement_id"] == agreement_id
        for field in ("provisional_royalty_cents_prev", "truedown_cents",
                      "final_royalty_cents", "mg_prorated_cents",
                      "minimum_guarantee_shortfall_cents", "amount_due_cents"):
            assert statement[field] == 0, field
        assert statement["superseded_by_statement_id"] is None


class TestWrongSourceStateIsRefusedAcrossTheMachines:
    """Every action endpoint asks the same first question: is this row in a state that allows it."""

    @staticmethod
    def _world():
        bundle = fx.run_with_room()
        run_id = bundle["run"]["id"]
        agreement_id = bundle["agreement"]["id"]
        bundle["agreement_b"] = fx.create_agreement(
            ip_title="Neon Atrium II", territory_city_codes=["AUS"],
            term_start_date="2026-11-01", term_end_date="2027-03-31",
        )
        bundle["slot"] = fx.open_slot(run_id)
        bundle["guest"] = fx.create_guest()
        bundle["order"] = fx.place_order(bundle["slot"]["id"], bundle["guest"]["id"])
        bundle["staff"] = fx.enrol_staff(run_id)
        bundle["inspection"] = fx.scheduled_inspection(run_id, "SENSORY")
        bundle["submission"] = validate_success(
            api_client.create_submission(
                f.submission_payload(
                    agreement_id, run_id, fx.agreement_version(agreement_id)
                ),
                PRODUCER,
            ),
            201,
        )
        bundle["statement"] = fx.draft_statement(run_id)
        return bundle

    def test_the_venue_licence_asset_run_and_window_all_refuse_the_wrong_source(self):
        """Five machines, five state errors, and two of them outrank a clock gate and a review gate.

        PRD: "Checks are grouped into rungs and evaluated in the ascending order listed below"
        PRD: "At the other end of the term, a `VenueOpsManager` ends the lease,
        moving `LEASE_ACTIVE → LEASE_ENDED`, but only when the site is genuinely empty"
        PRD: "Expiry moves `ACTIVE → EXPIRED` and is the mirror image: it is
        admissible only once the logical clock's calendar date is strictly after
        `term_end_date`, and an early attempt earns `ERR_TERM_NOT_ENDED`."
        PRD: "From `IN_REVIEW` the representative records a `decision` of `APPROVED`,
        `REJECTED` or `CHANGES_REQUESTED` with an optional `note`, and the three
        branches diverge sharply."
        PRD: "A `decision` of `CLOSE` then moves `CLOSING → CLOSED`, and it is
        admissible only when the books are clean: no order of the run may still be
        `CONFIRMED` or `REFUND_DUE`, and no shift of the run may still be `SCHEDULED`."
        PRD: "Releasing a slot moves it `DRAFT → OPEN`, sets both `released_capacity`
        and `available_capacity` to `base_capacity` and stamps `released_at` from the clock."
        PRD: "`version` is an integer that is 1 at creation and increases by exactly 1
        on every mutation of that row, again including cascaded mutations."

        Design: Corner/state_machines/wrong_source_state_transitions_are_rejected_across_eleven_machines
        """
        world = self._world()
        venue_id = world["venue"]["id"]
        agreement_b_id = world["agreement_b"]["id"]
        submission_id = world["submission"]["id"]
        run_id = world["run"]["id"]
        slot_id = world["slot"]["id"]
        venue_before = fx.read_venue(venue_id)
        agreement_b_before = fx.read_agreement(agreement_b_id)
        submission_before = fx.read_submission(submission_id)
        run_before = fx.read_run(run_id)
        slot_before = fx.read_slot(slot_id)
        assert venue_before["status"] == "PERMIT_ISSUED"
        assert agreement_b_before["status"] == "DRAFT"
        assert submission_before["status"] == "SUBMITTED"
        assert run_before["run_status"] == "PLANNED"
        assert slot_before["status"] == "OPEN"

        validate_error(
            api_client.end_lease(venue_id, VOM),
            ApiErrorId.ERR_VENUE_INVALID_STATE.value,
            409,
        )
        validate_error(
            api_client.expire_agreement(agreement_b_id, LM),
            ApiErrorId.ERR_AGREEMENT_INVALID_STATE.value,
            409,
        )
        validate_error(
            api_client.decide_submission(
                submission_id,
                f.submission_decision_payload("APPROVED", note="approved without a review"),
                REP,
            ),
            ApiErrorId.ERR_SUBMISSION_INVALID_STATE.value,
            409,
        )
        validate_error(
            api_client.decide_closure(
                run_id, f.closure_decision_payload("CLOSE"), PRODUCER
            ),
            ApiErrorId.ERR_RUN_INVALID_STATE.value,
            409,
        )
        validate_error(
            api_client.release_slot(slot_id, PRODUCER),
            ApiErrorId.ERR_SLOT_INVALID_STATE.value,
            409,
        )

        assert_row_inert(venue_before, fx.read_venue(venue_id))
        assert_row_inert(agreement_b_before, fx.read_agreement(agreement_b_id))
        assert_row_inert(submission_before, fx.read_submission(submission_id))
        assert_row_inert(run_before, fx.read_run(run_id))
        assert_row_inert(slot_before, fx.read_slot(slot_id))

    def test_the_order_person_inspection_kit_and_statement_all_refuse_it_too(self):
        """Five more machines, one accepted void in the middle, and a terminal row that refuses the next hop.

        PRD: "Settling the refund is a separate act and it recomputes nothing."
        PRD: "`CLEAR` moves a person `TRAINING → CLEARED` and is doubly gated:
        `readiness_score_audit` must be at least 78.00, or the decision is refused
        with `ERR_STAFF_READINESS_BELOW_MIN`, and `incident_count` must be no more
        than 2, or it is refused with `ERR_STAFF_INCIDENTS_ABOVE_MAX`."
        PRD: "An inspection that will not be carried out is voided instead, moving
        `SCHEDULED → VOIDED` with the supplied `note` stored as `findings_note`,
        leaving `outcome` null and `allowed_occupancy_cap` at 0."
        PRD: "On every branch, whatever the verdict, finalisation moves the inspection
        `SCHEDULED → FINALIZED`, records `finalized_by_user_id` from the finalising
        `X-User-ID` and `finalized_at` from the clock"
        PRD: "On a kit in `REFURB_REQUIRED` whose `refurb_count` is still below 2,
        refurbishing adds 30.00 to `condition_score` capped at 100.00, raises
        `refurb_count` by 1, and moves the kit `REFURB_REQUIRED → IN_TRANSIT`"
        PRD: "Settling records payment to the licensor: the statement moves
        `ISSUED → SETTLED` and `settled_at` is stamped from the clock."

        Design: Corner/state_machines/wrong_source_state_transitions_are_rejected_across_eleven_machines
        """
        world = self._world()
        order_id = world["order"]["id"]
        staff_id = world["staff"]["id"]
        inspection_id = world["inspection"]["id"]
        kit_id = world["kit"]["id"]
        statement_id = world["statement"]["id"]
        order_before = fx.read_order(order_id)
        staff_before = fx.read_staff_member(staff_id)
        kit_before = fx.read_kit(kit_id)
        statement_before = fx.read_statement(statement_id)
        assert order_before["status"] == "PENDING"
        assert staff_before["status"] == "CANDIDATE"
        assert kit_before["status"] == "DEPLOYED"
        assert statement_before["status"] == "DRAFT"

        validate_error(
            api_client.settle_refund(order_id, AGENT),
            ApiErrorId.ERR_ORDER_INVALID_STATE.value,
            409,
        )
        validate_error(
            api_client.decide_staff_status(
                staff_id, f.staff_status_decision_payload("CLEAR"), PRODUCER
            ),
            ApiErrorId.ERR_STAFF_INVALID_STATE.value,
            409,
        )

        voided = validate_success(
            api_client.void_inspection(inspection_id, f.inspection_void_payload(), OFFICER)
        )
        assert_inspection(voided)
        assert voided["status"] == "VOIDED"
        assert voided["outcome"] is None
        assert voided["allowed_occupancy_cap"] == 0
        assert voided["version"] == 2
        validate_error(
            api_client.finalize_inspection(
                inspection_id, f.inspection_finalize_payload(), OFFICER
            ),
            ApiErrorId.ERR_INSPECTION_INVALID_STATE.value,
            409,
        )
        assert_row_inert(voided, fx.read_inspection(inspection_id))

        validate_error(
            api_client.refurbish_kit(kit_id, VOM),
            ApiErrorId.ERR_KIT_INVALID_STATE.value,
            409,
        )
        validate_error(
            api_client.settle_statement(statement_id, LM),
            ApiErrorId.ERR_STATEMENT_INVALID_STATE.value,
            409,
        )

        assert_row_inert(order_before, fx.read_order(order_id))
        assert_row_inert(staff_before, fx.read_staff_member(staff_id))
        assert_row_inert(kit_before, fx.read_kit(kit_id))
        assert_row_inert(statement_before, fx.read_statement(statement_id))


class TestClockPositionGatesHoldAtTheirOwnEdges:
    """Two of the four gates open on the instant named; the other two open the day after.

    PRD: "`ERR_LEASE_START_NOT_REACHED` when a lease is activated before its start
    date; `ERR_TERM_NOT_ENDED` when an agreement is expired without the term having
    ended;"
    """

    def test_the_lease_opens_on_its_date_and_the_licence_expires_only_after_its_term(self):
        """One inclusive gate and one exclusive gate on the same clock walk.

        PRD: "activation is admissible only when the logical clock's calendar date is
        on or after `lease_start_date`, and an early attempt is refused with
        `ERR_LEASE_START_NOT_REACHED`"
        PRD: "Expiry moves `ACTIVE → EXPIRED` and is the mirror image: it is
        admissible only once the logical clock's calendar date is strictly after
        `term_end_date`, and an early attempt earns `ERR_TERM_NOT_ENDED`."
        PRD: "`ERR_PERIOD_NOT_ENDED` when a statement is finalised before its period has closed"

        Design: Corner/validations/clock_position_gates_hold_at_four_different_edges
        """
        venue = fx.venue_permitted(lease_start_date="2026-09-01")
        venue_id = venue["id"]
        before = fx.read_venue(venue_id)

        validate_error(
            api_client.activate_lease(venue_id, VOM),
            ApiErrorId.ERR_LEASE_START_NOT_REACHED.value,
            409,
        )
        assert_row_inert(before, fx.read_venue(venue_id))

        fx.set_clock("2026-08-31T23:59:59Z")
        validate_error(
            api_client.activate_lease(venue_id, VOM),
            ApiErrorId.ERR_LEASE_START_NOT_REACHED.value,
            409,
        )
        assert_row_inert(before, fx.read_venue(venue_id))

        fx.set_clock("2026-09-01T00:00:00Z")
        activated = validate_success(api_client.activate_lease(venue_id, VOM))
        assert_venue(activated)
        assert activated["status"] == "LEASE_ACTIVE"

        agreement = fx.agreement_active()
        agreement_id = agreement["id"]
        assert agreement["term_end_date"] == "2026-12-31"
        active_row = fx.read_agreement(agreement_id)

        fx.set_clock("2026-12-31T23:59:59Z")
        validate_error(
            api_client.expire_agreement(agreement_id, LM),
            ApiErrorId.ERR_TERM_NOT_ENDED.value,
            409,
        )
        assert_row_inert(active_row, fx.read_agreement(agreement_id))

        fx.set_clock("2027-01-01T00:00:00Z")
        expired = validate_success(api_client.expire_agreement(agreement_id, LM))
        assert_agreement(expired)
        assert expired["status"] == "EXPIRED"

    def test_the_shift_completes_on_its_end_instant_and_the_statement_issues_the_day_after(self):
        """The second inclusive gate and the second exclusive gate, one second apart from their edges.

        PRD: "`COMPLETE` moves `SCHEDULED → COMPLETED` and is admissible only once
        the logical clock has reached `shift_end_utc`; an earlier attempt is refused
        with `ERR_SHIFT_NOT_ENDED`."
        PRD: "Finalising issues the statement, and it may only happen once the period
        is genuinely over: the logical clock's calendar date must be"
        PRD: "`ERR_SHIFT_NOT_ENDED` when a shift is completed before its end instant"

        Design: Corner/validations/clock_position_gates_hold_at_four_different_edges
        """
        world = fx.cleared_run()
        run_id = world["run"]["id"]
        shift = fx.book_shift(
            world["roster"]["performer"]["id"],
            shift_start_utc="2026-09-10T09:00:00Z",
            shift_end_utc="2026-09-10T17:00:00Z",
        )
        shift_id = shift["id"]
        statement = fx.draft_statement(
            run_id, period_start_date="2026-09-01", period_end_date="2026-09-30"
        )
        statement_id = statement["id"]
        shift_before = fx.read_shift(shift_id)
        statement_before = fx.read_statement(statement_id)
        assert shift_before["status"] == "SCHEDULED"
        assert statement_before["status"] == "DRAFT"

        fx.set_clock("2026-09-10T16:59:59Z")
        validate_error(
            api_client.decide_shift_status(
                shift_id, f.shift_status_decision_payload("COMPLETE"), PRODUCER
            ),
            ApiErrorId.ERR_SHIFT_NOT_ENDED.value,
            409,
        )
        assert_row_inert(shift_before, fx.read_shift(shift_id))

        fx.set_clock("2026-09-10T17:00:00Z")
        completed = validate_success(
            api_client.decide_shift_status(
                shift_id, f.shift_status_decision_payload("COMPLETE"), PRODUCER
            )
        )
        assert_shift(completed)
        assert completed["status"] == "COMPLETED"

        fx.set_clock("2026-09-30T23:59:59Z")
        validate_error(
            api_client.finalize_statement(statement_id, LM),
            ApiErrorId.ERR_PERIOD_NOT_ENDED.value,
            409,
        )
        assert_row_inert(statement_before, fx.read_statement(statement_id))

        fx.set_clock("2026-10-01T00:00:00Z")
        issued = validate_success(api_client.finalize_statement(statement_id, LM))
        assert_statement(issued)
        assert issued["status"] == "ISSUED"


class TestEachRolePerformsTheOperationsItOwns:
    """Seven roles, no hierarchy: every one of them is the only one that can do its own work."""

    def test_the_six_staff_roles_each_reach_the_endpoints_that_name_them(self):
        """Money, statements, reviews, windows, inspections and accounts, one role each.

        PRD: "The `Authorized Role(s)` column is exhaustive: a role absent from a
        row may not call that endpoint and receives `ERR_UNAUTHORIZED`."
        PRD: "Bucket one is the landlord allowance: the service takes the smaller
        of the amount still to be allocated and the allowance headroom, which is
        `buildout_allowance_cents` less `allowance_drawn_cents`, adds it to
        `allowance_drawn_cents`, and reduces the amount still to be allocated by
        that much."
        PRD: "Finally the whole `draw_amount_cents` is added to
        `buildout_spend_cents`."
        PRD: "On a venue, `buildout_spend_cents` always equals
        `allowance_drawn_cents` plus `kit_credit_drawn_cents` plus
        `operator_capex_cents`."

        Design: Corner/rbac/each_role_performs_the_operations_it_owns
        """
        world = fx.run_with_room(lease_active=True)
        venue_id = world["venue"]["id"]
        run_id = world["run"]["id"]
        agreement_id = world["agreement"]["id"]
        submission = validate_success(
            api_client.create_submission(
                f.submission_payload(
                    agreement_id, run_id, fx.agreement_version(agreement_id)
                ),
                PRODUCER,
            ),
            201,
        )
        assert submission["status"] == "SUBMITTED"

        drawn = validate_success(
            api_client.draw_buildout(
                venue_id, f.buildout_draw_payload(500000), VOM
            )
        )
        assert_venue(drawn)
        assert drawn["allowance_drawn_cents"] == 500000
        assert drawn["kit_credit_drawn_cents"] == 0
        assert drawn["operator_capex_cents"] == 0
        assert drawn["buildout_spend_cents"] == 500000

        statement = validate_success(
            api_client.create_statement(
                f.statement_payload(run_id, fx.run_version(run_id)), LM
            ),
            201,
        )
        assert_statement(statement)
        assert statement["status"] == "DRAFT"

        reviewing = validate_success(
            api_client.start_submission_review(submission["id"], REP)
        )
        assert_submission(reviewing)
        assert reviewing["status"] == "IN_REVIEW"

        slot = validate_success(
            api_client.create_slot(
                f.slot_payload(
                    run_id,
                    slot_start_utc="2026-08-25T14:00:00Z",
                    slot_end_utc="2026-08-25T14:45:00Z",
                ),
                PRODUCER,
            ),
            201,
        )
        assert_slot(slot)
        assert slot["status"] == "DRAFT"
        released = validate_success(api_client.release_slot(slot["id"], PRODUCER))
        assert released["status"] == "OPEN"

        inspection = validate_success(
            api_client.create_inspection(
                f.inspection_payload(
                    run_id,
                    inspection_type="ACCESSIBILITY",
                    scheduled_for_utc="2026-08-20T09:00:00Z",
                ),
                OFFICER,
            ),
            201,
        )
        assert_inspection(inspection)
        assert inspection["inspection_type"] == "ACCESSIBILITY"
        assert inspection["status"] == "SCHEDULED"

        guest = validate_success(
            api_client.create_guest(
                f.guest_payload(email="mina@example.com", display_name="Mina Ortega",
                                loyalty_tier="MEMBER"),
                AGENT,
            ),
            201,
        )
        assert_guest(guest)
        assert guest["status"] == "ACTIVE"

    def test_the_guest_owns_no_endpoint_and_still_buys_reads_and_cancels(self):
        """An empty exclusive list is not an empty permission set.

        PRD: "Read-only price quote for a hypothetical order on this slot:
        slot_dynamic_price plus the full ticket_order_total breakdown at the
        current clock position."
        PRD: "Lead time is measured from the current logical clock instant to
        `slot_start_utc` in seconds and floored to whole days."
        PRD: "Booking 30 or more days ahead earns the early multiplier 0.90; from
        7 up to 29 days the multiplier is 1.00; closer in than 7 days the late
        multiplier is 1.15."
        PRD: "`per_guest_after_loyalty_cents` is the unit price reduced by the
        loyalty discount for the guest's tier — 0 percent for `VISITOR`, 5
        percent for `MEMBER`, 12 percent for `PATRON` — rounded half up to whole
        cents."
        PRD: "A `PENDING` order simply drops its hold: it moves to `CANCELLED`
        with `refund_pct` 0.00 and all three money legs at 0, and the slot's
        `held_capacity` falls by `party_size` while `available_capacity` rises
        again"
        PRD: "The same operations performed by a `GuestServicesAgent` carry no
        such restriction, because that role acts on any guest's behalf."
        PRD: "List royalty statements; the reverse-reachability channel for the
        run, agreement and supersede links."

        Design: Corner/rbac/each_role_performs_the_operations_it_owns
        """
        world = fx.selling_world(
            slot_overrides={
                "slot_start_utc": "2026-08-25T14:00:00Z",
                "slot_end_utc": "2026-08-25T14:45:00Z",
                "base_capacity": 20,
                "wheelchair_positions": 2,
            }
        )
        run_id = world["run"]["id"]
        slot_id = world["slot"]["id"]
        guest_id = world["guest"]["id"]
        guest_headers = make_guest_headers(guest_id)

        order = validate_success(
            api_client.create_order(
                f.order_payload(slot_id, guest_id, party_size=2), guest_headers
            ),
            201,
        )
        assert_order(order)
        assert order["status"] == "PENDING"
        assert order["unit_price_cents"] == 35833
        assert order["gross_amount_cents"] == 71666
        assert_slot_ledger(fx.read_slot(slot_id), 20, 2, 0, 18)

        quote = validate_success(
            api_client.get_price_quote(
                slot_id,
                f.price_quote_params(loyalty_tier="MEMBER", party_size=2),
                guest_headers,
            )
        )
        assert quote["slot_id"] == slot_id
        assert quote["pricing_tier"] == "STANDARD"
        assert quote["lead_days"] == 24
        assert quote["unit_price_cents"] == 35833
        assert quote["per_guest_after_loyalty_cents"] == 34041
        assert quote["gross_amount_cents"] == 68082
        assert quote["group_discount_cents"] == 0
        assert quote["companion_waiver_cents"] == 0
        assert quote["discount_cents"] == 0
        assert quote["net_amount_cents"] == 68082

        cancelled = validate_success(
            api_client.cancel_order(order["id"], f.cancel_payload(), guest_headers)
        )
        assert_order(cancelled)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["refund_pct"] == 0.00
        assert cancelled["net_collected_cents"] == 0
        assert cancelled["refunded_cents"] == 0
        assert cancelled["credit_issued_cents"] == 0
        assert_slot_ledger(fx.read_slot(slot_id), 20, 0, 0, 20)

        seen_by_agent = validate_object(api_client.get_venue(world["venue"]["id"], AGENT))
        assert seen_by_agent["id"] == world["venue"]["id"]

        statement = fx.draft_statement(run_id)
        rows = assert_total_count(
            api_client.list_statements(REP, {"run_id": run_id}), 1
        )
        assert rows[0]["id"] == statement["id"]


class TestUnauthenticatedAndUnauthorizedInPriorityOrder:
    """Who you are is asked first, what you may do second, and where it lives only third."""

    def test_a_bad_header_is_never_a_forbidden_call_and_neither_hides_a_missing_row(self):
        """Blank, undeclared, wrong and phantom: four different answers in ladder order.

        PRD: "If either header is absent, is blank, or if `X-User-Role` does not
        name one of the roles declared below, the request is rejected with
        `ERR_UNAUTHENTICATED` and HTTP 401."
        PRD: "`X-User-ID` present and non-blank, and `X-User-Role` present and
        naming a declared role."
        PRD: "The role named by `X-User-Role` appears in the called endpoint's
        authorised-role list."
        PRD: "Every identifier in the request path resolves to a stored row,
        validated left to right."
        PRD: "The `Authorized Role(s)` column is exhaustive: a role absent from a
        row may not call that endpoint and receives `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/unauthenticated_and_unauthorized_calls_are_rejected_in_priority_order
        """
        world = fx.run_with_room()
        run_id = world["run"]["id"]
        guest = fx.create_guest()
        guest_headers = make_guest_headers(guest["id"])
        rejected = f.venue_payload(
            city_code="AUS", site_name="Blank id",
            lease_start_date="2026-09-01", lease_end_date="2027-02-28",
        )

        validate_error(
            api_client.create_venue(rejected, BLANK_USER_ID_HEADERS),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
            401,
        )
        validate_error(
            api_client.create_venue(rejected, BLANK_ROLE_HEADERS),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
            401,
        )
        validate_error(
            api_client.create_venue(rejected, UNDECLARED_ROLE_HEADERS),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
            401,
        )
        validate_error(
            api_client.create_venue(rejected, PRODUCER),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api_client.draw_buildout(
                UNKNOWN_UUID, f.buildout_draw_payload(100000), AGENT
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api_client.create_guest(
                f.guest_payload(email="guest.c@example.com", display_name="Guest C"),
                guest_headers,
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api_client.list_statements(guest_headers, {"run_id": run_id}),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )

        rows = assert_total_count(api_client.list_venues(VOM), 1)
        assert rows[0]["id"] == world["venue"]["id"]

    def test_identity_answers_after_the_role_and_the_owner_still_gets_through(self):
        """A rep that is not the named rep, and a guest that is not the owner.

        PRD: "The five codes are `ERR_SOD_SUSPENSION_LIFT_SAME_USER`,
        `ERR_SOD_APPROVAL_SAME_USER`, `ERR_SOD_EXTENSION_SAME_USER`,
        `ERR_LICENSOR_REP_MISMATCH` and `ERR_GUEST_OWNERSHIP_MISMATCH`, all at
        HTTP 403; §2.10 states the rules."
        PRD: "This rung guards suspension lifting, submission review and
        decisions, extension granting, order creation and order cancellation."
        PRD: "Beyond those three, a `LicensorRep` may act only on submissions
        whose governing agreement names that caller's `X-User-ID` as its
        `licensor_rep_user_id`; any other representative attempting to start a
        review or issue a decision is refused with `ERR_LICENSOR_REP_MISMATCH`."
        PRD: "A `Guest` that places an order for a different account, or cancels
        an order belonging to a different account, is rejected with
        `ERR_GUEST_OWNERSHIP_MISMATCH` and HTTP 403."

        Design: Corner/rbac/unauthenticated_and_unauthorized_calls_are_rejected_in_priority_order
        """
        world = fx.selling_world(
            slot_overrides={
                "slot_start_utc": "2026-08-25T14:00:00Z",
                "slot_end_utc": "2026-08-25T14:45:00Z",
                "base_capacity": 20,
                "wheelchair_positions": 2,
            }
        )
        run_id = world["run"]["id"]
        slot_id = world["slot"]["id"]
        agreement_id = world["agreement"]["id"]
        guest_a = world["guest"]
        guest_b = fx.create_guest()
        headers_a = make_guest_headers(guest_a["id"])
        headers_b = make_guest_headers(guest_b["id"])
        submission = validate_success(
            api_client.create_submission(
                f.submission_payload(
                    agreement_id, run_id, fx.agreement_version(agreement_id)
                ),
                PRODUCER,
            ),
            201,
        )
        submission_before = fx.read_submission(submission["id"])
        order_a = fx.place_order(slot_id, guest_a["id"], headers_a, party_size=2)
        order_before = fx.read_order(order_a["id"])
        assert order_before["status"] == "PENDING"

        validate_error(
            api_client.start_submission_review(submission["id"], REP_OTHER),
            ApiErrorId.ERR_LICENSOR_REP_MISMATCH.value,
            403,
        )
        assert_row_inert(submission_before, fx.read_submission(submission["id"]))

        reviewing = validate_success(
            api_client.start_submission_review(submission["id"], REP)
        )
        assert reviewing["status"] == "IN_REVIEW"

        validate_error(
            api_client.create_order(
                f.order_payload(slot_id, guest_a["id"], party_size=1), headers_b
            ),
            ApiErrorId.ERR_GUEST_OWNERSHIP_MISMATCH.value,
            403,
        )
        assert_slot_ledger(fx.read_slot(slot_id), 20, 2, 0, 18)

        validate_error(
            api_client.cancel_order(
                order_a["id"], f.cancel_payload(reason="not my order"), headers_b
            ),
            ApiErrorId.ERR_GUEST_OWNERSHIP_MISMATCH.value,
            403,
        )
        assert_row_inert(order_before, fx.read_order(order_a["id"]))

        cancelled = validate_success(
            api_client.cancel_order(
                order_a["id"], f.cancel_payload(reason="my own order"), headers_a
            )
        )
        assert cancelled["status"] == "CANCELLED"
        assert_slot_ledger(fx.read_slot(slot_id), 20, 0, 0, 20)


class TestEveryWriteIsVisibleToTheVeryNextRead:
    """The mutating response already carries the new state, and the neighbouring row is already current."""

    def test_the_order_and_the_window_agree_at_every_hop_and_the_aggregate_is_pure(self):
        """One order, one confirm, and never a stale counter anywhere in between.

        PRD: "Those cascades are immediate and complete: by the time a response is
        returned, every row the cascade touches has its new state, its refreshed
        `updated_at` and its incremented `version` already persisted, and there is
        no deferred or eventual settlement anywhere in the service."
        PRD: "`version` is an integer that is 1 at creation and increases by
        exactly 1 on every mutation of that row, again including cascaded
        mutations."
        PRD: "`gross_amount_cents` is that per-guest figure multiplied by
        `party_size`."
        PRD: "On success the order moves `PENDING → CONFIRMED`,
        `net_collected_cents` becomes `net_amount_cents`, the seats move from
        `held_capacity` into `sold_capacity`, `wheelchair_sold` rises by
        `wheelchair_party_count`, `available_capacity` is recomputed as
        `released_capacity` less `held_capacity` less `sold_capacity`, and the
        slot moves to `SOLD_OUT` when that leaves nothing available."
        PRD: "Utilisation is 100 multiplied by the sum of `sold_capacity` over
        those windows divided by the sum of `released_capacity` over them, rounded
        half up to two decimals, and is 0.00 when nothing has been released at all
        rather than an error."
        PRD: "Note that `demand_index` is written only on a successful extension;
        the read-only telemetry view computes the same figure and stores nothing."
        PRD: "That view persists nothing, writes no field and never advances the
        run's `version`."

        Design: Corner/consistency_model/every_write_is_visible_to_the_very_next_read
        """
        world = fx.selling_world(
            slot_overrides={
                "slot_start_utc": "2026-08-25T14:00:00Z",
                "slot_end_utc": "2026-08-25T14:45:00Z",
                "base_capacity": 20,
                "wheelchair_positions": 2,
            }
        )
        run_id = world["run"]["id"]
        slot_id = world["slot"]["id"]
        guest_id = world["guest"]["id"]
        guest_headers = make_guest_headers(guest_id)
        release_version = world["slot"]["version"]

        order = validate_success(
            api_client.create_order(
                f.order_payload(slot_id, guest_id, party_size=3), guest_headers
            ),
            201,
        )
        assert_order(order)
        assert order["status"] == "PENDING"
        assert order["unit_price_cents"] == 35833
        assert order["per_guest_after_loyalty_cents"] == 35833
        assert order["gross_amount_cents"] == 107499
        assert order["discount_cents"] == 0
        assert order["net_amount_cents"] == 107499
        assert order["net_collected_cents"] == 0

        held = validate_object(api_client.get_slot(slot_id, guest_headers))
        assert_slot_ledger(held, 20, 3, 0, 17)
        assert held["version"] == release_version + 1

        confirmed = validate_success(api_client.confirm_order(order["id"], AGENT))
        assert_order(confirmed)
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["net_collected_cents"] == 107499
        assert confirmed["version"] == order["version"] + 1

        reread = validate_object(api_client.get_order(order["id"], AGENT))
        assert reread == confirmed

        sold = validate_object(api_client.get_slot(slot_id, PRODUCER))
        assert_slot_ledger(sold, 20, 0, 3, 17)
        assert sold["status"] == "OPEN"
        assert sold["version"] == release_version + 2

        before_telemetry = fx.read_run(run_id)
        telemetry = validate_object(api_client.get_demand_index(run_id, PRODUCER))
        assert telemetry["demand_index"] == 15.00
        again = validate_object(api_client.get_demand_index(run_id, LM))
        assert again["demand_index"] == telemetry["demand_index"]

        assert_row_inert(before_telemetry, fx.read_run(run_id))
        assert before_telemetry["demand_index"] == 0.00

    def test_an_enrolment_is_already_derived_and_already_listed_in_its_own_response(self):
        """The create response carries the derived figures the list is about to repeat.

        PRD: "A new enrolment lands in `CANDIDATE` with `training_score`,
        `completed_rehearsal_count`, `scheduled_rehearsal_count`,
        `cert_coverage_pct`, `readiness_score_preflight` and
        `readiness_score_audit` all at zero."
        PRD: "Those cascades are immediate and complete: by the time a response is
        returned, every row the cascade touches has its new state, its refreshed
        `updated_at` and its incremented `version` already persisted, and there is
        no deferred or eventual settlement anywhere in the service."
        PRD: "List staff members; the reverse-reachability channel for the run
        link."

        Design: Corner/consistency_model/every_write_is_visible_to_the_very_next_read
        """
        world = fx.run_with_room()
        run_id = world["run"]["id"]

        member = validate_success(
            api_client.create_staff_member(
                f.staff_member_payload(
                    run_id, "PERFORMER", ["SCRIPTED_INTERACTION"],
                    full_name="Ada Reyes",
                ),
                PRODUCER,
            ),
            201,
        )
        assert_staff_member(member)
        assert member["status"] == "CANDIDATE"
        assert member["training_score"] == 0
        assert member["completed_rehearsal_count"] == 0
        assert member["scheduled_rehearsal_count"] == 0
        assert member["cert_coverage_pct"] == 0.00
        assert member["readiness_score_preflight"] == 0.00
        assert member["readiness_score_audit"] == 0.00
        assert member["version"] == 1

        rows = assert_total_count(
            api_client.list_staff_members(OFFICER, {"run_id": run_id}), 1
        )
        assert rows[0]["id"] == member["id"]
        assert rows[0]["status"] == "CANDIDATE"
        assert rows[0]["cert_coverage_pct"] == 0.00
        assert rows[0]["readiness_score_preflight"] == 0.00
        assert rows[0]["readiness_score_audit"] == 0.00
        assert rows[0]["version"] == 1
