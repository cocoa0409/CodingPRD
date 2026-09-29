"""
Every declared error code, reached deliberately: the eleven distinct not-found ids, the
replayed state transitions, the donor-safety gates and the cold-chain sequence.

Each case drives the system to the exact position where one code is the only legitimate
answer, then re-reads the rows to prove the refusal wrote nothing.
"""

from test_helpers import (
    COORDINATOR_HEADERS,
    ERR_ALLOCATION_NOT_FOUND,
    ERR_ALLOCATION_STATE_INVALID,
    ERR_CONSENT_SCOPE_VIOLATION,
    ERR_DONOR_AGE_ABOVE_REQUEST_MAX,
    ERR_DONOR_NOT_FOUND,
    ERR_EVALUATION_INCOMPLETE,
    ERR_INVALID_REISSUE_SOURCE,
    ERR_INVESTIGATION_NOT_FOUND,
    ERR_INVESTIGATION_STATE_INVALID,
    ERR_NO_TEMPERATURE_BASELINE,
    ERR_PANEL_STATE_INVALID,
    ERR_PROCEDURE_CLASSIFICATION_MISMATCH,
    ERR_READING_OUTSIDE_SHIPMENT_WINDOW,
    ERR_RECOVERY_NOT_FOUND,
    ERR_REISSUE_LIMIT_REACHED,
    ERR_REPORT_NOT_FOUND,
    ERR_REPORT_STATE_INVALID,
    ERR_REPORT_TISSUE_NOT_IMPLANTED_BY_SURGEON,
    ERR_REQUEST_NOT_FOUND,
    ERR_REQUEST_STATE_INVALID,
    ERR_SCREENING_RISK_TOO_HIGH,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SEROLOGY_PANEL_NOT_FOUND,
    ERR_SEROLOGY_PENDING,
    ERR_SHIPMENT_NOT_FOUND,
    ERR_SHIPMENT_STATE_INVALID,
    ERR_SURGEON_NOT_FOUND,
    ERR_TECHNICIAN_NOT_FOUND,
    ERR_TISSUE_CUSTODY_INVALID,
    ERR_TISSUE_EXPIRED,
    ERR_TISSUE_NOT_FOUND,
    LAB_TECHNICIAN_HEADERS,
    MEDICAL_DIRECTOR_HEADERS,
    T_EVAL_SLIT,
    T_NOW,
    UNKNOWN_ALLOCATION_ID,
    UNKNOWN_DONOR_ID,
    UNKNOWN_INVESTIGATION_ID,
    UNKNOWN_PANEL_ID,
    UNKNOWN_RECOVERY_ID,
    UNKNOWN_REPORT_ID,
    UNKNOWN_REQUEST_ID,
    UNKNOWN_SHIPMENT_ID,
    UNKNOWN_SURGEON_ID,
    UNKNOWN_TECHNICIAN_ID,
    UNKNOWN_TISSUE_ID,
    assert_dimensions,
    assert_instant_equals,
    factories,
    fixtures,
    get_success_data,
    make_evaluation_technician_headers,
    make_surgeon_headers,
    total_count_of,
    validate_error,
    validate_success,
)


def test_every_not_found_id_in_the_catalog_is_reachable_with_an_unknown_uuid(pinned_api):
    """
    Eleven syntactically valid but absent identifiers produce eleven distinct 404 codes
    rather than one shared not-found, and a body-level foreign key reports the first
    unresolved key of the two it was handed.

    PRD 2.8: "Path identifiers are resolved strictly left to right, and the first one that
    fails to resolve determines the response."

    PRD 2.8: "Every not-found condition carries HTTP 404 and the code named for the missing
    entity: `ERR_DONOR_NOT_FOUND`, `ERR_SEROLOGY_PANEL_NOT_FOUND`,
    `ERR_TECHNICIAN_NOT_FOUND`, `ERR_RECOVERY_NOT_FOUND`, `ERR_TISSUE_NOT_FOUND`,
    `ERR_SURGEON_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`,
    `ERR_SHIPMENT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND` and `ERR_INVESTIGATION_NOT_FOUND`."

    PRD 2.8: "Foreign keys supplied in a request **body** are resolved with the same
    vocabulary, after all path identifiers have resolved: `donor_id`, `technician_id`,
    `evaluator_technician_id`, `surgeon_id`, `tissue_id`, `request_id`, `allocation_id`,
    `replaces_shipment_id` and `source_report_id` each yield the corresponding not-found
    code."

    PRD 2.10: "Every identifier in the request path resolves, left to right — otherwise the
    matching 404 code from section 2.8. Applies to every endpoint with a path identifier."

    PRD 2.10: "Every foreign key in the request body resolves — otherwise the matching 404
    code. Applies to recovery dispatch, tissue evaluation, surgeon-request creation, manual
    allocation, shipment preparation and adverse-reaction reporting."

    PRD 3.6: "Manual allocation reserves exactly one tissue against exactly one request. The
    coordinator supplies `tissue_id` and `request_id`."

    Design: Corner/errors/every_not_found_id_in_the_catalog_is_reachable_with_an_unknown_uuid
    """
    validate_error(
        pinned_api.get_donor(UNKNOWN_DONOR_ID, COORDINATOR_HEADERS),
        ERR_DONOR_NOT_FOUND,
        404,
    )
    validate_error(
        pinned_api.get_technician(UNKNOWN_TECHNICIAN_ID, COORDINATOR_HEADERS),
        ERR_TECHNICIAN_NOT_FOUND,
        404,
    )
    validate_error(
        pinned_api.post_serology_results(
            UNKNOWN_PANEL_ID, factories.results_payload(), LAB_TECHNICIAN_HEADERS
        ),
        ERR_SEROLOGY_PANEL_NOT_FOUND,
        404,
    )
    validate_error(
        pinned_api.get_recovery(UNKNOWN_RECOVERY_ID, COORDINATOR_HEADERS),
        ERR_RECOVERY_NOT_FOUND,
        404,
    )
    validate_error(
        pinned_api.get_tissue(UNKNOWN_TISSUE_ID, COORDINATOR_HEADERS),
        ERR_TISSUE_NOT_FOUND,
        404,
    )
    validate_error(
        pinned_api.get_surgeon(UNKNOWN_SURGEON_ID, COORDINATOR_HEADERS),
        ERR_SURGEON_NOT_FOUND,
        404,
    )
    validate_error(
        pinned_api.get_surgeon_request(UNKNOWN_REQUEST_ID, COORDINATOR_HEADERS),
        ERR_REQUEST_NOT_FOUND,
        404,
    )
    validate_error(
        pinned_api.get_allocation(UNKNOWN_ALLOCATION_ID, COORDINATOR_HEADERS),
        ERR_ALLOCATION_NOT_FOUND,
        404,
    )
    validate_error(
        pinned_api.get_shipment(UNKNOWN_SHIPMENT_ID, COORDINATOR_HEADERS),
        ERR_SHIPMENT_NOT_FOUND,
        404,
    )
    validate_error(
        pinned_api.get_adverse_reaction_report(UNKNOWN_REPORT_ID, COORDINATOR_HEADERS),
        ERR_REPORT_NOT_FOUND,
        404,
    )
    validate_error(
        pinned_api.get_lookback_investigation(
            UNKNOWN_INVESTIGATION_ID, MEDICAL_DIRECTOR_HEADERS
        ),
        ERR_INVESTIGATION_NOT_FOUND,
        404,
    )

    body_fk = pinned_api.create_allocation(
        factories.allocation_payload(UNKNOWN_TISSUE_ID, UNKNOWN_REQUEST_ID),
        COORDINATOR_HEADERS,
    )

    validate_error(body_fk, ERR_TISSUE_NOT_FOUND, 404)


def test_resulting_the_same_panel_twice_yields_err_panel_state_invalid(pinned_api):
    """
    The results endpoint is legal only from DRAWN, so a second post carrying a reactive HIV
    marker is refused and neither the stored verdict nor the donor's published serology
    moves.

    PRD 3.2: "The four marker fields `hiv_result`, `hbv_result`, `hcv_result` and
    `syphilis_result` are each `NON_REACTIVE`, `REACTIVE` or `INDETERMINATE`, and only a
    panel still in `DRAWN` accepts them; a panel already `RESULTED` or `INVALIDATED` is
    refused with `ERR_PANEL_STATE_INVALID`."

    PRD 2.10: "The serology panel's `status` is `DRAWN` — otherwise
    `ERR_PANEL_STATE_INVALID` (409). Applies to posting marker results."

    PRD 3.2: "The panel moves `DRAWN → RESULTED` with `resulted_at` stamped from the logical
    clock, and the donor's `serology_status` is republished from the verdict: `NON_REACTIVE`
    becomes `NEGATIVE`, `REACTIVE` becomes `REACTIVE`, and `INDETERMINATE` becomes
    `INDETERMINATE`."

    Design: Corner/errors/resulting_the_same_panel_twice_yields_err_panel_state_invalid
    """
    donor = fixtures.consented_donor(pinned_api, donor_code="D-2846-X02", body_cooled_at=None)
    panel = fixtures.draw_panel(pinned_api, donor["id"])
    first = fixtures.post_results(pinned_api, panel["id"])
    assert first["overall_result"] == "NON_REACTIVE"
    assert first["version"] == 2

    response = pinned_api.post_serology_results(
        panel["id"],
        factories.results_payload(hiv_result="REACTIVE"),
        LAB_TECHNICIAN_HEADERS,
    )

    validate_error(response, ERR_PANEL_STATE_INVALID, 409)
    panels = get_success_data(
        pinned_api.list_serology_panels(donor["id"], LAB_TECHNICIAN_HEADERS)
    )
    assert len(panels) == 1
    assert panels[0]["overall_result"] == "NON_REACTIVE"
    assert panels[0]["hiv_result"] == "NON_REACTIVE"
    assert panels[0]["version"] == 2
    reread = fixtures.read_donor(pinned_api, donor["id"])
    assert reread["serology_status"] == "NEGATIVE"
    assert reread["status"] == "CONSENT_OBTAINED"


def test_cancelling_a_cancelled_request_yields_err_request_state_invalid(pinned_api):
    """
    Cancellation accepts OPEN or ALLOCATED only, so the second cancellation is refused and
    the original reason survives rather than being overwritten by the replay.

    PRD 3.6: "A request may be cancelled by its surgeon or by a coordinator while it is
    `OPEN` or `ALLOCATED`. Cancellation records `cancel_reason`, moves the request to the
    terminal `CANCELLED` status and increments its `version`."

    PRD 2.10: "The surgeon request's `status` permits the operation — `OPEN` for allocation,
    `OPEN` or `ALLOCATED` for cancellation — otherwise `ERR_REQUEST_STATE_INVALID` (409)."

    Design: Corner/errors/cancelling_a_cancelled_request_yields_err_request_state_invalid
    """
    booking = fixtures.surgeon_with_request(pinned_api, "Dr Imani Rho", "CTR-01", "PK")
    cancelled = fixtures.cancel_request(
        pinned_api, booking.request_id, "Patient deferred"
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == "Patient deferred"
    assert cancelled["version"] == 2

    response = pinned_api.cancel_surgeon_request(
        booking.request_id,
        factories.cancel_request_payload("Duplicate booking"),
        COORDINATOR_HEADERS,
    )

    validate_error(response, ERR_REQUEST_STATE_INVALID, 409)
    reread = fixtures.read_request(pinned_api, booking.request_id)
    assert reread["status"] == "CANCELLED"
    assert reread["cancel_reason"] == "Patient deferred"
    assert reread["version"] == 2


def test_closing_an_open_investigation_yields_err_investigation_state_invalid(pinned_api):
    """
    The two-step recall sequence cannot be short-circuited: closing a freshly opened
    investigation is refused with both closure fields still null, while notification from
    that very same OPEN state succeeds.

    PRD 3.9: "The director supplies `donor_id` and optionally `source_report_id`;
    `trigger_reason` is set to `ADVERSE_REACTION` when a `source_report_id` was supplied and
    to `POSITIVE_RETEST` when it was not."

    PRD 3.9: "The investigation is created with `opened_at` stamped from the logical clock,
    `status` `OPEN`, `notified_at`, `closed_at`, `closure_note` and
    `notified_recipient_count` all null, and the donor's `lookback_flag` set to true with the
    donor's `version` incremented."

    PRD 3.9: "`impacted_tissue_count` is set to the count of **every** tissue of that donor,
    with no status filter whatsoever — implanted, discarded, research-released and
    quarantined tissue all count, because the investigation's job is to state how many
    corneas came from this donor at all."

    PRD 3.9: "Closure is legal only from `NOTIFIED` — an investigation may not be closed
    before its recipients have been notified."

    PRD 2.10: "The lookback investigation's `status` permits the operation — `OPEN` for
    notification, `NOTIFIED` for closure — otherwise `ERR_INVESTIGATION_STATE_INVALID`
    (409)."

    PRD 3.9: "Notification records that every reachable recipient has been contacted. It is
    legal only from `OPEN`, stamps `notified_at` from the logical clock, moves the
    investigation `OPEN → NOTIFIED` and sets `notified_recipient_count`."

    Design: Corner/errors/closing_an_open_investigation_yields_err_investigation_state_invalid
    """
    donor = fixtures.create_donor(
        pinned_api, donor_code="D-2846-X04", body_cooled_at=None
    )
    investigation = fixtures.open_lookback(pinned_api, donor["id"])
    assert investigation["status"] == "OPEN"
    assert investigation["trigger_reason"] == "POSITIVE_RETEST"
    assert_instant_equals(investigation["opened_at"], T_NOW, "opened_at")
    assert investigation["impacted_tissue_count"] == 0
    assert investigation["quarantined_count"] == 0
    assert fixtures.read_donor(pinned_api, donor["id"])["lookback_flag"] is True

    response = pinned_api.close_investigation(
        investigation["id"],
        factories.close_payload("NO_ACTION", "Nothing found"),
        MEDICAL_DIRECTOR_HEADERS,
    )

    validate_error(response, ERR_INVESTIGATION_STATE_INVALID, 409)
    reread = fixtures.read_investigation(pinned_api, investigation["id"])
    assert reread["status"] == "OPEN"
    assert reread["closed_at"] is None
    assert reread["closure_note"] is None

    notified = fixtures.notify_investigation(pinned_api, investigation["id"])

    assert notified["status"] == "NOTIFIED"
    assert_instant_equals(notified["notified_at"], T_NOW, "notified_at")
    assert notified["notified_recipient_count"] == 0


def test_the_recovering_technician_grading_their_own_tissue_yields_err_segregation_of_duties(
    pinned_api,
):
    """
    The evaluator is fully certified to grade, so certification is not the obstacle: the
    refusal is the duty split alone, and it leaves no evaluation row and an untouched tissue.

    PRD 3.4: "Two personnel gates guard the write. The bank enforces **segregation of
    duties**: the technician who recovered a cornea may not be the technician who grades it.
    Concretely, if the named `evaluator_technician_id` equals the `technician_id` of the
    recovery that produced this tissue, the evaluation is refused with
    `ERR_SEGREGATION_OF_DUTIES`."

    PRD 3.4: "All three of those failures are reported as `ERR_TECHNICIAN_NOT_CERTIFIED`, and
    the segregation-of-duties check is evaluated **before** them, so a recovering technician
    who is also uncertified is reported as a segregation-of-duties violation."

    PRD 2.10: "The `evaluator_technician_id` differs from the `technician_id` of the recovery
    that produced the tissue — otherwise `ERR_SEGREGATION_OF_DUTIES` (422). Applies to
    tissue-evaluation creation."

    PRD 2.5: "Most resources additionally carry `updated_at` — the logical-clock instant of
    the most recent mutation, initially equal to `created_at` — and `version`, an integer
    that starts at 1 on creation and increases by exactly 1 on every mutation of that row."

    Design: Corner/errors/the_recovering_technician_grading_their_own_tissue_yields_err_segregation_of_duties
    """
    technician = fixtures.evaluation_technician(pinned_api, "Nils Abadi")
    donor = fixtures.approved_donor(pinned_api, donor_code="D-2846-X05")
    chain = fixtures.recovered_tissues(pinned_api, donor["id"], technician["id"])
    tissue = chain.tissues[0]
    assert tissue["version"] == 1

    response = pinned_api.create_tissue_evaluation(
        tissue["id"],
        factories.slit_lamp_payload(technician["id"], T_EVAL_SLIT, tissue["version"]),
        make_evaluation_technician_headers(technician["id"]),
    )

    validate_error(response, ERR_SEGREGATION_OF_DUTIES, 422)
    rows = get_success_data(
        pinned_api.list_tissue_evaluations(tissue["id"], COORDINATOR_HEADERS)
    )
    assert len(rows) == 0
    assert fixtures.read_tissue(pinned_api, tissue["id"])["version"] == 1


def test_classifying_with_only_a_slit_lamp_reading_yields_err_evaluation_incomplete(
    pinned_api,
):
    """
    One recorded examination is not enough: classification demands one of each method, and the
    refusal leaves the tissue UNGRADED with no score and no classification.

    PRD 3.4: "When an evaluation is recorded, it is created with `status` `RECORDED`, and **any
    earlier evaluation of the same tissue with the same `method`** moves to `SUPERSEDED`;
    evaluations of the other method are untouched."

    PRD 3.4: "Each write increments the tissue's `version` by 1 and stores that post-write
    value in the new evaluation's `tissue_version_after`, which is the handle the client must
    echo as `expected_tissue_version` on its next evaluation of the same tissue."

    PRD 3.5: "It is legal only for a tissue whose `disposition_status` is still `UNGRADED`, and
    it requires that the tissue already carry **one `RECORDED` `SLIT_LAMP` evaluation and one
    `RECORDED` `SPECULAR` evaluation**; a tissue missing either is refused with
    `ERR_EVALUATION_INCOMPLETE`."

    PRD 2.10: "Both a recorded `SLIT_LAMP` evaluation and a recorded `SPECULAR` evaluation
    exist for the tissue — otherwise `ERR_EVALUATION_INCOMPLETE` (422). Applies to tissue
    classification."

    Design: Corner/errors/classifying_with_only_a_slit_lamp_reading_yields_err_evaluation_incomplete
    """
    recoverer = fixtures.recovery_technician(pinned_api, "Rosa Field")
    evaluator = fixtures.evaluation_technician(pinned_api, "Nils Abadi")
    donor = fixtures.approved_donor(
        pinned_api,
        donor_code="D-2846-X06",
        body_cooled_at="2026-08-03T03:00:00.000Z",
        age_years=52,
    )
    chain = fixtures.recovered_tissues(
        pinned_api, donor["id"], recoverer["id"]
    )
    tissue_id = chain.tissues[0]["id"]

    evaluation = fixtures.record_slit_lamp(
        pinned_api, tissue_id, evaluator["id"]
    )
    assert evaluation["status"] == "RECORDED"
    assert evaluation["tissue_version_after"] == 2

    response = pinned_api.classify_tissue(
        tissue_id, factories.classify_payload(), MEDICAL_DIRECTOR_HEADERS
    )

    validate_error(response, ERR_EVALUATION_INCOMPLETE, 422)
    reread = fixtures.read_tissue(pinned_api, tissue_id)
    assert reread["disposition_status"] == "UNGRADED"
    assert reread["tissue_quality_score"] is None
    assert reread["classification"] is None
    assert reread["version"] == 2


def test_classifying_a_donor_with_no_resulted_panel_yields_err_serology_pending(pinned_api):
    """
    Approval only bars a reactive donor, so a donor with no panel at all reaches recovery and
    full grading; the serology gate lands one step later, at classification.

    PRD 3.2: "It requires the donor to be in `CONSENT_OBTAINED` — any other status is
    `ERR_DONOR_STATE_INVALID` — and requires `serology_status` to be anything other than
    `REACTIVE`, a reactive donor being refused with `ERR_SEROLOGY_REACTIVE`."

    PRD 3.5: "The donor's `serology_status` must not be `PENDING` — a resulted,
    non-invalidated panel must exist — refused with `ERR_SEROLOGY_PENDING`, because the bank
    will not assign a regulatory fate to tissue whose serology is unknown."

    PRD 2.10: "The donor's `serology_status` is not `PENDING`, meaning a resulted,
    non-invalidated panel exists — otherwise `ERR_SEROLOGY_PENDING` (422). Applies to tissue
    classification."

    Design: Corner/errors/classifying_a_donor_with_no_resulted_panel_yields_err_serology_pending
    """
    recoverer = fixtures.recovery_technician(pinned_api, "Rosa Field")
    evaluator = fixtures.evaluation_technician(pinned_api, "Nils Abadi")
    donor = fixtures.approved_donor(
        pinned_api,
        with_serology=False,
        donor_code="D-2846-X07",
        body_cooled_at="2026-08-03T03:00:00.000Z",
        age_years=52,
    )
    assert donor["status"] == "APPROVED_FOR_RECOVERY"
    assert donor["serology_status"] == "PENDING"
    chain = fixtures.recovered_tissues(
        pinned_api, donor["id"], recoverer["id"]
    )
    tissue_id = chain.tissues[0]["id"]
    graded = fixtures.graded_tissue(
        pinned_api, tissue_id, evaluator["id"]
    )
    assert graded["version"] == 3

    response = pinned_api.classify_tissue(
        tissue_id, factories.classify_payload(), MEDICAL_DIRECTOR_HEADERS
    )

    validate_error(response, ERR_SEROLOGY_PENDING, 422)
    reread = fixtures.read_tissue(pinned_api, tissue_id)
    assert reread["disposition_status"] == "UNGRADED"
    assert reread["classification"] is None
    assert reread["version"] == 3


def test_a_transplant_override_on_a_sixty_point_risk_donor_yields_err_screening_risk_too_high(
    pinned_api,
):
    """
    A single CJD_FAMILY answer carries 60 points, which does not gate recovery at all but sits
    above the transplant ceiling, so the transplant assertion at classification is refused.

    PRD 3.1: "The weights encode the bank's clinical priorities: a family history of
    Creutzfeldt–Jakob disease (`CJD_FAMILY`) is worth 60 points, unexplained neurological death
    (`UNEXPLAINED_NEURO`) 50, intravenous drug use (`IV_DRUG_USE`) 40, HIV risk behaviour
    (`HIV_RISK`) 35, a hepatitis B or C history (`HEP_B_C_HISTORY`) 30, sepsis (`SEPSIS`) 25,
    incarceration within the last twelve months (`INCARCERATION_12M`) 15 and a tattoo within
    the last twelve months (`TATTOO_12M`) 10."

    PRD 3.1: "Whichever variant applies, `weight_applied` on every one of the donor's rows is
    rewritten to the weight that row actually contributed — the question's weight for a `YES`
    row, zero for a `NO` row, and zero for an `UNKNOWN` row whenever the predicate fails."

    PRD 3.1: "A `screening_risk_score` of 50 or more is the bank's **transplant risk ceiling**:
    at or above that figure the donor can never yield a transplant-grade graft, as section 3.5
    makes precise."

    PRD 3.5: "That assertion is checked against the donor's screening: when
    `intended_use_override` is `TRANSPLANT` and the donor's `screening_risk_score` is 50 or
    above, the classification is refused with `ERR_SCREENING_RISK_TOO_HIGH`."

    PRD 2.10: "When `intended_use_override` is `TRANSPLANT`, the donor's
    `screening_risk_score` is strictly below 50 — otherwise `ERR_SCREENING_RISK_TOO_HIGH`
    (422). Applies to tissue classification."

    Design: Corner/errors/a_transplant_override_on_a_sixty_point_risk_donor_yields_err_screening_risk_too_high
    """
    recoverer = fixtures.recovery_technician(pinned_api, "Rosa Field")
    evaluator = fixtures.evaluation_technician(pinned_api, "Nils Abadi")
    donor = fixtures.create_donor(
        pinned_api,
        donor_code="D-2846-X09",
        body_cooled_at="2026-08-03T03:00:00.000Z",
        age_years=52,
        cause_of_death_category="NEUROLOGIC",
    )
    record = fixtures.add_screening(
        pinned_api, donor["id"], "CJD_FAMILY", "YES", "SPOUSE"
    )
    assert record["weight_applied"] == 60
    consented = fixtures.record_consent(
        pinned_api,
        donor["id"],
        consent_type="NEXT_OF_KIN",
        consent_scope="TRANSPLANT_ONLY",
        authorizing_party_name="Spouse Delia",
    )
    assert consented["screening_risk_score"] == 60
    fixtures.resulted_panel_for(pinned_api, donor["id"])
    approved = fixtures.approve_recovery(pinned_api, donor["id"])
    assert approved["status"] == "APPROVED_FOR_RECOVERY"
    assert approved["screening_risk_score"] == 60
    chain = fixtures.recovered_tissues(
        pinned_api, donor["id"], recoverer["id"]
    )
    tissue_id = chain.tissues[0]["id"]
    graded = fixtures.graded_tissue(
        pinned_api, tissue_id, evaluator["id"]
    )
    assert graded["version"] == 3

    response = pinned_api.classify_tissue(
        tissue_id,
        factories.classify_payload(intended_use_override="TRANSPLANT"),
        MEDICAL_DIRECTOR_HEADERS,
    )

    validate_error(response, ERR_SCREENING_RISK_TOO_HIGH, 422)
    reread = fixtures.read_tissue(pinned_api, tissue_id)
    assert reread["disposition_status"] == "UNGRADED"
    assert reread["classification"] is None
    assert reread["version"] == 3


def test_allocating_a_tissue_after_its_expiry_instant_yields_err_tissue_expired(pinned_api):
    """
    Advancing the clock past the expiry does not rewrite the tissue, but it changes the next
    comparison: the viability gate at rung 34 answers before the expiry-versus-surgery gate at
    rung 35, which this pair also violates.

    PRD 2.4: "Setting the clock mutates no entity and recomputes no derived field — a donor
    whose recovery deadline has just passed is not retroactively rewritten; the newly current
    instant simply changes the outcome of the next comparison."

    PRD 3.5: "The base is again the medium's allowance — 336 hours for `OPTISOL_GS`, 264 hours
    for `LIFE4C` — and the same 48-hour band penalty applies when the recovery's
    `time_limit_band` is `WITHIN_EXTENDED`."

    PRD 3.5: "The base less all three applicable penalties is then raised to a floor of 24
    hours, stored in `shelf_life_hours`, and `expires_at` is recomputed as `preserved_at`
    advanced by that many whole hours."

    PRD 2.10: "The tissue's `expires_at` is strictly later than the logical clock — otherwise
    `ERR_TISSUE_EXPIRED` (422). Applies to manual allocation and implantation."

    PRD 2.10: "The tissue's `expires_at` is at or after the request's `surgery_date` —
    otherwise `ERR_EXPIRY_BEFORE_SURGERY_DATE` (422). Applies to three operations: manual
    allocation, allocation confirmation and shipment dispatch."

    Design: Corner/errors/allocating_a_tissue_after_its_expiry_instant_yields_err_tissue_expired
    """
    chain = fixtures.tissue_chain(
        pinned_api,
        donor_code="D-2846-X10",
        donor_kwargs={"body_cooled_at": "2026-08-03T03:00:00.000Z", "age_years": 52},
        endothelial_cell_count=3100,
        evaluation_technician_name="Nils Abadi",
    )
    tissue = chain["tissues"][0]
    assert tissue["disposition_status"] == "ELIGIBLE"
    assert_instant_equals(tissue["expires_at"], "2026-08-17T09:00:00.000Z", "expires_at")
    surgeon = fixtures.create_surgeon(pinned_api, "Dr Imani Rho", "CTR-01", "PK")
    moved = fixtures.set_clock(pinned_api, "2026-08-18T00:00:00.000Z")
    assert_instant_equals(moved["current_utc"], "2026-08-18T00:00:00.000Z", "current_utc")
    request = fixtures.create_request(
        pinned_api,
        surgeon["id"],
        procedure_type="PK",
        surgery_date="2026-08-20T00:00:00.000Z",
        min_ecd=2000,
        max_donor_age_years=70,
    )

    response = pinned_api.create_allocation(
        factories.allocation_payload(tissue["id"], request["id"]), COORDINATOR_HEADERS
    )

    validate_error(response, ERR_TISSUE_EXPIRED, 422)
    assert_dimensions(
        fixtures.read_tissue(pinned_api, tissue["id"]),
        "ELIGIBLE",
        "IN_HOUSE",
        "after the refused allocation",
    )
    assert fixtures.read_request(pinned_api, request["id"])["status"] == "OPEN"


def test_allocation_admission_separates_the_procedure_mismatch_from_the_donor_age_ceiling(
    pinned_api,
):
    """
    One therapeutic cornea from a 68-year-old donor is offered to two requests that each break
    exactly one admission filter, and the two refusals name different codes rather than
    collapsing into the shared ECD floor, which both requests satisfy.

    PRD 3.5: "Otherwise, when `tissue_quality_score` is 45 or above **and** the specular
    `endothelial_cell_count` is 1800 or above, the classification is `TRANSPLANT_THERAPEUTIC`."

    PRD 3.5: "A **low-endothelium penalty of 24 hours** is charged when the tissue's `RECORDED`
    `SPECULAR` evaluation reports an `endothelial_cell_count` below 2200."

    PRD 3.6: "A tissue classified `TRANSPLANT_OPTICAL` may be matched to a request whose
    `procedure_type` is `PK`, `DSAEK`, `DMEK` or `THERAPEUTIC` — optical-grade tissue is
    acceptable for every procedure. A tissue classified `TRANSPLANT_THERAPEUTIC` may be matched
    only to a `THERAPEUTIC` or a `PK` request; the lamellar procedures `DSAEK` and `DMEK` demand
    optical-grade tissue and a therapeutic tissue offered for either is a mismatch."

    PRD 2.10: "The tissue's `classification` is a transplant classification and permits the
    request's `procedure_type` — otherwise `ERR_PROCEDURE_CLASSIFICATION_MISMATCH` (422).
    Applies to manual allocation."

    PRD 2.10: "The tissue's recorded specular `endothelial_cell_count` is at least the
    request's `min_ecd` — otherwise `ERR_ECD_BELOW_REQUEST_MINIMUM` (422). Applies to manual
    allocation."

    PRD 2.10: "The donor's `age_years` is no greater than the request's `max_donor_age_years` —
    otherwise `ERR_DONOR_AGE_ABOVE_REQUEST_MAX` (422). Applies to manual allocation."

    Design: Corner/errors/allocation_admission_separates_the_procedure_mismatch_from_the_donor_age_ceiling
    """
    chain = fixtures.tissue_chain(
        pinned_api,
        donor_code="D-2846-X11",
        donor_kwargs={"body_cooled_at": "2026-08-03T03:00:00.000Z", "age_years": 68},
        endothelial_cell_count=2100,
        evaluation_technician_name="Nils Abadi",
    )
    tissue = chain["tissues"][0]
    assert tissue["tissue_quality_score"] == 66
    assert tissue["classification"] == "TRANSPLANT_THERAPEUTIC"
    assert tissue["shelf_life_hours"] == 312
    assert_instant_equals(tissue["expires_at"], "2026-08-16T09:00:00.000Z", "expires_at")
    surgeon = fixtures.create_surgeon(pinned_api, "Dr Imani Rho", "CTR-01", "PK")
    lamellar = fixtures.create_request(
        pinned_api,
        surgeon["id"],
        procedure_type="DMEK",
        surgery_date="2026-08-08T00:00:00.000Z",
        min_ecd=2000,
        max_donor_age_years=70,
    )
    young_only = fixtures.create_request(
        pinned_api,
        surgeon["id"],
        procedure_type="THERAPEUTIC",
        surgery_date="2026-08-09T00:00:00.000Z",
        min_ecd=2000,
        max_donor_age_years=40,
    )

    mismatch = pinned_api.create_allocation(
        factories.allocation_payload(tissue["id"], lamellar["id"]), COORDINATOR_HEADERS
    )
    too_old = pinned_api.create_allocation(
        factories.allocation_payload(tissue["id"], young_only["id"]), COORDINATOR_HEADERS
    )

    validate_error(mismatch, ERR_PROCEDURE_CLASSIFICATION_MISMATCH, 422)
    validate_error(too_old, ERR_DONOR_AGE_ABOVE_REQUEST_MAX, 422)
    assert (
        total_count_of(
            pinned_api.list_allocations(COORDINATOR_HEADERS, tissue_id=tissue["id"])
        )
        == 0
    )
    assert (
        fixtures.read_tissue(pinned_api, tissue["id"])["disposition_status"] == "ELIGIBLE"
    )


def test_the_cold_chain_sequence_triggers_seven_distinct_state_and_window_error_codes(
    pinned_api,
):
    """
    One allocation is walked from RESERVED to IN_TRANSIT with every next step attempted one beat
    too early, and each premature attempt names its own code — including a custody conflict that
    must not degrade into the dimension-A eligibility code, since dimension A is already ISSUED.

    PRD 3.7: "A shipment is prepared against a `CONFIRMED` allocation."

    PRD 2.10: "The allocation's `status` permits the operation — `RESERVED` for confirmation and
    cancellation, `CONFIRMED` for shipment preparation and shipment dispatch — otherwise
    `ERR_ALLOCATION_STATE_INVALID` (409). This check also guards request cancellation, where an
    allocation that has already left `RESERVED` blocks the cancellation."

    PRD 3.7: "The shipment is created in `PREPARED` with `shipped_at`, `delivered_at`,
    `min_temp_c`, `max_temp_c`, `temp_excursion_minutes_over` and `integrity_verdict` all null."

    PRD 3.8: "It is legal only for a shipment in `IN_TRANSIT` whose tissue's `custody_status` is
    `IN_TRANSIT`, and only for the surgeon reachable from the shipment's allocation."

    PRD 2.10: "The shipment's `status` permits the operation — `PREPARED` for dispatch,
    `PREPARED` or `IN_TRANSIT` for appending a temperature reading, `IN_TRANSIT` for delivery —
    otherwise `ERR_SHIPMENT_STATE_INVALID` (409)."

    PRD 3.7: "The reading must fall inside the shipment's monitoring window: `recorded_at` must
    be at or after the shipment's own `created_at`, and — once `shipped_at` has been set — at or
    before `shipped_at` advanced by 168 hours, which is seven days. For a shipment still in
    `PREPARED` the `shipped_at` bound does not yet exist, so only the lower bound is enforced. A
    reading outside the window is refused with `ERR_READING_OUTSIDE_SHIPMENT_WINDOW`."

    PRD 2.10: "A temperature reading's `recorded_at` lies inside the shipment's monitoring
    window — otherwise `ERR_READING_OUTSIDE_SHIPMENT_WINDOW` (422). Applies to appending a
    temperature reading."

    PRD 3.7: "The shipment must be `PREPARED`, its allocation must be `CONFIRMED`, the receiving
    surgeon must be `ACTIVE`, the tissue's `expires_at` must still be at or after the request's
    `surgery_date`, the tissue's `reissue_generation` must be at most 1, and — critically — the
    shipment must already carry **at least one temperature reading**, the pre-dispatch reading
    being the cold-chain baseline against which the first excursion segment is measured. A
    shipment with no readings is refused with `ERR_NO_TEMPERATURE_BASELINE`."

    PRD 2.10: "The shipment being dispatched has at least one temperature reading — otherwise
    `ERR_NO_TEMPERATURE_BASELINE` (422)."

    PRD 3.7: "On success `shipped_at` is stored, the shipment moves `PREPARED → IN_TRANSIT`, and
    the tissue moves on **both** dimensions in the same request: `disposition_status` goes
    `RESERVED → ISSUED` and `custody_status` goes `IN_HOUSE → IN_TRANSIT`, or `RETURNED_TO_BANK →
    IN_TRANSIT` when this is a re-issue of previously returned tissue."

    PRD 3.7: "The tissue's `issue_count` increases by 1 — this is the only place it ever moves —
    and the `version` of the shipment and of the tissue each increase by 1."

    PRD 3.8: "It requires the tissue's `disposition_status` to be `ISSUED` and its
    `custody_status` to be `AT_SURGEON`, requires the tissue's `expires_at` to be strictly later
    than the current logical instant — a cornea that expired in the surgeon's fridge may not be
    grafted, refused with `ERR_TISSUE_EXPIRED` — and requires the delivering shipment's
    `integrity_verdict` to be `PASS` or `EXCURSION_MINOR`, refused otherwise with
    `ERR_SHIPMENT_INTEGRITY_FAILED`."

    PRD 2.10: "The tissue's `custody_status` is a legal from-state for the requested dimension-B
    transition — otherwise `ERR_TISSUE_CUSTODY_INVALID` (409). Applies to implantation,
    unused-tissue return, shipment dispatch and manual allocation."

    PRD 3.9: "The report is only accepted for a tissue the reporting surgeon actually grafted:
    the tissue's `disposition_status` must be `IMPLANTED` **and** the `surgeon_id` of the request
    behind that tissue's consumed allocation must equal the body's `surgeon_id`, with any other
    combination refused as `ERR_REPORT_TISSUE_NOT_IMPLANTED_BY_SURGEON`."

    PRD 2.10: "The reported tissue is `IMPLANTED` and its consumed allocation belongs to the
    reporting surgeon — otherwise `ERR_REPORT_TISSUE_NOT_IMPLANTED_BY_SURGEON` (422). Applies to
    adverse-reaction reporting."

    PRD 3.7: "When `replaces_shipment_id` is supplied it must reference a shipment whose `status`
    is `RETURNED` **and** whose allocation covers the same tissue as the new shipment's
    allocation; anything else — a shipment in another status, or a returned shipment for a
    different tissue — is refused with `ERR_INVALID_REISSUE_SOURCE`."

    PRD 2.10: "`replaces_shipment_id`, when supplied, references a `RETURNED` shipment covering
    the same tissue — otherwise `ERR_INVALID_REISSUE_SOURCE` (422). Applies to shipment
    preparation."

    Design: Corner/errors/the_cold_chain_sequence_triggers_seven_distinct_state_and_window_error_codes
    """
    chain = fixtures.tissue_chain(
        pinned_api,
        donor_code="D-2846-X12",
        donor_kwargs={"body_cooled_at": "2026-08-03T03:00:00.000Z", "age_years": 52},
        evaluation_technician_name="Nils Abadi",
    )
    tissue_id = chain["tissue_ids"][0]
    assert chain["tissues"][0]["classification"] == "TRANSPLANT_OPTICAL"
    booking = fixtures.surgeon_with_request(pinned_api, "Dr Imani Rho", "CTR-01", "PK")
    allocation = fixtures.allocate(pinned_api, tissue_id, booking.request_id)
    assert allocation["status"] == "RESERVED"

    too_early = pinned_api.create_shipment(
        factories.shipment_payload(allocation["id"], "COURIER"), COORDINATOR_HEADERS
    )

    validate_error(too_early, ERR_ALLOCATION_STATE_INVALID, 409)
    assert fixtures.confirm(pinned_api, allocation["id"])["status"] == "CONFIRMED"

    shipment = fixtures.prepare_shipment(pinned_api, allocation["id"])
    assert shipment["status"] == "PREPARED"
    assert shipment["integrity_verdict"] is None
    assert shipment["shipped_at"] is None

    early_delivery = pinned_api.deliver_shipment(
        shipment["id"],
        factories.deliver_payload("2026-08-03T12:00:00.000Z"),
        make_surgeon_headers(booking.surgeon_id),
    )

    validate_error(early_delivery, ERR_SHIPMENT_STATE_INVALID, 409)

    before_window = pinned_api.create_temperature_reading(
        shipment["id"],
        factories.reading_payload("2026-08-03T05:00:00.000Z", 4.0),
        COORDINATOR_HEADERS,
    )

    validate_error(before_window, ERR_READING_OUTSIDE_SHIPMENT_WINDOW, 422)

    no_baseline = pinned_api.dispatch_shipment(
        shipment["id"],
        factories.dispatch_payload("2026-08-03T10:00:00.000Z"),
        COORDINATOR_HEADERS,
    )

    validate_error(no_baseline, ERR_NO_TEMPERATURE_BASELINE, 422)

    baseline = pinned_api.create_temperature_reading(
        shipment["id"], factories.reading_payload(T_NOW, 4.0), COORDINATOR_HEADERS
    )
    reading = validate_success(baseline, 201)
    assert_instant_equals(reading["recorded_at"], T_NOW, "baseline recorded_at")

    dispatched = validate_success(
        pinned_api.dispatch_shipment(
            shipment["id"],
            factories.dispatch_payload("2026-08-03T10:00:00.000Z"),
            COORDINATOR_HEADERS,
        ),
        200,
    )

    assert dispatched["status"] == "IN_TRANSIT"
    in_transit = fixtures.read_tissue(pinned_api, tissue_id)
    assert_dimensions(in_transit, "ISSUED", "IN_TRANSIT", "after dispatch")
    assert in_transit["issue_count"] == 1

    premature_implant = pinned_api.implant_tissue(
        tissue_id, None, make_surgeon_headers(booking.surgeon_id)
    )

    validate_error(premature_implant, ERR_TISSUE_CUSTODY_INVALID, 409)

    premature_report = pinned_api.create_adverse_reaction_report(
        factories.report_payload(
            tissue_id,
            booking.surgeon_id,
            reaction_type="REJECTION",
            severity="MINOR",
            narrative="Filed before the graft was ever confirmed.",
        ),
        make_surgeon_headers(booking.surgeon_id),
    )

    validate_error(premature_report, ERR_REPORT_TISSUE_NOT_IMPLANTED_BY_SURGEON, 422)

    bad_reissue = pinned_api.create_shipment(
        factories.shipment_payload(
            allocation["id"], "AIR", replaces_shipment_id=shipment["id"]
        ),
        COORDINATOR_HEADERS,
    )

    validate_error(bad_reissue, ERR_INVALID_REISSUE_SOURCE, 422)


def test_adjudicating_an_already_dismissed_report_twice_yields_err_report_state_invalid(
    pinned_api,
):
    """
    Both adjudicated values are terminal, so neither a repeated dismissal nor a reversal to
    substantiation is accepted; the first note survives and no lookback was ever opened.

    PRD 2.7: "An `AdverseReactionReport`'s `status` runs over `SUBMITTED`, `SUBSTANTIATED` and
    `UNSUBSTANTIATED`, starting at `SUBMITTED`, with both adjudicated values terminal."

    PRD 3.9: "The report is created with `reported_at` stamped from the logical clock, `status`
    `SUBMITTED` and `adjudication_note` null."

    PRD 3.9: "The medical director adjudicates every submitted report exactly once. Dismissal
    records `adjudication_note` and moves the report to `UNSUBSTANTIATED`; nothing else in the
    system changes — no lookback is opened, no tissue is quarantined, and the surgeon's
    `substantiated_reaction_count` does not move."

    PRD 2.10: "The adverse-reaction report's `status` is `SUBMITTED` — otherwise
    `ERR_REPORT_STATE_INVALID` (409). Applies to substantiation and dismissal."

    PRD 3.8: "It is `PASS` when `temp_excursion_minutes_over` is exactly 0."

    PRD 3.8: "On success `disposition_status` moves `ISSUED → IMPLANTED`, which is terminal,
    while `custody_status` **remains** `AT_SURGEON` — the tissue is in the patient and the bank
    never gets it back, but dimension B does not move."

    Design: Corner/errors/adjudicating_an_already_dismissed_report_twice_yields_err_report_state_invalid
    """
    chain = fixtures.tissue_chain(
        pinned_api,
        donor_code="D-2846-X13",
        donor_kwargs={"body_cooled_at": "2026-08-03T03:00:00.000Z", "age_years": 52},
        evaluation_technician_name="Nils Abadi",
    )
    tissue_id = chain["tissue_ids"][0]
    booking = fixtures.surgeon_with_request(pinned_api, "Dr Imani Rho", "CTR-01", "PK")
    delivery = fixtures.implanted_tissue(
        pinned_api, tissue_id, booking.request_id, booking.surgeon_id
    )
    assert delivery.shipment["integrity_verdict"] == "PASS"
    assert delivery.shipment["temp_excursion_minutes_over"] == 0
    assert fixtures.read_tissue(pinned_api, tissue_id)["disposition_status"] == "IMPLANTED"

    report = fixtures.create_report(
        pinned_api,
        tissue_id,
        booking.surgeon_id,
        reaction_type="PRIMARY_GRAFT_FAILURE",
        severity="SERIOUS",
        narrative="Graft never cleared; suspected primary failure.",
    )
    assert report["status"] == "SUBMITTED"
    assert report["adjudication_note"] is None
    dismissed = fixtures.dismiss(
        pinned_api, report["id"], "Consistent with recipient surgical technique."
    )
    assert dismissed["status"] == "UNSUBSTANTIATED"
    assert dismissed["version"] == 2

    replayed = pinned_api.dismiss_report(
        report["id"],
        factories.adjudication_payload("Second dismissal attempt."),
        MEDICAL_DIRECTOR_HEADERS,
    )
    reversed_verdict = pinned_api.substantiate_report(
        report["id"],
        factories.adjudication_payload("Reversal attempt after dismissal."),
        MEDICAL_DIRECTOR_HEADERS,
    )

    validate_error(replayed, ERR_REPORT_STATE_INVALID, 409)
    validate_error(reversed_verdict, ERR_REPORT_STATE_INVALID, 409)
    reread = get_success_data(
        pinned_api.get_adverse_reaction_report(report["id"], MEDICAL_DIRECTOR_HEADERS)
    )
    assert reread["status"] == "UNSUBSTANTIATED"
    assert reread["version"] == 2
    assert reread["adjudication_note"] == "Consistent with recipient surgical technique."
    assert (
        total_count_of(
            pinned_api.list_lookback_investigations(
                MEDICAL_DIRECTOR_HEADERS, donor_id=chain["donor_id"]
            )
        )
        == 0
    )
    assert (
        fixtures.read_surgeon(pinned_api, booking.surgeon_id)[
            "substantiated_reaction_count"
        ]
        == 0
    )


def test_a_third_dispatch_of_a_twice_returned_tissue_yields_err_reissue_limit_reached(
    pinned_api,
):
    """
    Two completed out-and-back cycles raise reissue_generation to 2 and issue_count to 2, and the
    ceiling then closes the cycle at the earliest gated operation — the manual allocation — so no
    third shipment is ever created and neither counter moves.

    PRD 3.7: "The tissue's `issue_count` increases by 1 — this is the only place it ever moves —
    and the `version` of the shipment and of the tissue each increase by 1."

    PRD 3.8: "In every case the `custody_status` moves `AT_SURGEON → RETURNED_TO_BANK`, the
    delivering shipment moves `DELIVERED → RETURNED`, `reissue_generation` increases by 1, the
    allocation moves `CONFIRMED → RELEASED` with its `cancel_reason` set to the literal
    `UNUSED_TISSUE_RETURNED`, and its request moves `ALLOCATED → OPEN` with its priority
    recomputed."

    PRD 3.8: "When the delivering shipment's `integrity_verdict` is `PASS` **and** the tissue's
    `expires_at` is strictly later than the current logical instant, `disposition_status` moves
    `ISSUED → ELIGIBLE` and the cornea rejoins the allocatable pool."

    PRD 3.8: "A tissue in `custody_status` `RETURNED_TO_BANK` and `disposition_status` `ELIGIBLE`
    may be allocated again, shipped under a new shipment whose `replaces_shipment_id` names the
    `RETURNED` shipment, and dispatched, which moves custody `RETURNED_TO_BANK → IN_TRANSIT` and
    disposition `RESERVED → ISSUED` again."

    PRD 3.8: "The `reissue_generation` counter is the hard limit on this cycle: **a tissue whose
    `reissue_generation` has reached 2 can never be allocated or dispatched again**, and both
    attempts are refused with `ERR_REISSUE_LIMIT_REACHED`."

    PRD 3.8: "Since the counter starts at 0 and rises by 1 on each completed return, a cornea may
    be sent out at most three times in total — an initial issue and two re-issues — and its
    `issue_count`, which counts dispatches rather than returns, records how many of those actually
    happened."

    PRD 2.10: "The tissue's `reissue_generation` is at most 1 — otherwise
    `ERR_REISSUE_LIMIT_REACHED` (409). Applies to manual allocation and shipment dispatch."

    Design: Corner/errors/a_third_dispatch_of_a_twice_returned_tissue_yields_err_reissue_limit_reached
    """
    chain = fixtures.tissue_chain(
        pinned_api,
        donor_code="D-2846-X14",
        donor_kwargs={"body_cooled_at": "2026-08-03T03:00:00.000Z", "age_years": 52},
        evaluation_technician_name="Nils Abadi",
    )
    tissue_id = chain["tissue_ids"][0]
    fresh = fixtures.read_tissue(pinned_api, tissue_id)
    assert fresh["reissue_generation"] == 0
    assert fresh["issue_count"] == 0
    booking = fixtures.surgeon_with_request(pinned_api, "Dr Imani Rho", "CTR-01", "PK")

    first = fixtures.returned_tissue_chain(
        pinned_api, tissue_id, booking.request_id, booking.surgeon_id
    )
    assert first.shipment["integrity_verdict"] == "PASS"
    after_first = fixtures.read_tissue(pinned_api, tissue_id)
    assert after_first["reissue_generation"] == 1
    assert after_first["issue_count"] == 1
    assert_dimensions(
        after_first, "ELIGIBLE", "RETURNED_TO_BANK", "after the first return"
    )

    second = fixtures.returned_tissue_chain(
        pinned_api,
        tissue_id,
        booking.request_id,
        booking.surgeon_id,
        return_reason="SURGERY_CANCELLED",
        carrier="AIR",
        replaces_shipment_id=first.shipment_id,
        baseline_at="2026-08-03T12:30:00.000Z",
        shipped_at="2026-08-03T13:00:00.000Z",
        readings=(("2026-08-03T13:00:00.000Z", 4.0),),
        delivered_at="2026-08-03T14:00:00.000Z",
    )
    assert second.shipment["status"] == "DELIVERED"
    assert second.shipment["integrity_verdict"] == "PASS"
    after_second = fixtures.read_tissue(pinned_api, tissue_id)
    assert after_second["reissue_generation"] == 2
    assert after_second["issue_count"] == 2
    assert_dimensions(
        after_second, "ELIGIBLE", "RETURNED_TO_BANK", "after the second return"
    )

    third = pinned_api.create_allocation(
        factories.allocation_payload(tissue_id, booking.request_id), COORDINATOR_HEADERS
    )

    validate_error(third, ERR_REISSUE_LIMIT_REACHED, 409)
    final = fixtures.read_tissue(pinned_api, tissue_id)
    assert_dimensions(
        final, "ELIGIBLE", "RETURNED_TO_BANK", "after the refused third allocation"
    )
    assert final["reissue_generation"] == 2
    assert final["issue_count"] == 2
    allocations = fixtures.allocations_for_tissue(pinned_api, tissue_id)
    assert len(allocations) == 2
    assert [row["status"] for row in allocations] == ["RELEASED", "RELEASED"]
