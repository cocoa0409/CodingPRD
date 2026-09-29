"""Composite setup helpers.

The harness restarts the service against an empty database before every single
test, so nothing is pre-seeded: each precondition below is built from scratch
using only endpoints the PRD declares.  All setup calls go through the lenient
`get_success_data`, so a broken precondition surfaces as the API's own error id
instead of an opaque KeyError.

The logical clock starts at exactly 2026-08-01T00:00:00Z (PRD 2.5) and is
strictly monotonic, so these helpers never re-set it to that value; they only
ever move it forward.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import ApiClient
from .constants import CLOCK_DEFAULT, REQUIRED_BASE_TEST_TYPES
from .test_users import (
    TECH_ALT_USER_ID,
    TECH_USER_ID,
    VET_ALT_USER_ID,
    VET_USER_ID,
    make_advisor_headers,
    make_coordinator_headers,
    make_director_headers,
    make_distributor_headers,
    make_facility_headers,
    make_tech_headers,
    make_vet_headers,
)

JsonDict = Dict[str, Any]

DIRECTOR = make_director_headers()
VET = make_vet_headers()
VET_ALT = make_vet_headers(VET_ALT_USER_ID)
TECH = make_tech_headers()
TECH_ALT = make_tech_headers(TECH_ALT_USER_ID)
COORDINATOR = make_coordinator_headers()
ADVISOR = make_advisor_headers()

# --- the canonical timeline these helpers walk --------------------------------
CLOCK_START = CLOCK_DEFAULT                      # server startup value
BASE_SAMPLE_DATE = "2026-08-01"                  # the clock date, never future
BASE_VALIDITY_DAYS = 365                         # valid_until 2027-08-01
BASE_VALID_UNTIL = "2027-08-01T00:00:00.000Z"
DEFAULT_ISOLATION_DAYS = 30
CLOCK_ISOLATION_SERVED = "2026-08-31T00:00:00Z"  # start + 30 days
BOOKING_START = "2026-09-10T08:00:00Z"
BOOKING_END = "2026-09-10T10:00:00Z"
CLOCK_AT_COLLECTION = BOOKING_START


def _data(response, expected_status: Optional[int] = None) -> JsonDict:
    return get_success_data(response, expected_status)


# ------------------------------------------------------------------- tier 0
def advance_clock(api: ApiClient, instant: str) -> JsonDict:
    """Move the logical clock strictly forward and return the sweep report."""
    return _data(api.set_clock(instant, DIRECTOR), 200)


# ------------------------------------------------------------------- tier 1
def register_facility(api: ApiClient, **overrides: Any) -> JsonDict:
    return _data(api.create_facility(factories.facility_payload(**overrides), DIRECTOR), 201)


def suspend_facility(
    api: ApiClient, facility_id: str, suspension_reason: str = "REGULATOR_AUDIT_FINDING"
) -> JsonDict:
    return _data(
        api.set_facility_approval_status(
            facility_id,
            factories.facility_approval_payload("SUSPENDED", suspension_reason=suspension_reason),
            DIRECTOR,
        ),
        200,
    )


def approve_facility(api: ApiClient, facility_id: str) -> JsonDict:
    return _data(
        api.set_facility_approval_status(
            facility_id,
            factories.facility_approval_payload("APPROVED", suspension_reason=factories.OMIT),
            DIRECTOR,
        ),
        200,
    )


def register_country_requirement(api: ApiClient, **overrides: Any) -> JsonDict:
    return _data(
        api.create_country_requirement(
            factories.country_requirement_payload(**overrides), COORDINATOR
        ),
        201,
    )


def register_sire(api: ApiClient, **overrides: Any) -> JsonDict:
    return _data(api.create_sire(factories.sire_payload(**overrides), DIRECTOR), 201)


def contract_sire(api: ApiClient, sire_id: str, **overrides: Any) -> JsonDict:
    return _data(
        api.contract_sire(sire_id, factories.contract_payload(**overrides), DIRECTOR), 200
    )


def house_sire(
    api: ApiClient,
    sire_id: str,
    facility_id: str,
    isolation_days: int = DEFAULT_ISOLATION_DAYS,
) -> JsonDict:
    return _data(
        api.house_sire(sire_id, factories.house_payload(facility_id, isolation_days), DIRECTOR),
        200,
    )


def register_distributor(api: ApiClient, **overrides: Any) -> JsonDict:
    return _data(
        api.create_distributor(factories.distributor_payload(**overrides), DIRECTOR), 201
    )


def register_tank(api: ApiClient, distributor_id: str, **overrides: Any) -> JsonDict:
    return _data(
        api.create_tank(factories.tank_payload(distributor_id, **overrides), DIRECTOR), 201
    )


def register_customer_herd(api: ApiClient, distributor_id: str, **overrides: Any) -> JsonDict:
    return _data(
        api.create_customer_herd(
            factories.customer_herd_payload(distributor_id, **overrides), ADVISOR
        ),
        201,
    )


# ------------------------------------------------------------------- tier 2
def order_health_test(
    api: ApiClient,
    sire_id: str,
    facility_id: str,
    test_type: str = "IBR",
    sample_date: str = BASE_SAMPLE_DATE,
    validity_days: int = BASE_VALIDITY_DAYS,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> JsonDict:
    return _data(
        api.order_health_test(
            sire_id,
            factories.health_test_payload(
                facility_id, test_type, sample_date, validity_days, **overrides
            ),
            headers or VET,
        ),
        201,
    )


def result_health_test(
    api: ApiClient,
    test_id: str,
    result: str = "NEGATIVE",
    headers: Optional[Dict[str, str]] = None,
) -> JsonDict:
    return _data(
        api.record_health_test_result(
            test_id, factories.health_test_result_payload(result), headers or VET
        ),
        200,
    )


def negative_test(
    api: ApiClient,
    sire_id: str,
    facility_id: str,
    test_type: str = "IBR",
    sample_date: str = BASE_SAMPLE_DATE,
    validity_days: int = BASE_VALIDITY_DAYS,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> JsonDict:
    """Order a test and file a NEGATIVE result, returning the resulted row."""
    ordered = order_health_test(
        api, sire_id, facility_id, test_type, sample_date, validity_days, headers, **overrides
    )
    return result_health_test(api, ordered["id"], "NEGATIVE", headers)


def grant_base_health_currency(
    api: ApiClient,
    sire_id: str,
    facility_id: str,
    sample_date: str = BASE_SAMPLE_DATE,
    validity_days: int = BASE_VALIDITY_DAYS,
    headers: Optional[Dict[str, str]] = None,
    per_type_validity_days: Optional[Dict[str, int]] = None,
) -> Dict[str, JsonDict]:
    """PRD 2.9: one NEGATIVE, unexpired assay for each of the four base types."""
    tests: Dict[str, JsonDict] = {}
    for test_type in REQUIRED_BASE_TEST_TYPES:
        days = (per_type_validity_days or {}).get(test_type, validity_days)
        tests[test_type] = negative_test(
            api, sire_id, facility_id, test_type, sample_date, days, headers
        )
    return tests


# ------------------------------------------------------------------- tier 3
def eligible_sire(
    api: ApiClient,
    facility: Optional[JsonDict] = None,
    *,
    registration_code: str = "REG-A",
    sire_overrides: Optional[JsonDict] = None,
    facility_overrides: Optional[JsonDict] = None,
    isolation_days: int = DEFAULT_ISOLATION_DAYS,
    clearance_clock: Optional[str] = CLOCK_ISOLATION_SERVED,
    sample_date: str = BASE_SAMPLE_DATE,
    validity_days: int = BASE_VALIDITY_DAYS,
    per_type_validity_days: Optional[Dict[str, int]] = None,
    vet_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """A RESIDENT, ELIGIBLE bull housed at an APPROVED facility.

    Walks the PRD's own path: register, contract, house, four NEGATIVE base
    assays, then collection-clearance once the clock has reached
    `isolation_ends_at`.  Pass `clearance_clock=None` when the caller has
    already moved the clock far enough.
    """
    facility = facility or register_facility(api, **(facility_overrides or {}))
    sire = register_sire(
        api, registration_code=registration_code, **(sire_overrides or {})
    )
    contract_sire(api, sire["id"])
    house_sire(api, sire["id"], facility["id"], isolation_days)
    tests = grant_base_health_currency(
        api,
        sire["id"],
        facility["id"],
        sample_date=sample_date,
        validity_days=validity_days,
        headers=vet_headers,
        per_type_validity_days=per_type_validity_days,
    )
    if clearance_clock:
        advance_clock(api, clearance_clock)
    cleared = _data(
        api.clear_sire_for_collection(
            sire["id"], factories.clearance_payload(), vet_headers or VET
        ),
        200,
    )
    return {
        "facility": facility,
        "facility_headers": make_facility_headers(facility["id"]),
        "sire": cleared,
        "health_tests": tests,
    }


def book_collection(
    api: ApiClient,
    sire_id: str,
    facility_id: str,
    start_at: str = BOOKING_START,
    end_at: str = BOOKING_END,
    **overrides: Any,
) -> JsonDict:
    return _data(
        api.create_booking(
            factories.booking_payload(sire_id, facility_id, start_at, end_at, **overrides),
            make_facility_headers(facility_id),
        ),
        201,
    )


def complete_collection(
    api: ApiClient,
    booking_id: str,
    facility_id: str,
    volume_ml: float = 6.0,
    concentration_m_per_ml: float = 1200,
    motility_pct: float = 68.0,
    **overrides: Any,
) -> JsonDict:
    return _data(
        api.complete_booking(
            booking_id,
            factories.booking_complete_payload(
                volume_ml, concentration_m_per_ml, motility_pct, **overrides
            ),
            make_facility_headers(facility_id),
        ),
        200,
    )


def discover_ejaculate(api: ApiClient, booking_id: str) -> JsonDict:
    """PRD 3.4: the cascade-created ejaculate is reachable only by the list."""
    rows = _data(api.list_ejaculates(TECH, {"booking_id": booking_id}), 200)
    assert len(rows) == 1, f"expected exactly one ejaculate for {booking_id}, got {rows}"
    return rows[0]


def collected_ejaculate(
    api: ApiClient,
    context: Optional[Dict[str, Any]] = None,
    *,
    start_at: str = BOOKING_START,
    end_at: str = BOOKING_END,
    collection_clock: Optional[str] = CLOCK_AT_COLLECTION,
    volume_ml: float = 6.0,
    concentration_m_per_ml: float = 1200,
    motility_pct: float = 68.0,
    **eligible_kwargs: Any,
) -> Dict[str, Any]:
    """An ELIGIBLE bull with one COMPLETED booking and its PENDING_QC ejaculate."""
    context = context or eligible_sire(api, **eligible_kwargs)
    booking = book_collection(
        api, context["sire"]["id"], context["facility"]["id"], start_at, end_at
    )
    if collection_clock:
        advance_clock(api, collection_clock)
    booking = complete_collection(
        api,
        booking["id"],
        context["facility"]["id"],
        volume_ml,
        concentration_m_per_ml,
        motility_pct,
    )
    context = dict(context)
    context["booking"] = booking
    context["ejaculate"] = discover_ejaculate(api, booking["id"])
    return context


def evaluate_qc(
    api: ApiClient,
    ejaculate_id: str,
    verdict: str = "ACCEPTED",
    post_thaw_motility_pct: float = 55.0,
    morphology_normal_pct: float = 82.0,
    headers: Optional[Dict[str, str]] = None,
) -> JsonDict:
    return _data(
        api.evaluate_ejaculate_qc(
            ejaculate_id,
            factories.qc_evaluation_payload(
                verdict, post_thaw_motility_pct, morphology_normal_pct
            ),
            headers or TECH,
        ),
        200,
    )


def accepted_ejaculate(
    api: ApiClient,
    context: Optional[Dict[str, Any]] = None,
    *,
    post_thaw_motility_pct: float = 55.0,
    morphology_normal_pct: float = 82.0,
    evaluator_headers: Optional[Dict[str, str]] = None,
    **collected_kwargs: Any,
) -> Dict[str, Any]:
    context = context or collected_ejaculate(api, **collected_kwargs)
    context = dict(context)
    context["ejaculate"] = evaluate_qc(
        api,
        context["ejaculate"]["id"],
        "ACCEPTED",
        post_thaw_motility_pct,
        morphology_normal_pct,
        evaluator_headers,
    )
    return context


def cut_lot(
    api: ApiClient,
    ejaculate_id: str,
    product_line: str = "CONVENTIONAL",
    straw_count: int = 200,
    processing_cost_cents: int = 250000,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> JsonDict:
    return _data(
        api.cut_straw_lot(
            ejaculate_id,
            factories.straw_lot_payload(
                product_line, straw_count, processing_cost_cents, **overrides
            ),
            headers or TECH,
        ),
        201,
    )


def release_lot(
    api: ApiClient, lot_id: str, headers: Optional[Dict[str, str]] = None
) -> JsonDict:
    """Released by a technician other than the QC evaluator (PRD 3.5)."""
    return _data(
        api.release_straw_lot(lot_id, factories.lot_release_payload(), headers or TECH_ALT),
        200,
    )


def reject_lot(
    api: ApiClient,
    lot_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> JsonDict:
    return _data(
        api.reject_straw_lot(lot_id, factories.lot_reject_payload(**overrides), headers or TECH),
        200,
    )


def quarantine_lot(
    api: ApiClient,
    context: Optional[Dict[str, Any]] = None,
    *,
    product_line: str = "CONVENTIONAL",
    straw_count: int = 200,
    processing_cost_cents: int = 250000,
    lot_overrides: Optional[JsonDict] = None,
    **accepted_kwargs: Any,
) -> Dict[str, Any]:
    context = context or accepted_ejaculate(api, **accepted_kwargs)
    context = dict(context)
    context["lot"] = cut_lot(
        api,
        context["ejaculate"]["id"],
        product_line,
        straw_count,
        processing_cost_cents,
        **(lot_overrides or {}),
    )
    return context


def released_lot(
    api: ApiClient,
    context: Optional[Dict[str, Any]] = None,
    *,
    releaser_headers: Optional[Dict[str, str]] = None,
    **quarantine_kwargs: Any,
) -> Dict[str, Any]:
    context = context or quarantine_lot(api, **quarantine_kwargs)
    context = dict(context)
    context["lot"] = release_lot(api, context["lot"]["id"], releaser_headers)
    return context


# ------------------------------------------------------------------- tier 4
def file_evaluation(api: ApiClient, sire_id: str, **overrides: Any) -> JsonDict:
    """File a DRAFT evaluation, pinning the sire's current version (PRD 2.7)."""
    sire = _data(api.get_sire(sire_id, DIRECTOR), 200)
    return _data(
        api.file_genomic_evaluation(
            sire_id,
            factories.genomic_evaluation_payload(sire["version"], **overrides),
            DIRECTOR,
        ),
        201,
    )


def publish_evaluation(api: ApiClient, evaluation_id: str) -> JsonDict:
    return _data(
        api.publish_genomic_evaluation(evaluation_id, factories.publish_payload(), DIRECTOR),
        200,
    )


def rollback_evaluation(api: ApiClient, evaluation_id: str, **overrides: Any) -> JsonDict:
    return _data(
        api.rollback_genomic_evaluation(
            evaluation_id, factories.rollback_payload(**overrides), DIRECTOR
        ),
        200,
    )


def published_proof(api: ApiClient, sire_id: str, **overrides: Any) -> JsonDict:
    """File and publish one evaluation, returning the PUBLISHED row."""
    draft = file_evaluation(api, sire_id, **overrides)
    return publish_evaluation(api, draft["id"])


# ------------------------------------------------------------------- tier 5
def draft_certificate(
    api: ApiClient, sire_id: str, straw_lot_id: str, country_requirement_id: str
) -> JsonDict:
    return _data(
        api.create_export_certificate(
            factories.export_certificate_payload(
                sire_id, straw_lot_id, country_requirement_id
            ),
            COORDINATOR,
        ),
        201,
    )


def submit_certificate(api: ApiClient, certificate_id: str) -> JsonDict:
    return _data(
        api.submit_export_certificate(
            certificate_id, factories.certificate_submit_payload(), COORDINATOR
        ),
        200,
    )


def issue_certificate(
    api: ApiClient, certificate_id: str, headers: Optional[Dict[str, str]] = None
) -> JsonDict:
    """Signed by a vet who filed no result for the bull (PRD 3.7)."""
    return _data(
        api.issue_export_certificate(
            certificate_id, factories.certificate_issue_payload(), headers or VET_ALT
        ),
        200,
    )


def reject_certificate(api: ApiClient, certificate_id: str, **overrides: Any) -> JsonDict:
    return _data(
        api.reject_export_certificate(
            certificate_id, factories.certificate_reject_payload(**overrides), VET
        ),
        200,
    )


def submitted_certificate(
    api: ApiClient,
    sire_id: str,
    straw_lot_id: str,
    country_requirement_id: str,
) -> JsonDict:
    draft = draft_certificate(api, sire_id, straw_lot_id, country_requirement_id)
    return submit_certificate(api, draft["id"])


def issued_certificate(
    api: ApiClient,
    sire_id: str,
    straw_lot_id: str,
    country_requirement_id: str,
    signer_headers: Optional[Dict[str, str]] = None,
) -> JsonDict:
    submitted = submitted_certificate(
        api, sire_id, straw_lot_id, country_requirement_id
    )
    return issue_certificate(api, submitted["id"], signer_headers)


# ------------------------------------------------------------------- tier 6
def distributor_with_tank(
    api: ApiClient,
    *,
    distributor_overrides: Optional[JsonDict] = None,
    tank_overrides: Optional[JsonDict] = None,
) -> Dict[str, Any]:
    distributor = register_distributor(api, **(distributor_overrides or {}))
    tank = register_tank(api, distributor["id"], **(tank_overrides or {}))
    return {
        "distributor": distributor,
        "tank": tank,
        "distributor_headers": make_distributor_headers(distributor["id"]),
    }


def service_tank(
    api: ApiClient,
    tank_id: str,
    fill_pct: float = 95.0,
    headers: Optional[Dict[str, str]] = None,
) -> JsonDict:
    return _data(
        api.service_tank(tank_id, factories.tank_service_payload(fill_pct), headers or DIRECTOR),
        200,
    )


def request_consignment(
    api: ApiClient,
    lot_id: str,
    distributor_id: str,
    tank_id: str,
    doses: int = 40,
    unit_price_cents: int = 4000,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> JsonDict:
    lot = _data(api.get_straw_lot(lot_id, DIRECTOR), 200)
    return _data(
        api.request_consignment_transfer(
            lot_id,
            factories.consignment_request_payload(
                distributor_id,
                tank_id,
                lot["version"],
                doses,
                unit_price_cents,
                **overrides,
            ),
            headers or DIRECTOR,
        ),
        201,
    )


def approve_transfer(api: ApiClient, transfer_id: str) -> JsonDict:
    return _data(
        api.approve_consignment_transfer(
            transfer_id, factories.transfer_approve_payload(), DIRECTOR
        ),
        200,
    )


def dispatch_transfer(api: ApiClient, transfer_id: str) -> JsonDict:
    return _data(
        api.dispatch_consignment_transfer(
            transfer_id, factories.transfer_dispatch_payload(), DIRECTOR
        ),
        200,
    )


def receive_transfer(api: ApiClient, transfer_id: str, distributor_id: str) -> JsonDict:
    return _data(
        api.receive_consignment_transfer(
            transfer_id,
            factories.transfer_receive_payload(),
            make_distributor_headers(distributor_id),
        ),
        200,
    )


def report_usage(
    api: ApiClient,
    transfer_id: str,
    distributor_id: str,
    doses_used: int,
    **overrides: Any,
) -> JsonDict:
    return _data(
        api.report_consignment_usage(
            transfer_id,
            factories.report_usage_payload(doses_used, **overrides),
            make_distributor_headers(distributor_id),
        ),
        200,
    )


def return_transfer(api: ApiClient, transfer_id: str, distributor_id: str, **overrides: Any) -> JsonDict:
    return _data(
        api.return_consignment_transfer(
            transfer_id,
            factories.transfer_return_payload(**overrides),
            make_distributor_headers(distributor_id),
        ),
        200,
    )


def received_consignment(
    api: ApiClient,
    context: Optional[Dict[str, Any]] = None,
    *,
    doses: int = 40,
    unit_price_cents: int = 4000,
    distributor_overrides: Optional[JsonDict] = None,
    tank_overrides: Optional[JsonDict] = None,
    stop_after: str = "RECEIVED",
    **released_kwargs: Any,
) -> Dict[str, Any]:
    """Walk a consignment as far as `stop_after` along PRD 3.8's lifecycle."""
    context = context or released_lot(api, **released_kwargs)
    context = dict(context)
    if "distributor" not in context or "tank" not in context:
        context.update(
            distributor_with_tank(
                api,
                distributor_overrides=distributor_overrides,
                tank_overrides=tank_overrides,
            )
        )
    transfer = request_consignment(
        api,
        context["lot"]["id"],
        context["distributor"]["id"],
        context["tank"]["id"],
        doses,
        unit_price_cents,
    )
    if stop_after != "REQUESTED":
        transfer = approve_transfer(api, transfer["id"])
    if stop_after not in ("REQUESTED", "APPROVED"):
        transfer = dispatch_transfer(api, transfer["id"])
    if stop_after not in ("REQUESTED", "APPROVED", "IN_TRANSIT"):
        transfer = receive_transfer(api, transfer["id"], context["distributor"]["id"])
    context["transfer"] = transfer
    context["lot"] = _data(api.get_straw_lot(context["lot"]["id"], DIRECTOR), 200)
    return context


# ------------------------------------------------------------------- tier 7
def request_recommendation(
    api: ApiClient, herd_id: str, headers: Optional[Dict[str, str]] = None, **overrides: Any
) -> JsonDict:
    return _data(
        api.request_mating_recommendation(
            herd_id, factories.mating_recommendation_payload(**overrides), headers or ADVISOR
        ),
        201,
    )


def decide_recommendation(
    api: ApiClient,
    recommendation_id: str,
    decision: str = "ACCEPTED",
    headers: Optional[Dict[str, str]] = None,
) -> JsonDict:
    return _data(
        api.decide_mating_recommendation(
            recommendation_id, factories.decision_payload(decision), headers or ADVISOR
        ),
        200,
    )


# ------------------------------------------------------------- read helpers
def read_sire(api: ApiClient, sire_id: str) -> JsonDict:
    return _data(api.get_sire(sire_id, DIRECTOR), 200)


def read_facility(api: ApiClient, facility_id: str) -> JsonDict:
    return _data(api.get_facility(facility_id, DIRECTOR), 200)


def read_health_test(api: ApiClient, test_id: str) -> JsonDict:
    return _data(api.get_health_test(test_id, VET), 200)


def read_booking(api: ApiClient, booking_id: str) -> JsonDict:
    return _data(api.get_booking(booking_id, DIRECTOR), 200)


def read_ejaculate(api: ApiClient, ejaculate_id: str) -> JsonDict:
    return _data(api.get_ejaculate(ejaculate_id, TECH), 200)


def read_lot(api: ApiClient, lot_id: str) -> JsonDict:
    return _data(api.get_straw_lot(lot_id, DIRECTOR), 200)


def read_evaluation(api: ApiClient, evaluation_id: str) -> JsonDict:
    return _data(api.get_genomic_evaluation(evaluation_id, DIRECTOR), 200)


def read_certificate(api: ApiClient, certificate_id: str) -> JsonDict:
    return _data(api.get_export_certificate(certificate_id, COORDINATOR), 200)


def read_distributor(api: ApiClient, distributor_id: str) -> JsonDict:
    return _data(api.get_distributor(distributor_id, DIRECTOR), 200)


def read_tank(api: ApiClient, tank_id: str) -> JsonDict:
    return _data(api.get_tank(tank_id, DIRECTOR), 200)


def read_transfer(api: ApiClient, transfer_id: str) -> JsonDict:
    return _data(api.get_consignment_transfer(transfer_id, DIRECTOR), 200)


def read_herd(api: ApiClient, herd_id: str) -> JsonDict:
    return _data(api.get_customer_herd(herd_id, ADVISOR), 200)


def read_recommendation(api: ApiClient, recommendation_id: str) -> JsonDict:
    return _data(api.get_mating_recommendation(recommendation_id, ADVISOR), 200)


def read_valuation(api: ApiClient) -> JsonDict:
    return _data(api.get_inventory_valuation(DIRECTOR), 200)


def plant_value(api: ApiClient) -> int:
    return read_valuation(api)["plant_inventory_value_cents"]
