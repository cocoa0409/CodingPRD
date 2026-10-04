"""ServiceContract and SLA credit tests: contract overlap, renewal window and
chaining, SLA breach credit tiering and per-event rounding, and breach
detection via the logical clock.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_active_contract,
    create_alert,
    create_contract,
    create_contract_payload,
    create_enterprise_with_site,
    get_success_data,
    validate_error,
    validate_success,
)

NA = TEST_USERS["network_architect_headers"]
FT = TEST_USERS["field_technician_headers"]


def _resolve_critical_outage(site_id, minutes_later_iso):
    """Raise + acknowledge + mitigate + resolve a CRITICAL OUTAGE alert after
    advancing the logical clock. Returns the resolved alert."""
    alert = create_alert(site_id, alert_class="OUTAGE", severity="CRITICAL")
    get_success_data(api_client.acknowledge_alert(site_id, alert["id"], FT))
    get_success_data(api_client.mitigate_alert(site_id, alert["id"], FT))
    get_success_data(api_client.set_clock({"to_iso8601": minutes_later_iso}, NA))
    return get_success_data(api_client.resolve_alert(site_id, alert["id"], FT))


class TestContractOverlap:
    def test_overlapping_same_tier_contract_rejected(self):
        """PRD §3.8: "Activating a `DRAFT` contract requires the Enterprise to
        be `ACTIVE` and forbids tier collisions: no other `ACTIVE` contract on
        the same Enterprise may have an overlapping term at the same `sla_tier`
        — such a collision is rejected with `ERR_CONTRACT_OVERLAP` (HTTP 409)."

        Design: Corner/endpoints/site_summary_returns_computed_aggregates
        """
        ent, _site = create_enterprise_with_site()
        create_active_contract(
            ent["id"], contract_code="K-1", sla_tier="STANDARD",
            contract_start_utc="2026-09-01T00:00:00Z",
            contract_end_utc="2027-09-01T00:00:00Z",
        )
        c2 = create_contract(
            ent["id"], contract_code="K-2", sla_tier="STANDARD",
            contract_start_utc="2027-01-01T00:00:00Z",
            contract_end_utc="2028-01-01T00:00:00Z",
        )
        resp = api_client.activate_contract(ent["id"], c2["id"], NA)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_OVERLAP)

    def test_overlapping_different_tier_allowed(self):
        """PRD §3.8: "no other `ACTIVE` contract on the same Enterprise may
        have an overlapping term at the same `sla_tier`" — the collision rule
        is scoped to the same tier.

        Design: Corner/endpoints/site_summary_returns_computed_aggregates
        """
        ent, _site = create_enterprise_with_site()
        create_active_contract(
            ent["id"], contract_code="K-1", sla_tier="STANDARD",
            contract_start_utc="2026-09-01T00:00:00Z",
            contract_end_utc="2027-09-01T00:00:00Z",
        )
        c2 = create_contract(
            ent["id"], contract_code="K-2", sla_tier="ENHANCED",
            contract_start_utc="2027-01-01T00:00:00Z",
            contract_end_utc="2028-01-01T00:00:00Z",
        )
        resp = api_client.activate_contract(ent["id"], c2["id"], NA)
        data = validate_success(resp)
        assert data["status"] == "ACTIVE"


class TestContractRenewal:
    def test_renew_within_final_month_creates_chained_draft(self):
        """PRD §3.8: "Renewal is available only in the contract's final month:
        the logical current time must be within 30 days of `contract_end_utc`
        (that is, at or after the instant 30 days before the end). Renewing
        moves the existing contract to `RENEWED` and creates a fresh contract
        in `DRAFT` whose start equals the old contract's end; the renewal
        request supplies the new term's `new_contract_end_utc`."

        Design: Corner/endpoints/site_summary_returns_computed_aggregates
        """
        ent, _site = create_enterprise_with_site()
        contract = create_active_contract(
            ent["id"], contract_code="K-R", sla_tier="STANDARD",
            contract_start_utc="2026-09-01T00:00:00Z",
            contract_end_utc="2027-09-01T00:00:00Z",
        )
        # Move the logical clock to within 30 days of the end.
        get_success_data(api_client.set_clock({"to_iso8601": "2027-08-15T00:00:00Z"}, NA))
        resp = api_client.renew_contract(
            ent["id"], contract["id"], {"new_contract_end_utc": "2028-09-01T00:00:00Z"}, NA
        )
        renewed = validate_success(resp, expected_status=201)
        assert renewed["status"] == "DRAFT"
        assert renewed["contract_start_utc"] == "2027-09-01T00:00:00Z"
        assert renewed["contract_end_utc"] == "2028-09-01T00:00:00Z"
        old = get_success_data(api_client.get_contract(contract["id"], NA))
        assert old["status"] == "RENEWED"

    def test_renew_outside_final_month_rejected(self):
        """PRD §3.8: "Renewal is available only in the contract's final month:
        the logical current time must be within 30 days of `contract_end_utc`
        (that is, at or after the instant 30 days before the end)."
        PRD §2.9: "requesting a transition the resource's current state does
        not allow yields `ERR_INVALID_STATE` (HTTP 409)".

        Design: Corner/endpoints/site_summary_returns_computed_aggregates
        """
        ent, _site = create_enterprise_with_site()
        contract = create_active_contract(
            ent["id"], contract_code="K-E", sla_tier="STANDARD",
            contract_start_utc="2026-09-01T00:00:00Z",
            contract_end_utc="2027-09-01T00:00:00Z",
        )
        # Logical clock is at the default 2026-09-01, a full year before the
        # end — renewal is not yet available.
        resp = api_client.renew_contract(
            ent["id"], contract["id"], {"new_contract_end_utc": "2028-09-01T00:00:00Z"}, NA
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestSlaBreachCredit:
    def test_single_critical_outage_applies_enhanced_tier_credit(self):
        """PRD §3.8: "The credit per breach event is a percentage of the
        contract's monthly fee — taken as a flat 100,000 cents per month for
        this platform — with the rate tiered by `sla_tier`: 5 percent for
        `STANDARD`, 10 percent for `ENHANCED`, and 20 percent for
        `MISSION_CRITICAL`. Each event's credit is rounded half-up to a whole
        cent, then the per-event credits for the month are summed; the
        resulting `sla_credit_applied_cents` is recorded on the alert and added
        to the Enterprise's `sla_credit_balance_cents`."

        Design: Corner/calculations/sla_breach_credit_constants_applied
        """
        ent, site = create_enterprise_with_site()
        create_active_contract(
            ent["id"], contract_code="K-E1", sla_tier="ENHANCED",
            contracted_max_outage_minutes_per_month=5,
            contract_start_utc="2026-09-01T00:00:00Z",
            contract_end_utc="2027-09-01T00:00:00Z",
        )
        alert = _resolve_critical_outage(site["id"], "2026-09-01T00:10:00Z")
        assert alert["sla_credit_applied_cents"] == 10000
        ent_after = get_success_data(api_client.get_enterprise(ent["id"], NA))
        assert ent_after["sla_credit_balance_cents"] == 10000

    def test_two_critical_outages_breach_mission_critical_contract(self):
        """PRD §3.8: "When the alert is an `OUTAGE` at `CRITICAL` severity, the
        downtime in minutes from `raised_at_utc` to `resolved_at_utc` is added
        to the running total of CRITICAL outage minutes for the current UTC
        calendar month, and if that cumulative total exceeds the covering
        contract's `contracted_max_outage_minutes_per_month`, the contract
        automatically flips from `ACTIVE` to `BREACHED` and an SLA credit is
        applied."
        PRD §3.8: "Each event's credit is rounded half-up to a whole cent, then
        the per-event credits for the month are summed".

        Design: Difficulty/dual_variant_calc/sla_credit_tiered_per_event_vs_monthly_flat
        """
        ent, site = create_enterprise_with_site()
        contract = create_active_contract(
            ent["id"], contract_code="K-MC", sla_tier="MISSION_CRITICAL",
            contracted_max_outage_minutes_per_month=30,
            contract_start_utc="2026-09-01T00:00:00Z",
            contract_end_utc="2027-09-01T00:00:00Z",
        )
        _resolve_critical_outage(site["id"], "2026-09-01T00:20:00Z")  # 20 min
        _resolve_critical_outage(site["id"], "2026-09-01T00:45:00Z")  # 25 min more

        # Cumulative 45 > 30 -> breach; the credit applies when the cumulative
        # total crosses the cap, so only the second event credits (20% of
        # 100_000).
        ent_after = get_success_data(api_client.get_enterprise(ent["id"], NA))
        assert ent_after["sla_credit_balance_cents"] == 20000
        contract_after = get_success_data(api_client.get_contract(contract["id"], NA))
        assert contract_after["status"] == "BREACHED"

    def test_under_budget_outage_does_not_breach(self):
        """PRD §3.8: "if that cumulative total exceeds the covering contract's
        `contracted_max_outage_minutes_per_month`, the contract automatically
        flips from `ACTIVE` to `BREACHED` and an SLA credit is applied" — under
        the budget no flip occurs.

        Design: Difficulty/dual_variant_calc/sla_credit_tiered_per_event_vs_monthly_flat
        """
        ent, site = create_enterprise_with_site()
        contract = create_active_contract(
            ent["id"], contract_code="K-OK", sla_tier="STANDARD",
            contracted_max_outage_minutes_per_month=60,
            contract_start_utc="2026-09-01T00:00:00Z",
            contract_end_utc="2027-09-01T00:00:00Z",
        )
        _resolve_critical_outage(site["id"], "2026-09-01T00:10:00Z")  # 10 min < 60
        contract_after = get_success_data(api_client.get_contract(contract["id"], NA))
        assert contract_after["status"] == "ACTIVE"
        ent_after = get_success_data(api_client.get_enterprise(ent["id"], NA))
        assert ent_after["sla_credit_balance_cents"] == 0
