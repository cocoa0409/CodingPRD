"""
Gates that read another entity's current state, and the interval arithmetic that decides
whether two commitments can coexist.

The cross-entity cases flip the gating entity's state and re-attempt the same operation.
The overlap cases pin the half-open technician occupation interval and the surgeon's
per-date graft bucket.
"""

from test_helpers import (
    COORDINATOR_HEADERS,
    ERR_SEROLOGY_PENDING,
    ERR_SURGEON_DAY_CAPACITY_EXCEEDED,
    ERR_SURGEON_NOT_CREDENTIALED,
    ERR_TECHNICIAN_DISPATCH_OVERLAP,
    MEDICAL_DIRECTOR_HEADERS,
    SHELF_LIFE_VARIANT_FINAL,
    SHELF_LIFE_VARIANT_PROVISIONAL,
    assert_dimensions,
    assert_instant_equals,
    factories,
    fixtures,
    total_count_of,
    validate_error,
)


def _graded_tissue_of_an_unresulted_donor(pinned_api):
    """A fully graded cornea whose donor has never had a serology panel drawn."""
    chain = fixtures.tissue_chain(
        pinned_api,
        donor_code="D-2846-CE1",
        with_serology=False,
        classify_tissues=False,
    )
    return chain


def test_classification_is_refused_while_the_donors_serology_is_pending(pinned_api):
    """
    Both exams are on file, but the donor has no resulted panel, so the cornea cannot be
    given a regulatory fate and keeps its recovery-time shelf life.

    PRD 3.5: "The donor's `serology_status` must not be `PENDING` — a resulted,
    non-invalidated panel must exist — refused with `ERR_SEROLOGY_PENDING`, because the bank
    will not assign a regulatory fate to tissue whose serology is unknown."

    Design: Difficulty/cross_entity_state_dependency/classification_gated_by_the_donors_serology_status
    """
    chain = _graded_tissue_of_an_unresulted_donor(pinned_api)
    tissue_id = chain["tissue_ids"][0]
    assert chain["donor"]["serology_status"] == "PENDING"

    response = pinned_api.classify_tissue(
        tissue_id, factories.classify_payload(), MEDICAL_DIRECTOR_HEADERS
    )

    validate_error(response, ERR_SEROLOGY_PENDING, 422)
    tissue = fixtures.read_tissue(pinned_api, tissue_id)
    assert tissue["disposition_status"] == "UNGRADED"
    assert tissue["classification"] is None
    assert tissue["tissue_quality_score"] is None
    assert tissue["shelf_life_variant"] == SHELF_LIFE_VARIANT_PROVISIONAL


def test_a_clean_panel_republishes_the_donor_and_unblocks_classification(pinned_api):
    """
    Resulting a non-reactive panel republishes the donor's serology as NEGATIVE, and the
    same classification then succeeds.

    PRD 3.2: "The panel moves `DRAWN → RESULTED` with `resulted_at` stamped from the logical
    clock, and the donor's `serology_status` is republished from the verdict: `NON_REACTIVE`
    becomes `NEGATIVE`, `REACTIVE` becomes `REACTIVE`, and `INDETERMINATE` becomes
    `INDETERMINATE`."

    Design: Difficulty/cross_entity_state_dependency/classification_gated_by_the_donors_serology_status
    """
    chain = _graded_tissue_of_an_unresulted_donor(pinned_api)
    tissue_id = chain["tissue_ids"][0]

    panel = fixtures.draw_panel(pinned_api, chain["donor_id"])
    resulted = fixtures.post_results(pinned_api, panel["id"])
    assert resulted["overall_result"] == "NON_REACTIVE"
    donor = fixtures.read_donor(pinned_api, chain["donor_id"])
    assert donor["serology_status"] == "NEGATIVE"

    classified = fixtures.classify(pinned_api, tissue_id)

    assert classified["classification"] == "TRANSPLANT_OPTICAL"
    assert classified["tissue_quality_score"] == 86
    assert_dimensions(classified, "ELIGIBLE", "IN_HOUSE")
    assert classified["shelf_life_variant"] == SHELF_LIFE_VARIANT_FINAL


def _prepared_shipment_for_a_credentialed_surgeon(pinned_api):
    """A confirmed, baselined parcel waiting on the loading dock."""
    chain = fixtures.tissue_chain(pinned_api, donor_code="D-2846-CE2")
    tissue_id = chain["tissue_ids"][0]
    booking = fixtures.surgeon_with_request(pinned_api, "Dr Tomas Rhee", "CTR-06", "PK")
    allocation, shipment = fixtures.prepared_shipment(
        pinned_api, tissue_id, booking.request_id
    )
    fixtures.add_reading(pinned_api, shipment["id"], "2026-08-03T09:45:00.000Z", 4.0)
    return tissue_id, booking, allocation, shipment


def test_dispatch_is_refused_while_the_receiving_surgeon_is_suspended(pinned_api):
    """
    Suspending the surgeon after the parcel was prepared blocks hand-off to the carrier and
    leaves every row where it stood.

    PRD 3.7: "The shipment must be `PREPARED`, its allocation must be `CONFIRMED`, the
    receiving surgeon must be `ACTIVE`, the tissue's `expires_at` must still be at or after
    the request's `surgery_date`, the tissue's `reissue_generation` must be at most 1, and —
    critically — the shipment must already carry **at least one temperature reading**, the
    pre-dispatch reading being the cold-chain baseline against which the first excursion
    segment is measured."

    Design: Difficulty/cross_entity_state_dependency/dispatch_gated_by_the_receiving_surgeons_credential_status
    """
    tissue_id, booking, _allocation, shipment = _prepared_shipment_for_a_credentialed_surgeon(
        pinned_api
    )
    fixtures.set_credential_status(pinned_api, booking.surgeon_id, "SUSPENDED")

    response = pinned_api.dispatch_shipment(
        shipment["id"],
        factories.dispatch_payload("2026-08-03T10:00:00.000Z"),
        COORDINATOR_HEADERS,
    )

    validate_error(response, ERR_SURGEON_NOT_CREDENTIALED, 422)
    unshipped = fixtures.read_shipment(pinned_api, shipment["id"])
    assert unshipped["status"] == "PREPARED"
    assert unshipped["shipped_at"] is None
    tissue = fixtures.read_tissue(pinned_api, tissue_id)
    assert_dimensions(tissue, "RESERVED", "IN_HOUSE")
    assert tissue["issue_count"] == 0


def test_restoring_the_credential_lets_the_same_parcel_leave(pinned_api):
    """
    Returning the surgeon to ACTIVE clears the gate, and the retried dispatch moves both
    tissue dimensions.

    PRD 3.7: "On success `shipped_at` is stored, the shipment moves `PREPARED →
    IN_TRANSIT`, and the tissue moves on **both** dimensions in the same request:
    `disposition_status` goes `RESERVED → ISSUED` and `custody_status` goes `IN_HOUSE →
    IN_TRANSIT`, or `RETURNED_TO_BANK → IN_TRANSIT` when this is a re-issue of previously
    returned tissue."

    Design: Difficulty/cross_entity_state_dependency/dispatch_gated_by_the_receiving_surgeons_credential_status
    """
    tissue_id, booking, _allocation, shipment = _prepared_shipment_for_a_credentialed_surgeon(
        pinned_api
    )
    fixtures.set_credential_status(pinned_api, booking.surgeon_id, "SUSPENDED")
    fixtures.set_credential_status(pinned_api, booking.surgeon_id, "ACTIVE")

    dispatched = fixtures.dispatch_shipment(
        pinned_api, shipment["id"], "2026-08-03T10:00:00.000Z"
    )

    assert dispatched["status"] == "IN_TRANSIT"
    assert_instant_equals(dispatched["shipped_at"], "2026-08-03T10:00:00.000Z", "shipped_at")
    tissue = fixtures.read_tissue(pinned_api, tissue_id)
    assert_dimensions(tissue, "ISSUED", "IN_TRANSIT")
    assert tissue["issue_count"] == 1


def _one_technician_and_three_donors(pinned_api):
    """One recovery technician approved for three separate donors."""
    technician = fixtures.create_technician(pinned_api, "Rosa Field", "RECOVERY_ONLY")
    donors = [
        fixtures.approved_donor(pinned_api, with_serology=False, donor_code=code)
        for code in ("D-2846-TO1", "D-2846-TO2", "D-2846-TO3")
    ]
    return technician, donors


def test_a_dispatch_starting_exactly_at_the_occupation_end_is_admitted(pinned_api):
    """
    The first dispatch occupies the technician until 11:00 and a second dispatch beginning
    at precisely 11:00 is legal, leaving two live occupations.

    PRD 3.4: "Because the interval excludes its right endpoint, **adjacency is legal**: a
    proposal whose `dispatched_at` equals a candidate's `occupation_end_at` produces no
    conflict and is admitted."

    Design: Difficulty/resource_temporal_overlap/technician_occupation_is_half_open_so_adjacent_dispatch_is_legal
    """
    technician, donors = _one_technician_and_three_donors(pinned_api)
    first = fixtures.create_recovery(
        pinned_api,
        donors[0]["id"],
        technician["id"],
        dispatched_at="2026-08-03T06:30:00.000Z",
        planned_release_at="2026-08-03T10:00:00.000Z",
    )
    assert first["status"] == "DISPATCHED"
    assert_instant_equals(
        first["occupation_end_at"], "2026-08-03T11:00:00.000Z", "occupation_end_at"
    )
    assert fixtures.read_technician(pinned_api, technician["id"])["open_dispatch_count"] == 1

    second = fixtures.create_recovery(
        pinned_api,
        donors[1]["id"],
        technician["id"],
        dispatched_at="2026-08-03T11:00:00.000Z",
        planned_release_at="2026-08-03T13:00:00.000Z",
    )

    assert second["status"] == "DISPATCHED"
    assert_instant_equals(
        second["occupation_end_at"], "2026-08-03T14:00:00.000Z", "occupation_end_at"
    )
    assert fixtures.read_technician(pinned_api, technician["id"])["open_dispatch_count"] == 2


def test_a_dispatch_one_minute_inside_the_occupation_conflicts(pinned_api):
    """
    A third dispatch beginning at 10:59 falls inside the first occupation interval and is
    refused, leaving the technician with the two dispatches they already had.

    PRD 3.4: "The proposed dispatch conflicts with a candidate when the proposal's
    `dispatched_at` is strictly earlier than the candidate's `occupation_end_at` **and** the
    candidate's `dispatched_at` is strictly earlier than the proposal's `occupation_end_at`."

    Design: Difficulty/resource_temporal_overlap/technician_occupation_is_half_open_so_adjacent_dispatch_is_legal
    """
    technician, donors = _one_technician_and_three_donors(pinned_api)
    fixtures.create_recovery(
        pinned_api,
        donors[0]["id"],
        technician["id"],
        dispatched_at="2026-08-03T06:30:00.000Z",
        planned_release_at="2026-08-03T10:00:00.000Z",
    )
    fixtures.create_recovery(
        pinned_api,
        donors[1]["id"],
        technician["id"],
        dispatched_at="2026-08-03T11:00:00.000Z",
        planned_release_at="2026-08-03T13:00:00.000Z",
    )

    response = pinned_api.create_recovery(
        factories.recovery_payload(
            donors[2]["id"],
            technician["id"],
            "2026-08-03T10:59:00.000Z",
            "2026-08-03T13:00:00.000Z",
        ),
        COORDINATOR_HEADERS,
    )

    validate_error(response, ERR_TECHNICIAN_DISPATCH_OVERLAP, 409)
    assert fixtures.read_technician(pinned_api, technician["id"])["open_dispatch_count"] == 2
    assert fixtures.count_recoveries(pinned_api, donor_id=donors[2]["id"]) == 0
    assert fixtures.read_donor(pinned_api, donors[2]["id"])["status"] == "APPROVED_FOR_RECOVERY"


def _two_grafts_booked_for_the_same_day(pinned_api):
    """
    A surgeon already holding two reserved grafts for 8 August, a spare cornea, and two
    further requests: a third for 8 August and one for 9 August.
    """
    pair = fixtures.tissue_chain(
        pinned_api,
        donor_code="D-2846-CAP1",
        recovered_lateralities=("OD", "OS"),
        recovery_technician_name="Rosa Field",
    )
    spare = fixtures.tissue_chain(
        pinned_api,
        donor_code="D-2846-CAP2",
        recovery_technician_name="Sam Okoro",
    )
    booking = fixtures.surgeon_with_request(pinned_api, "Dr Yuki Bell", "CTR-07", "PK")
    second = fixtures.create_request(pinned_api, booking.surgeon_id)
    same_day = fixtures.create_request(pinned_api, booking.surgeon_id)
    next_day = fixtures.create_request(
        pinned_api, booking.surgeon_id, surgery_date="2026-08-09T00:00:00.000Z"
    )
    fixtures.allocate(pinned_api, pair["tissue_ids"][0], booking.request_id)
    filled = fixtures.allocate(pinned_api, pair["tissue_ids"][1], second["id"])
    assert filled["processing_fee_cents"] == 245000
    return spare["tissue_ids"][0], same_day, next_day


def test_a_third_graft_on_the_same_surgery_date_exceeds_the_day_capacity(pinned_api):
    """
    Two live allocations already sit in the 8 August bucket, so a third reservation for that
    date is refused and nothing is recorded.

    PRD 3.6: "At the moment of reservation, and again at confirmation, the surgeon must hold
    **at most one other** allocation whose `status` is `RESERVED`, `CONFIRMED` or `CONSUMED`
    and whose request's `surgery_date` falls on that same UTC date."

    Design: Difficulty/resource_temporal_overlap/surgeon_day_capacity_counts_two_grafts_per_utc_date
    """
    spare_tissue_id, same_day, _next_day = _two_grafts_booked_for_the_same_day(pinned_api)

    response = pinned_api.create_allocation(
        factories.allocation_payload(spare_tissue_id, same_day["id"]), COORDINATOR_HEADERS
    )

    validate_error(response, ERR_SURGEON_DAY_CAPACITY_EXCEEDED, 409)
    assert (
        total_count_of(
            pinned_api.list_allocations(COORDINATOR_HEADERS, request_id=same_day["id"])
        )
        == 0
    )
    assert fixtures.read_request(pinned_api, same_day["id"])["status"] == "OPEN"
    assert_dimensions(
        fixtures.read_tissue(pinned_api, spare_tissue_id), "ELIGIBLE", "IN_HOUSE"
    )


def test_the_same_tissue_is_admitted_for_the_next_calendar_date(pinned_api):
    """
    The bucket is keyed on the surgery date, so the identical cornea reserves cleanly against
    a request booked for 9 August.

    PRD 3.6: "The bucket is the UTC calendar date of the request's `surgery_date`."

    Design: Difficulty/resource_temporal_overlap/surgeon_day_capacity_counts_two_grafts_per_utc_date
    """
    spare_tissue_id, _same_day, next_day = _two_grafts_booked_for_the_same_day(pinned_api)

    allocation = fixtures.allocate(pinned_api, spare_tissue_id, next_day["id"])

    assert allocation["status"] == "RESERVED"
    assert allocation["processing_fee_cents"] == 245000
    assert_dimensions(
        fixtures.read_tissue(pinned_api, spare_tissue_id), "RESERVED", "IN_HOUSE"
    )
    assert fixtures.read_request(pinned_api, next_day["id"])["status"] == "ALLOCATED"
