"""
Error-catalogue breadth: every declared HTTP status is reachable in one error
envelope, the shape gate outranks path resolution, and the one shared state rule
still names the entity that refused.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    assert_error_envelope,
    assert_vial_counters,
    validate_list,
)
from test_helpers import factories as f
from test_helpers.test_users import (
    billing_headers,
    headers_omitting,
    specialist_headers,
    tech_headers,
)

# Syntactically valid identifiers that resolve to no row.
UNKNOWN_LOT_ID = "bbbbbbbb-0000-4000-8000-00000000000f"
UNRESOLVED_LOT_ID = "cccccccc-0000-4000-8000-000000000001"


def _assert_single_error_envelope(response, expected_error_id):
    """Assert the response is one error envelope naming exactly this error."""
    data = assert_error_envelope(response)
    assert set(data.keys()) == {"error_id", "message"}, (
        f"An error body must carry exactly error_id and message; got {sorted(data.keys())}"
    )
    assert data["error_id"] == expected_error_id.value
    assert data["message"].strip()


def test_each_declared_status_is_reachable_and_arrives_as_one_error_envelope(breadth, tech):
    """
    Seven requests walk the 400, 401, 403, 404, 409, 412 and 422 rows of the error
    catalogue, each answering with a single error envelope and changing nothing.

    Every status in the run is declared by the rule that produces it.  The shape gate
    is 400 — "pagination values inside their bounds (`limit` from 1 to 100 inclusive,
    `offset` at least 0) — otherwise `ERR_INVALID_REQUEST` (400)".  Authentication is
    401: "Every request must carry both `X-User-ID` and `X-User-Role`. If either
    header is absent, or present but empty, the request is rejected with
    `ERR_MISSING_AUTH_HEADERS` (HTTP 401) before anything else about the request is
    examined."  Authorisation is 403: "If the role is recognised but the endpoint does
    not list it among its authorised roles, the rejection is `ERR_ROLE_NOT_PERMITTED`
    (HTTP 403)."  Path resolution is 404 — "Every identifier in the URL path resolves
    to an existing row, validated left to right — otherwise the 404 belonging to the
    entity that failed to resolve" — while the lot key is a 409: the `lot_number` is
    "unique within that drug", and a repeat is `ERR_DUPLICATE_LOT_NUMBER`.  The
    concurrency guard is 412: "If `expected_treatment_plan_version` does not equal the
    plan's current `version`, the create is rejected with `ERR_STALE_PLAN_VERSION`
    (HTTP 412), and the rejection happens before any vial is reserved, so no inventory
    is disturbed by a stale request."  The dose gate is 422: "the dose must be
    physically possible: strictly greater than zero and no greater than the effective
    drug's `vial_fill_ml`, either violation being `ERR_DOSE_EXCEEDS_VIAL_FILL` (HTTP
    422)."  Each answer is one envelope: "`response_type`" of `"error"` with `data`
    holding "The `error_id` ... a unique, machine-readable string that identifies the
    specific error" and "The `message` ... a human-readable explanation of what went
    wrong".

    Design: Corner/errors/corner_each_error_family_returns_its_declared_http_status_in_one_error_envelope
    """
    encounter = breadth.enc_np
    lot = breadth.lot_ref
    drug = breadth.drug_ref
    injector = specialist_headers(breadth.cl1["id"])

    malformed = breadth.api.list_drug_lots(tech, f.page_params(limit=0, drug_id=drug["id"]))
    validate_error(malformed, ApiErrorId.ERR_INVALID_REQUEST, 400)
    _assert_single_error_envelope(malformed, ApiErrorId.ERR_INVALID_REQUEST)

    unauthenticated = breadth.api.get_drug_lot(
        lot["id"], headers_omitting(tech_headers(), "X-User-Role")
    )
    validate_error(unauthenticated, ApiErrorId.ERR_MISSING_AUTH_HEADERS, 401)
    _assert_single_error_envelope(unauthenticated, ApiErrorId.ERR_MISSING_AUTH_HEADERS)

    wrong_role = breadth.api.quarantine_drug_lot(
        lot["id"],
        f.quarantine_payload(quarantine_reason="Attempted by the wrong role"),
        billing_headers(),
    )
    validate_error(wrong_role, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)
    _assert_single_error_envelope(wrong_role, ApiErrorId.ERR_ROLE_NOT_PERMITTED)

    unresolved = breadth.api.get_drug_lot(UNKNOWN_LOT_ID, tech)
    validate_error(unresolved, ApiErrorId.ERR_LOT_NOT_FOUND, 404)
    _assert_single_error_envelope(unresolved, ApiErrorId.ERR_LOT_NOT_FOUND)

    duplicate = breadth.api.create_drug_lot(
        f.lot_payload(
            drug_id=drug["id"],
            lot_number="RX-9001",
            expiration_date="2027-12-31T00:00:00Z",
            received_date="2026-07-05T00:00:00Z",
            unit_acquisition_cost_cents=130000,
            vials_received=1,
        ),
        tech,
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_LOT_NUMBER, 409)
    _assert_single_error_envelope(duplicate, ApiErrorId.ERR_DUPLICATE_LOT_NUMBER)

    stale = breadth.api.create_injection_encounter(
        f.encounter_payload(
            treatment_plan_id=breadth.plan_np["id"],
            imaging_study_id=breadth.img_np["id"],
            encounter_datetime="2026-08-01T10:00:00Z",
            expected_treatment_plan_version=breadth.plan_np["version"],
        ),
        injector,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_PLAN_VERSION, 412)
    _assert_single_error_envelope(stale, ApiErrorId.ERR_STALE_PLAN_VERSION)

    overdose = breadth.api.document_injection_encounter(
        encounter["id"],
        f.document_payload(administered_dose_ml=0.9, post_injection_iop_mmhg=16),
        injector,
    )
    validate_error(overdose, ApiErrorId.ERR_DOSE_EXCEEDS_VIAL_FILL, 422)
    _assert_single_error_envelope(overdose, ApiErrorId.ERR_DOSE_EXCEEDS_VIAL_FILL)

    settled_lot = breadth.read_lot(lot["id"])
    assert_vial_counters(
        settled_lot,
        vials_on_hand=4,
        vials_reserved=1,
        vials_administered=0,
        vials_quarantined=0,
    )
    assert settled_lot["status"] == "AVAILABLE"
    assert breadth.read_encounter(encounter["id"])["status"] == "DRAFT"


def test_a_malformed_query_outranks_the_unresolved_identifier_in_the_same_url(breadth, tech):
    """
    The same URL answers 400 while its query string is illegal and 404 once it is
    legal, so the shape gate is genuinely ahead of path resolution.

    The precedence list puts them in that order and forbids reporting the later one:
    step 5 is "The request body and query string carry every required field, each with
    the declared type, a recognised enum member, a value inside its numeric range ...
    — otherwise `ERR_INVALID_REQUEST` (400)", step 6 is "Every identifier in the URL
    path resolves to an existing row, validated left to right — otherwise the 404
    belonging to the entity that failed to resolve", and the rule over both is that
    "the response must carry the error of the *first* violated rule in the order
    below, and evaluation stops there ... an implementation that reports a later error
    while an earlier one also applies is wrong, even though both conditions hold."
    The parameter under test is required and closed: the caller must be "supplying a
    `basis` of either `CARRYING` or `EXPIRATION`".

    Design: Corner/errors/corner_request_shape_is_judged_before_the_ids_in_the_path_are_resolved
    """
    breadth.drug_ref

    missing_basis = breadth.api.get_drug_lot_exposure(UNRESOLVED_LOT_ID, tech)
    validate_error(missing_basis, ApiErrorId.ERR_INVALID_REQUEST, 400)

    bad_basis = breadth.api.get_drug_lot_exposure(
        UNRESOLVED_LOT_ID, tech, f.exposure_params(basis="NOT_A_BASIS")
    )
    validate_error(bad_basis, ApiErrorId.ERR_INVALID_REQUEST, 400)

    well_formed = breadth.api.get_drug_lot_exposure(
        UNRESOLVED_LOT_ID, tech, f.exposure_params(basis="CARRYING")
    )
    validate_error(well_formed, ApiErrorId.ERR_LOT_NOT_FOUND, 404)


def test_one_state_rule_fans_out_into_five_entity_specific_refusals(breadth, billing, compliance):
    """
    Resuming a draft plan, deciding an unsubmitted authorization, billing an
    unattested encounter, releasing an unquarantined lot and re-approving an active
    enrollment are all refused by the same rule, each naming its own entity.

    One precedence step covers all five: "The target resource is in a state the
    requested transition allows — otherwise the state error belonging to that
    resource: `ERR_PLAN_NOT_TREATABLE` or `ERR_PLAN_STATE_INVALID`,
    `ERR_AUTHORIZATION_STATE_INVALID`, `ERR_ENCOUNTER_STATE_INVALID`,
    `ERR_CLAIM_LINE_STATE_INVALID`, `ERR_LOT_STATE_INVALID`,
    `ERR_RECALL_STATE_INVALID`, `ERR_NOTIFICATION_STATE_INVALID`,
    `ERR_ENROLLMENT_STATE_INVALID`, `ERR_ADVERSE_EVENT_STATE_INVALID` or
    `ERR_VIAL_STATE_INVALID`, each HTTP 409."  Each refusal has its own sentence
    behind it: "resumption of a plan that is not `SUSPENDED`" is
    `ERR_PLAN_STATE_INVALID`; a decision "is accepted only while the authorization
    sits in `SUBMITTED` or `APPEALED`"; "the encounter must be `ATTESTED` — an
    unattested encounter cannot be billed, and the attempt is
    `ERR_ENCOUNTER_STATE_INVALID` (HTTP 409)"; release requires that "The lot must be
    `QUARANTINED`"; and "Approving anything that is not `PENDING` ... is
    `ERR_ENROLLMENT_STATE_INVALID` (HTTP 409)".  The starting states are equally
    declared: "A new plan is born in `DRAFT`", "The new authorization begins in
    `DRAFT`", "A lot begins in `AVAILABLE`", and an enrollment "is born `PENDING`"
    whose "Approval moves `PENDING → ACTIVE`".

    Design: Corner/errors/corner_the_shared_state_gate_still_names_the_entity_that_refused
    """
    documented = breadth.enc_np_documented
    lot = breadth.lot_ref
    injector = specialist_headers(breadth.cl1["id"])

    fellow_eye = breadth.plan(
        clinician_id=breadth.cl1["id"],
        patient_id=breadth.pt_np["id"],
        drug_id=breadth.drug_ref["id"],
        eye="OS",
        loading_doses_required=3,
    )
    assert fellow_eye["status"] == "DRAFT"

    authorization = breadth.authorization(
        treatment_plan_id=breadth.plan_np["id"],
        expected_treatment_plan_version=breadth.read_plan(breadth.plan_np["id"])["version"],
    )
    assert authorization["status"] == "DRAFT"

    enrollment = breadth.enrollment(
        patient_id=breadth.pt_np["id"],
        program_type="INDEPENDENT_FOUNDATION",
        annual_benefit_cents=800000,
        per_encounter_cap_cents=150000,
        effective_date="2026-08-01T00:00:00Z",
        expiration_date="2027-07-31T00:00:00Z",
    )
    approved = breadth.approve_enrollment(enrollment["id"])
    assert approved["status"] == "ACTIVE"

    validate_error(
        breadth.api.resume_treatment_plan(fellow_eye["id"], {}, injector),
        ApiErrorId.ERR_PLAN_STATE_INVALID,
        409,
    )
    validate_error(
        breadth.api.decide_prior_authorization(
            authorization["id"],
            f.approval_decision_payload(
                auth_number="AUTH-9001",
                approved_injections=3,
                effective_date="2026-08-01T00:00:00Z",
            ),
            billing,
        ),
        ApiErrorId.ERR_AUTHORIZATION_STATE_INVALID,
        409,
    )
    validate_error(
        breadth.api.create_claim(
            f.claim_payload(injection_encounter_id=documented["id"]), billing
        ),
        ApiErrorId.ERR_ENCOUNTER_STATE_INVALID,
        409,
    )
    validate_error(
        breadth.api.release_drug_lot(lot["id"], {}, compliance),
        ApiErrorId.ERR_LOT_STATE_INVALID,
        409,
    )
    validate_error(
        breadth.api.approve_assistance_enrollment(enrollment["id"], {}, billing),
        ApiErrorId.ERR_ENROLLMENT_STATE_INVALID,
        409,
    )

    assert breadth.read_plan(fellow_eye["id"])["status"] == "DRAFT"
    assert breadth.read_authorization(authorization["id"])["status"] == "DRAFT"
    assert breadth.read_encounter(documented["id"])["status"] == "DOCUMENTED"
    assert breadth.read_lot(lot["id"])["status"] == "AVAILABLE"
    assert breadth.read_enrollment(enrollment["id"])["status"] == "ACTIVE"

    _, claim_meta = validate_list(breadth.api.list_claims(billing, f.page_params()))
    assert claim_meta["total_count"] == 0
