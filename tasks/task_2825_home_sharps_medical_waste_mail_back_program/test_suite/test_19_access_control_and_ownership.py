"""Access control: identity headers, role membership and owner scoping (PRD 2.1).

The three checks exercised here are the first three things the API does with a
request. Header validity answers before any lookup, role membership answers
before the existence band, and ownership answers before any state precondition.
"""

import pytest

from test_helpers import (
    assert_auto_ship_run,
    assert_enrollment,
    assert_kit,
    assert_total_count,
    conformance_screening_payload,
    create_active_enrollment,
    create_california_rule,
    create_draft_enrollment,
    create_eligible_patient,
    create_sponsor,
    create_sponsorship_program,
    destruction_certificate_payload,
    funding_adjustment_payload,
    get_success_data,
    issue_kit_for,
    label_activation_payload,
    make_destruction_officer_headers,
    make_intake_technician_headers,
    make_logistics_coordinator_headers,
    make_patient_headers,
    make_program_admin_headers,
    make_sponsor_representative_headers,
    read_enrollment,
    read_kit,
    read_program,
    seal_payload,
    set_clock,
    setup_program_foundations,
    sponsor_decision_payload,
    state_rule_payload,
    validate_error,
    validate_success,
)

# Syntactically valid identifiers that no row in an empty database carries.
UNKNOWN_ID = "00000000-0000-4000-8000-00000000ffff"
UNKNOWN_FACILITY_ID = "00000000-0000-4000-8000-00000000fffe"
UNKNOWN_PATIENT_ID = "00000000-0000-4000-8000-00000000fffd"
UNKNOWN_SPONSOR_ID = "00000000-0000-4000-8000-00000000fffc"

# The clock's startup value (PRD 2.4). `created_at` is rendered with three
# fractional-second digits, so instants are compared to whole-second precision.
CLOCK_START = "2026-08-01T00:00:00Z"


def _assert_same_instant(actual: str, expected: str) -> None:
    """Compare two ISO 8601 UTC instants ignoring the fractional-second width."""
    assert actual is not None, "expected an ISO 8601 instant, got None"
    assert actual[:19] == expected[:19], (
        f"Expected the instant {expected}, got {actual}"
    )


def _seed_california_rule(api) -> dict:
    """Clock at the startup instant plus one readable CA state rule."""
    set_clock(api, CLOCK_START)
    return create_california_rule(
        api, household_sharps_classification="HOUSEHOLD_EXEMPT"
    )


# ---------------------------------------------------------------------------
# Identity headers: the very first check on any request (PRD 2.1)
# ---------------------------------------------------------------------------
MISSING_HEADER_VARIANTS = [
    ("both_headers_absent", {}),
    ("user_id_absent", {"X-User-Role": "ProgramAdmin"}),
    ("role_absent", {"X-User-ID": "admin-1"}),
]


@pytest.mark.parametrize(
    "variant,headers", MISSING_HEADER_VARIANTS, ids=[v[0] for v in MISSING_HEADER_VARIANTS]
)
def test_01_a_request_missing_either_identity_header_is_unauthenticated(
    api, variant, headers
):
    """A read of an existing state rule is refused whenever either identity
    header is missing, whichever one it is.

    PRD 2.1: "Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the capability set the caller is asserting."
    PRD 2.1: "When either header is absent, or when `X-User-Role` is not one of the six declared role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_x_user_headers_and_unknown_roles_return_unauthenticated
    """
    state_rule = _seed_california_rule(api)

    response = api.call(
        "GET", f"/sharps/state-rules/{state_rule['id']}", headers=headers
    )

    validate_error(response, "ERR_UNAUTHENTICATED", expected_status=401)


def test_02_a_header_less_write_is_refused_and_persists_nothing(api):
    """The header-less registration of a second state rule is refused, and the
    row it would have created does not exist afterwards.

    PRD 2.1: "When either header is absent, or when `X-User-Role` is not one of the six declared role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD 3.1: "State rules can be listed and filtered by `state_code` or by `mail_back_permitted`."

    Design: Corner/rbac/missing_x_user_headers_and_unknown_roles_return_unauthenticated
    """
    _seed_california_rule(api)

    response = api.call(
        "POST",
        "/sharps/state-rules",
        headers={},
        payload=state_rule_payload(
            state_code="NV",
            household_sharps_classification="HOUSEHOLD_EXEMPT",
            mail_back_permitted=True,
            max_container_volume_liters=30.3,
            certificate_retention_years=3,
        ),
    )

    validate_error(response, "ERR_UNAUTHENTICATED", expected_status=401)

    # The header-less write created nothing.
    header_less_read = api.call(
        "GET", "/sharps/state-rules", headers={}, payload={"state_code": "NV"}
    )
    validate_error(header_less_read, "ERR_UNAUTHENTICATED", expected_status=401)
    assert_total_count(
        api.list_state_rules(make_program_admin_headers(), {"state_code": "NV"}), 0
    )


@pytest.mark.parametrize(
    "role_name",
    ["FacilityAuditor", "ProgramAdministrator", "programadmin", "PATIENT"],
)
def test_03_an_undeclared_role_name_is_unauthenticated_not_a_role_denial(
    api, role_name
):
    """A well-formed header pair naming a role outside the six declared names is
    a 401, not the 403 that a declared-but-unauthorized role would earn.

    PRD 2.1: "When either header is absent, or when `X-User-Role` is not one of the six declared role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD 2.1: "The six roles are `ProgramAdmin`, `SponsorRepresentative`, `Patient`, `LogisticsCoordinator`, `IntakeTechnician` and `DestructionOfficer`."

    Design: Corner/rbac/missing_x_user_headers_and_unknown_roles_return_unauthenticated
    """
    _seed_california_rule(api)

    response = api.call(
        "POST",
        "/sharps/state-rules",
        headers={"X-User-ID": "aud-1", "X-User-Role": role_name},
        payload=state_rule_payload(
            state_code="NV",
            household_sharps_classification="HOUSEHOLD_EXEMPT",
            mail_back_permitted=True,
            max_container_volume_liters=30.3,
            certificate_retention_years=3,
        ),
    )

    validate_error(response, "ERR_UNAUTHENTICATED", expected_status=401)
    assert_total_count(
        api.list_state_rules(make_program_admin_headers(), {"state_code": "NV"}), 0
    )


PRIORITY_ONE_PROBES = [
    ("read_of_an_unknown_kit", "GET", f"/sharps/kits/{UNKNOWN_ID}", None),
    (
        "malformed_state_rule_write",
        "POST",
        "/sharps/state-rules",
        {"state_code": "CALIFORNIA", "certificate_retention_years": 99},
    ),
]


@pytest.mark.parametrize(
    "probe,method,path,payload",
    PRIORITY_ONE_PROBES,
    ids=[p[0] for p in PRIORITY_ONE_PROBES],
)
def test_04_the_identity_check_answers_before_any_lookup_or_payload_parsing(
    api, probe, method, path, payload
):
    """A header-less read of an identifier that matches nothing is a 401 rather
    than a 404, and a header-less write of an unparseable payload is a 401 rather
    than a 400.

    PRD 2.1: "When either header is absent, or when `X-User-Role` is not one of the six declared role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD 2.1: "This is the very first check performed on any request, ahead of payload parsing and ahead of any lookup."

    Design: Corner/rbac/missing_x_user_headers_and_unknown_roles_return_unauthenticated
    """
    _seed_california_rule(api)

    response = api.call(method, path, headers={}, payload=payload)

    validate_error(response, "ERR_UNAUTHENTICATED", expected_status=401)


def test_05_the_same_route_succeeds_once_both_identity_headers_are_present(api):
    """Positive control: the route that refused every header-less probe reads
    normally for a caller who supplies both headers.

    PRD 2.1: "Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the capability set the caller is asserting."
    PRD 4: "Endpoints that mint a new resource return HTTP 201 with the created resource in `data`; endpoints that modify an existing resource return HTTP 200 with the updated resource in `data`, as do all read endpoints."

    Design: Corner/rbac/missing_x_user_headers_and_unknown_roles_return_unauthenticated
    """
    state_rule = _seed_california_rule(api)

    response = api.call(
        "GET",
        f"/sharps/state-rules/{state_rule['id']}",
        headers={"X-User-ID": "admin-1", "X-User-Role": "ProgramAdmin"},
    )

    data = validate_success(response, expected_status=200)
    assert data["state_code"] == "CA", (
        f"Expected the CA state rule, got {data['state_code']!r}"
    )


# ---------------------------------------------------------------------------
# Role membership: refused before the existence band (PRD 2.1, PRD 2.6)
# ---------------------------------------------------------------------------
ROLE_EXCLUSIVITY_PROBES = [
    (
        "conformance_screening_attempted_by_a_destruction_officer",
        "POST",
        f"/sharps/shipments/{UNKNOWN_ID}/conformance-screening",
        conformance_screening_payload("CONFORMING", 1200),
        make_destruction_officer_headers("officer-12"),
    ),
    (
        "label_activation_attempted_by_an_intake_technician",
        "POST",
        f"/sharps/return-labels/{UNKNOWN_ID}/activate",
        label_activation_payload(
            UNKNOWN_FACILITY_ID,
            scheduled_intake_date="2026-08-05",
            declared_gross_weight_grams=1200,
        ),
        make_intake_technician_headers("tech-77"),
    ),
    (
        "sponsor_funding_decision_attempted_by_the_program_admin",
        "POST",
        f"/sharps/enrollments/{UNKNOWN_ID}/sponsor-decision",
        sponsor_decision_payload("APPROVE"),
        make_program_admin_headers(),
    ),
    (
        "destruction_certification_attempted_by_an_intake_technician",
        "POST",
        f"/sharps/shipments/{UNKNOWN_ID}/destruction-certificates",
        destruction_certificate_payload(60),
        make_intake_technician_headers("tech-77"),
    ),
    (
        "state_rule_registration_attempted_by_a_sponsor_representative",
        "POST",
        "/sharps/state-rules",
        state_rule_payload(
            state_code="NV",
            household_sharps_classification="HOUSEHOLD_EXEMPT",
            mail_back_permitted=True,
            max_container_volume_liters=30.3,
            certificate_retention_years=3,
        ),
        make_sponsor_representative_headers(UNKNOWN_SPONSOR_ID),
    ),
]


@pytest.mark.parametrize(
    "probe,method,path,payload,headers",
    ROLE_EXCLUSIVITY_PROBES,
    ids=[p[0] for p in ROLE_EXCLUSIVITY_PROBES],
)
def test_06_a_role_outside_the_authorized_list_is_refused_before_the_lookup(
    api, probe, method, path, payload, headers
):
    """Each probe carries a well-formed header pair for a declared role that the
    endpoint does not authorize, and each targets a path identifier that matches
    nothing: the answer is the role refusal rather than the 404 the identifier
    would otherwise earn.

    PRD 2.1: "When the headers are well formed but the named role does not appear in the authorized-role list of the endpoint being called, the answer is `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD 2.6: "The bands are, in order: header validity (`ERR_UNAUTHENTICATED`), role membership (`ERR_ROLE_NOT_PERMITTED`), request shape (`ERR_INVALID_REQUEST`), existence of referenced records (the 404 family above), resource ownership (`ERR_NOT_RESOURCE_OWNER`), state preconditions on the target record, optimistic-concurrency version echoes, and then the four business bands."

    Design: Corner/rbac/roles_cannot_invoke_other_roles_exclusive_operations
    """
    set_clock(api, CLOCK_START)

    response = api.call(method, path, headers=headers, payload=payload)

    validate_error(response, "ERR_ROLE_NOT_PERMITTED", expected_status=403)


def test_07_only_the_program_admin_may_run_the_replacement_container_checkpoint(api):
    """A LogisticsCoordinator is refused on the checkpoint and no run record is
    left behind; the same route answers 201 for the ProgramAdmin.

    PRD 2.1: "When the headers are well formed but the named role does not appear in the authorized-role list of the endpoint being called, the answer is `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD 3.9: "A `ProgramAdmin` runs the replacement-container checkpoint, optionally supplying an `as_of_date` against which due dates are evaluated; when omitted it defaults to the logical clock's UTC date."

    Design: Corner/rbac/roles_cannot_invoke_other_roles_exclusive_operations
    """
    set_clock(api, CLOCK_START)

    refused = api.call(
        "POST",
        "/sharps/auto-ship-runs",
        headers=make_logistics_coordinator_headers(),
        payload={},
    )
    validate_error(refused, "ERR_ROLE_NOT_PERMITTED", expected_status=403)
    assert_total_count(api.list_auto_ship_runs(make_program_admin_headers()), 0)

    accepted = api.create_auto_ship_run({}, make_program_admin_headers())
    run = validate_success(accepted, expected_status=201)
    assert_auto_ship_run(run, enrollments_evaluated=0, kits_created=0)


def test_08_only_the_program_admin_may_drive_the_logical_clock(api):
    """A Patient is refused on the clock-setting capability and the clock is
    unchanged, which the `created_at` of the next created row confirms.

    PRD 2.1: "When the headers are well formed but the named role does not appear in the authorized-role list of the endpoint being called, the answer is `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD 2.4: "A `ProgramAdmin` may set it by supplying a `to_iso8601` instant to the clock-setting capability; the response body for that operation carries no resource, so `data` is an empty object."
    PRD 2.4: "Every resource also carries a `created_at` timestamp: an ISO 8601 UTC instant with three fractional-second digits, read from the logical clock at the moment the row was minted."

    Design: Corner/rbac/roles_cannot_invoke_other_roles_exclusive_operations
    """
    set_clock(api, CLOCK_START)

    refused = api.call(
        "POST",
        "/_clock/set_current_utc",
        headers=make_patient_headers(UNKNOWN_PATIENT_ID),
        payload={"to_iso8601": "2027-01-01T00:00:00Z"},
    )
    validate_error(refused, "ERR_ROLE_NOT_PERMITTED", expected_status=403)

    state_rule = create_california_rule(api)
    _assert_same_instant(state_rule["created_at"], CLOCK_START)


# ---------------------------------------------------------------------------
# Owner scoping for the two entity-backed roles (PRD 2.1)
# ---------------------------------------------------------------------------
def _build_two_owner_world(api) -> dict:
    """Two sponsors, one funded program each.

    Dana is enrolled against Northwind's program and her enrollment waits in
    PENDING_SPONSOR_APPROVAL; Eli is enrolled against Cascadia's program, was
    approved by Cascadia and holds a freshly ISSUED kit.
    """
    ctx = setup_program_foundations(
        api,
        clock=CLOCK_START,
        state_rule_overrides={"household_sharps_classification": "HOUSEHOLD_EXEMPT"},
        sponsor_overrides={
            "legal_name": "Northwind Devices Inc",
            "sponsor_type": "MANUFACTURER",
            "contact_email": "programs@northwind.example",
        },
        program_overrides={
            "program_code": "NW-2026",
            "funding_ceiling_cents": 500000,
            "per_kit_allowance_cents": 5000,
        },
        with_facility=False,
    )
    sponsor_a = ctx["sponsor"]
    program_a = ctx["sponsorship_program"]

    sponsor_b = create_sponsor(
        api,
        legal_name="Cascadia Health Plan",
        sponsor_type="HEALTH_PLAN",
        contact_email="programs@cascadia.example",
    )
    program_b = create_sponsorship_program(
        api,
        sponsor_b["id"],
        program_code="CAS-2026",
        funding_ceiling_cents=500000,
        per_kit_allowance_cents=5000,
    )

    dana = create_eligible_patient(
        api,
        ctx["state_rule"]["id"],
        full_name="Dana Reyes",
        weekly_sharps_count=20,
        contact_email="dana@example.com",
    )
    enrollment_d = create_draft_enrollment(
        api, dana["id"], program_a["id"], cadence_days=30, kits_authorized=3
    )
    enrollment_d = get_success_data(
        api.submit_enrollment(enrollment_d["id"], make_program_admin_headers())
    )

    eli = create_eligible_patient(
        api,
        ctx["state_rule"]["id"],
        full_name="Eli Barnes",
        weekly_sharps_count=20,
        contact_email="eli@example.com",
    )
    enrollment_e = create_active_enrollment(
        api,
        eli["id"],
        program_b["id"],
        sponsor_b["id"],
        cadence_days=30,
        kits_authorized=3,
    )
    kit_e = issue_kit_for(api, ctx, enrollment=enrollment_e)

    return {
        "sponsor_a": sponsor_a,
        "program_a": program_a,
        "sponsor_b": sponsor_b,
        "program_b": program_b,
        "dana": dana,
        "enrollment_d": enrollment_d,
        "eli": eli,
        "enrollment_e": enrollment_e,
        "kit_e": kit_e,
    }


def test_09_a_sponsor_cannot_cast_another_sponsors_funding_decision(api):
    """Cascadia's representative cannot fund an enrollment that hangs off
    Northwind's program, and the refusal leaves no partial write.

    PRD 2.1: "When `X-User-Role` is `SponsorRepresentative`, `X-User-ID` is the `id` of the acting `Sponsor`; ownership checks on any resource that references a `Sponsor` compare the resource's sponsor foreign-key field to `X-User-ID`, whether the sponsor is reached directly from a program or indirectly from an enrollment through its program."
    PRD 2.1: "A violation of either ownership rule — a patient acting on another patient's kit, or a sponsor representative acting on another sponsor's program — is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/entity_backed_roles_cannot_act_on_another_owners_kit_or_program
    """
    world = _build_two_owner_world(api)
    enrollment_d = world["enrollment_d"]

    response = api.record_sponsor_decision(
        enrollment_d["id"],
        sponsor_decision_payload("APPROVE"),
        make_sponsor_representative_headers(world["sponsor_b"]["id"]),
    )

    validate_error(response, "ERR_NOT_RESOURCE_OWNER", expected_status=403)
    assert_enrollment(
        read_enrollment(api, enrollment_d["id"]),
        status="PENDING_SPONSOR_APPROVAL",
        version=enrollment_d["version"],
    )


@pytest.mark.parametrize("version_offset", [0, -1], ids=["fresh_echo", "stale_echo"])
def test_10_a_sponsor_cannot_adjust_another_sponsors_funding_ceiling(
    api, version_offset
):
    """Cascadia's representative cannot move Northwind's funding ceiling. The
    answer is the ownership refusal whether the version echo is fresh or stale,
    because ownership is decided before the version echo is ever consulted.

    PRD 2.1: "A violation of either ownership rule — a patient acting on another patient's kit, or a sponsor representative acting on another sponsor's program — is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
    PRD 2.6: "The bands are, in order: header validity (`ERR_UNAUTHENTICATED`), role membership (`ERR_ROLE_NOT_PERMITTED`), request shape (`ERR_INVALID_REQUEST`), existence of referenced records (the 404 family above), resource ownership (`ERR_NOT_RESOURCE_OWNER`), state preconditions on the target record, optimistic-concurrency version echoes, and then the four business bands."

    Design: Corner/rbac/entity_backed_roles_cannot_act_on_another_owners_kit_or_program
    """
    world = _build_two_owner_world(api)
    program_a = read_program(api, world["program_a"]["id"])

    response = api.create_funding_adjustment(
        program_a["id"],
        funding_adjustment_payload(
            delta_cents=-400000,
            expected_program_version=program_a["version"] + version_offset,
        ),
        make_sponsor_representative_headers(world["sponsor_b"]["id"]),
    )

    validate_error(response, "ERR_NOT_RESOURCE_OWNER", expected_status=403)
    after = read_program(api, program_a["id"])
    assert after["funding_ceiling_cents"] == 500000, (
        f"Expected the ceiling to stay 500000, got {after['funding_ceiling_cents']}"
    )
    assert after["version"] == program_a["version"], (
        f"Expected version {program_a['version']}, got {after['version']}"
    )


def test_11_a_patient_cannot_acknowledge_another_patients_kit(api):
    """Dana cannot acknowledge receipt of Eli's kit; the kit resolves to Eli by
    walking from the kit to its enrollment and from the enrollment to its patient.

    PRD 2.1: "When `X-User-Role` is `Patient`, `X-User-ID` is the `id` of the acting `Patient`; ownership checks on any resource that references a `Patient` compare the resource's patient foreign-key field to `X-User-ID`, which for a kit means walking from the kit to its enrollment and from the enrollment to its patient."
    PRD 3.5: "Both are also available to a `ProgramAdmin` acting on the patient's behalf, and when the acting role is `Patient` the kit must belong to that patient — reached from the kit through its enrollment to the enrollment's patient — with any mismatch refused as `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/entity_backed_roles_cannot_act_on_another_owners_kit_or_program
    """
    world = _build_two_owner_world(api)
    kit_e = world["kit_e"]

    response = api.acknowledge_kit_receipt(
        kit_e["id"], make_patient_headers(world["dana"]["id"])
    )

    validate_error(response, "ERR_NOT_RESOURCE_OWNER", expected_status=403)
    assert_kit(read_kit(api, kit_e["id"]), status="ISSUED")


def test_12_a_patient_cannot_seal_another_patients_kit(api):
    """Dana cannot declare a fill count against Eli's kit, and the kit is left
    exactly where it was.

    PRD 3.5: "Both are also available to a `ProgramAdmin` acting on the patient's behalf, and when the acting role is `Patient` the kit must belong to that patient — reached from the kit through its enrollment to the enrollment's patient — with any mismatch refused as `ERR_NOT_RESOURCE_OWNER`."
    PRD 3.5: "On success the kit moves `ACTIVE_FILLING → SEALED`, both declared values are stored on the kit, and the kit's `version` is incremented by 1."

    Design: Corner/rbac/entity_backed_roles_cannot_act_on_another_owners_kit_or_program
    """
    world = _build_two_owner_world(api)
    kit_e = world["kit_e"]

    response = api.seal_kit(
        kit_e["id"],
        seal_payload(fill_units=60, sealed_gross_weight_grams=1200),
        make_patient_headers(world["dana"]["id"]),
    )

    validate_error(response, "ERR_NOT_RESOURCE_OWNER", expected_status=403)
    assert_kit(read_kit(api, kit_e["id"]), status="ISSUED")


def test_13_ownership_answers_before_the_kit_state_precondition(api):
    """Once Eli has acknowledged his kit, a replayed acknowledgement from Dana is
    still the ownership refusal — not the kit-state refusal the same replay would
    earn from the owning patient.

    PRD 2.1: "Ownership is evaluated after header validity, role membership, payload shape and referenced-resource existence, but before any state precondition."
    PRD 3.5: "Both are also available to a `ProgramAdmin` acting on the patient's behalf, and when the acting role is `Patient` the kit must belong to that patient — reached from the kit through its enrollment to the enrollment's patient — with any mismatch refused as `ERR_NOT_RESOURCE_OWNER`."
    PRD 3.5: "It is legal from `ISSUED` and also from `RETURNED_TO_PATIENT`, and from any other kit state it is refused with `ERR_INVALID_KIT_STATE`; the kit's enrollment must additionally be `ACTIVE`, a paused or terminated enrollment producing `ERR_INVALID_ENROLLMENT_STATE`."

    Design: Corner/rbac/entity_backed_roles_cannot_act_on_another_owners_kit_or_program
    """
    world = _build_two_owner_world(api)
    kit_e = world["kit_e"]

    owner_ack = api.acknowledge_kit_receipt(
        kit_e["id"], make_patient_headers(world["eli"]["id"])
    )
    assert_kit(validate_success(owner_ack, expected_status=200), status="ACTIVE_FILLING")

    replayed = api.acknowledge_kit_receipt(
        kit_e["id"], make_patient_headers(world["dana"]["id"])
    )
    validate_error(replayed, "ERR_NOT_RESOURCE_OWNER", expected_status=403)


def test_14_the_owning_patient_drives_the_kit_through_receipt_and_sealing(api):
    """Positive control: the two operations Dana was refused both succeed for Eli,
    the patient the kit actually belongs to.

    PRD 2.1: "When `X-User-Role` is `Patient`, `X-User-ID` is the `id` of the acting `Patient`; ownership checks on any resource that references a `Patient` compare the resource's patient foreign-key field to `X-User-ID`, which for a kit means walking from the kit to its enrollment and from the enrollment to its patient."
    PRD 3.5: "On success the kit moves `ACTIVE_FILLING → SEALED`, both declared values are stored on the kit, and the kit's `version` is incremented by 1."

    Design: Corner/rbac/entity_backed_roles_cannot_act_on_another_owners_kit_or_program
    """
    world = _build_two_owner_world(api)
    kit_e = world["kit_e"]
    eli_headers = make_patient_headers(world["eli"]["id"])

    acknowledged = validate_success(
        api.acknowledge_kit_receipt(kit_e["id"], eli_headers), expected_status=200
    )
    assert_kit(acknowledged, status="ACTIVE_FILLING")

    sealed = validate_success(
        api.seal_kit(
            kit_e["id"],
            seal_payload(fill_units=60, sealed_gross_weight_grams=1200),
            eli_headers,
        ),
        expected_status=200,
    )
    assert_kit(sealed, status="SEALED", fill_units=60)


def test_15_the_owning_sponsor_casts_the_funding_decision(api):
    """Positive control: Northwind's own representative approves the enrollment
    that Cascadia's representative was refused on.

    PRD 3.3: "Both branches require the enrollment to be in `PENDING_SPONSOR_APPROVAL` — otherwise `ERR_INVALID_ENROLLMENT_STATE` — and both require that the acting `X-User-ID` equal the `sponsor_id` of the program the enrollment is bound to, a mismatch producing `ERR_NOT_RESOURCE_OWNER`."
    PRD 3.3: "On success `APPROVE` moves the enrollment `PENDING_SPONSOR_APPROVAL → ACTIVE`, sets `activated_at` to the current logical-clock instant, copies the submitted note into `sponsor_decision_note`, sets `next_autoship_due_date` to the current logical-clock UTC date so that the enrollment is immediately due for its first replacement container, and cascades the patient `ELIGIBLE → ENROLLED` with the patient's own `version` incremented by 1 — a child activation driving the parent forward."

    Design: Corner/rbac/entity_backed_roles_cannot_act_on_another_owners_kit_or_program
    """
    world = _build_two_owner_world(api)

    response = api.record_sponsor_decision(
        world["enrollment_d"]["id"],
        sponsor_decision_payload("APPROVE"),
        make_sponsor_representative_headers(world["sponsor_a"]["id"]),
    )

    assert_enrollment(validate_success(response, expected_status=200), status="ACTIVE")


def test_16_the_opaque_program_admin_role_sits_outside_the_ownership_rule(api):
    """The ownership rule is scoped to the two entity-backed roles, so the
    ProgramAdmin moves Northwind's ceiling without any owner comparison.

    PRD 2.1: "When `X-User-Role` is `ProgramAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity."
    PRD 2.1: "Two roles are entity-backed."
    PRD 3.2: "The delta is added to `funding_ceiling_cents`, which may rise or fall, but it may never be pushed below the sum of `reserved_cents` and `committed_cents`: a sponsor cannot claw back money that is already reserved against outstanding kits or committed against issued certificates, and an attempt to do so is refused with `ERR_FUNDING_BELOW_OBLIGATIONS` (HTTP 422)."

    Design: Corner/rbac/entity_backed_roles_cannot_act_on_another_owners_kit_or_program
    """
    world = _build_two_owner_world(api)
    program_a = read_program(api, world["program_a"]["id"])

    response = api.create_funding_adjustment(
        program_a["id"],
        funding_adjustment_payload(
            delta_cents=1000, expected_program_version=program_a["version"]
        ),
        make_program_admin_headers(),
    )

    adjusted = validate_success(response, expected_status=200)
    assert adjusted["funding_ceiling_cents"] == 501000, (
        f"Expected the ceiling to reach 501000, got {adjusted['funding_ceiling_cents']}"
    )
