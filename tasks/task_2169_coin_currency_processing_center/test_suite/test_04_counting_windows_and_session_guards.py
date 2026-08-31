"""Booking the machine: window occupancy, scheduling guards and the two bag axes."""

from test_helpers import (
    ApiErrorId,
    MANAGER_1,
    TELLER_1,
    assert_count_session,
    create_count_session_payload,
    create_machine,
    make_manager_headers,
    make_teller_headers,
    open_bag,
    read_bag,
    read_bag_version,
    read_session,
    schedule_session,
    set_posture,
    setup_intake_ticket,
    validate_error,
    validate_paginated,
    validate_success,
)

CURRENCY_BAG = {
    "bag_type": "CURRENCY",
    "declared_amount_cents": 100_000,
    "declared_note_count": 100,
    "declared_coin_weight_grams": 0,
}


class TestParallelBagAxes:
    def test_open_hop_advances_only_the_custody_axis(self, api):
        """PRD §3.2: "The custody axis, `custody_status`, runs `SEALED → IN_TRANSIT →
        VAULT_RECEIVED → OPENED` and records where the bag physically is. The counting
        axis, `count_status`, runs `PENDING → COUNTING → COUNTED → ADJUSTED` and records
        how far its contents have been processed."
        PRD §3.2: "An `OPEN` hop, also teller-recorded, moves the bag `VAULT_RECEIVED →
        OPENED`, and it is permitted only when a counting session for that bag already
        exists in `SCHEDULED` condition; opening a bag with no scheduled count is refused
        with `ERR_INVALID_STATE`."
        PRD §3.2: "An `OPEN` hop leaves the counting axis alone — the bag remains
        `PENDING`."

        Design: Difficulty/non_linear_state_machine/sealed_bag_custody_and_count_axes_advance_independently
        """
        scenario = setup_intake_ticket(bag_specs=[CURRENCY_BAG])
        bag = scenario["bag"]

        before = read_bag(bag["id"])
        assert before["custody_status"] == "VAULT_RECEIVED", (
            f"Expected custody VAULT_RECEIVED before the OPEN hop, got {before['custody_status']}"
        )
        assert before["count_status"] == "PENDING", (
            f"Expected count PENDING before the OPEN hop, got {before['count_status']}"
        )

        schedule_session(bag["id"], scenario["machine"]["id"])
        event = open_bag(bag["id"], bag["seal_number"])
        assert event["sequence_no"] == 3, (
            f"PICKUP, VAULT_RECEIPT and OPEN make the OPEN hop the third, got {event['sequence_no']}"
        )

        after_open = read_bag(bag["id"])
        assert after_open["custody_status"] == "OPENED", (
            f"Expected custody OPENED, got {after_open['custody_status']}"
        )
        assert after_open["count_status"] == "PENDING", (
            f"The OPEN hop leaves the counting axis at PENDING, got {after_open['count_status']}"
        )

    def test_starting_the_session_advances_only_the_counting_axis(self, api):
        """PRD §3.4: "Starting a session moves it `SCHEDULED → IN_PROGRESS` and
        simultaneously moves the bag's counting axis `PENDING → COUNTING`, incrementing the
        bag's `version` by 1."
        PRD §3.2: "A bag carries **two independent state axes on the same row**, and this
        is the single most important structural fact about it."
        PRD §3.2: "Neither axis constrains the other's ordering; the only coupling between
        them is the explicit guards named below."

        Design: Difficulty/non_linear_state_machine/sealed_bag_custody_and_count_axes_advance_independently
        """
        scenario = setup_intake_ticket(bag_specs=[CURRENCY_BAG])
        bag = scenario["bag"]
        session = schedule_session(bag["id"], scenario["machine"]["id"])
        open_bag(bag["id"], bag["seal_number"])

        response = api.start_count_session(session["id"], make_teller_headers(TELLER_1))
        started = validate_success(response, 200)
        assert_count_session(started)
        assert started["status"] == "IN_PROGRESS", (
            f"Expected the session at IN_PROGRESS, got {started['status']}"
        )

        after_start = read_bag(bag["id"])
        assert after_start["count_status"] == "COUNTING", (
            f"The start moves the counting axis to COUNTING, got {after_start['count_status']}"
        )
        assert after_start["custody_status"] == "OPENED", (
            f"The custody axis stays OPENED across the start, got {after_start['custody_status']}"
        )


class TestMachineWindowOccupancy:
    def test_window_starting_inside_the_cleaning_buffer_conflicts(self, api):
        """PRD §3.4: "The machine must not be double-booked: take the requested occupation
        as the interval beginning at `window_start` and ending 15 minutes after
        `window_end` — a quarter-hour cleaning buffer is appended to every declared
        window's end, never to its start — and treat that interval as half-open, including
        its start instant and excluding its end instant. That extended interval must not
        intersect the identically extended interval of any other session on the same
        `counting_machine_id` that is currently `SCHEDULED` or `IN_PROGRESS`; an
        intersection is `ERR_MACHINE_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/counting_machine_half_open_window_plus_cleaning_buffer
        """
        scenario = setup_intake_ticket(
            bag_specs=[dict(CURRENCY_BAG), dict(CURRENCY_BAG)], declared_bag_count=2
        )
        machine_id = scenario["machine"]["id"]
        first_bag, second_bag = scenario["bags"]

        first_session = schedule_session(
            first_bag["id"], machine_id, "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z"
        )

        response = api.create_count_session(
            create_count_session_payload(
                second_bag["id"],
                machine_id,
                read_bag_version(second_bag["id"]),
                "2026-08-03T10:10:00Z",
                "2026-08-03T11:00:00Z",
            ),
            make_teller_headers(TELLER_1),
        )
        validate_error(response, ApiErrorId.ERR_MACHINE_WINDOW_CONFLICT.value)
        assert response.status_code == 409, (
            f"ERR_MACHINE_WINDOW_CONFLICT must be HTTP 409, got {response.status_code}"
        )
        assert read_session(first_session["id"])["status"] == "SCHEDULED", (
            "The incumbent session keeps its window"
        )

    def test_window_starting_exactly_where_the_buffer_ends_is_accepted(self, api):
        """PRD §3.4: "Because both intervals are half-open, a session whose extended
        interval ends exactly where another's begins does not conflict."
        PRD §3.4: "The session is created in `SCHEDULED` with `operator_user_id` captured
        from the caller's `X-User-ID`, `verifier_user_id` and `completed_at` null, and
        `counted_amount_cents`, `counted_note_count`, `counted_coin_weight_grams` and
        `seized_face_value_cents` all at 0."

        Design: Difficulty/resource_temporal_overlap/counting_machine_half_open_window_plus_cleaning_buffer
        """
        scenario = setup_intake_ticket(
            bag_specs=[dict(CURRENCY_BAG), dict(CURRENCY_BAG)], declared_bag_count=2
        )
        machine_id = scenario["machine"]["id"]
        first_bag, second_bag = scenario["bags"]

        first_session = schedule_session(
            first_bag["id"], machine_id, "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z"
        )

        response = api.create_count_session(
            create_count_session_payload(
                second_bag["id"],
                machine_id,
                read_bag_version(second_bag["id"]),
                "2026-08-03T10:15:00Z",
                "2026-08-03T11:00:00Z",
            ),
            make_teller_headers(TELLER_1),
        )
        second_session = validate_success(response, 201)
        assert_count_session(second_session)
        assert second_session["status"] == "SCHEDULED", (
            f"The 10:15 window is free, expected SCHEDULED, got {second_session['status']}"
        )
        assert second_session["operator_user_id"] == TELLER_1
        assert second_session["verifier_user_id"] is None
        assert second_session["counted_amount_cents"] == 0
        assert second_session["seized_face_value_cents"] == 0
        assert read_session(first_session["id"])["status"] == "SCHEDULED", (
            "The 09:00 session keeps its own window"
        )


class TestValidationLadderOnScheduling:
    def test_machine_type_mismatch_is_reported_ahead_of_the_window_conflict(self, api):
        """PRD §3.4: "The machine's `machine_type` must accept the bag's `bag_type`: a
        `CURRENCY_SORTER` accepts only `CURRENCY` bags, a `COIN_COUNTER` accepts only
        `COIN` bags, and a `MIXED_PROCESSOR` accepts all three of `CURRENCY`, `COIN` and
        `MIXED`; note in particular that a `MIXED` bag can only ever go on a
        `MIXED_PROCESSOR`. A mismatch is `ERR_MACHINE_TYPE_MISMATCH`."
        PRD §3.4: "When several of these fail together, the validation ladder in §2.6
        decides which is reported: the stale-version check first, then machine-type
        compatibility, then window conflict, then the past-window check."

        Design: Difficulty/priority_pair_validation_conflict/machine_type_mismatch_beats_window_conflict_on_count_session_create
        """
        scenario = setup_intake_ticket(
            bag_specs=[
                {
                    "bag_type": "COIN",
                    "declared_amount_cents": 50_000,
                    "declared_note_count": 0,
                    "declared_coin_weight_grams": 12_000,
                },
                dict(CURRENCY_BAG),
            ],
            declared_bag_count=2,
            machine_type="COIN_COUNTER",
        )
        machine_id = scenario["machine"]["id"]
        coin_bag, currency_bag = scenario["bags"]

        schedule_session(coin_bag["id"], machine_id, "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z")

        response = api.create_count_session(
            create_count_session_payload(
                currency_bag["id"],
                machine_id,
                read_bag_version(currency_bag["id"]),
                "2026-08-03T09:30:00Z",
                "2026-08-03T10:30:00Z",
            ),
            make_teller_headers(TELLER_1),
        )
        validate_error(response, ApiErrorId.ERR_MACHINE_TYPE_MISMATCH.value)
        assert response.status_code == 422, (
            f"ERR_MACHINE_TYPE_MISMATCH must be HTTP 422, got {response.status_code}"
        )

    def test_the_rejected_mismatch_books_no_window_and_leaves_the_incumbent_scheduled(self, api):
        """PRD §3.4: "Sessions can be read singly or listed, filtered by `sealed_bag_id`,
        `counting_machine_id` and `status`, with `limit` and `offset`."
        PRD §3.4: "Creating the new session increments the bag's `version` by 1, which is
        why two sessions cannot be scheduled back-to-back against the same observed bag
        version."
        PRD §3.4: "The machine's `machine_type` must accept the bag's `bag_type`: a
        `CURRENCY_SORTER` accepts only `CURRENCY` bags, a `COIN_COUNTER` accepts only
        `COIN` bags, and a `MIXED_PROCESSOR` accepts all three of `CURRENCY`, `COIN` and
        `MIXED`; note in particular that a `MIXED` bag can only ever go on a
        `MIXED_PROCESSOR`. A mismatch is `ERR_MACHINE_TYPE_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/machine_type_mismatch_beats_window_conflict_on_count_session_create
        """
        scenario = setup_intake_ticket(
            bag_specs=[
                {
                    "bag_type": "COIN",
                    "declared_amount_cents": 50_000,
                    "declared_note_count": 0,
                    "declared_coin_weight_grams": 12_000,
                },
                dict(CURRENCY_BAG),
            ],
            declared_bag_count=2,
            machine_type="COIN_COUNTER",
        )
        machine_id = scenario["machine"]["id"]
        coin_bag, currency_bag = scenario["bags"]

        coin_session = schedule_session(
            coin_bag["id"], machine_id, "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z"
        )
        version_before = read_bag_version(currency_bag["id"])

        response = api.create_count_session(
            create_count_session_payload(
                currency_bag["id"],
                machine_id,
                version_before,
                "2026-08-03T09:30:00Z",
                "2026-08-03T10:30:00Z",
            ),
            make_teller_headers(TELLER_1),
        )
        validate_error(response, ApiErrorId.ERR_MACHINE_TYPE_MISMATCH.value)

        assert read_session(coin_session["id"])["status"] == "SCHEDULED", (
            "The COIN bag's session keeps its machine window"
        )
        _, meta = validate_paginated(
            api.list_count_sessions(
                make_manager_headers(MANAGER_1), params={"sealed_bag_id": currency_bag["id"]}
            )
        )
        assert meta["total_count"] == 0, (
            f"No session may exist for the rejected CURRENCY bag, got {meta['total_count']}"
        )
        assert read_bag_version(currency_bag["id"]) == version_before, (
            "A rejected create must not increment the bag's version"
        )

    def test_scheduling_before_vault_receipt_is_refused(self, api):
        """PRD §3.4: "The bag's custody axis must have reached `VAULT_RECEIVED`; a bag
        still `SEALED` or `IN_TRANSIT` is `ERR_BAG_NOT_RECEIVED`."

        Design: Corner/validations/count_session_create_before_vault_receipt_returns_bag_not_received
        """
        scenario = setup_intake_ticket(
            bag_specs=[
                {
                    "bag_type": "CURRENCY",
                    "declared_amount_cents": 50_000,
                    "declared_note_count": 50,
                    "declared_coin_weight_grams": 0,
                }
            ],
            deliver=False,
        )
        bag = scenario["bag"]

        response = api.create_count_session(
            create_count_session_payload(
                bag["id"], scenario["machine"]["id"], bag["version"]
            ),
            make_teller_headers(TELLER_1),
        )
        validate_error(response, ApiErrorId.ERR_BAG_NOT_RECEIVED.value)
        assert response.status_code == 409

        assert read_bag(bag["id"])["custody_status"] == "SEALED"
        _, meta = validate_paginated(
            api.list_count_sessions(
                make_manager_headers(MANAGER_1), params={"sealed_bag_id": bag["id"]}
            )
        )
        assert meta["total_count"] == 0, (
            f"No session may exist for an undelivered bag, got {meta['total_count']}"
        )

    def test_a_second_session_on_the_same_bag_supersedes_the_first(self, api):
        """PRD §3.4: "Scheduling a session deliberately **supersedes** any earlier session
        on the same bag: every prior session for that `sealed_bag_id` still sitting in
        `SCHEDULED` moves `SCHEDULED → SUPERSEDED`, releasing its hold on its machine
        window."
        PRD §3.4: "Superseding changes nothing on the bag or the ticket — no field on
        either row moves as a result — and a `SUPERSEDED` session is terminal and can no
        longer be started or completed."

        Design: Corner/state_machines/count_session_create_supersedes_prior_scheduled_session_on_same_bag
        """
        scenario = setup_intake_ticket(
            bag_specs=[
                {
                    "bag_type": "CURRENCY",
                    "declared_amount_cents": 60_000,
                    "declared_note_count": 60,
                    "declared_coin_weight_grams": 0,
                }
            ]
        )
        bag = scenario["bag"]
        first_machine = scenario["machine"]
        second_machine = create_machine(scenario["vault"]["id"], machine_code="SORT-C15B")

        first_session = schedule_session(
            bag["id"], first_machine["id"], "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z"
        )
        second_session = schedule_session(
            bag["id"], second_machine["id"], "2026-08-03T09:30:00Z", "2026-08-03T10:30:00Z"
        )

        assert second_session["status"] == "SCHEDULED", (
            f"The newer session is SCHEDULED, got {second_session['status']}"
        )
        assert read_session(first_session["id"])["status"] == "SUPERSEDED", (
            "The prior SCHEDULED session on the same bag must move to SUPERSEDED"
        )

        sessions, meta = validate_paginated(
            api.list_count_sessions(
                make_manager_headers(MANAGER_1),
                params={"sealed_bag_id": bag["id"], "status": "SCHEDULED"},
            )
        )
        assert meta["total_count"] == 1, (
            f"Exactly one SCHEDULED session may remain on the bag, got {meta['total_count']}"
        )
        assert sessions[0]["id"] == second_session["id"]
        assert read_bag(bag["id"])["count_status"] == "PENDING", (
            "Superseding moves no field on the bag's counting axis"
        )


class TestStartGuards:
    def test_a_machine_in_maintenance_cannot_start_its_session(self, api):
        """PRD §3.4: "Three conditions gate the start: the bag must be `OPENED` on its
        custody axis, since the physical bag has to be cut open to be counted — anything
        less is `ERR_BAG_NOT_RECEIVED`; the bound machine's `status` must be `AVAILABLE`,
        and a machine in `MAINTENANCE` yields `ERR_MACHINE_UNAVAILABLE`; and the vault the
        machine sits on must not be `FROZEN`, which yields `ERR_VAULT_FROZEN`."

        Design: Corner/validations/machine_in_maintenance_blocks_count_session_start
        """
        scenario = setup_intake_ticket(
            bag_specs=[
                {
                    "bag_type": "CURRENCY",
                    "declared_amount_cents": 50_000,
                    "declared_note_count": 50,
                    "declared_coin_weight_grams": 0,
                }
            ],
            machine_status="MAINTENANCE",
        )
        bag = scenario["bag"]
        session = schedule_session(bag["id"], scenario["machine"]["id"])
        open_bag(bag["id"], bag["seal_number"])

        response = api.start_count_session(session["id"], make_teller_headers(TELLER_1))
        validate_error(response, ApiErrorId.ERR_MACHINE_UNAVAILABLE.value)
        assert response.status_code == 409

        assert read_session(session["id"])["status"] == "SCHEDULED", (
            "A refused start leaves the session SCHEDULED"
        )
        assert read_bag(bag["id"])["count_status"] == "PENDING", (
            "A refused start leaves the counting axis at PENDING"
        )

    def test_a_frozen_vault_blocks_the_count_from_starting(self, api):
        """PRD §2.10: "`FROZEN` blocks counting, cash-letter shipment, and coin release
        alike."
        PRD §2.10: "Where an operation reaches a vault indirectly, the gate still applies:
        starting a counting session reaches the vault through the counting machine the
        session occupies, and shipping a cash letter reaches it through the cash letter's
        own `vault_id`."
        PRD §2.10: "Attempting a gated operation against a `FROZEN` vault is rejected with
        `ERR_VAULT_FROZEN`."

        Design: Difficulty/cross_entity_state_dependency/count_session_start_gated_by_vault_posture_frozen
        """
        scenario = setup_intake_ticket(bag_specs=[dict(CURRENCY_BAG)])
        bag = scenario["bag"]
        session = schedule_session(bag["id"], scenario["machine"]["id"])
        open_bag(bag["id"], bag["seal_number"])

        frozen = set_posture(scenario["vault"]["id"], "FROZEN")
        assert frozen["posture"] == "FROZEN", f"Expected FROZEN, got {frozen['posture']}"

        response = api.start_count_session(session["id"], make_teller_headers(TELLER_1))
        validate_error(response, ApiErrorId.ERR_VAULT_FROZEN.value)
        assert response.status_code == 409, (
            f"ERR_VAULT_FROZEN must be HTTP 409, got {response.status_code}"
        )

    def test_the_frozen_rejection_leaves_both_bag_axes_untouched(self, api):
        """PRD §3.4: "Starting a session moves it `SCHEDULED → IN_PROGRESS` and
        simultaneously moves the bag's counting axis `PENDING → COUNTING`, incrementing the
        bag's `version` by 1."
        PRD §2.10: "Attempting a gated operation against a `FROZEN` vault is rejected with
        `ERR_VAULT_FROZEN`."

        Design: Difficulty/cross_entity_state_dependency/count_session_start_gated_by_vault_posture_frozen
        """
        scenario = setup_intake_ticket(bag_specs=[dict(CURRENCY_BAG)])
        bag = scenario["bag"]
        session = schedule_session(bag["id"], scenario["machine"]["id"])
        open_bag(bag["id"], bag["seal_number"])
        set_posture(scenario["vault"]["id"], "FROZEN")

        response = api.start_count_session(session["id"], make_teller_headers(TELLER_1))
        validate_error(response, ApiErrorId.ERR_VAULT_FROZEN.value)

        assert read_session(session["id"])["status"] == "SCHEDULED", (
            "A refused start leaves the session SCHEDULED"
        )
        refreshed = read_bag(bag["id"])
        assert refreshed["count_status"] == "PENDING", (
            f"The counting axis stays PENDING, got {refreshed['count_status']}"
        )
        assert refreshed["custody_status"] == "OPENED", (
            f"The custody axis stays OPENED, got {refreshed['custody_status']}"
        )
