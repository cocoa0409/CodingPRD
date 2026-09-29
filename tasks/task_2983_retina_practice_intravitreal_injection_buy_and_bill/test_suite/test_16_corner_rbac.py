"""
Role-based access breadth: the write surface is partitioned with no overlap, the
read surface is shared but not uniformly, the role gate runs ahead of the
two-person identity rules, and only two roles are entity-backed.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiErrorId, assert_instant_equals, validate_list
from test_helpers import factories as f
from test_helpers.test_users import (
    ADMIN_USER_ID,
    COMPLIANCE_USER_ID,
    TECH_USER_ID_ALT,
    admin_headers,
    billing_headers,
    compliance_headers,
    patient_headers,
    specialist_headers,
    tech_headers,
)


def test_every_write_family_belongs_to_exactly_one_role(breadth, admin, tech, billing):
    """
    Reference data, clinical writes, inventory receipt, assistance money, recall
    initiation and the clock each refuse every role but their owner, and the
    identical payload succeeds as soon as the owning role sends it.

    The PRD partitions the write surface role by role.  "A `PracticeAdmin` is the
    reference-data administrator and clock operator. This role exclusively creates
    payers, drugs, payer drug policies, patients and clinicians, suspends a clinician,
    and sets the logical clock."  "A `RetinaSpecialist` ... exclusively interprets
    imaging studies, opens and steers treatment plans ... A `RetinaSpecialist` may read
    every collection but may not perform any inventory, billing, assistance or recall
    write."  "A `PharmacyTech` is the buy-and-bill inventory custodian. This role
    exclusively receives drug lots, quarantines a lot, runs the inventory expiration
    sweep, and ships a recall return ... neither initiates nor closes a recall."  "A
    `BillingSpecialist` ... creates, approves and terminates assistance enrollments."
    "A `ComplianceOfficer` ... exclusively initiates a lot recall, sends its patient
    notifications, closes it ... It performs no clinical or billing write."  The
    refusal is the same in every case: "If the role is recognised but the endpoint does
    not list it among its authorised roles, the rejection is `ERR_ROLE_NOT_PERMITTED`
    (HTTP 403)", which the precedence list places at step 3 — "The role is authorised
    for this endpoint ... Applies to every endpoint."

    Design: Corner/rbac/corner_every_write_family_is_exclusive_to_exactly_one_role
    """
    breadth.pol_np_ref
    patient = breadth.pt_np
    clinician = breadth.cl1
    lot = breadth.lot_ref
    injector = specialist_headers(clinician["id"])

    study_payload = f.imaging_payload(
        patient_id=patient["id"],
        eye="OD",
        study_datetime="2026-08-01T00:00:00Z",
        central_subfield_thickness_um=400,
        intraretinal_fluid=True,
        subretinal_fluid=False,
        new_hemorrhage=False,
        va_letter_score=60,
    )
    lot_payload = f.lot_payload(
        drug_id=breadth.drug_ref["id"],
        lot_number="RX-9301",
        expiration_date="2027-10-31T00:00:00Z",
        received_date="2026-07-10T00:00:00Z",
        unit_acquisition_cost_cents=130500,
        vials_received=1,
    )
    enrollment_payload = f.enrollment_payload(
        patient_id=patient["id"],
        program_type="INDEPENDENT_FOUNDATION",
        annual_benefit_cents=800000,
        per_encounter_cap_cents=150000,
        effective_date="2026-08-01T00:00:00Z",
        expiration_date="2027-07-31T00:00:00Z",
    )

    validate_error(
        breadth.api.create_payer(
            f.payer_payload(
                name="Wrong Role Payer", payer_type="COMMERCIAL", coinsurance_rate=0.2
            ),
            tech,
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        breadth.api.create_imaging_study(study_payload, admin),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    study = validate_success(breadth.api.create_imaging_study(study_payload, injector), 201)
    assert study["interpreted_by_clinician_id"] == clinician["id"]

    validate_error(
        breadth.api.create_drug_lot(lot_payload, injector),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    received = validate_success(breadth.api.create_drug_lot(lot_payload, tech), 201)
    assert received["lot_number"] == "RX-9301"

    validate_error(
        breadth.api.create_assistance_enrollment(enrollment_payload, compliance_headers("U-CO-7")),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    enrolled = validate_success(
        breadth.api.create_assistance_enrollment(enrollment_payload, billing), 201
    )
    assert enrolled["status"] == "PENDING"

    validate_error(
        breadth.api.create_lot_recall(
            f.recall_payload(
                drug_lot_id=lot["id"], recall_class="CLASS_III", reason="Attempted by pharmacy"
            ),
            tech,
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    _, recall_meta = validate_list(breadth.api.list_lot_recalls(tech, f.page_params()))
    assert recall_meta["total_count"] == 0

    validate_error(
        breadth.api.set_clock({"current_utc": "2026-08-02T00:00:00Z"}, billing),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    still_parked = validate_success(
        breadth.api.create_payer(
            f.payer_payload(name="Clock Witness", payer_type="COMMERCIAL", coinsurance_rate=0.2),
            admin,
        ),
        201,
    )
    assert_instant_equals(still_parked["created_at"], breadth.CLOCK, "created_at")

    _, payer_meta = validate_list(breadth.api.list_payers(admin, f.page_params()))
    assert payer_meta["total_count"] == 2


def test_the_staff_roles_share_the_lot_read_but_not_its_economics(breadth, admin):
    """
    Two different staff roles read the same lot, the patient may not read inventory at
    all, the exposure computation is narrower than the lot it belongs to, and the
    patient's own notification collection is reachable and empty.

    The read surface is declared per role.  A `ComplianceOfficer` "may read
    everything", and both it and the `PracticeAdmin` appear on the lot read's authorised
    list, while "A `Patient` is a notified patient acting on their own recall
    notifications. This role's only write is acknowledging a recall notification. Its
    only reads are the recall-notification collection and a single recall notification.
    Every other endpoint in the API is denied to it."  The exposure read is narrower
    than its parent: only "A `PracticeAdmin`, `PharmacyTech` or `BillingSpecialist` may
    ask a lot what it is costing the practice".  Both refusals are step 3 — "The role is
    authorised for this endpoint — otherwise `ERR_ROLE_NOT_PERMITTED` (403)".  The
    admin's own answer follows the carrying formula, "applies the practice's annual
    financing rate of 2000 basis points ... multiplies by `days_held`, divides by a
    365-day year, and rounds the result half up to whole cents exactly once at the very
    end", which for five vials at 132000 held 31 days is 11211.  The patient's listing
    is scoped rather than blocked: "a patient may only touch `RecallNotification` rows
    whose `patient_id` equals their `X-User-ID`."

    Design: Corner/rbac/corner_read_access_is_shared_by_the_staff_roles_but_not_uniformly
    """
    breadth.pol_np_ref
    patient = breadth.pt_np
    lot = breadth.lot_ref

    by_admin = validate_success(breadth.api.get_drug_lot(lot["id"], admin), 200)
    by_officer = validate_success(
        breadth.api.get_drug_lot(lot["id"], compliance_headers("U-CO-8")), 200
    )
    assert by_admin["lot_number"] == "RX-9001"
    assert by_officer["lot_number"] == "RX-9001"

    validate_error(
        breadth.api.get_drug_lot(lot["id"], patient_headers(patient["id"])),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        breadth.api.get_drug_lot_exposure(
            lot["id"], compliance_headers("U-CO-8"), f.exposure_params(basis="CARRYING")
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        403,
    )

    permitted = validate_success(
        breadth.api.get_drug_lot_exposure(lot["id"], admin, f.exposure_params(basis="CARRYING")),
        200,
    )
    assert permitted["exposure_cents"] == 11211

    rows, meta = validate_list(
        breadth.api.list_recall_notifications(
            patient_headers(patient["id"]), f.page_params(patient_id=patient["id"])
        )
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_the_role_gate_runs_ahead_of_both_two_person_identity_rules(breadth, billing, tech):
    """
    A second signature from another role is a role refusal rather than a valid
    countersignature; the injector's own second signature is the identity refusal; a
    different clinician's is accepted; and closing a recall as the tech is refused on
    the role before the initiator comparison is ever reached.

    The precedence list orders the three gates: step 3 is "The role is authorised for
    this endpoint — otherwise `ERR_ROLE_NOT_PERMITTED` (403). Applies to every
    endpoint", step 9 is "The wastage attester is not the injecting clinician —
    otherwise `ERR_SEGREGATION_OF_DUTIES` (403). Applies to wastage attestation", and
    step 11 is "The closing operator's `X-User-ID` differs from the recall's
    `initiated_by_user_id` — otherwise `ERR_RECALL_CLOSER_CONFLICT` (403). Applies to
    recall closure."  Over all three sits the rule that "the response must carry the
    error of the *first* violated rule in the order below, and evaluation stops there."
    Who may sign is declared by remit: a `RetinaSpecialist` "performs their
    documentation, wastage attestation and voiding", a `BillingSpecialist` "performs no
    clinical or inventory write", and a `PharmacyTech` "neither initiates nor closes a
    recall".  The accepted signature is the second clinician's: "The attester must be a
    different clinician from the injector: an acting `X-User-ID` equal to the
    encounter's `clinician_id` is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)",
    and "On success the acting clinician's identifier is written to
    `attested_by_clinician_id`."

    Design: Corner/rbac/corner_role_and_identity_are_orthogonal_gates_on_the_same_second_person_rule
    """
    documented = breadth.enc_np_documented
    attest_body = f.attest_payload(attested_wasted_ml=0.21)

    validate_error(
        breadth.api.attest_wastage(documented["id"], attest_body, billing),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        breadth.api.attest_wastage(
            documented["id"], attest_body, specialist_headers(breadth.cl1["id"])
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    assert breadth.read_encounter(documented["id"])["status"] == "DOCUMENTED"

    attested = validate_success(
        breadth.api.attest_wastage(
            documented["id"], attest_body, specialist_headers(breadth.cl2["id"])
        ),
        200,
    )
    assert attested["status"] == "ATTESTED"
    assert attested["attested_by_clinician_id"] == breadth.cl2["id"]

    recall = breadth.recall(
        drug_lot_id=breadth.lot_ref["id"],
        recall_class="CLASS_III",
        reason="Label defect on the outer carton",
        user_id=COMPLIANCE_USER_ID,
    )
    assert recall["initiated_by_user_id"] == COMPLIANCE_USER_ID

    validate_error(
        breadth.api.close_lot_recall(
            recall["id"], f.recall_close_payload(closure_note="Attempted by pharmacy"), tech
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    assert breadth.read_recall(recall["id"])["status"] == "INITIATED"


def test_only_the_clinician_and_patient_identities_have_to_resolve(breadth):
    """
    A pharmacy tech acting as a free-text terminal name books a lot successfully,
    while a specialist carrying a real patient's id and a patient carrying a real
    clinician's id are both refused on identity.

    The PRD splits identity resolution in two.  For the entity-backed pair: "When
    `X-User-Role` is `RetinaSpecialist`, `X-User-ID` is the `id` of the acting
    `Clinician` ... When `X-User-Role` is `Patient`, `X-User-ID` is the `id` of the
    acting `Patient` row ... For both of these entity-backed roles the header value
    must resolve to an existing row; a `RetinaSpecialist` whose `X-User-ID` matches no
    `Clinician`, or a `Patient` whose `X-User-ID` matches no `Patient`, is rejected
    with `ERR_ACTING_IDENTITY_NOT_FOUND` (HTTP 403). This existence check runs on every
    endpoint whose authorised roles include `RetinaSpecialist` or `Patient`."  For the
    opaque four: "When `X-User-Role` is `PharmacyTech`, `BillingSpecialist`,
    `ComplianceOfficer` or `PracticeAdmin`, `X-User-ID` is an opaque operator
    identifier not tied to any persisted entity ... it never compares such an
    identifier to any entity's `id`, and it never requires the identifier to resolve to
    a row."  The check is step 4 of the precedence list, after the role name is known —
    "For the entity-backed roles, `X-User-ID` resolves to an existing row
    (`RetinaSpecialist` to a `Clinician`, `Patient` to a `Patient`) — otherwise
    `ERR_ACTING_IDENTITY_NOT_FOUND` (403)" — so neither failure is the 401 of a missing
    or unrecognised header.

    Design: Corner/rbac/corner_entity_backed_identities_must_resolve_while_opaque_identities_are_free_text
    """
    breadth.pol_np_ref
    patient = breadth.pt_np
    clinician = breadth.cl1

    opaque = validate_success(
        breadth.api.create_drug_lot(
            f.lot_payload(
                drug_id=breadth.drug_ref["id"],
                lot_number="RX-9401",
                expiration_date="2027-11-30T00:00:00Z",
                received_date="2026-07-12T00:00:00Z",
                unit_acquisition_cost_cents=129500,
                vials_received=2,
            ),
            tech_headers(TECH_USER_ID_ALT),
        ),
        201,
    )
    assert opaque["status"] == "AVAILABLE"
    assert opaque["vials_on_hand"] == 2

    validate_error(
        breadth.api.create_imaging_study(
            f.imaging_payload(
                patient_id=patient["id"],
                eye="OD",
                study_datetime="2026-08-01T00:00:00Z",
                central_subfield_thickness_um=400,
                intraretinal_fluid=True,
                subretinal_fluid=False,
                new_hemorrhage=False,
                va_letter_score=60,
            ),
            specialist_headers(patient["id"]),
        ),
        ApiErrorId.ERR_ACTING_IDENTITY_NOT_FOUND,
        403,
    )
    validate_error(
        breadth.api.list_recall_notifications(
            patient_headers(clinician["id"]), f.page_params(patient_id=patient["id"])
        ),
        ApiErrorId.ERR_ACTING_IDENTITY_NOT_FOUND,
        403,
    )

    _, meta = validate_list(
        breadth.api.list_imaging_studies(
            admin_headers(ADMIN_USER_ID), f.page_params(patient_id=patient["id"])
        )
    )
    assert meta["total_count"] == 0
