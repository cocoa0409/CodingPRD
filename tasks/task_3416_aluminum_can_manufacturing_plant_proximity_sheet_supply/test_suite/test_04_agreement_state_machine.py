"""Supply agreement state machine: idempotency, terminal lockdown, sign window,
and the renegotiation cycle (PRD §2.7, §3.2)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    set_clock, create_plant, create_customer, create_agreement,
    create_active_agreement, sign_agreement, get_agreement,
    make_customer_planner_headers, manager, api_client,
)


class TestSignTwice:
    def test_sign_twice_returns_invalid_state_idempotency(self, api):
        """PRD §2.7 gate 6: "first the target resource's own from-state for the
        requested transition (`ERR_INVALID_STATE`, HTTP 409, including attempts
        made from terminal states)".

        Design: Corner/state_machines/sign_twice_returns_invalid_state_idempotency
        """
        set_clock()
        plant = create_plant()
        customer = create_customer()
        agreement = create_agreement(plant["id"], customer["id"])
        planner = make_customer_planner_headers(customer["id"])
        first = validate_success(api.sign_agreement(agreement["id"], planner))
        assert first["status"] == "ACTIVE"
        assert first["version"] == 2
        resp2 = api.sign_agreement(agreement["id"], planner)
        validate_error(resp2, ApiErrorId.ERR_INVALID_STATE)
        assert get_agreement(agreement["id"])["version"] == 2, \
            "a rejected sign must not mutate the agreement"


class TestTerminatedLockdown:
    def test_terminated_agreement_rejects_sign_renegotiate_and_amend(self, api):
        """PRD §3.2: "`EXPIRED` and `TERMINATED` are the agreement's terminal
        states, and any further transition attempted on them is rejected with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/terminated_agreement_rejects_sign_renegotiate_and_amend
        """
        set_clock()
        plant = create_plant()
        customer = create_customer()
        agreement = create_active_agreement(plant["id"], customer["id"])
        planner = make_customer_planner_headers(customer["id"])
        terminated = validate_success(
            api.terminate_agreement(agreement["id"], manager()))
        assert terminated["status"] == "TERMINATED"
        v_term = get_agreement(agreement["id"])["version"]
        validate_error(api.sign_agreement(agreement["id"], planner),
                       ApiErrorId.ERR_INVALID_STATE)
        validate_error(api.open_renegotiation(agreement["id"], planner),
                       ApiErrorId.ERR_INVALID_STATE)
        # Version-correct amend: rejection must come from the terminal state,
        # not from the concurrency gate.
        validate_error(api.amend_agreement(
            agreement["id"],
            {"expected_agreement_version": v_term,
             "conversion_cost_cents_per_1000": 1700}, manager()),
            ApiErrorId.ERR_INVALID_STATE)
        final = get_agreement(agreement["id"])
        assert final["status"] == "TERMINATED"
        assert final["version"] == v_term


class TestSignWindow:
    def test_sign_after_end_date_returns_agreement_window_passed(self, api):
        """PRD §3.2: "Signing is only possible while the logical clock's date is
        on or before the agreement's `end_date`; once the clock's date has
        passed the end date, signing is rejected with
        `ERR_AGREEMENT_WINDOW_PASSED`."

        Design: Corner/validations/sign_after_end_date_returns_agreement_window_passed
        """
        set_clock("2027-01-15T00:00:00Z")
        plant = create_plant()
        customer = create_customer()
        agreement = create_agreement(plant["id"], customer["id"],
                                     start_date="2026-01-01",
                                     end_date="2026-12-31")
        resp = api.sign_agreement(
            agreement["id"], make_customer_planner_headers(customer["id"]))
        err = validate_error(resp, ApiErrorId.ERR_AGREEMENT_WINDOW_PASSED)
        assert err["error_id"] != ApiErrorId.ERR_INVALID_STATE
        assert get_agreement(agreement["id"])["status"] == "DRAFT"


class TestRenegotiationCycle:
    def _cycled_agreement(self, api):
        """DRAFT -> ACTIVE -> RENEGOTIATING -> ACTIVE -> RENEGOTIATING -> ACTIVE;
        returns (agreement_id, customer_id, version trace)."""
        set_clock()
        plant = create_plant()
        customer = create_customer()
        agreement = create_agreement(plant["id"], customer["id"],
                                     committed_annual_units=12_000_000,
                                     pass_through_pct=0.9,
                                     conversion_cost_cents_per_1000=1500)
        planner = make_customer_planner_headers(customer["id"])
        versions = [agreement["version"]]
        signed = sign_agreement(agreement)
        versions.append(signed["version"])
        reneg1 = validate_success(
            api.open_renegotiation(agreement["id"], planner))
        versions.append(reneg1["version"])
        amend1 = validate_success(api.amend_agreement(
            agreement["id"], {"expected_agreement_version": reneg1["version"],
                              "conversion_cost_cents_per_1000": 1600}, manager()))
        versions.append(amend1["version"])
        reneg2 = validate_success(
            api.open_renegotiation(agreement["id"], planner))
        versions.append(reneg2["version"])
        amend2 = validate_success(api.amend_agreement(
            agreement["id"], {"expected_agreement_version": reneg2["version"],
                              "conversion_cost_cents_per_1000": 1700}, manager()))
        versions.append(amend2["version"])
        return agreement["id"], customer["id"], versions, amend1, reneg2, amend2

    def test_renegotiation_cycle_status_and_version_chain(self, api):
        """PRD §3.2: "This renegotiation cycle may loop `ACTIVE` →
        `RENEGOTIATING` → `ACTIVE` any number of times, and every sign,
        reopening, and amendment increments the agreement's `version` by 1."

        Design: Difficulty/non_linear_state_machine/supply_agreement_renegotiation_cycle_active_renegotiating_active
        """
        agr_id, _cust, versions, amend1, reneg2, amend2 = self._cycled_agreement(api)
        assert versions == [1, 2, 3, 4, 5, 6]
        assert amend1["status"] == "ACTIVE"
        assert reneg2["status"] == "RENEGOTIATING"
        assert amend2["status"] == "ACTIVE"

    def test_renegotiation_cycle_amend_applies_and_preserves_terms(self, api):
        """PRD §3.2: "a `PlantManager` then amends it back to `ACTIVE`, applying
        any subset of amended `committed_annual_units`, `pass_through_pct`,
        `conversion_cost_cents_per_1000`, and `end_date` — terms not supplied
        remain unchanged".

        Design: Difficulty/non_linear_state_machine/supply_agreement_renegotiation_cycle_active_renegotiating_active
        """
        agr_id, _cust, _v, _a1, _r2, _a2 = self._cycled_agreement(api)
        final = get_agreement(agr_id)
        assert final["conversion_cost_cents_per_1000"] == 1700
        assert final["pass_through_pct"] == 0.9, \
            "untouched terms survive both amends"
        assert final["committed_annual_units"] == 12_000_000
