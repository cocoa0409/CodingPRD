"""Information returns: revision creation, extraction, normalization, voiding."""

from collections import Counter

from flask import Blueprint

import auth
import calc
import clock
import listing
import response
import store
import svc
import webutil
from errors import (
    ApiError,
    ERR_FILING_COVERAGE_OVERLAP,
    ERR_INVALID_REQUEST,
    ERR_NO_EXTRACTED_FIELDS,
    ERR_ORG_NOT_IN_GOOD_STANDING,
    ERR_STALE_ORGANIZATION_VERSION,
    ERR_UNSUPPORTED_FORM_VERSION,
)

bp = Blueprint("filings", __name__)

FORM_TYPES = ("FORM_990", "FORM_990_EZ", "FORM_990_PF")
SOURCES = ("IRS_BULK_XML", "ORG_UPLOAD", "MANUAL_ENTRY")
SCHEDULE_CODES = ("SCHEDULE_A", "SCHEDULE_O", "SCHEDULE_I")

FILING_FIELDS = (
    "organization_id", "form_type", "form_version_year", "tax_year",
    "coverage_start", "coverage_end", "source", "expected_organization_version",
)

READ_ALL = (
    auth.ROLE_PLATFORM_ADMIN, auth.ROLE_PLATFORM_VERIFIER,
    auth.ROLE_ORGANIZATION_USER, auth.ROLE_DATA_CONSUMER,
)


def _overlaps_closed(start_a, end_a, start_b, end_b):
    if start_a is None or end_a is None or start_b is None or end_b is None:
        return False
    return start_a <= end_b and start_b <= end_a


@bp.route("/nonprofits/filings", methods=["POST"])
def create_filing():
    acting = auth.actor()
    auth.require_role(acting, (auth.ROLE_ORGANIZATION_USER, auth.ROLE_PLATFORM_ADMIN))
    data = webutil.body()
    webutil.reject_unknown(data, FILING_FIELDS)

    # Authorization precedes request-shape validation (PRD 2.10 rungs 2 and 4).
    declared_org_id = data.get("organization_id")
    if (acting.role == auth.ROLE_ORGANIZATION_USER and isinstance(declared_org_id, str)
            and declared_org_id != acting.user_id):
        raise ApiError(
            "ERR_FORBIDDEN_ROLE",
            "An OrganizationUser may submit filings only for its own organization.",
        )

    organization_id = webutil.as_string(data, "organization_id")
    form_type = webutil.as_enum(data, "form_type", FORM_TYPES)
    form_version_year = webutil.as_int(data, "form_version_year")
    tax_year = webutil.as_int(data, "tax_year")
    coverage_start_raw = webutil.as_datetime(data, "coverage_start")
    coverage_end_raw = webutil.as_datetime(data, "coverage_end")
    source = webutil.as_enum(data, "source", SOURCES)
    expected_version = webutil.as_int(data, "expected_organization_version")

    org = svc.get_organization(organization_id)

    if expected_version != org.get("version"):
        raise ApiError(
            ERR_STALE_ORGANIZATION_VERSION,
            "expected_organization_version does not match the organization's current version.",
        )

    coverage_start = clock.parse_dt(coverage_start_raw)
    coverage_end = clock.parse_dt(coverage_end_raw)
    if coverage_end < coverage_start:
        raise ApiError(
            ERR_INVALID_REQUEST, "coverage_end must not precede coverage_start."
        )

    for existing in store.where("filings", organization_id=organization_id):
        if existing.get("form_type") == form_type:
            continue
        if existing.get("status") in ("SUPERSEDED", "VOIDED"):
            continue
        if _overlaps_closed(
            coverage_start, coverage_end,
            clock.parse_dt(existing.get("coverage_start")),
            clock.parse_dt(existing.get("coverage_end")),
        ):
            raise ApiError(
                ERR_FILING_COVERAGE_OVERLAP,
                "The coverage interval touches or overlaps a filing with a different form_type.",
            )

    if form_version_year not in calc.SUPPORTED_FORM_VERSION_YEARS:
        raise ApiError(
            ERR_UNSUPPORTED_FORM_VERSION,
            "form_version_year %s is not a supported tax-form version." % form_version_year,
        )

    siblings = [
        f for f in store.where("filings", organization_id=organization_id)
        if f.get("tax_year") == tax_year and f.get("form_type") == form_type
    ]
    revision_number = 1
    if siblings:
        revision_number = 1 + max((f.get("revision_number") or 0) for f in siblings)

    for sibling in siblings:
        if sibling.get("status") in ("SUPERSEDED", "VOIDED"):
            continue
        sibling["pre_supersede_status"] = sibling.get("status")
        sibling["superseded_by_revision_number"] = revision_number
        sibling["status"] = "SUPERSEDED"
        store.touch(sibling)

    filing = store.new_row(
        organization_id=organization_id,
        form_type=form_type,
        form_version_year=form_version_year,
        tax_year=tax_year,
        revision_number=revision_number,
        superseded_by_revision_number=None,
        pre_supersede_status=None,
        coverage_start=coverage_start_raw,
        coverage_end=coverage_end_raw,
        source=source,
        status="RECEIVED",
        extracted_field_count=0,
        total_revenue_cents=0,
        extraction_confidence_pct=None,
        is_verified=False,
    )
    store.insert("filings", filing)
    svc.recompute_revenue(org)
    store.touch(org)
    return response.ok(svc.ser_filing(filing), status=201)


@bp.route("/nonprofits/filings/<filing_id>", methods=["GET"])
def get_filing(filing_id):
    acting = auth.actor()
    auth.require_role(acting, READ_ALL)
    filing = svc.get_filing(filing_id)
    return response.ok(svc.ser_filing(filing))


def _parse_raw_lines(data):
    raw_lines = webutil.as_list(data, "raw_lines")
    parsed = []
    for element in raw_lines:
        if not isinstance(element, dict):
            raise ApiError(ERR_INVALID_REQUEST, "Each raw line must be an object.")
        line_code = webutil.as_string(element, "line_code")
        raw_value = element.get("raw_value")
        if raw_value is None or isinstance(raw_value, bool) or not isinstance(raw_value, (str, int, float)):
            raise ApiError(ERR_INVALID_REQUEST, "Field 'raw_value' is required.")
        raw_format = webutil.as_enum(element, "raw_format", calc.RAW_FORMATS)
        schedule_code = webutil.as_enum(
            element, "schedule_code", SCHEDULE_CODES, required=False, default=None
        )
        is_revenue_component = webutil.as_bool(element, "is_revenue_component", default=False)
        parsed.append({
            "line_code": line_code,
            "raw_value": raw_value,
            "raw_format": raw_format,
            "schedule_code": schedule_code,
            "is_revenue_component": is_revenue_component,
        })
    return parsed


@bp.route("/nonprofits/filings/<filing_id>/extract", methods=["POST"])
def extract_filing(filing_id):
    acting = auth.actor()
    auth.require_role(acting, (auth.ROLE_PLATFORM_VERIFIER,))
    filing = svc.get_filing(filing_id)

    data = webutil.body()
    webutil.reject_unknown(data, ("raw_lines",))
    parsed = _parse_raw_lines(data)

    # State (rung 5) then good standing (rung 6), then the business constraints.
    if filing.get("status") not in ("RECEIVED", "EXTRACTION_FAILED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "A filing in %s status cannot be extracted." % filing.get("status"),
        )
    org = svc.get_organization(filing.get("organization_id"))
    if org.get("profile_status") not in ("DRAFT", "ACTIVE"):
        raise ApiError(
            ERR_ORG_NOT_IN_GOOD_STANDING,
            "The owning organization is not in good standing for extraction.",
        )

    if not parsed:
        raise ApiError(
            ERR_NO_EXTRACTED_FIELDS,
            "raw_lines must contain at least one entry.",
        )

    permitted = calc.FORM_VERSION_LINE_MAP.get(filing.get("form_version_year"))
    if permitted is None:
        raise ApiError(
            ERR_UNSUPPORTED_FORM_VERSION,
            "form_version_year %s is not a supported tax-form version."
            % filing.get("form_version_year"),
        )
    for line in parsed:
        if line["line_code"] not in permitted:
            raise ApiError(
                ERR_UNSUPPORTED_FORM_VERSION,
                "line_code '%s' is not valid for form version %s."
                % (line["line_code"], filing.get("form_version_year")),
            )

    parseable = [line for line in parsed if calc.parse_raw_decimal(line["raw_value"]) is not None]
    if not parseable:
        filing["status"] = "EXTRACTION_FAILED"
        filing["extracted_field_count"] = 0
        filing["extraction_confidence_pct"] = None
        store.touch(filing)
        return response.ok(svc.ser_filing(filing))

    for line in parsed:
        row = store.new_row(
            filing_id=filing_id,
            line_code=line["line_code"],
            raw_value=str(line["raw_value"]),
            raw_format=line["raw_format"],
            schedule_code=line["schedule_code"],
            is_revenue_component=line["is_revenue_component"],
            normalized_value_cents=None,
            normalization_status="PENDING",
            is_verified=False,
            correction_count=0,
            confidence_pct=float(calc.confidence_for(line["raw_format"])),
        )
        store.insert("extracted_fields", row)

    filing["status"] = "EXTRACTED"
    svc.refresh_filing_extraction(filing)
    store.touch(filing)
    return response.ok(svc.ser_filing(filing))


@bp.route("/nonprofits/filings/<filing_id>/normalize", methods=["POST"])
def normalize_filing(filing_id):
    acting = auth.actor()
    auth.require_role(acting, (auth.ROLE_PLATFORM_VERIFIER,))
    filing = svc.get_filing(filing_id)

    data = webutil.body()
    webutil.reject_unknown(data, ())

    # PRD 2.10 ladder: state (rung 5) outranks the good-standing safety gate
    # (rung 6), which outranks the zero-field business constraint (rung 7).
    if filing.get("status") not in ("EXTRACTED", "DISPUTED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "A filing in %s status cannot be normalized." % filing.get("status"),
        )
    org = svc.get_organization(filing.get("organization_id"))
    if org.get("profile_status") not in ("DRAFT", "ACTIVE"):
        raise ApiError(
            ERR_ORG_NOT_IN_GOOD_STANDING,
            "The owning organization is not in good standing for normalization.",
        )
    fields = store.where("extracted_fields", filing_id=filing_id)
    if not fields:
        raise ApiError(
            ERR_NO_EXTRACTED_FIELDS,
            "The filing has no extracted fields to normalize.",
        )

    duplicates = Counter(f.get("line_code") for f in fields)
    for field in fields:
        status = field.get("normalization_status")
        if status not in ("PENDING", "CONFLICT"):
            continue
        if duplicates.get(field.get("line_code"), 0) > 1:
            if status != "CONFLICT":
                field["normalization_status"] = "CONFLICT"
                field["normalized_value_cents"] = None
                store.touch(field)
            continue
        cents = calc.normalize_cents(field.get("raw_value"), field.get("raw_format"))
        if cents is None:
            continue
        field["normalized_value_cents"] = cents
        field["normalization_status"] = "NORMALIZED"
        store.touch(field)

    if filing.get("status") == "EXTRACTED":
        filing["status"] = "NORMALIZED"
    svc.recompute_filing_totals(filing)
    svc.refresh_filing_verified(filing)
    store.touch(filing)

    svc.recompute_revenue(org)
    svc.recompute_scores(org)
    svc.recompute_disclosure(org)
    svc.apply_profile_floor_cascade(org)
    svc.apply_seal_floor_cascade(org)
    store.touch(org)
    return response.ok(svc.ser_filing(filing))


@bp.route("/nonprofits/filings/<filing_id>/void", methods=["POST"])
def void_filing(filing_id):
    acting = auth.actor()
    auth.require_role(acting, (auth.ROLE_PLATFORM_ADMIN,))
    filing = svc.get_filing(filing_id)

    data = webutil.body()
    webutil.reject_unknown(data, ())

    previous_status = filing.get("status")
    if previous_status == "VOIDED":
        raise ApiError("ERR_INVALID_STATE", "The filing is already voided.")

    restored = None
    for candidate in store.where(
        "filings",
        organization_id=filing.get("organization_id"),
        tax_year=filing.get("tax_year"),
        form_type=filing.get("form_type"),
    ):
        if candidate.get("superseded_by_revision_number") == filing.get("revision_number"):
            candidate["status"] = candidate.get("pre_supersede_status") or "NORMALIZED"
            candidate["superseded_by_revision_number"] = None
            candidate["pre_supersede_status"] = None
            store.touch(candidate)
            restored = candidate

    filing["status"] = "VOIDED"
    store.touch(filing)

    org = svc.get_organization(filing.get("organization_id"))
    svc.recompute_revenue(org)
    if previous_status in ("NORMALIZED", "DISPUTED") or (
        restored is not None and restored.get("status") in ("NORMALIZED", "DISPUTED")
    ):
        svc.recompute_scores(org)
        svc.recompute_disclosure(org)
        svc.apply_profile_floor_cascade(org)
        svc.apply_seal_floor_cascade(org)
    store.touch(org)
    return response.ok(svc.ser_filing(filing))


@bp.route("/nonprofits/filings/<filing_id>/extracted-fields", methods=["GET"])
def list_extracted_fields(filing_id):
    acting = auth.actor()
    auth.require_role(acting, READ_ALL)
    svc.get_filing(filing_id)
    rows = store.where("extracted_fields", filing_id=filing_id)
    spec = (
        ("normalization_status", "normalization_status", "str"),
        ("is_revenue_component", "is_revenue_component", "bool"),
    )
    return listing.list_endpoint(rows, svc.ser_extracted_field, spec)


@bp.route("/nonprofits/extracted-fields/<field_id>", methods=["GET"])
def get_extracted_field(field_id):
    acting = auth.actor()
    auth.require_role(acting, READ_ALL)
    field = svc.get_extracted_field(field_id)
    return response.ok(svc.ser_extracted_field(field))
