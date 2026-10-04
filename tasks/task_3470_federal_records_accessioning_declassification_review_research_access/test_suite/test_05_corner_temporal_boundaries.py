"""Corner coverage: inclusive/exclusive temporal boundaries — appeal window,
transfer lag, cooling period, visit window, unit span and unit range."""

import test_helpers as th

E = th.ApiErrorId


def test_appeal_window_inclusive_boundary(api):
    """PRD §3.9: "The appeal window is thirty days: the appeal must arrive
    while the clock stands at or before `decided_at` plus 30 days, with the
    boundary inclusive — an appeal at exactly the thirtieth day is timely, and
    one a day later is rejected with `ERR_APPEAL_WINDOW_CLOSED` (409)."

    Design: Corner/validations/appeal_window_inclusive_boundary
    """
    th.set_clock()
    bundle = th.setup_classified_collection(classification_default="SECRET")
    collection = bundle["collection"]
    ada = th.create_active_researcher()
    researcher = th.make_researcher_headers(ada["id"])

    f1 = th.create_denied_foia(ada, collection, ["B1"],
                               description_of_records="f1 records")
    f2 = th.create_denied_foia(ada, collection, ["B3"],
                               description_of_records="f2 records")
    assert th.same_instant(f1["decided_at"], th.STARTUP_CLOCK_UTC)

    # Exactly decided_at + 30 days: timely.
    th.set_clock("2026-10-01T00:00:00Z")
    appealed = th.validate_success(
        api.appeal_foia_request(
            f1["id"], th.appeal_payload("timely at the boundary"), headers=researcher
        ),
        200,
    )
    assert appealed["status"] == "APPEALED"

    # One day later: the window is closed.
    th.set_clock("2026-10-02T00:00:00Z")
    th.validate_error(
        api.appeal_foia_request(
            f2["id"], th.appeal_payload("one day late"), headers=researcher
        ),
        E.ERR_APPEAL_WINDOW_CLOSED,
    )
    after = th.get_success_data(
        api.get_foia_request(f2["id"], headers=th.TEST_USERS["foia_officer_headers"])
    )
    assert after["status"] == "DENIED"


def test_transfer_lag_inclusive_boundary(api):
    """PRD §3.3: "The lag gate compares the logical clock against the
    anniversary of `records_cutoff_date` shifted forward by the schedule's
    `transfer_lag_years`: accession is allowed when the clock has reached that
    anniversary, inclusively — a transfer whose lag anniversary is exactly
    today may be accessioned today — and is rejected with
    `ERR_TRANSFER_LAG_NOT_ELAPSED` (409) while the clock still stands before
    it."

    Design: Corner/validations/transfer_lag_inclusive_boundary
    """
    th.set_clock()
    agency = th.create_agency()
    schedule = th.create_approved_schedule(
        agency, schedule_number="SCH-DOJ-031", title="Long-lag Files",
        transfer_lag_years=25,
    )
    transfer = th.create_validated_transfer(agency, schedule, unit_count=10,
                                            linear_feet=2.0)
    archivist = th.TEST_USERS["processing_archivist_headers"]

    # One day before the 25-year lag anniversary: rejected.
    th.set_clock("2026-03-14T00:00:00Z")
    th.validate_error(
        api.accession_transfer(
            transfer["id"], th.accession_payload("too early"), headers=archivist
        ),
        E.ERR_TRANSFER_LAG_NOT_ELAPSED,
    )
    still = th.get_success_data(api.get_transfer(transfer["id"], headers=archivist))
    assert still["status"] == "VALIDATED"

    # At exactly the anniversary: allowed.
    th.set_clock("2026-03-15T00:00:00Z")
    accessioned = th.validate_success(
        api.accession_transfer(
            transfer["id"], th.accession_payload("exactly on the anniversary"),
            headers=archivist,
        ),
        200,
    )
    assert accessioned["status"] == "ACCESSIONED"


def test_cooling_period_inclusive_boundary(api):
    """PRD §3.6: "A statutory cooling period then runs: release is allowed only
    once the clock has reached `notified_at` plus 30 days, with the boundary
    inclusive, so a release at exactly the thirtieth day proceeds while
    anything earlier is rejected with `ERR_COOLING_PERIOD_ACTIVE` (409)."
    PRD §3.6: "Release moves the restriction to its terminal `RELEASED` status
    and stamps `released_at`. It then recomputes the collection's
    `restriction_posture` and advances the collection's `version`"

    Design: Corner/validations/cooling_period_inclusive_boundary
    """
    th.set_clock()
    bundle = th.setup_presidential_collection()
    collection = bundle["collection"]
    chief = th.TEST_USERS["chief_archivist_headers"]

    restriction = th.impose_restriction(collection, "P5_CONFIDENTIAL_ADVICE")
    restriction = th.designate_representative(restriction, "rep-44")
    restriction = th.notify_restriction(restriction)
    assert th.same_instant(restriction["notified_at"], th.STARTUP_CLOCK_UTC)

    # One second before the 30-day cooling boundary: rejected.
    th.set_clock("2026-09-30T23:59:59Z")
    th.validate_error(api.release_restriction(restriction["id"], headers=chief),
                      E.ERR_COOLING_PERIOD_ACTIVE)

    # At exactly notified_at + 30 days: allowed.
    th.set_clock("2026-10-01T00:00:00Z")
    released = th.validate_success(
        api.release_restriction(restriction["id"], headers=chief), 200
    )
    assert released["status"] == "RELEASED"
    assert th.same_instant(released["released_at"], "2026-10-01T00:00:00Z")
    assert th.read_collection(collection["id"])["restriction_posture"] == "PUBLIC"


def test_visit_window_boundaries(api):
    """PRD §3.7: "The `visit_date` must then fall within the booking window —
    on or after the clock's current instant and no later than 30 days out
    (`ERR_VISIT_DATE_OUT_OF_WINDOW`, 409)."

    Design: Corner/validations/visit_window_boundaries
    """
    th.set_clock()
    bundle = th.setup_public_described_collection()
    collection_id = bundle["collection"]["id"]
    ada = th.create_active_researcher()
    researcher = th.make_researcher_headers(ada["id"])

    # Before the clock: rejected.
    th.validate_error(
        api.create_pull_request(
            th.pull_request_payload(ada["id"], collection_id, 1, 5,
                                    "2026-08-31T00:00:00Z"),
            headers=researcher,
        ),
        E.ERR_VISIT_DATE_OUT_OF_WINDOW,
    )
    # Exactly clock + 30 days: allowed.
    resp = api.create_pull_request(
        th.pull_request_payload(ada["id"], collection_id, 1, 5,
                                "2026-10-01T00:00:00Z"),
        headers=researcher,
    )
    th.validate_success(resp, 201)
    # One day beyond: rejected.
    th.validate_error(
        api.create_pull_request(
            th.pull_request_payload(ada["id"], collection_id, 6, 10,
                                    "2026-10-02T00:00:00Z"),
            headers=researcher,
        ),
        E.ERR_VISIT_DATE_OUT_OF_WINDOW,
    )


def test_unit_span_limit_boundary(api):
    """PRD §3.7: "Second, the reserved span — the count of units from
    `unit_start` through `unit_end` inclusive — may not exceed 24 units
    (`ERR_UNIT_SPAN_LIMIT_EXCEEDED`, 409)."

    Design: Corner/validations/unit_span_limit_boundary
    """
    th.set_clock()
    bundle = th.setup_public_described_collection()
    collection_id = bundle["collection"]["id"]
    ada = th.create_active_researcher()
    researcher = th.make_researcher_headers(ada["id"])

    # Span 24 is the inclusive cap: succeeds.
    resp = api.create_pull_request(
        th.pull_request_payload(ada["id"], collection_id, 1, 24,
                                "2026-09-10T00:00:00Z"),
        headers=researcher,
    )
    th.validate_success(resp, 201)
    # Span 25: rejected.
    th.validate_error(
        api.create_pull_request(
            th.pull_request_payload(ada["id"], collection_id, 25, 49,
                                    "2026-09-12T00:00:00Z"),
            headers=researcher,
        ),
        E.ERR_UNIT_SPAN_LIMIT_EXCEEDED,
    )

    data, meta = th.validate_paginated(
        api.list_pull_requests(
            headers=th.TEST_USERS["research_room_staff_headers"],
            params={"researcher_id": ada["id"]},
        )
    )
    assert len(data) == 1
    assert meta["total_count"] == 1


def test_unit_range_invalid_bounds(api):
    """PRD §3.7: "First, the unit range must lie inside the collection's
    holdings: `unit_start` at least 1, `unit_end` at most the collection's
    `units_total`, and `unit_start` not greater than `unit_end`
    (`ERR_UNIT_RANGE_INVALID`, 400)."

    Design: Corner/validations/unit_range_invalid_bounds
    """
    th.set_clock()
    bundle = th.setup_public_described_collection()
    collection_id = bundle["collection"]["id"]
    ada = th.create_active_researcher()
    researcher = th.make_researcher_headers(ada["id"])

    th.validate_error(
        api.create_pull_request(
            th.pull_request_payload(ada["id"], collection_id, 0, 5,
                                    "2026-09-10T00:00:00Z"),
            headers=researcher,
        ),
        E.ERR_UNIT_RANGE_INVALID,
    )
    th.validate_error(
        api.create_pull_request(
            th.pull_request_payload(ada["id"], collection_id, 45, 51,
                                    "2026-09-10T00:00:00Z"),
            headers=researcher,
        ),
        E.ERR_UNIT_RANGE_INVALID,
    )
