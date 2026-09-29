"""
Composite state builders.

The runner restarts the service before every individual test, so each test opens
against an empty database and must build whatever state it needs through the
public endpoints.  ``World`` wraps that with one method per creation step, and the
two subclasses expose the two standing casts as lazily built, memoised
properties: nothing is created until a test touches it, and touching it twice
returns the same row rather than repeating the write.

Phasing matters.  A step that would invalidate an earlier step of the same chain
is never bundled with it — quarantine, recall, suspension and clock movement are
always separate calls a test makes for itself, so reusing a property can never
undo what an earlier property established.
"""

from typing import Any, Callable, Dict, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from . import factories as f
from .constants import DEFAULT_CLOCK
from .test_users import (
    admin_headers,
    billing_headers,
    compliance_headers,
    patient_headers,
    specialist_headers,
    tech_headers,
)


class World:
    """Builders for one test's state, each returning the created resource dict."""

    def __init__(self, api: ApiClient) -> None:
        self.api = api
        self._memo: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Memo
    # ------------------------------------------------------------------
    def _once(self, key: str, build: Callable[[], Any]) -> Any:
        if key not in self._memo:
            self._memo[key] = build()
        return self._memo[key]

    # ------------------------------------------------------------------
    # Clock
    # ------------------------------------------------------------------
    def set_clock(self, current_utc: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.set_clock(f.clock_payload(current_utc), admin_headers())
        )

    # ------------------------------------------------------------------
    # Reference data
    # ------------------------------------------------------------------
    def payer(self, **kwargs: Any) -> Dict[str, Any]:
        return get_success_data(self.api.create_payer(f.payer_payload(**kwargs), admin_headers()))

    def drug(self, **kwargs: Any) -> Dict[str, Any]:
        return get_success_data(self.api.create_drug(f.drug_payload(**kwargs), admin_headers()))

    def biosimilar(self, **kwargs: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_drug(f.biosimilar_payload(**kwargs), admin_headers())
        )

    def policy(self, **kwargs: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_payer_drug_policy(f.policy_payload(**kwargs), admin_headers())
        )

    def patient(self, **kwargs: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_patient(f.patient_payload(**kwargs), admin_headers())
        )

    def clinician(self, **kwargs: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_clinician(f.clinician_payload(**kwargs), admin_headers())
        )

    # ------------------------------------------------------------------
    # Imaging and plans
    # ------------------------------------------------------------------
    def imaging(self, *, clinician_id: str, **kwargs: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_imaging_study(
                f.imaging_payload(**kwargs), specialist_headers(clinician_id)
            )
        )

    def plan(self, *, clinician_id: str, **kwargs: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_treatment_plan(f.plan_payload(**kwargs), specialist_headers(clinician_id))
        )

    def activate_plan(
        self, plan_id: str, *, clinician_id: str, baseline_imaging_study_id: str
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.activate_treatment_plan(
                plan_id,
                f.plan_activate_payload(baseline_imaging_study_id=baseline_imaging_study_id),
                specialist_headers(clinician_id),
            )
        )

    # ------------------------------------------------------------------
    # Inventory
    # ------------------------------------------------------------------
    def lot(self, **kwargs: Any) -> Dict[str, Any]:
        return get_success_data(self.api.create_drug_lot(f.lot_payload(**kwargs), tech_headers()))

    # ------------------------------------------------------------------
    # Authorization
    # ------------------------------------------------------------------
    def authorization(self, *, treatment_plan_id: str, expected_treatment_plan_version: int) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_prior_authorization(
                f.authorization_payload(
                    treatment_plan_id=treatment_plan_id,
                    expected_treatment_plan_version=expected_treatment_plan_version,
                ),
                billing_headers(),
            )
        )

    def submit_authorization(self, pa_id: str, **kwargs: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.submit_prior_authorization(
                pa_id, f.authorization_submit_payload(**kwargs), billing_headers()
            )
        )

    def approve_authorization(
        self, pa_id: str, *, auth_number: str, approved_injections: int, effective_date: str
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.decide_prior_authorization(
                pa_id,
                f.approval_decision_payload(
                    auth_number=auth_number,
                    approved_injections=approved_injections,
                    effective_date=effective_date,
                ),
                billing_headers(),
            )
        )

    def approved_authorization(
        self,
        *,
        treatment_plan_id: str,
        expected_treatment_plan_version: int,
        auth_number: str,
        approved_injections: int,
        effective_date: str,
    ) -> Dict[str, Any]:
        """Create, submit and approve one authorization; returns the approved row."""
        pa = self.authorization(
            treatment_plan_id=treatment_plan_id,
            expected_treatment_plan_version=expected_treatment_plan_version,
        )
        self.submit_authorization(pa["id"])
        return self.approve_authorization(
            pa["id"],
            auth_number=auth_number,
            approved_injections=approved_injections,
            effective_date=effective_date,
        )

    # ------------------------------------------------------------------
    # Encounters
    # ------------------------------------------------------------------
    def encounter(self, *, clinician_id: str, **kwargs: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_injection_encounter(
                f.encounter_payload(**kwargs), specialist_headers(clinician_id)
            )
        )

    def document(self, encounter_id: str, *, clinician_id: str, **kwargs: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.document_injection_encounter(
                encounter_id, f.document_payload(**kwargs), specialist_headers(clinician_id)
            )
        )

    def attest(
        self, encounter_id: str, *, clinician_id: str, attested_wasted_ml: float
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.attest_wastage(
                encounter_id,
                f.attest_payload(attested_wasted_ml=attested_wasted_ml),
                specialist_headers(clinician_id),
            )
        )

    # ------------------------------------------------------------------
    # Revenue cycle
    # ------------------------------------------------------------------
    def claim(self, *, injection_encounter_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_claim(
                f.claim_payload(injection_encounter_id=injection_encounter_id), billing_headers()
            )
        )

    def submit_claim(self, claim_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.submit_claim(claim_id, {}, billing_headers()))

    def remit(self, claim_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return get_success_data(self.api.post_remittance(claim_id, payload, billing_headers()))

    def enrollment(self, **kwargs: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_assistance_enrollment(f.enrollment_payload(**kwargs), billing_headers())
        )

    def approve_enrollment(self, enrollment_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.approve_assistance_enrollment(enrollment_id, {}, billing_headers())
        )

    def active_enrollment(self, **kwargs: Any) -> Dict[str, Any]:
        """Create and approve one enrollment; returns the ``ACTIVE`` row."""
        row = self.enrollment(**kwargs)
        return self.approve_enrollment(row["id"])

    # ------------------------------------------------------------------
    # Surveillance and recalls
    # ------------------------------------------------------------------
    def adverse_event(self, *, clinician_id: str, **kwargs: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_adverse_event(
                f.adverse_event_payload(**kwargs), specialist_headers(clinician_id)
            )
        )

    def start_investigation(self, event_id: str, *, user_id: Optional[str] = None) -> Dict[str, Any]:
        headers = compliance_headers(user_id) if user_id else compliance_headers()
        return get_success_data(self.api.start_adverse_event_investigation(event_id, {}, headers))

    def adjudicate(self, event_id: str, *, clinician_id: str, outcome: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.adjudicate_adverse_event(
                event_id, f.adjudication_payload(outcome=outcome), specialist_headers(clinician_id)
            )
        )

    def recall(self, *, user_id: Optional[str] = None, **kwargs: Any) -> Dict[str, Any]:
        headers = compliance_headers(user_id) if user_id else compliance_headers()
        return get_success_data(self.api.create_lot_recall(f.recall_payload(**kwargs), headers))

    def send_notifications(self, recall_id: str, *, user_id: Optional[str] = None) -> Dict[str, Any]:
        headers = compliance_headers(user_id) if user_id else compliance_headers()
        return get_success_data(self.api.send_recall_notifications(recall_id, {}, headers))

    def ship_return(self, recall_id: str, **kwargs: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.ship_recall_return(recall_id, f.ship_return_payload(**kwargs), tech_headers())
        )

    def reconcile_credit(self, recall_id: str, *, credit_received_cents: int) -> Dict[str, Any]:
        return get_success_data(
            self.api.reconcile_recall_credit(
                recall_id,
                f.reconcile_credit_payload(credit_received_cents=credit_received_cents),
                billing_headers(),
            )
        )

    def acknowledge(self, notification_id: str, *, patient_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.acknowledge_recall_notification(
                notification_id, {}, patient_headers(patient_id)
            )
        )

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def read_lot(self, lot_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_drug_lot(lot_id, tech_headers()))

    def read_vial(self, vial_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_vial(vial_id, tech_headers()))

    def read_plan(self, plan_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_treatment_plan(plan_id, admin_headers()))

    def read_encounter(self, encounter_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_injection_encounter(encounter_id, admin_headers()))

    def read_authorization(self, pa_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_prior_authorization(pa_id, billing_headers()))

    def read_claim(self, claim_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_claim(claim_id, billing_headers()))

    def read_enrollment(self, enrollment_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_assistance_enrollment(enrollment_id, billing_headers()))

    def read_recall(self, recall_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_lot_recall(recall_id, compliance_headers()))

    def read_adverse_event(self, event_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_adverse_event(event_id, admin_headers()))

    def lot_vials(self, lot_id: str, **filters: Any) -> Any:
        response = self.api.list_vials(tech_headers(), f.page_params(limit=100, drug_lot_id=lot_id, **filters))
        return get_success_data(response)

    def recall_notifications(self, recall_id: str) -> Any:
        response = self.api.list_recall_notifications(
            compliance_headers(), f.page_params(limit=100, lot_recall_id=recall_id)
        )
        return get_success_data(response)


# ==========================================================================
# The breadth cast
# ==========================================================================


class BreadthWorld(World):
    """
    The standing cast used by the breadth suite: one open-access payer whose
    policy demands no authorization, one reference product, one lot of five
    vials, one patient, two clinicians, and the plan/encounter chain over them.
    """

    CLOCK = DEFAULT_CLOCK
    ENCOUNTER_AT = "2026-08-01T09:00:00Z"

    # -- payers ---------------------------------------------------------
    @property
    def pay_comm(self) -> Dict[str, Any]:
        return self._once(
            "pay_comm",
            lambda: self.payer(
                name="Cascade Commercial",
                payer_type="COMMERCIAL",
                coinsurance_rate=0.2,
                biosimilar_preference="NONE",
                appeal_window_days=60,
            ),
        )

    @property
    def pay_np(self) -> Dict[str, Any]:
        return self._once(
            "pay_np",
            lambda: self.payer(
                name="Foothill Open Access",
                payer_type="COMMERCIAL",
                coinsurance_rate=0.1,
                pa_required=False,
                appeal_window_days=45,
            ),
        )

    @property
    def pay_mcr(self) -> Dict[str, Any]:
        return self._once(
            "pay_mcr",
            lambda: self.payer(
                name="Federal Part B Carrier",
                payer_type="MEDICARE_PART_B",
                coinsurance_rate=0.2,
                biosimilar_preference="MANDATORY",
                appeal_window_days=30,
            ),
        )

    # -- products -------------------------------------------------------
    @property
    def drug_ref(self) -> Dict[str, Any]:
        return self._once(
            "drug_ref",
            lambda: self.drug(
                brand_name="Ranovex",
                hcpcs_code="J2778",
                vial_type="SINGLE_DOSE",
                vial_fill_ml=0.27,
                label_dose_ml=0.06,
                mg_per_ml=40,
                billing_unit_mg=1,
                asp_cents_per_billing_unit=15000,
                min_interval_days=28,
                max_interval_days=112,
            ),
        )

    @property
    def drug_bio_a(self) -> Dict[str, Any]:
        return self._once(
            "drug_bio_a",
            lambda: self.biosimilar(
                reference_drug_id=self.drug_ref["id"],
                brand_name="Ranovex-B",
                hcpcs_code="Q5199",
                vial_type="SINGLE_DOSE",
                vial_fill_ml=0.27,
                label_dose_ml=0.06,
                mg_per_ml=40,
                billing_unit_mg=1,
                asp_cents_per_billing_unit=9000,
                min_interval_days=28,
                max_interval_days=112,
            ),
        )

    @property
    def drug_bio_b(self) -> Dict[str, Any]:
        return self._once(
            "drug_bio_b",
            lambda: self.biosimilar(
                reference_drug_id=self.drug_ref["id"],
                brand_name="Ranovex-C",
                hcpcs_code="Q5200",
                vial_type="SINGLE_DOSE",
                vial_fill_ml=0.27,
                label_dose_ml=0.06,
                mg_per_ml=40,
                billing_unit_mg=1,
                asp_cents_per_billing_unit=10000,
                min_interval_days=28,
                max_interval_days=112,
            ),
        )

    @property
    def drug_cmp(self) -> Dict[str, Any]:
        return self._once(
            "drug_cmp",
            lambda: self.drug(
                brand_name="Compounded Bevacizumab",
                hcpcs_code="J9035",
                vial_type="MULTI_DOSE_COMPOUNDED",
                vial_fill_ml=1.0,
                label_dose_ml=0.05,
                mg_per_ml=40,
                billing_unit_mg=1,
                asp_cents_per_billing_unit=5000,
                min_interval_days=28,
                max_interval_days=84,
            ),
        )

    # -- policies -------------------------------------------------------
    @property
    def pol_np_ref(self) -> Dict[str, Any]:
        return self._once(
            "pol_np_ref",
            lambda: self.policy(
                payer_id=self.pay_np["id"],
                drug_id=self.drug_ref["id"],
                coverage_tier="PREFERRED",
                drug_allowed_cents_per_billing_unit=14000,
                admin_allowed_cents=10000,
                wastage_reimbursed=False,
                pa_required=False,
            ),
        )

    @property
    def pol_comm_ref(self) -> Dict[str, Any]:
        return self._once(
            "pol_comm_ref",
            lambda: self.policy(
                payer_id=self.pay_comm["id"],
                drug_id=self.drug_ref["id"],
                coverage_tier="PREFERRED",
                drug_allowed_cents_per_billing_unit=14000,
                admin_allowed_cents=10000,
                wastage_reimbursed=False,
                pa_required=True,
                pa_max_injections=1,
            ),
        )

    @property
    def pol_mcr_ref(self) -> Dict[str, Any]:
        return self._once(
            "pol_mcr_ref",
            lambda: self.policy(
                payer_id=self.pay_mcr["id"],
                drug_id=self.drug_ref["id"],
                coverage_tier="NON_PREFERRED",
                drug_allowed_cents_per_billing_unit=14000,
                admin_allowed_cents=10000,
                wastage_reimbursed=True,
                pa_required=False,
            ),
        )

    @property
    def pol_mcr_bio_a(self) -> Dict[str, Any]:
        return self._once(
            "pol_mcr_bio_a",
            lambda: self.policy(
                payer_id=self.pay_mcr["id"],
                drug_id=self.drug_bio_a["id"],
                coverage_tier="PREFERRED",
                drug_allowed_cents_per_billing_unit=11000,
                admin_allowed_cents=10000,
                wastage_reimbursed=True,
                pa_required=False,
            ),
        )

    @property
    def pol_mcr_bio_b(self) -> Dict[str, Any]:
        return self._once(
            "pol_mcr_bio_b",
            lambda: self.policy(
                payer_id=self.pay_mcr["id"],
                drug_id=self.drug_bio_b["id"],
                coverage_tier="PREFERRED",
                drug_allowed_cents_per_billing_unit=12000,
                admin_allowed_cents=10000,
                wastage_reimbursed=True,
                pa_required=False,
            ),
        )

    @property
    def pol_np_cmp(self) -> Dict[str, Any]:
        return self._once(
            "pol_np_cmp",
            lambda: self.policy(
                payer_id=self.pay_np["id"],
                drug_id=self.drug_cmp["id"],
                coverage_tier="PREFERRED",
                drug_allowed_cents_per_billing_unit=6000,
                admin_allowed_cents=10000,
                wastage_reimbursed=False,
                pa_required=False,
            ),
        )

    # -- people ---------------------------------------------------------
    @property
    def cl1(self) -> Dict[str, Any]:
        return self._once(
            "cl1", lambda: self.clinician(full_name="Dr Alina Reyes", npi="2000000001")
        )

    @property
    def cl2(self) -> Dict[str, Any]:
        return self._once(
            "cl2", lambda: self.clinician(full_name="Dr Owen Bassett", npi="2000000002")
        )

    @property
    def pt_np(self) -> Dict[str, Any]:
        return self._once(
            "pt_np",
            lambda: self.patient(
                mrn="MRN-2003",
                full_name="Nina Prakash",
                payer_id=self.pay_np["id"],
                member_id="FOA-2003",
                notification_channel="EMAIL",
                contact_point="nina.prakash@example.test",
            ),
        )

    @property
    def pt_mcr(self) -> Dict[str, Any]:
        return self._once(
            "pt_mcr",
            lambda: self.patient(
                mrn="MRN-2011",
                full_name="Marcus Byrne",
                payer_id=self.pay_mcr["id"],
                member_id="PB-2011",
                notification_channel="PHONE",
                contact_point="+15550112011",
            ),
        )

    @property
    def pt_comm(self) -> Dict[str, Any]:
        return self._once(
            "pt_comm",
            lambda: self.patient(
                mrn="MRN-2021",
                full_name="Colin Marsh",
                payer_id=self.pay_comm["id"],
                member_id="CC-2021",
                notification_channel="SMS",
                contact_point="+15550112021",
            ),
        )

    # -- inventory ------------------------------------------------------
    @property
    def lot_ref(self) -> Dict[str, Any]:
        return self._once(
            "lot_ref",
            lambda: self.lot(
                drug_id=self.drug_ref["id"],
                lot_number="RX-9001",
                expiration_date="2027-06-30T00:00:00Z",
                received_date="2026-07-01T00:00:00Z",
                unit_acquisition_cost_cents=132000,
                vials_received=5,
            ),
        )

    @property
    def lot_bio_a(self) -> Dict[str, Any]:
        return self._once(
            "lot_bio_a",
            lambda: self.lot(
                drug_id=self.drug_bio_a["id"],
                lot_number="BA-7001",
                expiration_date="2027-05-31T00:00:00Z",
                received_date="2026-07-01T00:00:00Z",
                unit_acquisition_cost_cents=96000,
                vials_received=3,
            ),
        )

    @property
    def lot_cmp(self) -> Dict[str, Any]:
        return self._once(
            "lot_cmp",
            lambda: self.lot(
                drug_id=self.drug_cmp["id"],
                lot_number="CM-5001",
                expiration_date="2026-09-30T00:00:00Z",
                received_date="2026-07-01T00:00:00Z",
                unit_acquisition_cost_cents=8000,
                vials_received=2,
            ),
        )

    # -- the open-access clinical chain ---------------------------------
    @property
    def img_np(self) -> Dict[str, Any]:
        """An active OD study on the open-access patient, taken at the clock."""
        return self._once(
            "img_np",
            lambda: self.imaging(
                clinician_id=self.cl1["id"],
                patient_id=self.pt_np["id"],
                eye="OD",
                study_datetime=self.CLOCK,
                central_subfield_thickness_um=420,
                intraretinal_fluid=True,
                subretinal_fluid=True,
            ),
        )

    @property
    def plan_np(self) -> Dict[str, Any]:
        """The draft plan; its ``version`` here is the pre-activation version."""
        return self._once(
            "plan_np",
            lambda: self.plan(
                clinician_id=self.cl1["id"],
                patient_id=self.pt_np["id"],
                drug_id=self.drug_ref["id"],
                eye="OD",
            ),
        )

    @property
    def plan_np_active(self) -> Dict[str, Any]:
        """The same plan after activation, so ``version`` is the activated one."""
        return self._once(
            "plan_np_active",
            lambda: self.activate_plan(
                self.plan_np["id"],
                clinician_id=self.cl1["id"],
                baseline_imaging_study_id=self.img_np["id"],
            ),
        )

    @property
    def enc_np(self) -> Dict[str, Any]:
        """A draft encounter on the activated plan, holding one reserved vial."""

        def build() -> Dict[str, Any]:
            self.pol_np_ref
            self.lot_ref
            plan = self.plan_np_active
            return self.encounter(
                clinician_id=self.cl1["id"],
                treatment_plan_id=plan["id"],
                imaging_study_id=self.img_np["id"],
                encounter_datetime=self.ENCOUNTER_AT,
                expected_treatment_plan_version=plan["version"],
            )

        return self._once("enc_np", build)

    @property
    def enc_np_documented(self) -> Dict[str, Any]:
        """The same encounter documented at the labelled dose."""
        return self._once(
            "enc_np_documented",
            lambda: self.document(
                self.enc_np["id"],
                clinician_id=self.cl1["id"],
                administered_dose_ml=0.06,
                post_injection_iop_mmhg=17,
            ),
        )

    @property
    def enc_np_attested(self) -> Dict[str, Any]:
        """The same encounter attested by the second clinician."""
        return self._once(
            "enc_np_attested",
            lambda: self.attest(
                self.enc_np_documented["id"],
                clinician_id=self.cl2["id"],
                attested_wasted_ml=0.21,
            ),
        )

    @property
    def claim_np(self) -> Dict[str, Any]:
        return self._once(
            "claim_np", lambda: self.claim(injection_encounter_id=self.enc_np_attested["id"])
        )


# ==========================================================================
# The depth cast
# ==========================================================================


class DepthWorld(World):
    """
    The standing cast used by the depth suite: three payers with different
    biosimilar postures, a reference product with its biosimilar and a compounded
    product, a five-vial lot, four patients and three clinicians.
    """

    CLOCK = DEFAULT_CLOCK
    ENCOUNTER_AT = "2026-08-01T09:00:00Z"

    # -- payers ---------------------------------------------------------
    @property
    def pay_comm(self) -> Dict[str, Any]:
        return self._once(
            "pay_comm",
            lambda: self.payer(
                name="Meridian Commercial",
                payer_type="COMMERCIAL",
                coinsurance_rate=0.2,
                biosimilar_preference="NONE",
                appeal_window_days=60,
            ),
        )

    @property
    def pay_np(self) -> Dict[str, Any]:
        return self._once(
            "pay_np",
            lambda: self.payer(
                name="Harbor Open Access",
                payer_type="COMMERCIAL",
                coinsurance_rate=0.1,
                pa_required=False,
                appeal_window_days=45,
            ),
        )

    @property
    def pay_mcr(self) -> Dict[str, Any]:
        return self._once(
            "pay_mcr",
            lambda: self.payer(
                name="National Part B",
                payer_type="MEDICARE_PART_B",
                coinsurance_rate=0.2,
                biosimilar_preference="MANDATORY",
                appeal_window_days=30,
            ),
        )

    # -- products -------------------------------------------------------
    @property
    def drug_ref(self) -> Dict[str, Any]:
        return self._once(
            "drug_ref",
            lambda: self.drug(
                brand_name="Ranovex",
                hcpcs_code="J2778",
                vial_type="SINGLE_DOSE",
                vial_fill_ml=0.27,
                label_dose_ml=0.06,
                mg_per_ml=40,
                billing_unit_mg=1,
                asp_cents_per_billing_unit=15000,
                min_interval_days=28,
                max_interval_days=112,
            ),
        )

    @property
    def drug_bio(self) -> Dict[str, Any]:
        return self._once(
            "drug_bio",
            lambda: self.biosimilar(
                reference_drug_id=self.drug_ref["id"],
                brand_name="Ranovex-BS",
                hcpcs_code="Q5124",
                vial_type="SINGLE_DOSE",
                vial_fill_ml=0.27,
                label_dose_ml=0.06,
                mg_per_ml=40,
                billing_unit_mg=1,
                asp_cents_per_billing_unit=9000,
                min_interval_days=28,
                max_interval_days=112,
            ),
        )

    @property
    def drug_cmp(self) -> Dict[str, Any]:
        return self._once(
            "drug_cmp",
            lambda: self.drug(
                brand_name="Bevaflex Compounded",
                hcpcs_code="J9035",
                vial_type="MULTI_DOSE_COMPOUNDED",
                vial_fill_ml=4.0,
                label_dose_ml=0.05,
                mg_per_ml=25,
                billing_unit_mg=0.25,
                asp_cents_per_billing_unit=1200,
                min_interval_days=28,
                max_interval_days=84,
            ),
        )

    # -- policies -------------------------------------------------------
    @property
    def pol_comm_ref(self) -> Dict[str, Any]:
        return self._once(
            "pol_comm_ref",
            lambda: self.policy(
                payer_id=self.pay_comm["id"],
                drug_id=self.drug_ref["id"],
                coverage_tier="PREFERRED",
                drug_allowed_cents_per_billing_unit=16000,
                admin_allowed_cents=12000,
                wastage_reimbursed=True,
            ),
        )

    @property
    def pol_np_ref(self) -> Dict[str, Any]:
        return self._once(
            "pol_np_ref",
            lambda: self.policy(
                payer_id=self.pay_np["id"],
                drug_id=self.drug_ref["id"],
                coverage_tier="PREFERRED",
                drug_allowed_cents_per_billing_unit=14000,
                admin_allowed_cents=10000,
                wastage_reimbursed=False,
                pa_required=False,
            ),
        )

    @property
    def pol_mcr_ref(self) -> Dict[str, Any]:
        return self._once(
            "pol_mcr_ref",
            lambda: self.policy(
                payer_id=self.pay_mcr["id"],
                drug_id=self.drug_ref["id"],
                coverage_tier="NON_PREFERRED",
                drug_allowed_cents_per_billing_unit=15500,
                admin_allowed_cents=11000,
                wastage_reimbursed=True,
                pa_required=False,
            ),
        )

    @property
    def pol_mcr_bio(self) -> Dict[str, Any]:
        return self._once(
            "pol_mcr_bio",
            lambda: self.policy(
                payer_id=self.pay_mcr["id"],
                drug_id=self.drug_bio["id"],
                coverage_tier="PREFERRED",
                drug_allowed_cents_per_billing_unit=9500,
                admin_allowed_cents=11000,
                wastage_reimbursed=True,
                pa_required=False,
            ),
        )

    # -- people ---------------------------------------------------------
    @property
    def cl1(self) -> Dict[str, Any]:
        return self._once(
            "cl1", lambda: self.clinician(full_name="Ivo Sandoval", npi="1000000001")
        )

    @property
    def cl2(self) -> Dict[str, Any]:
        return self._once("cl2", lambda: self.clinician(full_name="Petra Lund", npi="1000000002"))

    @property
    def cl3(self) -> Dict[str, Any]:
        """A clinician capped at a single injection a day."""
        return self._once(
            "cl3",
            lambda: self.clinician(
                full_name="Rune Vasquez",
                npi="1000000003",
                credential="DO",
                max_injections_per_day=1,
            ),
        )

    @property
    def pt1(self) -> Dict[str, Any]:
        return self._once(
            "pt1",
            lambda: self.patient(
                mrn="MRN-1001",
                full_name="Alma Reyes",
                payer_id=self.pay_comm["id"],
                member_id="MC-1001",
                notification_channel="EMAIL",
                contact_point="alma.reyes@example.test",
            ),
        )

    @property
    def pt2(self) -> Dict[str, Any]:
        return self._once(
            "pt2",
            lambda: self.patient(
                mrn="MRN-1002",
                full_name="Bo Nakamura",
                payer_id=self.pay_mcr["id"],
                member_id="NB-1002",
                notification_channel="SMS",
                contact_point="+15550101002",
            ),
        )

    @property
    def pt3(self) -> Dict[str, Any]:
        return self._once(
            "pt3",
            lambda: self.patient(
                mrn="MRN-1003",
                full_name="Cleo Iverson",
                payer_id=self.pay_np["id"],
                member_id="HO-1003",
                notification_channel="PHONE",
                contact_point="+15550101003",
            ),
        )

    @property
    def pt4(self) -> Dict[str, Any]:
        return self._once(
            "pt4",
            lambda: self.patient(
                mrn="MRN-1004",
                full_name="Dara Okonjo",
                payer_id=self.pay_np["id"],
                member_id="HO-1004",
                notification_channel="PHONE",
                contact_point="+15550101004",
            ),
        )

    # -- inventory ------------------------------------------------------
    @property
    def lot_ref(self) -> Dict[str, Any]:
        return self._once(
            "lot_ref",
            lambda: self.lot(
                drug_id=self.drug_ref["id"],
                lot_number="RX-2201",
                expiration_date="2027-06-30T00:00:00Z",
                received_date="2026-07-01T00:00:00Z",
                unit_acquisition_cost_cents=132000,
                vials_received=5,
            ),
        )

    # -- the commercial clinical chain ----------------------------------
    @property
    def img1(self) -> Dict[str, Any]:
        return self._once(
            "img1",
            lambda: self.imaging(
                clinician_id=self.cl1["id"],
                patient_id=self.pt1["id"],
                eye="OD",
                study_datetime=self.CLOCK,
                central_subfield_thickness_um=420,
                intraretinal_fluid=True,
                subretinal_fluid=True,
            ),
        )

    @property
    def plan1(self) -> Dict[str, Any]:
        return self._once(
            "plan1",
            lambda: self.plan(
                clinician_id=self.cl1["id"],
                patient_id=self.pt1["id"],
                drug_id=self.drug_ref["id"],
                eye="OD",
            ),
        )

    @property
    def plan1_active(self) -> Dict[str, Any]:
        return self._once(
            "plan1_active",
            lambda: self.activate_plan(
                self.plan1["id"],
                clinician_id=self.cl1["id"],
                baseline_imaging_study_id=self.img1["id"],
            ),
        )

    @property
    def pa1(self) -> Dict[str, Any]:
        """An approved authorization for three injections effective at the clock."""

        def build() -> Dict[str, Any]:
            self.pol_comm_ref
            plan = self.plan1_active
            return self.approved_authorization(
                treatment_plan_id=plan["id"],
                expected_treatment_plan_version=plan["version"],
                auth_number="AUTH-778",
                approved_injections=3,
                effective_date=self.CLOCK,
            )

        return self._once("pa1", build)

    @property
    def enc1(self) -> Dict[str, Any]:
        """The plan's first encounter, booked after the authorization exists."""

        def build() -> Dict[str, Any]:
            self.pa1
            self.lot_ref
            plan = self.read_plan(self.plan1["id"])
            return self.encounter(
                clinician_id=self.cl1["id"],
                treatment_plan_id=plan["id"],
                imaging_study_id=self.img1["id"],
                encounter_datetime=self.ENCOUNTER_AT,
                expected_treatment_plan_version=plan["version"],
            )

        return self._once("enc1", build)

    @property
    def enc1_documented(self) -> Dict[str, Any]:
        return self._once(
            "enc1_documented",
            lambda: self.document(
                self.enc1["id"],
                clinician_id=self.cl1["id"],
                administered_dose_ml=0.06,
                post_injection_iop_mmhg=16,
            ),
        )

    @property
    def enc1_attested(self) -> Dict[str, Any]:
        return self._once(
            "enc1_attested",
            lambda: self.attest(
                self.enc1_documented["id"], clinician_id=self.cl2["id"], attested_wasted_ml=0.21
            ),
        )

    @property
    def enrollment1(self) -> Dict[str, Any]:
        """An active foundation grant covering the whole of the second half of 2026."""
        return self._once(
            "enrollment1",
            lambda: self.active_enrollment(
                patient_id=self.pt1["id"],
                program_type="INDEPENDENT_FOUNDATION",
                annual_benefit_cents=500000,
                per_encounter_cap_cents=40000,
                effective_date="2026-07-01T00:00:00Z",
                expiration_date="2026-12-31T00:00:00Z",
            ),
        )
