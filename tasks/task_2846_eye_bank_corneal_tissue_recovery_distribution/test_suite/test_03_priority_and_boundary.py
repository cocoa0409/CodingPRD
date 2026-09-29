"""
Refusal priority between two simultaneously-failing gates, and the exact instant or count
at which an inclusive bound flips.

The priority cases pin which of two applicable refusals is reported; the boundary cases
pin the accepted value and the very next value that is refused.
"""

from test_helpers import (
    COORDINATOR_HEADERS,
    ERR_DONOR_UNDER_LOOKBACK,
    ERR_ECD_BELOW_REQUEST_MINIMUM,
    ERR_EXPIRY_BEFORE_SURGERY_DATE,
    ERR_PRESERVATION_WINDOW_EXCEEDED,
    ERR_SURGEON_NOT_CREDENTIALED,
    ERR_TISSUE_NOT_ELIGIBLE,
    MEDICAL_DIRECTOR_HEADERS,
    assert_dimensions,
    assert_instant_equals,
    factories,
    fixtures,
    make_recovery_technician_headers,
    validate_error,
)


def _donor_under_lookback(pinned_api):
    """
    A donor with one classified cornea and one still-ungraded cornea, placed under an
    operator-initiated lookback investigation.
    """
    chain = fixtures.tissue_chain(
        pinned_api,
        donor_code="D-2846-PP1",
        recovered_lateralities=("OD", "OS"),
        classify_tissues=False,
    )
    graded, ungraded = chain["tissue_ids"]
    fixtures.classify(pinned_api, graded)
    booking = fixtures.surgeon_with_request(pinned_api, "Dr Anwar Reed", "CTR-01", "PK")
    investigation = fixtures.open_lookback(pinned_api, chain["donor_id"])
    return {
        "donor_id": chain["donor_id"],
        "graded": graded,
        "ungraded": ungraded,
        "request_id": booking.request_id,
        "investigation": investigation,
    }


def test_allocating_a_lookback_quarantined_tissue_reports_the_disposition_conflict(
    pinned_api,
):
    """
    The sweep has already moved the eligible cornea to QUARANTINED, so the manual
    allocation reports the 409 disposition conflict rather than the 422 lookback refusal.

    PRD 2.10: "And because every state gate (rungs 11 to 20) precedes every business-safety
    gate (rungs 21 onward), an operation attempted from the wrong state reports the state
    conflict even when a safety rule would also have refused it."

    Design: Difficulty/priority_pair_validation_conflict/allocation_of_quarantined_lookback_tissue_returns_409_state_error
    """
    state = _donor_under_lookback(pinned_api)
    assert state["investigation"]["impacted_tissue_count"] == 2
    assert state["investigation"]["quarantined_count"] == 1
    assert_dimensions(
        fixtures.read_tissue(pinned_api, state["graded"]), "QUARANTINED", "IN_HOUSE"
    )

    response = pinned_api.create_allocation(
        factories.allocation_payload(state["graded"], state["request_id"]),
        COORDINATOR_HEADERS,
    )

    validate_error(response, ERR_TISSUE_NOT_ELIGIBLE, 409)
    assert fixtures.allocations_for_tissue(pinned_api, state["graded"]) == []
    assert fixtures.read_request(pinned_api, state["request_id"])["status"] == "OPEN"


def test_classifying_the_ungraded_sibling_reports_the_lookback_refusal(pinned_api):
    """
    The sibling was never quarantined because UNGRADED is not in the quarantinable subset,
    so its classification passes the state gate and lands on the lookback gate instead.

    PRD 2.10: "The donor's `lookback_flag` is false — otherwise `ERR_DONOR_UNDER_LOOKBACK`
    (422). Applies to four operations: tissue classification, quarantine release, manual
    allocation and the allocation run."

    Design: Difficulty/priority_pair_validation_conflict/allocation_of_quarantined_lookback_tissue_returns_409_state_error
    """
    state = _donor_under_lookback(pinned_api)
    before = fixtures.read_tissue(pinned_api, state["ungraded"])
    assert before["disposition_status"] == "UNGRADED"

    response = pinned_api.classify_tissue(
        state["ungraded"], factories.classify_payload(), MEDICAL_DIRECTOR_HEADERS
    )

    validate_error(response, ERR_DONOR_UNDER_LOOKBACK, 422)
    after = fixtures.read_tissue(pinned_api, state["ungraded"])
    assert after["disposition_status"] == "UNGRADED"
    assert after["classification"] is None
    assert after["version"] == before["version"]


def _suspended_surgeon_with_a_short_lived_tissue(pinned_api):
    """
    A therapeutic cornea expiring on 13 August, reserved against a request for surgery on
    20 August by a surgeon suspended after the request was opened.
    """
    chain = fixtures.tissue_chain(
        pinned_api,
        donor_code="D-2846-PP2",
        donor_kwargs={
            "referral_source": "MEDICAL_EXAMINER",
            "body_cooled_at": None,
            "age_years": 52,
        },
        endothelial_cell_count=2100,
    )
    tissue = chain["tissues"][0]
    booking = fixtures.surgeon_with_request(
        pinned_api,
        "Dr Lena Ost",
        "CTR-04",
        "PK",
        surgery_date="2026-08-20T00:00:00.000Z",
    )
    return chain, tissue, booking


def test_the_credential_gate_is_reported_ahead_of_the_expiry_against_surgery_date_gate(
    pinned_api,
):
    """
    Both the surgeon's suspension and the tissue's early expiry would refuse this
    reservation; the credential check sits higher on the ladder and is the one reported.

    PRD 2.10: "The receiving surgeon's `credential_status` is `ACTIVE` — otherwise
    `ERR_SURGEON_NOT_CREDENTIALED` (422). Applies to four operations: surgeon-request
    creation, manual allocation, allocation confirmation and shipment dispatch."

    Design: Difficulty/priority_pair_validation_conflict/allocation_for_suspended_surgeon_with_short_shelf_life_returns_422_credentialing
    """
    chain, tissue, booking = _suspended_surgeon_with_a_short_lived_tissue(pinned_api)
    assert chain["donor"]["recovery_window_minutes"] == 720
    assert chain["recovery"]["time_limit_band"] == "WITHIN_STANDARD"
    assert tissue["classification"] == "TRANSPLANT_THERAPEUTIC"
    assert tissue["shelf_life_hours"] == 240
    assert_instant_equals(
        tissue["expires_at"], "2026-08-13T09:00:00.000Z", "expires_at"
    )
    fixtures.set_credential_status(pinned_api, booking.surgeon_id, "SUSPENDED")

    response = pinned_api.create_allocation(
        factories.allocation_payload(tissue["id"], booking.request_id),
        COORDINATOR_HEADERS,
    )

    validate_error(response, ERR_SURGEON_NOT_CREDENTIALED, 422)
    assert_dimensions(
        fixtures.read_tissue(pinned_api, tissue["id"]), "ELIGIBLE", "IN_HOUSE"
    )
    assert fixtures.allocations_for_request(pinned_api, booking.request_id) == []
    assert fixtures.read_request(pinned_api, booking.request_id)["status"] == "OPEN"


def test_restoring_the_credential_uncovers_the_masked_expiry_refusal(pinned_api):
    """
    With the surgeon active again the reservation reaches the lower gate, which refuses it
    because the cornea expires a week before the booked surgery date.

    PRD 2.10: "The tissue's `expires_at` is at or after the request's `surgery_date` —
    otherwise `ERR_EXPIRY_BEFORE_SURGERY_DATE` (422). Applies to three operations: manual
    allocation, allocation confirmation and shipment dispatch."

    Design: Difficulty/priority_pair_validation_conflict/allocation_for_suspended_surgeon_with_short_shelf_life_returns_422_credentialing
    """
    _chain, tissue, booking = _suspended_surgeon_with_a_short_lived_tissue(pinned_api)
    fixtures.set_credential_status(pinned_api, booking.surgeon_id, "SUSPENDED")
    fixtures.set_credential_status(pinned_api, booking.surgeon_id, "ACTIVE")

    response = pinned_api.create_allocation(
        factories.allocation_payload(tissue["id"], booking.request_id),
        COORDINATOR_HEADERS,
    )

    validate_error(response, ERR_EXPIRY_BEFORE_SURGERY_DATE, 422)
    assert_dimensions(
        fixtures.read_tissue(pinned_api, tissue["id"]), "ELIGIBLE", "IN_HOUSE"
    )
    assert fixtures.allocations_for_request(pinned_api, booking.request_id) == []


def _on_site_recovery_against_an_eighteen_hundred_deadline(pinned_api, donor_code):
    """
    A promptly cooled asystole donor whose recovery deadline falls at 18:00, with the
    technician already on site.
    """
    technician = fixtures.create_technician(pinned_api, "Rosa Field", "RECOVERY_ONLY")
    donor = fixtures.create_donor(
        pinned_api,
        donor_code=donor_code,
        death_at="2026-08-03T02:00:00.000Z",
        body_cooled_at="2026-08-03T06:00:00.000Z",
        age_years=52,
    )
    assert donor["recovery_window_minutes"] == 960
    assert_instant_equals(
        donor["recovery_deadline_at"], "2026-08-03T18:00:00.000Z", "recovery_deadline_at"
    )
    fixtures.add_screening(pinned_api, donor["id"], "TATTOO_12M", "NO", "SPOUSE")
    fixtures.record_consent(pinned_api, donor["id"])
    fixtures.approve_recovery(pinned_api, donor["id"])
    recovery = fixtures.create_recovery(
        pinned_api,
        donor["id"],
        technician["id"],
        dispatched_at="2026-08-03T06:30:00.000Z",
        planned_release_at="2026-08-03T18:00:00.000Z",
    )
    fixtures.arrive(pinned_api, recovery["id"], technician["id"], "2026-08-03T07:00:00.000Z")
    return donor, technician, recovery


def test_preservation_exactly_at_the_recovery_deadline_is_accepted(pinned_api):
    """
    Preserving the cornea at the deadline instant itself completes the recovery, and the
    960 minute elapsed figure bands as EXCEEDED.

    PRD 3.3: "**The deadline is enforced here and it is enforced strictly:** a
    `preservation_at` strictly later than the donor's `recovery_deadline_at` is refused with
    `ERR_PRESERVATION_WINDOW_EXCEEDED`, while a `preservation_at` exactly equal to the
    deadline is accepted."

    PRD 3.3: "On success, `death_to_preservation_minutes` is set to the number of whole
    minutes from the donor's `death_at` to `preservation_at`, floored, and `time_limit_band`
    is banded from that figure: `WITHIN_STANDARD` when it is at most twelve hours (720
    minutes), `WITHIN_EXTENDED` when it is more than 720 but at most fifteen hours (900
    minutes), and `EXCEEDED` when it is greater still."

    Design: Difficulty/boundary_precision_check/preservation_at_equal_to_recovery_deadline_accepted_one_millisecond_later_rejected
    """
    donor, technician, recovery = _on_site_recovery_against_an_eighteen_hundred_deadline(
        pinned_api, "D-2846-BP1"
    )

    completed = fixtures.complete_recovery(
        pinned_api,
        recovery["id"],
        technician["id"],
        preservation_at="2026-08-03T18:00:00.000Z",
    )

    assert completed["status"] == "COMPLETED"
    assert completed["death_to_preservation_minutes"] == 960
    assert completed["time_limit_band"] == "EXCEEDED"
    reread = fixtures.read_donor(pinned_api, donor["id"])
    assert reread["status"] == "RECOVERED"
    assert reread["tissues_recovered_count"] == 1
    assert fixtures.count_tissues(pinned_api) == 1


def test_preservation_one_millisecond_past_the_deadline_is_refused(pinned_api):
    """
    A single millisecond beyond the deadline puts the cornea outside the window, and no
    tissue is created.

    PRD 3.3: "**The deadline is enforced here and it is enforced strictly:** a
    `preservation_at` strictly later than the donor's `recovery_deadline_at` is refused with
    `ERR_PRESERVATION_WINDOW_EXCEEDED`, while a `preservation_at` exactly equal to the
    deadline is accepted."

    Design: Difficulty/boundary_precision_check/preservation_at_equal_to_recovery_deadline_accepted_one_millisecond_later_rejected
    """
    donor, technician, recovery = _on_site_recovery_against_an_eighteen_hundred_deadline(
        pinned_api, "D-2846-BP2"
    )

    response = pinned_api.complete_recovery(
        recovery["id"],
        factories.complete_payload("2026-08-03T18:00:00.001Z"),
        make_recovery_technician_headers(technician["id"]),
    )

    validate_error(response, ERR_PRESERVATION_WINDOW_EXCEEDED, 422)
    still_open = fixtures.read_recovery(pinned_api, recovery["id"])
    assert still_open["status"] == "ON_SITE"
    assert still_open["preservation_at"] is None
    assert still_open["time_limit_band"] is None
    reread = fixtures.read_donor(pinned_api, donor["id"])
    assert reread["status"] == "APPROVED_FOR_RECOVERY"
    assert reread["tissues_recovered_count"] == 0
    assert fixtures.count_tissues(pinned_api) == 0


def _two_therapeutic_corneas_and_two_requests(pinned_api):
    """
    A bilateral donor whose two corneas both grade at 2100 cells, with one request whose
    floor is exactly 2100 and one whose floor is 2101.
    """
    chain = fixtures.tissue_chain(
        pinned_api,
        donor_code="D-2846-BP3",
        recovered_lateralities=("OD", "OS"),
        endothelial_cell_count=2100,
    )
    first, second = chain["tissues"]
    booking = fixtures.surgeon_with_request(
        pinned_api,
        "Dr Pia Sandoval",
        "CTR-05",
        "PK",
        surgery_date="2026-08-10T00:00:00.000Z",
        min_ecd=2100,
    )
    strict_request = fixtures.create_request(
        pinned_api,
        booking.surgeon_id,
        surgery_date="2026-08-11T00:00:00.000Z",
        min_ecd=2101,
    )
    return first, second, booking, strict_request


def test_a_minimum_equal_to_the_cell_count_admits_the_tissue(pinned_api):
    """
    The endothelial floor is inclusive, so a request asking for at least 2100 cells accepts
    a cornea counted at exactly 2100.

    PRD 2.10: "The tissue's recorded specular `endothelial_cell_count` is at least the
    request's `min_ecd` — otherwise `ERR_ECD_BELOW_REQUEST_MINIMUM` (422). Applies to manual
    allocation."

    Design: Difficulty/boundary_precision_check/ecd_floor_is_inclusive_so_2100_matches_2100_and_2101_is_rejected
    """
    first, _second, booking, _strict = _two_therapeutic_corneas_and_two_requests(pinned_api)
    assert first["classification"] == "TRANSPLANT_THERAPEUTIC"
    assert first["shelf_life_hours"] == 312
    assert_instant_equals(first["expires_at"], "2026-08-16T09:00:00.000Z", "expires_at")

    allocation = fixtures.allocate(pinned_api, first["id"], booking.request_id)

    assert allocation["status"] == "RESERVED"
    assert allocation["reserved_ecd_snapshot"] == 2100
    assert allocation["reserved_classification_snapshot"] == "TRANSPLANT_THERAPEUTIC"
    assert allocation["processing_fee_cents"] == 189000
    assert_dimensions(
        fixtures.read_tissue(pinned_api, first["id"]), "RESERVED", "IN_HOUSE"
    )
    assert fixtures.read_request(pinned_api, booking.request_id)["status"] == "ALLOCATED"


def test_a_minimum_one_cell_above_the_count_refuses_the_tissue(pinned_api):
    """
    Raising the floor by a single cell to 2101 puts the same 2100 cell cornea below the
    request's minimum.

    PRD 2.10: "The tissue's recorded specular `endothelial_cell_count` is at least the
    request's `min_ecd` — otherwise `ERR_ECD_BELOW_REQUEST_MINIMUM` (422). Applies to manual
    allocation."

    Design: Difficulty/boundary_precision_check/ecd_floor_is_inclusive_so_2100_matches_2100_and_2101_is_rejected
    """
    _first, second, _booking, strict = _two_therapeutic_corneas_and_two_requests(pinned_api)

    response = pinned_api.create_allocation(
        factories.allocation_payload(second["id"], strict["id"]), COORDINATOR_HEADERS
    )

    validate_error(response, ERR_ECD_BELOW_REQUEST_MINIMUM, 422)
    assert_dimensions(
        fixtures.read_tissue(pinned_api, second["id"]), "ELIGIBLE", "IN_HOUSE"
    )
    assert fixtures.allocations_for_request(pinned_api, strict["id"]) == []
    assert fixtures.read_request(pinned_api, strict["id"])["status"] == "OPEN"
