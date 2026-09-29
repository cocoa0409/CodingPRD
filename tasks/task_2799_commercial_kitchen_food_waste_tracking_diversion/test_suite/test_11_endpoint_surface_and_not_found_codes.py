"""Allocation-line endpoint surface, the empty data-quality scan, and the not-found
code every unresolved identifier answers with.
"""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_consignment,
    assert_consignment_line,
    assert_waste_entry,
    factories,
    fixtures,
    make_kitchen_staff_headers,
    make_platform_admin_headers,
    make_shift_lead_headers,
    make_site_sustainability_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_NOON = "2026-08-01T12:00:00Z"
CAPTURED_AT = "2026-08-01T10:00:00Z"
PICKUP_WINDOW = {
    "pickup_window_start": "2026-08-02T09:00:00Z",
    "pickup_window_end": "2026-08-02T11:00:00Z",
}


def _site_with_draft_consignment():
    """Clock at noon, one 1000 g morning capture, and a DRAFT COMPOST consignment."""
    fixtures.set_clock(CLOCK_NOON)
    return fixtures.site_with_draft_consignment(
        entry_overrides={"captured_at": CAPTURED_AT},
        consignment_overrides=dict(PICKUP_WINDOW),
    )


class TestAllocationLineDeletion:
    """Removing an allocation line from a DRAFT consignment."""

    def test_deleting_a_line_empties_both_filtered_listings(self, api):
        """Deleting the only line leaves neither parent's filtered listing holding it.

        PRD Coverage: "Lines may be listed filtered by `consignment_id` or by `waste_entry_id`, which is the reverse-navigation read from a capture to everywhere its grams went." "Deleting a line — permitted only while the consignment is `DRAFT`, and available to the same two roles — restores the capture's unrouted grams exactly, so the identity that a capture's `weight_grams` equals its routed plus its unrouted grams holds continuously and with zero drift."

        Design: Corner/endpoints/deleting_a_consignment_line_removes_it_from_both_listings
        """
        world = _site_with_draft_consignment()
        site_id = world["site"]["id"]
        consignment_id = world["consignment"]["id"]
        entry_id = world["entry"]["id"]
        line = fixtures.add_line(site_id, consignment_id, entry_id, 400)

        headers = make_site_sustainability_manager_headers(site_id)
        deleted = validate_success(api.delete_consignment_line(line["id"], headers), 200)
        assert deleted == {}, "the deletion answers with an empty data object"

        by_consignment, consignment_meta = validate_paginated(
            api.list_consignment_lines(headers, consignment_id=consignment_id)
        )
        assert consignment_meta["total_count"] == 0
        assert by_consignment == []

        by_entry, entry_meta = validate_paginated(
            api.list_consignment_lines(headers, waste_entry_id=entry_id)
        )
        assert entry_meta["total_count"] == 0
        assert by_entry == []

        entry = fixtures.read_entry(entry_id)
        assert_waste_entry(entry)
        assert entry["routed_weight_grams"] == 0
        assert entry["unrouted_weight_grams"] == 1000

    def test_the_deleted_line_is_a_hard_delete_and_its_consignment_totals_reset(self, api):
        """The row is really gone, so the by-id read is a not-found and the parent totals fall to zero.

        PRD Coverage: "That single identifier is resolved before any body content is inspected, and a path identifier that names no existing row yields that entity's not-found error." "For the consignment, `staged_weight_grams` becomes the sum of `allocated_weight_grams` over its lines and `line_count` becomes the number of lines attached."

        Design: Corner/endpoints/deleting_a_consignment_line_removes_it_from_both_listings
        """
        world = _site_with_draft_consignment()
        site_id = world["site"]["id"]
        consignment_id = world["consignment"]["id"]
        line = fixtures.add_line(site_id, consignment_id, world["entry"]["id"], 400)

        headers = make_site_sustainability_manager_headers(site_id)
        validate_success(api.delete_consignment_line(line["id"], headers), 200)

        validate_error(
            api.get_consignment_line(line["id"], make_platform_admin_headers()),
            ApiErrorId.LINE_NOT_FOUND.value,
        )

        consignment = fixtures.read_consignment(consignment_id)
        assert_consignment(consignment)
        assert consignment["line_count"] == 0
        assert consignment["staged_weight_grams"] == 0


class TestAllocationLineLinksTwoParents:
    """The line is the junction row between one capture and one consignment."""

    def test_a_new_line_is_readable_from_the_consignment_and_from_the_capture_side(self, api):
        """The same allocation row comes back under either parent's filter.

        PRD Coverage: "**Allocation lines** attach captured grams to a consignment and may be created by either the owning `SiteSustainabilityManager` or a `ShiftLead`." "A line names its `consignment_id`, the `waste_entry_id` whose weight is being routed, and the `allocated_weight_grams` being routed, which may be a partial slice of the capture — the same capture can be split across several consignments and channels." "Lines may be listed filtered by `consignment_id` or by `waste_entry_id`, which is the reverse-navigation read from a capture to everywhere its grams went."

        Design: Corner/endpoints/consignment_line_links_an_entry_to_a_consignment_and_is_readable_from_both_sides
        """
        world = _site_with_draft_consignment()
        site_id = world["site"]["id"]
        consignment_id = world["consignment"]["id"]
        entry_id = world["entry"]["id"]

        payload = factories.create_consignment_line_payload(consignment_id, entry_id, 250)
        line = validate_success(
            api.create_consignment_line(payload, make_shift_lead_headers("sl-1")), 201
        )
        assert line["consignment_id"] == consignment_id
        assert line["waste_entry_id"] == entry_id
        assert line["allocated_weight_grams"] == 250

        reader = make_site_sustainability_manager_headers(site_id)
        by_consignment, consignment_meta = validate_paginated(
            api.list_consignment_lines(reader, consignment_id=consignment_id)
        )
        assert consignment_meta["total_count"] == 1
        assert [row["id"] for row in by_consignment] == [line["id"]]

        by_entry, entry_meta = validate_paginated(
            api.list_consignment_lines(reader, waste_entry_id=entry_id)
        )
        assert entry_meta["total_count"] == 1
        assert [row["id"] for row in by_entry] == [line["id"]]

    def test_the_line_carries_no_version_while_both_parents_reflect_the_link(self, api):
        """An allocation line is an immutable event record, yet both parents move.

        PRD Coverage: "A line is an immutable event record: it carries only `id` and `created_at`, with no `updated_at` and no `version` of its own." "`ConsignmentLine` is the one exception: an allocation line is an immutable event record, so it carries only `id` and `created_at` — it has neither `updated_at` nor `version`, and nothing in the system ever bumps a line's version because it has none." "For the consignment, `staged_weight_grams` becomes the sum of `allocated_weight_grams` over its lines and `line_count` becomes the number of lines attached."

        Design: Corner/endpoints/consignment_line_links_an_entry_to_a_consignment_and_is_readable_from_both_sides
        """
        world = _site_with_draft_consignment()
        consignment_id = world["consignment"]["id"]
        entry_id = world["entry"]["id"]

        payload = factories.create_consignment_line_payload(consignment_id, entry_id, 250)
        line = validate_success(
            api.create_consignment_line(payload, make_shift_lead_headers("sl-1")), 201
        )
        assert_consignment_line(line)
        assert "version" not in line
        assert "updated_at" not in line

        consignment = fixtures.read_consignment(consignment_id)
        assert consignment["staged_weight_grams"] == 250
        assert consignment["line_count"] == 1

        entry = fixtures.read_entry(entry_id)
        assert_waste_entry(entry)
        assert entry["routed_weight_grams"] == 250
        assert entry["unrouted_weight_grams"] == 750


class TestEmptyDataQualityScan:
    """The scan is the one bulk creator whose empty result is a success."""

    def test_scan_of_a_site_with_no_stations_and_no_shifts_is_an_empty_success(self, api):
        """A site with nothing to interrogate answers 200 with an empty array of findings.

        PRD Coverage: "A data-quality scan is requested by the owning `SiteSustainabilityManager` or by a `PlatformAdmin` for one `site_id` and one `scan_date`, and it materialises findings as durable rows." "The scan answers with an array of exactly the findings it created, in creation order; a scan of a site that has no `ACTIVE` station and no shift on that date is still a success carrying an empty array, not an error."

        Design: Corner/endpoints/scan_of_a_site_with_no_stations_and_no_shifts_is_an_empty_success
        """
        fixtures.set_clock(CLOCK_NOON)
        site = fixtures.create_site()
        headers = make_site_sustainability_manager_headers(site["id"])

        payload = factories.create_data_quality_scan_payload(site["id"], "2026-08-01")
        response = api.create_data_quality_scan(payload, headers)
        findings = validate_success(response, 200)
        assert findings == [], "a site with no ACTIVE station and no shift creates no findings"
        assert response.json()["response_type"] == "array"

        listed, meta = validate_paginated(api.list_findings(headers, site_id=site["id"]))
        assert meta["total_count"] == 0
        assert listed == []


# The pinned walk: each single-record read answers with the not-found code of the
# entity that owns the collection the path addresses, in this order.
OWNING_ENTITY_READS = [
    ("get_tracking_station", ApiErrorId.STATION_NOT_FOUND.value),
    ("get_food_type", ApiErrorId.FOOD_TYPE_NOT_FOUND.value),
    ("get_shift", ApiErrorId.SHIFT_NOT_FOUND.value),
    ("get_waste_entry", ApiErrorId.ENTRY_NOT_FOUND.value),
    ("get_baseline_period", ApiErrorId.BASELINE_NOT_FOUND.value),
    ("get_reduction_target", ApiErrorId.TARGET_NOT_FOUND.value),
    ("get_hauler", ApiErrorId.HAULER_NOT_FOUND.value),
    ("get_consignment", ApiErrorId.CONSIGNMENT_NOT_FOUND.value),
    ("get_consignment_line", ApiErrorId.LINE_NOT_FOUND.value),
    ("get_hauler_ticket", ApiErrorId.TICKET_NOT_FOUND.value),
    ("get_alert", ApiErrorId.ALERT_NOT_FOUND.value),
    ("get_finding", ApiErrorId.FINDING_NOT_FOUND.value),
    ("get_rollup", ApiErrorId.ROLLUP_NOT_FOUND.value),
    ("get_site", ApiErrorId.SITE_NOT_FOUND.value),
    ("get_recipe", ApiErrorId.RECIPE_NOT_FOUND.value),
]


class TestUnknownPathIdentifierCodes:
    """Each unresolved path identifier answers with its owning entity's own code."""

    @pytest.mark.parametrize(
        "read_name,expected_error_id",
        OWNING_ENTITY_READS,
        ids=[name for name, _ in OWNING_ENTITY_READS],
    )
    def test_unknown_path_id_answers_its_owning_entity_not_found_code(
        self, api, read_name, expected_error_id
    ):
        """Over an empty database every single-record read answers with its own not-found code.

        PRD Coverage: "6. Existence of every identifier appearing in the URL path — the owning entity's not-found error." "That single identifier is resolved before any body content is inspected, and a path identifier that names no existing row yields that entity's not-found error."

        Design: Corner/errors/every_unknown_path_id_returns_its_owning_entity_not_found_code
        """
        fixtures.set_clock(CLOCK_NOON)

        response = getattr(api, read_name)(NON_EXISTENT_UUID, make_platform_admin_headers())
        validate_error(response, expected_error_id)
        assert response.status_code == 404


class TestUnresolvableBodyForeignKeys:
    """A foreign key supplied in the body answers with the referenced entity's code."""

    def test_a_capture_naming_a_phantom_food_type_is_a_food_type_not_found(self, api):
        """A real station and shift with an unissued `food_type_id` is a food-type not-found.

        PRD Coverage: "7. Existence of every foreign key supplied in the request body, including every member of a `site_ids` array — the referenced entity's not-found error." "The request names the `station_id` that weighed the loss, the `shift_id` the loss is booked to, the `food_type_id` of the discarded item, the net `weight_grams` which must be greater than 0 and no more than 200000, and a `loss_reason` drawn from `OVERPRODUCTION`, `SPOILAGE`, `TRIM`, `EXPIRATION`, `PLATE_WASTE` and `CONTAMINATION`."

        Design: Corner/errors/body_foreign_keys_that_resolve_to_nothing_are_not_found_at_priority_forty_five
        """
        fixtures.set_clock(CLOCK_NOON)
        site = fixtures.create_site()
        station = fixtures.create_station(site["id"], station_code="PREP-1", station_kind="PREP")
        shift = fixtures.open_shift(
            site["id"], shift_date="2026-08-01", shift_code="AM", meals_served=250
        )

        payload = factories.create_waste_entry_payload(
            station["id"], shift["id"], NON_EXISTENT_UUID, captured_at=CAPTURED_AT
        )
        validate_error(
            api.create_waste_entry(payload, make_kitchen_staff_headers("ks-1")),
            ApiErrorId.FOOD_TYPE_NOT_FOUND.value,
        )

        listed, meta = validate_paginated(
            api.list_waste_entries(make_platform_admin_headers(), shift_id=shift["id"])
        )
        assert meta["total_count"] == 0, "the refused capture wrote no row"
        assert listed == []

    def test_a_consignment_naming_a_phantom_hauler_is_a_hauler_not_found(self, api):
        """A consignment whose `hauler_id` was never issued is a hauler not-found.

        PRD Coverage: "7. Existence of every foreign key supplied in the request body, including every member of a `site_ids` array — the referenced entity's not-found error." "A consignment is opened by the owning `SiteSustainabilityManager` with the `site_id` the material leaves from, the `hauler_id` collecting it, a `channel` drawn from the same four values, and a reserved pickup interval given by `pickup_window_start` inclusive and `pickup_window_end` exclusive, where the end must be strictly after the start."

        Design: Corner/errors/body_foreign_keys_that_resolve_to_nothing_are_not_found_at_priority_forty_five
        """
        fixtures.set_clock(CLOCK_NOON)
        site = fixtures.create_site()
        headers = make_site_sustainability_manager_headers(site["id"])

        payload = factories.create_consignment_payload(
            site["id"], NON_EXISTENT_UUID, channel="COMPOST", **PICKUP_WINDOW
        )
        validate_error(
            api.create_consignment(payload, headers), ApiErrorId.HAULER_NOT_FOUND.value
        )

        listed, meta = validate_paginated(api.list_consignments(headers, site_id=site["id"]))
        assert meta["total_count"] == 0, "the refused consignment wrote no row"
        assert listed == []
