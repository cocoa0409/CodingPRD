"""Shared lookups (rungs 7 and 8) and list plumbing."""

from db import db
from errors import ApiError
from response import paginated, read_page_params

REGION_PATTERN = r"^[A-Z]{2}$"
REGION_OR_WILDCARD = r"^([A-Z]{2}|\*)$"

CONTENT_TYPES = ("MOVIE", "EPISODE", "LIVE_EVENT")
AVAILABILITY_STATES = ("DRAFT", "SCHEDULED", "PUBLISHED", "TAKEN_DOWN", "EXPIRED")
PACKAGING_STATES = ("UNPACKAGED", "PACKAGING", "PACKAGED", "STALE")
TAKEDOWN_REASONS = ("NONE", "CONTRACT_END", "PACKAGING_STALE", "MANUAL_LEGAL")
QC_STATES = ("INGESTED", "QC_PASSED", "QC_FAILED", "REMEDIATION_REQUESTED", "QC_REJECTED")
CODEC_FAMILIES = ("H264", "HEVC", "AV1")
LADDER_STATES = ("DRAFT", "VALIDATED", "LOCKED", "REJECTED", "SUPERSEDED")
DEVICE_CLASSES = (
    "SMART_TV_4K", "SMART_TV_HD", "MOBILE_HIGH", "MOBILE_LOW",
    "SET_TOP_LEGACY", "BROWSER_HTML5",
)
DRM_SYSTEMS = ("WIDEVINE", "PLAYREADY", "FAIRPLAY")
REQUIRED_DRM_SYSTEMS = ("WIDEVINE", "PLAYREADY", "FAIRPLAY", "NONE")
PROFILE_STATES = ("ACTIVE", "RETIRED")
PACKAGE_STATES = ("PENDING", "PACKAGED", "STALE", "REVOKED")
SUBSCRIPTION_TIERS = ("BASIC", "STANDARD", "PREMIUM", "ANY")
LICENSE_TIERS = ("BASIC", "STANDARD", "PREMIUM")
DEVICE_SCOPES = ("ALL", "TV_ONLY", "MOBILE_ONLY")
HDCP_LEVELS = ("NONE", "TYPE_0", "TYPE_1")
WINDOW_STATES = ("SCHEDULED", "ACTIVE", "CLOSED", "CANCELLED")
VENDOR_STATES = ("ACTIVE", "DEGRADED", "DRAINED")
STEERING_MODES = ("PERFORMANCE", "COST", "WEIGHTED")
POLICY_STATES = ("ACTIVE", "STANDBY_ONLY", "UNROUTABLE")
RESERVATION_STATES = ("RESERVED", "ARMED", "LIVE", "FAILED_OVER", "ENDED", "CANCELLED")
TRIGGER_REASONS = (
    "CODEC_DEPRECATION", "STANDARD_UPDATE", "QUALITY_REGRESSION", "DEVICE_MATRIX_CHANGE",
)
JOB_STATES = ("QUEUED", "RUNNING", "COMPLETED", "FAILED", "ABORTED")


def _fetch(collection, identifier, error_id):
    row = collection.get(identifier) if isinstance(identifier, str) else None
    if row is None:
        raise ApiError(error_id)
    return row


def get_title(identifier):
    return _fetch(db.titles, identifier, "ERR_TITLE_NOT_FOUND")


def get_asset(identifier):
    return _fetch(db.assets, identifier, "ERR_ASSET_NOT_FOUND")


def get_ladder(identifier):
    return _fetch(db.ladders, identifier, "ERR_LADDER_NOT_FOUND")


def get_package(identifier):
    return _fetch(db.packages, identifier, "ERR_PACKAGE_NOT_FOUND")


def get_profile(identifier):
    return _fetch(db.device_profiles, identifier, "ERR_DEVICE_PROFILE_NOT_FOUND")


def get_vendor(identifier):
    return _fetch(db.vendors, identifier, "ERR_VENDOR_NOT_FOUND")


def get_policy(identifier):
    return _fetch(db.policies, identifier, "ERR_POLICY_NOT_FOUND")


def get_reservation(identifier):
    return _fetch(db.reservations, identifier, "ERR_RESERVATION_NOT_FOUND")


def get_window(identifier):
    return _fetch(db.windows, identifier, "ERR_WINDOW_NOT_FOUND")


def get_job(identifier):
    return _fetch(db.jobs, identifier, "ERR_JOB_NOT_FOUND")


def get_metric(identifier):
    return _fetch(db.metrics, identifier, "ERR_METRIC_WINDOW_NOT_FOUND")


def identity(row):
    return row


def respond_list(items):
    page, page_size = read_page_params({})
    return paginated(items, identity, page, page_size)


def send_list(items, page, page_size):
    return paginated(items, identity, page, page_size)


def apply_filters(items, filters, spec_map):
    """spec_map maps a query field to the row field it filters on."""
    out = items
    for field, value in filters.items():
        row_field = spec_map.get(field, field)
        out = [row for row in out if row.get(row_field) == value]
    return out
