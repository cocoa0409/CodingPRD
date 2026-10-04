"""Wildfire defense dispatch: the vendor poll, the release cycle and zone capacity."""
from test_helpers import (
    api_client,
    create_agency,
    create_property,
    create_zone,
    get_success_data,
    make_agency_producer_headers,
    reload_property,
    reset_clock,
    request_dispatch,
    setup_zone_with_requested_dispatches,
    validate_error,
    validate_success,
)


def test_a_poll_assigns_exactly_one_request(api, underwriter_headers):
    """PRD 3.6: "Polling the vendor network assigns exactly one queued request per
    poll, drawn from the zone being polled."
    PRD 3.6: "Assignment moves the selected dispatch to `VENDOR_ASSIGNED`, sets its
    `vendor_ref` from the polled selection, stamps `assigned_at`, and recomputes
    `defense_in_progress` on the property to true."

    Design: Difficulty/non_linear_state_machine/wildfire_dispatch_vendor_release_returns_to_the_queue
    """
    zone, agency, requests = setup_zone_with_requested_dispatches(
        count=2, zone_code="ZG1R", agency_code="AG6R")
    poll = validate_success(api_client.poll_vendors(zone["id"], underwriter_headers), 200)
    assert poll["status"] == "VENDOR_ASSIGNED"
    assert poll["vendor_ref"] is not None
    assigned_property_id = poll["property_id"]

    listing = get_success_data(api_client.list_zone_dispatches(
        zone["id"], underwriter_headers))
    statuses = sorted(row["status"] for row in listing)
    assert statuses == ["REQUESTED", "VENDOR_ASSIGNED"]

    assert reload_property(assigned_property_id)["defense_in_progress"] is True
    others = [p for p, _d in requests if p["id"] != assigned_property_id]
    assert reload_property(others[0]["id"])["defense_in_progress"] is False


def test_a_released_dispatch_returns_to_the_queue_and_is_selectable_again(
        api, underwriter_headers):
    """PRD 3.6: "supplying a reference that matches the property's assigned vendor
    re-affirms the assignment, while supplying a null reference releases it, clearing
    `vendor_ref`, resetting `assigned_at` and returning the dispatch to `REQUESTED` so
    the next poll may select it again."

    Design: Difficulty/non_linear_state_machine/wildfire_dispatch_vendor_release_returns_to_the_queue
    """
    # Two dwellings are queued so the zone band stays normal once both enroll in
    # the active set; a lone dwelling would make the zone CRITICAL and a CRITICAL
    # band refuses release (PRD §3.6).
    zone, agency, requests = setup_zone_with_requested_dispatches(
        count=2, zone_code="ZG1S", agency_code="AG6S")
    prop, dispatch = requests[0]

    poll = validate_success(api_client.poll_vendors(zone["id"], underwriter_headers), 200)
    assert poll["status"] == "VENDOR_ASSIGNED"
    assert poll["assigned_at"] is not None
    assigned_prop = [p for p, _d in requests if p["id"] == poll["property_id"]][0]

    released = validate_success(api_client.dispatch_ack(
        assigned_prop["id"], zone["id"], None, make_agency_producer_headers(agency["id"])), 200)
    assert released["status"] == "REQUESTED"
    assert released["vendor_ref"] is None
    assert released["assigned_at"] is None
    assert reload_property(assigned_prop["id"])["defense_in_progress"] is False

    # The release edge is live, not terminal: the same row is re-selected.
    again = validate_success(api_client.poll_vendors(zone["id"], underwriter_headers), 200)
    assert again["id"] == poll["id"]
    assert again["status"] == "VENDOR_ASSIGNED"


def test_a_poll_beyond_the_zone_capacity_is_refused(api, underwriter_headers):
    """PRD 3.6: "A poll that would place a third overlapping assignment in the same
    zone is refused with `ERR_ZONE_DISPATCH_CAPACITY`"
    PRD 3.6: "each assignment occupies the half-open window from `assigned_at` to
    `assigned_at` plus 24 hours"

    Design: Difficulty/resource_temporal_overlap/wildfire_zone_capacity_window_with_buffer_and_aggregate_limit
    """
    zone, agency, requests = setup_zone_with_requested_dispatches(
        count=3, zone_code="ZQ1", agency_code="AG16")
    validate_success(api_client.poll_vendors(zone["id"], underwriter_headers), 200)
    validate_success(api_client.poll_vendors(zone["id"], underwriter_headers), 200)

    res = api_client.poll_vendors(zone["id"], underwriter_headers)
    validate_error(res, "ERR_ZONE_DISPATCH_CAPACITY", expected_status=422)

    listing = get_success_data(api_client.list_zone_dispatches(
        zone["id"], underwriter_headers))
    statuses = sorted(row["status"] for row in listing)
    assert statuses == ["REQUESTED", "VENDOR_ASSIGNED", "VENDOR_ASSIGNED"]


def test_the_capacity_window_expires_with_the_clock(api, underwriter_headers,
                                                    platform_admin_headers):
    """PRD 2.4: "each defense assignment occupies a 24-hour window on its zone."
    PRD 3.6: "each assignment occupies the half-open window from `assigned_at` to
    `assigned_at` plus 24 hours"

    Design: Difficulty/resource_temporal_overlap/wildfire_zone_capacity_window_with_buffer_and_aggregate_limit
    """
    zone, agency, requests = setup_zone_with_requested_dispatches(
        count=3, zone_code="ZQ1B", agency_code="AG16B")
    validate_success(api_client.poll_vendors(zone["id"], underwriter_headers), 200)
    validate_success(api_client.poll_vendors(zone["id"], underwriter_headers), 200)
    validate_error(api_client.poll_vendors(zone["id"], underwriter_headers),
                   "ERR_ZONE_DISPATCH_CAPACITY", expected_status=422)

    # Past the fixed-length windows the same zone polls cleanly again.
    reset_clock("2026-09-02T01:00:00Z")
    third = validate_success(api_client.poll_vendors(zone["id"], underwriter_headers), 200)
    assert third["status"] == "VENDOR_ASSIGNED"


def test_an_empty_pool_is_refused_as_no_eligible_vendor(api, underwriter_headers):
    """PRD 3.6: "a poll finding no eligible request at all — an empty pool — is refused
    with `ERR_NO_ELIGIBLE_VENDOR`."

    Design: Difficulty/boundary_precision_check/vendor_poll_empty_pool_and_zone_capacity_boundaries
    """
    zone = create_zone(zone_code="ZM2", state_event="ACTIVE")
    create_agency(agency_code="AG12B")

    res = api_client.poll_vendors(zone["id"], underwriter_headers)
    validate_error(res, "ERR_NO_ELIGIBLE_VENDOR", expected_status=422)


def test_dropping_the_zone_event_cancels_the_outstanding_assignment(
        api, underwriter_headers, platform_admin_headers):
    """PRD 3.4: "Dropping a zone's `state_event` below `ACTIVE` cancels every defense
    dispatch in that zone that has reached vendor assignment, and recomputes
    `defense_in_progress` on every affected property."

    Design: Difficulty/boundary_precision_check/vendor_poll_empty_pool_and_zone_capacity_boundaries
    """
    zone, agency, requests = setup_zone_with_requested_dispatches(
        count=3, zone_code="ZM1S", agency_code="AG12S")
    validate_success(api_client.poll_vendors(zone["id"], underwriter_headers), 200)
    validate_success(api_client.poll_vendors(zone["id"], underwriter_headers), 200)

    validate_success(api_client.set_zone_event(
        zone["id"], "WATCH", underwriter_headers), 200)

    listing = get_success_data(api_client.list_zone_dispatches(
        zone["id"], underwriter_headers))
    assert sorted(row["status"] for row in listing) == [
        "CANCELLED", "CANCELLED", "REQUESTED"]

    # A poll is only eligible against a zone in an ACTIVE event, so the WATCH
    # level refuses the sweep rather than reassigning the freed vendor slot
    # (PRD §3.6: "A poll that finding no eligible request at all — an empty pool
    # — is refused with `ERR_NO_ELIGIBLE_VENDOR`").
    res = api_client.poll_vendors(zone["id"], underwriter_headers)
    validate_error(res, "ERR_NO_ELIGIBLE_VENDOR", expected_status=422)


def test_advancing_a_requested_dispatch_is_refused(api, underwriter_headers):
    """PRD 3.6: "An underwriter advances a dispatch one step at a time: from
    `VENDOR_ASSIGNED` to `ON_SITE`, and from `ON_SITE` to `COMPLETED`."

    Design: Corner/state_machines/defense_dispatch_advance_from_requested_returns_invalid_state
    """
    zone = create_zone(zone_code="ZT1", state_event="ACTIVE")
    agency = create_agency(agency_code="AGT1")
    prop = create_property(zone["id"], agency["id"])
    dispatch = request_dispatch(prop["id"], underwriter_headers)
    assert dispatch["status"] == "REQUESTED"

    res = api_client.advance_dispatch(dispatch["id"], underwriter_headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    still = get_success_data(api_client.list_property_dispatches(
        prop["id"], underwriter_headers))[0]
    assert still["status"] == "REQUESTED"
    assert still["assigned_at"] is None


def test_a_dispatch_request_outside_an_active_event_is_refused(api, underwriter_headers):
    """PRD 3.6: "a defense request raised against a zone whose event is not `ACTIVE` is
    rejected with `ERR_ZONE_EVENT_INACTIVE` rather than queued."

    Design: Corner/errors/every_error_code_is_reachable_from_a_declared_endpoint
    """
    zone = create_zone(zone_code="ZU1D", wildland_urban_interface_band="OUTSIDE_WUI",
                       exposure_band="STANDARD", sustained_wind_mph=20)
    agency = create_agency(agency_code="AGU1D")
    prop = create_property(zone["id"], agency["id"])
    assert zone["state_event"] == "NONE"

    res = api_client.request_dispatch(prop["id"], underwriter_headers)
    validate_error(res, "ERR_ZONE_EVENT_INACTIVE", expected_status=422)

    assert get_success_data(api_client.list_property_dispatches(
        prop["id"], underwriter_headers)) == []