"""Data licenses and the usage events metered against them (PRD 3.9)."""

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
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LICENSE_TERM_CLOSED,
    ERR_LICENSE_TERM_OVERLAP,
    ERR_ORG_NOT_IN_GOOD_STANDING,
    ERR_PERMITTED_USE_NOT_IN_TIER,
    ERR_QUOTA_EXCEEDED,
    ERR_USAGE_EVENT_NOT_FOUND,
)

bp = Blueprint("licenses", __name__)

DATASET_SCOPES = (
    "ORGANIZATION_PROFILES", "FILING_FINANCIALS", "GRANT_HISTORY", "LEADERSHIP_COMPENSATION",
)


def _half_open_overlap(start_a, end_a, start_b, end_b):
    """[start, end) intervals; an adjacent term is not an overlap."""
    if None in (start_a, end_a, start_b, end_b):
        return False
    return start_a < end_b and start_b < end_a


@bp.route("/nonprofits/licenses/<license_id>", methods=["GET"])
def get_license(license_id):
    acting = auth.actor()
    auth.require_role(acting, (
        auth.ROLE_PLATFORM_ADMIN, auth.ROLE_PLATFORM_VERIFIER, auth.ROLE_DATA_CONSUMER,
    ))
    license_row = svc.get_license(license_id)
    return response.ok(svc.ser_license(license_row))


@bp.route("/nonprofits/licenses/<license_id>/activate", methods=["POST"])
def activate_license(license_id):
    acting = auth.actor()
    auth.require_role(acting, (auth.ROLE_DATA_CONSUMER,))
    license_row = svc.get_license(license_id)
    auth.require_owner(acting, license_row.get("licensee_organization_id"), "licenses")

    data = webutil.body()
    webutil.reject_unknown(data, ())

    if license_row.get("status") != "DRAFT":
        raise ApiError(
            ERR_INVALID_STATE,
            "A license in %s status cannot be activated." % license_row.get("status"),
        )

    licensee = svc.get_organization(license_row.get("licensee_organization_id"))
    if licensee.get("profile_status") != "ACTIVE":
        raise ApiError(
            ERR_ORG_NOT_IN_GOOD_STANDING,
            "The licensee organization must be ACTIVE to activate a license.",
        )

    tier = license_row.get("tier")
    permitted = calc.PERMITTED_USES_BY_TIER.get(tier, ())
    if license_row.get("permitted_use") not in permitted:
        raise ApiError(
            ERR_PERMITTED_USE_NOT_IN_TIER,
            "permitted_use '%s' is not permitted for tier %s."
            % (license_row.get("permitted_use"), tier),
        )

    term_start = clock.parse_dt(license_row.get("term_start"))
    term_end = clock.parse_dt(license_row.get("term_end"))
    for other in store.where("licenses", licensee_organization_id=license_row.get("licensee_organization_id")):
        if other["id"] == license_row["id"]:
            continue
        if other.get("tier") != tier:
            continue
        if other.get("status") == "EXPIRED":
            continue
        if _half_open_overlap(
            term_start, term_end,
            clock.parse_dt(other.get("term_start")),
            clock.parse_dt(other.get("term_end")),
        ):
            raise ApiError(
                ERR_LICENSE_TERM_OVERLAP,
                "The term overlaps an existing non-EXPIRED license of the same tier.",
            )

    if (license_row.get("projected_annual_records") or 0) < 1:
        raise ApiError(
            ERR_INVALID_REQUEST, "projected_annual_records must be at least 1."
        )

    license_row["status"] = "ACTIVE"
    license_row["included_records"] = calc.TIER_INCLUDED_RECORDS[tier]
    license_row["projected_annual_fee_cents"] = calc.license_fee_cents(
        tier, license_row.get("projected_annual_records") or 0
    )
    license_row["final_annual_fee_cents"] = calc.license_fee_cents(
        tier, license_row.get("records_accessed") or 0
    )
    license_row["overage_records"] = max(
        0, (license_row.get("records_accessed") or 0) - license_row["included_records"]
    )
    license_row["overage_flag"] = (
        (license_row.get("records_accessed") or 0) > license_row["included_records"]
    )
    store.touch(license_row)

    svc.recompute_counters(licensee)
    store.touch(licensee)
    return response.ok(svc.ser_license(license_row))


@bp.route("/nonprofits/licenses/<license_id>/usage-events", methods=["POST"])
def post_usage_event(license_id):
    acting = auth.actor()
    auth.require_role(acting, (auth.ROLE_DATA_CONSUMER,))
    license_row = svc.get_license(license_id)
    auth.require_owner(acting, license_row.get("licensee_organization_id"), "licenses")

    data = webutil.body()
    webutil.reject_unknown(data, ("dataset_scope", "record_count", "purpose_code"))
    dataset_scope = webutil.as_enum(data, "dataset_scope", DATASET_SCOPES)
    record_count = webutil.as_int(data, "record_count", minimum=1)
    purpose_code = webutil.as_string(data, "purpose_code")

    if license_row.get("status") != "ACTIVE":
        raise ApiError(
            ERR_INVALID_STATE,
            "A usage event may be posted only against an ACTIVE license.",
        )

    included = license_row.get("included_records") or 0
    accessed = license_row.get("records_accessed") or 0
    if accessed + record_count > included * calc.QUOTA_HARD_CAP_MULTIPLIER:
        raise ApiError(
            ERR_QUOTA_EXCEEDED,
            "The posting would push records_accessed above the hard cap of %d."
            % (included * calc.QUOTA_HARD_CAP_MULTIPLIER),
        )

    term_start = clock.parse_dt(license_row.get("term_start"))
    term_end = clock.parse_dt(license_row.get("term_end"))
    now = clock.now()
    if term_start is None or term_end is None or not (term_start <= now < term_end):
        raise ApiError(
            ERR_LICENSE_TERM_CLOSED,
            "The logical clock is outside the license term window.",
        )

    event = store.new_row(
        license_id=license_id,
        dataset_scope=dataset_scope,
        record_count=record_count,
        purpose_code=purpose_code,
        status="POSTED",
        occurred_at=clock.fmt_dt(now),
    )
    store.insert("usage_events", event)

    license_row["records_accessed"] = accessed + record_count
    _refresh_license_usage(license_row)
    store.touch(license_row)
    return response.ok(svc.ser_usage_event(event), status=201)


def _refresh_license_usage(license_row):
    tier = license_row.get("tier")
    included = calc.TIER_INCLUDED_RECORDS.get(tier, license_row.get("included_records") or 0)
    accessed = license_row.get("records_accessed") or 0
    license_row["included_records"] = included
    license_row["overage_records"] = max(0, accessed - included)
    license_row["overage_flag"] = accessed > included
    license_row["final_annual_fee_cents"] = calc.license_fee_cents(tier, accessed)


@bp.route("/nonprofits/licenses/<license_id>/usage-events/<event_id>/void", methods=["POST"])
def void_usage_event(license_id, event_id):
    acting = auth.actor()
    auth.require_role(acting, (auth.ROLE_PLATFORM_ADMIN,))
    license_row = svc.get_license(license_id)

    data = webutil.body()
    webutil.reject_unknown(data, ())

    event = svc.get_usage_event(event_id)
    if event.get("license_id") != license_id:
        raise ApiError(
            ERR_USAGE_EVENT_NOT_FOUND,
            "No usage event '%s' exists for license '%s'." % (event_id, license_id),
        )

    if event.get("status") != "POSTED":
        raise ApiError(ERR_INVALID_STATE, "Only a POSTED usage event can be voided.")

    event["status"] = "VOIDED"
    store.touch(event)
    license_row["records_accessed"] = max(
        0, (license_row.get("records_accessed") or 0) - (event.get("record_count") or 0)
    )
    _refresh_license_usage(license_row)
    store.touch(license_row)
    return response.ok(svc.ser_usage_event(event))


@bp.route("/nonprofits/licenses/<license_id>/usage-events", methods=["GET"])
def list_usage_events(license_id):
    acting = auth.actor()
    auth.require_role(acting, (
        auth.ROLE_PLATFORM_ADMIN, auth.ROLE_PLATFORM_VERIFIER, auth.ROLE_DATA_CONSUMER,
    ))
    svc.get_license(license_id)
    rows = store.where("usage_events", license_id=license_id)
    spec = (("status", "status", "str"), ("dataset_scope", "dataset_scope", "str"))
    return listing.list_endpoint(rows, svc.ser_usage_event, spec)
