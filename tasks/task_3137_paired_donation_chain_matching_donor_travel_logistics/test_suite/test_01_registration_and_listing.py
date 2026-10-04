"""Entity creation, registration, defaults, and listing/pagination tests."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_center_payload,
    create_donor_payload,
    create_itinerary_payload,
    create_recipient_payload,
    create_slot_payload,
    make_center_coordinator_headers,
    reset_clock,
    create_center,
    create_donor,
    create_recipient,
    validate_error,
    validate_paginated,
    validate_success,
    get_success_data,
)

LOGISTICS = TEST_USERS["logistics_headers"]


class TestCenterCreation:
    def test_center_creation_returns_system_fields(self, api, registry_admin_headers):
        """PRD §3.1: "New centers are born with `participation_status` equal to
        `ACTIVE` and with all computed counters — `failed_outcome_count`,
        `shipped_organ_count`, `probed_cold_ischemia_violations`,
        `reputation_score_bps`, and `active_chain_count` — initialized."
        PRD §2.4: "`version` — an integer starting at its initial value at
        creation and incremented by one on every mutation."

        Design: Corner/entities/center_creation_returns_system_fields
        """
        reset_clock()
        resp = api.create_center(create_center_payload(), registry_admin_headers)
        data = validate_success(resp, expected_status=201)
        assert data["participation_status"] == "ACTIVE"
        assert data["version"] == 1
        assert data["failed_outcome_count"] == 0
        assert data["shipped_organ_count"] == 0
        assert data["reputation_score_bps"] == 10000

    def test_get_nonexistent_center_returns_not_found(self, api, registry_admin_headers):
        """PRD §2.5: "The first missing identifier short-circuits the request
        with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/get_nonexistent_center_returns_not_found
        """
        reset_clock()
        resp = api.get_center("00000000-0000-0000-0000-000000000000", registry_admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


class TestDonorRegistration:
    def test_donor_creation_missing_required_field_returns_invalid_request(
        self, api, registry_admin_headers
    ):
        """PRD §5: "`ERR_INVALID_REQUEST` | 400".
        PRD §3.2: "an integer `age_at_registration` which must be at least 18".

        Design: Corner/entities/donor_creation_missing_required_field_returns_invalid_request
        """
        reset_clock()
        center = create_center()
        payload = create_donor_payload(center["id"])
        del payload["abo_type"]
        resp = api.create_donor(payload, make_center_coordinator_headers(center["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_donor_invalid_enum_abo_type_returns_invalid_request(
        self, api, registry_admin_headers
    ):
        """PRD §3.2: "the `abo_type` (one of `A`, `B`, `AB`, or `O`)".
        PRD §5: "`ERR_INVALID_REQUEST` | 400".

        Design: Corner/entities/donor_invalid_enum_abo_type_returns_invalid_request
        """
        reset_clock()
        center = create_center()
        payload = create_donor_payload(center["id"], abo_type="INVALID")
        resp = api.create_donor(payload, make_center_coordinator_headers(center["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_donor_under_age_18_returns_invalid_request(self, api, registry_admin_headers):
        """PRD §3.2: "an integer `age_at_registration` which must be at least 18".
        PRD §5: "`ERR_INVALID_REQUEST` | 400".

        Design: Corner/entities/donor_under_age_18_returns_invalid_request
        """
        reset_clock()
        center = create_center()
        payload = create_donor_payload(center["id"], age_at_registration=17)
        resp = api.create_donor(payload, make_center_coordinator_headers(center["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_donor_defaults_medical_status_cleared(self, api, registry_admin_headers):
        """PRD §3.2: "The donor's initial `medical_status` is `CLEARED`, initial
        `surgery_state` is `PRE_SURGERY`, and initial `chain_participation_state`
        is `POOL`. The donor's `protection_policy_id` is null until the
        nephrectomy completes, `priority_waitlist_status` begins at `NONE`, and
        the computed fields `traveled_distance_miles` and
        `complications_recorded` start at zero."

        Design: Corner/entities/donor_defaults_medical_status_cleared
        """
        reset_clock()
        center = create_center()
        donor = create_donor(center)
        assert donor["medical_status"] == "CLEARED"
        assert donor["surgery_state"] == "PRE_SURGERY"
        assert donor["chain_participation_state"] == "POOL"
        assert donor.get("protection_policy_id") is None
        assert donor["priority_waitlist_status"] == "NONE"
        assert donor["traveled_distance_miles"] == 0

    def test_get_donor_returns_full_record(self, api, registry_admin_headers):
        """PRD §3.2: "The donor's initial `medical_status` is `CLEARED`, initial
        `surgery_state` is `PRE_SURGERY`, and initial `chain_participation_state`
        is `POOL`."

        Design: Corner/endpoints/get_donor_returns_full_record
        """
        reset_clock()
        center = create_center()
        donor = create_donor(center)
        resp = api.get_donor(donor["id"], registry_admin_headers)
        data = validate_success(resp)
        assert data["id"] == donor["id"]
        assert data["medical_status"] == "CLEARED"
        assert data["surgery_state"] == "PRE_SURGERY"
        assert data["chain_participation_state"] == "POOL"


class TestRecipientRegistration:
    def test_recipient_cpra_out_of_range_returns_invalid_request(
        self, api, registry_admin_headers
    ):
        """PRD §3.2: "a `cpra_percent` sensitization score from 0 to 100 (higher
        narrows the feasible donor pool)".
        PRD §5: "`ERR_INVALID_REQUEST` | 400".

        Design: Corner/entities/recipient_cpra_out_of_range_returns_invalid_request
        """
        reset_clock()
        center = create_center()
        payload = create_recipient_payload(center["id"], cpra_percent=150)
        resp = api.create_recipient(payload, make_center_coordinator_headers(center["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


class TestSlotAndItineraryInputValidation:
    def test_slot_end_before_start_returns_invalid_request(self, api, registry_admin_headers):
        """PRD §3.5: "a `CenterCoordinator` supplies the `center_id`, the
        `slot_start_utc` and `slot_end_utc` (start strictly before end, and the
        duration must be at least `SLOT_MIN_HOURS`)".
        PRD §5: "`ERR_INVALID_REQUEST` | 400".

        Design: Corner/entities/slot_end_before_start_returns_invalid_request
        """
        reset_clock()
        center = create_center()
        payload = create_slot_payload(
            center["id"], "2026-09-10T12:00:00Z", "2026-09-10T11:00:00Z"
        )
        resp = api.create_slot(payload, make_center_coordinator_headers(center["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_itinerary_arrive_before_depart_returns_invalid_request(
        self, api, registry_admin_headers
    ):
        """PRD §3.10: "the planned `depart_utc` and `arrive_utc` (arrival
        strictly after departure)".
        PRD §5: "`ERR_INVALID_REQUEST` | 400".

        Design: Corner/entities/itinerary_arrive_before_depart_returns_invalid_request
        """
        reset_clock()
        center = create_center()
        donor = create_donor(center)
        payload = create_itinerary_payload(
            donor["id"],
            depart_utc="2026-09-10T16:00:00Z",
            arrive_utc="2026-09-10T08:00:00Z",
        )
        resp = api.create_itinerary(payload, LOGISTICS)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_itinerary_initial_state_draft(self, api, registry_admin_headers):
        """PRD §3.10: "The itinerary begins in `DRAFT`; its `itinerary_state`
        moves to `CONFIRMED` on confirmation and terminates at either
        `REIMBURSED` or `CANCELLED`."

        Design: Corner/state_machines/itinerary_initial_state_draft
        """
        reset_clock()
        center = create_center()
        donor = create_donor(center)
        resp = api.create_itinerary(create_itinerary_payload(donor["id"]), LOGISTICS)
        data = validate_success(resp, expected_status=201)
        assert data["itinerary_state"] == "DRAFT"


class TestListingAndPagination:
    def test_list_centers_pagination_default_limit(self, api, registry_admin_headers):
        """PRD §2.3: "`limit` defaults to 10, must be at least 1, and must not
        exceed 100."
        PRD §2.3: "The `meta` envelope of a paginated list response carries
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/list_centers_pagination_default_limit
        """
        reset_clock()
        for _ in range(12):
            create_center()
        resp = api.list_centers(registry_admin_headers)
        data, meta = validate_paginated(resp)
        assert len(data) <= 10
        assert meta["total_count"] == 12
        assert meta["has_more"] is True
        assert meta["offset"] == 0

    def test_filter_recipients_by_medical_status(self, api, registry_admin_headers):
        """PRD §4: "GET | `/nkr/recipients` | List Recipients (paginated,
        filterable)".
        PRD §3.2: "A new recipient is stamped with `listed_at_utc` at
        creation, has `medical_status` equal to `LISTED`,
        `chain_participation_state` equal to `POOL`, and
        `priority_boost_active` false."

        Design: Corner/endpoints/filter_recipients_by_medical_status
        """
        reset_clock()
        center = create_center()
        coord = make_center_coordinator_headers(center["id"])
        create_recipient(center, abo_type="A")
        create_recipient(center, abo_type="B")
        held = create_recipient(center, abo_type="O")
        get_success_data(api.recipient_medical_hold(held["id"], coord))
        resp = api.list_recipients(registry_admin_headers, params={"medical_status": "ON_HOLD"})
        data, meta = validate_paginated(resp)
        assert len(data) == 1
        assert data[0]["id"] == held["id"]

    def test_filter_donors_by_donor_kind(self, api, registry_admin_headers):
        """PRD §4: "GET | `/nkr/donors` | List Donors (paginated, filterable)".
        PRD §3.2: "a `donor_kind` — `PAIRED` for a donor entering with a
        recipient, `ALTRUISTIC` for a non-directed chain starter, or `BRIDGE`
        for a donor holding a bridge credit."

        Design: Corner/endpoints/filter_donors_by_donor_kind
        """
        reset_clock()
        center = create_center()
        create_donor(center, abo_type="A")
        create_donor(center, abo_type="B")
        altruistic = create_donor(center, abo_type="O", donor_kind="ALTRUISTIC")
        resp = api.list_donors(registry_admin_headers, params={"donor_kind": "ALTRUISTIC"})
        data, meta = validate_paginated(resp)
        assert len(data) == 1
        assert data[0]["id"] == altruistic["id"]

    def test_pagination_with_filtering_interaction(self, api, registry_admin_headers):
        """PRD §2.3: "List endpoints accept the query parameters `limit` and
        `offset`. `limit` defaults to 10, must be at least 1, and must not
        exceed 100. `offset` defaults to 0."
        PRD §4: "GET | `/nkr/donors` | List Donors (paginated, filterable)".

        Design: Corner/cross_cutting_layers/pagination_with_filtering_interaction
        """
        reset_clock()
        center = create_center()
        create_donor(center, abo_type="A")
        create_donor(center, abo_type="B")
        create_donor(center, abo_type="O")
        resp = api.list_donors(
            registry_admin_headers,
            params={"medical_status": "CLEARED", "limit": 1, "offset": 1},
        )
        data, meta = validate_paginated(resp)
        assert len(data) == 1
        assert meta["limit"] == 1
        assert meta["offset"] == 1
        assert meta["total_count"] == 3
        assert meta["has_more"] is True


# Imported late to keep the module header focused on factories/assertions.
from test_helpers import TEST_USERS as _TU  # noqa: E402

LOGISTICS = _TU["logistics_headers"]
