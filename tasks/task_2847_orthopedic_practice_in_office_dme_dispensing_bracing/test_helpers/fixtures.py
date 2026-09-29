"""Composite setups built entirely through the public API.

The harness restarts the server before every test, so each fixture starts
from an empty database and creates everything it needs. Setup steps use
`get_success_data`, which fails loudly with the offending status when a
precondition cannot be established.

The five tiers are: a client, single entities, linked pairs, encounters walked
to a named posture, and whole scenarios.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import DmeApiClient
from .constants import CLOCK_DEFAULT_UTC, SUPERVISION_DIRECT
from .test_users import (
    compliance_officer_headers,
    insurance_coordinator_headers,
    inventory_manager_headers,
    make_dme_fitter_headers,
    make_ortho_physician_headers,
    practice_admin_headers,
)


# ---------------------------------------------------------------------------
# Tier 1 — client
# ---------------------------------------------------------------------------
def make_client() -> DmeApiClient:
    return DmeApiClient()


# ---------------------------------------------------------------------------
# Tier 2 — single entities
# ---------------------------------------------------------------------------
def create_clinic(api: DmeApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_clinic(f.clinic_payload(**overrides), practice_admin_headers()))


def create_physician(api: DmeApiClient, clinic_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_physician(clinic_id, f.physician_payload(**overrides), practice_admin_headers())
    )


def create_fitter(api: DmeApiClient, clinic_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_fitter(clinic_id, f.fitter_payload(**overrides), practice_admin_headers())
    )


def create_patient(api: DmeApiClient, clinic_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_patient(clinic_id, f.patient_payload(**overrides), practice_admin_headers())
    )


def create_supplier(api: DmeApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_supplier(f.supplier_payload(**overrides), practice_admin_headers()))


def create_product(api: DmeApiClient, supplier_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_product(f.product_payload(supplier_id, **overrides), inventory_manager_headers())
    )


def create_product_from(
    api: DmeApiClient, payload: Dict[str, Any]
) -> Dict[str, Any]:
    return get_success_data(api.create_product(payload, inventory_manager_headers()))


def set_clock(api: DmeApiClient, current_utc: str) -> Dict[str, Any]:
    return get_success_data(api.set_clock(current_utc, practice_admin_headers()), 200)


def attest_standards(
    api: DmeApiClient, supplier_id: str, attested: bool = True, quality_hold: bool = False
) -> Dict[str, Any]:
    return get_success_data(
        api.standards_attestation(
            supplier_id,
            f.standards_attestation_payload(
                dmepos_standards_attested=attested, quality_hold=quality_hold
            ),
            compliance_officer_headers(),
        ),
        200,
    )


# ---------------------------------------------------------------------------
# Tier 3 — linked pairs
# ---------------------------------------------------------------------------
def create_shelf(
    api: DmeApiClient,
    clinic_id: str,
    product_id: str,
    received_qty: Optional[int] = None,
    **overrides: Any
) -> Dict[str, Any]:
    """Open a shelf and, when a quantity is given, receive stock onto it."""
    shelf = get_success_data(
        api.create_par_level(
            f.par_level_payload(clinic_id, product_id, **overrides), inventory_manager_headers()
        )
    )
    if received_qty:
        shelf = get_success_data(
            api.receive_stock(
                shelf["id"], f.stock_receipt_payload(received_qty), inventory_manager_headers()
            )
        )
    return shelf


def read_shelf(api: DmeApiClient, par_level_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_par_level(par_level_id, inventory_manager_headers()), 200)


def shelf_version(api: DmeApiClient, par_level_id: str) -> int:
    return read_shelf(api, par_level_id)["version"]


def read_encounter(api: DmeApiClient, encounter_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_encounter(encounter_id, practice_admin_headers()), 200)


def encounter_version(api: DmeApiClient, encounter_id: str) -> int:
    return read_encounter(api, encounter_id)["version"]


def read_clinic(api: DmeApiClient, clinic_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_clinic(clinic_id, practice_admin_headers()), 200)


def read_supplier(api: DmeApiClient, supplier_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_supplier(supplier_id, inventory_manager_headers()), 200)


def read_fitter(api: DmeApiClient, fitter_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_fitter(fitter_id, practice_admin_headers()), 200)


def read_fab_order(api: DmeApiClient, order_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_custom_fab_order(order_id, inventory_manager_headers()), 200)


def read_summary(api: DmeApiClient, clinic_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_dispensing_summary(clinic_id, compliance_officer_headers()), 200)


# ---------------------------------------------------------------------------
# Tier 4 — a practice with a roster, a catalog and a shelf
# ---------------------------------------------------------------------------
class Practice(object):
    """One clinic with the roster, supplier, catalog item and shelf a test needs."""

    def __init__(self, api: DmeApiClient, **kwargs: Any) -> None:
        self.api = api
        self.__dict__.update(kwargs)

    # -- headers ------------------------------------------------------------
    @property
    def ordering_physician_headers(self) -> Dict[str, str]:
        return make_ortho_physician_headers(self.ordering_physician_id)

    @property
    def attesting_physician_headers(self) -> Dict[str, str]:
        return make_ortho_physician_headers(self.attesting_physician_id)

    @property
    def fitter_headers(self) -> Dict[str, str]:
        return make_dme_fitter_headers(self.fitter_id)

    # -- encounter walk -----------------------------------------------------
    def open_encounter(
        self, quantity: int = 1, product_id: Optional[str] = None, patient_id: Optional[str] = None
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_encounter(
                f.encounter_payload(
                    self.clinic_id,
                    patient_id or self.patient_id,
                    product_id or self.product_id,
                    self.ordering_physician_id,
                    quantity,
                ),
                practice_admin_headers(),
            )
        )

    def sign_note(self, encounter_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.sign_medical_necessity_note(
                encounter_id,
                f.medical_necessity_note_payload(**overrides),
                self.ordering_physician_headers,
            )
        )

    def attest(self, encounter_id: str, level: str = SUPERVISION_DIRECT) -> Dict[str, Any]:
        return get_success_data(
            self.api.attest_ioas(
                encounter_id, f.ioas_attestation_payload(level), self.attesting_physician_headers
            )
        )

    def verify_coverage(self, encounter_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_coverage_verification(
                encounter_id,
                f.coverage_verification_payload(**overrides),
                insurance_coordinator_headers(),
            )
        )

    def reserve(self, encounter_id: str, par_level_id: Optional[str] = None) -> Dict[str, Any]:
        shelf_id = par_level_id or self.par_level_id
        version = shelf_version(self.api, shelf_id)
        return get_success_data(
            self.api.create_reservation(
                encounter_id, f.reservation_payload(version), self.fitter_headers
            )
        )

    def fit(
        self,
        encounter_id: str,
        start_at: str = "2026-08-01T09:00:00Z",
        end_at: str = "2026-08-01T09:30:00Z",
        outcome: str = "ACCEPTABLE",
        fitter_id: Optional[str] = None,
        **overrides: Any
    ) -> Dict[str, Any]:
        headers = make_dme_fitter_headers(fitter_id) if fitter_id else self.fitter_headers
        return get_success_data(
            self.api.create_fitting_record(
                encounter_id,
                f.fitting_record_payload(start_at, end_at, outcome, **overrides),
                headers,
            )
        )

    def dispense(
        self, encounter_id: str, signature_role: str = "PATIENT", fitter_id: Optional[str] = None
    ) -> Dict[str, Any]:
        headers = make_dme_fitter_headers(fitter_id) if fitter_id else self.fitter_headers
        return get_success_data(
            self.api.dispense(encounter_id, f.dispense_payload(signature_role), headers)
        )

    def issue_abn(self, encounter_id: str, **overrides: Any) -> Dict[str, Any]:
        version = encounter_version(self.api, encounter_id)
        return get_success_data(
            self.api.create_abn_notice(
                encounter_id, f.abn_notice_payload(version, **overrides), insurance_coordinator_headers()
            )
        )

    def sign_abn(self, notice_id: str, option: str = "OPTION_1", signed_by: str = "PATIENT"):
        return get_success_data(
            self.api.sign_abn_notice(
                notice_id,
                f.abn_signature_payload(option_selected=option, signed_by=signed_by),
                insurance_coordinator_headers(),
            )
        )

    def request_prior_auth(self, encounter_id: str, requested_units: int = 1) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_prior_auth_request(
                encounter_id,
                f.prior_auth_request_payload(requested_units),
                insurance_coordinator_headers(),
            )
        )

    def decide_prior_auth(self, request_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.decide_prior_auth(
                request_id, f.prior_auth_decision_payload(**overrides), insurance_coordinator_headers()
            )
        )

    def appeal_prior_auth(self, request_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.appeal_prior_auth(
                request_id, f.prior_auth_appeal_payload(**overrides), insurance_coordinator_headers()
            )
        )

    def place_fab_order(
        self, encounter_id: str, supplier_id: Optional[str] = None
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_custom_fab_order(
                encounter_id,
                f.custom_fab_order_payload(supplier_id or self.supplier_id),
                self.fitter_headers,
            )
        )

    def fabrication_event(self, order_id: str, event: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_fabrication_event(
                order_id, f.fabrication_event_payload(event), inventory_manager_headers()
            )
        )

    def fitting_check(self, order_id: str, outcome: str = "ACCEPT", **overrides: Any):
        return get_success_data(
            self.api.fitting_check(
                order_id, f.fitting_check_payload(outcome, **overrides), self.fitter_headers
            )
        )

    def open_return(self, encounter_id: str, reason: str = "POOR_FIT", **overrides: Any):
        return get_success_data(
            self.api.create_return(
                encounter_id, f.return_payload(reason, **overrides), self.fitter_headers
            )
        )

    def inspect_return(self, return_id: str, condition: str = "SELLABLE") -> Dict[str, Any]:
        return get_success_data(
            self.api.inspect_return(
                return_id, f.inspection_payload(condition), inventory_manager_headers()
            )
        )

    # -- composite walks ----------------------------------------------------
    def documented_encounter(self, quantity: int = 1, **kwargs: Any) -> str:
        encounter = self.open_encounter(quantity=quantity, **kwargs)
        self.sign_note(encounter["id"])
        return encounter["id"]

    def attested_encounter(self, quantity: int = 1, **kwargs: Any) -> str:
        encounter_id = self.documented_encounter(quantity=quantity, **kwargs)
        self.attest(encounter_id)
        return encounter_id

    def verified_encounter(
        self, quantity: int = 1, coverage: Optional[Dict[str, Any]] = None, **kwargs: Any
    ) -> str:
        encounter_id = self.attested_encounter(quantity=quantity, **kwargs)
        self.verify_coverage(encounter_id, **(coverage or {}))
        return encounter_id

    def reserved_encounter(
        self,
        quantity: int = 1,
        coverage: Optional[Dict[str, Any]] = None,
        par_level_id: Optional[str] = None,
        **kwargs: Any
    ) -> str:
        encounter_id = self.verified_encounter(quantity=quantity, coverage=coverage, **kwargs)
        self.reserve(encounter_id, par_level_id)
        return encounter_id

    def fitted_encounter(
        self,
        quantity: int = 1,
        coverage: Optional[Dict[str, Any]] = None,
        par_level_id: Optional[str] = None,
        start_at: str = "2026-08-01T09:00:00Z",
        end_at: str = "2026-08-01T09:30:00Z",
        **kwargs: Any
    ) -> str:
        encounter_id = self.reserved_encounter(
            quantity=quantity, coverage=coverage, par_level_id=par_level_id, **kwargs
        )
        self.fit(encounter_id, start_at, end_at)
        return encounter_id

    def delivered_encounter(
        self,
        quantity: int = 1,
        coverage: Optional[Dict[str, Any]] = None,
        par_level_id: Optional[str] = None,
        start_at: str = "2026-08-01T09:00:00Z",
        end_at: str = "2026-08-01T09:30:00Z",
        **kwargs: Any
    ) -> str:
        encounter_id = self.fitted_encounter(
            quantity=quantity,
            coverage=coverage,
            par_level_id=par_level_id,
            start_at=start_at,
            end_at=end_at,
            **kwargs
        )
        self.dispense(encounter_id)
        return encounter_id


# ---------------------------------------------------------------------------
# Tier 5 — whole scenarios
# ---------------------------------------------------------------------------
def build_practice(
    api: DmeApiClient,
    clinic: Optional[Dict[str, Any]] = None,
    supplier: Optional[Dict[str, Any]] = None,
    product: Optional[Dict[str, Any]] = None,
    product_payload: Optional[Dict[str, Any]] = None,
    product_factory: Optional[Any] = None,
    fitter: Optional[Dict[str, Any]] = None,
    patient: Optional[Dict[str, Any]] = None,
    par_level: Optional[Dict[str, Any]] = None,
    received_qty: Optional[int] = 10,
    with_shelf: bool = True,
) -> Practice:
    """One accredited clinic, two physicians, a fitter, a patient, an attested
    supplier, one catalog item and (by default) a stocked shelf."""
    clinic_row = create_clinic(api, **(clinic or {}))
    supplier_row = create_supplier(api, **(supplier or {}))
    if product_payload is not None:
        product_row = create_product_from(api, product_payload)
    elif product_factory is not None:
        product_row = create_product_from(api, product_factory(supplier_row["id"]))
    else:
        product_row = create_product(api, supplier_row["id"], **(product or {}))
    # An encounter's ordering physician must share the product's specialty line,
    # so the roster is built to match the catalog item under test.
    line = product_row["specialty"]
    ordering = create_physician(api, clinic_row["id"], full_name="Ora Vance", specialty=line)
    attesting = create_physician(api, clinic_row["id"], full_name="Dov Reyes", specialty=line)
    fitter_row = create_fitter(api, clinic_row["id"], **(fitter or {}))
    patient_row = create_patient(api, clinic_row["id"], **(patient or {}))
    shelf_row = None
    if with_shelf:
        shelf_row = create_shelf(
            api,
            clinic_row["id"],
            product_row["id"],
            received_qty=received_qty,
            **(par_level or {})
        )
    return Practice(
        api,
        clinic_id=clinic_row["id"],
        clinic=clinic_row,
        ordering_physician_id=ordering["id"],
        ordering_physician=ordering,
        attesting_physician_id=attesting["id"],
        attesting_physician=attesting,
        fitter_id=fitter_row["id"],
        fitter=fitter_row,
        patient_id=patient_row["id"],
        patient=patient_row,
        supplier_id=supplier_row["id"],
        supplier=supplier_row,
        product_id=product_row["id"],
        product=product_row,
        par_level_id=shelf_row["id"] if shelf_row else None,
        par_level=shelf_row,
    )


def add_product(practice: Practice, payload: Dict[str, Any]) -> Dict[str, Any]:
    return create_product_from(practice.api, payload)


def add_shelf(
    practice: Practice, product_id: str, received_qty: Optional[int] = None, **overrides: Any
) -> Dict[str, Any]:
    return create_shelf(
        practice.api, practice.clinic_id, product_id, received_qty=received_qty, **overrides
    )


def add_patient(practice: Practice, **overrides: Any) -> Dict[str, Any]:
    return create_patient(practice.api, practice.clinic_id, **overrides)


def add_fitter(practice: Practice, **overrides: Any) -> Dict[str, Any]:
    return create_fitter(practice.api, practice.clinic_id, **overrides)


def add_physician(practice: Practice, **overrides: Any) -> Dict[str, Any]:
    return create_physician(practice.api, practice.clinic_id, **overrides)


def suspend_clinic_via_stockouts(practice: Practice, product_ids: List[str]) -> None:
    """Open a shelf per product and never stock it, so the clinic's posture
    reflects only shelves that have carried stock."""
    for product_id in product_ids:
        add_shelf(practice, product_id)
