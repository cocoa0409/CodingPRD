"""
The endpoint surface itself: a CRUD triple with its nested collection, a status action that
is a real gate, the batch matcher, and a two-dimension terminal action.

Each case exercises one endpoint family and then reads back through a second endpoint, so a
write that only pretends to have happened is caught.
"""

from test_helpers import (
    COORDINATOR_HEADERS,
    ERR_TECHNICIAN_NOT_CERTIFIED,
    MEDICAL_DIRECTOR_HEADERS,
    T_NOW,
    assert_common_fields,
    assert_dimensions,
    assert_instant_equals,
    assert_ledger,
    factories,
    fixtures,
    get_success_data,
    make_surgeon_headers,
    validate_error,
    validate_success,
)


def test_surgeon_create_read_and_nested_request_listing_are_ordered_by_priority_score(
    pinned_api,
):
    """
    Registration defaults the credential and the whole money ledger, the read echoes them, and
    the nested request collection comes back by descending priority score rather than in
    insertion order.

    PRD 3.6: "A surgeon is registered with `full_name` (1 to 80 characters), `center_code`, the
    transplant centre code (1 to 16 characters), and `specialty`, one of `PK`, `DSAEK`, `DMEK`
    or `THERAPEUTIC`."

    PRD 3.6: "Registration sets `credential_status` to `ACTIVE` and the four maintained
    counters `gross_billed_cents`, `credited_fee_cents`, `outstanding_fee_cents` and
    `substantiated_reaction_count` all to 0."

    PRD 3.6: "In step one, an urgency weight of 30 is credited for `URGENT` and 10 for
    `ROUTINE`; separately, the number of whole days from the current logical instant to
    `surgery_date` is computed by flooring, and this figure may be negative for a request whose
    surgery date has already passed."

    PRD 3.6: "Surgery-proximity points are then awarded from that day count: 40 points when it
    is 2 or fewer, 25 points when it is between 3 and 7 inclusive, 10 points when it is between
    8 and 21 inclusive, and 0 points otherwise."

    PRD 3.6: "In step two, `priority_tier` is selected **from `base_score` alone**: `PLATINUM`
    when `base_score` is 60 or more, `GOLD` when it is at least 40 but less than 60, and
    `STANDARD` otherwise."

    PRD 3.6: "In step three a tier bonus of 15 for `PLATINUM`, 8 for `GOLD` and 0 for
    `STANDARD` is added to `base_score` to produce `priority_score`."

    PRD 2.3: "The following listings override that default, and their ordering is part of the
    contract: the donor list, the shipment list and the tissue-evaluation-by-technician list
    are returned newest first; the tissue list is ordered by descending `preserved_at`; the
    recovery list by descending `dispatched_at`; the serology-panel list by descending
    `drawn_at` (invalidated panels included); the tissue-evaluation list for one tissue and the
    evaluation list for one technician by descending `performed_at`; the allocation list by
    descending `allocated_at`; the adverse-reaction-report list by descending `reported_at`;
    the lookback-investigation list by descending `opened_at`; the temperature-reading list by
    ascending `recorded_at`; and both surgeon-request listings by descending `priority_score`
    with ascending `created_at` as the tie-break."

    Design: Corner/endpoints/surgeon_create_read_and_nested_request_listing_are_ordered_by_priority_score
    """
    created = validate_success(
        pinned_api.create_surgeon(
            factories.surgeon_payload("Dr Imani Rho", "CTR-01", "PK"),
            COORDINATOR_HEADERS,
        ),
        201,
    )
    assert created["credential_status"] == "ACTIVE"
    assert_ledger(created, 0, 0, 0, "at registration")
    assert created["substantiated_reaction_count"] == 0
    assert_common_fields(created, 1, "surgeon")

    reread = get_success_data(
        pinned_api.get_surgeon(created["id"], MEDICAL_DIRECTOR_HEADERS)
    )
    assert reread["full_name"] == "Dr Imani Rho"
    assert reread["center_code"] == "CTR-01"
    assert reread["specialty"] == "PK"
    assert reread["credential_status"] == "ACTIVE"
    assert reread["version"] == 1

    routine = fixtures.create_request(
        pinned_api, created["id"], surgery_date="2026-08-08T00:00:00.000Z"
    )
    assert routine["base_score"] == 35
    assert routine["priority_tier"] == "STANDARD"
    assert routine["priority_score"] == 35

    urgent = fixtures.create_request(
        pinned_api,
        created["id"],
        procedure_type="DMEK",
        surgery_date="2026-08-05T00:00:00.000Z",
        laterality_preference="OD",
        urgency="URGENT",
    )
    assert urgent["base_score"] == 70
    assert urgent["priority_tier"] == "PLATINUM"
    assert urgent["priority_score"] == 85

    nested = get_success_data(
        pinned_api.list_surgeon_requests_nested(
            created["id"], make_surgeon_headers(created["id"])
        )
    )

    assert [row["id"] for row in nested] == [urgent["id"], routine["id"]]
    assert [row["priority_score"] for row in nested] == [85, 35]


def test_deactivating_a_technician_makes_the_next_dispatch_fail_with_not_certified(
    pinned_api,
):
    """
    The roster-availability action is a gate rather than a label: with the donor fully released
    for recovery, an INACTIVE technician still cannot be dispatched and no recovery row is
    written.

    PRD 3.3: "Every technician is created `ACTIVE` with `open_dispatch_count` 0."

    PRD 3.3: "The `status` field, either `ACTIVE` or `INACTIVE`, is toggled by the coordinator
    through the roster-availability operation, which sets the supplied value and increments the
    technician's `version`; an `INACTIVE` technician can neither be dispatched to a recovery
    nor record an evaluation, and both refusals use `ERR_TECHNICIAN_NOT_CERTIFIED`."

    PRD 2.10: "The acting technician has `status` `ACTIVE`, a `certification_expires_at`
    strictly later than the logical clock, and — when grading tissue — `certification_level`
    `RECOVERY_AND_EVAL` — otherwise `ERR_TECHNICIAN_NOT_CERTIFIED` (422). Applies to recovery
    dispatch and tissue-evaluation creation."

    Design: Corner/endpoints/deactivating_a_technician_makes_the_next_dispatch_fail_with_not_certified
    """
    technician = fixtures.create_technician(pinned_api, "Rosa Field", "RECOVERY_ONLY")
    assert technician["status"] == "ACTIVE"
    assert technician["version"] == 1
    donor = fixtures.approved_donor(
        pinned_api,
        donor_code="D-2846-E02",
        body_cooled_at="2026-08-03T03:00:00.000Z",
        age_years=52,
    )
    assert donor["status"] == "APPROVED_FOR_RECOVERY"
    deactivated = fixtures.set_technician_status(
        pinned_api, technician["id"], "INACTIVE"
    )
    assert deactivated["status"] == "INACTIVE"
    assert deactivated["version"] == 2

    response = pinned_api.create_recovery(
        factories.recovery_payload(
            donor["id"],
            technician["id"],
            "2026-08-03T06:30:00.000Z",
            "2026-08-03T10:00:00.000Z",
        ),
        COORDINATOR_HEADERS,
    )

    validate_error(response, ERR_TECHNICIAN_NOT_CERTIFIED, 422)
    assert fixtures.count_recoveries(pinned_api, donor_id=donor["id"]) == 0
    after = fixtures.read_technician(pinned_api, technician["id"])
    assert after["open_dispatch_count"] == 0
    assert after["version"] == 2


def test_the_allocation_run_matches_the_earliest_expiring_of_two_compatible_tissues(
    pinned_api,
):
    """
    Both corneas clear every match filter for one therapeutic request, so the run's own
    tie-break decides: the soonest-expiring, weaker cornea is spent and the optical one is
    left on the shelf.

    PRD 3.5: "**Endothelial points** reward cell density above a baseline of 1800 cells per
    square millimetre: subtract 1800 from `endothelial_cell_count`, divide by 50 and take the
    floor, then raise the result to 0 if it went negative and cap it at 40 — the clamps are
    applied in exactly that order, so a count of 1799 earns zero rather than a negative
    contribution and a count of 4000 earns 40 rather than 44."

    PRD 3.5: "**Clarity points** are 25 minus five times `stromal_clarity_grade`, so a
    perfectly clear stroma earns 25 and a grade of 4 earns 5. **Epithelium points** are 15
    minus four times `epithelium_defect_grade`. **Folds points** are 10 minus three times
    `dm_folds_grade`. **Guttata points** are 10 minus five times `guttata_grade`, so a guttata
    grade of 2 earns 0. Finally an **age adjustment** is applied: minus 8 points when the
    donor's `age_years` is 71 or more, zero when `age_years` is 46 or more but less than 71,
    and plus 5 points for a donor younger than 46. The five component figures and the age
    adjustment are added together, and the sum is then raised to at least 0 and lowered to at
    most 100."

    PRD 3.5: "Otherwise, when `tissue_quality_score` is 70 or above **and** the specular
    `endothelial_cell_count` is 2000 or above **and** the recovery's `time_limit_band` is
    `WITHIN_STANDARD`, the classification is `TRANSPLANT_OPTICAL`."

    PRD 3.5: "Otherwise, when `tissue_quality_score` is 45 or above **and** the specular
    `endothelial_cell_count` is 1800 or above, the classification is `TRANSPLANT_THERAPEUTIC`."

    PRD 3.5: "`TRANSPLANT_OPTICAL` and `TRANSPLANT_THERAPEUTIC` both move
    `disposition_status` from `UNGRADED` to `ELIGIBLE`, making the tissue allocatable."

    PRD 3.5: "The base is again the medium's allowance — 336 hours for `OPTISOL_GS`, 264 hours
    for `LIFE4C` — and the same 48-hour band penalty applies when the recovery's
    `time_limit_band` is `WITHIN_EXTENDED`."

    PRD 3.5: "A **low-endothelium penalty of 24 hours** is charged when the tissue's
    `RECORDED` `SPECULAR` evaluation reports an `endothelial_cell_count` below 2200."

    PRD 3.5: "The base less all three applicable penalties is then raised to a floor of 24
    hours, stored in `shelf_life_hours`, and `expires_at` is recomputed as `preserved_at`
    advanced by that many whole hours."

    PRD 3.6: "A tissue classified `TRANSPLANT_OPTICAL` may be matched to a request whose
    `procedure_type` is `PK`, `DSAEK`, `DMEK` or `THERAPEUTIC` — optical-grade tissue is
    acceptable for every procedure. A tissue classified `TRANSPLANT_THERAPEUTIC` may be
    matched only to a `THERAPEUTIC` or a `PK` request; the lamellar procedures `DSAEK` and
    `DMEK` demand optical-grade tissue and a therapeutic tissue offered for either is a
    mismatch."

    PRD 3.6: "**Step four applies the per-pair match filter**, which is the same compatibility
    set the manual path enforces: the specular `endothelial_cell_count` at least `min_ecd`; the
    donor's `age_years` at most `max_donor_age_years`; the `laterality_preference` either `ANY`
    or equal to the tissue's `laterality`; the request's `procedure_type` among those permitted
    for the tissue's `classification`; and the tissue's `expires_at` not earlier than the
    request's `surgery_date`. **Step five chooses among the matching tissues** by `expires_at`
    ascending — the soonest-expiring acceptable tissue is spent first, which is the whole point
    of an expiry-driven selector — then by the specular `endothelial_cell_count` ascending, so
    that the weakest acceptable tissue goes out and the best tissue is preserved for a later
    request, then by the tissue's `created_at` ascending."

    PRD 3.6: "Each match creates an allocation exactly as the manual path would, but with
    `source` `RUN`, including the pinned snapshots and the processing fee; each matched tissue
    moves `ELIGIBLE → RESERVED`, each matched request moves `OPEN → ALLOCATED`, and the
    `version` of every tissue and request the run touched is incremented by 1."

    PRD 3.6: "The run returns an object rather than a resource, carrying `run_at` set to the
    current logical instant, `allocations_created` as the number of matches, `allocation_ids`
    listing the created allocations in the order they were created, `unmatched_request_ids` and
    `expired_request_ids`."

    PRD 3.6: "On success the allocation is created with `allocated_at` set to the current
    logical instant, `status` `RESERVED` and `source` `MANUAL`; `reserved_ecd_snapshot` is
    pinned from the `endothelial_cell_count` of the tissue's `RECORDED` `SPECULAR` evaluation
    and `reserved_classification_snapshot` is pinned from the tissue's `classification`, which
    at this point is necessarily `TRANSPLANT_OPTICAL` or `TRANSPLANT_THERAPEUTIC`."

    PRD 3.6: "The base is 245000 cents for `TRANSPLANT_OPTICAL` and 189000 cents for
    `TRANSPLANT_THERAPEUTIC`."

    PRD 3.6: "`expiry_margin_hours` records the number of whole hours from the request's
    `surgery_date` to the tissue's `expires_at`, floored, and may legitimately be 0 when the
    tissue expires within the hour after surgery."

    Design: Corner/endpoints/the_allocation_run_matches_the_earliest_expiring_of_two_compatible_tissues
    """
    recovery_technician = fixtures.recovery_technician(pinned_api, "Rosa Field")
    evaluator = fixtures.evaluation_technician(pinned_api, "Nils Abadi")
    donor = fixtures.approved_donor(
        pinned_api,
        donor_code="D-2846-E03",
        body_cooled_at="2026-08-03T03:00:00.000Z",
        age_years=52,
    )
    chain = fixtures.recovered_tissues(
        pinned_api,
        donor["id"],
        recovery_technician["id"],
        recovered_lateralities=("OD", "OS"),
    )
    assert chain.recovery["time_limit_band"] == "WITHIN_STANDARD"
    od, os_tissue = chain.tissues
    assert od["laterality"] == "OD"
    assert os_tissue["laterality"] == "OS"

    fixtures.graded_tissue(
        pinned_api, od["id"], evaluator["id"], endothelial_cell_count=3100
    )
    optical = fixtures.classify(pinned_api, od["id"])
    assert optical["tissue_quality_score"] == 86
    assert optical["classification"] == "TRANSPLANT_OPTICAL"
    assert optical["disposition_status"] == "ELIGIBLE"
    assert_instant_equals(optical["expires_at"], "2026-08-17T09:00:00.000Z", "OD expires_at")

    fixtures.graded_tissue(
        pinned_api, os_tissue["id"], evaluator["id"], endothelial_cell_count=2100
    )
    therapeutic = fixtures.classify(pinned_api, os_tissue["id"])
    assert therapeutic["tissue_quality_score"] == 66
    assert therapeutic["classification"] == "TRANSPLANT_THERAPEUTIC"
    assert therapeutic["disposition_status"] == "ELIGIBLE"
    assert therapeutic["shelf_life_hours"] == 312
    assert_instant_equals(
        therapeutic["expires_at"], "2026-08-16T09:00:00.000Z", "OS expires_at"
    )

    surgeon = fixtures.create_surgeon(pinned_api, "Dr Imani Rho", "CTR-01", "PK")
    request = fixtures.create_request(
        pinned_api,
        surgeon["id"],
        procedure_type="THERAPEUTIC",
        surgery_date="2026-08-08T00:00:00.000Z",
    )
    assert request["priority_score"] == 35

    run = fixtures.run_allocation(pinned_api)

    assert_instant_equals(run["run_at"], T_NOW, "run_at")
    assert run["allocations_created"] == 1
    assert len(run["allocation_ids"]) == 1
    assert run["unmatched_request_ids"] == []
    assert run["expired_request_ids"] == []
    allocations = fixtures.allocations_for_request(pinned_api, request["id"])
    assert len(allocations) == 1
    allocation = allocations[0]
    assert allocation["tissue_id"] == os_tissue["id"]
    assert allocation["status"] == "RESERVED"
    assert allocation["source"] == "RUN"
    assert allocation["reserved_ecd_snapshot"] == 2100
    assert allocation["reserved_classification_snapshot"] == "TRANSPLANT_THERAPEUTIC"
    assert allocation["processing_fee_cents"] == 189000
    assert allocation["expiry_margin_hours"] == 201
    assert_dimensions(
        fixtures.read_tissue(pinned_api, od["id"]), "ELIGIBLE", "IN_HOUSE", "unmatched OD"
    )
    assert fixtures.read_request(pinned_api, request["id"])["status"] == "ALLOCATED"


def test_discard_is_allowed_from_quarantine_and_destroys_the_custody_dimension(pinned_api):
    """
    Disposal is legal straight out of quarantine, moves both dimensions in one request, records
    the method and leaves the quarantine reason on the row rather than clearing it.

    PRD 3.9: "It records the supplied `quarantine_reason` and moves the tissue's
    `disposition_status` to `QUARANTINED` from either `ELIGIBLE` or `RESERVED`;
    `custody_status` is not touched."

    PRD 3.9: "The acting director or coordinator supplies `disposal_method`, one of
    `INCINERATION`, `AUTOCLAVE` or `RESEARCH_TRANSFER`, and the tissue moves to `DISCARDED` on
    dimension A and to `DESTROYED` on dimension B in the same request. Disposal is legal from
    `ELIGIBLE`, `QUARANTINED`, `RELEASED_FOR_RESEARCH` and `RELEASED_FOR_TRAINING`, and never
    from `UNGRADED`, `RESERVED`, `ISSUED`, `IMPLANTED` or `DISCARDED`."

    PRD 2.5: "Most resources additionally carry `updated_at` — the logical-clock instant of the
    most recent mutation, initially equal to `created_at` — and `version`, an integer that
    starts at 1 on creation and increases by exactly 1 on every mutation of that row."

    Design: Corner/endpoints/discard_is_allowed_from_quarantine_and_destroys_the_custody_dimension
    """
    chain = fixtures.tissue_chain(
        pinned_api,
        donor_code="D-2846-E04",
        donor_kwargs={"body_cooled_at": "2026-08-03T03:00:00.000Z", "age_years": 52},
        evaluation_technician_name="Nils Abadi",
    )
    tissue = chain["tissues"][0]
    assert tissue["disposition_status"] == "ELIGIBLE"
    assert tissue["version"] == 4

    quarantined = fixtures.quarantine(
        pinned_api, tissue["id"], "Donor chart discrepancy pending review"
    )

    assert_dimensions(quarantined, "QUARANTINED", "IN_HOUSE", "after quarantine")
    assert quarantined["quarantine_reason"] == "Donor chart discrepancy pending review"
    assert quarantined["version"] == 5

    discarded = fixtures.discard(pinned_api, tissue["id"], "AUTOCLAVE")

    assert_dimensions(discarded, "DISCARDED", "DESTROYED", "after disposal")
    assert discarded["disposal_method"] == "AUTOCLAVE"
    assert discarded["quarantine_reason"] == "Donor chart discrepancy pending review"
    assert discarded["version"] == 6
