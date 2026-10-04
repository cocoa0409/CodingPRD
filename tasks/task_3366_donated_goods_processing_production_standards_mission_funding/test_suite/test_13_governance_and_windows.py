"""Org license cycle with its cascade, plus the two temporal-overlap regimes:
half-open territory windows and closed contract windows."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_allocation,
    create_donation,
    create_org,
    create_program,
    create_site,
    create_territory,
    create_territory_payload,
    create_workforce_contract_payload,
    current_org_version,
    get_org,
    list_allocations,
    make_contract_manager_headers,
    make_donation_attendant_headers,
    milestone_payload,
    sort_item_descriptor,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
REGULATOR = TEST_USERS["brand_regulator_headers"]


def _setup_org_with_pending_allocation():
    """Org + site + program + one PENDING allocation of 5000 + one RECEIVED
    donation (the sort probe for the org-wide write gate)."""
    org = create_org("Org Cycle")
    site = create_site(org["id"], name="Site C", site_type="STORE_DROP")
    prog = create_program(org["id"], name="Jobs")
    alloc = create_allocation(org["id"], prog["id"], 5000, creator_id="pd-1")
    donation = create_donation(site["id"], donor_name="Donor X", item_count=1)
    return org, site, prog, alloc, donation


def _sort_probe(site_id, donation_id):
    return api_client.sort_donation(
        donation_id,
        {"items": [sort_item_descriptor(category="TEXTILES",
                                        condition_grade="A",
                                        estimated_value_cents=100,
                                        weight_lbs=1)]},
        make_donation_attendant_headers(site_id))


class TestMemberOrgSuspendReinstateCycle:
    def test_suspend_cascades_pending_allocations_and_gates_writes(self, api):
        """PRD 3.1: "Suspension by a `BrandRegulator` takes an `ACTIVE`
        organization to `SUSPENDED` — any other starting state is rejected with
        `ERR_INVALID_STATE` — and cascades downward: every `PENDING` funding
        allocation belonging to that organization's mission programs is set to
        `CANCELLED`, while `APPROVED` allocations keep their reservation
        untouched."
        PRD 2.7: "Every org-scoped write — creating sites, standards, runs,
        lots, programs, allocations, contracts, or disposal tickets for the
        org; sorting, pricing, or selling its items; running its markdown
        events; approving, disbursing, reviewing, or attesting under it —
        requires the organization to be `ACTIVE`, and is otherwise rejected
        with `ERR_ORG_SUSPENDED` (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/member_org_suspend_reinstate_cycle
        """
        org, site, prog, alloc, donation = _setup_org_with_pending_allocation()
        suspended = validate_success(
            api_client.suspend_member_org(org["id"], REGULATOR))
        assert suspended["brand_license_status"] == "SUSPENDED"
        rows = list_allocations({"mission_program_id": prog["id"]})
        assert len(rows) == 1
        assert rows[0]["status"] == "CANCELLED", "suspend cascade on PENDING"
        probe = _sort_probe(site["id"], donation["id"])
        validate_error(probe, ApiErrorId.ERR_ORG_SUSPENDED)

    def test_reinstate_restores_writes_and_advances_version(self, api):
        """PRD 3.1: "Reinstatement takes a `SUSPENDED` organization back to
        `ACTIVE`, re-enabling org-scoped writes without altering any financial
        field."
        PRD 3.1: "Each of the two transitions advances the organization's
        `version` by one."

        Design: Difficulty/non_linear_state_machine/member_org_suspend_reinstate_cycle
        """
        org, site, _prog, _alloc, donation = _setup_org_with_pending_allocation()
        v_before = current_org_version(org["id"])
        api_client.suspend_member_org(org["id"], REGULATOR)
        reinstated = validate_success(
            api_client.reinstate_member_org(org["id"], REGULATOR))
        assert reinstated["brand_license_status"] == "ACTIVE"
        assert reinstated["version"] == v_before + 2, (
            "suspend +1 and reinstate +1")
        sorted_donation = validate_success(
            _sort_probe(site["id"], donation["id"]))
        assert sorted_donation["status"] == "SORTED"


class TestTerritoryHalfOpenAdjacency:
    def _setup_two_orgs_with_territory(self):
        org_a = create_org("Org TA")
        org_b = create_org("Org TB")
        create_territory(org_a["id"], "PNW-N", "2026-01-01T00:00:00Z",
                         effective_to="2027-01-01T00:00:00Z")
        return org_a, org_b

    def test_adjacent_window_accepted_crossing_rejected(self, api):
        """PRD 3.1: "Territory windows are half-open: a new assignment for a
        `region_code` already held by a *different* organization is rejected
        with `ERR_TERRITORY_WINDOW_OVERLAP` only when the half-open windows
        genuinely intersect; pure adjacency, where one window's `effective_to`
        equals the other's `effective_from`, is allowed, and two assignments to
        the same organization never conflict."
        PRD 3.1: "Assigning a territory records the holding `member_org_id`, a
        `region_code` such as PNW-NORTH, and a window running from
        `effective_from` (inclusive) to `effective_to` (exclusive, with a null
        `effective_to` meaning open-ended)."

        Design: Difficulty/resource_temporal_overlap/territory_half_open_adjacency
        """
        _org_a, org_b = self._setup_two_orgs_with_territory()
        adjacent = validate_success(api_client.create_territory(
            create_territory_payload(org_b["id"], region_code="PNW-N",
                                     effective_from="2027-01-01T00:00:00Z"),
            REGULATOR), 201)
        assert adjacent["region_code"] == "PNW-N"
        assert adjacent.get("effective_to") is None, "open-ended window"
        crossing = api_client.create_territory(
            create_territory_payload(org_b["id"], region_code="PNW-N",
                                     effective_from="2026-06-01T00:00:00Z",
                                     effective_to="2026-12-01T00:00:00Z"),
            REGULATOR)
        validate_error(crossing, ApiErrorId.ERR_TERRITORY_WINDOW_OVERLAP)

    def test_same_org_windows_never_conflict(self, api):
        """PRD 3.1: "Territory windows are half-open: a new assignment for a
        `region_code` already held by a *different* organization is rejected
        with `ERR_TERRITORY_WINDOW_OVERLAP` only when the half-open windows
        genuinely intersect; pure adjacency, where one window's `effective_to`
        equals the other's `effective_from`, is allowed, and two assignments to
        the same organization never conflict."

        Design: Difficulty/resource_temporal_overlap/territory_half_open_adjacency
        """
        org_a, _org_b = self._setup_two_orgs_with_territory()
        same_org = api_client.create_territory(
            create_territory_payload(org_a["id"], region_code="PNW-N",
                                     effective_from="2026-06-01T00:00:00Z",
                                     effective_to="2026-12-01T00:00:00Z"),
            REGULATOR)
        data = validate_success(same_org, 201)
        assert data["member_org_id"] == org_a["id"]


class TestContractClosedIntervalTouching:
    def _setup_org_with_dol_contract(self):
        org = create_org("Org CW")
        contract = validate_success(api_client.create_workforce_contract(
            create_workforce_contract_payload(
                org["id"],
                [milestone_payload(description="M1",
                                   target_date="2026-06-01T00:00:00Z",
                                   min_headcount=10, payout_cents=25000)],
                funding_agency="DOL", start_date="2026-03-01T00:00:00Z",
                end_date="2026-06-30T00:00:00Z", contract_value_cents=100000,
                enrolled_headcount=20),
            make_contract_manager_headers("cm-1")), 201)
        return org, contract

    def test_touching_window_rejected_next_day_accepted(self, api):
        """PRD 3.8: "The same organization and agency may not hold overlapping
        contracts: because the windows are closed intervals, even contracts
        that merely touch — one contract's `end_date` equal to another's
        `start_date` — count as overlapping and the later creation is rejected
        with `ERR_CONTRACT_WINDOW_OVERLAP`."
        PRD 3.8: "A `ContractManager` creates one with the operating
        `member_org_id`, the `funding_agency` name, a performance window from
        `start_date` through `end_date` — a *closed* interval, both dates
        inclusive — the total `contract_value_cents`, the currently
        `enrolled_headcount`, and an inline `milestones` list in which each
        entry supplies a `description`, a `target_date` due date, a
        `min_headcount` enrollment requirement, and a `payout_cents` value."

        Design: Difficulty/resource_temporal_overlap/contract_closed_interval_touching
        """
        org, _c1 = self._setup_org_with_dol_contract()
        touching = api_client.create_workforce_contract(
            create_workforce_contract_payload(
                org["id"],
                [milestone_payload(description="M1",
                                   target_date="2026-09-01T00:00:00Z",
                                   min_headcount=10, payout_cents=20000)],
                funding_agency="DOL", start_date="2026-06-30T00:00:00Z",
                end_date="2026-09-30T00:00:00Z", contract_value_cents=80000,
                enrolled_headcount=15),
            make_contract_manager_headers("cm-1"))
        validate_error(touching, ApiErrorId.ERR_CONTRACT_WINDOW_OVERLAP)
        next_day = api_client.create_workforce_contract(
            create_workforce_contract_payload(
                org["id"],
                [milestone_payload(description="M1",
                                   target_date="2026-09-01T00:00:00Z",
                                   min_headcount=10, payout_cents=20000)],
                funding_agency="DOL", start_date="2026-07-01T00:00:00Z",
                end_date="2026-09-30T00:00:00Z", contract_value_cents=80000,
                enrolled_headcount=15),
            make_contract_manager_headers("cm-1"))
        data = validate_success(next_day, 201)
        assert data["status"] == "ACTIVE"

    def test_overlap_only_within_same_agency(self, api):
        """PRD 3.8: "The same organization and agency may not hold overlapping
        contracts: because the windows are closed intervals, even contracts
        that merely touch — one contract's `end_date` equal to another's
        `start_date` — count as overlapping and the later creation is rejected
        with `ERR_CONTRACT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/contract_closed_interval_touching
        """
        org, _c1 = self._setup_org_with_dol_contract()
        other_agency = api_client.create_workforce_contract(
            create_workforce_contract_payload(
                org["id"],
                [milestone_payload(description="M1",
                                   target_date="2026-05-01T00:00:00Z",
                                   min_headcount=10, payout_cents=20000)],
                funding_agency="STATE-WIB", start_date="2026-03-01T00:00:00Z",
                end_date="2026-06-30T00:00:00Z", contract_value_cents=80000,
                enrolled_headcount=15),
            make_contract_manager_headers("cm-1"))
        data = validate_success(other_agency, 201)
        assert data["funding_agency"] == "STATE-WIB"
        same_agency = api_client.create_workforce_contract(
            create_workforce_contract_payload(
                org["id"],
                [milestone_payload(description="M1",
                                   target_date="2026-05-01T00:00:00Z",
                                   min_headcount=10, payout_cents=20000)],
                funding_agency="DOL", start_date="2026-04-01T00:00:00Z",
                end_date="2026-05-31T00:00:00Z", contract_value_cents=80000,
                enrolled_headcount=15),
            make_contract_manager_headers("cm-1"))
        validate_error(same_agency, ApiErrorId.ERR_CONTRACT_WINDOW_OVERLAP)
