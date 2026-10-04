"""Eligibility screening: screen creation, verification and determination."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, set_clock,
    create_client, create_funder, create_program, create_grant, open_assessment,
    open_screen, verify_screen, submit_assessment, route_assessment, determine_screen,
    setup_landscape, refresh_screen, setup_capacity_pair, ApiErrorId,
    INTAKE, PROGRAM, FINANCE, COMPLIANCE,
)


def test_eligibility_screen_creation_links_assessment_program_and_grant():
    """PRD §3.4: "Opening a screen sets `determination` to `PENDING`,
    `verification_state` to `UNVERIFIED`, and `screened_at` to the current
    logical clock."
    PRD §3.4: "The screen records the `program_id` being screened for, the
    `grant_id` whose eligibility rules govern it".

    Design: Corner/entities/eligibility_screen_creation_links_assessment_program_and_grant
    """
    set_clock("2026-09-01T00:00:00Z")
    funder = create_funder()
    program = create_program()
    grant = create_grant(funder["id"], program["id"], grant_code="G-1")
    client = create_client()
    assessment = open_assessment(client["id"])

    resp = api_client.create_eligibility_screen(
        assessment["id"],
        {
            "program_id": program["id"],
            "grant_id": grant["id"],
            "verified_income_cents": 120000,
            "household_size_at_screen": 2,
        },
        INTAKE,
    )
    data = validate_success(resp, expected_status=201)
    assert data["determination"] == "PENDING"
    assert data["verification_state"] == "UNVERIFIED"
    assert data["screened_at"] == "2026-09-01T00:00:00.000Z"
    assert data["intake_assessment_id"] == assessment["id"]
    assert data["program_id"] == program["id"]
    assert data["grant_id"] == grant["id"]


def test_eligibility_screen_verification_expires_180_days_after_screened_at():
    """PRD §3.4: "A screen whose `verification_state` is `VERIFIED` and whose
    `determination` is still `PENDING` is set to `verification_state` of
    `EXPIRED` when the logical clock reaches or passes 180 days after
    `screened_at`."
    PRD §3.4: "Expiry touches only the verification dimension; the determination
    stays `PENDING`, and the screen must be re-verified before it can be
    determined."

    Design: Corner/state_machines/eligibility_screen_verification_expires_180_days_after_screened_at
    """
    set_clock("2026-09-01T00:00:00Z")
    funder = create_funder()
    program = create_program()
    grant = create_grant(funder["id"], program["id"], grant_code="G-1")
    client = create_client()
    assessment = open_assessment(client["id"])
    screen = open_screen(assessment["id"], program["id"], grant["id"])
    verify_screen(screen["id"])

    set_clock("2027-02-27T00:00:00Z")  # 179 days after screened_at
    open_screen(assessment["id"], program["id"], grant["id"], verified_income_cents=100000)
    before = refresh_screen(screen["id"])
    assert before["verification_state"] == "VERIFIED", (
        "at screened_at + 179 days the verification is still live"
    )

    set_clock("2027-03-02T00:00:00Z")  # past the 180-day boundary
    newest = open_screen(assessment["id"], program["id"], grant["id"],
                         verified_income_cents=110000)

    after = refresh_screen(screen["id"])
    assert after["verification_state"] == "EXPIRED"
    assert after["determination"] == "PENDING", "expiry leaves the determination dimension alone"
    newest_after = refresh_screen(newest["id"])
    assert newest_after["verification_state"] == "UNVERIFIED"


def test_federal_funded_screen_requires_nondiscrimination_attestation():
    """PRD §2.8: "A program must carry `nondiscrimination_attested` true before
    it may be screened or enrolled under a funder whose `funder_type` is
    `FEDERAL` or `STATE`."
    PRD §2.8: "A request that screens or enrolls against an unattested program
    under such a funder is rejected with `ERR_NONDISCRIMINATION_VIOLATION`
    (HTTP 422)."

    Design: Corner/validations/federal_funded_screen_requires_nondiscrimination_attestation
    """
    set_clock("2026-09-01T00:00:00Z")
    federal = create_funder(name="Federal HHS", funder_type="FEDERAL",
                            allow_faith_based_activity=False,
                            requires_time_and_effort_documentation=True,
                            max_admin_rate_pct=0.10, fiscal_year_start_month=10)
    diocesan = create_funder(name="Diocesan Fund", funder_type="DIOCESAN",
                             allow_faith_based_activity=True)
    program = create_program(name="Refugee Welcome", service_domain="REFUGEE",
                             nondiscrimination_attested=False, match_eligible=False)
    grant_fed = create_grant(federal["id"], program["id"], grant_code="G-FED",
                             restricted_purpose="REFUGEE_RESETTLEMENT")
    grant_dio = create_grant(diocesan["id"], program["id"], grant_code="G-DIO",
                             allocation_rank=2, restricted_purpose="REFUGEE_RESETTLEMENT")
    client = create_client(full_name="Yusuf Kaya", immigration_status="REFUGEE",
                           household_size=4)
    assessment = open_assessment(client["id"], presenting_needs=["resettlement support"],
                                 requested_domains=["REFUGEE"])

    refused = api_client.create_eligibility_screen(
        assessment["id"],
        {"program_id": program["id"], "grant_id": grant_fed["id"],
         "verified_income_cents": 50000, "household_size_at_screen": 4},
        INTAKE,
    )
    validate_error(refused, ApiErrorId.ERR_NONDISCRIMINATION_VIOLATION)

    accepted = api_client.create_eligibility_screen(
        assessment["id"],
        {"program_id": program["id"], "grant_id": grant_dio["id"],
         "verified_income_cents": 50000, "household_size_at_screen": 4},
        INTAKE,
    )
    validate_success(accepted, expected_status=201)


def test_eligibility_determination_before_parent_assessment_routes_is_rejected():
    """PRD §3.4: "A screen determined while the parent assessment is not
    `ROUTED` is refused with `ERR_INTAKE_NOT_ROUTED`; a screen opened or
    determined in violation of §2.7 is refused with
    `ERR_CONFIDENTIALITY_SCOPE_DENIED`; and one opened against an unattested
    program under a federal or state funder is refused with
    `ERR_NONDISCRIMINATION_VIOLATION`."
    PRD §2.10: "`ERR_INTAKE_NOT_ROUTED` (HTTP 409) fires when a determination is
    attempted on an eligibility screen whose parent assessment is not in
    `ROUTED` status."

    Design: Corner/validations/eligibility_determination_before_parent_assessment_routes_is_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    funder = create_funder()
    program = create_program()
    grant = create_grant(funder["id"], program["id"], grant_code="G-1")
    client = create_client()
    assessment = open_assessment(client["id"])
    screen = open_screen(assessment["id"], program["id"], grant["id"])
    verify_screen(screen["id"])

    resp = api_client.determine_eligibility_screen(screen["id"], {"determination": "ELIGIBLE"},
                                                   COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_INTAKE_NOT_ROUTED)

    after = refresh_screen(screen["id"])
    assert after["determination"] == "PENDING"
    assert after["verification_state"] == "VERIFIED"
    listed = get_success_data(api_client.list_enrollments(PROGRAM, {"client_id": client["id"]}))
    assert listed == [], "the refused determination creates no enrollment"


def test_confidentiality_protected_consent_expiry_boundary_denies_late_determination():
    """PRD §2.7: "A `PROTECTED` client is permitted only when the target domain
    appears in the client's `consent_scope` and the logical clock has not passed
    `consent_expires_on`."
    PRD §2.7: "A refusal carries `ERR_CONFIDENTIALITY_SCOPE_DENIED` with HTTP
    403, and it guards four operations: opening an eligibility screen under an
    assessment, recording a determination on an eligibility screen, creating an
    enrollment directly, and reading a client record."

    Design: Corner/validations/confidentiality_protected_consent_expiry_boundary_denies_late_determination
    """
    set_clock("2026-09-10T00:00:00Z")
    funder = create_funder()
    program = create_program()
    grant = create_grant(funder["id"], program["id"], grant_code="G-1")
    client = create_client(confidentiality_tier="PROTECTED", consent_scope=["HOUSING"],
                           consent_expires_on="2026-09-15T00:00:00Z")
    assessment = open_assessment(client["id"], assessment_date="2026-09-10T00:00:00Z")
    inside = open_screen(assessment["id"], program["id"], grant["id"])
    later = open_screen(assessment["id"], program["id"], grant["id"],
                        verified_income_cents=110000)
    verify_screen(inside["id"])
    verify_screen(later["id"])
    submit_assessment(assessment["id"])
    route_assessment(assessment["id"])

    first = determine_screen(inside["id"], "ELIGIBLE")
    assert first["determination"] == "ELIGIBLE", "the consent window is still open on 2026-09-10"

    set_clock("2026-09-20T00:00:00Z")  # past consent_expires_on
    resp = api_client.determine_eligibility_screen(later["id"], {"determination": "ELIGIBLE"},
                                                   COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_CONFIDENTIALITY_SCOPE_DENIED)

    after = refresh_screen(later["id"])
    assert after["determination"] == "PENDING"
    assert after["verification_state"] == "VERIFIED"


def test_program_capacity_refuses_late_screen_determined_after_capacity_reached():
    """PRD §3.4: "An attempt to consume a slot when `enrolled_slots` is already
    at or above `capacity_slots` is refused with `ERR_PROGRAM_CAPACITY_EXCEEDED`
    (HTTP 409), and that refusal guards both direct enrollment creation and
    eligible determinations."

    Design: Corner/calculations/program_capacity_refuses_late_screen_determined_after_capacity_reached
    """
    set_clock("2026-09-01T00:00:00Z")
    landscape = setup_landscape(program={"capacity_slots": 1})
    client = create_client()
    assessment = open_assessment(client["id"])
    first = open_screen(assessment["id"], landscape["program"]["id"], landscape["grant"]["id"])
    verify_screen(first["id"])
    submit_assessment(assessment["id"])
    route_assessment(assessment["id"])
    determined = determine_screen(first["id"], "ELIGIBLE")
    assert determined["determination"] == "ELIGIBLE"
    assert determined["denial_reason_code"] is None

    second = open_screen(assessment["id"], landscape["program"]["id"],
                         landscape["grant"]["id"], verified_income_cents=130000)
    verify_screen(second["id"])

    resp = api_client.determine_eligibility_screen(second["id"], {"determination": "ELIGIBLE"},
                                                   COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_CAPACITY_EXCEEDED)

    after = refresh_screen(second["id"])
    assert after["determination"] == "PENDING"
    assert after["verification_state"] == "VERIFIED"


def test_grant_posture_recompute_on_open_grant_keeps_open_and_bumps_version():
    """PRD §2.12: "A finance officer or a compliance officer may also force a
    recomputation of one grant on demand, which recalculates `burn_ratio`,
    applies whatever posture transition the new ratio implies, and returns the
    grant."
    PRD §2.4: "When the server recalculates a computed value — a grant's
    posture, a program's slot counters, a client's open enrollment count, a
    delivery's braided totals — that recalculation updates the owning row's
    `updated_at` and increments its `version`."

    Design: Corner/state_machines/grant_posture_recompute_on_open_grant_keeps_open_and_bumps_version
    """
    set_clock("2026-09-01T00:00:00Z")
    landscape = setup_landscape()
    grant = landscape["grant"]

    resp = api_client.recompute_grant_posture(grant["id"], FINANCE)
    data = validate_success(resp)
    assert data["status"] == "OPEN", "a grant below the throttle point stays OPEN"
    assert data["burn_ratio"] == 0.0
    assert data["version"] == grant["version"] + 1, "a recomputation is a mutation like any other"
