"""Composite setup helpers.

Every fixture builds its preconditions from scratch through the declared API
(the harness reboots the server — and resets the logical clock to
2026-09-01T00:00:00Z — before every test). All setup calls go through
``get_success_data`` so a setup failure raises a clear "Setup step failed"
rather than a confusing assertion error deep in a test.

Identity threading: a fixture that creates a product under
``registrant_headers`` reuses those same headers for every later
ownership-gated call on that product (ownership compares X-User-ID to the
product's registrant_ref).
"""
from typing import Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .calc import (
    add_days,
    expected_annual_fee_cents,
    expected_renewal_fee_cents,
)
from .constants import (
    APPLICATION_FEE_CENTS,
    DEFAULT_CLOCK_ISO,
    REQUIRED_STUDY_TYPES,
    REVIEW_COMPLETION_DAYS,
)
from .factories import (
    make_active_ingredient_payload,
    make_amendment_payload,
    make_application_payload,
    make_bulletin_payload,
    make_certification_payload,
    make_certification_renewal_payload,
    make_clock_payload,
    make_data_call_in_payload,
    make_dci_response_payload,
    make_disposal_payload,
    make_issue_order_payload,
    make_method_change_payload,
    make_new_use_payload,
    make_proceeding_payload,
    make_product_payload,
    make_rate_change_payload,
    make_review_case_payload,
    make_risk_assessment_payload,
    make_state_registration_payload,
    make_study_decision_payload,
    make_study_payload,
    make_submit_payload,
    make_tolerance_payload,
    make_use_site_object,
    make_vacatur_payload,
)
from .test_users import TEST_USERS, user_id_of

ADMIN = TEST_USERS["admin_headers"]
REVIEWER = TEST_USERS["reviewer_1_headers"]
REVIEWER_B = TEST_USERS["reviewer_2_headers"]
ASSESSOR = TEST_USERS["assessor_1_headers"]
ASSESSOR_B = TEST_USERS["assessor_2_headers"]
REGISTRANT = TEST_USERS["registrant_alice_headers"]
REGISTRANT_B = TEST_USERS["registrant_bob_headers"]
STATE_AGENCY = TEST_USERS["state_agency_headers"]
CERT_AUTHORITY = TEST_USERS["certification_authority_headers"]


# ---------------------------------------------------------------------------
# Logical clock (platform endpoint, unprefixed; SystemAdministrator only)
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str, headers: Optional[Dict] = None) -> str:
    """Advance the logical clock (monotonic; equal is an idempotent no-op).
    Runs the pinned four-step sweep server-side. Returns current_utc."""
    resp = api_client.set_clock(make_clock_payload(to_iso8601), headers or ADMIN)
    return get_success_data(resp)["current_utc"]


def reset_clock(headers: Optional[Dict] = None) -> str:
    """Pin the clock to the server default; harmless on a fresh boot because
    an equal set is an idempotent no-op."""
    return set_clock(DEFAULT_CLOCK_ISO, headers)


# ---------------------------------------------------------------------------
# Reference data and product shells
# ---------------------------------------------------------------------------
def create_active_ingredient(headers: Optional[Dict] = None, **overrides) -> Dict:
    resp = api_client.create_active_ingredient(
        make_active_ingredient_payload(**overrides), headers or ADMIN)
    return get_success_data(resp, 201)


def create_product(registrant_headers: Optional[Dict] = None,
                   active_ingredient_id: Optional[str] = None, **overrides) -> Dict:
    """Create an UNREGISTERED product shell. Creates a fresh active
    ingredient first when ``active_ingredient_id`` is not supplied."""
    reg = registrant_headers or REGISTRANT
    if active_ingredient_id is None:
        active_ingredient_id = create_active_ingredient()["id"]
    resp = api_client.create_product(
        make_product_payload(active_ingredient_id, **overrides), reg)
    product = get_success_data(resp, 201)
    assert product["registrant_ref"] == user_id_of(reg), (
        "Setup failed: product registrant_ref must equal the creator's X-User-ID")
    return product


def get_product(product_id: str, headers: Optional[Dict] = None) -> Dict:
    return get_success_data(api_client.get_product(product_id, headers or ADMIN))


def get_product_version(product_id: str, headers: Optional[Dict] = None) -> int:
    return get_product(product_id, headers)["version"]


def list_product_use_sites(product_id: str, headers: Optional[Dict] = None,
                           status: Optional[str] = None) -> List[Dict]:
    params = {"status": status} if status else None
    return get_success_data(
        api_client.list_product_use_sites(product_id, headers or ADMIN, params=params))


def list_product_tolerances(product_id: str, headers: Optional[Dict] = None,
                            status: Optional[str] = None) -> List[Dict]:
    params = {"status": status} if status else None
    return get_success_data(
        api_client.list_product_tolerances(product_id, headers or ADMIN, params=params))


def list_product_review_cases(product_id: str, headers: Optional[Dict] = None,
                              status: Optional[str] = None) -> List[Dict]:
    params = {"status": status} if status else None
    return get_success_data(
        api_client.list_product_review_cases(product_id, headers or ADMIN, params=params))


# ---------------------------------------------------------------------------
# Applications, studies, tolerances
# ---------------------------------------------------------------------------
def create_application(product_id: str, registrant_headers: Optional[Dict] = None,
                       use_pattern: str = "NON_FOOD_USE", **overrides) -> Dict:
    """Create a DRAFT application; mints one PROPOSED use site per element of
    proposed_use_sites."""
    resp = api_client.create_application(
        make_application_payload(product_id, use_pattern, **overrides),
        registrant_headers or REGISTRANT)
    return get_success_data(resp, 201)


def create_study(application_id: Optional[str] = None,
                 data_call_in_id: Optional[str] = None,
                 study_type: str = "EFFICACY",
                 registrant_headers: Optional[Dict] = None, **overrides) -> Dict:
    resp = api_client.create_study(
        make_study_payload(application_id=application_id,
                           data_call_in_id=data_call_in_id,
                           study_type=study_type, **overrides),
        registrant_headers or REGISTRANT)
    return get_success_data(resp, 201)


def create_required_studies(application_id: str, use_pattern: str,
                            registrant_headers: Optional[Dict] = None,
                            residue_commodity: str = "CORN",
                            residue_ppm: float = 0.02) -> Dict[str, Dict]:
    """File one study per required study type for the use pattern.
    Returns {study_type: study_dict}."""
    studies = {}
    for study_type in REQUIRED_STUDY_TYPES[use_pattern]:
        extra = {}
        if study_type == "RESIDUE_CHEMISTRY":
            extra = {"commodity_code": residue_commodity,
                     "field_trial_residue_ppm": residue_ppm}
        studies[study_type] = create_study(
            application_id=application_id, study_type=study_type,
            registrant_headers=registrant_headers, **extra)
    return studies


def accept_study(study_id: str, assessor_headers: Optional[Dict] = None) -> Dict:
    resp = api_client.decide_study(
        study_id, make_study_decision_payload("ACCEPT"), assessor_headers or ASSESSOR)
    return get_success_data(resp)


def reject_study(study_id: str, assessor_headers: Optional[Dict] = None) -> Dict:
    resp = api_client.decide_study(
        study_id, make_study_decision_payload("REJECT"), assessor_headers or ASSESSOR)
    return get_success_data(resp)


def create_tolerance(product_id: str, registrant_headers: Optional[Dict] = None,
                     commodity_code: str = "CORN", tolerance_ppm: float = 0.05,
                     **overrides) -> Dict:
    resp = api_client.create_tolerance(
        make_tolerance_payload(product_id, commodity_code, tolerance_ppm, **overrides),
        registrant_headers or REGISTRANT)
    return get_success_data(resp, 201)


def submit_application(application_id: str, registrant_headers: Optional[Dict] = None,
                       use_pattern: str = "NON_FOOD_USE") -> Dict:
    """First submit with the exact filing fee for the use pattern."""
    resp = api_client.submit_application(
        application_id, registrant_headers or REGISTRANT,
        payload=make_submit_payload(use_pattern))
    return get_success_data(resp)


def resubmit_application(application_id: str,
                         registrant_headers: Optional[Dict] = None) -> Dict:
    """Resubmit from DATA_DEFICIENCY: payment_cents omitted entirely."""
    resp = api_client.submit_application(
        application_id, registrant_headers or REGISTRANT, payload={})
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Risk assessments and the approval decision
# ---------------------------------------------------------------------------
def run_risk_assessment(application_id: str, tier: str = "SCREENING",
                        pct_crop_treated: Optional[float] = None,
                        assessor_headers: Optional[Dict] = None, **overrides) -> Dict:
    payload_kwargs = dict(overrides)
    if pct_crop_treated is not None:
        payload_kwargs["pct_crop_treated"] = pct_crop_treated
    resp = api_client.create_risk_assessment(
        make_risk_assessment_payload(application_id, tier, **payload_kwargs),
        assessor_headers or ASSESSOR)
    return get_success_data(resp, 201)


def list_risk_assessments(application_id: str, headers: Optional[Dict] = None) -> List[Dict]:
    return get_success_data(
        api_client.list_application_risk_assessments(application_id, headers or ADMIN))


def decide_application(application_id: str, decision: str,
                       reviewer_headers: Optional[Dict] = None, **overrides) -> Dict:
    from .factories import make_application_decision_payload
    resp = api_client.decide_application(
        application_id, make_application_decision_payload(decision, **overrides),
        reviewer_headers or REVIEWER)
    return get_success_data(resp)


def approve_application(application_id: str, final_classification: str = "GENERAL_USE",
                        reviewer_headers: Optional[Dict] = None) -> Dict:
    """APPROVE an IN_REVIEW application. The default reviewer (rr-1) differs
    from the default assessor (ra-1), satisfying segregation of duties."""
    return decide_application(
        application_id, "APPROVE", reviewer_headers=reviewer_headers,
        final_classification=final_classification)


def setup_application_in_review(use_pattern: str = "NON_FOOD_USE",
                                registrant_headers: Optional[Dict] = None,
                                accept_studies: bool = False,
                                assessor_headers: Optional[Dict] = None,
                                with_tolerance: bool = False,
                                tolerance_commodity: str = "CORN",
                                tolerance_ppm: float = 0.05,
                                residue_commodity: str = "CORN",
                                residue_ppm: float = 0.02,
                                product_overrides: Optional[Dict] = None,
                                use_site_overrides: Optional[Dict] = None,
                                ) -> Dict:
    """Product + DRAFT application + one study per required type + submit.

    Returns a namespace dict with keys: active_ingredient, product,
    application, studies ({study_type: study}), registrant_headers,
    assessor_headers, tolerance (or None).
    """
    reg = registrant_headers or REGISTRANT
    assr = assessor_headers or ASSESSOR
    ai = create_active_ingredient()
    product = create_product(reg, ai["id"], **(product_overrides or {}))
    sites = None
    if use_site_overrides is not None:
        base_site = make_use_site_object() if use_pattern != "NON_FOOD_USE" else None
        if base_site is None:
            from .factories import make_non_food_use_site_object
            base_site = make_non_food_use_site_object()
        base_site.update(use_site_overrides)
        sites = [base_site]
    app_kwargs = {"use_pattern": use_pattern}
    if sites is not None:
        app_kwargs["proposed_use_sites"] = sites
    application = create_application(product["id"], reg, **app_kwargs)
    studies = create_required_studies(
        application["id"], use_pattern, reg,
        residue_commodity=residue_commodity, residue_ppm=residue_ppm)
    tolerance = None
    if with_tolerance:
        tolerance = create_tolerance(
            product["id"], reg, commodity_code=tolerance_commodity,
            tolerance_ppm=tolerance_ppm)
    if accept_studies:
        studies = {st: accept_study(s["id"], assr) for st, s in studies.items()}
    application = submit_application(application["id"], reg, use_pattern)
    return {
        "active_ingredient": ai,
        "product": product,
        "application": application,
        "studies": studies,
        "tolerance": tolerance,
        "registrant_headers": reg,
        "assessor_headers": assr,
    }


def create_registered_product(use_pattern: str = "NON_FOOD_USE",
                              final_classification: str = "GENERAL_USE",
                              registrant_headers: Optional[Dict] = None,
                              reviewer_headers: Optional[Dict] = None,
                              assessor_headers: Optional[Dict] = None,
                              tolerance_commodity: str = "CORN",
                              tolerance_ppm: float = 0.05,
                              residue_ppm: float = 0.02,
                              product_overrides: Optional[Dict] = None,
                              use_site_overrides: Optional[Dict] = None,
                              assessment_tier: str = "SCREENING",
                              ) -> Dict:
    """Full pipeline: product -> application -> required studies (ACCEPTED)
    -> submit -> SCREENING risk assessment -> APPROVE.

    FOOD_USE/MIXED_USE pipelines also propose a tolerance (the approval gate
    requires one). Returns a namespace dict: active_ingredient, product
    (REGISTERED), application (APPROVED), studies, assessment, tolerance,
    use_sites (ACTIVE), review_case (the auto-created cycle-1 case), and the
    three header sets used.
    """
    reg = registrant_headers or REGISTRANT
    rev = reviewer_headers or REVIEWER
    assr = assessor_headers or ASSESSOR
    needs_tolerance = use_pattern in ("FOOD_USE", "MIXED_USE")
    ctx = setup_application_in_review(
        use_pattern=use_pattern, registrant_headers=reg, accept_studies=True,
        assessor_headers=assr, with_tolerance=needs_tolerance,
        tolerance_commodity=tolerance_commodity, tolerance_ppm=tolerance_ppm,
        residue_ppm=residue_ppm, product_overrides=product_overrides,
        use_site_overrides=use_site_overrides)
    app_id = ctx["application"]["id"]
    ctx["assessment"] = run_risk_assessment(app_id, tier=assessment_tier,
                                            assessor_headers=assr)
    ctx["application"] = approve_application(
        app_id, final_classification=final_classification, reviewer_headers=rev)
    ctx["product"] = get_product(ctx["product"]["id"])
    assert ctx["product"]["status"] == "REGISTERED", (
        f"Setup failed: product not REGISTERED after approval "
        f"(got {ctx['product']['status']})")
    ctx["use_sites"] = list_product_use_sites(ctx["product"]["id"], status="ACTIVE")
    cases = list_product_review_cases(ctx["product"]["id"])
    assert len(cases) == 1 and cases[0]["status"] == "SCHEDULED", (
        "Setup failed: approval must auto-create exactly one SCHEDULED review case")
    ctx["review_case"] = cases[0]
    ctx["reviewer_headers"] = rev
    return ctx


# ---------------------------------------------------------------------------
# Label amendments (OCC-guarded: expected_product_version must match the
# product's current version; each successful filing bumps it by one)
# ---------------------------------------------------------------------------
def file_amendment(product_id: str, amendment_type: str, payload: Dict,
                   registrant_headers: Optional[Dict] = None,
                   expected_product_version: Optional[int] = None) -> Dict:
    """File a label amendment. When expected_product_version is omitted the
    current version is fetched first — the common happy path."""
    reg = registrant_headers or REGISTRANT
    if expected_product_version is None:
        expected_product_version = get_product_version(product_id, reg)
    resp = api_client.create_label_amendment(
        make_amendment_payload(product_id, amendment_type, payload,
                               expected_product_version), reg)
    return get_success_data(resp, 201)


def file_new_use_amendment(product_id: str, registrant_headers: Optional[Dict] = None,
                           use_site: Optional[Dict] = None,
                           commodity_code: Optional[str] = None,
                           tolerance_ppm: Optional[float] = None,
                           expected_product_version: Optional[int] = None) -> Dict:
    return file_amendment(
        product_id, "NEW_USE",
        make_new_use_payload(use_site=use_site, commodity_code=commodity_code,
                             tolerance_ppm=tolerance_ppm),
        registrant_headers, expected_product_version)


def file_rate_change_amendment(product_id: str, use_site_id: str,
                               new_rate: float = 2.0,
                               registrant_headers: Optional[Dict] = None,
                               expected_product_version: Optional[int] = None) -> Dict:
    return file_amendment(
        product_id, "RATE_CHANGE",
        make_rate_change_payload(use_site_id, new_rate),
        registrant_headers, expected_product_version)


def file_method_change_amendment(product_id: str, use_site_id: str,
                                 new_method: str = "AERIAL",
                                 expedited: Optional[bool] = None,
                                 registrant_headers: Optional[Dict] = None,
                                 expected_product_version: Optional[int] = None) -> Dict:
    return file_amendment(
        product_id, "METHOD_CHANGE",
        make_method_change_payload(use_site_id, new_method, expedited),
        registrant_headers, expected_product_version)


def decide_amendment(amendment_id: str, decision: str,
                     reviewer_headers: Optional[Dict] = None, **overrides) -> Dict:
    from .factories import make_amendment_decision_payload
    resp = api_client.decide_label_amendment(
        amendment_id, make_amendment_decision_payload(decision, **overrides),
        reviewer_headers or REVIEWER)
    return get_success_data(resp)


def approve_amendment(amendment_id: str,
                      reviewer_headers: Optional[Dict] = None) -> Dict:
    return decide_amendment(amendment_id, "APPROVE", reviewer_headers)


def get_amendment(amendment_id: str, headers: Optional[Dict] = None) -> Dict:
    return get_success_data(api_client.get_label_amendment(amendment_id, headers or ADMIN))


# ---------------------------------------------------------------------------
# Endangered-species bulletins
# ---------------------------------------------------------------------------
def create_bulletin(product_id: str, reviewer_headers: Optional[Dict] = None,
                    county_fips: str = "06037",
                    restriction_code: str = "SEASONAL_WINDOW",
                    window_start_month: int = 3, window_end_month: int = 8,
                    **overrides) -> Dict:
    resp = api_client.create_bulletin(
        make_bulletin_payload(product_id, county_fips, restriction_code,
                              window_start_month, window_end_month, **overrides),
        reviewer_headers or REVIEWER)
    return get_success_data(resp, 201)


def lift_bulletin(bulletin_id: str, reviewer_headers: Optional[Dict] = None) -> Dict:
    resp = api_client.lift_bulletin(bulletin_id, reviewer_headers or REVIEWER)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Applicator certifications
# ---------------------------------------------------------------------------
def create_certification(state_code: str = "TX",
                         certified_until: str = "2030-01-01T00:00:00Z",
                         cert_headers: Optional[Dict] = None, **overrides) -> Dict:
    resp = api_client.create_certification(
        make_certification_payload(state_code, certified_until, **overrides),
        cert_headers or CERT_AUTHORITY)
    return get_success_data(resp, 201)


def renew_certification(certification_id: str, new_certified_until: str,
                        cert_headers: Optional[Dict] = None) -> Dict:
    resp = api_client.renew_certification(
        certification_id, make_certification_renewal_payload(new_certified_until),
        cert_headers or CERT_AUTHORITY)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Registration review cases and data call-ins
# ---------------------------------------------------------------------------
def create_manual_review_case(product_id: str, opened_at: str,
                              due_at: Optional[str] = None,
                              reviewer_headers: Optional[Dict] = None) -> Dict:
    """Manually schedule a case; due_at defaults server-side to
    opened_at + 180 days when omitted."""
    resp = api_client.create_review_case(
        make_review_case_payload(product_id, opened_at, due_at),
        reviewer_headers or REVIEWER)
    return get_success_data(resp, 201)


def get_review_case(case_id: str, headers: Optional[Dict] = None) -> Dict:
    return get_success_data(api_client.get_review_case(case_id, headers or ADMIN))


def open_case_via_clock(case: Dict, headers: Optional[Dict] = None) -> Dict:
    """Advance the clock to the case's opened_at (sweep step 1 opens every
    SCHEDULED case with opened_at <= now) and return the refreshed case."""
    set_clock(case["opened_at"], headers)
    opened = get_review_case(case["id"], headers)
    assert opened["status"] == "OPEN", (
        f"Setup failed: case not OPEN after clock reached opened_at "
        f"(got {opened['status']})")
    return opened


def setup_open_review_case(product_id: str, opened_at: str = "2027-01-05T00:00:00Z",
                           due_at: Optional[str] = "2027-07-04T00:00:00Z",
                           reviewer_headers: Optional[Dict] = None) -> Dict:
    """Manual case created, then opened by advancing the clock to opened_at."""
    case = create_manual_review_case(product_id, opened_at, due_at, reviewer_headers)
    return open_case_via_clock(case)


def complete_case(case_id: str, reviewer_headers: Optional[Dict] = None) -> Dict:
    resp = api_client.complete_review_case(case_id, reviewer_headers or REVIEWER)
    return get_success_data(resp)


def issue_dci(case_id: str, required_study_types: Sequence[str] = ("TOXICOLOGY",),
              response_deadline: str = "2027-02-09T00:00:00Z",
              reviewer_headers: Optional[Dict] = None) -> Dict:
    """Issue a data call-in against an OPEN/UNDER_REVIEW case (case moves to
    DCI_PENDING). response_deadline must be strictly after the clock."""
    resp = api_client.create_data_call_in(
        make_data_call_in_payload(case_id, required_study_types, response_deadline),
        reviewer_headers or REVIEWER)
    return get_success_data(resp, 201)


def get_dci(dci_id: str, headers: Optional[Dict] = None) -> Dict:
    return get_success_data(api_client.get_data_call_in(dci_id, headers or ADMIN))


def create_dci_study(dci_id: str, study_type: str = "TOXICOLOGY",
                     registrant_headers: Optional[Dict] = None, **overrides) -> Dict:
    """File a study answering a data call-in (parent is the DCI)."""
    return create_study(data_call_in_id=dci_id, study_type=study_type,
                        registrant_headers=registrant_headers, **overrides)


def respond_dci(dci_id: str, study_submission_ids: Sequence[str],
                registrant_headers: Optional[Dict] = None) -> Dict:
    resp = api_client.respond_data_call_in(
        dci_id, make_dci_response_payload(study_submission_ids),
        registrant_headers or REGISTRANT)
    return get_success_data(resp)


def setup_case_with_dci(product_id: str,
                        required_study_types: Sequence[str] = ("TOXICOLOGY",),
                        response_deadline: str = "2027-02-09T00:00:00Z",
                        opened_at: str = "2027-01-05T00:00:00Z",
                        due_at: Optional[str] = "2027-07-04T00:00:00Z",
                        reviewer_headers: Optional[Dict] = None) -> Dict:
    """OPEN case with one ISSUED data call-in (case now DCI_PENDING).
    Returns {"case": ..., "dci": ...}."""
    case = setup_open_review_case(product_id, opened_at, due_at, reviewer_headers)
    dci = issue_dci(case["id"], required_study_types, response_deadline,
                    reviewer_headers)
    return {"case": get_review_case(case["id"]), "dci": dci}


def setup_satisfied_dci(product_id: str,
                        required_study_types: Sequence[str] = ("TOXICOLOGY",),
                        registrant_headers: Optional[Dict] = None,
                        reviewer_headers: Optional[Dict] = None,
                        assessor_headers: Optional[Dict] = None,
                        **case_kwargs) -> Dict:
    """DCI answered and its study ACCEPTED: the call-in is SATISFIED and the
    case returns to UNDER_REVIEW. Returns {"case", "dci", "studies"}."""
    reg = registrant_headers or REGISTRANT
    ctx = setup_case_with_dci(product_id, required_study_types,
                              reviewer_headers=reviewer_headers, **case_kwargs)
    studies = [create_dci_study(ctx["dci"]["id"], st, reg)
               for st in required_study_types]
    dci = respond_dci(ctx["dci"]["id"], [s["id"] for s in studies], reg)
    for s in studies:
        accept_study(s["id"], assessor_headers)
    dci = get_dci(ctx["dci"]["id"])
    assert dci["status"] == "SATISFIED", (
        f"Setup failed: DCI not SATISFIED (got {dci['status']})")
    return {"case": get_review_case(ctx["case"]["id"]), "dci": dci,
            "studies": studies}


def setup_delinquent_dci(product_id: str,
                         required_study_types: Sequence[str] = ("TOXICOLOGY",),
                         response_deadline: str = "2027-02-09T00:00:00Z",
                         past_deadline: str = "2027-02-10T00:00:00Z",
                         reviewer_headers: Optional[Dict] = None,
                         **case_kwargs) -> Dict:
    """DCI left unanswered past its deadline: one clock set past the deadline
    sweeps the DCI to DELINQUENT and fires the referral/auto-suspension
    cascade (case REFERRED, product SUSPENDED). Returns {"case", "dci",
    "product"}."""
    ctx = setup_case_with_dci(product_id, required_study_types, response_deadline,
                              reviewer_headers=reviewer_headers, **case_kwargs)
    set_clock(past_deadline)
    dci = get_dci(ctx["dci"]["id"])
    assert dci["status"] == "DELINQUENT", (
        f"Setup failed: DCI not DELINQUENT after deadline passed (got {dci['status']})")
    return {"case": get_review_case(ctx["case"]["id"]), "dci": dci,
            "product": get_product(product_id)}


# ---------------------------------------------------------------------------
# Cancellation / suspension proceedings
# ---------------------------------------------------------------------------
def initiate_proceeding(product_id: str, proceeding_type: str = "CANCELLATION",
                        reason: str = "RISK_FINDING",
                        initiator_headers: Optional[Dict] = None) -> Dict:
    """Open a proceeding (born INITIATED). The initiator's X-User-ID is
    stamped as initiated_by_ref and anchors the order-issuance SoD check."""
    resp = api_client.create_proceeding(
        make_proceeding_payload(product_id, proceeding_type, reason),
        initiator_headers or REVIEWER)
    return get_success_data(resp, 201)


def hold_hearing(proceeding_id: str, reviewer_headers: Optional[Dict] = None) -> Dict:
    resp = api_client.hear_proceeding(proceeding_id, reviewer_headers or REVIEWER)
    return get_success_data(resp)


def issue_cancellation_order(proceeding_id: str,
                             issuer_headers: Optional[Dict] = None,
                             authorized_units: int = 100,
                             stocks_method: str = "FIXED",
                             depletion_rate_units_per_month: Optional[int] = None
                             ) -> Dict:
    """Issue a CANCELLATION order from HEARING_HELD. The default issuer
    (rr-2) differs from the default initiator (rr-1), satisfying SoD."""
    resp = api_client.issue_order(
        proceeding_id, issuer_headers or REVIEWER_B,
        payload=make_issue_order_payload(
            stocks_method=stocks_method, authorized_units=authorized_units,
            depletion_rate_units_per_month=depletion_rate_units_per_month))
    return get_success_data(resp)


def issue_suspension_order(proceeding_id: str,
                           issuer_headers: Optional[Dict] = None) -> Dict:
    """Issue a SUSPENSION order directly from INITIATED (no hearing, no
    stocks fields)."""
    resp = api_client.issue_order(
        proceeding_id, issuer_headers or REVIEWER_B,
        payload=make_issue_order_payload())
    return get_success_data(resp)


def vacate_proceeding(proceeding_id: str, reviewer_headers: Optional[Dict] = None,
                      **overrides) -> Dict:
    resp = api_client.vacate_proceeding(
        proceeding_id, make_vacatur_payload(**overrides),
        reviewer_headers or REVIEWER)
    return get_success_data(resp)


def get_proceeding(proceeding_id: str, headers: Optional[Dict] = None) -> Dict:
    return get_success_data(api_client.get_proceeding(proceeding_id, headers or ADMIN))


def record_disposal(proceeding_id: str, units: int, method: str = "SALE",
                    reviewer_headers: Optional[Dict] = None) -> Dict:
    resp = api_client.record_disposal(
        proceeding_id, make_disposal_payload(units, method),
        reviewer_headers or REVIEWER)
    return get_success_data(resp)


def setup_effective_cancellation(product_id: str,
                                 authorized_units: int = 100,
                                 stocks_method: str = "FIXED",
                                 depletion_rate_units_per_month: Optional[int] = None,
                                 initiator_headers: Optional[Dict] = None,
                                 issuer_headers: Optional[Dict] = None,
                                 reason: str = "RISK_FINDING") -> Dict:
    """INITIATED -> HEARING_HELD -> EFFECTIVE cancellation order against the
    product (product now CANCELLED). Returns the EFFECTIVE proceeding."""
    proceeding = initiate_proceeding(product_id, "CANCELLATION", reason,
                                     initiator_headers)
    hold_hearing(proceeding["id"], initiator_headers)
    return issue_cancellation_order(
        proceeding["id"], issuer_headers, authorized_units, stocks_method,
        depletion_rate_units_per_month)


def setup_effective_suspension(product_id: str,
                               initiator_headers: Optional[Dict] = None,
                               issuer_headers: Optional[Dict] = None,
                               reason: str = "IMMINENT_HAZARD") -> Dict:
    """INITIATED -> EFFECTIVE suspension order (product now SUSPENDED)."""
    proceeding = initiate_proceeding(product_id, "SUSPENSION", reason,
                                     initiator_headers)
    return issue_suspension_order(proceeding["id"], issuer_headers)


def setup_cancelled_product(authorized_units: int = 100,
                            stocks_method: str = "FIXED",
                            depletion_rate_units_per_month: Optional[int] = None,
                            **pipeline_kwargs) -> Dict:
    """Full pipeline through a CANCELLED product. Returns the
    create_registered_product namespace plus "proceeding" (EFFECTIVE) and
    the refreshed "product" (CANCELLED)."""
    ctx = create_registered_product(**pipeline_kwargs)
    ctx["proceeding"] = setup_effective_cancellation(
        ctx["product"]["id"], authorized_units, stocks_method,
        depletion_rate_units_per_month)
    ctx["product"] = get_product(ctx["product"]["id"])
    assert ctx["product"]["status"] == "CANCELLED", (
        f"Setup failed: product not CANCELLED (got {ctx['product']['status']})")
    return ctx


def setup_suspended_product(**pipeline_kwargs) -> Dict:
    """Full pipeline through a SUSPENDED product via a manual suspension
    order. Namespace plus "proceeding" (EFFECTIVE) and "product"
    (SUSPENDED)."""
    ctx = create_registered_product(**pipeline_kwargs)
    ctx["proceeding"] = setup_effective_suspension(ctx["product"]["id"])
    ctx["product"] = get_product(ctx["product"]["id"])
    assert ctx["product"]["status"] == "SUSPENDED", (
        f"Setup failed: product not SUSPENDED (got {ctx['product']['status']})")
    return ctx


def reinstate_product(product_id: str, reviewer_headers: Optional[Dict] = None) -> Dict:
    resp = api_client.reinstate_product(product_id, reviewer_headers or REVIEWER)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# State registrations
# ---------------------------------------------------------------------------
def apply_state_registration(product_id: str, state_code: str = "TX",
                             registrant_headers: Optional[Dict] = None) -> Dict:
    resp = api_client.create_state_registration(
        make_state_registration_payload(product_id, state_code),
        registrant_headers or REGISTRANT)
    return get_success_data(resp, 201)


def get_state_registration(registration_id: str,
                           headers: Optional[Dict] = None) -> Dict:
    return get_success_data(
        api_client.get_state_registration(registration_id, headers or ADMIN))


def grant_state_registration(registration_id: str,
                             agency_headers: Optional[Dict] = None,
                             additional_restrictions: Optional[List[str]] = None
                             ) -> Dict:
    from .factories import make_state_decision_payload
    overrides = {}
    if additional_restrictions is not None:
        overrides["additional_restrictions"] = additional_restrictions
    resp = api_client.decide_state_registration(
        registration_id, make_state_decision_payload("GRANT", **overrides),
        agency_headers or STATE_AGENCY)
    return get_success_data(resp)


def setup_granted_state_registration(state_code: str = "TX",
                                     classification: str = "GENERAL_USE",
                                     registrant_headers: Optional[Dict] = None,
                                     certify_until: str = "2030-01-01T00:00:00Z",
                                     **pipeline_kwargs) -> Dict:
    """REGISTERED product + GRANTED state registration. For a RESTRICTED_USE
    product a valid applicator certification for the state is created first
    (the grant gate requires one). Namespace plus "state_registration" and
    "certification" (None for GENERAL_USE)."""
    ctx = create_registered_product(final_classification=classification,
                                    registrant_headers=registrant_headers,
                                    **pipeline_kwargs)
    certification = None
    if classification == "RESTRICTED_USE":
        certification = create_certification(state_code, certify_until)
    sreg = apply_state_registration(ctx["product"]["id"], state_code,
                                    ctx["registrant_headers"])
    ctx["state_registration"] = grant_state_registration(sreg["id"])
    ctx["certification"] = certification
    return ctx


def renew_state_registration(registration_id: str,
                             registrant_headers: Optional[Dict] = None,
                             payment_cents: Optional[int] = None,
                             clock_iso: Optional[str] = None) -> Dict:
    """Renew with the exact computed fee. When payment_cents is omitted, the
    fee is recomputed from the row's stamped annual_fee_cents and the
    current logical-clock instant (pass clock_iso if the fixture advanced
    the clock to a value the caller tracks)."""
    from .factories import make_renewal_payload
    if payment_cents is None:
        row = get_state_registration(registration_id)
        if clock_iso is None:
            raise AssertionError(
                "renew_state_registration without payment_cents needs clock_iso")
        payment_cents = expected_renewal_fee_cents(
            row["annual_fee_cents"], row["renewal_due_at"], clock_iso)
    resp = api_client.renew_state_registration(
        registration_id, make_renewal_payload(payment_cents),
        registrant_headers or REGISTRANT)
    return get_success_data(resp)


def expected_state_annual_fee(state_code: str, classification: str) -> int:
    """Convenience re-export for tests: base fee + RUP surcharge."""
    return expected_annual_fee_cents(state_code, classification)


def expected_next_cycle_opened_at(completed_at: str) -> str:
    """opened_at of the auto-scheduled successor case (completed + 5475d)."""
    from .constants import REVIEW_CYCLE_DAYS
    return add_days(completed_at, REVIEW_CYCLE_DAYS)


def expected_case_due_at(opened_at: str) -> str:
    """due_at of a case: opened_at + 180 days."""
    return add_days(opened_at, REVIEW_COMPLETION_DAYS)
