"""Endpoint contracts: round trips, action shapes and reverse-reachability.

Several resources here are only reachable through a filtered list — a seat
assignment is minted by a pick and a household link has no sub-collection at
all — so these tests walk each declared filter and pin the status code an
action endpoint answers with when it creates nothing.
"""

from test_helpers import factories as f
from test_helpers.api_errors import ERR_REFERENCED_ENTITY_NOT_FOUND
from test_helpers.assertions import (
    assert_cents,
    assert_donor_points,
    assert_instant,
    assert_page_meta,
    assert_points,
    assert_ratio,
    assert_seat_inventory,
    assert_three_fractional_digits,
    find_ledger_entries,
    validate_error,
    validate_list,
    validate_success,
)
from test_helpers.constants import (
    ALUMNUS,
    ATHLETICS_ANNUAL,
    CAPITAL,
    ENDOWMENT,
    ENTRY_ALUMNI_STATUS,
    ENTRY_CONSECUTIVE_YEARS,
    ENTRY_CUMULATIVE_GIVING,
    ENTRY_DISPUTE_ADJUSTMENT,
    ENTRY_NET_TRANSFER,
    ENTRY_SEASON_TICKET_TENURE,
    GIFT_PLEDGED,
    GIFT_RECEIVED,
    INDIVIDUAL,
    JOINT_HOUSEHOLD,
    NON_ALUMNUS,
    OCCUPANCY_HELD,
    OCCUPANCY_RELEASED,
    PAYMENT_PAID,
    PAYMENT_UNBILLED,
    POSTURE_NORMAL,
    POSTURE_PREMIUM,
    RECALC_COMPUTED,
    RENOVATION_NONE,
    SECTION_OPEN,
    SLOT_CONSUMED,
    SLOT_SCHEDULED,
    VARIANT_CERTIFIED,
    VARIANT_PROVISIONAL,
)
from test_helpers.fixtures import (
    add_gift,
    add_received_gift,
    certified_cycle,
    communicate_cycle,
    confirm_assignment,
    create_event,
    create_section_with_seats,
    open_cycle,
    pick_seat_ok,
    publish_and_open,
    publish_slots,
    read_cycle,
    read_donor,
    read_section,
    register_donor,
    run_cycle,
    sensitivity,
    set_clock,
    slot_for_donor,
)
from test_helpers.test_users import ADMIN, OFFICER, POLICY

# A well-formed UUID that no row will ever carry.
MISSING_PARTNER_ID = "00000000-0000-4000-8000-00000000d0a0"

SECTION_FIELDS = (
    "id",
    "section_code",
    "venue_code",
    "seat_capacity",
    "per_seat_requirement_cents",
    "required_points_per_seat",
    "status",
    "renovation_status",
    "pricing_posture",
    "seat_row_count",
    "seats_available",
    "seats_committed_count",
    "decommissioned_seat_count",
    "assigned_seat_count",
    "underwater_seat_count",
    "created_at",
    "updated_at",
    "version",
)


def _a_freshly_opened_section(client):
    set_clock(client, f.instant(2026, 4, 1))
    response = client.create_section(
        f.section_payload(
            section_code="SEC-RT",
            venue_code="STADIUM-RT",
            seat_capacity=4,
            per_seat_requirement_cents=175000,
            required_points_per_seat=12.50,
        ),
        headers=ADMIN,
    )
    return validate_success(response, 201)


class TestASectionRoundTripsThroughCreateReadAndList:
    """There is no update-by-replacement path, so create is the whole contract."""

    def test_the_create_response_carries_every_opening_default(self, client):
        """One call fixes the status trio, zeroes the counters and seeds history.

        PRD 3.7: "The section opens with `status` `OPEN`, `renovation_status`
        `NONE`, `pricing_posture` `NORMAL`, every inventory counter at zero, and
        `post_renovation_capacity`, `post_renovation_requirement_cents` and
        `reseating_recalculation_id` all null."

        PRD 3.7: "It also opens `requirement_history` with a single entry pairing
        the opening `per_seat_requirement_cents` with a `cycle_year` taken from
        the UTC calendar year of the current logical clock instant."

        Design: Corner/endpoints/section_create_read_and_list_round_trip_through_the_standard_envelope
        """
        section = _a_freshly_opened_section(client)

        assert section["section_code"] == "SEC-RT"
        assert section["venue_code"] == "STADIUM-RT"
        assert section["seat_capacity"] == 4
        assert_cents(
            section["per_seat_requirement_cents"], 175000, "per_seat_requirement_cents"
        )
        assert_points(
            section["required_points_per_seat"], "12.50", "required_points_per_seat"
        )
        assert section["status"] == SECTION_OPEN
        assert section["renovation_status"] == RENOVATION_NONE
        assert section["pricing_posture"] == POSTURE_NORMAL
        assert section["post_renovation_capacity"] is None
        assert section["post_renovation_requirement_cents"] is None
        assert section["reseating_recalculation_id"] is None
        assert section["version"] == 1
        assert_three_fractional_digits(section["created_at"], "created_at")
        assert_instant(section["created_at"], f.instant(2026, 4, 1), "created_at")
        assert_instant(section["updated_at"], section["created_at"], "updated_at")

        assert_seat_inventory(
            section,
            seats_available=0,
            seats_committed_count=0,
            decommissioned_seat_count=0,
            assigned_seat_count=0,
            underwater_seat_count=0,
            seat_row_count=0,
            label="SEC-RT",
        )

        history = section["requirement_history"]
        assert len(history) == 1, "requirement_history should be seeded once"
        assert history[0]["cycle_year"] == 2026
        assert_cents(
            history[0]["per_seat_requirement_cents"],
            175000,
            "requirement_history[0].per_seat_requirement_cents",
        )

    def test_the_single_read_agrees_with_the_create_field_for_field(self, client):
        """A read is not a mutation, so nothing moves and nothing differs.

        PRD 4: "Status codes follow one rule with no exceptions: an operation that
        brings a new resource into existence returns **201 Created**, and every
        other successful operation — including every read and every state
        transition on an existing resource — returns **200 OK**."

        Design: Corner/endpoints/section_create_read_and_list_round_trip_through_the_standard_envelope
        """
        section = _a_freshly_opened_section(client)

        fetched = validate_success(
            client.get_section(section["id"], headers=OFFICER), 200
        )
        for field in SECTION_FIELDS:
            assert fetched[field] == section[field], (
                "section.{0} changed between create and read: {1!r} then {2!r}".format(
                    field, section[field], fetched[field]
                )
            )
        assert fetched["requirement_history"] == section["requirement_history"]
        assert fetched["version"] == 1

    def test_the_venue_code_filter_selects_and_deselects(self, client):
        """A filter that matches nothing is an empty page, not a 404.

        PRD 2.3: "Other collections offer filters drawn from their own fields:
        gifts by `gift_status`, `cycle_year` and `designation`; point transfers by
        `status` and `basis`; point-ledger entries by `donor_id`,
        `recalculation_id`, `entry_type` and `variant`; selection events by
        `event_type` and `status`; disputes by `donor_id`, `recalculation_id` and
        `status`; sections by `status`, `renovation_status`,
        `reseating_recalculation_id`, `pricing_posture` and `venue_code`; seats by
        `seat_status` and `row_label`; seat assignments by `donor_id`, `seat_id`,
        `selection_slot_id`, `occupancy_status`, `payment_status`,
        `eligibility_status` and `pricing_mode`; selection slots by
        `selection_event_id`, `donor_id` and `slot_status`; and relocation
        requests by `donor_id`, `current_seat_assignment_id`, `target_section_id`,
        `selection_event_id`, `granted_seat_assignment_id`, `request_type` and
        `status`."

        Design: Corner/endpoints/section_create_read_and_list_round_trip_through_the_standard_envelope
        """
        section = _a_freshly_opened_section(client)

        rows, meta = validate_list(
            client.list_sections(headers=OFFICER, params={"venue_code": "STADIUM-RT"})
        )
        assert_page_meta(meta, total_count=1, has_more=False)
        assert [row["id"] for row in rows] == [section["id"]]

        empty, empty_meta = validate_list(
            client.list_sections(
                headers=OFFICER, params={"venue_code": "STADIUM-OTHER"}
            )
        )
        assert empty == []
        assert_page_meta(empty_meta, total_count=0, has_more=False)


def _a_donor_with_no_season_history(client):
    set_clock(client, f.instant(2026, 4, 1))
    donor = register_donor(client, alumni_status=NON_ALUMNUS)
    assert donor["season_ticket_seasons_purchased"] == 0
    assert donor["season_ticket_first_cycle_year"] is None
    return donor


def _renew(client, donor_id, cycle_year):
    return client.renew_season_ticket(
        donor_id, f.season_ticket_renewal_payload(cycle_year), headers=OFFICER
    )


class TestSeasonTicketRenewalIsAnActionOnTheDonor:
    """The path is collection-shaped, but nothing new comes into existence."""

    def test_the_call_answers_200_with_the_donor_itself(self, client):
        """No renewal resource is minted, so the rule gives 200 and a Donor body.

        PRD 4: "Status codes follow one rule with no exceptions: an operation that
        brings a new resource into existence returns **201 Created**, and every
        other successful operation — including every read and every state
        transition on an existing resource — returns **200 OK**."

        Design: Corner/endpoints/season_ticket_renewal_returns_the_updated_donor_with_a_200_not_a_new_resource
        """
        donor = _a_donor_with_no_season_history(client)

        body = validate_success(_renew(client, donor["id"], 2026), 200)
        assert body["id"] == donor["id"]
        assert body["donor_status"] == donor["donor_status"]
        assert "certified_points" in body
        assert body["season_ticket_seasons_purchased"] == 1
        assert body["season_ticket_first_cycle_year"] == 2026
        assert body["version"] == donor["version"] + 1

    def test_the_first_recorded_year_is_not_the_minimum_year(self, client):
        """Recording 2024 last does not pull the first cycle backwards.

        PRD 3.1: "The renewal operation carries a single `cycle_year`, and each
        distinct `cycle_year` counts once: recording a year not already on file
        increments `season_ticket_seasons_purchased` by 1 and advances the donor's
        `version` by 1, and if `season_ticket_first_cycle_year` was previously
        unset it is filled in from this call."

        Design: Corner/endpoints/season_ticket_renewal_returns_the_updated_donor_with_a_200_not_a_new_resource
        """
        donor = _a_donor_with_no_season_history(client)

        after_first = validate_success(_renew(client, donor["id"], 2026), 200)
        assert after_first["season_ticket_seasons_purchased"] == 1
        assert after_first["season_ticket_first_cycle_year"] == 2026
        assert after_first["version"] == 2

        after_second = validate_success(_renew(client, donor["id"], 2027), 200)
        assert after_second["season_ticket_seasons_purchased"] == 2
        assert after_second["season_ticket_first_cycle_year"] == 2026
        assert after_second["version"] == 3

        after_third = validate_success(_renew(client, donor["id"], 2024), 200)
        assert after_third["season_ticket_seasons_purchased"] == 3
        assert after_third["season_ticket_first_cycle_year"] == 2026
        assert after_third["version"] == 4

        assert_donor_points(
            read_donor(client, donor["id"]), certified_points="0.00", label="donor"
        )


def _two_unlinked_joint_households(client):
    set_clock(client, f.instant(2026, 4, 1))
    first = register_donor(
        client, alumni_status=NON_ALUMNUS, entity_type=JOINT_HOUSEHOLD
    )
    second = register_donor(
        client, alumni_status=NON_ALUMNUS, entity_type=JOINT_HOUSEHOLD
    )
    assert first["household_partner_donor_id"] is None
    assert second["household_partner_donor_id"] is None
    return first, second


class TestTheHouseholdLinkIsWalkedThroughTheDonorListFilter:
    """The link has no sub-collection, so the filter is the only reverse channel."""

    def test_an_unresolvable_partner_id_is_a_body_reference_404(self, client):
        """A body id that resolves to nothing is not a link-eligibility failure.

        PRD 2.7: "Identifiers supplied inside a request body are a separate
        concern and report a separate code. When a body names a row that does not
        exist — a partner donor on a household link, the donor or recalculation on
        a dispute, the source or recipient donor on a transfer, the reseating
        recalculation on a renovation, the seat on a pick, the current assignment,
        target section or selection event on a relocation request, or the target
        seat on a relocation decision — the response is
        `ERR_REFERENCED_ENTITY_NOT_FOUND` (HTTP 404)."

        Design: Corner/endpoints/household_link_is_discoverable_through_the_partner_filter_on_the_donor_list
        """
        first, second = _two_unlinked_joint_households(client)

        refused = client.link_household(
            first["id"],
            f.household_link_payload(MISSING_PARTNER_ID, first["version"]),
            headers=OFFICER,
        )
        validate_error(refused, ERR_REFERENCED_ENTITY_NOT_FOUND, 404)

        untouched = read_donor(client, first["id"])
        assert untouched["version"] == first["version"]

        linked = validate_success(
            client.link_household(
                first["id"],
                f.household_link_payload(second["id"], first["version"]),
                headers=OFFICER,
            ),
            200,
        )
        assert linked["household_partner_donor_id"] == second["id"]

    def test_the_partner_filter_returns_the_other_donor_from_either_side(
        self, client
    ):
        """The link is written on both rows, and each side finds its counterpart.

        PRD 3.1: "This reciprocal link is exactly the factual precondition a
        `DIVORCE`-basis point transfer later relies on, which is why the household
        list filter on `household_partner_donor_id` exists as a way to walk the
        link from either side."

        PRD 2.3: "The donor list additionally accepts a `sort` parameter for
        callers who want a different ordering of the donor book, alongside its
        filters `donor_status`, `alumni_status`, `entity_type`,
        `household_partner_donor_id` and `min_certified_points`."

        Design: Corner/endpoints/household_link_is_discoverable_through_the_partner_filter_on_the_donor_list
        """
        first, second = _two_unlinked_joint_households(client)
        validate_success(
            client.link_household(
                first["id"],
                f.household_link_payload(second["id"], first["version"]),
                headers=OFFICER,
            ),
            200,
        )

        rows, meta = validate_list(
            client.list_donors(
                headers=OFFICER, params={"household_partner_donor_id": first["id"]}
            )
        )
        assert_page_meta(meta, total_count=1, has_more=False)
        assert [row["id"] for row in rows] == [second["id"]]

        back, back_meta = validate_list(
            client.list_donors(
                headers=OFFICER, params={"household_partner_donor_id": second["id"]}
            )
        )
        assert_page_meta(back_meta, total_count=1, has_more=False)
        assert [row["id"] for row in back] == [first["id"]]


def _four_gifts_across_two_years(client):
    """Two designations, two statuses and two derived cycle years on one donor."""
    set_clock(client, f.instant(2026, 4, 1))
    donor = register_donor(client, alumni_status=NON_ALUMNUS)
    annual_received = add_received_gift(
        client, donor["id"], 1000000, f.instant(2026, 3, 1)
    )
    capital_pledged = add_gift(
        client,
        donor["id"],
        500000,
        f.instant(2026, 5, 1),
        designation=CAPITAL,
        gift_status=GIFT_PLEDGED,
    )
    endowment_received = add_gift(
        client,
        donor["id"],
        700000,
        f.instant(2025, 4, 1),
        designation=ENDOWMENT,
        gift_status=GIFT_RECEIVED,
    )
    annual_pledged = add_gift(
        client,
        donor["id"],
        300000,
        f.instant(2026, 6, 1),
        designation=ATHLETICS_ANNUAL,
        gift_status=GIFT_PLEDGED,
    )
    return donor, (annual_received, capital_pledged, endowment_received, annual_pledged)


def _gift_page(client, donor_id, **params):
    return validate_list(
        client.list_donor_gifts(donor_id, headers=OFFICER, params=params or None)
    )


class TestTheGiftSubCollectionFiltersOnADerivedField:
    """cycle_year is never supplied, so filtering on it exercises the derivation."""

    def test_the_cycle_year_of_each_gift_comes_from_its_gift_date(self, client):
        """A 2025-dated gift buckets to 2025 even though the clock reads 2026.

        PRD 3.2: "Two fields on the gift are derived and never accepted from the
        body. `cycle_year` is the UTC calendar year of `gift_date`, and it is the
        bucket the consecutive-year streak scan reads."

        Design: Corner/endpoints/gift_list_filters_compose_on_status_designation_and_derived_cycle_year
        """
        donor, gifts = _four_gifts_across_two_years(client)
        annual_received, _capital, endowment_received, _annual_pledged = gifts

        rows, meta = _gift_page(client, donor["id"])
        assert_page_meta(meta, total_count=4, has_more=False)
        assert annual_received["cycle_year"] == 2026
        assert endowment_received["cycle_year"] == 2025
        for row in rows:
            assert row["version"] == 1
            assert "cycle_year" in row

    def test_the_three_filters_narrow_by_conjunction(self, client):
        """Each filter alone keeps two rows; together they keep exactly one.

        PRD 2.3: "Every filter is optional, and supplying several narrows the
        result set by conjunction."

        Design: Corner/endpoints/gift_list_filters_compose_on_status_designation_and_derived_cycle_year
        """
        donor, gifts = _four_gifts_across_two_years(client)
        _annual_received, _capital, endowment_received, annual_pledged = gifts

        _rows, pledged = _gift_page(client, donor["id"], gift_status=GIFT_PLEDGED)
        assert_page_meta(pledged, total_count=2)

        _rows, annual = _gift_page(client, donor["id"], designation=ATHLETICS_ANNUAL)
        assert_page_meta(annual, total_count=2)

        older, older_meta = _gift_page(client, donor["id"], cycle_year=2025)
        assert_page_meta(older_meta, total_count=1)
        assert [row["id"] for row in older] == [endowment_received["id"]]

        narrowed, narrowed_meta = _gift_page(
            client,
            donor["id"],
            gift_status=GIFT_PLEDGED,
            designation=ATHLETICS_ANNUAL,
            cycle_year=2026,
        )
        assert_page_meta(narrowed_meta, total_count=1)
        assert [row["id"] for row in narrowed] == [annual_pledged["id"]]


def _one_alumnus_scored_once(client):
    """A single ALUMNUS donor whose cycle has been run once and communicated."""
    set_clock(client, f.instant(2026, 4, 1))
    donor = register_donor(client, alumni_status=ALUMNUS, entity_type=INDIVIDUAL)
    add_received_gift(client, donor["id"], 1000000, f.instant(2026, 3, 1))
    cycle = open_cycle(client, 2026)
    run_cycle(client, cycle["id"])
    return donor, communicate_cycle(client, cycle["id"])


def _ledger_page(client, **params):
    params.setdefault("limit", 100)
    return validate_list(
        client.list_point_ledger_entries(headers=OFFICER, params=params)
    )


class TestThePointLedgerListFiltersByVariantAndComponent:
    """One run writes six components twice over, and a re-run appends a second set."""

    def test_one_run_writes_six_components_in_each_of_two_variants(self, client):
        """Twelve rows for one donor, six of them CERTIFIED.

        PRD 3.3: "Because a run writes both variants, it appends **two generations
        of ledger rows per donor**: one row per formula component per variant."

        Design: Corner/endpoints/point_ledger_entry_list_filters_by_variant_and_component_across_two_generations
        """
        donor, _cycle = _one_alumnus_scored_once(client)

        _rows, meta = _ledger_page(client, donor_id=donor["id"])
        assert_page_meta(meta, total_count=12)

        certified, certified_meta = _ledger_page(
            client, donor_id=donor["id"], variant=VARIANT_CERTIFIED
        )
        assert_page_meta(certified_meta, total_count=6)
        assert sorted(row["entry_type"] for row in certified) == sorted(
            (
                ENTRY_CUMULATIVE_GIVING,
                ENTRY_CONSECUTIVE_YEARS,
                ENTRY_SEASON_TICKET_TENURE,
                ENTRY_ALUMNI_STATUS,
                ENTRY_NET_TRANSFER,
                ENTRY_DISPUTE_ADJUSTMENT,
            )
        )

    def test_the_component_filter_isolates_one_itemised_row(self, client):
        """The 25.00 alumni row is itemised, not folded into a single total.

        PRD 3.3: "Fifth, the **alumni bonus**, which is granted only while
        `donor_status` is `ACTIVE` or `LAPSED` and is 0 otherwise: 25 points for
        `ALUMNUS`, 15 for `FACULTY_STAFF`, 5 for `STUDENT`, and 0 for
        `NON_ALUMNUS`."

        PRD 3.3: "Each row records `donor_id`, `recalculation_id`, the
        `entry_type` naming the component — `CUMULATIVE_GIVING`,
        `CONSECUTIVE_YEARS`, `SEASON_TICKET_TENURE`, `ALUMNI_STATUS`,
        `NET_TRANSFER` or `DISPUTE_ADJUSTMENT` — the `variant` (`PROVISIONAL` or
        `CERTIFIED`), the `points` that component contributed to 2 decimal places,
        a human-readable `basis_note` explaining the derivation such as the tier
        split, the streak span or the cap applied, and `computed_at`, the logical
        clock instant the row was written."

        Design: Corner/endpoints/point_ledger_entry_list_filters_by_variant_and_component_across_two_generations
        """
        donor, _cycle = _one_alumnus_scored_once(client)

        alumni, alumni_meta = _ledger_page(
            client,
            donor_id=donor["id"],
            variant=VARIANT_CERTIFIED,
            entry_type=ENTRY_ALUMNI_STATUS,
        )
        assert_page_meta(alumni_meta, total_count=1)
        assert_points(alumni[0]["points"], "25.00", "ALUMNI_STATUS points")
        assert_instant(
            alumni[0]["computed_at"], f.instant(2026, 4, 1), "computed_at"
        )

        transfers, transfer_meta = _ledger_page(
            client, donor_id=donor["id"], entry_type=ENTRY_NET_TRANSFER
        )
        assert_page_meta(transfer_meta, total_count=2)
        for row in transfers:
            assert_points(row["points"], "0.00", "NET_TRANSFER points")

        certified, _meta = _ledger_page(
            client, donor_id=donor["id"], variant=VARIANT_CERTIFIED
        )
        giving = find_ledger_entries(certified, entry_type=ENTRY_CUMULATIVE_GIVING)
        streak = find_ledger_entries(certified, entry_type=ENTRY_CONSECUTIVE_YEARS)
        assert_points(giving[0]["points"], "10.00", "CUMULATIVE_GIVING points")
        assert_points(streak[0]["points"], "5.00", "CONSECUTIVE_YEARS points")
        assert_donor_points(
            read_donor(client, donor["id"]), certified_points="40.00", label="donor"
        )

    def test_a_re_run_appends_a_second_generation(self, client):
        """Twelve rows become twenty-four, and the old generation survives.

        PRD 3.3: "Ledger rows are never rewritten or deleted; a re-run appends a
        fresh generation alongside the old one."

        PRD 3.4: "That second pass recomputes every donor's points, this time
        folding in the `dispute_adjustment_points` produced by disputes that were
        upheld, appends a fresh generation of ledger rows, resets
        `communication_sent_count` to 0 because the donors must be told again, and
        advances the recalculation's `version` by 1."

        Design: Corner/endpoints/point_ledger_entry_list_filters_by_variant_and_component_across_two_generations
        """
        donor, cycle = _one_alumnus_scored_once(client)

        run_cycle(client, cycle["id"])

        _rows, meta = _ledger_page(client, donor_id=donor["id"])
        assert_page_meta(meta, total_count=24)

        _rows, provisional = _ledger_page(
            client, recalculation_id=cycle["id"], variant=VARIANT_PROVISIONAL
        )
        assert_page_meta(provisional, total_count=12)

        after = read_cycle(client, cycle["id"])
        assert after["status"] == RECALC_COMPUTED
        assert after["communication_sent_count"] == 0


def _three_donors_created_in_reverse_rank_order(client):
    """Creation order is the reverse of the ranking, so insertion order is a trap."""
    set_clock(client, f.instant(2026, 4, 1))
    low = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, low["id"], 1000000, f.instant(2026, 3, 1))
    mid = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, mid["id"], 1500000, f.instant(2026, 3, 1))
    high = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, high["id"], 2000000, f.instant(2026, 3, 1))

    cycle = certified_cycle(client, 2026)
    event = create_event(
        client, cycle["id"], f.instant(2026, 9, 1), f.instant(2026, 9, 7), 2880
    )
    published = publish_slots(client, event["id"])
    assert published["published_slot_count"] == 3
    return (low, mid, high), published


def _slot_page(client, event_id, **params):
    params.setdefault("selection_event_id", event_id)
    return validate_list(client.list_selection_slots(headers=OFFICER, params=params))


class TestTheSelectionSlotListIsOrderedBySlotIndex:
    """This is the one collection that overrides the created_at default order."""

    def test_the_default_order_is_slot_index_not_creation_order(self, client):
        """The donors were created low to high, and the page comes back high to low.

        PRD 2.3: "One collection overrides this: the selection-slot list is ordered
        by `slot_index` ascending by default, because a slot's position in its
        event's window is the only order a reader of that collection cares about."

        Design: Corner/endpoints/selection_slot_list_defaults_to_slot_index_ascending_and_paginates_consistently
        """
        donors, event = _three_donors_created_in_reverse_rank_order(client)
        low, mid, high = donors

        rows, meta = _slot_page(client, event["id"])
        assert_page_meta(meta, total_count=3, has_more=False)
        assert [row["slot_index"] for row in rows] == [0, 1, 2]
        assert [row["donor_id"] for row in rows] == [high["id"], mid["id"], low["id"]]

    def test_each_slot_start_steps_by_the_slot_length(self, client):
        """Two-day slots tile the six-day window from its start.

        PRD 3.8: "Taking the ranked pool in order with a zero-based counter, each
        donor's `slot_index` is their position in that order; their `slot_start` is
        `window_start` advanced by the counter multiplied by the sum of
        `slot_minutes` and `slot_buffer_minutes`, expressed in minutes; and their
        `slot_end` is their `slot_start` advanced by `slot_minutes`."

        PRD 3.8: "It ranks the eligible pool on the four keys of §3.5 and creates
        one slot per ranked donor, each carrying the donor's `donor_id`, its
        `selection_event_id`, a `slot_index`, a `slot_start`, a `slot_end`, and
        `rank_at_publish` — the donor's `rank_position` as observed at
        publication, which is the comparand the staleness check later reads."

        Design: Corner/endpoints/selection_slot_list_defaults_to_slot_index_ascending_and_paginates_consistently
        """
        _donors, event = _three_donors_created_in_reverse_rank_order(client)

        rows, _meta = _slot_page(client, event["id"])
        assert_instant(rows[0]["slot_start"], f.instant(2026, 9, 1), "slot 0 start")
        assert_instant(rows[1]["slot_start"], f.instant(2026, 9, 3), "slot 1 start")
        assert_instant(rows[2]["slot_start"], f.instant(2026, 9, 5), "slot 2 start")
        for row in rows:
            assert row["rank_at_publish"] == row["slot_index"] + 1
            assert row["slot_status"] == SLOT_SCHEDULED

    def test_the_order_survives_pagination_and_the_status_filter(self, client):
        """total_count counts the matches, not the page, on every page.

        PRD 2.3: "List responses carry `limit`, `offset`, `total_count` and
        `has_more` inside `meta`, where `total_count` is the number of rows
        matching the filters before pagination is applied and `has_more` is true
        exactly when rows remain beyond the current page."

        Design: Corner/endpoints/selection_slot_list_defaults_to_slot_index_ascending_and_paginates_consistently
        """
        _donors, event = _three_donors_created_in_reverse_rank_order(client)

        first_page, first_meta = _slot_page(client, event["id"], limit=2)
        assert_page_meta(first_meta, total_count=3, limit=2, offset=0, has_more=True)
        assert [row["slot_index"] for row in first_page] == [0, 1]

        second_page, second_meta = _slot_page(client, event["id"], limit=2, offset=1)
        assert_page_meta(second_meta, total_count=3, limit=2, offset=1, has_more=False)
        assert [row["slot_index"] for row in second_page] == [1, 2]

        consumed, consumed_meta = _slot_page(
            client, event["id"], slot_status=SLOT_CONSUMED
        )
        assert consumed == []
        assert_page_meta(consumed_meta, total_count=0, has_more=False)


def _a_single_seat_section_filled_and_paid(client):
    """SEC-M's only seat is ASSIGNED and PAID, so no seat is free at all."""
    set_clock(client, f.instant(2026, 4, 1))
    section, seats = create_section_with_seats(
        client,
        [("M", 1)],
        section_code="SEC-M",
        venue_code="STADIUM-M",
        seat_capacity=1,
        per_seat_requirement_cents=150000,
        required_points_per_seat=0.00,
    )
    donor = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, donor["id"], 1000000, f.instant(2026, 3, 1))
    cycle = certified_cycle(client, 2026)
    event = publish_and_open(
        client, cycle["id"], f.instant(2026, 9, 1), f.instant(2026, 9, 2), 1440
    )

    set_clock(client, f.instant(2026, 9, 1, 6))
    slot = slot_for_donor(client, event["id"], donor["id"])
    held = pick_seat_ok(client, slot["id"], seats[0]["id"], donor["id"])
    confirm_assignment(client, held["id"])

    filled = read_section(client, section["id"])
    assert_seat_inventory(
        filled,
        seats_available=0,
        seats_committed_count=1,
        assigned_seat_count=1,
        underwater_seat_count=0,
        seat_row_count=1,
        label="SEC-M",
    )
    return filled, donor


class TestPricingSensitivityIsADerivedReadThatPersistsNothing:
    """The PREMIUM corner needs a zero ratio and a full house at the same time."""

    def test_the_full_house_reads_premium_and_recommends_the_uplift(self, client):
        """A zero ratio alone is not enough; seats_available must be zero too.

        PRD 3.7: "The branch order is pinned and `SOFT` is evaluated first and
        wins outright — when the ratio is at least 0.30 the posture is `SOFT`;
        otherwise, when the ratio is exactly zero **and** `seats_available` is
        zero, the posture is `PREMIUM`; otherwise it is `NORMAL`."

        PRD 3.7: "That recommendation is `per_seat_requirement_cents` multiplied
        by 0.90 and rounded half up to whole cents when the posture is `SOFT`,
        multiplied by 1.10 and rounded half up to whole cents when the posture is
        `PREMIUM`, and simply `per_seat_requirement_cents` unchanged when the
        posture is `NORMAL`."

        Design: Corner/endpoints/pricing_sensitivity_computed_read_is_side_effect_free_and_recommends_the_premium_uplift
        """
        section, _donor = _a_single_seat_section_filled_and_paid(client)

        report = sensitivity(client, section["id"])
        assert report["section_code"] == "SEC-M"
        assert_cents(
            report["per_seat_requirement_cents"], 150000, "per_seat_requirement_cents"
        )
        assert_points(
            report["required_points_per_seat"], "0.00", "required_points_per_seat"
        )
        assert report["assigned_seat_count"] == 1
        assert report["underwater_seat_count"] == 0
        assert_ratio(report["underwater_ratio"], "0.0000", "underwater_ratio")
        assert report["pricing_posture"] == POSTURE_PREMIUM
        assert_cents(
            report["recommended_requirement_cents"],
            165000,
            "recommended_requirement_cents",
        )
        assert len(report["requirement_history"]) == 1
        assert report["requirement_history"][0]["cycle_year"] == 2026
        assert_cents(
            report["requirement_history"][0]["per_seat_requirement_cents"],
            150000,
            "requirement_history[0].per_seat_requirement_cents",
        )

    def test_two_reads_by_two_roles_agree_and_move_no_version(self, client):
        """The report is derived on read, so the section is untouched by it.

        PRD 3.7: "A separate computed read reports pricing sensitivity for a
        section: it returns `section_code`, `per_seat_requirement_cents`,
        `required_points_per_seat`, `assigned_seat_count`,
        `underwater_seat_count`, the `underwater_ratio` computed the same way and
        rounded half up to 4 decimal places, the current `pricing_posture`, the
        whole `requirement_history`, and a `recommended_requirement_cents`."

        PRD 2.4: "Most resources also carry `updated_at`, in the same format,
        refreshed on every mutation, and `version`, an integer that starts at 1 on
        creation and increases by exactly 1 on each mutation that the
        specification says advances it."

        Design: Corner/endpoints/pricing_sensitivity_computed_read_is_side_effect_free_and_recommends_the_premium_uplift
        """
        section, _donor = _a_single_seat_section_filled_and_paid(client)
        version_before = section["version"]

        by_office = sensitivity(client, section["id"], headers=OFFICER)
        by_committee = sensitivity(client, section["id"], headers=POLICY)
        assert by_committee == by_office

        after = read_section(client, section["id"])
        assert after["version"] == version_before
        assert_instant(after["updated_at"], section["updated_at"], "updated_at")


def _one_held_and_unbilled_assignment(client):
    """A single pick on SEC-N, left exactly as the pick created it."""
    set_clock(client, f.instant(2026, 4, 1))
    _section, seats = create_section_with_seats(
        client,
        [("N", 1)],
        section_code="SEC-N",
        venue_code="STADIUM-N",
        seat_capacity=1,
        per_seat_requirement_cents=100000,
        required_points_per_seat=0.00,
    )
    donor = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, donor["id"], 1000000, f.instant(2026, 3, 1))
    cycle = certified_cycle(client, 2026)
    event = publish_and_open(
        client, cycle["id"], f.instant(2026, 9, 1), f.instant(2026, 9, 2), 1440
    )

    set_clock(client, f.instant(2026, 9, 1, 6))
    slot = slot_for_donor(client, event["id"], donor["id"])
    assignment = pick_seat_ok(client, slot["id"], seats[0]["id"], donor["id"])
    assert assignment["occupancy_status"] == OCCUPANCY_HELD
    assert assignment["payment_status"] == PAYMENT_UNBILLED
    return donor, seats[0], slot, assignment


def _assignment_page(client, **params):
    return validate_list(client.list_seat_assignments(headers=OFFICER, params=params))


class TestTheSeatAssignmentListIsTheOnlyWayBackToAPickedRow:
    """No create call exists for this resource, so its three keys must be walkable."""

    def test_all_three_foreign_keys_resolve_to_the_same_row(self, client):
        """donor_id, seat_id and selection_slot_id each find the one assignment.

        PRD 3.9: "The pick creates a seat assignment. Its `donor_id` is copied from
        the slot's `donor_id` and never read from the body, and its
        `selection_slot_id` records the slot it came through."

        Design: Corner/endpoints/seat_assignment_list_is_the_reverse_channel_for_all_three_of_its_foreign_keys
        """
        donor, seat, slot, assignment = _one_held_and_unbilled_assignment(client)

        for label, params in (
            ("donor_id", {"donor_id": donor["id"]}),
            ("seat_id", {"seat_id": seat["id"]}),
            ("selection_slot_id", {"selection_slot_id": slot["id"]}),
        ):
            rows, meta = _assignment_page(client, **params)
            assert_page_meta(meta, total_count=1, has_more=False)
            assert [row["id"] for row in rows] == [assignment["id"]], (
                "the {0} filter did not resolve to the picked row".format(label)
            )

        rows, _meta = _assignment_page(client, donor_id=donor["id"])
        row = rows[0]
        assert row["donor_id"] == donor["id"]
        assert row["seat_id"] == seat["id"]
        assert row["selection_slot_id"] == slot["id"]
        assert_cents(row["requirement_cents"], 100000, "requirement_cents")
        assert_cents(row["total_due_cents"], 100000, "total_due_cents")

    def test_the_two_status_axes_filter_independently(self, client):
        """A mismatched pair is an empty page rather than an error.

        PRD 2.3: "Every filter is optional, and supplying several narrows the
        result set by conjunction."

        PRD 3.9: "The row starts with `occupancy_status` `HELD` and
        `payment_status` `UNBILLED`, `amount_paid_cents` at 0,
        `eligibility_status` `ELIGIBLE` and `release_reason` `NONE`."

        Design: Corner/endpoints/seat_assignment_list_is_the_reverse_channel_for_all_three_of_its_foreign_keys
        """
        _donor, _seat, _slot, assignment = _one_held_and_unbilled_assignment(client)

        matched, matched_meta = _assignment_page(
            client, occupancy_status=OCCUPANCY_HELD, payment_status=PAYMENT_UNBILLED
        )
        assert_page_meta(matched_meta, total_count=1)
        assert [row["id"] for row in matched] == [assignment["id"]]

        released, released_meta = _assignment_page(
            client, occupancy_status=OCCUPANCY_RELEASED
        )
        assert released == []
        assert_page_meta(released_meta, total_count=0)

        mismatched, mismatched_meta = _assignment_page(
            client, occupancy_status=OCCUPANCY_HELD, payment_status=PAYMENT_PAID
        )
        assert mismatched == []
        assert_page_meta(mismatched_meta, total_count=0)
