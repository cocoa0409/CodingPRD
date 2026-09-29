"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, and uses the lenient success validator so a broken setup step
reports as a setup failure rather than as an assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .assertions import shift_instant
from .constants import CLOCK_STARTUP
from .factories import (
    market_requirement_payload, brand_payload, style_payload,
    material_input_payload, fiber_test_payload, care_test_payload,
    fiber_results_payload, care_results_payload, permanent_label_payload,
    hangtag_payload, import_shipment_payload, marking_review_payload,
    compliance_audit_payload, audit_finding_payload, disposition_payload,
    DEFAULT_FIBER_TEXT,
)
from .test_users import TEST_USERS, make_brand_admin_headers

ADMIN = TEST_USERS["compliance_admin_headers"]
LAB = TEST_USERS["accredited_lab_headers"]
SPECIALIST = TEST_USERS["labeling_specialist_headers"]
SPECIALIST_2 = TEST_USERS["labeling_specialist_2_headers"]
APPROVER = TEST_USERS["labeling_approver_headers"]
APPROVER_2 = TEST_USERS["labeling_approver_2_headers"]
CUSTOMS = TEST_USERS["customs_officer_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# --- logical clock -------------------------------------------------------

def set_clock(current_utc: str) -> str:
    data = get_success_data(api.set_clock(current_utc, ADMIN))
    return data["current_utc"]


# --- registry tier -------------------------------------------------------

def register_market(market_code="US", **overrides) -> dict:
    payload = market_requirement_payload(market_code=market_code, **overrides)
    return get_success_data(api.create_market_requirement(payload, ADMIN))


def register_brand(**overrides) -> dict:
    return get_success_data(api.create_brand(brand_payload(**overrides), ADMIN))


def register_licensee(licensor_id, **overrides) -> dict:
    payload = brand_payload(
        legal_name="Licensee Apparel Co", party_type="LICENSEE",
        licensor_brand_id=licensor_id, responsibility_mode="LICENSOR_OF_RECORD",
        **overrides)
    return get_success_data(api.create_brand(payload, ADMIN))


# --- style tier ----------------------------------------------------------

def create_style(brand_id=None, **overrides) -> dict:
    if brand_id is None:
        brand_id = register_brand()["id"]
    return get_success_data(api.create_style(style_payload(brand_id, **overrides), ADMIN))


def read_style(style_id) -> dict:
    return get_success_data(api.get_style(style_id, ADMIN))


def style_version(style_id) -> int:
    return read_style(style_id)["version"]


def replace_declaration(style_id, declared_fibers) -> dict:
    payload = {"declared_fibers": declared_fibers,
               "expected_style_version": style_version(style_id)}
    return get_success_data(api.replace_fiber_declaration(style_id, payload, ADMIN))


# --- supply graph tier ---------------------------------------------------

def add_material_input(style_id, **overrides) -> dict:
    payload = material_input_payload(**overrides)
    return get_success_data(api.create_material_input(style_id, payload, ADMIN))


# The default graph: one YARN root and one CUT_AND_SEW node made from it, both
# in US. It satisfies both origin pools and makes both variants select US.
DEFAULT_GRAPH = [
    {"stage": "YARN", "country_code": "US", "value_added_usd": 100.00,
     "weight_grams": 400.0},
    {"stage": "CUT_AND_SEW", "country_code": "US", "value_added_usd": 200.00,
     "weight_grams": 500.0, "_parent": 0},
]


def build_supply_graph(style_id, nodes=None) -> list:
    """Append each node spec in order. A node may name `_parent`, the index of
    an already-appended node in this same list, to become its child."""
    created = []
    for spec in (nodes if nodes is not None else DEFAULT_GRAPH):
        spec = dict(spec)
        parent_index = spec.pop("_parent", None)
        if parent_index is not None:
            spec["parent_input_id"] = created[parent_index]["id"]
        created.append(add_material_input(style_id, **spec))
    return created


# --- origin determination tier -------------------------------------------

def draft_determination(style_id, headers=None) -> dict:
    payload = {"style_id": style_id, "expected_style_version": style_version(style_id)}
    return get_success_data(
        api.create_origin_determination(payload, headers or ADMIN))


def issue_determination(determination_id, method="SUBSTANTIAL_TRANSFORMATION") -> dict:
    return get_success_data(
        api.issue_origin_determination(determination_id, {"method": method}, ADMIN))


def setup_issued_origin(style_id, method="SUBSTANTIAL_TRANSFORMATION",
                        graph=None) -> dict:
    """Supply graph + drafted determination + issuance. Returns the issued row."""
    build_supply_graph(style_id, graph)
    draft = draft_determination(style_id)
    return issue_determination(draft["id"], method)


# --- laboratory tier -----------------------------------------------------

def reserve_fiber_test(style_id, **overrides) -> dict:
    payload = fiber_test_payload(style_id, **overrides)
    return get_success_data(api.create_lab_test(payload, LAB))


def reserve_care_test(style_id, **overrides) -> dict:
    payload = care_test_payload(style_id, **overrides)
    return get_success_data(api.create_lab_test(payload, LAB))


def post_results(lab_test_id, payload) -> dict:
    return get_success_data(api.post_lab_test_results(lab_test_id, payload, LAB))


def pass_fiber_test(style_id, measured_fibers=None, reserve_overrides=None) -> dict:
    test = reserve_fiber_test(style_id, **(reserve_overrides or {}))
    body = (fiber_results_payload() if measured_fibers is None
            else {"measured_fibers": measured_fibers})
    return post_results(test["id"], body)


def fail_fiber_test(style_id, measured_fibers, reserve_overrides=None) -> dict:
    test = reserve_fiber_test(style_id, **(reserve_overrides or {}))
    return post_results(test["id"], {"measured_fibers": measured_fibers})


def pass_care_test(style_id, reserve_overrides=None, results_overrides=None) -> dict:
    test = reserve_care_test(style_id, **(reserve_overrides or {}))
    return post_results(test["id"], care_results_payload(**(results_overrides or {})))


# --- composite: a style ready for label approval --------------------------

def setup_label_ready_style(markets=None, brand_overrides=None, style_overrides=None,
                            graph=None, origin_method="SUBSTANTIAL_TRANSFORMATION",
                            measured_fibers=None, care_reserve=None,
                            care_results=None, skip_fiber=False,
                            skip_origin=False, skip_care=False) -> dict:
    """Registry + brand + style + supply graph + issued determination + a passed
    fiber-content run + a passed care-performance run.

    Returns a bundle whose keys are: markets, brand, style, determination,
    fiber_test, care_test. Each `skip_*` flag leaves the matching piece of
    evidence out so a caller can test the gate that misses it.
    """
    registered = []
    for spec in (markets if markets is not None else [{}]):
        spec = dict(spec)
        code = spec.pop("market_code", "US")
        registered.append(register_market(code, **spec))
    brand = register_brand(**(brand_overrides or {}))
    style_kwargs = dict(style_overrides or {})
    style_kwargs.setdefault("target_market_codes",
                            [m["market_code"] for m in registered])
    style = create_style(brand["id"], **style_kwargs)

    determination = None
    if not skip_origin:
        determination = setup_issued_origin(style["id"], origin_method, graph)
    elif graph is not None:
        build_supply_graph(style["id"], graph)

    fiber_test = None
    if not skip_fiber:
        fiber_test = pass_fiber_test(style["id"], measured_fibers)

    care_test = None
    if not skip_care:
        care_test = pass_care_test(style["id"], care_reserve, care_results)

    return {
        "markets": registered,
        "market": registered[0],
        "brand": brand,
        "style": read_style(style["id"]),
        "determination": determination,
        "fiber_test": fiber_test,
        "care_test": care_test,
    }


def label_payload_for(bundle, **overrides) -> dict:
    """A permanent-label payload whose printed strings agree with the bundle's
    style declaration and issued determination."""
    style = bundle["style"]
    determination = bundle["determination"]
    care_test = bundle["care_test"]
    payload = permanent_label_payload(
        style["id"],
        determination["id"] if determination else None,
        care_test["id"] if care_test else None,
        market_codes=list(style["target_market_codes"]),
        fiber_content_text=style["effective_fiber_content_text"] or DEFAULT_FIBER_TEXT,
        origin_text=("Made in " + determination["determined_country"]
                     if determination and determination.get("determined_country")
                     else "Made in US"),
        wash_temp_c=care_test["wash_temp_c"] if care_test else 40,
    )
    languages = sorted({lang for m in bundle["markets"]
                        for lang in m["required_languages"]})
    payload["languages"] = languages or ["en"]
    payload.update(overrides)
    return payload


def draft_permanent_label(bundle, headers=None, **overrides) -> dict:
    payload = label_payload_for(bundle, **overrides)
    return get_success_data(api.create_label_spec(payload, headers or SPECIALIST))


def submit_label(label_spec_id, headers=None) -> dict:
    return get_success_data(api.submit_label_spec(label_spec_id, headers or SPECIALIST))


def approve_label(label_spec_id, headers=None) -> dict:
    return get_success_data(api.approve_label_spec(label_spec_id, headers or APPROVER))


def publish_label(label_spec_id, effective_from="2026-09-01T00:00:00Z",
                  effective_to="2026-12-01T00:00:00Z", headers=None) -> dict:
    return get_success_data(api.publish_label_spec(
        label_spec_id, effective_from, effective_to, headers or APPROVER))


def setup_pending_permanent_label(bundle=None, label_overrides=None, **bundle_kwargs):
    """Returns (bundle, label) with the label sitting in PENDING_APPROVAL."""
    bundle = bundle or setup_label_ready_style(**bundle_kwargs)
    label = draft_permanent_label(bundle, **(label_overrides or {}))
    label = submit_label(label["id"])
    return bundle, label


def setup_approved_permanent_label(bundle=None, label_overrides=None, **bundle_kwargs):
    bundle, label = setup_pending_permanent_label(bundle, label_overrides,
                                                  **bundle_kwargs)
    return bundle, approve_label(label["id"])


def setup_published_permanent_label(bundle=None, label_overrides=None,
                                    effective_from="2026-09-01T00:00:00Z",
                                    effective_to="2026-12-01T00:00:00Z",
                                    **bundle_kwargs):
    bundle, label = setup_approved_permanent_label(bundle, label_overrides,
                                                   **bundle_kwargs)
    return bundle, publish_label(label["id"], effective_from, effective_to)


def read_label(label_spec_id) -> dict:
    return get_success_data(api.get_label_spec(label_spec_id, ADMIN))


# --- hangtags -------------------------------------------------------------

def create_hangtag(parent, headers=None, **overrides) -> dict:
    """Create a hangtag against the parent permanent label, reading the parent's
    current version for the concurrency guard."""
    parent_row = read_label(parent["id"] if isinstance(parent, dict) else parent)
    payload = hangtag_payload(parent_row["version"])
    payload["fiber_content_text"] = parent_row["fiber_content_text"]
    payload["origin_text"] = parent_row["origin_text"]
    payload["market_codes"] = list(parent_row["market_codes"])
    payload["languages"] = list(parent_row["languages"])
    payload.update(overrides)
    return get_success_data(
        api.create_hangtag(parent_row["id"], payload, headers or SPECIALIST))


# --- imported goods -------------------------------------------------------

def file_shipment(importer_brand_id, style_id, **overrides) -> dict:
    payload = import_shipment_payload(importer_brand_id, style_id, **overrides)
    return get_success_data(api.create_import_shipment(payload, ADMIN))


def review_shipment(shipment_id, outcome="DEFICIENT", deficiency_code="MISSING_ORIGIN"):
    payload = {"outcome": outcome}
    if deficiency_code is not None and outcome == "DEFICIENT":
        payload["deficiency_code"] = deficiency_code
    return get_success_data(api.marking_review(shipment_id, payload, CUSTOMS))


def correct_shipment(shipment_id, corrective_label_spec_id, corrected_units) -> dict:
    payload = {"corrective_label_spec_id": corrective_label_spec_id,
               "corrected_units": corrected_units}
    return get_success_data(api.correct_import_shipment(shipment_id, payload, ADMIN))


def setup_deficient_shipment(brand_id=None, style_id=None, **shipment_overrides):
    """A filed entry driven through a deficient marking review. Returns
    (brand_id, style_id, shipment)."""
    if style_id is None:
        register_market("US")
        brand_id = brand_id or register_brand()["id"]
        style_id = create_style(brand_id)["id"]
    shipment = file_shipment(brand_id, style_id, **shipment_overrides)
    return brand_id, style_id, review_shipment(shipment["id"])


def read_brand(brand_id) -> dict:
    return get_success_data(api.get_brand(brand_id, ADMIN))


def assess_penalty_of(brand_id, style_id, amount_usd, market_code="US",
                      quantity_units=100, **overrides) -> dict:
    """File and review one deficient entry whose assessed penalty is exactly
    `amount_usd`. The regime at `market_code` must carry a marking_duty_rate of
    0.5, so an OPEN posture assesses declared_value_usd * 0.5 under AD_VALOREM.
    Returns the reviewed entry."""
    shipment = file_shipment(brand_id, style_id,
                             quantity_units=quantity_units,
                             declared_value_usd=round(amount_usd * 2, 2),
                             entry_market_code=market_code, **overrides)
    return review_shipment(shipment["id"])


def setup_suspended_brand(style_overrides=None):
    """Drive a brand's penalty ledger strictly past USD 25,000.00 so its posture
    reads SUSPENDED. Returns (market, brand, style, shipment)."""
    market = register_market("US", marking_duty_rate=0.500)
    brand = register_brand()
    style = create_style(brand["id"], **(style_overrides or {}))
    shipment = assess_penalty_of(brand["id"], style["id"], 25_000.01,
                                 quantity_units=100_000)
    return market, brand, style, shipment


# --- audits and findings --------------------------------------------------

def open_audit(brand_id, **overrides) -> dict:
    payload = compliance_audit_payload(brand_id, **overrides)
    return get_success_data(api.create_compliance_audit(payload, AUDITOR))


def raise_finding(audit_id, style_id, **overrides) -> dict:
    payload = audit_finding_payload(style_id, **overrides)
    return get_success_data(api.create_audit_finding(audit_id, payload, AUDITOR))


def record_disposition(finding_id, units_relabeled=0, units_destroyed=0,
                       units_released=0, corrective_label_spec_id=None) -> dict:
    payload = disposition_payload(units_relabeled, units_destroyed, units_released,
                                  corrective_label_spec_id)
    return get_success_data(
        api.record_finding_disposition(finding_id, payload, SPECIALIST))


def verify_finding(finding_id) -> dict:
    return get_success_data(api.verify_finding(finding_id, AUDITOR))


def reopen_finding(finding_id, reopen_reason="the correction did not hold") -> dict:
    return get_success_data(api.reopen_finding(finding_id, reopen_reason, AUDITOR))


def read_audit(audit_id) -> dict:
    return get_success_data(api.get_compliance_audit(audit_id, AUDITOR))


def read_finding(finding_id) -> dict:
    return get_success_data(api.get_audit_finding(finding_id, AUDITOR))


def setup_audit_with_findings(brand_id=None, style_id=None, finding_specs=None):
    """Open one audit over a brand and raise the given findings inside it.
    Returns (brand_id, style_id, audit, findings)."""
    if style_id is None:
        register_market("US")
        brand_id = brand_id or register_brand()["id"]
        style_id = create_style(brand_id)["id"]
    audit = open_audit(brand_id)
    findings = [raise_finding(audit["id"], style_id, **spec)
                for spec in (finding_specs or [{}])]
    return brand_id, style_id, read_audit(audit["id"]), findings


def setup_restricted_brand(brand_id=None, style_id=None):
    """Drive a brand to RESTRICTED posture: one audit in IN_REVIEW carrying three
    CRITICAL findings. Returns (brand_id, style_id, audit, findings)."""
    return setup_audit_with_findings(
        brand_id, style_id,
        finding_specs=[
            {"finding_code": "FIBER_CONTENT_MISSTATED", "units_affected": 100},
            {"finding_code": "ORIGIN_MISSTATED", "units_affected": 200},
            {"finding_code": "CARE_UNSUBSTANTIATED", "units_affected": 5000},
        ])


def setup_remediated_finding(brand_id=None, style_id=None, units_affected=100):
    """One audit, one finding, disposition recorded. Returns (audit, finding)."""
    brand_id, style_id, audit, findings = setup_audit_with_findings(
        brand_id, style_id, finding_specs=[{"units_affected": units_affected}])
    finding = record_disposition(findings[0]["id"], units_destroyed=units_affected)
    return audit, finding
