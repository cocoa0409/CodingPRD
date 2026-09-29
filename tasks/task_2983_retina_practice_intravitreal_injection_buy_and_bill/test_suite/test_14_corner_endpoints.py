"""
Endpoint-pattern breadth: the shared envelope, the pagination bounds, a bulk
action, a pure computed read, a two-parent link and a conditional action.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    assert_envelope_shape,
    assert_error_envelope,
    assert_instant_equals,
    assert_vial_counters,
    list_ids,
    validate_list,
)
from test_helpers import factories as f
from test_helpers.test_users import billing_headers, specialist_headers

# Syntactically valid identifiers that resolve to no row of any kind.
UNKNOWN_PAYER_ID = "00000000-0000-4000-8000-0000000000ff"
UNKNOWN_PLAN_ID = "00000000-0000-4000-8000-0000000000aa"
UNKNOWN_STUDY_ID = "00000000-0000-4000-8000-0000000000bb"

PAGINATION_META_KEYS = {"limit", "offset", "total_count", "has_more"}


def test_the_same_meta_block_carries_an_object_an_array_and_an_error(breadth, admin):
    """
    A create, a listing and a rejection differ only in `response_type` and in the
    shape of `data`; all three carry the same two mandatory `meta` fields.

    The PRD publishes one success envelope and one error envelope.  In both, "The
    `api_request_id` is a server-generated unique identifier for the request that
    starts with `req_`" and "The `api_request_timestamp` is a server-generated ISO
    8601 UTC timestamp with three fractional digits".  What varies is declared
    field by field: "The `response_type` is either \"object\" for a single resource
    or \"array\" for a list of resources", "The `data` field contains the resource
    object or an array of resource objects", and "Pagination-related fields in
    `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list
    endpoints" — while "Single-resource reads and write operations return a `meta`
    object without those four fields."  The error envelope is narrower still: "The
    `meta` object for error responses contains only `api_request_id` and
    `api_request_timestamp`", with `data` holding "The `error_id` ... a unique,
    machine-readable string that identifies the specific error" and "The `message`
    ... a human-readable explanation of what went wrong".

    Design: Corner/endpoints/corner_envelope_is_identical_across_object_array_and_error_responses
    """
    created_response = breadth.api.create_payer(
        f.payer_payload(
            name="Envelope Test Payer",
            payer_type="COMMERCIAL",
            coinsurance_rate=0.2,
            pa_required=True,
            biosimilar_preference="NONE",
            appeal_window_days=60,
        ),
        admin,
    )
    created = validate_success(created_response, 201)
    assert_envelope_shape(created_response, "object")
    assert created["version"] == 1
    assert_instant_equals(created["created_at"], breadth.CLOCK, "created_at")
    create_meta = created_response.json()["meta"]
    assert not PAGINATION_META_KEYS & set(create_meta), (
        f"A create response must carry no pagination fields; got {sorted(create_meta)}"
    )

    list_response = breadth.api.list_payers(billing_headers(), f.page_params(limit=10, offset=0))
    rows, meta = validate_list(list_response)
    assert_envelope_shape(list_response, "array")
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert rows[0]["name"] == "Envelope Test Payer"
    assert rows[0]["id"] == created["id"]

    error_response = breadth.api.get_payer(UNKNOWN_PAYER_ID, billing_headers())
    validate_error(error_response, ApiErrorId.ERR_PAYER_NOT_FOUND, 404)
    error_data = assert_error_envelope(error_response)
    assert set(error_data.keys()) == {"error_id", "message"}
    assert error_data["message"].strip()
    assert set(error_response.json()["meta"].keys()) == {
        "api_request_id",
        "api_request_timestamp",
    }

    for response in (created_response, list_response, error_response):
        body_meta = response.json()["meta"]
        assert body_meta["api_request_id"].startswith("req_")
        assert body_meta["api_request_timestamp"]


def test_the_pagination_range_is_closed_at_one_and_a_hundred_and_an_overshoot_is_empty(
    breadth, tech
):
    """
    Three lots paged with no parameters take the declared defaults; a limit of 0 or
    101 and a negative offset are all malformed; an offset past the end is an empty
    page rather than a 404.

    The PRD fixes both bounds and the failure mode: "`limit` controls page size: its
    default is 10, its minimum accepted value is 1 and its maximum accepted value is
    100. `offset` controls the starting position: its default is 0 and its minimum
    accepted value is 0. A `limit` below 1 or above 100, or a negative `offset`, is a
    malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400) rather
    than being silently clamped."  The precedence list says the same thing as step 5
    — "pagination values inside their bounds (`limit` from 1 to 100 inclusive,
    `offset` at least 0) — otherwise `ERR_INVALID_REQUEST` (400)".  What comes back
    on a valid page is equally fixed: "`limit` and `offset` echo the effective values
    used for the page, `total_count` reports how many rows matched the filter across
    all pages, and `has_more` is true when rows remain beyond the current page", in
    the declared order — "List results are ordered by `created_at` ascending unless
    the narrative for a specific listing says otherwise" — and lots "may be listed
    filtered on `drug_id` and `status`".

    Design: Corner/endpoints/corner_pagination_bounds_are_enforced_and_an_overshot_offset_returns_an_empty_page
    """
    drug = breadth.drug_ref
    first = breadth.lot_ref

    breadth.set_clock("2026-08-01T01:00:00Z")
    second = breadth.lot(
        drug_id=drug["id"],
        lot_number="RX-9101",
        expiration_date="2027-07-31T00:00:00Z",
        received_date="2026-07-02T00:00:00Z",
        unit_acquisition_cost_cents=131500,
        vials_received=1,
    )
    breadth.set_clock("2026-08-01T02:00:00Z")
    third = breadth.lot(
        drug_id=drug["id"],
        lot_number="RX-9102",
        expiration_date="2027-08-31T00:00:00Z",
        received_date="2026-07-03T00:00:00Z",
        unit_acquisition_cost_cents=131000,
        vials_received=1,
    )

    defaulted, default_meta = validate_list(
        breadth.api.list_drug_lots(tech, f.page_params(drug_id=drug["id"]))
    )
    assert default_meta["limit"] == 10
    assert default_meta["offset"] == 0
    assert default_meta["total_count"] == 3
    assert default_meta["has_more"] is False
    assert defaulted[0]["lot_number"] == "RX-9001"
    assert list_ids(defaulted) == [first["id"], second["id"], third["id"]]

    validate_error(
        breadth.api.list_drug_lots(tech, f.page_params(limit=0, drug_id=drug["id"])),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        breadth.api.list_drug_lots(tech, f.page_params(limit=101, drug_id=drug["id"])),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        breadth.api.list_drug_lots(tech, f.page_params(offset=-1, drug_id=drug["id"])),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )

    at_the_ceiling, ceiling_meta = validate_list(
        breadth.api.list_drug_lots(tech, f.page_params(limit=100, drug_id=drug["id"]))
    )
    assert len(at_the_ceiling) == 3
    assert ceiling_meta["limit"] == 100
    assert at_the_ceiling[0]["lot_number"] == "RX-9001"

    overshot_response = breadth.api.list_drug_lots(
        tech, f.page_params(limit=2, offset=50, drug_id=drug["id"])
    )
    overshot, overshot_meta = validate_list(overshot_response)
    assert overshot_response.status_code == 200
    assert overshot == []
    assert overshot_meta["total_count"] == 3
    assert overshot_meta["has_more"] is False
    assert overshot_meta["offset"] == 50


def test_the_sweep_visits_every_lot_and_expires_only_the_lapsed_one(breadth, tech):
    """
    One sweep over two lots accrues carrying cost on both, expires only the lot
    already past its date along with its in-stock vials, and a second sweep at the
    same clock expires nothing further.

    The PRD walks the sweep in order: "Every lot is visited. For each visited lot the
    carrying accrual described above is recomputed and *persisted* into
    `carrying_cost_accrued_cents` — this endpoint is the only writer of that field, so
    it is stale by exactly as much time as has passed since the last sweep — and
    `last_swept_at` is set to the logical clock. Any lot whose status is
    `AVAILABLE` and whose `expiration_date` is at or before the logical clock moves
    `AVAILABLE → EXPIRED`, every vial of that lot still in `IN_STOCK` moves to
    `EXPIRED`, `vials_on_hand` and `vials_expired` are recomputed, and the lot's
    `version` advances by 1."  The summary it answers with is named field by field:
    "`lots_swept` counts the lots visited, `lots_expired` counts the lots that moved
    to `EXPIRED` on this run, `vials_expired` counts the vials that moved to
    `EXPIRED` on this run, `carrying_cost_accrued_cents_total` sums
    `carrying_cost_accrued_cents` across the lots swept, and `swept_at` reports the
    logical-clock instant of the sweep."  Each accrual follows §3.5: "`days_held` is
    the whole number of days from the lot's `received_date` to the logical clock,
    truncated downward. Only vials in `IN_STOCK` are counted ... multiplying it by
    `unit_acquisition_cost_cents` gives `unconsumed_value_cents`. The accrual itself
    takes that same unconsumed value, applies the practice's annual financing rate of
    2000 basis points ... multiplies by `days_held`, divides by a 365-day year, and
    rounds the result half up to whole cents exactly once at the very end."  Both
    lots were received on 2026-07-01, so both are held 31 whole days: the surviving
    lot accrues 5 x 132000 x 0.2 x 31 / 365 = 11211, and the lapsed lot — still
    holding two `IN_STOCK` vials when its accrual is taken — accrues 2 x 100000 x 0.2
    x 31 / 365 = 3397, for a total of 14608.  On the second run those two vials are
    `EXPIRED`, so the lapsed lot's recomputed accrual is 0 and the total is 11211.

    Design: Corner/endpoints/corner_expiration_sweep_is_a_bulk_action_whose_totals_are_order_sensitive_and_idempotent
    """
    survivor = breadth.lot_ref
    lapsed = breadth.lot(
        drug_id=breadth.drug_ref["id"],
        lot_number="RX-9200",
        expiration_date="2026-07-15T00:00:00Z",
        received_date="2026-07-01T00:00:00Z",
        unit_acquisition_cost_cents=100000,
        vials_received=2,
    )
    assert lapsed["status"] == "AVAILABLE"

    first_sweep = validate_success(breadth.api.run_expiration_sweep({}, tech), 200)
    assert first_sweep["lots_swept"] == 2
    assert first_sweep["lots_expired"] == 1
    assert first_sweep["vials_expired"] == 2
    assert first_sweep["carrying_cost_accrued_cents_total"] == 14608
    assert_instant_equals(first_sweep["swept_at"], breadth.CLOCK, "swept_at")

    expired_lot = breadth.read_lot(lapsed["id"])
    assert expired_lot["status"] == "EXPIRED"
    assert expired_lot["carrying_cost_accrued_cents"] == 3397
    assert_instant_equals(expired_lot["last_swept_at"], breadth.CLOCK, "last_swept_at")
    assert_vial_counters(expired_lot, vials_on_hand=0, vials_expired=2)
    assert {vial["status"] for vial in breadth.lot_vials(lapsed["id"])} == {"EXPIRED"}

    survived = breadth.read_lot(survivor["id"])
    assert survived["status"] == "AVAILABLE"
    assert survived["carrying_cost_accrued_cents"] == 11211
    assert_vial_counters(survived, vials_on_hand=5, vials_expired=0)
    assert {vial["status"] for vial in breadth.lot_vials(survivor["id"])} == {"IN_STOCK"}

    second_sweep = validate_success(breadth.api.run_expiration_sweep({}, tech), 200)
    assert second_sweep["lots_swept"] == 2
    assert second_sweep["lots_expired"] == 0
    assert second_sweep["vials_expired"] == 0
    assert second_sweep["carrying_cost_accrued_cents_total"] == 11211

    assert breadth.read_lot(lapsed["id"])["status"] == "EXPIRED"
    assert breadth.read_lot(survivor["id"])["carrying_cost_accrued_cents"] == 11211


def test_the_exposure_read_needs_a_basis_a_permitted_role_and_persists_nothing(
    breadth, tech, billing
):
    """
    The exposure endpoint refuses a missing or unrecognised `basis` and the
    specialist entirely, answers twice with identical numbers, and never writes the
    lot's accrued figure.

    The PRD scopes the read and states its purity: "A `PracticeAdmin`, `PharmacyTech`
    or `BillingSpecialist` may ask a lot what it is costing the practice, supplying a
    `basis` of either `CARRYING` or `EXPIRATION`. The read persists nothing. Its
    response echoes the `drug_lot_id` and the `basis` and reports `days_held`,
    `unconsumed_vials`, `unconsumed_value_cents`, `exposure_cents`,
    `projected_burn_vials` and `at_risk_vials`."  A value outside that pair fails the
    payload gate, which requires "a recognised enum member ... — otherwise
    `ERR_INVALID_REQUEST` (400)", and the role check is ahead of it in the
    precedence: "The role is authorised for this endpoint — otherwise
    `ERR_ROLE_NOT_PERMITTED` (403)."  The arithmetic is pinned: "`days_held` is the
    whole number of days from the lot's `received_date` to the logical clock,
    truncated downward. Only vials in `IN_STOCK` are counted ... that count is
    reported as `unconsumed_vials`, and multiplying it by
    `unit_acquisition_cost_cents` gives `unconsumed_value_cents`. The accrual itself
    takes that same unconsumed value, applies the practice's annual financing rate of
    2000 basis points ... multiplies by `days_held`, divides by a 365-day year, and
    rounds the result half up to whole cents exactly once at the very end ... On this
    basis `projected_burn_vials` and `at_risk_vials` are both reported as 0."  Five
    vials at 132000 held 31 days give 660000 x 0.2 x 31 / 365 = 11211.  Nothing moves
    on the lot because "A lot begins in `AVAILABLE` with ... `carrying_cost_accrued_cents`
    at 0" and the sweep "is the only writer of that field".

    Design: Corner/endpoints/corner_exposure_read_requires_a_basis_is_role_restricted_and_persists_nothing
    """
    lot = breadth.lot_ref
    assert breadth.read_lot(lot["id"])["carrying_cost_accrued_cents"] == 0

    validate_error(
        breadth.api.get_drug_lot_exposure(lot["id"], tech),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        breadth.api.get_drug_lot_exposure(lot["id"], tech, f.exposure_params(basis="CARYING")),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        breadth.api.get_drug_lot_exposure(
            lot["id"],
            specialist_headers(breadth.cl1["id"]),
            f.exposure_params(basis="CARRYING"),
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        403,
    )

    first = validate_success(
        breadth.api.get_drug_lot_exposure(lot["id"], billing, f.exposure_params(basis="CARRYING")),
        200,
    )
    assert first["drug_lot_id"] == lot["id"]
    assert first["basis"] == "CARRYING"
    assert first["days_held"] == 31
    assert first["unconsumed_vials"] == 5
    assert first["unconsumed_value_cents"] == 660000
    assert first["exposure_cents"] == 11211
    assert first["projected_burn_vials"] == 0
    assert first["at_risk_vials"] == 0

    second = validate_success(
        breadth.api.get_drug_lot_exposure(lot["id"], tech, f.exposure_params(basis="CARRYING")),
        200,
    )
    assert second["exposure_cents"] == first["exposure_cents"]
    assert second["days_held"] == first["days_held"]
    assert second["unconsumed_value_cents"] == first["unconsumed_value_cents"]

    settled = breadth.read_lot(lot["id"])
    assert settled["carrying_cost_accrued_cents"] == 0
    assert settled["last_swept_at"] is None
    assert_vial_counters(settled, vials_on_hand=5)


def test_the_encounter_links_a_plan_and_a_study_and_checks_both_ends(breadth, tech):
    """
    Booking resolves the plan before the study, reports each unresolved parent with
    its own 404, refuses a study belonging to a different patient even when the eye
    letters agree, and reserves a vial only on the request that is accepted.

    The encounter is declared as a link between the two: the specialist supplies "the
    `treatment_plan_id` being treated, the `imaging_study_id` of the study that drove
    the treatment decision, the `encounter_datetime` ... and the
    `expected_treatment_plan_version` guard."  Body keys are resolved in that order —
    "Every foreign key supplied in the request body resolves to an existing row,
    validated in the order the fields are listed for that endpoint in §4's companion
    narrative — otherwise the same catalogue of 404s" — a catalogue that includes both
    `ERR_PLAN_NOT_FOUND` and `ERR_IMAGING_STUDY_NOT_FOUND`.  The eye rule matches on
    both coordinates at once: "It must belong to the plan's patient and its `eye` must
    equal the plan's `eye`, or the request is `ERR_IMAGING_EYE_MISMATCH` (HTTP 422)."
    Only the accepted booking touches inventory, where "the vial moves `IN_STOCK →
    RESERVED` with `reserved_for_encounter_id` naming this encounter".

    Design: Corner/endpoints/corner_encounter_create_links_two_parents_and_rejects_a_study_from_another_patient
    """
    breadth.pol_np_ref
    breadth.lot_ref
    study = breadth.img_np
    plan = breadth.plan_np_active
    injector = specialist_headers(breadth.cl1["id"])

    stranger = breadth.patient(
        mrn="MRN-2061",
        full_name="Priya Raman",
        payer_id=breadth.pay_np["id"],
        member_id="FOO-61",
        notification_channel="EMAIL",
        contact_point="priya.raman@example.test",
    )
    stranger_study = breadth.imaging(
        clinician_id=breadth.cl1["id"],
        patient_id=stranger["id"],
        eye="OD",
        study_datetime=breadth.CLOCK,
        central_subfield_thickness_um=430,
        intraretinal_fluid=True,
        subretinal_fluid=False,
        new_hemorrhage=False,
        va_letter_score=55,
    )

    validate_error(
        breadth.api.create_injection_encounter(
            f.encounter_payload(
                treatment_plan_id=UNKNOWN_PLAN_ID,
                imaging_study_id=UNKNOWN_STUDY_ID,
                encounter_datetime=breadth.ENCOUNTER_AT,
                expected_treatment_plan_version=plan["version"],
            ),
            injector,
        ),
        ApiErrorId.ERR_PLAN_NOT_FOUND,
        404,
    )
    validate_error(
        breadth.api.create_injection_encounter(
            f.encounter_payload(
                treatment_plan_id=plan["id"],
                imaging_study_id=UNKNOWN_STUDY_ID,
                encounter_datetime=breadth.ENCOUNTER_AT,
                expected_treatment_plan_version=plan["version"],
            ),
            injector,
        ),
        ApiErrorId.ERR_IMAGING_STUDY_NOT_FOUND,
        404,
    )
    validate_error(
        breadth.api.create_injection_encounter(
            f.encounter_payload(
                treatment_plan_id=plan["id"],
                imaging_study_id=stranger_study["id"],
                encounter_datetime=breadth.ENCOUNTER_AT,
                expected_treatment_plan_version=plan["version"],
            ),
            injector,
        ),
        ApiErrorId.ERR_IMAGING_EYE_MISMATCH,
        422,
    )

    assert_vial_counters(
        breadth.read_lot(breadth.lot_ref["id"]), vials_on_hand=5, vials_reserved=0
    )

    booked = validate_success(
        breadth.api.create_injection_encounter(
            f.encounter_payload(
                treatment_plan_id=plan["id"],
                imaging_study_id=study["id"],
                encounter_datetime=breadth.ENCOUNTER_AT,
                expected_treatment_plan_version=plan["version"],
            ),
            injector,
        ),
        201,
    )
    assert booked["treatment_plan_id"] == plan["id"]
    assert booked["imaging_study_id"] == study["id"]
    assert booked["patient_id"] == breadth.pt_np["id"]
    assert booked["status"] == "DRAFT"

    vial = breadth.read_vial(booked["vial_id"])
    assert vial["status"] == "RESERVED"
    assert vial["reserved_for_encounter_id"] == booked["id"]
    assert_vial_counters(
        breadth.read_lot(breadth.lot_ref["id"]), vials_on_hand=4, vials_reserved=1
    )

    _, meta = validate_list(breadth.api.list_vials(tech, f.page_params(status="RESERVED")))
    assert meta["total_count"] == 1


def test_a_claim_waits_for_the_attestation_not_for_the_documentation(breadth, billing):
    """
    Billing a merely documented encounter is refused and creates no claim; the very
    same call succeeds once a second clinician attests the wastage.

    The PRD makes attestation the condition: "A claim is created from a single input,
    `injection_encounter_id`, and the encounter must be `ATTESTED` — an unattested
    encounter cannot be billed, and the attempt is `ERR_ENCOUNTER_STATE_INVALID` (HTTP
    409)."  Attestation is the only thing that moves in between: "Attestation moves the
    encounter `DOCUMENTED → ATTESTED` and carries a single input,
    `attested_wasted_ml`", and "The attester must be a different clinician from the
    injector".  The claim's own opening figures follow: "Both status axes are born
    `PENDING`", "`drug_billed_cents` is the encounter's `administered_billing_units`
    multiplied by the policy's `drug_allowed_cents_per_billing_unit` ... the expected
    allowables at creation are: `drug_allowed_cents` equal to `drug_billed_cents`;
    `wastage_allowed_cents` equal to `wastage_billed_cents` when the policy's
    `wastage_reimbursed` is true and exactly 0 when it is false; and
    `admin_allowed_cents` equal to `admin_billed_cents`", with "`total_allowed_cents`
    is `drug_allowed_cents` plus `wastage_allowed_cents` plus `admin_allowed_cents`" —
    2 units at 14000 plus a discard this policy does not reimburse plus 10000 for the
    administration, so 38000.  Creating the claim is what advances the encounter:
    "`ATTESTED → BILLED` happens when a claim is created for the encounter, and
    nothing on the encounter changes beyond its status and `updated_at`."

    Design: Corner/endpoints/corner_claim_creation_is_a_conditional_action_gated_on_attestation
    """
    documented = breadth.enc_np_documented
    assert documented["status"] == "DOCUMENTED"

    validate_error(
        breadth.api.create_claim(
            f.claim_payload(injection_encounter_id=documented["id"]), billing
        ),
        ApiErrorId.ERR_ENCOUNTER_STATE_INVALID,
        409,
    )
    _, empty = validate_list(breadth.api.list_claims(billing, f.page_params()))
    assert empty["total_count"] == 0
    assert breadth.read_encounter(documented["id"])["status"] == "DOCUMENTED"

    attested = validate_success(
        breadth.api.attest_wastage(
            documented["id"],
            f.attest_payload(attested_wasted_ml=0.21),
            specialist_headers(breadth.cl2["id"]),
        ),
        200,
    )
    assert attested["status"] == "ATTESTED"

    claim = validate_success(
        breadth.api.create_claim(
            f.claim_payload(injection_encounter_id=documented["id"]), billing
        ),
        201,
    )
    assert claim["total_allowed_cents"] == 38000
    assert claim["drug_allowed_cents"] == 28000
    assert claim["wastage_allowed_cents"] == 0
    assert claim["admin_allowed_cents"] == 10000
    assert claim["drug_line_status"] == "PENDING"
    assert claim["admin_line_status"] == "PENDING"

    billed = breadth.read_encounter(documented["id"])
    assert billed["status"] == "BILLED"
    assert billed["total_billed_billing_units"] == 10

    vial = breadth.read_vial(documented["vial_id"])
    assert vial["status"] == "ADMINISTERED"
