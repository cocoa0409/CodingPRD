"""Connection lifecycle: token lapse, refresh cap, reauthorization and epoch steps."""
from test_helpers import (
    api_client, validate_error, validate_success, get_success_data,
    setup_basic_scenario, expire_token, force_reauth, rotate_epoch,
    create_connection,
    ApiErrorId, make_member_headers,
)


class TestTokenLapseAndRecovery:
    def test_expiring_a_token_moves_the_connection_to_token_expired(self, api):
        """PRD §3.6: "An operator can expire a connection's credential, which attempts
        the `CONNECTED → TOKEN_EXPIRED` transition and stamps `token_expires_at` with
        the current logical instant."

        Design: Difficulty/transitive_cascade/tc_token_lapse_pauses_workflow_then_blocks_resume
        """
        scenario = setup_basic_scenario()
        expire_token(scenario["connection"]["id"])
        connection = get_success_data(
            api_client.get_connection(scenario["connection"]["id"], scenario["owner_headers"]))
        assert connection["status"] == "TOKEN_EXPIRED"

    def test_run_charge_against_expired_token_is_refused(self, api):
        """PRD §3.3: "the connection referenced by the action about to be charged must
        be `CONNECTED` at the moment the charge is evaluated, and a charge evaluated
        against a `TOKEN_EXPIRED` connection is refused with
        `ERR_CONNECTION_TOKEN_EXPIRED` (HTTP 422)."

        Design: Difficulty/transitive_cascade/tc_token_lapse_pauses_workflow_then_blocks_resume
        """
        scenario = setup_basic_scenario(allowance=100)
        expire_token(scenario["connection"]["id"])
        res = api_client.dispatch_run(scenario["workflow"]["id"], {"charge": "success"},
                                      scenario["owner_headers"])
        validate_error(res, ApiErrorId.ERR_CONNECTION_TOKEN_EXPIRED.value)
        workflow = get_success_data(
            api_client.get_workflow(scenario["workflow"]["id"], scenario["owner_headers"]))
        assert workflow["status"] == "PAUSED"
        assert workflow["pause_reason"] == "TOKEN_EXPIRED"

    def test_resume_is_blocked_while_the_credential_is_still_lapsed(self, api):
        """PRD §3.2: "a workflow that was paused because its credential lapsed may only
        resume when every connection its actions reference is back to `CONNECTED`"

        Design: Difficulty/transitive_cascade/tc_token_lapse_pauses_workflow_then_blocks_resume
        """
        scenario = setup_basic_scenario(allowance=100)
        expire_token(scenario["connection"]["id"])
        api_client.dispatch_run(scenario["workflow"]["id"], {"charge": "success"},
                                scenario["owner_headers"])
        res = api_client.resume_workflow(scenario["workflow"]["id"], scenario["owner_headers"])
        validate_error(res, ApiErrorId.ERR_CONNECTION_INVALID_STATE.value)

    def test_resume_succeeds_once_the_credential_is_refreshed(self, api):
        """PRD §3.2: "but only once the condition that stopped it has genuinely cleared:
        a workflow that was paused because its credential lapsed may only resume when
        every connection its actions reference is back to `CONNECTED`"

        Design: Difficulty/transitive_cascade/tc_token_lapse_pauses_workflow_then_blocks_resume
        """
        scenario = setup_basic_scenario(allowance=100)
        expire_token(scenario["connection"]["id"])
        api_client.dispatch_run(scenario["workflow"]["id"], {"charge": "success"},
                                scenario["owner_headers"])
        get_success_data(api_client.refresh_connection(
            scenario["connection"]["id"], make_member_headers(scenario["member"]["id"])))
        resumed = get_success_data(
            api_client.resume_workflow(scenario["workflow"]["id"], scenario["owner_headers"]))
        assert resumed["status"] == "ACTIVE"
        assert resumed["pause_reason"] is None


class TestRefreshCap:
    def test_refreshing_a_live_connection_is_refused(self, api):
        """PRD §3.6: "A refresh attempted against a connection that is not
        `TOKEN_EXPIRED` — including one already `CONNECTED` or already
        `REAUTH_REQUIRED` — is refused with `ERR_CONNECTION_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/transitive_cascade/tc_charge_pauses_workflow_then_expires_connection_then_blocks_migration
        """
        scenario = setup_basic_scenario()
        res = api_client.refresh_connection(
            scenario["connection"]["id"], make_member_headers(scenario["member"]["id"]))
        validate_error(res, ApiErrorId.ERR_CONNECTION_INVALID_STATE.value)

    def test_exhausting_the_refresh_cap_forces_reauthorization(self, api):
        """PRD §3.6: "A refresh attempted once the cap is spent, which the platform
        detects when `refresh_count` already stands at 5, is refused with
        `ERR_TOKEN_REFRESH_CAP_EXHAUSTED` (HTTP 409) and instead forces the
        `TOKEN_EXPIRED → REAUTH_REQUIRED` transition, stamping `reauth_requested_at`
        with the current instant."

        Design: Difficulty/transitive_cascade/tc_charge_pauses_workflow_then_expires_connection_then_blocks_migration
        """
        scenario = setup_basic_scenario()
        res = force_reauth(scenario["connection"]["id"], scenario["member"]["id"])
        validate_error(res, ApiErrorId.ERR_TOKEN_REFRESH_CAP_EXHAUSTED.value)
        connection = get_success_data(
            api_client.get_connection(scenario["connection"]["id"], scenario["owner_headers"]))
        assert connection["status"] == "REAUTH_REQUIRED"

    def test_exhausted_envelope_with_large_charge_fails_the_action(self, api):
        """PRD §3.4: "An action whose retry envelope is exhausted while its charged cost
        reached at least one full dollar — that is, a charged cost of 100 cents or more —
        undergoes the `RUNNING → FAILED` transition, records a `FAILED_PERMANENT` event,
        and is charged nothing for that final attempt"

        Design: Corner/calculations/cal_retry_envelope_floors_at_one_attempt
        """
        # The polled action's charged cost is comfortably above a full dollar (the
        # 50-cent surcharge alone is 400 cents for 8 whole tasks), so exhausting
        # the envelope on a live credential is the permanent-failure path of §3.4.
        scenario = setup_basic_scenario(allowance=200)
        res = api_client.dispatch_run(
            scenario["workflow"]["id"],
            {"charge": "forced_failure", "forced_failure": True, "max_retries": 1},
            scenario["owner_headers"])
        validate_success(res, 201)
        action = get_success_data(
            api_client.get_action(scenario["action"]["id"], scenario["owner_headers"]))
        assert action["status"] == "FAILED"


class TestEpochSteps:
    def test_second_opening_occupation_in_the_same_epoch_is_refused(self, api):
        """PRD §3.6: "An account may hold at most one OPENING step and at most one
        CLOSING step in any single epoch, and a second request naming a step that has
        already been occupied in this epoch is refused with `ERR_DUPLICATE_EPOCH_STEP`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/ov_epoch_step_exact_slot_already_occupied
        """
        scenario = setup_basic_scenario(allowance=100)
        member_headers = make_member_headers(scenario["member"]["id"])
        conn = scenario["connection"]["id"]
        expire_token(conn)
        first = get_success_data(api_client.refresh_connection(conn, member_headers,
                                                               payload={"charge": "OPENING"}))
        assert first["status"] == "CONNECTED"
        expire_token(conn)
        res = api_client.refresh_connection(conn, member_headers, payload={"charge": "OPENING"})
        validate_error(res, ApiErrorId.ERR_DUPLICATE_EPOCH_STEP.value)

    def test_opening_occupation_succeeds_while_the_slot_is_free(self, api):
        """PRD §3.6: "Refreshing a connection may occupy the account's **OPENING** step,
        and reauthorizing or disconnecting may occupy its **CLOSING** step, depending on
        the `charge` the caller names on the request."

        Design: Difficulty/resource_temporal_overlap/ov_epoch_step_exact_slot_already_occupied
        """
        scenario = setup_basic_scenario(allowance=100)
        member_headers = make_member_headers(scenario["member"]["id"])
        expire_token(scenario["connection"]["id"])
        res = api_client.refresh_connection(scenario["connection"]["id"], member_headers,
                                            payload={"charge": "OPENING"})
        refreshed = validate_success(res, 200)
        assert refreshed["status"] == "CONNECTED"

    def test_disconnect_releases_the_opening_step_for_the_next_epoch(self, api):
        """PRD §3.6: "Occupying the CLOSING step by reauthorizing or disconnecting also
        releases the OPENING step's occupation, which is the compensation that restores
        the step allocation to its pre-epoch total — the next epoch may then open
        normally."

        Design: Difficulty/compensating_invariant/ci_disconnect_releases_primary_connection_step_occupation
        """
        scenario = setup_basic_scenario(allowance=100)
        member_headers = make_member_headers(scenario["member"]["id"])
        # Disconnecting a credential is terminal (PRD §3.6), so the next epoch is
        # opened on a fresh credential of the same account rather than on the
        # disconnected one — the released slot is an account-level allocation.
        first = create_connection(scenario["account"]["id"], scenario["integration"]["id"],
                                  scenario["member"]["id"])
        expire_token(first["id"])
        occupied = get_success_data(api_client.refresh_connection(
            first["id"], member_headers, payload={"charge": "OPENING"}))
        assert occupied["status"] == "CONNECTED"
        released = get_success_data(api_client.disconnect_connection(
            first["id"], member_headers, payload={"charge": "CLOSING"}))
        assert released["status"] == "DISCONNECTED"
        rotate_epoch(scenario["account"]["id"])
        second = create_connection(scenario["account"]["id"], scenario["integration"]["id"],
                                   scenario["member"]["id"])
        expire_token(second["id"])
        again = get_success_data(api_client.refresh_connection(
            second["id"], member_headers, payload={"charge": "OPENING"}))
        assert again["status"] == "CONNECTED"

    def test_next_epoch_opening_step_is_free_after_the_compensating_disconnect(self, api):
        """PRD §3.6: "Occupying the CLOSING step by reauthorizing or disconnecting also
        releases the OPENING step's occupation, which is the compensation that restores
        the step allocation to its pre-epoch total — the next epoch may then open
        normally."

        Design: Difficulty/compensating_invariant/ci_disconnect_releases_primary_connection_step_occupation
        """
        scenario = setup_basic_scenario(allowance=100)
        member_headers = make_member_headers(scenario["member"]["id"])
        first = create_connection(scenario["account"]["id"], scenario["integration"]["id"],
                                  scenario["member"]["id"])
        expire_token(first["id"])
        get_success_data(api_client.refresh_connection(first["id"], member_headers,
                                                       payload={"charge": "OPENING"}))
        get_success_data(api_client.disconnect_connection(first["id"], member_headers,
                                                          payload={"charge": "CLOSING"}))
        rotate_epoch(scenario["account"]["id"])
        second = create_connection(scenario["account"]["id"], scenario["integration"]["id"],
                                   scenario["member"]["id"])
        expire_token(second["id"])
        res = api_client.refresh_connection(second["id"], member_headers,
                                            payload={"charge": "OPENING"})
        refreshed = validate_success(res, 200)
        assert refreshed["status"] == "CONNECTED"