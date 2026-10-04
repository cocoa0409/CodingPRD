"""Queue B — validations section (6 non-stub instances)."""
from test_helpers import (
    create_order_payload,
    list_payload,
    build_user_headers,
    create_drug,
    create_manufacturer,
    create_patient,
    create_pharmacy,
    create_prescriber,
    create_prescription,
    create_license_pending,
    create_sourced_price,
    get_success_data,
    validate_error,
    verify_license,
    reset_clock,
    OPS,
    PHARMACIST,

)


class TestAuthenticationBeforeExistence:

    def test_missing_role_header_is_rejected_before_the_body_is_validated(self, api):
        """PRD §2.1: "A request whose X-User-Role header is absent, or whose
        value is not one of the four declared roles, is refused with
        ERR_MISSING_ROLE_HEADER and HTTP 401."

        Design: Corner/validations/missing_role_header_is_rejected_before_existence_checks
        """
        reset_clock()
        response = api.create_drug({}, headers=build_user_headers("nobody", ""))
        validate_error(response, "ERR_MISSING_ROLE_HEADER")


class TestRolePermission:

    def test_patient_cannot_create_a_manufacturer(self, api):
        """PRD §2.1: "A request whose role is declared but not permitted for the
        operation being attempted is refused with ERR_ROLE_NOT_PERMITTED and
        HTTP 403."

        Design: Corner/validations/patient_role_denied_on_ops_exclusive_manufacturer_creation
        """
        reset_clock()
        patient = create_patient()
        response = api.create_manufacturer(
            {"manufacturer_name": "Bexley Generics"},
            build_user_headers(patient["id"], "Patient"),
        )
        validate_error(response, "ERR_ROLE_NOT_PERMITTED")
        listing = list_payload(api.list_manufacturers(OPS))
        assert listing == []


class TestPatientOwnership:

    def test_a_patient_cannot_read_another_patients_order(self, api):
        """PRD §2.1: "any resource that is patient-scoped — a prescription, an
        order, a claim, or a comparison message addressed in the request — must
        belong to the Patient whose id matches X-User-ID"
        PRD §2.1: "A Patient caller addressing a resource that belongs to a
        different patient is refused with ERR_PATIENT_OWNERSHIP_REQUIRED and
        HTTP 403."

        Design: Corner/validations/patient_ownership_is_enforced_on_another_patients_order
        """
        reset_clock()
        ctx = patient_order_stack(api)
        response = api.get_order(
            ctx["order"]["id"], build_user_headers(ctx["other"]["id"], "Patient"))
        validate_error(response, "ERR_PATIENT_OWNERSHIP_REQUIRED")

    def test_the_owning_patient_reads_the_same_order_successfully(self, api):
        """PRD §2.1: "This ownership rule never applies to Pharmacist or
        PharmacyOps callers, whose identity is opaque."

        Design: Corner/validations/patient_ownership_is_enforced_on_another_patients_order
        """
        reset_clock()
        ctx = patient_order_stack(api)
        data = get_success_data(api.get_order(
            ctx["order"]["id"], build_user_headers(ctx["owner"]["id"], "Patient")))
        assert data["id"] == ctx["order"]["id"]
        prescription = get_success_data(api.get_prescription(
            ctx["prescription"]["id"], OPS))
        assert prescription["patient_id"] == ctx["owner"]["id"]


class TestPrescriberValidity:

    def test_intake_is_refused_while_the_prescriber_is_suspended(self, api):
        """PRD §3.4: "The prescription must be DRAFT; the Prescriber referenced
        by prescriber_id must exist and must be ACTIVE"
        PRD §3.4: "If the prescriber reference is missing, the drug reference is
        missing, or the prescriber is not ACTIVE, the request is refused with
        ERR_PRESCRIBER_ORDER_REQUIRED and HTTP 422"

        Design: Corner/validations/intake_of_a_lisinopril_prescription_blocked_when_prescriber_is_suspended
        """
        reset_clock()
        drug = create_drug(drug_name="Lisinopril", strength="10MG")
        patient = create_patient()
        prescriber = create_prescriber()
        rx = create_prescription(patient["id"], prescriber["id"], drug["id"],
                                 total_refills_authorized=1)
        get_success_data(api.set_prescriber_state(prescriber["id"], "SUSPENDED", OPS))

        response = api.create_intake_request(rx["id"], 30, OPS)
        validate_error(response, "ERR_PRESCRIBER_ORDER_REQUIRED")
        still = get_success_data(api.get_prescription(rx["id"], OPS))
        assert still["status"] == "DRAFT"

    def test_reactivating_the_prescriber_unblocks_the_same_intake(self, api):
        """PRD §3.4: "suspending a prescriber invalidates intake, which is exactly the ACTIVE check §3.4 below enforces at intake routing"

        Design: Corner/validations/intake_of_a_lisinopril_prescription_blocked_when_prescriber_is_suspended
        """
        reset_clock()
        drug = create_drug(drug_name="Lisinopril", strength="10MG")
        patient = create_patient()
        prescriber = create_prescriber()
        rx = create_prescription(patient["id"], prescriber["id"], drug["id"],
                                 total_refills_authorized=1)
        get_success_data(api.set_prescriber_state(prescriber["id"], "SUSPENDED", OPS))
        api.create_intake_request(rx["id"], 30, OPS)
        get_success_data(api.set_prescriber_state(prescriber["id"], "ACTIVE", OPS))

        created = get_success_data(api.create_intake_request(rx["id"], 30, OPS))
        assert created["status"] == "SUBMITTED"


class TestLicenceConflict:

    def test_a_second_active_licence_for_the_same_pair_is_refused(self, api):
        """PRD §3.5: "Filing a second licence for a pair that already carries an
        ACTIVE licence, or filing a replacement whose expiry is not strictly
        after the incumbent's, is refused with ERR_LICENSE_CONFLICT and HTTP
        409."
        PRD §3.5: "the incumbent is set to SUPERSEDED" only when the filing is
        accepted.

        Design: Corner/validations/duplicate_active_licence_filing_is_refused_before_expiry_comparison
        """
        reset_clock()
        pharmacy = create_pharmacy()
        incumbent = create_license_pending(
            pharmacy["id"], state_code="CA", license_number="CA-MP-1001",
            expiry_at="2027-09-01T00:00:00Z")
        verify_license(pharmacy["id"], incumbent["id"])

        response = api.file_license(pharmacy["id"], {
            "state_code": "CA", "license_number": "CA-MP-1002",
            "expiry_at": "2026-12-01T00:00:00Z",
        }, OPS)
        validate_error(response, "ERR_LICENSE_CONFLICT")

    def test_the_refused_filing_leaves_the_incumbent_active_and_alone(self, api):
        """PRD §2.7: "The first identifier in the path that does not correspond
        to a persisted resource terminates the request immediately"

        Design: Corner/validations/duplicate_active_licence_filing_is_refused_before_expiry_comparison
        """
        reset_clock()
        pharmacy = create_pharmacy()
        incumbent = create_license_pending(
            pharmacy["id"], state_code="CA", license_number="CA-MP-1001",
            expiry_at="2027-09-01T00:00:00Z")
        verify_license(pharmacy["id"], incumbent["id"])
        api.file_license(pharmacy["id"], {
            "state_code": "CA", "license_number": "CA-MP-1002",
            "expiry_at": "2026-12-01T00:00:00Z",
        }, OPS)

        still = get_success_data(api.get_license(pharmacy["id"], incumbent["id"], OPS))
        assert still["status"] == "ACTIVE"
        licenses = list_payload(api.list_licenses(pharmacy["id"], OPS))
        assert len(licenses) == 1


class TestSubstantiationExpiry:

    def test_an_expired_record_cannot_be_enabled(self, api):
        """PRD §2.11: "Attempting to enable a substantiation whose valid_until is
        not strictly after the logical clock is refused with
        ERR_SUBSTANTIATION_EXPIRED."
        PRD §3.9: "Three further preconditions hold: the record's status is
        PENDING, its valid_until is strictly after the logical clock, and its
        observed_at is at or before the logical clock."

        Design: Corner/validations/candidate_substantiation_expiry_is_a_deferred_failure_not_a_state_blind_block
        """
        reset_clock()
        ctx = substantiation_ready_order(api)
        # The record is registered with a validity window that has already
        # lapsed at the current logical clock, so it is still PENDING when the
        # enablement attempt is made.
        sub = get_success_data(api.create_substantiation({
            "order_id": ctx["order"]["id"],
            "source_kind": "BENEFIT_INDEX",
            "source_reference": "benefit index ref 402",
            "observed_at": "2026-07-01T00:00:00Z",
            "valid_until": "2026-08-25T00:00:00Z",
        }, OPS))

        response = api.enable_substantiation(
            ctx["order"]["id"], sub["id"], ctx["version"], OPS)
        validate_error(response, "ERR_SUBSTANTIATION_EXPIRED")

        still = get_success_data(api.get_substantiation(sub["id"], OPS))
        assert still["status"] == "PENDING", (
            "the temporal check is evaluated against the clock, not the "
            "record's status"
        )

    def test_the_same_record_enables_while_still_inside_its_validity_window(self, api):
        """PRD §3.9: "the record's status is PENDING, its valid_until is strictly
        after the logical clock, and its observed_at is at or before the logical
        clock"

        Design: Corner/validations/candidate_substantiation_expiry_is_a_deferred_failure_not_a_state_blind_block
        """
        reset_clock()
        ctx = substantiation_ready_order(api)
        sub = get_success_data(api.create_substantiation({
            "order_id": ctx["order"]["id"],
            "source_kind": "BENEFIT_INDEX",
            "source_reference": "benefit index ref 402",
            "observed_at": "2026-08-01T00:00:00Z",
            "valid_until": "2026-09-05T00:00:00Z",
        }, OPS))

        reset_clock("2026-09-02T00:00:00Z")
        enabled = get_success_data(api.enable_substantiation(
            ctx["order"]["id"], sub["id"], ctx["version"], OPS))
        assert enabled["status"] == "ENABLED"


# ─── local helpers ────────────────────────────────────

def patient_order_stack(api):
    """An order owned by one patient, with a second patient for the negative
    ownership case."""
    manufacturer = create_manufacturer()
    drug = create_drug()
    price_row = create_sourced_price(drug["id"], manufacturer["id"],
                                     unit_cost_cents=12, available_units=600,
                                     reliability_tier="A",
                                     packaging="500-count bottle")
    owner = create_patient()
    other = create_patient(full_name="Bo Sandoval", email="bo@example.com")
    prescriber = create_prescriber()
    rx = create_prescription(owner["id"], prescriber["id"], drug["id"],
                             total_refills_authorized=1, ship_state_code="CA")
    rq = get_success_data(api.create_intake_request(rx["id"], 100, OPS))
    get_success_data(api.review_intake_request(rq["id"], PHARMACIST))
    get_success_data(api.accept_intake_request(rq["id"], PHARMACIST))
    drug = get_success_data(api.expand_formulary(drug["id"], OPS))
    pharmacy = create_pharmacy()
    order = get_success_data(api.create_order(create_order_payload(
        rx["id"], rq["id"], pharmacy["id"], price_row["id"], quantity=30), OPS))
    return {"order": order, "owner": owner, "other": other, "prescription": rx}


def substantiation_ready_order(api):
    """A CREATED order with a comparison, plus the order's current version."""
    manufacturer = create_manufacturer()
    drug = create_drug()
    price_row = create_sourced_price(drug["id"], manufacturer["id"],
                                     unit_cost_cents=12, available_units=600,
                                     reliability_tier="A",
                                     packaging="500-count bottle")
    patient = create_patient()
    prescriber = create_prescriber()
    rx = create_prescription(patient["id"], prescriber["id"], drug["id"],
                             total_refills_authorized=1, ship_state_code="CA")
    rq = get_success_data(api.create_intake_request(rx["id"], 100, OPS))
    get_success_data(api.review_intake_request(rq["id"], PHARMACIST))
    get_success_data(api.accept_intake_request(rq["id"], PHARMACIST))
    drug = get_success_data(api.expand_formulary(drug["id"], OPS))
    pharmacy = create_pharmacy()
    order = get_success_data(api.create_order(create_order_payload(
        rx["id"], rq["id"], pharmacy["id"], price_row["id"], quantity=30), OPS))
    return {"order": order,
            "version": get_success_data(api.get_order(order["id"], OPS))["version"]}