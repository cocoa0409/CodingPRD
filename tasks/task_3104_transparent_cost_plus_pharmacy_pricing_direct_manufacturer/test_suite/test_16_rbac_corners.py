"""Queue B — rbac section (4 non-stub instances)."""
from test_helpers import (
    build_user_headers,
    create_drug,
    create_manufacturer,
    create_patient,
    create_prescriber,
    create_prescription,
    create_sourced_price,
    get_success_data,
    list_claims_of,
    validate_error,
    validate_success,
    reset_clock,
    OPS,
    PHARMACIST,
)


class TestPharmacistCannotAdmitToFormulary:

    def test_formulary_admission_is_refused_for_a_pharmacist(self, api):
        """PRD §2.1: "The Pharmacist role exclusively owns intake review, intake acceptance and rejection, prescription termination, drug substitution, and refill authorisation and denial."
        PRD §2.1: "A request whose role is declared but not permitted for the
        operation being attempted is refused with ERR_ROLE_NOT_PERMITTED and
        HTTP 403."

        Design: Corner/rbac/pharmacist_cannot_admit_a_drug_to_the_formulary
        """
        reset_clock()
        ctx = gate_passing_drug(api)
        response = api.expand_formulary(ctx["drug"]["id"], PHARMACIST)
        validate_error(response, "ERR_ROLE_NOT_PERMITTED")
        still = get_success_data(api.get_drug(ctx["drug"]["id"], OPS))
        assert still["state"] == "NON_FORMULARY"

    def test_the_same_pharmacist_still_performs_its_own_clinical_write(self, api):
        """PRD §2.1: "The Pharmacist role exclusively owns intake review, intake
        acceptance and rejection"

        Design: Corner/rbac/pharmacist_cannot_admit_a_drug_to_the_formulary
        """
        reset_clock()
        ctx = gate_passing_drug(api)
        accepted = validate_success(
            api.accept_intake_request(ctx["request"]["id"], PHARMACIST), 200)
        assert accepted["status"] == "ACCEPTED"


class TestPatientCannotAuthoriseARefill:

    def test_refill_authorisation_is_refused_for_a_patient(self, api):
        """PRD §3.4: "Authorising a refill requires the claim to be PENDING"
        PRD §4: "| POST | `/claims/{id}/refill-authorizations` | Authorise the next refill of a prescription | Pharmacist |"

        Design: Corner/rbac/patient_cannot_reach_pharmacist_exclusive_refill_authorization
        """
        reset_clock()
        ctx = pending_claim_stack(api)
        response = api.authorize_refill(
            ctx["claim"]["id"], 30,
            build_user_headers(ctx["patient"]["id"], "Patient"))
        validate_error(response, "ERR_ROLE_NOT_PERMITTED")

    def test_the_same_patient_still_reads_the_claim(self, api):
        """PRD §4: "| GET | `/claims/{id}` | Get a refill authorisation | PharmacyOps, Pharmacist, Patient |"

        Design: Corner/rbac/patient_cannot_reach_pharmacist_exclusive_refill_authorization
        """
        reset_clock()
        ctx = pending_claim_stack(api)
        data = get_success_data(api.get_claim(
            ctx["claim"]["id"], build_user_headers(ctx["patient"]["id"], "Patient")))
        assert data["status"] == "PENDING", (
            "the read succeeded for a role that cannot perform the write on the "
            "same resource"
        )


class TestPharmacyOpsCannotAuthoriseARefill:

    def test_refill_authorisation_is_refused_for_pharmacy_ops(self, api):
        """PRD §2.1: "PharmacyOps owns manufacturer registration and state, drug creation, price-row registration and every move along the price and sourcing dimensions, formulary admission and delisting, pharmacy and licence filing, patient and prescriber registration, order arithmetic, order payment, fulfilment, dispatch, delivery, cancellation, and the entire substantiation registry."
        PRD §2.1: "A request whose role is declared but not permitted for the
        operation being attempted is refused with ERR_ROLE_NOT_PERMITTED and
        HTTP 403."

        Design: Corner/rbac/pharmacyops_cannot_authorise_a_refill_even_though_it_owns_fulfilment
        """
        reset_clock()
        ctx = pending_claim_stack(api)
        response = api.authorize_refill(ctx["claim"]["id"], 30, OPS)
        validate_error(response, "ERR_ROLE_NOT_PERMITTED")
        still = get_success_data(api.get_claim(ctx["claim"]["id"], OPS))
        assert still["status"] == "PENDING"
        assert still["reserved_quantity"] == 0

    def test_pharmacy_ops_still_performs_its_own_exclusive_write(self, api):
        """PRD §4: "| POST | `/formularies/{id}/expansion` | Admit a drug to the formulary | PharmacyOps |"

        Design: Corner/rbac/pharmacyops_cannot_authorise_a_refill_even_though_it_owns_fulfilment
        """
        reset_clock()
        ctx = gate_passing_drug(api)
        admitted = get_success_data(api.expand_formulary(ctx["drug"]["id"], OPS))
        assert admitted["state"] == "FORMULARY"


class TestAnonymousAndHeaderlessCallers:

    def test_anonymous_is_refused_on_a_drug_read(self, api):
        """PRD §2.1: "Anonymous is an unauthenticated caller permitted only on
        the liveness probe; every other operation requires a declared role."
        PRD §4: "| GET | `/drugs` | List drugs, filterable by formulary state | PharmacyOps, Pharmacist, Patient |"

        Design: Corner/rbac/anonymous_reaches_only_the_health_probe
        """
        reset_clock()
        response = api.list_drugs(build_user_headers("anonymous-caller", "Anonymous"))
        validate_error(response, "ERR_ROLE_NOT_PERMITTED")

    def test_an_absent_role_header_is_a_different_error_from_a_rising_role(self, api):
        """PRD §2.1: "A request that carries no declarable role at all — the
        X-User-Role header is simply absent — is indistinguishable from one
        carrying a bogus value, and both are refused with ERR_MISSING_ROLE_HEADER
        before any other consideration."

        Design: Corner/rbac/anonymous_reaches_only_the_health_probe
        """
        reset_clock()
        response = api.list_drugs(build_user_headers("nobody", ""))
        validate_error(response, "ERR_MISSING_ROLE_HEADER")


# ─── local helpers ────────────────────────────────────

def gate_passing_drug(api):
    """A NON_FORMULARY drug whose pool and demand satisfy the admission gate,
    with an intake request left at UNDER_REVIEW so the Pharmacist's own
    exclusive write can be exercised."""
    manufacturer = create_manufacturer()
    drug = create_drug()
    create_sourced_price(drug["id"], manufacturer["id"], unit_cost_cents=12,
                         available_units=500, reliability_tier="C",
                         packaging="500-count bottle")
    patient = create_patient()
    prescriber = create_prescriber()
    rx = create_prescription(patient["id"], prescriber["id"], drug["id"],
                             total_refills_authorized=1, ship_state_code="CA")
    rq = get_success_data(api.create_intake_request(rx["id"], 250, OPS))
    get_success_data(api.review_intake_request(rq["id"], PHARMACIST))
    return {
        "drug": drug,
        "patient": patient,
        "prescription": rx,
        "request": get_success_data(api.get_intake_request(rq["id"], OPS)),
    }


def pending_claim_stack(api):
    """An ACTIVE prescription on a SOURCED drug with its first PENDING claim."""
    manufacturer = create_manufacturer()
    drug = create_drug()
    create_sourced_price(drug["id"], manufacturer["id"], unit_cost_cents=12,
                         available_units=600, reliability_tier="A",
                         packaging="500-count bottle")
    patient = create_patient()
    prescriber = create_prescriber()
    rx = create_prescription(patient["id"], prescriber["id"], drug["id"],
                             total_refills_authorized=2, ship_state_code="CA")
    rq = get_success_data(api.create_intake_request(rx["id"], 100, OPS))
    get_success_data(api.review_intake_request(rq["id"], PHARMACIST))
    get_success_data(api.accept_intake_request(rq["id"], PHARMACIST))
    claims = list_claims_of(rx["id"])
    return {"drug": drug, "patient": patient, "claim": claims[0]}