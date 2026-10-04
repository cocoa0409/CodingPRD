"""Rate filings, fee configurations, and the regulatory fee gate."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_fee_config,
    create_approved_filing,
    create_application,
    create_cause_and_cohort,
    create_fee_config_payload,
    create_policyholder,
    create_quote,
    create_rate_filing_payload,
    get_success_data,
    set_clock,
    setup_state_fee,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

UNDERWRITER = TEST_USERS["underwriting_admin_headers"]


class TestRateFilingStateMachine:
    def test_two_filings_per_state_supersede_cycle(self, api):
        """PRD §3.1: "Approval is a crowning event: every other filing for the same state_code that was APPROVED transitions to SUPERSEDED in the same request, and the newly approved filing's approved_at is stamped with the current logical clock (approved_at remains null on filings that were never approved)."

        Design: Difficulty/non_linear_state_machine/rate_filing_two_filings_per_state_supersede_cycle
        """
        set_clock()
        f1 = create_approved_filing(
            state_code="TX",
            filing_mode="PCT_OF_PREMIUM",
            max_flat_fee_pct=0.25,
            max_flat_fee_cap_cents=20000,
        )
        f2_data = validate_success(
            api.create_rate_filing(
                create_rate_filing_payload(
                    state_code="TX",
                    max_flat_fee_pct=0.35,
                    max_flat_fee_cap_cents=30000,
                    filing_mode="ABSOLUTE_CENTS",
                ),
                UNDERWRITER,
            ),
            expected_status=201,
        )
        f2 = validate_success(api.approve_rate_filing(f2_data["id"], UNDERWRITER))
        assert f2["status"] == "APPROVED"
        assert f2["approved_at"] is not None
        f1_after = validate_success(api.get_rate_filing(f1["id"], UNDERWRITER))
        assert f1_after["status"] == "SUPERSEDED"

    def test_superseded_filing_counted_in_list_filter(self, api):
        """PRD §3.1: "every other filing for the same state_code that was APPROVED transitions to SUPERSEDED in the same request".
        PRD §2.3: "rate filings filter by state_code and status".

        Design: Difficulty/non_linear_state_machine/rate_filing_two_filings_per_state_supersede_cycle
        """
        set_clock()
        f1 = create_approved_filing(
            state_code="TX",
            filing_mode="PCT_OF_PREMIUM",
            max_flat_fee_pct=0.25,
            max_flat_fee_cap_cents=20000,
        )
        f2 = create_approved_filing(
            state_code="TX",
            filing_mode="ABSOLUTE_CENTS",
            max_flat_fee_pct=0.35,
            max_flat_fee_cap_cents=30000,
        )
        data, meta = validate_paginated(
            api.list_rate_filings(UNDERWRITER, params={"state_code": "TX", "status": "APPROVED"})
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in data] == [f2["id"]]

    def test_approve_rejected_filing_rejected(self, api):
        """PRD §3.1: "attempting to approve or reject a filing that is no longer SUBMITTED is rejected with ERR_FILING_NOT_SUBMITTED."

        Design: Corner/validations/approve_rejected_filing_rejected
        """
        set_clock()
        filing = validate_success(
            api.create_rate_filing(create_rate_filing_payload(state_code="TX"), UNDERWRITER),
            expected_status=201,
        )
        validate_success(api.reject_rate_filing(filing["id"], UNDERWRITER))
        resp = api.approve_rate_filing(filing["id"], UNDERWRITER)
        validate_error(resp, ApiErrorId.ERR_FILING_NOT_SUBMITTED)
        after = validate_success(api.get_rate_filing(filing["id"], UNDERWRITER))
        assert after["status"] == "REJECTED"


class TestFeeConfigGate:
    def test_activate_with_unapproved_filing_rejected(self, api):
        """PRD §3.2: "Activation is the strictest gate. Activating a config requires it to be DRAFT (anything else is ERR_INVALID_STATE), requires its referenced filing to be APPROVED (ERR_RATE_FILING_NOT_APPROVED)".

        Design: Corner/validations/activate_with_unapproved_filing_rejected
        """
        set_clock()
        filing = validate_success(
            api.create_rate_filing(create_rate_filing_payload(state_code="TX"), UNDERWRITER),
            expected_status=201,
        )
        fc = validate_success(
            api.create_fee_config(
                create_fee_config_payload(state_code="TX", filing_id=filing["id"]),
                UNDERWRITER,
            ),
            expected_status=201,
        )
        resp = api.activate_fee_config(fc["id"], UNDERWRITER)
        validate_error(resp, ApiErrorId.ERR_RATE_FILING_NOT_APPROVED)
        after = validate_success(api.get_fee_config(fc["id"], UNDERWRITER))
        assert after["status"] == "DRAFT"

    def test_fee_cap_violation_on_update(self, api):
        """PRD §3.2: "the fee must fit inside the filing's cap: when the filing's mode is ABSOLUTE_CENTS, flat_fee_cents must not exceed the filing's max_flat_fee_cap_cents; when the mode is PCT_OF_PREMIUM, flat_fee_pct must not exceed the filing's max_flat_fee_pct. A violation is rejected with ERR_FLAT_FEE_VIOLATES_FILING."

        Design: Corner/validations/fee_cap_violation_on_update
        """
        set_clock()
        filing = create_approved_filing(
            state_code="TX", filing_mode="PCT_OF_PREMIUM", max_flat_fee_pct=0.25
        )
        fc = validate_success(
            api.create_fee_config(
                create_fee_config_payload(state_code="TX", filing_id=filing["id"], flat_fee_pct=0.20),
                UNDERWRITER,
            ),
            expected_status=201,
        )
        resp = api.update_fee_config(
            fc["id"],
            {"flat_fee_pct": 0.40, "expected_fee_config_version": fc["version"]},
            UNDERWRITER,
        )
        validate_error(resp, ApiErrorId.ERR_FLAT_FEE_VIOLATES_FILING)
        after = validate_success(api.get_fee_config(fc["id"], UNDERWRITER))
        assert after["flat_fee_pct"] == 0.20

    def test_stale_version_rejected_and_draft_unchanged(self, api):
        """PRD §2.6: "if another writer has advanced that entity's version since the client last read it, the request is rejected with ERR_STALE_VERSION (HTTP 412), and the client must re-read before retrying."
        PRD §3.2: "An update to a DRAFT config is an OCC-guarded write as described in §2.6 and increments the config's version by one on success."

        Design: Difficulty/priority_pair_validation_conflict/stale_version_beats_fee_cap_violation_on_fee_update
        """
        set_clock()
        filing = create_approved_filing(
            state_code="TX", filing_mode="PCT_OF_PREMIUM", max_flat_fee_pct=0.25
        )
        fc = validate_success(
            api.create_fee_config(
                create_fee_config_payload(state_code="TX", filing_id=filing["id"], flat_fee_pct=0.20),
                UNDERWRITER,
            ),
            expected_status=201,
        )
        updated = validate_success(
            api.update_fee_config(
                fc["id"],
                {"flat_fee_pct": 0.22, "expected_fee_config_version": fc["version"]},
                UNDERWRITER,
            )
        )
        assert updated["version"] == fc["version"] + 1
        resp = api.update_fee_config(
            fc["id"],
            {"flat_fee_pct": 0.40, "expected_fee_config_version": fc["version"]},
            UNDERWRITER,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        after = validate_success(api.get_fee_config(fc["id"], UNDERWRITER))
        assert after["flat_fee_pct"] == 0.22
        assert after["version"] == updated["version"]

    def test_stale_version_reported_on_stale_and_cap_violating_update(self, api):
        """PRD §2.6: "Updating a DRAFT fee configuration requires expected_fee_config_version matching the fee config's current version." — "if another writer has advanced that entity's version since the client last read it, the request is rejected with ERR_STALE_VERSION (HTTP 412), and the client must re-read before retrying."
        PRD §2.8: "Authentication, authorization, and existence checks, in that order, precede every business validation on every endpoint; the generic state guard (ERR_INVALID_STATE, HTTP 409) follows them, then optimistic-concurrency staleness, then the business rules described throughout §3."

        Design: Difficulty/priority_pair_validation_conflict/stale_version_beats_fee_cap_violation_on_fee_update
        """
        set_clock()
        filing = create_approved_filing(
            state_code="TX", filing_mode="PCT_OF_PREMIUM", max_flat_fee_pct=0.25
        )
        fc = validate_success(
            api.create_fee_config(
                create_fee_config_payload(state_code="TX", filing_id=filing["id"], flat_fee_pct=0.20),
                UNDERWRITER,
            ),
            expected_status=201,
        )
        # One legitimate update advances the version.
        updated = validate_success(
            api.update_fee_config(
                fc["id"],
                {"flat_fee_pct": 0.22, "expected_fee_config_version": fc["version"]},
                UNDERWRITER,
            )
        )
        # A second update with the now-stale version AND a cap-violating value:
        # PRD §2.8 pins staleness before the §3 business rules.
        resp = api.update_fee_config(
            fc["id"],
            {"flat_fee_pct": 0.40, "expected_fee_config_version": fc["version"]},
            UNDERWRITER,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        after = validate_success(api.get_fee_config(fc["id"], UNDERWRITER))
        assert after["flat_fee_pct"] == 0.22

    def test_second_active_fee_config_same_state_rejected_then_succeeds_after_retire(self, api):
        """PRD §3.2: "requires that no other config for the same state_code is already ACTIVE; a collision is rejected with ERR_FEE_CONFIG_ALREADY_ACTIVE."

        Design: Difficulty/resource_temporal_overlap/active_fee_config_intervals_must_not_overlap_per_state
        """
        set_clock()
        filing = create_approved_filing(
            state_code="ND", filing_mode="PCT_OF_PREMIUM", max_flat_fee_pct=0.25
        )
        fc_a = create_active_fee_config(state_code="ND", filing_id=filing["id"], flat_fee_pct=0.20)
        fc_b = validate_success(
            api.create_fee_config(
                create_fee_config_payload(state_code="ND", filing_id=filing["id"], flat_fee_pct=0.22),
                UNDERWRITER,
            ),
            expected_status=201,
        )
        resp = api.activate_fee_config(fc_b["id"], UNDERWRITER)
        validate_error(resp, ApiErrorId.ERR_FEE_CONFIG_ALREADY_ACTIVE)
        validate_success(api.retire_fee_config(fc_a["id"], UNDERWRITER))
        fc_b_after = validate_success(api.activate_fee_config(fc_b["id"], UNDERWRITER))
        assert fc_b_after["status"] == "ACTIVE"
        fc_a_after = validate_success(api.get_fee_config(fc_a["id"], UNDERWRITER))
        assert fc_a_after["status"] == "RETIRED"

    def test_fee_config_activate_requires_draft_state(self, api):
        """PRD §3.2: "Activating a config requires it to be DRAFT (anything else is ERR_INVALID_STATE)".

        Design: Difficulty/resource_temporal_overlap/active_fee_config_intervals_must_not_overlap_per_state
        """
        set_clock()
        filing = create_approved_filing(state_code="ND", filing_mode="PCT_OF_PREMIUM")
        fc_a = create_active_fee_config(state_code="ND", filing_id=filing["id"], flat_fee_pct=0.20)
        # Re-activating an already ACTIVE config is a state violation.
        resp = api.activate_fee_config(fc_a["id"], UNDERWRITER)
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_INVALID_STATE.value, ApiErrorId.ERR_FEE_CONFIG_ALREADY_ACTIVE.value]
        )


class TestRetiredConfigBlocksBinding:
    def test_bind_fails_after_only_fee_config_retired(self, api):
        """PRD §3.2: "Retiring an ACTIVE config moves it to RETIRED; from that moment, new policy binds in that state fail with ERR_FEE_CONFIG_NOT_FOUND until a replacement config is activated."

        Design: Difficulty/non_linear_state_machine/fee_config_branching_activate_vs_retire_from_distinct_states
        """
        set_clock()
        cause, cohort = create_cause_and_cohort(2026)
        filing, fc = setup_state_fee(
            state_code="VT", filing_mode="PCT_OF_PREMIUM", max_flat_fee_pct=0.25, flat_fee_pct=0.20
        )
        validate_success(api.retire_fee_config(fc["id"], UNDERWRITER))
        ph = create_policyholder(state_code="VT")
        quote = create_quote(ph["id"], 100000, 50000)
        app = create_application(ph["id"], quote["id"])
        resp = api.approve_application(app["id"], UNDERWRITER)
        validate_error(resp, ApiErrorId.ERR_FEE_CONFIG_NOT_FOUND)
        app_after = validate_success(api.get_application(app["id"], UNDERWRITER))
        assert app_after["status"] == "UNDER_REVIEW"

    def test_retired_config_keeps_filing_approved(self, api):
        """PRD §3.2: "Retiring an ACTIVE config moves it to RETIRED".
        PRD §3.1: "Supersession deliberately does not cascade into fee configurations: a FeeConfig that references a now-SUPERSEDED filing keeps its own status untouched, and only new activations must reference a currently APPROVED filing."

        Design: Difficulty/non_linear_state_machine/fee_config_branching_activate_vs_retire_from_distinct_states
        """
        set_clock()
        filing, fc = setup_state_fee(state_code="VT", filing_mode="PCT_OF_PREMIUM")
        retired = validate_success(api.retire_fee_config(fc["id"], UNDERWRITER))
        assert retired["status"] == "RETIRED"
        filing_after = validate_success(api.get_rate_filing(filing["id"], UNDERWRITER))
        assert filing_after["status"] == "APPROVED"
