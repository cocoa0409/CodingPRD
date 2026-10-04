"""Tests for slot overlap semantics, slot lifecycle cycles, bulk publish
supersede semantics, and the OCC guard on bulk publish (PRD §3.2 and §2.9).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    book_slot,
    create_patient,
    create_slot,
    get_provider,
    get_slot,
    make_patient_headers,
    make_provider_headers,
    setup_bookable_practice,
    slot_time,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSlotHalfOpenAdjacencyVsOverlap:
    def test_adjacent_slots_accepted_overlapping_rejected(self, api):
        """PRD §3.2: "A new slot that overlaps any existing slot of the same provider whose status is `OPEN` or `BOOKED` is rejected with `ERR_SLOT_OVERLAP`; adjacency — one slot's `end_at` exactly equal to another's `start_at` — does not count as overlap, and `CLOSED` slots never block anything."

        Design: Difficulty/resource_temporal_overlap/slot_half_open_adjacency_vs_overlap
        """
        ctx = setup_bookable_practice(
            slot_windows=[("2026-09-03T10:00:00Z", "2026-09-03T10:30:00Z")]
        )
        prov_id = ctx["provider"]["id"]
        # Adjacent after: starts exactly at s1.end_at — must succeed.
        r2 = api_client.create_slot(
            prov_id,
            {"start_at": "2026-09-03T10:30:00Z", "end_at": "2026-09-03T11:00:00Z"},
            make_provider_headers(prov_id),
        )
        validate_success(r2, 201)
        # Overlapping by 15 minutes — must fail.
        r_overlap = api_client.create_slot(
            prov_id,
            {"start_at": "2026-09-03T10:15:00Z", "end_at": "2026-09-03T10:45:00Z"},
            make_provider_headers(prov_id),
        )
        validate_error(r_overlap, ApiErrorId.ERR_SLOT_OVERLAP)
        # Adjacent before: ends exactly at s1.start_at — must succeed.
        r3 = api_client.create_slot(
            prov_id,
            {"start_at": "2026-09-03T09:30:00Z", "end_at": "2026-09-03T10:00:00Z"},
            make_provider_headers(prov_id),
        )
        validate_success(r3, 201)

    def test_overlap_check_leaves_exactly_three_open_slots(self, api):
        """PRD §3.2: "A new slot that overlaps any existing slot of the same provider whose status is `OPEN` or `BOOKED` is rejected with `ERR_SLOT_OVERLAP`; adjacency — one slot's `end_at` exactly equal to another's `start_at` — does not count as overlap, and `CLOSED` slots never block anything."

        Design: Difficulty/resource_temporal_overlap/slot_half_open_adjacency_vs_overlap
        """
        ctx = setup_bookable_practice(
            slot_windows=[("2026-09-03T10:00:00Z", "2026-09-03T10:30:00Z")]
        )
        prov_id = ctx["provider"]["id"]
        api_client.create_slot(
            prov_id,
            {"start_at": "2026-09-03T10:30:00Z", "end_at": "2026-09-03T11:00:00Z"},
            make_provider_headers(prov_id),
        )
        api_client.create_slot(
            prov_id,
            {"start_at": "2026-09-03T10:15:00Z", "end_at": "2026-09-03T10:45:00Z"},
            make_provider_headers(prov_id),
        )
        api_client.create_slot(
            prov_id,
            {"start_at": "2026-09-03T09:30:00Z", "end_at": "2026-09-03T10:00:00Z"},
            make_provider_headers(prov_id),
        )
        resp = api_client.list_slots(
            make_provider_headers(prov_id), params={"provider_id": prov_id, "status": "OPEN"}
        )
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 3, (
            f"expected exactly 3 OPEN slots after one rejection, got {meta['total_count']}"
        )


class TestSlotOpenBookedReleaseRebookCycle:
    def test_open_booked_open_booked_cycle(self, api):
        """PRD §3.2: "A slot is born `OPEN`. Booking flips it to `BOOKED` and sets `current_booking_id` to the occupying booking's id; a cancellation of that booking releases it back to `OPEN` and clears `current_booking_id` to null."

        Design: Difficulty/non_linear_state_machine/slot_open_booked_release_rebook_cycle
        """
        ctx = setup_bookable_practice(slot_windows=[slot_time(48)])
        slot = ctx["slots"][0]
        pat1 = create_patient(email="p1@x.com", full_name="Pat One")
        pat2 = create_patient(email="p2@x.com", full_name="Pat Two")
        b1 = book_slot(slot["id"], pat1["id"], ctx["type"]["id"])
        api_client.cancel_booking(b1["id"], make_patient_headers(pat1["id"]))
        slot_mid = get_slot(slot["id"])
        assert slot_mid["status"] == "OPEN"
        b2 = book_slot(slot["id"], pat2["id"], ctx["type"]["id"])
        slot_end = get_slot(slot["id"])
        assert slot_end["status"] == "BOOKED"
        assert slot_end["current_booking_id"] == b2["id"]

    def test_version_advances_on_every_hop_and_cancel_reason_patient(self, api):
        """PRD §2.4: "version` is an integer that starts at creation and increments by 1 on every mutation of the resource."
        PRD §3.5: "The booking's `cancel_reason` records who cancelled: `PATIENT` for a patient actor, `PRACTICE` for a `PracticeStaff` actor, and `RELIABILITY_GATE` when the system cancels."

        Design: Difficulty/non_linear_state_machine/slot_open_booked_release_rebook_cycle
        """
        ctx = setup_bookable_practice(slot_windows=[slot_time(48)])
        slot = ctx["slots"][0]
        v1 = slot["version"]
        pat1 = create_patient(email="p1@x.com", full_name="Pat One")
        b1 = book_slot(slot["id"], pat1["id"], ctx["type"]["id"])
        api_client.cancel_booking(b1["id"], make_patient_headers(pat1["id"]))
        slot_mid = get_slot(slot["id"])
        assert slot_mid["version"] == v1 + 2, (
            f"book + cancel are two mutations, expected version {v1 + 2}, got {slot_mid['version']}"
        )
        b1_after = api_client.get_booking(b1["id"], make_patient_headers(pat1["id"]))
        from test_helpers import get_success_data
        b1_data = get_success_data(b1_after)
        assert b1_data["status"] == "CANCELLED"
        assert b1_data["cancel_reason"] == "PATIENT"
        assert b1_data["late_cancel"] is False


class TestSlotSupplyBookCancelRoundTrip:
    def test_open_count_conserved_across_book_cancel(self, api):
        """PRD §3.2: "A slot is born `OPEN`. Booking flips it to `BOOKED` and sets `current_booking_id` to the occupying booking's id; a cancellation of that booking releases it back to `OPEN` and clears `current_booking_id` to null."

        Design: Difficulty/compensating_invariant/slot_supply_book_cancel_round_trip
        """
        ctx = setup_bookable_practice(slot_windows=[slot_time(48)])
        slot = ctx["slots"][0]
        prov_id = ctx["provider"]["id"]
        patient = create_patient()

        def open_count():
            resp = api_client.list_slots(
                TEST_USERS["ops_admin_headers"],
                params={"provider_id": prov_id, "status": "OPEN"},
            )
            _, meta = validate_paginated(resp)
            return meta["total_count"]

        assert open_count() == 1
        booking = book_slot(slot["id"], patient["id"], ctx["type"]["id"])
        assert open_count() == 0, "the only slot is BOOKED"
        api_client.cancel_booking(booking["id"], make_patient_headers(patient["id"]))
        assert open_count() == 1, "the conserved OPEN-slot count equals the pre-booking count"

    def test_slot_state_and_version_after_round_trip(self, api):
        """PRD §3.2: "A slot is born `OPEN`. Booking flips it to `BOOKED` and sets `current_booking_id` to the occupying booking's id; a cancellation of that booking releases it back to `OPEN` and clears `current_booking_id` to null."
        PRD §2.4: "version` is an integer that starts at creation and increments by 1 on every mutation of the resource."

        Design: Difficulty/compensating_invariant/slot_supply_book_cancel_round_trip
        """
        ctx = setup_bookable_practice(slot_windows=[slot_time(48)])
        slot = ctx["slots"][0]
        v1 = slot["version"]
        patient = create_patient()
        booking = book_slot(slot["id"], patient["id"], ctx["type"]["id"])
        api_client.cancel_booking(booking["id"], make_patient_headers(patient["id"]))
        slot_after = get_slot(slot["id"])
        assert slot_after["status"] == "OPEN"
        assert slot_after["current_booking_id"] is None
        assert slot_after["version"] == v1 + 2


class TestBulkPublish:
    def test_supersede_closes_unlisted_future_open_slots(self, api):
        """PRD §3.2: "The bulk publish accepts a `slots` array alongside the OCC field `expected_provider_version` (§2.9), and applies supersede semantics atomically: every slot in the payload is created — each one overlap-checked against the provider's existing `OPEN` and `BOOKED` slots exactly as a single publish would be — and every future `OPEN` slot of the provider that is not present in the payload is closed with `close_reason` `PROVIDER_CLOSED`."

        Design: Corner/endpoints/bulk_publish_supersedes_unlisted_open_slots
        """
        ctx = setup_bookable_practice(slot_windows=[("2026-09-03T10:00:00Z", "2026-09-03T10:30:00Z")])
        prov_id = ctx["provider"]["id"]
        old_slot = ctx["slots"][0]
        prov = get_provider(prov_id)
        resp = api_client.bulk_publish_slots(
            prov_id,
            {
                "slots": [{"start_at": "2026-09-04T10:00:00Z", "end_at": "2026-09-04T10:30:00Z"}],
                "expected_provider_version": prov["version"],
            },
            make_provider_headers(prov_id),
        )
        data = validate_success(resp)
        assert data["created_count"] == 1
        assert data["closed_count"] == 1
        old_after = get_slot(old_slot["id"])
        assert old_after["status"] == "CLOSED"
        assert old_after["close_reason"] == "PROVIDER_CLOSED"

    def test_bulk_publish_increments_provider_version_by_one(self, api):
        """PRD §3.2: "A successful publish — single or bulk — increments the provider's `version` by 1; a booking, notably, does not touch the provider's version (only the slot's own `version` increments)."

        Design: Corner/endpoints/bulk_publish_supersedes_unlisted_open_slots
        """
        ctx = setup_bookable_practice(slot_windows=[("2026-09-03T10:00:00Z", "2026-09-03T10:30:00Z")])
        prov_id = ctx["provider"]["id"]
        prov_v = get_provider(prov_id)["version"]
        api_client.bulk_publish_slots(
            prov_id,
            {
                "slots": [{"start_at": "2026-09-04T10:00:00Z", "end_at": "2026-09-04T10:30:00Z"}],
                "expected_provider_version": prov_v,
            },
            make_provider_headers(prov_id),
        )
        prov_after = get_provider(prov_id)
        assert prov_after["version"] == prov_v + 1


class TestOccBulkPublishStaleVersion:
    def test_stale_version_rejected_412_and_rolled_back(self, api):
        """PRD §2.9: "The bulk schedule publish on a provider requires a non-optional `expected_provider_version` field in the request, carrying the provider `version` the client last observed. If the provider's current `version` does not match, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_bulk_publish_stale_version_rejected
        """
        ctx = setup_bookable_practice(slot_windows=[])
        prov_id = ctx["provider"]["id"]
        prov_v = get_provider(prov_id)["version"]
        slot = create_slot(prov_id, "2026-09-03T10:00:00Z", "2026-09-03T10:30:00Z")
        resp = api_client.bulk_publish_slots(
            prov_id,
            {
                "slots": [{"start_at": "2026-09-04T10:00:00Z", "end_at": "2026-09-04T10:30:00Z"}],
                "expected_provider_version": prov_v,
            },
            make_provider_headers(prov_id),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        slot_after = get_slot(slot["id"])
        assert slot_after["status"] == "OPEN", "the stale publish must be fully rolled back"

    def test_current_version_publish_succeeds(self, api):
        """PRD §2.9: "The bulk schedule publish on a provider requires a non-optional `expected_provider_version` field in the request, carrying the provider `version` the client last observed. If the provider's current `version` does not match, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_bulk_publish_stale_version_rejected
        """
        ctx = setup_bookable_practice(slot_windows=[])
        prov_id = ctx["provider"]["id"]
        prov_v = get_provider(prov_id)["version"]
        resp = api_client.bulk_publish_slots(
            prov_id,
            {
                "slots": [{"start_at": "2026-09-04T10:00:00Z", "end_at": "2026-09-04T10:30:00Z"}],
                "expected_provider_version": prov_v,
            },
            make_provider_headers(prov_id),
        )
        data = validate_success(resp)
        assert data["created_count"] == 1
        assert data["closed_count"] == 0
