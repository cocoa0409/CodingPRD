"""Resource shapes: seeded defaults, derived fields and system stamps.

These probe what a row looks like the instant it is created - which counters
are seeded rather than absent, which inputs are optional, which fields the
server derives and refuses to read from the body, and which not-found code a
path or a body reference reports.
"""

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_DONOR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_REFERENCED_ENTITY_NOT_FOUND,
    ERR_SECTION_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_append_only_fields,
    assert_array_envelope,
    assert_donor_points,
    assert_instant,
    assert_object_envelope,
    assert_page_meta,
    assert_points,
    validate_error,
    validate_list,
    validate_success,
)
from test_helpers.constants import (
    ALUMNUS,
    CAPITAL,
    CLOCK_INITIAL_INSTANT,
    DONOR_ACTIVE,
    ENTRY_CUMULATIVE_GIVING,
    FACULTY_STAFF,
    GIFT_PLEDGED,
    INDIVIDUAL,
    NON_ALUMNUS,
    SEAT_AVAILABLE,
    STUDENT,
    VARIANT_CERTIFIED,
)
from test_helpers.fixtures import (
    add_received_gift,
    create_section,
    open_cycle,
    read_donor,
    read_section,
    register_donor,
    run_cycle,
    set_clock,
)
from test_helpers.test_users import ADMIN, CERTIFIER, OFFICER, POLICY

UNKNOWN_DONOR_ID = "00000000-0000-4000-8000-000000000001"
UNKNOWN_SECTION_ID = "00000000-0000-4000-8000-000000000002"
UNKNOWN_RECIPIENT_ID = "00000000-0000-4000-8000-000000000003"


class TestDonorCreation:
    """The four required inputs are echoed and every counter is seeded."""

    def test_a_minimal_create_seeds_every_counter(self, client):
        """No counter is absent: all nine start at zero and both anchors are null.

        PRD 3.1: "A newly registered donor lands in `donor_status` `ACTIVE` with
        `status_effective_date` set to the current logical clock instant, and
        every point and counter field starts at zero:
        `season_ticket_seasons_purchased`, `cumulative_giving_cents`,
        `consecutive_giving_years`, `provisional_points`,
        `certified_base_points`, `certified_points`, `transferred_points_in`,
        `transferred_points_out`, `dispute_adjustment_points` and
        `pending_request_count` are all `0`, while `household_partner_donor_id`
        and `rank_position` are both null."

        Design: Corner/entities/donor_create_returns_201_with_defaults_and_echoed_input
        """
        payload = {
            "full_name": "Avery Alum",
            "email": "avery.alum@example.com",
            "alumni_status": ALUMNUS,
            "entity_type": INDIVIDUAL,
        }
        response = client.create_donor(payload, headers=OFFICER)
        assert_object_envelope(response)
        donor = validate_success(response, 201)

        assert donor["full_name"] == "Avery Alum"
        assert donor["email"] == "avery.alum@example.com"
        assert donor["alumni_status"] == ALUMNUS
        assert donor["entity_type"] == INDIVIDUAL
        assert donor["donor_status"] == DONOR_ACTIVE
        assert donor["season_ticket_first_cycle_year"] is None
        assert donor["household_partner_donor_id"] is None
        assert donor["rank_position"] is None
        assert donor["season_ticket_seasons_purchased"] == 0
        assert donor["pending_request_count"] == 0
        assert donor["version"] == 1
        assert_donor_points(
            donor,
            provisional_points="0.00",
            certified_base_points="0.00",
            certified_points="0.00",
            transferred_points_in="0.00",
            transferred_points_out="0.00",
            dispute_adjustment_points="0.00",
            cumulative_giving_cents=0,
            consecutive_giving_years=0,
        )

    def test_the_system_stamps_come_from_the_logical_clock(self, client):
        """created_at and updated_at read the parked clock, and version starts at 1.

        PRD 2.4: "Most resources also carry `updated_at`, in the same format,
        refreshed on every mutation, and `version`, an integer that starts at 1
        on creation and increases by exactly 1 on each mutation that the
        specification says advances it."

        Design: Corner/entities/donor_create_stamps_system_id_timestamps_and_version_one
        """
        set_clock(client, "2026-05-04T09:30:00.000Z")

        donor = register_donor(client, alumni_status=STUDENT)

        assert isinstance(donor["id"], str) and donor["id"]
        assert_instant(donor["created_at"], "2026-05-04T09:30:00.000Z", "created_at")
        assert_instant(donor["updated_at"], "2026-05-04T09:30:00.000Z", "updated_at")
        assert donor["version"] == 1

    def test_a_missing_alumni_status_is_a_malformed_request(self, client):
        """alumni_status has no default, so omitting it writes nothing at all.

        PRD 2.8: "The body parses; required fields are present; enum values are
        recognised; numeric and string constraints hold; `limit` is within 1
        through 100 and `offset` is at least 0 — on every endpoint. Violation:
        `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/donor_create_without_alumni_status_returns_invalid_request
        """
        refused = client.create_donor(
            {
                "full_name": "Missing Field",
                "email": "missing.field@example.com",
                "entity_type": INDIVIDUAL,
            },
            headers=OFFICER,
        )
        validate_error(refused, ERR_INVALID_REQUEST, 400)

        _rows, meta = validate_list(client.list_donors(headers=OFFICER))
        assert_page_meta(meta, total_count=0)

    def test_an_unrecognised_entity_type_is_refused_not_stored(self, client):
        """entity_type accepts exactly four symbols and PARTNERSHIP is not one.

        PRD 3.1: "Registering one is a development-office or platform-operator
        act and requires four values plus one optional anchor: `full_name`, the
        legal or entity name, between 1 and 120 characters and not blank;
        `email`, the contact address used for recalculation communications, which
        must contain an at-sign and must be unique across the donor book;
        `alumni_status`, one of `ALUMNUS`, `FACULTY_STAFF`, `STUDENT` or
        `NON_ALUMNUS`; and `entity_type`, one of `INDIVIDUAL`,
        `JOINT_HOUSEHOLD`, `CORPORATION` or `FOUNDATION`."

        Design: Corner/entities/donor_create_with_unrecognised_entity_type_returns_invalid_request
        """
        refused = client.create_donor(
            {
                "full_name": "Enum Breaker",
                "email": "enum.breaker@example.com",
                "alumni_status": ALUMNUS,
                "entity_type": "PARTNERSHIP",
            },
            headers=OFFICER,
        )
        validate_error(refused, ERR_INVALID_REQUEST, 400)

        _rows, meta = validate_list(client.list_donors(headers=OFFICER))
        assert_page_meta(meta, total_count=0)

    def test_a_duplicate_email_leaves_the_first_row_untouched(self, client):
        """email is unique across the donor book, so the second create fails.

        PRD 3.1: "Registering one is a development-office or platform-operator
        act and requires four values plus one optional anchor: `full_name`, the
        legal or entity name, between 1 and 120 characters and not blank;
        `email`, the contact address used for recalculation communications, which
        must contain an at-sign and must be unique across the donor book;
        `alumni_status`, one of `ALUMNUS`, `FACULTY_STAFF`, `STUDENT` or
        `NON_ALUMNUS`; and `entity_type`, one of `INDIVIDUAL`,
        `JOINT_HOUSEHOLD`, `CORPORATION` or `FOUNDATION`."

        Design: Corner/entities/duplicate_donor_email_is_rejected_as_invalid_request
        """
        first = register_donor(
            client, full_name="Twin One", email="twin@example.com",
            alumni_status=NON_ALUMNUS,
        )

        refused = client.create_donor(
            {
                "full_name": "Twin Two",
                "email": "twin@example.com",
                "alumni_status": ALUMNUS,
                "entity_type": INDIVIDUAL,
            },
            headers=OFFICER,
        )
        validate_error(refused, ERR_INVALID_REQUEST, 400)

        survivor = read_donor(client, first["id"])
        assert survivor["full_name"] == "Twin One"
        assert survivor["version"] == 1
        _rows, meta = validate_list(client.list_donors(headers=OFFICER))
        assert_page_meta(meta, total_count=1)


class TestDonorReads:
    """Single-resource reads and the paginated collection."""

    def test_the_single_resource_read_returns_the_stored_row(self, client):
        """The read echoes what the create wrote, as an object envelope.

        PRD 2.4: "Alongside `id`, every resource carries `created_at`, an ISO
        8601 UTC timestamp with exactly three fractional-second digits, recorded
        when the row was first written."

        Design: Corner/entities/donor_get_by_id_returns_the_stored_row
        """
        created = register_donor(
            client,
            full_name="Rory Reader",
            email="rory.reader@example.com",
            alumni_status=FACULTY_STAFF,
        )

        response = client.get_donor(created["id"], headers=CERTIFIER)
        assert_object_envelope(response)
        donor = validate_success(response)

        assert donor["id"] == created["id"]
        assert donor["email"] == "rory.reader@example.com"
        assert donor["alumni_status"] == FACULTY_STAFF
        assert donor["version"] == 1
        assert_instant(donor["created_at"], CLOCK_INITIAL_INSTANT, "created_at")
        assert_instant(donor["updated_at"], CLOCK_INITIAL_INSTANT, "updated_at")

    def test_total_count_describes_the_whole_matching_set(self, client):
        """Paging changes the rows returned, never total_count.

        PRD 2.3: "List responses carry `limit`, `offset`, `total_count` and
        `has_more` inside `meta`, where `total_count` is the number of rows
        matching the filters before pagination is applied and `has_more` is true
        exactly when rows remain beyond the current page."

        Design: Corner/entities/donors_list_reports_total_count_and_has_more_across_pages
        """
        for name in ("Page One", "Page Two", "Page Three"):
            register_donor(
                client,
                full_name=name,
                email="{0}@example.com".format(name.lower().replace(" ", ".")),
                alumni_status=NON_ALUMNUS,
            )

        first_response = client.list_donors(
            headers=OFFICER, params={"limit": 2, "offset": 0}
        )
        assert_array_envelope(first_response)
        first_rows, first_meta = validate_list(first_response)
        assert len(first_rows) == 2
        assert_page_meta(first_meta, total_count=3, limit=2, offset=0, has_more=True)

        second_rows, second_meta = validate_list(
            client.list_donors(headers=OFFICER, params={"limit": 2, "offset": 2})
        )
        assert len(second_rows) == 1
        assert_page_meta(second_meta, total_count=3, limit=2, offset=2, has_more=False)

    def test_an_unknown_donor_id_reports_the_donor_specific_code(self, client):
        """Each collection has its own 404 code rather than a generic one.

        PRD 2.7: "Each collection has its own not-found code:
        `ERR_DONOR_NOT_FOUND`, `ERR_GIFT_NOT_FOUND`,
        `ERR_RECALCULATION_NOT_FOUND`, `ERR_LEDGER_ENTRY_NOT_FOUND`,
        `ERR_DISPUTE_NOT_FOUND`, `ERR_TRANSFER_NOT_FOUND`,
        `ERR_SECTION_NOT_FOUND`, `ERR_SEAT_NOT_FOUND`,
        `ERR_SEAT_ASSIGNMENT_NOT_FOUND`, `ERR_SELECTION_EVENT_NOT_FOUND`,
        `ERR_SELECTION_SLOT_NOT_FOUND` and `ERR_RELOCATION_REQUEST_NOT_FOUND`,
        each carrying HTTP 404."

        Design: Corner/entities/donor_get_with_unknown_id_returns_donor_not_found
        """
        refused = client.get_donor(UNKNOWN_DONOR_ID, headers=OFFICER)
        validate_error(refused, ERR_DONOR_NOT_FOUND, 404)


class TestOptionalInputsAndDerivedFields:
    """What the server fills in when the body stays quiet."""

    def test_an_omitted_gift_status_leaves_the_gift_pledged(self, client):
        """A defaulted gift is unsettled, so nothing reaches cumulative giving.

        PRD 3.2: "A gift is recorded against a donor with three required values —
        `gift_date`, the instant the gift was made; `amount_cents`, which must be
        strictly greater than zero; and `designation`, one of
        `ATHLETICS_ANNUAL`, `CAPITAL` or `ENDOWMENT` — plus an optional
        `gift_status` that defaults to `PLEDGED` when omitted and is otherwise
        `RECEIVED` or `REFUNDED`."

        Design: Corner/entities/gift_create_without_gift_status_defaults_to_pledged
        """
        donor = register_donor(client, alumni_status=NON_ALUMNUS)

        response = client.create_gift(
            donor["id"],
            f.gift_payload(1000000, f.instant(2026, 3, 1)),
            headers=OFFICER,
        )
        gift = validate_success(response, 201)

        assert gift["gift_status"] == GIFT_PLEDGED
        assert gift["settled_at"] is None
        assert gift["donor_id"] == donor["id"]
        assert_donor_points(read_donor(client, donor["id"]), cumulative_giving_cents=0)

    def test_an_omitted_hold_ceiling_defaults_to_a_single_hold(self, client):
        """max_concurrent_holds defaults to 1, not to an unbounded count.

        PRD 3.7: "A physical seat is added to a section with `row_label`, between
        1 and 8 characters and not blank; `seat_number`, strictly greater than
        zero; and an optional `max_concurrent_holds`, which defaults to 1 and
        must be at least 1."

        Design: Corner/entities/seat_create_without_max_concurrent_holds_defaults_to_one
        """
        section = create_section(client, seat_capacity=2)

        response = client.create_seat(
            section["id"], {"row_label": "DF", "seat_number": 1}, headers=ADMIN
        )
        seat = validate_success(response, 201)

        assert seat["max_concurrent_holds"] == 1
        assert seat["seat_status"] == SEAT_AVAILABLE
        assert seat["section_id"] == section["id"]

        after = read_section(client, section["id"])
        assert after["seat_row_count"] == 1
        assert after["seats_available"] == 1

    def test_the_cycle_year_comes_from_the_gift_date_not_the_clock(self, client):
        """A 2025-dated gift recorded in 2026 buckets into cycle 2025.

        PRD 3.2: "`cycle_year` is the UTC calendar year of `gift_date`, and it is
        the bucket the consecutive-year streak scan reads."

        Design: Corner/entities/gift_create_derives_cycle_year_from_gift_date
        """
        donor = register_donor(client, alumni_status=NON_ALUMNUS)

        gift = add_received_gift(
            client,
            donor["id"],
            750000,
            f.instant(2025, 11, 15),
            designation=CAPITAL,
        )
        assert gift["cycle_year"] == 2025

        rows, _meta = validate_list(
            client.list_donor_gifts(
                donor["id"], headers=OFFICER, params={"cycle_year": 2025}
            )
        )
        assert [row["id"] for row in rows] == [gift["id"]]
        assert_donor_points(
            read_donor(client, donor["id"]), cumulative_giving_cents=750000
        )

    def test_a_dispute_window_before_the_cutoff_is_refused(self, client):
        """The ordering constraint is strict, so the cycle is never created.

        PRD 3.3: "An annual cycle is opened by a development officer or platform
        operator with three values: `cycle_year`, the athletics cycle year being
        certified, which must be between 1900 and 2100 and must be unique across
        all recalculations; `cutoff_date`, the instant after which gifts are
        excluded from both variants; and `dispute_window_end`, the last instant
        at which a dispute may be filed against this cycle, which must be
        strictly later than `cutoff_date`."

        Design: Corner/entities/recalculation_create_with_dispute_window_before_cutoff_returns_invalid_request
        """
        refused = client.create_recalculation(
            {
                "cycle_year": 2026,
                "cutoff_date": f.end_of_day(2026, 6, 30),
                "dispute_window_end": f.instant(2026, 6, 1),
            },
            headers=OFFICER,
        )
        validate_error(refused, ERR_INVALID_REQUEST, 400)


class TestParentsReferencesAndAppendOnlyRows:
    """Nested paths, body references and the one entity without a version."""

    def test_a_ledger_entry_carries_no_version_and_no_updated_at(self, client):
        """The append-only row exposes computed_at instead of updated_at.

        PRD 2.4: "There is one exception: a point-ledger entry is append-only and
        therefore carries only `id` and `created_at` — it has neither
        `updated_at` nor `version`, and no operation ever rewrites one."

        Design: Corner/entities/point_ledger_entry_is_immutable_and_has_no_version_field
        """
        set_clock(client, f.instant(2026, 4, 1))
        donor = register_donor(client, alumni_status=NON_ALUMNUS)
        add_received_gift(client, donor["id"], 1000000, f.instant(2026, 3, 1))
        cycle = open_cycle(client, 2026)
        run_cycle(client, cycle["id"])

        rows, _meta = validate_list(
            client.list_point_ledger_entries(
                headers=OFFICER,
                params={
                    "donor_id": donor["id"],
                    "variant": VARIANT_CERTIFIED,
                    "entry_type": ENTRY_CUMULATIVE_GIVING,
                },
            )
        )
        assert len(rows) == 1

        entry = validate_success(
            client.get_point_ledger_entry(rows[0]["id"], headers=POLICY)
        )
        assert_append_only_fields(entry)
        for field in (
            "donor_id",
            "recalculation_id",
            "entry_type",
            "variant",
            "points",
            "computed_at",
        ):
            assert field in entry, "ledger entry is missing {0}".format(field)
        assert entry["entry_type"] == ENTRY_CUMULATIVE_GIVING
        assert entry["variant"] == VARIANT_CERTIFIED
        assert_points(entry["points"], "10.00", "ledger.points")
        assert_instant(entry["computed_at"], "2026-04-01T00:00:00.000Z", "computed_at")

    def test_a_seat_under_an_unknown_section_reports_the_parents_code(self, client):
        """The nested create resolves the section first and never orphans a seat.

        PRD 2.7: "So a request naming a seat inside a section reports the
        section's code first if the section id is unknown, and only reaches the
        seat check once the section resolves."

        Design: Corner/entities/seat_create_under_unknown_section_returns_section_not_found
        """
        refused = client.create_seat(
            UNKNOWN_SECTION_ID, {"row_label": "ZZ", "seat_number": 1}, headers=ADMIN
        )
        validate_error(refused, ERR_SECTION_NOT_FOUND, 404)

    def test_an_unknown_body_reference_reports_the_reference_code(self, client):
        """A body id that does not resolve is priority 7, not a path 404.

        PRD 2.7: "When a body names a row that does not exist — a partner donor
        on a household link, the donor or recalculation on a dispute, the source
        or recipient donor on a transfer, the reseating recalculation on a
        renovation, the seat on a pick, the current assignment, target section or
        selection event on a relocation request, or the target seat on a
        relocation decision — the response is `ERR_REFERENCED_ENTITY_NOT_FOUND`
        (HTTP 404)."

        Design: Corner/entities/transfer_create_with_unknown_recipient_returns_referenced_entity_not_found
        """
        source = register_donor(client, alumni_status=NON_ALUMNUS)

        refused = client.create_point_transfer(
            f.transfer_payload(
                source["id"], UNKNOWN_RECIPIENT_ID, "DEATH", 10.00, source["version"]
            ),
            headers=OFFICER,
        )
        validate_error(refused, ERR_REFERENCED_ENTITY_NOT_FOUND, 404)

        _rows, meta = validate_list(
            client.list_donor_point_transfers(source["id"], headers=OFFICER)
        )
        assert_page_meta(meta, total_count=0)
        assert read_donor(client, source["id"])["version"] == 1
