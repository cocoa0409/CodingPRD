"""Half-open service windows and the reservation pool (PRD §3.2, §3.3)."""
from test_helpers import (
    TEST_USERS,
    add_product_line,
    api_client,
    confirm_receipt,
    create_active_product,
    create_approved_partner,
    create_season,
    declare_capacity,
    get_allocation,
    get_partner,
    get_profile,
    register_claim,
    set_clock,
    ship_allocation,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
PLANNER = TEST_USERS["planner_headers"]
FULFILL = TEST_USERS["fulfillment_headers"]


class TestHalfOpenCapacityWindows:
    """Difficulty/resource_temporal_overlap — adjacency is not overlap."""

    def _partner_with_early_window(self):
        set_clock("2026-09-01T00:00:00Z")
        create_season()
        partner = create_approved_partner(
            legal_name="Omicron Family Shelter",
            partner_type="DOMESTIC_VIOLENCE_SHELTER",
            operating_region="SOUTHEAST",
            operating_state_code="FL",
            registry_id="FL-CHR-150015",
            ein="100200700",
            unduplicated_recipients_per_facility=7000,
            need_tier="HIGH",
        )
        declare_capacity(
            partner["id"], max_allocatable_units=3000,
            effective_from="2026-08-01T00:00:00Z", effective_to="2026-10-01T00:00:00Z",
        )
        return partner

    def test_overlapping_window_is_refused(self, api):
        """PRD §3.2: "A profile's `effective_from` instant is when its ceiling becomes readable and its `effective_to` instant when it stops being selectable; when a successor profile for the same partner and season carries a later `effective_from`, the earlier profile becomes `SUPERSEDED`, which is terminal."
        PRD §2.6: "When two selectable profiles resolve for the same partner and season the commitment is refused outright with `ERR_CAPACITY_PROFILE_AMBIGUOUS`, and when the covering liability's available units fall short of `allocated_units` the shortfall is reported with `ERR_LIABILITY_INSUFFICIENT` rather than absorbed."

        Design: Difficulty/resource_temporal_overlap/half_open_partner_service_windows_reject_an_overlapping_allocation
        """
        partner = self._partner_with_early_window()

        res = api_client.create_capacity_profile(
            partner["id"],
            {
                "season_code": "2026-Q3",
                "max_allocatable_units": 4000,
                "effective_from": "2026-09-30T23:59:59Z",
                "effective_to": "2026-12-01T00:00:00Z",
            },
            COORD,
        )
        validate_error(res, "ERR_CAPACITY_PROFILE_AMBIGUOUS", expected_status=409)

    def test_adjacent_window_is_accepted_and_is_the_selectable_one(self, api):
        """PRD §3.2: "A profile's `effective_from` instant is when its ceiling becomes readable and its `effective_to` instant when it stops being selectable; when a successor profile for the same partner and season carries a later `effective_from`, the earlier profile becomes `SUPERSEDED`, which is terminal."
        PRD §2.6: "When two selectable profiles resolve for the same partner and season the commitment is refused outright with `ERR_CAPACITY_PROFILE_AMBIGUOUS`, and when the covering liability's available units fall short of `allocated_units` the shortfall is reported with `ERR_LIABILITY_INSUFFICIENT` rather than absorbed."

        Design: Difficulty/resource_temporal_overlap/half_open_partner_service_windows_reject_an_overlapping_allocation
        """
        partner = self._partner_with_early_window()

        adjacent = validate_success(
            api_client.create_capacity_profile(
                partner["id"],
                {
                    "season_code": "2026-Q3",
                    "max_allocatable_units": 4000,
                    "effective_from": "2026-10-01T00:00:00Z",
                    "effective_to": "2026-12-01T00:00:00Z",
                },
                COORD,
            ),
            201,
        )
        assert adjacent["max_allocatable_units"] == 4000

        profiles = validate_success(
            api_client.list_partner_capacity_profiles(partner["id"], PLANNER), 200
        )
        # PRD §3.1 makes an approval mint a profile for every `PLANNED` season,
        # so the declared pair sits alongside that placeholder.
        assert len(profiles) >= 2

        selectable = validate_success(
            api_client.list_capacity_profiles(
                PLANNER, {"partner_id": partner["id"], "season_code": "2026-Q3"}
            ),
            200,
        )
        # PRD §3.2: an adjacent successor supersedes the earlier profile, so
        # exactly one row for the season is still selectable.
        live = [r for r in selectable if r["status"] == "ACTIVE"]
        assert len(live) == 1
        assert live[0]["id"] == adjacent["id"]


class TestReversalReservation:
    """Difficulty/resource_temporal_overlap — a reversal parks units in the reserve pool."""

    def _received_allocation(self):
        set_clock("2026-09-01T00:00:00Z")
        season = create_season()
        product = create_active_product(
            product_name="Field Work Crew",
            product_kind="ATHLETIC_SOCK",
            design_channel="DUAL_CHANNEL",
            obligation_model="AT_SALE",
            retail_price_cents=1700,
            unit_cost_cents=990,
            is_reusable=True,
        )
        add_product_line(product["id"], "00000000000203", "L", True)
        partner = create_approved_partner(
            legal_name="Pi Rural Outreach",
            partner_type="YOUTH_OUTREACH",
            operating_region="MIDWEST",
            operating_state_code="IA",
            registry_id="IA-CHR-160016",
            ein="100200800",
            unduplicated_recipients_per_facility=5000,
            need_tier="MODERATE",
        )
        profile = declare_capacity(partner["id"], max_allocatable_units=20000)
        claim = register_claim(product["id"], partner["id"], stated_donation_units=1000)
        # PRD §2.7: committing a plan echoes the planner's last observed version
        # of the target GivingPartner, which is read after the ceiling is
        # declared (the declaration is itself a write). PRD §3.2: the commitment
        # "is created pending and approved within the request", so the returned
        # allocation is already APPROVED.
        allocation = validate_success(
            api_client.commit_allocation_plan(
                season["id"],
                {
                    "giving_partner_id": partner["id"],
                    "claim_id": claim["id"],
                    "donation_product_id": product["id"],
                    "allocated_units": 1000,
                    "priority_tier": "HIGH",
                    "liquidity_cap": 10,
                    "expected_partner_version": get_partner(partner["id"])["version"],
                },
                PLANNER,
            ),
            200,
        )
        distribution = ship_allocation(allocation["id"], 1000, "TRK-RTO-1", "UPS")
        confirm_receipt(distribution["id"], 1000, "RCV-RTO-1")
        # The callers roll the clock separately; the season must still be OPEN
        # when the first reversal is issued so that the reversal's own temporal
        # gate ("the freeze-bearing endpoints are ... the allocation reversal")
        # is what refuses the repeat, not a frozen calendar.
        return season, product, partner, profile, claim, allocation

    def test_reversal_moves_units_from_commitment_to_reservation(self, api):
        """PRD §3.3: "A `AllocationPlanner` reverses a received allocation by supplying `allocated_units`, `claim_id`, `priority_tier` and a `reason`; the reversal is legal only when the allocation is `RECEIVED` — any other source status raises `ERR_REVERSAL_REQUIRES_RECEIVED` (HTTP 409) — and only when either `impact_units_confirmed` is zero or the season's reconciliation delta is negative, and when `allocated_units` fits the partner's remaining headroom."
        PRD §3.3: "A successful reversal creates a child allocation whose `allocation_kind` is `REVERSAL` carrying the same `allocated_units`, raises the profile's `reserved_units` by that amount, and creates the make-up donation liability for the next impact season with `carried_in_units` equal to those units."
        PRD §3.3: "The `allocation_kind` distinction matters throughout: an `ALLOCATION` is a benefit that debits capacity, while a `REVERSAL` is a make-up that credits capacity and forecasts the next season."

        Design: Difficulty/resource_temporal_overlap/allocation_reversal_reservations_only_overlap_rows_thirty_days_apart
        """
        season, product, partner, profile, claim, allocation = self._received_allocation()
        received = get_allocation(allocation["id"])
        assert received["status"] == "RECEIVED"

        validate_success(
            api_client.reverse_allocation(
                allocation["id"],
                {
                    "allocated_units": 1000,
                    "claim_id": claim["id"],
                    "priority_tier": "HIGH",
                    "reason": "Partner capacity re-declared at half the ceiling for this season",
                },
                PLANNER,
            ),
            200,
        )

        assert get_allocation(allocation["id"])["status"] == "REVERSED"
        rows = validate_success(
            api_client.list_allocations(PLANNER, {"giving_partner_id": partner["id"]}), 200
        )
        reversals = [r for r in rows if r["allocation_kind"] == "REVERSAL"]
        assert len(reversals) == 1
        assert reversals[0]["allocated_units"] == 1000

        refreshed = get_profile(profile["id"])
        # PRD §3.3: "raises the profile's `reserved_units` by that amount" while
        # the parent "settles into `REVERSED`" (terminal), so the make-up units
        # move out of the committed figure and into the reserve pool.
        assert refreshed["reserved_units"] == 1000
        assert refreshed["committed_units"] == 0

    def test_reversal_is_refused_once_the_season_has_frozen(self, api):
        """PRD §3.3: "A `AllocationPlanner` reverses a received allocation by supplying `allocated_units`, `claim_id`, `priority_tier` and a `reason`; the reversal is legal only when the allocation is `RECEIVED` — any other source status raises `ERR_REVERSAL_REQUIRES_RECEIVED` (HTTP 409) — and only when either `impact_units_confirmed` is zero or the season's reconciliation delta is negative, and when `allocated_units` fits the partner's remaining headroom."
        PRD §3.3: "A successful reversal creates a child allocation whose `allocation_kind` is `REVERSAL` carrying the same `allocated_units`, raises the profile's `reserved_units` by that amount, and creates the make-up donation liability for the next impact season with `carried_in_units` equal to those units."

        Design: Difficulty/resource_temporal_overlap/allocation_reversal_reservations_only_overlap_rows_thirty_days_apart
        """
        season, product, partner, profile, claim, allocation = self._received_allocation()
        validate_success(
            api_client.reverse_allocation(
                allocation["id"],
                {
                    "allocated_units": 1000,
                    "claim_id": claim["id"],
                    "priority_tier": "HIGH",
                    "reason": "Capacity re-declared downward",
                },
                PLANNER,
            ),
            200,
        )

        second = api_client.reverse_allocation(
            allocation["id"],
            {
                "allocated_units": 1000,
                "claim_id": claim["id"],
                "priority_tier": "HIGH",
                "reason": "Repeat attempt",
            },
            PLANNER,
        )
        # PRD §3.3: "the reversal is legal only when the allocation is
        # `RECEIVED` — any other source status raises
        # `ERR_REVERSAL_REQUIRES_RECEIVED` (HTTP 409)".
        validate_error(second, "ERR_REVERSAL_REQUIRES_RECEIVED", expected_status=409)