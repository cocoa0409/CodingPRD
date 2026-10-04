"""Donor/recipient medical lifecycles, pair vetting, and pool entry."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_center,
    create_donor,
    create_in_pool_pair,
    create_pair_payload,
    create_recipient,
    get_success_data,
    make_center_coordinator_headers,
    reset_clock,
    setup_executing_chain,
    validate_error,
    validate_success,
)


class TestDonorMedicalCycle:
    def test_donor_medical_status_cyclic_hold_release(self, api):
        """PRD §3.6: "A `CenterCoordinator` may place a cleared donor on hold
        (moving `medical_status` from `CLEARED` to `ON_HOLD`)".
        PRD §3.6: "Release from hold returns the donor to `CLEARED`."
        PRD §3.2: "initial `surgery_state` is `PRE_SURGERY`".

        Design: Difficulty/non_linear_state_machine/donor_medical_status_cyclic_hold_release
        """
        reset_clock()
        center = create_center()
        donor = create_donor(center)
        coord = make_center_coordinator_headers(center["id"])
        for _ in range(2):
            held = validate_success(api.donor_medical_hold(donor["id"], coord))
            assert held["medical_status"] == "ON_HOLD"
            released = validate_success(api.donor_medical_release(donor["id"], coord))
            assert released["medical_status"] == "CLEARED"
        final = validate_success(api.get_donor(donor["id"], coord))
        assert final["medical_status"] == "CLEARED"
        assert final["surgery_state"] == "PRE_SURGERY"

    def test_donor_medical_hold_then_release_returns_cleared(self, api):
        """PRD §3.6: "A `CenterCoordinator` may place a cleared donor on hold
        (moving `medical_status` from `CLEARED` to `ON_HOLD`)".
        PRD §3.6: "Release from hold returns the donor to `CLEARED`."

        Design: Difficulty/non_linear_state_machine/donor_medical_status_cyclic_hold_release
        """
        reset_clock()
        center = create_center()
        donor = create_donor(center)
        coord = make_center_coordinator_headers(center["id"])
        get_success_data(api.donor_medical_hold(donor["id"], coord))
        released = validate_success(api.donor_medical_release(donor["id"], coord))
        assert released["medical_status"] == "CLEARED"
        assert released["surgery_state"] == "PRE_SURGERY"

    def test_invalid_donor_transition_hold_when_already_withdrawn(self, api):
        """PRD §3.2: "A donor's `medical_status` may move through `CLEARED`,
        `ON_HOLD`, and the terminal values `WITHDRAWN` and `DECEASED`".
        PRD §5: "`ERR_INVALID_STATE` | 409".

        Design: Corner/state_machines/invalid_donor_transition_hold_when_already_withdrawn
        """
        reset_clock()
        center = create_center()
        donor = create_donor(center)
        coord = make_center_coordinator_headers(center["id"])
        get_success_data(api.donor_withdraw(donor["id"], coord))
        resp = api.donor_medical_hold(donor["id"], coord)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        after = validate_success(api.get_donor(donor["id"], coord))
        assert after["medical_status"] == "WITHDRAWN"


class TestCenterLifecycle:
    def test_invalid_center_transition_reinstate_from_active(self, api):
        """PRD §3.1: "Reinstatement from `PROBATION` back to `ACTIVE` is
        permitted only while both thresholds are again below their respective
        limits" and "Reinstatement from `SUSPENDED` back to `ACTIVE` is
        permitted only when no chain whose `chain_state` is `LOCKED`,
        `SCHEDULED`, or `EXECUTING` references the center; otherwise the
        transition is rejected."
        PRD §5: "`ERR_CENTER_INVALID_STATE` | 409".

        Design: Corner/state_machines/invalid_center_transition_reinstate_from_active
        """
        reset_clock()
        center = create_center()
        resp = api.reinstate_center(center["id"], TEST_USERS["registry_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_CENTER_INVALID_STATE.value)


class TestPoolEntry:
    def test_pair_not_incompatible_error_triggered(self, api):
        """PRD §3.2: "Pool entry enforces genuine need: the donor and recipient
        must be ABO-cross-incompatible in the donation direction, or the donor
        must express at least one antigen in the recipient's
        `unacceptable_antigens` list, or — for a compatible-pair bypass — the
        request body must carry `compatible_pair_opt_in` set to true on a
        `PAIRED`-kind pair. If none of the three holds, pool entry is rejected
        with `ERR_PAIR_NOT_INCOMPATIBLE`."

        Design: Corner/errors/pair_not_incompatible_error_triggered
        """
        reset_clock()
        center_a = create_center()
        center_b = create_center()
        donor = create_donor(center_a, abo_type="O")  # O can give to anyone
        recipient = create_recipient(center_b, abo_type="A", unacceptable_antigens=[])
        coord = make_center_coordinator_headers(center_a["id"])
        pair = get_success_data(
            api.create_pair(
                create_pair_payload(donor["id"], recipient["id"], center_a["id"]), coord
            ),
            expected_status=201,
        )
        get_success_data(api.verify_pair(pair["id"], coord))
        resp = api.enter_pool(pair["id"], {}, coord)
        validate_error(resp, ApiErrorId.ERR_PAIR_NOT_INCOMPATIBLE.value)

    def test_chain_run_zero_pool_error_envelope(self, api):
        """PRD §3.3: "Execution requires that the run still be in `DRAFT`
        (otherwise `ERR_INVALID_STATE`) and that the candidate pool size — the
        number of `DonorRecipientPair` rows in `IN_POOL` — is at least
        `MIN_POOL_SIZE` of 2, otherwise `ERR_POOL_TOO_SMALL`."

        Design: Difficulty/boundary_precision_check/chain_run_zero_pool_returns_pool_too_small
        """
        reset_clock()
        run = get_success_data(
            api.create_chain_run({"run_label": "empty-pool"}, TEST_USERS["match_operator_headers"]),
            expected_status=201,
        )
        resp = api.execute_chain_run(
            run["id"],
            {"expected_run_version": run["version"]},
            TEST_USERS["match_operator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_POOL_TOO_SMALL.value)

    def test_chain_run_zero_pool_returns_pool_too_small(self, api):
        """PRD §3.3: "Execution requires that the run still be in `DRAFT`
        (otherwise `ERR_INVALID_STATE`) and that the candidate pool size — the
        number of `DonorRecipientPair` rows in `IN_POOL` — is at least
        `MIN_POOL_SIZE` of 2, otherwise `ERR_POOL_TOO_SMALL`."

        Design: Difficulty/boundary_precision_check/chain_run_zero_pool_returns_pool_too_small
        """
        reset_clock()
        operator = TEST_USERS["match_operator_headers"]
        run = get_success_data(
            api.create_chain_run({"run_label": "empty-pool"}, operator), expected_status=201
        )
        resp = api.execute_chain_run(
            run["id"], {"expected_run_version": run["version"]}, operator
        )
        validate_error(resp, ApiErrorId.ERR_POOL_TOO_SMALL.value)

    def test_chain_run_pool_size_boundary_min_pool_size(self, api):
        """PRD §3.3: "Execution requires that the run still be in `DRAFT`
        (otherwise `ERR_INVALID_STATE`) and that the candidate pool size — the
        number of `DonorRecipientPair` rows in `IN_POOL` — is at least
        `MIN_POOL_SIZE` of 2, otherwise `ERR_POOL_TOO_SMALL`."

        Design: Difficulty/boundary_precision_check/chain_run_pool_size_boundary_min_pool_size
        """
        reset_clock()
        center_a = create_center()
        center_b = create_center()
        create_in_pool_pair(center_a, center_b, donor_abo="A", recipient_abo="B")
        operator = TEST_USERS["match_operator_headers"]
        run1 = get_success_data(
            api.create_chain_run({"run_label": "pool-1"}, operator), expected_status=201
        )
        # Pool size 1 < MIN_POOL_SIZE 2.
        resp = api.execute_chain_run(
            run1["id"], {"expected_run_version": run1["version"]}, operator
        )
        validate_error(resp, ApiErrorId.ERR_POOL_TOO_SMALL.value)
        # Add a second pair; pool size 2 == MIN_POOL_SIZE -> executes.
        create_in_pool_pair(center_b, center_a, donor_abo="B", recipient_abo="A")
        run2 = get_success_data(
            api.create_chain_run({"run_label": "pool-2"}, operator), expected_status=201
        )
        executed = validate_success(
            api.execute_chain_run(
                run2["id"], {"expected_run_version": run2["version"]}, operator
            )
        )
        assert executed["run_state"] == "EXECUTED"

    def test_chain_run_pool_size_at_threshold_executes(self, api):
        """PRD §3.3: "the candidate pool size — the number of
        `DonorRecipientPair` rows in `IN_POOL` — is at least `MIN_POOL_SIZE` of
        2, otherwise `ERR_POOL_TOO_SMALL`."

        Design: Difficulty/boundary_precision_check/chain_run_pool_size_boundary_min_pool_size
        """
        reset_clock()
        center_a = create_center()
        center_b = create_center()
        create_in_pool_pair(center_a, center_b, donor_abo="A", recipient_abo="B")
        create_in_pool_pair(center_b, center_a, donor_abo="B", recipient_abo="A")
        operator = TEST_USERS["match_operator_headers"]
        run = get_success_data(
            api.create_chain_run({"run_label": "pool-ok"}, operator), expected_status=201
        )
        executed = validate_success(
            api.execute_chain_run(
                run["id"], {"expected_run_version": run["version"]}, operator
            )
        )
        assert executed["run_state"] == "EXECUTED"


class TestPostNephrectomyGuards:
    def test_post_nephrectomy_withdrawal_forbidden(self, api):
        """PRD §3.6: "A donor in `CLEARED` or `ON_HOLD` may be withdrawn — but
        only while `surgery_state` is not `NEPHRECTOMY_DONE`, otherwise
        `ERR_DONOR_POST_NEPHRECTOMY`."

        Design: Corner/validations/post_nephrectomy_withdrawal_forbidden
        """
        ctx = setup_executing_chain()
        donor = ctx["p1"]["donor"]
        coord = make_center_coordinator_headers(ctx["center_a"]["id"])
        get_success_data(api.complete_nephrectomy(donor["id"], coord))
        resp = api.donor_withdraw(donor["id"], coord)
        validate_error(resp, ApiErrorId.ERR_DONOR_POST_NEPHRECTOMY.value)

    def test_post_nephrectomy_withdrawal_keeps_donor_state(self, api):
        """PRD §3.6: "A donor in `CLEARED` or `ON_HOLD` may be withdrawn — but
        only while `surgery_state` is not `NEPHRECTOMY_DONE`, otherwise
        `ERR_DONOR_POST_NEPHRECTOMY`."

        Design: Corner/validations/post_nephrectomy_withdrawal_forbidden
        """
        ctx = setup_executing_chain()
        donor = ctx["p1"]["donor"]
        coord = make_center_coordinator_headers(ctx["center_a"]["id"])
        completed = validate_success(api.complete_nephrectomy(donor["id"], coord))
        assert completed["surgery_state"] == "NEPHRECTOMY_DONE"
        validate_error(
            api.donor_withdraw(donor["id"], coord),
            ApiErrorId.ERR_DONOR_POST_NEPHRECTOMY.value,
        )
        after = validate_success(api.get_donor(donor["id"], coord))
        assert after["surgery_state"] == "NEPHRECTOMY_DONE"
        assert after["medical_status"] == "CLEARED"
