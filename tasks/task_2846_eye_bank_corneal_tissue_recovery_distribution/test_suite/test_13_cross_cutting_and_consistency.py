"""
The cross-cutting layers: the two optimistic-concurrency handshakes, the all-or-nothing
allocation run, and the promise that a write response is already the next read.

Each case pairs a rejected write with a read-back proving nothing was persisted, or pairs a
write response with an immediate independent GET of the same row.
"""

from test_helpers import (
    COORDINATOR_HEADERS,
    ERR_NO_ELIGIBLE_TISSUE,
    ERR_STALE_DONOR_VERSION,
    ERR_STALE_TISSUE_VERSION,
    LAB_TECHNICIAN_HEADERS,
    MEDICAL_DIRECTOR_HEADERS,
    T_NOW,
    assert_instant_equals,
    assert_ledger,
    factories,
    fixtures,
    get_success_data,
    make_evaluation_technician_headers,
    total_count_of,
    validate_error,
)


def test_a_stale_expected_tissue_version_on_the_second_evaluation_returns_412(pinned_api):
    """
    The slit-lamp write moves the tissue's version, so the specular write that still echoes the
    version read before it is refused, and only the handle returned by the first write is
    accepted.

    PRD 2.6: "Recording a tissue evaluation requires `expected_tissue_version` as a
    non-optional field of the request body, carrying the client's last observed `version` of the
    target `CorneaTissue`. A new evaluation of a given `method` legitimately supersedes the
    prior recorded evaluation of that same method, so a write derived from a stale read would
    discard grading the client never saw. If `expected_tissue_version` does not equal the
    tissue's current `version`, the write is rejected with `ERR_STALE_TISSUE_VERSION` (HTTP 412)
    and nothing is persisted. On success, the created evaluation's `tissue_version_after` records
    the tissue's `version` once the write's cascade has settled — that value is the handle the
    client must echo on its next evaluation write for the same tissue."

    PRD 2.10: "`expected_tissue_version` equals the tissue's current `version` — otherwise
    `ERR_STALE_TISSUE_VERSION` (412). Applies to tissue-evaluation creation."

    PRD 3.4: "When an evaluation is recorded, it is created with `status` `RECORDED`, and **any
    earlier evaluation of the same tissue with the same `method`** moves to `SUPERSEDED`;
    evaluations of the other method are untouched."

    PRD 3.4: "Each write increments the tissue's `version` by 1 and stores that post-write value
    in the new evaluation's `tissue_version_after`, which is the handle the client must echo as
    `expected_tissue_version` on its next evaluation of the same tissue."

    Design: Corner/cross_cutting_complexity_layers/a_stale_expected_tissue_version_on_the_second_evaluation_returns_412
    """
    recovery_technician = fixtures.recovery_technician(pinned_api, "Rosa Field")
    evaluator = fixtures.evaluation_technician(pinned_api, "Nils Abadi")
    donor = fixtures.approved_donor(pinned_api, donor_code="D-2846-C01")
    chain = fixtures.recovered_tissues(
        pinned_api, donor["id"], recovery_technician["id"]
    )
    tissue = chain.tissues[0]
    first_seen_version = tissue["version"]

    slit = fixtures.record_slit_lamp(
        pinned_api,
        tissue["id"],
        evaluator["id"],
        performed_at="2026-08-03T09:30:00.000Z",
        expected_tissue_version=first_seen_version,
    )
    assert slit["status"] == "RECORDED"
    assert slit["tissue_version_after"] == first_seen_version + 1

    response = pinned_api.create_tissue_evaluation(
        tissue["id"],
        factories.specular_payload(
            evaluator["id"],
            "2026-08-03T09:40:00.000Z",
            first_seen_version,
            0,
            3100,
        ),
        make_evaluation_technician_headers(evaluator["id"]),
    )

    validate_error(response, ERR_STALE_TISSUE_VERSION, 412)
    after_rejection = fixtures.read_tissue(pinned_api, tissue["id"])
    assert after_rejection["version"] == first_seen_version + 1

    retry = fixtures.record_specular(
        pinned_api,
        tissue["id"],
        evaluator["id"],
        performed_at="2026-08-03T09:45:00.000Z",
        expected_tissue_version=slit["tissue_version_after"],
    )

    assert retry["status"] == "RECORDED"
    assert retry["tissue_version_after"] == first_seen_version + 2
    rows = get_success_data(
        pinned_api.list_tissue_evaluations(
            tissue["id"], make_evaluation_technician_headers(evaluator["id"])
        )
    )
    assert len(rows) == 2
    assert {row["method"] for row in rows} == {"SLIT_LAMP", "SPECULAR"}
    assert [row["status"] for row in rows] == ["RECORDED", "RECORDED"]


def test_a_stale_expected_donor_version_on_the_second_serology_panel_returns_412(pinned_api):
    """
    The donor's version has moved three times by the time the first panel is drawn, so a second
    draw echoing the version captured at consent is refused before it can invalidate a panel the
    lab never saw, and the retry carrying the first panel's handle supersedes it cleanly.

    PRD 3.1: "A newly registered donor is created with `status` `REFERRED`, `consent_type` and
    `consent_scope` both `NONE`, `authorizing_party_name` and `consent_obtained_at` both null,
    `serology_status` `PENDING`, `screening_risk_score` 0, `screening_risk_variant`
    `INTERVIEW_ONLY`, `deferral_reason` null, `lookback_flag` false, `tissues_recovered_count` 0
    and `version` 1."

    PRD 3.1: "The **first** screening record for a donor advances that donor from `REFERRED` to
    `SCREENING`; second and later records leave `status` untouched but still trigger a full
    recomputation of the risk score."

    PRD 2.5: "Most resources additionally carry `updated_at` — the logical-clock instant of the
    most recent mutation, initially equal to `created_at` — and `version`, an integer that starts
    at 1 on creation and increases by exactly 1 on every mutation of that row."

    PRD 3.2: "On success the four consent fields are written, `consent_obtained_at` is stamped
    with the current logical instant, and the donor advances `SCREENING → CONSENT_OBTAINED`."

    PRD 2.6: "Drawing a serology panel requires `expected_donor_version` as a non-optional field
    of the request body, carrying the client's last observed `version` of the target `Donor`. A
    newly created panel invalidates every earlier panel of that donor and can reset the donor's
    `serology_status`, so a write derived from a stale read would discard a laboratory result the
    client never saw. If `expected_donor_version` does not equal the donor's current `version`,
    the write is rejected with `ERR_STALE_DONOR_VERSION` (HTTP 412) and nothing is persisted. On
    success, the created panel's `donor_version_after` records the donor's `version` once the
    creation cascade has settled, and is the handle to echo on the next serology write for that
    donor."

    PRD 2.10: "`expected_donor_version` equals the donor's current `version` — otherwise
    `ERR_STALE_DONOR_VERSION` (412). Applies to serology-panel creation."

    PRD 3.2: "The new panel is created in `DRAWN` with `hiv_result`, `hbv_result`, `hcv_result`,
    `syphilis_result`, `overall_result`, `resulted_at` and `superseded_at` all null. Creating it
    is destructive to the donor's serologic history in a controlled way: **every** earlier panel
    of the same donor, whether it was still `DRAWN` or already `RESULTED`, moves to `INVALIDATED`
    with `superseded_at` stamped at the current logical instant and its own `version`
    incremented. Because no resulted, non-invalidated panel then remains, the donor's
    `serology_status` reverts to `PENDING`, `screening_risk_variant` reverts to `INTERVIEW_ONLY`,
    and `screening_risk_score` is recomputed under that variant — an `UNKNOWN`-heavy donor's
    score can therefore fall when a fresh specimen is drawn. The donor's `version` is
    incremented, and the new panel's `donor_version_after` captures the donor's `version` once
    that cascade has settled."

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

    Design: Corner/cross_cutting_complexity_layers/a_stale_expected_donor_version_on_the_second_serology_panel_returns_412
    """
    donor = fixtures.create_donor(pinned_api, donor_code="D-2846-C02")
    assert donor["status"] == "REFERRED"
    assert donor["version"] == 1
    fixtures.add_screening(pinned_api, donor["id"], "TATTOO_12M", "NO", "SPOUSE")
    consented = fixtures.record_consent(pinned_api, donor["id"])
    assert consented["status"] == "CONSENT_OBTAINED"
    assert consented["version"] == 3

    first = fixtures.draw_panel(
        pinned_api,
        donor["id"],
        expected_donor_version=consented["version"],
        drawn_at="2026-08-03T04:00:00.000Z",
    )
    assert first["status"] == "DRAWN"
    assert first["donor_version_after"] == 4

    response = pinned_api.create_serology_panel(
        donor["id"],
        factories.panel_payload(
            consented["version"],
            specimen_type="PRE_MORTEM",
            drawn_at="2026-08-03T05:00:00.000Z",
            hemodilution_pct=0.00,
        ),
        LAB_TECHNICIAN_HEADERS,
    )

    validate_error(response, ERR_STALE_DONOR_VERSION, 412)
    surviving = get_success_data(
        pinned_api.list_serology_panels(donor["id"], LAB_TECHNICIAN_HEADERS)
    )
    assert len(surviving) == 1
    assert surviving[0]["status"] == "DRAWN"
    assert surviving[0]["superseded_at"] is None
    assert fixtures.read_donor(pinned_api, donor["id"])["version"] == 4

    second = fixtures.draw_panel(
        pinned_api,
        donor["id"],
        expected_donor_version=first["donor_version_after"],
        specimen_type="PRE_MORTEM",
        drawn_at="2026-08-03T05:00:00.000Z",
    )

    assert second["status"] == "DRAWN"
    assert second["donor_version_after"] == 5
    panels = get_success_data(
        pinned_api.list_serology_panels(donor["id"], LAB_TECHNICIAN_HEADERS)
    )
    assert [row["id"] for row in panels] == [second["id"], first["id"]]
    assert [row["status"] for row in panels] == ["DRAWN", "INVALIDATED"]
    assert_instant_equals(panels[1]["superseded_at"], T_NOW, "superseded_at")
    final = fixtures.read_donor(pinned_api, donor["id"])
    assert final["version"] == 5
    assert final["serology_status"] == "PENDING"
    assert final["screening_risk_variant"] == "INTERVIEW_ONLY"


def test_an_allocation_run_over_an_empty_eligible_pool_rejects_and_rolls_back_the_expiry_sweep(
    pinned_api,
):
    """
    The only cornea in the bank was never classified, so no request can match; the run is refused
    and even the step-zero sweep that would have expired the overdue request is rolled back.

    PRD 3.3: "Each tissue copies `recovery_id` from the completing recovery, `donor_id` from that
    recovery's donor, `laterality` from the list member, `preservation_medium` and `preserved_at`
    from the completion, and is created with `disposition_status` `UNGRADED`, `custody_status`
    `IN_HOUSE`, `tissue_quality_score` and `classification` null, `issue_count` 0,
    `reissue_generation` 0, `quarantine_reason` and `disposal_method` null, and
    `shelf_life_variant` `PROVISIONAL_AT_RECOVERY`."

    PRD 2.4: "Setting the clock mutates no entity and recomputes no derived field — a donor whose
    recovery deadline has just passed is not retroactively rewritten; the newly current instant
    simply changes the outcome of the next comparison."

    PRD 3.6: "**Step zero is an expiry sweep:** every request whose `status` is `OPEN` and whose
    `surgery_date` is at or before the current logical instant moves `OPEN → EXPIRED`, and its
    identifier is reported in `expired_request_ids`. The sweep runs before any matching, so a
    request whose surgery date has passed can never be matched."

    PRD 3.6: "**Step three recomputes the tissue candidate pool before each request is served**,
    admitting a tissue only when its `disposition_status` is `ELIGIBLE`, its `custody_status` is
    `IN_HOUSE` or `RETURNED_TO_BANK`, its `classification` is `TRANSPLANT_OPTICAL` or
    `TRANSPLANT_THERAPEUTIC`, its `reissue_generation` is at most 1, its `expires_at` is strictly
    later than the current logical instant, its donor's `lookback_flag` is false, and it has not
    already been reserved earlier in this same run."

    PRD 3.6: "**Step six defines the fallbacks:** a request whose step-four result is empty stays
    `OPEN` and its identifier joins `unmatched_request_ids`; and when **every** request in the
    candidate set ends with an empty result — including the degenerate cases where the request set
    or the tissue pool is itself empty — the entire run is refused with `ERR_NO_ELIGIBLE_TISSUE`
    and **no state change of any kind is persisted, not even the step-zero expiry sweep**."

    PRD 2.10: "The allocation run produced at least one match — otherwise
    `ERR_NO_ELIGIBLE_TISSUE` (422)."

    Design: Corner/cross_cutting_complexity_layers/an_allocation_run_over_an_empty_eligible_pool_rejects_and_rolls_back_the_expiry_sweep
    """
    recovery_technician = fixtures.recovery_technician(pinned_api, "Rosa Field")
    donor = fixtures.approved_donor(pinned_api, donor_code="D-2846-C05")
    chain = fixtures.recovered_tissues(
        pinned_api, donor["id"], recovery_technician["id"]
    )
    tissue = chain.tissues[0]
    assert tissue["disposition_status"] == "UNGRADED"
    assert tissue["custody_status"] == "IN_HOUSE"
    assert tissue["classification"] is None

    surgeon = fixtures.create_surgeon(pinned_api, "Dr Imani Rho", "CTR-01", "PK")
    overdue = fixtures.create_request(
        pinned_api, surgeon["id"], surgery_date="2026-08-08T00:00:00.000Z"
    )
    assert overdue["status"] == "OPEN"
    assert overdue["version"] == 1
    fixtures.set_clock(pinned_api, "2026-08-09T00:00:00.000Z")
    upcoming = fixtures.create_request(
        pinned_api, surgeon["id"], surgery_date="2026-08-20T00:00:00.000Z"
    )
    assert upcoming["status"] == "OPEN"
    assert upcoming["version"] == 1

    response = pinned_api.create_allocation_run({}, COORDINATOR_HEADERS)

    validate_error(response, ERR_NO_ELIGIBLE_TISSUE, 422)
    overdue_after = fixtures.read_request(pinned_api, overdue["id"])
    assert overdue_after["status"] == "OPEN"
    assert overdue_after["version"] == 1
    upcoming_after = fixtures.read_request(pinned_api, upcoming["id"])
    assert upcoming_after["status"] == "OPEN"
    assert upcoming_after["version"] == 1
    assert total_count_of(pinned_api.list_allocations(COORDINATOR_HEADERS)) == 0
    assert (
        fixtures.read_tissue(pinned_api, tissue["id"])["disposition_status"]
        == "UNGRADED"
    )


def test_every_write_response_already_shows_what_the_next_independent_read_returns(pinned_api):
    """
    Three writes with computed side effects — consent re-deriving the risk score, classification
    deriving the grade and the final expiry, and confirmation moving money into another aggregate
    entirely — are each followed by an independent read that already agrees field for field.

    PRD 2.7: "Cascades in this system are **immediate and complete**: there is no deferred
    settlement and no background reconciliation."

    PRD 2.5: "Most resources additionally carry `updated_at` — the logical-clock instant of the
    most recent mutation, initially equal to `created_at` — and `version`, an integer that starts
    at 1 on creation and increases by exactly 1 on every mutation of that row."

    PRD 3.1: "The weights encode the bank's clinical priorities: a family history of
    Creutzfeldt–Jakob disease (`CJD_FAMILY`) is worth 60 points, unexplained neurological death
    (`UNEXPLAINED_NEURO`) 50, intravenous drug use (`IV_DRUG_USE`) 40, HIV risk behaviour
    (`HIV_RISK`) 35, a hepatitis B or C history (`HEP_B_C_HISTORY`) 30, sepsis (`SEPSIS`) 25,
    incarceration within the last twelve months (`INCARCERATION_12M`) 15 and a tattoo within the
    last twelve months (`TATTOO_12M`) 10."

    PRD 3.1: "While the donor's `serology_status` is still `PENDING` — that is, while no resulted,
    non-invalidated panel exists — the variant is `INTERVIEW_ONLY` and `screening_risk_score` is
    the `YES` total alone: the historian's uncertainty is deliberately not charged against the
    donor."

    PRD 3.1: "Whichever variant applies, `weight_applied` on every one of the donor's rows is
    rewritten to the weight that row actually contributed — the question's weight for a `YES` row,
    zero for a `NO` row, and zero for an `UNKNOWN` row whenever the predicate fails."

    PRD 3.2: "On success the four consent fields are written, `consent_obtained_at` is stamped
    with the current logical instant, and the donor advances `SCREENING → CONSENT_OBTAINED`."

    PRD 3.5: "**Endothelial points** reward cell density above a baseline of 1800 cells per
    square millimetre: subtract 1800 from `endothelial_cell_count`, divide by 50 and take the
    floor, then raise the result to 0 if it went negative and cap it at 40 — the clamps are
    applied in exactly that order, so a count of 1799 earns zero rather than a negative
    contribution and a count of 4000 earns 40 rather than 44."

    PRD 3.5: "**Clarity points** are 25 minus five times `stromal_clarity_grade`, so a perfectly
    clear stroma earns 25 and a grade of 4 earns 5. **Epithelium points** are 15 minus four times
    `epithelium_defect_grade`. **Folds points** are 10 minus three times `dm_folds_grade`.
    **Guttata points** are 10 minus five times `guttata_grade`, so a guttata grade of 2 earns 0.
    Finally an **age adjustment** is applied: minus 8 points when the donor's `age_years` is 71 or
    more, zero when `age_years` is 46 or more but less than 71, and plus 5 points for a donor
    younger than 46. The five component figures and the age adjustment are added together, and the
    sum is then raised to at least 0 and lowered to at most 100."

    PRD 3.5: "Otherwise, when `tissue_quality_score` is 70 or above **and** the specular
    `endothelial_cell_count` is 2000 or above **and** the recovery's `time_limit_band` is
    `WITHIN_STANDARD`, the classification is `TRANSPLANT_OPTICAL`."

    PRD 3.5: "`TRANSPLANT_OPTICAL` and `TRANSPLANT_THERAPEUTIC` both move `disposition_status`
    from `UNGRADED` to `ELIGIBLE`, making the tissue allocatable."

    PRD 3.5: "The base is again the medium's allowance — 336 hours for `OPTISOL_GS`, 264 hours for
    `LIFE4C` — and the same 48-hour band penalty applies when the recovery's `time_limit_band` is
    `WITHIN_EXTENDED`."

    PRD 3.5: "A **cooling penalty of 72 hours** is charged when the donor's `body_cooled_at` is
    null, meaning the body was never refrigerated, **or** when the number of whole floored minutes
    from `death_at` to `body_cooled_at` is strictly greater than 480 — that is, cooling began more
    than eight hours after death."

    PRD 3.5: "A **low-endothelium penalty of 24 hours** is charged when the tissue's `RECORDED`
    `SPECULAR` evaluation reports an `endothelial_cell_count` below 2200."

    PRD 3.5: "The base less all three applicable penalties is then raised to a floor of 24 hours,
    stored in `shelf_life_hours`, and `expires_at` is recomputed as `preserved_at` advanced by
    that many whole hours."

    PRD 3.6: "Registration sets `credential_status` to `ACTIVE` and the four maintained counters
    `gross_billed_cents`, `credited_fee_cents`, `outstanding_fee_cents` and
    `substantiated_reaction_count` all to 0."

    PRD 3.6: "On success the allocation is created with `allocated_at` set to the current logical
    instant, `status` `RESERVED` and `source` `MANUAL`; `reserved_ecd_snapshot` is pinned from the
    `endothelial_cell_count` of the tissue's `RECORDED` `SPECULAR` evaluation and
    `reserved_classification_snapshot` is pinned from the tissue's `classification`, which at this
    point is necessarily `TRANSPLANT_OPTICAL` or `TRANSPLANT_THERAPEUTIC`."

    PRD 3.6: "The base is 245000 cents for `TRANSPLANT_OPTICAL` and 189000 cents for
    `TRANSPLANT_THERAPEUTIC`. Three surcharges may attach: an urgency surcharge of 7.25 percent of
    the base when the request's `urgency` is `URGENT`; a procedure surcharge of 4.25 percent of the
    base when the `procedure_type` is `DMEK` or `DSAEK`; and a short-notice surcharge of 1.75
    percent of the base when the floored whole days from the current logical instant to
    `surgery_date` is 2 or fewer."

    PRD 2.11: "A surgeon's `gross_billed_cents` is the sum of `processing_fee_cents` over every
    allocation reachable through that surgeon's requests whose `status` is `CONFIRMED`, `CONSUMED`
    or `RELEASED`. Their `credited_fee_cents` is the sum of `processing_fee_cents` over those
    allocations whose `status` is `RELEASED`. Their `outstanding_fee_cents` is `gross_billed_cents`
    less `credited_fee_cents`."

    PRD 3.7: "On success the allocation moves `RESERVED → CONFIRMED`, and the money ledger moves
    with it: the surgeon's `gross_billed_cents` and `outstanding_fee_cents` each increase by
    exactly that allocation's `processing_fee_cents`, while `credited_fee_cents` is unchanged."

    Design: Corner/consistency_model/every_write_response_already_shows_what_the_next_independent_read_returns
    """
    recovery_technician = fixtures.recovery_technician(pinned_api, "Rosa Field")
    evaluator = fixtures.evaluation_technician(pinned_api, "Nils Abadi")
    donor = fixtures.create_donor(pinned_api, donor_code="D-2846-CM1")
    screening = fixtures.add_screening(
        pinned_api, donor["id"], "TATTOO_12M", "YES", "SPOUSE"
    )
    assert screening["weight_applied"] == 10

    written_donor = fixtures.record_consent(pinned_api, donor["id"])
    read_donor = fixtures.read_donor(pinned_api, donor["id"])

    assert written_donor["status"] == "CONSENT_OBTAINED"
    assert written_donor["screening_risk_score"] == 10
    assert written_donor["screening_risk_variant"] == "INTERVIEW_ONLY"
    assert read_donor["status"] == written_donor["status"]
    assert read_donor["screening_risk_score"] == written_donor["screening_risk_score"]
    assert read_donor["version"] == written_donor["version"]
    assert_instant_equals(
        read_donor["updated_at"], written_donor["updated_at"], "donor updated_at"
    )

    panel = fixtures.draw_panel(
        pinned_api, donor["id"], expected_donor_version=written_donor["version"]
    )
    fixtures.post_results(pinned_api, panel["id"])
    fixtures.approve_recovery(pinned_api, donor["id"])
    chain = fixtures.recovered_tissues(
        pinned_api, donor["id"], recovery_technician["id"]
    )
    assert chain.recovery["time_limit_band"] == "WITHIN_STANDARD"
    tissue = chain.tissues[0]
    slit = fixtures.record_slit_lamp(
        pinned_api,
        tissue["id"],
        evaluator["id"],
        performed_at="2026-08-03T09:30:00.000Z",
        expected_tissue_version=tissue["version"],
    )
    fixtures.record_specular(
        pinned_api,
        tissue["id"],
        evaluator["id"],
        performed_at="2026-08-03T09:45:00.000Z",
        expected_tissue_version=slit["tissue_version_after"],
        endothelial_cell_count=3100,
    )

    written_tissue = fixtures.classify(pinned_api, tissue["id"])
    read_tissue = fixtures.read_tissue(pinned_api, tissue["id"], MEDICAL_DIRECTOR_HEADERS)

    assert written_tissue["classification"] == "TRANSPLANT_OPTICAL"
    assert written_tissue["tissue_quality_score"] == 86
    assert written_tissue["disposition_status"] == "ELIGIBLE"
    assert written_tissue["shelf_life_hours"] == 336
    assert_instant_equals(
        written_tissue["expires_at"], "2026-08-17T09:00:00.000Z", "expires_at"
    )
    assert read_tissue["classification"] == written_tissue["classification"]
    assert read_tissue["tissue_quality_score"] == written_tissue["tissue_quality_score"]
    assert read_tissue["disposition_status"] == written_tissue["disposition_status"]
    assert_instant_equals(
        read_tissue["expires_at"], written_tissue["expires_at"], "re-read expires_at"
    )

    surgeon = fixtures.create_surgeon(pinned_api, "Dr Imani Rho", "CTR-01", "PK")
    assert_ledger(surgeon, 0, 0, 0, "at registration")
    request = fixtures.create_request(
        pinned_api, surgeon["id"], surgery_date="2026-08-08T00:00:00.000Z"
    )
    allocation = fixtures.allocate(pinned_api, tissue["id"], request["id"])
    assert allocation["status"] == "RESERVED"
    assert allocation["processing_fee_cents"] == 245000
    assert_ledger(
        fixtures.read_surgeon(pinned_api, surgeon["id"]), 0, 0, 0, "while RESERVED"
    )

    confirmed = fixtures.confirm(pinned_api, allocation["id"])

    assert confirmed["status"] == "CONFIRMED"
    assert_ledger(
        fixtures.read_surgeon(pinned_api, surgeon["id"]),
        allocation["processing_fee_cents"],
        0,
        allocation["processing_fee_cents"],
        "after confirmation",
    )
