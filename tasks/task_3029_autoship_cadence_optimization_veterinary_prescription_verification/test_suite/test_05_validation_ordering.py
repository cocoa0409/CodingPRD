"""Which rule is reached first when a single request violates more than one."""
from test_helpers import TEST_USERS, api_client, validate_error, get_success_data
from test_helpers.fixtures import (
    authorize,
    compose,
    create_site,
    report_passing,
    run_callback_attempt,
    setup_prescription_item,
    setup_prescription_with_callback_attempts,
)


def test_suspended_plan_outranks_the_unverified_prescription(api):
    """PRD §2.12: "a resource whose current status is not the transition's `from`
    status is refused with `ERR_INVALID_STATE` at HTTP 409, except that composition
    against a non-`ACTIVE` plan is refused with the more specific `ERR_PLAN_PAUSED`
    at the same status."
    PRD §2.12: "Business rules then apply in the following order, and the first
    failing rule determines the response."
    PRD §3.4: "Composition is refused outright when the plan is not `ACTIVE`: a plan
    in `PAUSED` reports `ERR_PLAN_PAUSED` with HTTP 409"

    Design: Difficulty/priority_pair_validation_conflict/verification_failure_but_paused_plan_reports_the_state_error
    """
    bundle = setup_prescription_with_callback_attempts(attempts=2)
    plan = bundle["plan"]
    pet = bundle["pet"]
    run_callback_attempt(bundle["rx"])  # third attempt: suspends the plan

    assert get_success_data(api_client.get_plan(
        plan["id"], TEST_USERS["customer_service_headers"]))["plan_status"] == "SUSPENDED"

    resp = compose(plan, pet)
    validate_error(resp, "ERR_PLAN_PAUSED")
    assert resp.status_code == 409

    orders = get_success_data(api_client.list_plan_orders(
        plan["id"], TEST_USERS["customer_service_headers"]))
    assert orders == [], "the refused compose must not have created an order"


def test_state_rule_beats_the_verification_coverage_rule(api):
    """PRD §2.12: "Once identity and addressability are established, a state
    transition request is checked against its governing transition before any
    business rule"
    PRD §3.4: "An absent prescription, or one still in `PENDING_VERIFICATION`,
    `VERIFICATION_IN_PROGRESS` or `VERIFICATION_FAILED`, is refused here with
    `ERR_RX_NOT_VERIFIED` and HTTP 422."

    Design: Difficulty/priority_pair_validation_conflict/verification_failure_but_paused_plan_reports_the_state_error
    """
    bundle = setup_prescription_with_callback_attempts(attempts=2)
    plan = bundle["plan"]
    pet = bundle["pet"]
    run_callback_attempt(bundle["rx"])

    resp = compose(plan, pet)
    actual = resp.json()["data"]["error_id"]
    assert actual == "ERR_PLAN_PAUSED", (
        f"the suspended-plan rule fires before the prescription-coverage rule, got {actual}"
    )
    assert actual != "ERR_RX_NOT_VERIFIED"


def test_retired_prescriber_outranks_the_site_licence_conflict(api):
    """PRD §2.12: "The prescriber gates follow: the authorising prescriber's
    eligibility yields `ERR_PRESCRIBER_NOT_VERIFIED`, a written prescription's email
    mismatch yields `ERR_PRESCRIBER_MISMATCH`, segregation of duties on the
    authorising identity yields `ERR_SUBMITTER_CANNOT_AUTHORIZE`, and the
    controlled-substance registration gate yields `ERR_CSR_AUTH_BLOCKED`. Site
    licensing then yields `ERR_SITE_NOT_LICENSED`, prescription coverage yields
    `ERR_RX_NOT_VERIFIED`"
    PRD §3.3: "the prescription must be in `VERIFICATION_IN_PROGRESS` and the
    prescriber must hold `vet_status` `LISTED` or `VETERINARIAN_VERIFIED`, or the
    attempt is refused with `ERR_PRESCRIBER_NOT_VERIFIED`"
    PRD §3.3: "only the first two may authorise a prescription."

    Design: Difficulty/priority_pair_validation_conflict/inactive_prescriber_outranks_the_site_licence_conflict
    """
    bundle = setup_prescription_item(
        vet_overrides=dict(full_name="Dr Owen Blake", clinic_name="Sierra Vet",
                           clinic_phone="7755550104", vet_email="oblake@sierravet.example",
                           license_number="VET-CA-9004", license_state="CA"),
        pet_overrides=dict(pet_name="Tilly", species="DOG", breed="Corgi",
                           weight_kg=11.0, owner_state="CA"))
    create_site(site_code="RNO4", site_state="NV", licensed_states=["NV"],
                cold_pack_capacity_units=50, csr_registered=True)
    vet = bundle["vet"]
    run_callback_attempt(bundle["rx"])

    get_success_data(api_client.set_vet_status(
        vet["id"], {"vet_status": "RETIRED"}, TEST_USERS["compliance_officer_headers"]), 200)

    resp = authorize(bundle["rx"], vet)
    validate_error(resp, "ERR_PRESCRIBER_NOT_VERIFIED")
    assert resp.status_code == 422

    rx_after = get_success_data(api_client.get_prescription(
        bundle["rx"]["id"], TEST_USERS["pharmacy_technician_headers"]))
    assert rx_after["rx_status"] == "VERIFICATION_IN_PROGRESS", (
        "the refused authorisation leaves the prescription where it was"
    )


def test_prescriber_eligibility_is_named_in_preference_to_site_licensing(api):
    """PRD §3.7: "a `CII` prescription may not be authorised at all unless every site
    whose `licensed_states` contains the owning pet's owner state holds a
    controlled-substance registration."
    PRD §3.3: "for a `CII` schedule, every site licensed for the owning pet's owner
    state must hold a controlled-substance registration, or the attempt is refused
    with `ERR_CSR_AUTH_BLOCKED`."

    Design: Difficulty/priority_pair_validation_conflict/inactive_prescriber_outranks_the_site_licence_conflict
    """
    bundle = setup_prescription_item(
        pet_overrides=dict(pet_name="Tilly", species="DOG", breed="Corgi",
                           weight_kg=11.0, owner_state="CA"))
    create_site(site_code="RNO4", site_state="NV", licensed_states=["NV"],
                cold_pack_capacity_units=50, csr_registered=True)
    vet = bundle["vet"]
    run_callback_attempt(bundle["rx"])

    get_success_data(api_client.set_vet_status(
        vet["id"], {"vet_status": "RETIRED"}, TEST_USERS["compliance_officer_headers"]), 200)
    resp = authorize(bundle["rx"], vet)

    assert resp.json()["data"]["error_id"] == "ERR_PRESCRIBER_NOT_VERIFIED"
    assert resp.json()["data"]["error_id"] != "ERR_SITE_NOT_LICENSED"
    assert resp.status_code == 422


def test_missing_role_header_precedes_path_existence(api):
    """PRD §2.12: "Authentication precedes everything. Header presence and role
    recognition are decided before path resolution, so a request with no usable role
    context fails with `ERR_MISSING_USER_CONTEXT` even when the path it names does
    not exist"
    PRD §2.1: "A request that omits either header, or that supplies a `X-User-Role`
    value which does not name one of the roles declared below, is rejected with
    `ERR_MISSING_USER_CONTEXT` and an HTTP 401 status."

    Design: Corner/validations/missing_user_context_header_returns_401_before_existence
    """
    resp = api_client.get_pet("00000000-0000-4000-8000-000000000000",
                              {"Content-Type": "application/json"})
    validate_error(resp, "ERR_MISSING_USER_CONTEXT")
    assert resp.status_code == 401