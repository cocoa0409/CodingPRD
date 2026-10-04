"""Transitive cascades: permit expiry suspends its station (PRD §2.5, §3.3);
contract termination suspends — and re-activation revives — the site
(PRD §3.1, §3.2).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    set_clock, create_site, create_planned_station, file_and_issue_permit,
    create_active_contract, create_supply_contract_payload,
    MANAGER, COMPLIANCE,
)


def _setup_station_in_construction_with_expiring_fire_permit(api):
    site = create_site(code="S-EXP")
    station = create_planned_station(
        site["id"], station_code="ST-E", capacity_kg_per_day=200,
        storage_capacity_kg=500, construction_start="2026-10-01",
        construction_end="2026-11-01")
    file_and_issue_permit(station["id"], "CONSTRUCTION", expiry_date="2027-01-01")
    fire = file_and_issue_permit(station["id"], "FIRE", expiry_date="2026-10-10")
    validate_success(api.start_construction(station["id"], MANAGER))
    return site, station, fire


class TestPermitExpirySuspendsStation:
    def test_clock_past_expiry_expires_permit_and_suspends_station(self, api):
        """PRD §2.5: "A permit in `ISSUED` whose `expiry_date` is before the
        current date moves to `EXPIRED`, which suspends any station of that
        permit sitting in `PERMITTED` or `CONSTRUCTION`."

        Design: Difficulty/transitive_cascade/permit_expiry_suspends_station
        """
        _site, station, fire = \
            _setup_station_in_construction_with_expiring_fire_permit(api)
        set_clock("2026-10-11T00:00:00Z")
        permit = get_success_data(api.get_permit(fire["id"], COMPLIANCE))
        assert permit["status"] == "EXPIRED", "clock past expiry_date expires the permit"
        station_after = get_success_data(api.get_station(station["id"], COMPLIANCE))
        assert station_after["construction_status"] == "SUSPENDED", (
            "the permit mutation cascades to the station (link 2)")

    def test_suspended_station_cannot_be_commissioned(self, api):
        """PRD §2.10: "Fourth, transition legality: the target resource must be
        in a valid from-state for the requested action (`ERR_INVALID_STATE`,
        HTTP 409)."
        PRD §3.3: "There is no path back: the station remains `SUSPENDED` (note
        this station-level `SUSPENDED` is distinct from the site-level status
        of the same name)."

        Design: Difficulty/transitive_cascade/permit_expiry_suspends_station
        """
        _site, station, _fire = \
            _setup_station_in_construction_with_expiring_fire_permit(api)
        set_clock("2026-10-11T00:00:00Z")
        resp = api.commission_station(station["id"], COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def _setup_two_contracts(api):
    """Site with c1 ACTIVE (DELIVERED_LIQUID) and c2 DRAFT (PIPELINE) —
    different supply modes may overlap freely."""
    site = create_site(code="S-SUS")
    c1 = create_active_contract(
        site["id"], supply_mode="DELIVERED_LIQUID", base_price_per_kg=2.0,
        reliability_sla_pct=99.0, committed_monthly_kg=50)
    c2 = get_success_data(api.create_supply_contract(
        site["id"], create_supply_contract_payload(
            supply_mode="PIPELINE", base_price_per_kg=1.8,
            reliability_sla_pct=99.9, committed_monthly_kg=50), MANAGER))
    return site, c1, c2


class TestContractTerminationSuspendsSite:
    def test_terminating_last_active_contract_suspends_site(self, api):
        """PRD §3.2: "Or a `SiteManager` terminates it, moving it to
        `TERMINATED` and stamping `terminated_at` with the current timestamp"
        PRD §3.1: "when the last `ACTIVE` supply contract of an `ACTIVE` site
        expires or is terminated, the site cascades to `SUSPENDED`; when a
        contract later activates while the site is `SUSPENDED`, the site
        cascades back to `ACTIVE`."

        Design: Difficulty/transitive_cascade/contract_termination_suspends_site
        """
        site, c1, _c2 = _setup_two_contracts(api)
        terminated = validate_success(
            api.terminate_supply_contract(site["id"], c1["id"], MANAGER))
        assert terminated["status"] == "TERMINATED"
        assert terminated["terminated_at"] is not None, "termination stamps terminated_at"
        site_after = get_success_data(api.get_site(site["id"], MANAGER))
        assert site_after["status"] == "SUSPENDED", (
            "no ACTIVE contract remains, so the site cascades to SUSPENDED")

    def test_activating_new_contract_revives_suspended_site(self, api):
        """PRD §3.1: "when the last `ACTIVE` supply contract of an `ACTIVE`
        site expires or is terminated, the site cascades to `SUSPENDED`; when a
        contract later activates while the site is `SUSPENDED`, the site
        cascades back to `ACTIVE`."

        Design: Difficulty/transitive_cascade/contract_termination_suspends_site
        """
        site, c1, c2 = _setup_two_contracts(api)
        validate_success(api.terminate_supply_contract(site["id"], c1["id"], MANAGER))
        validate_success(api.activate_supply_contract(site["id"], c2["id"], MANAGER))
        site_after = get_success_data(api.get_site(site["id"], MANAGER))
        assert site_after["status"] == "ACTIVE", "activation reverses the suspension"
        c1_after = get_success_data(api.get_supply_contract(c1["id"], MANAGER))
        assert c1_after["status"] == "TERMINATED", "the terminated contract is untouched"
