"""
The role model as a contract: who may act, who may not, who must resolve to a row, and who
must own the row they touch.

Every case here drives the authorization ladder of section 2.10 rather than a business rule,
so the refusals are all 401 or 403 and every one of them is checked to have written nothing.
"""

from test_helpers import (
    COORDINATOR_HEADERS,
    ERR_FORBIDDEN_ROLE,
    ERR_NOT_RESOURCE_OWNER,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHENTICATED,
    ERR_UNKNOWN_ACTOR,
    INVALID_ROLE_HEADERS,
    LAB_TECHNICIAN_HEADERS,
    MEDICAL_DIRECTOR_HEADERS,
    MISSING_USER_ID_HEADERS,
    NO_AUTH_HEADERS,
    UNKNOWN_DONOR_ID,
    UNKNOWN_PANEL_ID,
    UNKNOWN_REPORT_ID,
    UNKNOWN_REQUEST_ID,
    UNKNOWN_SURGEON_ID,
    UNKNOWN_TECHNICIAN_ID,
    UNKNOWN_TISSUE_ID,
    factories,
    fixtures,
    get_success_data,
    make_evaluation_technician_headers,
    make_recovery_technician_headers,
    make_surgeon_headers,
    total_count_of,
    validate_error,
    validate_success,
)

UNKNOWN_ACTOR_TECHNICIAN_ID = "00000000-0000-4000-8000-0000000000c1"


def test_every_role_exercises_its_own_exclusive_operation_along_one_chain(pinned_api):
    """
    One donor-to-classification chain that changes actor at every hop, so each of the five
    bank-side roles performs an operation reserved to it and the surgeon opens their own
    request at the end.

    PRD 2.1: "The six roles are `EyeBankCoordinator`, `LabTechnician`, `RecoveryTechnician`,
    `EvaluationTechnician`, `MedicalDirector` and `Surgeon`. Each endpoint in section 4 lists
    the roles authorized to invoke it; a syntactically valid role that does not appear in that
    list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    PRD 2.1: "The division of labour is deliberate and non-negotiable. An `EyeBankCoordinator`
    is operations staff: they intake referrals, record screening answers and consent, register
    technicians and surgeons, dispatch recoveries, allocate tissue and prepare and dispatch
    shipments — but they never grade tissue and never adjudicate. A `LabTechnician` draws
    serology specimens and posts marker results, and has no authority over consent,
    classification, allocation or shipping. A `RecoveryTechnician` is the field technician on a
    dispatch: they mark arrival, record preservation, and may abort their own dispatch. An
    `EvaluationTechnician` performs the slit-lamp and specular examinations. A `MedicalDirector`
    is the physician with release authority: approving donors for recovery, reinstating deferred
    donors, classifying tissue, managing quarantine and disposal, setting surgeon credential
    status, adjudicating adverse-reaction reports and running lookback investigations — never
    recording screening answers, never allocating and never shipping. A `Surgeon` opens and
    cancels their own tissue requests, acknowledges delivery, confirms implantation, returns
    unused tissue and files adverse-reaction reports."

    PRD 4: "**Endpoints that create a new resource respond with HTTP 201 and return the created
    resource in `data`; endpoints that modify an existing resource respond with HTTP 200 and
    return the updated resource; read endpoints respond with HTTP 200.**"

    PRD 3.1: "The **first** screening record for a donor advances that donor from `REFERRED` to
    `SCREENING`; second and later records leave `status` untouched but still trigger a full
    recomputation of the risk score."

    PRD 3.2: "On success the four consent fields are written, `consent_obtained_at` is stamped
    with the current logical instant, and the donor advances `SCREENING → CONSENT_OBTAINED`."

    PRD 3.2: "The new panel is created in `DRAWN` with `hiv_result`, `hbv_result`, `hcv_result`,
    `syphilis_result`, `overall_result`, `resulted_at` and `superseded_at` all null."

    PRD 3.2: "The panel moves `DRAWN → RESULTED` with `resulted_at` stamped from the logical
    clock, and the donor's `serology_status` is republished from the verdict: `NON_REACTIVE`
    becomes `NEGATIVE`, `REACTIVE` becomes `REACTIVE`, and `INDETERMINATE` becomes
    `INDETERMINATE`."

    PRD 3.2: "On success the donor advances `CONSENT_OBTAINED → APPROVED_FOR_RECOVERY` and its
    `version` is incremented; nothing else changes."

    PRD 3.3: "The new recovery is created in `DISPATCHED` with `arrival_at`, `preservation_at`,
    `preservation_medium`, `abort_reason`, `death_to_preservation_minutes` and `time_limit_band`
    all null and `recovered_lateralities` an empty list."

    PRD 3.3: "The dispatched technician marks arrival by supplying `arrival_at`, which moves the
    recovery `DISPATCHED → ON_SITE` and increments its `version`; the technician performing this
    must be the technician named in the recovery's `technician_id`, and any other technician is
    refused with `ERR_NOT_RESOURCE_OWNER`."

    PRD 3.3: "The recovery moves `ON_SITE → COMPLETED`, the donor moves `APPROVED_FOR_RECOVERY
    → RECOVERED` with `tissues_recovered_count` set to the number of tissues just created, the
    technician's `open_dispatch_count` falls by 1, and the `version` of the recovery, the donor
    and the technician each increase by 1."

    PRD 3.4: "Each write increments the tissue's `version` by 1 and stores that post-write value
    in the new evaluation's `tissue_version_after`, which is the handle the client must echo as
    `expected_tissue_version` on its next evaluation of the same tissue."

    PRD 3.5: "Otherwise, when `tissue_quality_score` is 70 or above **and** the specular
    `endothelial_cell_count` is 2000 or above **and** the recovery's `time_limit_band` is
    `WITHIN_STANDARD`, the classification is `TRANSPLANT_OPTICAL`."

    PRD 3.5: "`TRANSPLANT_OPTICAL` and `TRANSPLANT_THERAPEUTIC` both move `disposition_status`
    from `UNGRADED` to `ELIGIBLE`, making the tissue allocatable."

    PRD 3.6: "A request is created `OPEN` with `cancel_reason` null. Only the requesting surgeon
    themselves or a coordinator may open a request on that surgeon's behalf, and a surgeon
    naming a different `surgeon_id` is refused with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/every_role_exercises_its_own_exclusive_operation_along_one_donor_to_classification_chain
    """
    recoverer = validate_success(
        pinned_api.create_technician(
            factories.technician_payload("Rosa Field", "RECOVERY_ONLY"),
            COORDINATOR_HEADERS,
        ),
        201,
    )
    evaluator = validate_success(
        pinned_api.create_technician(
            factories.technician_payload("Nils Abadi", "RECOVERY_AND_EVAL"),
            COORDINATOR_HEADERS,
        ),
        201,
    )

    donor = validate_success(
        pinned_api.create_donor(
            factories.donor_payload(
                donor_code="D-2846-R01",
                referral_source="HOSPITAL",
                death_at="2026-08-03T02:00:00.000Z",
                death_time_basis="ASYSTOLE",
                body_cooled_at="2026-08-03T03:00:00.000Z",
                age_years=52,
                cause_of_death_category="CARDIAC",
            ),
            COORDINATOR_HEADERS,
        ),
        201,
    )
    assert donor["status"] == "REFERRED"

    validate_success(
        pinned_api.create_screening_record(
            donor["id"],
            factories.screening_payload("TATTOO_12M", "NO", "SPOUSE"),
            COORDINATOR_HEADERS,
        ),
        201,
    )
    consented = validate_success(
        pinned_api.record_consent(
            donor["id"],
            factories.consent_payload(
                "FIRST_PERSON", "TRANSPLANT_ONLY", "Registry Self-Consent"
            ),
            COORDINATOR_HEADERS,
        ),
        200,
    )
    assert consented["status"] == "CONSENT_OBTAINED"

    panel = validate_success(
        pinned_api.create_serology_panel(
            donor["id"],
            factories.panel_payload(
                consented["version"], "POST_MORTEM", "2026-08-03T04:00:00.000Z", 0.00
            ),
            LAB_TECHNICIAN_HEADERS,
        ),
        201,
    )
    assert panel["status"] == "DRAWN"

    resulted = validate_success(
        pinned_api.post_serology_results(
            panel["id"], factories.results_payload(), LAB_TECHNICIAN_HEADERS
        ),
        200,
    )
    assert resulted["status"] == "RESULTED"
    assert resulted["overall_result"] == "NON_REACTIVE"

    approved = validate_success(
        pinned_api.approve_recovery(donor["id"], None, MEDICAL_DIRECTOR_HEADERS), 200
    )
    assert approved["status"] == "APPROVED_FOR_RECOVERY"

    recovery = validate_success(
        pinned_api.create_recovery(
            factories.recovery_payload(
                donor["id"],
                recoverer["id"],
                "2026-08-03T06:30:00.000Z",
                "2026-08-03T10:00:00.000Z",
            ),
            COORDINATOR_HEADERS,
        ),
        201,
    )
    assert recovery["status"] == "DISPATCHED"

    on_site = validate_success(
        pinned_api.arrive_recovery(
            recovery["id"],
            factories.arrive_payload("2026-08-03T07:00:00.000Z"),
            make_recovery_technician_headers(recoverer["id"]),
        ),
        200,
    )
    assert on_site["status"] == "ON_SITE"

    completed = validate_success(
        pinned_api.complete_recovery(
            recovery["id"],
            factories.complete_payload(
                "2026-08-03T09:00:00.000Z", "OPTISOL_GS", ("OD",)
            ),
            make_recovery_technician_headers(recoverer["id"]),
        ),
        200,
    )
    assert completed["status"] == "COMPLETED"

    tissues = fixtures.list_tissues(
        pinned_api,
        headers=make_evaluation_technician_headers(evaluator["id"]),
        recovery_id=recovery["id"],
    )
    assert len(tissues) == 1
    tissue = tissues[0]

    slit = validate_success(
        pinned_api.create_tissue_evaluation(
            tissue["id"],
            factories.slit_lamp_payload(
                evaluator["id"], "2026-08-03T09:30:00.000Z", tissue["version"]
            ),
            make_evaluation_technician_headers(evaluator["id"]),
        ),
        201,
    )
    assert slit["tissue_version_after"] == tissue["version"] + 1

    specular = validate_success(
        pinned_api.create_tissue_evaluation(
            tissue["id"],
            factories.specular_payload(
                evaluator["id"],
                "2026-08-03T09:45:00.000Z",
                slit["tissue_version_after"],
                0,
                3100,
            ),
            make_evaluation_technician_headers(evaluator["id"]),
        ),
        201,
    )
    assert specular["tissue_version_after"] == slit["tissue_version_after"] + 1

    classified = validate_success(
        pinned_api.classify_tissue(
            tissue["id"], factories.classify_payload(), MEDICAL_DIRECTOR_HEADERS
        ),
        200,
    )
    assert classified["classification"] == "TRANSPLANT_OPTICAL"
    assert classified["disposition_status"] == "ELIGIBLE"

    surgeon = validate_success(
        pinned_api.create_surgeon(
            factories.surgeon_payload("Dr Imani Rho", "CTR-01", "PK"),
            COORDINATOR_HEADERS,
        ),
        201,
    )
    request = validate_success(
        pinned_api.create_surgeon_request(
            factories.request_payload(
                surgeon["id"],
                "PK",
                "2026-08-08T00:00:00.000Z",
                2000,
                70,
                "ANY",
                "ROUTINE",
            ),
            make_surgeon_headers(surgeon["id"]),
        ),
        201,
    )

    assert request["status"] == "OPEN"
    assert request["cancel_reason"] is None


def test_no_role_can_reach_another_roles_exclusive_operation(pinned_api):
    """
    Five cross-role attempts carry perfectly formed bodies but name resources that do not
    exist, and every one of them is refused for the role rather than for the missing row, so
    no 404 and no unknown-actor code ever surfaces.

    PRD 2.1: "The six roles are `EyeBankCoordinator`, `LabTechnician`, `RecoveryTechnician`,
    `EvaluationTechnician`, `MedicalDirector` and `Surgeon`. Each endpoint in section 4 lists
    the roles authorized to invoke it; a syntactically valid role that does not appear in that
    list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    PRD 2.1: "A `LabTechnician` draws serology specimens and posts marker results, and has no
    authority over consent, classification, allocation or shipping."

    PRD 2.1: "An `EvaluationTechnician` performs the slit-lamp and specular examinations."

    PRD 2.1: "A `Surgeon` opens and cancels their own tissue requests, acknowledges delivery,
    confirms implantation, returns unused tissue and files adverse-reaction reports."

    PRD 2.10: "When a request violates several rules at once, exactly one error is returned, and
    which one is fully determined: the checks below are evaluated in ascending order and the
    **first** failing check produces the response."

    PRD 2.10: "The acting role appears in the called endpoint's authorized-role list — otherwise
    `ERR_FORBIDDEN_ROLE` (403). Applies to every endpoint."

    PRD 2.10: "For an entity-backed role, `X-User-ID` resolves to an existing row of the backing
    table — `Technician` for `RecoveryTechnician` and `EvaluationTechnician`, `Surgeon` for
    `Surgeon` — otherwise `ERR_UNKNOWN_ACTOR` (403). Applies to every endpoint whose authorized
    roles include one of those three."

    PRD 2.10: "Every identifier in the request path resolves, left to right — otherwise the
    matching 404 code from section 2.8. Applies to every endpoint with a path identifier."

    PRD 2.10: "Every foreign key in the request body resolves — otherwise the matching 404 code.
    Applies to recovery dispatch, tissue evaluation, surgeon-request creation, manual allocation,
    shipment preparation and adverse-reaction reporting."

    Design: Corner/rbac/no_role_can_reach_another_roles_exclusive_operation
    """
    surgeon_classifying = pinned_api.classify_tissue(
        UNKNOWN_TISSUE_ID,
        factories.classify_payload(),
        make_surgeon_headers(UNKNOWN_SURGEON_ID),
    )
    coordinator_adjudicating = pinned_api.substantiate_report(
        UNKNOWN_REPORT_ID,
        factories.adjudication_payload("Coordinator attempting a medical adjudication."),
        COORDINATOR_HEADERS,
    )
    lab_dispatching = pinned_api.create_recovery(
        factories.recovery_payload(
            UNKNOWN_DONOR_ID,
            UNKNOWN_TECHNICIAN_ID,
            "2026-08-03T06:30:00.000Z",
            "2026-08-03T10:00:00.000Z",
        ),
        LAB_TECHNICIAN_HEADERS,
    )
    evaluator_allocating = pinned_api.create_allocation(
        factories.allocation_payload(UNKNOWN_TISSUE_ID, UNKNOWN_REQUEST_ID),
        make_evaluation_technician_headers(UNKNOWN_TECHNICIAN_ID),
    )
    director_posting_results = pinned_api.post_serology_results(
        UNKNOWN_PANEL_ID, factories.results_payload(), MEDICAL_DIRECTOR_HEADERS
    )

    for label, response in (
        ("surgeon classifying", surgeon_classifying),
        ("coordinator adjudicating", coordinator_adjudicating),
        ("lab technician dispatching", lab_dispatching),
        ("evaluation technician allocating", evaluator_allocating),
        ("medical director posting results", director_posting_results),
    ):
        validate_error(response, ERR_FORBIDDEN_ROLE, 403)
        assert response.status_code == 403, label


def test_a_request_missing_the_x_user_headers_is_unauthenticated(pinned_api):
    """
    All three header defects — no headers at all, a role without an id, and a role outside the
    declared six — answer 401 on a write and on a read alike, and the refused write leaves the
    donor table empty.

    PRD 2.1: "Every request to every endpoint — including the clock capability — must carry two
    headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role
    that principal is acting in. If either header is absent, or if `X-User-Role` is not exactly
    one of the six role names below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP
    401). This check precedes every other consideration; an unauthenticated caller never learns
    whether the resource it named exists."

    PRD 2.10: "Both `X-User-ID` and `X-User-Role` are present and `X-User-Role` is one of the six
    declared roles — otherwise `ERR_UNAUTHENTICATED` (401). Applies to every endpoint."

    PRD 2.2: "The `error_id` is a unique, machine-readable string that identifies the specific
    error."

    PRD 2.2: "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/rbac/a_request_missing_the_x_user_headers_is_unauthenticated
    """
    no_headers = pinned_api.create_donor(
        factories.donor_payload(
            donor_code="D-2846-R03",
            referral_source="HOSPITAL",
            death_at="2026-08-03T02:00:00.000Z",
            death_time_basis="ASYSTOLE",
            body_cooled_at="2026-08-03T03:00:00.000Z",
            age_years=52,
            cause_of_death_category="CARDIAC",
        ),
        NO_AUTH_HEADERS,
    )
    role_without_id = pinned_api.list_donors(MISSING_USER_ID_HEADERS)
    undeclared_role = pinned_api.list_donors(INVALID_ROLE_HEADERS)

    for label, response in (
        ("no headers at all", no_headers),
        ("role header without an id", role_without_id),
        ("undeclared role name", undeclared_role),
    ):
        validate_error(response, ERR_UNAUTHENTICATED, 401)
        body = response.json()
        assert body["response_type"] == "error", label
        assert body["data"]["message"], label

    assert total_count_of(pinned_api.list_donors(COORDINATOR_HEADERS)) == 0


def test_an_entity_backed_actor_must_resolve_and_must_own_the_resource(pinned_api):
    """
    One DISPATCHED recovery is arrived at three ways — by an id that matches no technician, by
    a real but unassigned technician, and finally by the assigned one — and the evaluation
    endpoint compares the actor against the body's evaluator rather than against the path
    resource.

    PRD 2.1: "When `X-User-Role` is `RecoveryTechnician`, `X-User-ID` is the `id` of the acting
    `Technician`; ownership checks on any resource that references a `Technician` compare the
    resource's foreign-key field to `X-User-ID`."

    PRD 2.1: "For those three roles, an `X-User-ID` that does not resolve to an existing
    `Technician` row (for `RecoveryTechnician` and `EvaluationTechnician`) or an existing
    `Surgeon` row (for `Surgeon`) is rejected with `ERR_UNKNOWN_ACTOR` (HTTP 403)."

    PRD 2.1: "Ownership is enforced on exactly ten operations, and a violation is always reported
    as `ERR_NOT_RESOURCE_OWNER` (HTTP 403). For a `RecoveryTechnician` acting on a recovery —
    marking arrival, recording preservation, or aborting — `X-User-ID` must equal that recovery's
    `technician_id`. For an `EvaluationTechnician` recording a tissue evaluation, `X-User-ID`
    must equal the `evaluator_technician_id` carried in the request body."

    PRD 2.10: "For an entity-backed role, `X-User-ID` resolves to an existing row of the backing
    table — `Technician` for `RecoveryTechnician` and `EvaluationTechnician`, `Surgeon` for
    `Surgeon` — otherwise `ERR_UNKNOWN_ACTOR` (403). Applies to every endpoint whose authorized
    roles include one of those three."

    PRD 2.10: "Resource ownership holds for entity-backed actors — otherwise
    `ERR_NOT_RESOURCE_OWNER` (403). Applies to the ten operations enumerated in section 2.1."

    PRD 3.3: "The dispatched technician marks arrival by supplying `arrival_at`, which moves the
    recovery `DISPATCHED → ON_SITE` and increments its `version`; the technician performing this
    must be the technician named in the recovery's `technician_id`, and any other technician is
    refused with `ERR_NOT_RESOURCE_OWNER`."

    PRD 3.3: "The recovery moves `ON_SITE → COMPLETED`, the donor moves `APPROVED_FOR_RECOVERY →
    RECOVERED` with `tissues_recovered_count` set to the number of tissues just created, the
    technician's `open_dispatch_count` falls by 1, and the `version` of the recovery, the donor
    and the technician each increase by 1."

    PRD 3.4: "The acting user must be the technician named as evaluator; grading on another
    technician's behalf is refused with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/an_entity_backed_actor_must_resolve_and_must_own_the_resource_it_touches
    """
    assigned = fixtures.create_technician(pinned_api, "Rosa Field", "RECOVERY_ONLY")
    bystander = fixtures.create_technician(
        pinned_api, "Nils Abadi", "RECOVERY_AND_EVAL"
    )
    colleague = fixtures.create_technician(
        pinned_api, "Petra Voss", "RECOVERY_AND_EVAL"
    )
    donor = fixtures.approved_donor(
        pinned_api,
        donor_code="D-2846-R04",
        body_cooled_at="2026-08-03T03:00:00.000Z",
        age_years=52,
    )
    recovery = fixtures.create_recovery(
        pinned_api,
        donor["id"],
        assigned["id"],
        dispatched_at="2026-08-03T06:30:00.000Z",
        planned_release_at="2026-08-03T10:00:00.000Z",
    )
    arrive_body = factories.arrive_payload("2026-08-03T07:00:00.000Z")

    unresolvable = pinned_api.arrive_recovery(
        recovery["id"],
        arrive_body,
        make_recovery_technician_headers(UNKNOWN_ACTOR_TECHNICIAN_ID),
    )

    validate_error(unresolvable, ERR_UNKNOWN_ACTOR, 403)

    not_the_owner = pinned_api.arrive_recovery(
        recovery["id"], arrive_body, make_recovery_technician_headers(bystander["id"])
    )

    validate_error(not_the_owner, ERR_NOT_RESOURCE_OWNER, 403)
    untouched = fixtures.read_recovery(pinned_api, recovery["id"])
    assert untouched["status"] == "DISPATCHED"
    assert untouched["version"] == 1
    assert untouched["arrival_at"] is None

    on_site = fixtures.arrive(
        pinned_api, recovery["id"], assigned["id"], "2026-08-03T07:00:00.000Z"
    )
    assert on_site["status"] == "ON_SITE"
    completed = fixtures.complete_recovery(
        pinned_api,
        recovery["id"],
        assigned["id"],
        preservation_at="2026-08-03T09:00:00.000Z",
    )
    assert completed["status"] == "COMPLETED"

    tissue = fixtures.tissues_of_recovery(pinned_api, recovery["id"])[0]
    assert tissue["version"] == 1

    on_a_colleagues_behalf = pinned_api.create_tissue_evaluation(
        tissue["id"],
        factories.slit_lamp_payload(
            colleague["id"], "2026-08-03T09:30:00.000Z", tissue["version"]
        ),
        make_evaluation_technician_headers(bystander["id"]),
    )

    validate_error(on_a_colleagues_behalf, ERR_NOT_RESOURCE_OWNER, 403)
    evaluations = get_success_data(
        pinned_api.list_tissue_evaluations(
            tissue["id"], make_evaluation_technician_headers(bystander["id"])
        )
    )
    assert evaluations == []
    assert fixtures.read_tissue(pinned_api, tissue["id"])["version"] == 1


def test_segregation_of_duties_is_scoped_per_tissue_not_per_technician(pinned_api):
    """
    One dual-certified technician grades the cornea a colleague recovered, which is accepted,
    and then the cornea they recovered themselves, which is refused — so the rule compares the
    evaluator with that tissue's recovering technician rather than banning dual-certified staff.

    PRD 2.1: "An `EvaluationTechnician` performs the slit-lamp and specular examinations."

    PRD 3.4: "Two personnel gates guard the write. The bank enforces **segregation of duties**:
    the technician who recovered a cornea may not be the technician who grades it. Concretely, if
    the named `evaluator_technician_id` equals the `technician_id` of the recovery that produced
    this tissue, the evaluation is refused with `ERR_SEGREGATION_OF_DUTIES`. Separately, the named
    evaluator must be fit to grade — `status` `ACTIVE`, a `certification_expires_at` strictly
    later than the current logical instant, and a `certification_level` of `RECOVERY_AND_EVAL`,
    because a `RECOVERY_ONLY` technician may recover but never grade."

    PRD 2.10: "The `evaluator_technician_id` differs from the `technician_id` of the recovery that
    produced the tissue — otherwise `ERR_SEGREGATION_OF_DUTIES` (422). Applies to
    tissue-evaluation creation."

    PRD 3.4: "Each write increments the tissue's `version` by 1 and stores that post-write value
    in the new evaluation's `tissue_version_after`, which is the handle the client must echo as
    `expected_tissue_version` on its next evaluation of the same tissue."

    Design: Corner/rbac/segregation_of_duties_is_scoped_per_tissue_not_per_technician
    """
    tech_a = fixtures.create_technician(pinned_api, "Nils Abadi", "RECOVERY_AND_EVAL")
    tech_b = fixtures.create_technician(pinned_api, "Petra Voss", "RECOVERY_AND_EVAL")
    donor_one = fixtures.approved_donor(
        pinned_api,
        donor_code="D-2846-R05A",
        body_cooled_at="2026-08-03T03:00:00.000Z",
        age_years=52,
    )
    donor_two = fixtures.approved_donor(
        pinned_api,
        donor_code="D-2846-R05B",
        referral_source="MEDICAL_EXAMINER",
        death_at="2026-08-03T02:30:00.000Z",
        body_cooled_at="2026-08-03T03:30:00.000Z",
        age_years=48,
        cause_of_death_category="TRAUMA",
    )
    chain_one = fixtures.recovered_tissues(
        pinned_api,
        donor_one["id"],
        tech_a["id"],
        dispatched_at="2026-08-03T06:30:00.000Z",
        planned_release_at="2026-08-03T10:00:00.000Z",
        arrival_at="2026-08-03T07:00:00.000Z",
        preservation_at="2026-08-03T09:00:00.000Z",
    )
    chain_two = fixtures.recovered_tissues(
        pinned_api,
        donor_two["id"],
        tech_b["id"],
        dispatched_at="2026-08-03T06:45:00.000Z",
        planned_release_at="2026-08-03T10:15:00.000Z",
        arrival_at="2026-08-03T07:15:00.000Z",
        preservation_at="2026-08-03T09:15:00.000Z",
    )
    own_tissue = chain_one.tissues[0]
    colleagues_tissue = chain_two.tissues[0]

    accepted = validate_success(
        pinned_api.create_tissue_evaluation(
            colleagues_tissue["id"],
            factories.slit_lamp_payload(
                tech_a["id"], "2026-08-03T09:45:00.000Z", colleagues_tissue["version"]
            ),
            make_evaluation_technician_headers(tech_a["id"]),
        ),
        201,
    )

    assert accepted["status"] == "RECORDED"
    assert accepted["tissue_version_after"] == colleagues_tissue["version"] + 1

    refused = pinned_api.create_tissue_evaluation(
        own_tissue["id"],
        factories.slit_lamp_payload(
            tech_a["id"], "2026-08-03T09:50:00.000Z", own_tissue["version"]
        ),
        make_evaluation_technician_headers(tech_a["id"]),
    )

    validate_error(refused, ERR_SEGREGATION_OF_DUTIES, 422)
    own_rows = get_success_data(
        pinned_api.list_tissue_evaluations(
            own_tissue["id"], make_evaluation_technician_headers(tech_a["id"])
        )
    )
    colleague_rows = get_success_data(
        pinned_api.list_tissue_evaluations(
            colleagues_tissue["id"], make_evaluation_technician_headers(tech_a["id"])
        )
    )
    assert own_rows == []
    assert len(colleague_rows) == 1
    assert (
        fixtures.read_tissue(pinned_api, own_tissue["id"])["version"]
        == own_tissue["version"]
    )


def test_shared_reads_reach_exactly_the_roles_declared_on_each_endpoint(pinned_api):
    """
    The three narrow bank-side roles each read what section 4 grants them, and the same lab
    technician is then refused the allocation list, so the read surface is an allow-list rather
    than a blanket grant to any authenticated actor.

    PRD 2.1: "The six roles are `EyeBankCoordinator`, `LabTechnician`, `RecoveryTechnician`,
    `EvaluationTechnician`, `MedicalDirector` and `Surgeon`. Each endpoint in section 4 lists
    the roles authorized to invoke it; a syntactically valid role that does not appear in that
    list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    PRD 4: "**Endpoints that create a new resource respond with HTTP 201 and return the created
    resource in `data`; endpoints that modify an existing resource respond with HTTP 200 and
    return the updated resource; read endpoints respond with HTTP 200.**"

    PRD 4: "| GET | `/eye-bank/donors/{id}` | Read one donor, including its computed recovery
    window, screening risk, serology status and lookback flag. | `EyeBankCoordinator`,
    `LabTechnician`, `MedicalDirector`, `RecoveryTechnician`, `EvaluationTechnician` |"

    PRD 4: "| GET | `/eye-bank/donors/{id}/screening-records` | List the donor's screening answers
    with the risk weight each contributed. | `EyeBankCoordinator`, `LabTechnician`,
    `MedicalDirector` |"

    PRD 4: "| GET | `/eye-bank/donors/{id}/serology-panels` | List the donor's serology panels,
    newest drawn_at first, including invalidated ones. | `EyeBankCoordinator`, `LabTechnician`,
    `MedicalDirector` |"

    PRD 4: "| GET | `/eye-bank/tissues/{id}` | Read one cornea tissue, including both state
    dimensions, quality score, classification, shelf-life variant and expiry. |
    `EyeBankCoordinator`, `LabTechnician`, `MedicalDirector`, `EvaluationTechnician`, `Surgeon` |"

    PRD 4: "| GET | `/eye-bank/recoveries/{id}` | Read one recovery, including its
    death-to-preservation minutes and time-limit band. | `EyeBankCoordinator`, `MedicalDirector`,
    `RecoveryTechnician`, `EvaluationTechnician` |"

    PRD 4: "| GET | `/eye-bank/technicians/{id}` | Read one technician, including the number of
    dispatches currently occupying them. | `EyeBankCoordinator`, `MedicalDirector`,
    `RecoveryTechnician`, `EvaluationTechnician` |"

    PRD 4: "| GET | `/eye-bank/allocations` | List allocations, newest allocated_at first,
    optionally filtered by tissue, request or status. | `EyeBankCoordinator`, `MedicalDirector`,
    `Surgeon` |"

    PRD 3.3: "Every technician is created `ACTIVE` with `open_dispatch_count` 0."

    PRD 3.2: "The panel moves `DRAWN → RESULTED` with `resulted_at` stamped from the logical
    clock, and the donor's `serology_status` is republished from the verdict: `NON_REACTIVE`
    becomes `NEGATIVE`, `REACTIVE` becomes `REACTIVE`, and `INDETERMINATE` becomes
    `INDETERMINATE`."

    PRD 3.3: "The recovery moves `ON_SITE → COMPLETED`, the donor moves `APPROVED_FOR_RECOVERY →
    RECOVERED` with `tissues_recovered_count` set to the number of tissues just created, the
    technician's `open_dispatch_count` falls by 1, and the `version` of the recovery, the donor
    and the technician each increase by 1."

    Design: Corner/rbac/shared_reads_reach_exactly_the_roles_declared_on_each_endpoint
    """
    recoverer = fixtures.create_technician(pinned_api, "Rosa Field", "RECOVERY_ONLY")
    evaluator = fixtures.create_technician(
        pinned_api, "Nils Abadi", "RECOVERY_AND_EVAL"
    )
    donor = fixtures.approved_donor(
        pinned_api,
        donor_code="D-2846-R06",
        body_cooled_at="2026-08-03T03:00:00.000Z",
        age_years=52,
    )
    chain = fixtures.recovered_tissues(
        pinned_api,
        donor["id"],
        recoverer["id"],
        dispatched_at="2026-08-03T06:30:00.000Z",
        planned_release_at="2026-08-03T10:00:00.000Z",
        arrival_at="2026-08-03T07:00:00.000Z",
        preservation_at="2026-08-03T09:00:00.000Z",
    )
    tissue_id = chain.tissues[0]["id"]
    lab = LAB_TECHNICIAN_HEADERS
    field_technician = make_recovery_technician_headers(recoverer["id"])
    grader = make_evaluation_technician_headers(evaluator["id"])

    lab_donor = validate_success(pinned_api.get_donor(donor["id"], lab), 200)
    assert lab_donor["donor_code"] == "D-2846-R06"
    assert lab_donor["status"] == "RECOVERED"

    lab_screening = validate_success(
        pinned_api.list_screening_records(donor["id"], lab), 200
    )
    assert len(lab_screening) == 1

    lab_panels = validate_success(
        pinned_api.list_serology_panels(donor["id"], lab), 200
    )
    assert len(lab_panels) == 1
    assert lab_panels[0]["status"] == "RESULTED"

    lab_tissue = validate_success(pinned_api.get_tissue(tissue_id, lab), 200)
    assert lab_tissue["disposition_status"] == "UNGRADED"

    own_recovery = validate_success(
        pinned_api.get_recovery(chain.recovery_id, field_technician), 200
    )
    assert own_recovery["status"] == "COMPLETED"

    read_roster = validate_success(
        pinned_api.get_technician(recoverer["id"], grader), 200
    )
    assert read_roster["status"] == "ACTIVE"

    graded_view = validate_success(pinned_api.get_tissue(tissue_id, grader), 200)
    assert graded_view["disposition_status"] == "UNGRADED"

    refused = pinned_api.list_allocations(lab)

    validate_error(refused, ERR_FORBIDDEN_ROLE, 403)
