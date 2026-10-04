"""Program configuration and episode intake: creation, defaults, idempotency,
and intake-level validations."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_employer,
    assert_episode,
    get_success_data,
    make_active_contract,
    make_contract,
    make_employer,
    make_template,
    make_patient,
    open_episode,
    reset_clock,
    unique_token,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_employer_create_returns_all_fields_and_active_status(api):
    """PRD §3.1: "A new employer starts `ACTIVE`."
    PRD §2.4: "Most resources carry a standard set of system-managed fields:
    `id`, a server-minted UUID with no type prefix; `created_at` and
    `updated_at`, ISO 8601 UTC timestamps with three fractional digits; and
    `version`, an integer that increments on every mutation of the resource."

    Design: Corner/entities/employer_create_returns_all_fields_and_active_status
    """
    reset_clock()
    rb = get_success_data(
        api.create_rate_book(
            {"book_code": unique_token("RB"), "rates": {"ORTHO_JOINT": 2500000}},
            {"X-User-ID": "test-program-admin-1", "X-User-Role": "ProgramAdmin"},
        )
    )
    from test_helpers import TEST_USERS

    payload = {
        "legal_name": "Acme Corp",
        "ein": unique_token("EIN"),
        "baseline_rate_book": rb["id"],
    }
    resp = api.create_employer(payload, TEST_USERS["program_admin_headers"])
    emp = validate_success(resp, expected_status=201)
    assert_employer(emp)
    assert emp["legal_name"] == "Acme Corp"
    assert emp["baseline_rate_book"] == rb["id"]
    assert emp["status"] == "ACTIVE", "A new employer starts ACTIVE"


def test_episode_get_not_found_returns_404(api, program_admin_headers):
    """PRD §2.10: "Path existence, resolved left to right (`ERR_NOT_FOUND`)."
    PRD §2.9: "The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the
    first identifier that does not resolve to an existing resource, before any
    later identifier or any business rule is examined."

    Design: Corner/entities/episode_get_not_found_returns_404
    """
    resp = api.get_episode(NON_EXISTENT_UUID, program_admin_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_episode_create_missing_patient_id_returns_invalid_request(
    api, care_coordinator_headers
):
    """PRD §2.10: "Request body well-formedness — required fields present,
    enums valid, types correct (`ERR_INVALID_REQUEST`)."
    PRD §3.3: "A `CareCoordinator` opens an episode by naming the `patient_id`,
    the `contract_id`, an `intake_request_id`, and optionally a `triage_rank` —
    0 for elective (the default) or 1 for urgent."

    Design: Corner/entities/episode_create_missing_patient_id_returns_invalid_request
    """
    reset_clock()
    resp = api.create_episode(
        {"contract_id": NON_EXISTENT_UUID, "intake_request_id": unique_token("IR")},
        care_coordinator_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_episode_triage_rank_defaults_to_zero(api):
    """PRD §3.3: "A `CareCoordinator` opens an episode by naming the
    `patient_id`, the `contract_id`, an `intake_request_id`, and optionally a
    `triage_rank` — 0 for elective (the default) or 1 for urgent."
    PRD §3.3: "The new episode starts in `INTAKE_PENDING` with `screen_seq` at 0"

    Design: Corner/entities/episode_triage_rank_defaults_to_zero
    """
    employer = make_employer({"ORTHO_JOINT": 2500000})
    template = make_template()
    contract = make_active_contract(employer, template)
    patient = make_patient(employer)
    episode = open_episode(patient, contract)  # no triage_rank supplied
    assert_episode(episode)
    assert episode["triage_rank"] == 0, "omitted triage_rank defaults to 0 (elective)"
    assert episode["status"] == "INTAKE_PENDING"


def test_episode_initial_state_is_intake_pending(api):
    """PRD §3.3: "The new episode starts in `INTAKE_PENDING` with `screen_seq`
    at 0"
    PRD §2.7: "An episode's `screen_seq` of 0 on `scheduled_start_seq`,
    `surgery_done_seq`, `discharge_seq`, `warranty_end_seq`, or
    `warranty_close_seq` means "not yet reached""

    Design: Corner/state_machines/episode_initial_state_is_intake_pending
    """
    employer = make_employer({"ORTHO_JOINT": 2500000})
    template = make_template()
    contract = make_contract(employer, template)
    patient = make_patient(employer)
    episode = open_episode(patient, contract)
    assert episode["status"] == "INTAKE_PENDING"
    assert episode["screen_seq"] == 0
    assert episode["scheduled_start_seq"] == 0
    assert episode["surgery_done_seq"] == 0
    assert episode["discharge_seq"] == 0
    assert episode["warranty_end_seq"] == 0
    assert episode["warranty_close_seq"] == 0


def test_episode_intake_idempotent_replay_same_key_same_payload(
    api, care_coordinator_headers, program_admin_headers
):
    """PRD §3.3: "Intake is idempotent per employer on the
    `intake_request_id`: a duplicate submission with the identical payload
    replays the original 201 response, while the same key carrying a different
    payload is a conflict rejected with `ERR_DUPLICATE_INTAKE_REQUEST`."

    Design: Corner/endpoints/episode_intake_idempotent_replay_same_key_same_payload
    """
    employer = make_employer({"ORTHO_JOINT": 2500000})
    template = make_template()
    contract = make_active_contract(employer, template)
    patient_a = make_patient(employer)
    patient_b = make_patient(employer)
    key = unique_token("IR")

    first = api.create_episode(
        {"patient_id": patient_a["id"], "contract_id": contract["id"],
         "intake_request_id": key},
        care_coordinator_headers,
    )
    first_data = validate_success(first, expected_status=201)

    replay = api.create_episode(
        {"patient_id": patient_a["id"], "contract_id": contract["id"],
         "intake_request_id": key},
        care_coordinator_headers,
    )
    replay_data = validate_success(replay, expected_status=201)
    assert replay_data["id"] == first_data["id"], (
        "identical replay must return the original episode id"
    )

    conflict = api.create_episode(
        {"patient_id": patient_b["id"], "contract_id": contract["id"],
         "intake_request_id": key},
        care_coordinator_headers,
    )
    validate_error(conflict, ApiErrorId.ERR_DUPLICATE_INTAKE_REQUEST)

    _, meta = validate_paginated(
        api.list_episodes(program_admin_headers, params={"contract_id": contract["id"]})
    )
    assert meta["total_count"] == 1, "replay must not create a second episode row"


def test_cross_entity_patient_employer_mismatch_rejected(
    api, care_coordinator_headers, program_admin_headers
):
    """PRD §3.3: "The patient must belong to the employer that owns the
    contract, else `ERR_PATIENT_EMPLOYER_MISMATCH`"

    Design: Corner/validations/cross_entity_patient_employer_mismatch_rejected
    """
    employer_a = make_employer({"ORTHO_JOINT": 2500000})
    employer_b = make_employer({"ORTHO_JOINT": 2500000})
    template = make_template()
    contract = make_active_contract(employer_a, template)
    patient_of_b = make_patient(employer_b)

    resp = api.create_episode(
        {"patient_id": patient_of_b["id"], "contract_id": contract["id"],
         "intake_request_id": unique_token("IR")},
        care_coordinator_headers,
    )
    validate_error(resp, ApiErrorId.ERR_PATIENT_EMPLOYER_MISMATCH)

    _, meta = validate_paginated(
        api.list_episodes(program_admin_headers, params={"contract_id": contract["id"]})
    )
    assert meta["total_count"] == 0, "rejected intake must not persist an episode"


def test_aggregate_component_sum_mismatch_rejected(api, program_admin_headers):
    """PRD §3.2: "the component values must sum exactly to the bundle price,
    otherwise creation fails with `ERR_COMPONENT_SUM_MISMATCH`"

    Design: Corner/validations/aggregate_component_sum_mismatch_rejected
    """
    employer = make_employer({"ORTHO_JOINT": 2500000})
    template = make_template()
    resp = api.create_contract(
        {
            "employer_id": employer["id"],
            "template_id": template["id"],
            "effective_from": "2026-09-01T00:00:00Z",
            "effective_to": "2027-09-01T00:00:00Z",
            "bundle_price_cents": 3000000,
            "rate_components": {
                "facility": 2399999,  # sum is one cent short of the bundle price
                "professional": 300000,
                "implant": 200000,
                "anesthesia": 100000,
            },
            "outlier_threshold_cents": 5000000,
            "outlier_share_pct": 0,
            "episode_cap_per_month": 50,
            "concurrent_capacity": 50,
            "travel_benefit_cents": 0,
            "lodging_benefit_cents": 0,
            "companion_allowed": False,
        },
        program_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_COMPONENT_SUM_MISMATCH)


def test_template_retired_blocks_new_contract_but_keeps_existing(
    api, program_admin_headers
):
    """PRD §3.1: "a `ProgramAdmin` may retire one, moving it to `RETIRED`,
    after which it cannot seed new contracts — attempting to create a contract
    against a retired template fails with `ERR_TEMPLATE_RETIRED` — while
    contracts already created against it are unaffected."
    PRD §3.2: "A new contract starts `DRAFT`, pins the template's current
    version into `template_version` at creation"

    Design: Corner/entities/template_retired_blocks_new_contract_but_keeps_existing
    """
    employer = make_employer({"ORTHO_JOINT": 2500000})
    template = make_template()
    contract = make_contract(employer, template)
    assert contract["template_version"] == template["version"], (
        "creation pins the template's current version"
    )

    get_success_data(api.retire_bundle_template(template["id"], program_admin_headers))

    resp = api.create_contract(
        {
            "employer_id": employer["id"],
            "template_id": template["id"],
            "effective_from": "2027-09-01T00:00:00Z",
            "effective_to": "2028-09-01T00:00:00Z",
            "bundle_price_cents": 3100000,
            "rate_components": {"facility": 3100000},
            "outlier_threshold_cents": 5000000,
            "outlier_share_pct": 0,
            "episode_cap_per_month": 50,
            "concurrent_capacity": 50,
            "travel_benefit_cents": 0,
            "lodging_benefit_cents": 0,
            "companion_allowed": False,
        },
        program_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_TEMPLATE_RETIRED)

    activated = validate_success(
        api.activate_contract(contract["id"], program_admin_headers)
    )
    assert activated["status"] == "ACTIVE", (
        "a contract created before retirement still activates"
    )


def test_missing_auth_headers_return_401_before_any_other_check(api):
    """PRD §2.1: "A request missing either header, or carrying a role the
    platform does not declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP
    401)."
    PRD §2.10: "1. Authentication — both headers present and the role declared
    (`ERR_UNAUTHENTICATED`)."

    Design: Corner/validations/missing_auth_headers_return_401_before_any_other_check
    """
    resp = api.create_episode({}, None)  # no X-User-ID / X-User-Role headers
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
