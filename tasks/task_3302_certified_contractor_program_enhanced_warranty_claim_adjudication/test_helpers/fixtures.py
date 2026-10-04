"""Composite setup helpers built from PRD-declared endpoints.

The PRD requires install_date to be on or before the current clock date at
registration creation. Since the clock starts at 2026-09-01 and most scenarios
use install_date 2026-09-10, fixtures advance the clock to the install date
before creating the registration and activate immediately, so activated_at
always equals the install date and proration math stays exact.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import REQUIRED_COMPONENT_TYPES, TIER_MIN_CREDITS
from .factories import (
    create_catalog_item_payload,
    create_claim_payload,
    create_complaint_payload,
    create_contractor_payload,
    create_distributor_payload,
    create_lead_assignment_payload,
    create_registration_component_payload,
    create_registration_payload,
    create_training_course_payload,
)
from .test_users import (
    TEST_USERS,
    make_contractor_headers,
    make_distributor_headers,
    make_inspector_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]
CLAIMANT = TEST_USERS["claimant_headers"]


def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_contractor_record(**overrides) -> dict:
    return get_success_data(api_client.create_contractor(create_contractor_payload(**overrides), ADMIN))


def add_training_credits(contractor_id: str, credits: int, validity_months: int = 36,
                       completed_at: str = "2026-09-01") -> dict:
    """Create one course with `credits` credits and a COMPLETED enrollment for the contractor."""
    course = get_success_data(
        api_client.create_training_course(
            create_training_course_payload(credits=credits, validity_months=validity_months), ADMIN
        )
    )
    enr = get_success_data(
        api_client.create_training_enrollment(
            {"contractor_id": contractor_id, "course_id": course["id"]}, ADMIN
        )
    )
    return get_success_data(
        api_client.complete_training_enrollment(enr["id"], {"completed_at": completed_at}, ADMIN)
    )


def make_certified_contractor(tier: str = "BRONZE", validity_months: int = 36,
                              completed_at: str = "2026-09-01",
                              **contractor_overrides) -> dict:
    """Contractor + enough creditable training + certification APPROVEd to ACTIVE.

    Returns dict with keys: contractor, certification.
    """
    contractor = create_contractor_record(**contractor_overrides)
    add_training_credits(contractor["id"], TIER_MIN_CREDITS[tier],
                         validity_months=validity_months, completed_at=completed_at)
    ch = make_contractor_headers(contractor["id"])
    cert = get_success_data(
        api_client.create_certification({"contractor_id": contractor["id"], "tier": tier}, ch)
    )
    cert = get_success_data(api_client.verify_certification(cert["id"], {"decision": "APPROVE"}, ADMIN))
    return {"contractor": contractor, "certification": cert}


def add_catalog_items(skus_by_type=None) -> dict:
    """Create the four required-type catalog items. skus_by_type maps component_type
    -> (sku, manufacturer); defaults to all-GAF SH-G/UN-G/ST-G/RC-G. Returns
    {component_type: sku}."""
    if skus_by_type is None:
        skus_by_type = {
            "SHINGLE": ("SH-G", "GAF"),
            "UNDERLAYMENT": ("UN-G", "GAF"),
            "STARTER": ("ST-G", "GAF"),
            "RIDGE_CAP": ("RC-G", "GAF"),
        }
    result = {}
    for ctype in REQUIRED_COMPONENT_TYPES:
        sku, manufacturer = skus_by_type[ctype]
        get_success_data(
            api_client.create_component_catalog_item(
                create_catalog_item_payload(sku=sku, component_type=ctype, manufacturer=manufacturer),
                ADMIN,
            )
        )
        result[ctype] = sku
    return result


def add_required_components(registration_id: str, contractor_id: str, skus: dict,
                            line_cents: int = 25000, per_line_cents=None) -> None:
    """Add one component line per required type to a DRAFT registration."""
    ch = make_contractor_headers(contractor_id)
    for ctype in REQUIRED_COMPONENT_TYPES:
        cents = line_cents if per_line_cents is None else per_line_cents[ctype]
        get_success_data(
            api_client.create_registration_component(
                create_registration_component_payload(
                    registration_id=registration_id,
                    catalog_sku=skus[ctype],
                    material_cost_cents=cents,
                ),
                ch,
            )
        )


def setup_active_registration(tier: str = "BRONZE", line_cents: int = 25000,
                              install_date: str = "2026-09-10",
                              mixed_manufacturer: bool = False,
                              validity_months: int = 36,
                              **contractor_overrides) -> dict:
    """Full chain: certified contractor + ACTIVE registration with all 4 required
    component types. activated_at == install_date (clock advanced before activation).

    Returns dict with keys: contractor, certification, registration, skus.
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = make_certified_contractor(tier=tier, validity_months=validity_months,
                                    **contractor_overrides)
    contractor, cert = ctx["contractor"], ctx["certification"]
    ch = make_contractor_headers(contractor["id"])
    if mixed_manufacturer:
        skus = add_catalog_items({
            "SHINGLE": ("SH-G", "GAF"),
            "UNDERLAYMENT": ("UN-G", "GAF"),
            "STARTER": ("ST-G", "GAF"),
            "RIDGE_CAP": ("RC-O", "OTHER"),
        })
    else:
        skus = add_catalog_items()
    # install_date must be <= current clock date at registration creation.
    set_clock(install_date + "T00:00:00Z")
    reg = get_success_data(
        api_client.create_warranty_registration(
            create_registration_payload(certification_id=cert["id"], install_date=install_date), ch
        )
    )
    add_required_components(reg["id"], contractor["id"], skus, line_cents=line_cents)
    reg = get_success_data(api_client.activate_warranty_registration(reg["id"], ADMIN))
    return {"contractor": contractor, "certification": cert, "registration": reg, "skus": skus}


def file_claim_with_photos(registration_id: str, claim_labor_cost_cents: int = 10000,
                           file_at: str = None, description: str = "claim") -> dict:
    """Optionally advance the clock, file a claim, add two PHOTO evidence items.

    Returns dict: claim (final state after 2nd photo) and version (current claim version).
    """
    if file_at is not None:
        set_clock(file_at + "T00:00:00Z")
    claim = get_success_data(
        api_client.create_warranty_claim(
            create_claim_payload(registration_id=registration_id,
                                 claim_labor_cost_cents=claim_labor_cost_cents,
                                 description=description),
            CLAIMANT,
        )
    )
    get_success_data(api_client.add_claim_evidence(claim["id"], {"evidence_type": "PHOTO", "note": "x"}, CLAIMANT))
    claim = get_success_data(api_client.add_claim_evidence(claim["id"], {"evidence_type": "PHOTO", "note": "y"}, CLAIMANT))
    return {"claim": claim, "version": claim["version"]}


def adjudicate(claim_id: str, determination: str, expected_claim_version: int) -> dict:
    return get_success_data(
        api_client.adjudicate_claim(
            claim_id,
            {"determination": determination, "expected_claim_version": expected_claim_version},
            ADMIN,
        )
    )


def get_remedy(claim_id: str) -> list:
    return get_success_data(api_client.list_remedy_allocations(claim_id, ADMIN))


def file_and_substantiate_complaint(contractor_id: str, category: str = "WORKMANSHIP") -> dict:
    complaint = get_success_data(
        api_client.create_complaint(
            create_complaint_payload(contractor_id=contractor_id, category=category), CLAIMANT
        )
    )
    return get_success_data(api_client.substantiate_complaint(complaint["id"], ADMIN))


def suspend_contractor_via_complaints(contractor_id: str) -> None:
    """Drive weighted complaint score to exactly 5 (3+2) and suspend the contractor:
    complaint A filed 2026-09-01 era (weight 2 at 2027-08-01), complaint B filed
    2027-06-01 (weight 3), both substantiated at 2027-08-01."""
    cmp_old = get_success_data(
        api_client.create_complaint(create_complaint_payload(contractor_id=contractor_id), CLAIMANT)
    )
    set_clock("2027-06-01T00:00:00Z")
    cmp_new = get_success_data(
        api_client.create_complaint(
            create_complaint_payload(contractor_id=contractor_id, category="COMMUNICATION"), CLAIMANT
        )
    )
    set_clock("2027-08-01T00:00:00Z")
    get_success_data(api_client.substantiate_complaint(cmp_old["id"], ADMIN))
    get_success_data(api_client.substantiate_complaint(cmp_new["id"], ADMIN))


def create_distributor_record(name="Dist", territory_codes=None, lead_pool_total=1) -> dict:
    return get_success_data(
        api_client.create_distributor(
            create_distributor_payload(
                name=name,
                territory_codes=territory_codes or ["T1"],
                lead_pool_total=lead_pool_total,
            ),
            ADMIN,
        )
    )


def assign_lead(distributor_id: str, contractor_id: str, territory_code: str = "T1",
                required_tier: str = "BRONZE", start_date: str = "2026-10-01",
                end_date: str = "2026-11-01") -> dict:
    return get_success_data(
        api_client.create_lead_assignment(
            create_lead_assignment_payload(
                distributor_id=distributor_id,
                contractor_id=contractor_id,
                territory_code=territory_code,
                required_tier=required_tier,
                start_date=start_date,
                end_date=end_date,
            ),
            make_distributor_headers(distributor_id),
        )
    )


def request_schedule_complete_inspection(claim_id: str, inspector_id: str = "INSP-1",
                                         service_date: str = "2027-09-15",
                                         findings: str = "confirmed", confirms_defect: bool = True) -> dict:
    """Request an inspection, schedule it, and have the assigned inspector complete it."""
    order = get_success_data(api_client.request_inspection(claim_id, ADMIN))
    order = get_success_data(
        api_client.schedule_inspection_order(
            order["id"], {"inspector_id": inspector_id, "service_date": service_date}, ADMIN
        )
    )
    return get_success_data(
        api_client.complete_inspection_order(
            order["id"], {"findings": findings, "confirms_defect": confirms_defect},
            make_inspector_headers(inspector_id),
        )
    )
