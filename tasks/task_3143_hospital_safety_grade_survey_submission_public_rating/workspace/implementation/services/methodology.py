"""Methodology versions, hospital pins and pending methodology changes."""

from calculations import (
    DERIVATION_RULES,
    DOMAINS,
    is_comparable,
    methodology_comparability_index,
)
from db import BaseRecord, clock, format_instant, store
from errors import (
    ApiError,
    ERR_HOSPITAL_METHODOLOGY_VERSION_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_METHODOLOGY_NOT_COMPARABLE,
    ERR_METHODOLOGY_VERSION_NOT_FOUND,
    ERR_PENDING_METHODOLOGY_CHANGE_NOT_FOUND,
)

from services.hospitals import get_hospital

CHANGE_APPLY = "APPLY"
CHANGE_REJECT = "REJECT_NOT_COMPARABLE"
CHANGE_WITHDRAW = "WITHDRAW"


class MethodologyVersion(BaseRecord):
    entity_name = "MethodologyVersion"


class HospitalMethodologyVersion(BaseRecord):
    entity_name = "HospitalMethodologyVersion"


class PendingMethodologyChange(BaseRecord):
    entity_name = "PendingMethodologyChange"


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get_methodology_version(version_id):
    version = store.methodology_versions.get(version_id)
    if version is None:
        raise ApiError(ERR_METHODOLOGY_VERSION_NOT_FOUND)
    return version


def get_hospital_methodology_version(row_id):
    row = store.hospital_methodology_versions.get(row_id)
    if row is None:
        raise ApiError(ERR_HOSPITAL_METHODOLOGY_VERSION_NOT_FOUND)
    return row


def get_pending_change(change_id):
    change = store.pending_methodology_changes.get(change_id)
    if change is None:
        raise ApiError(ERR_PENDING_METHODOLOGY_CHANGE_NOT_FOUND)
    return change


def current_pin(hospital_id):
    rows = [
        row for row in store.hospital_methodology_versions.values()
        if row["hospital_id"] == hospital_id and row.get("is_current")
    ]
    if not rows:
        return None
    rows.sort(key=lambda item: (item["created_at"], item["id"]))
    return rows[-1]


# ---------------------------------------------------------------------------
# Version authoring and publication
# ---------------------------------------------------------------------------

def _validate_definitions(raw_definitions):
    if not isinstance(raw_definitions, list) or not raw_definitions:
        raise ApiError(ERR_INVALID_REQUEST)
    definitions = []
    for entry in raw_definitions:
        if not isinstance(entry, dict):
            raise ApiError(ERR_INVALID_REQUEST)
        code = entry.get("measure_code")
        domain = entry.get("domain")
        rule = entry.get("derivation_rule", "NONE")
        if not isinstance(code, str) or code.strip() == "":
            raise ApiError(ERR_INVALID_REQUEST)
        if domain not in DOMAINS:
            raise ApiError(ERR_INVALID_REQUEST)
        if rule not in DERIVATION_RULES:
            raise ApiError(ERR_INVALID_REQUEST)
        for key in ("scale_factor", "weight"):
            if entry.get(key) is None:
                raise ApiError(ERR_INVALID_REQUEST)
        definition = {
            "measure_code": code,
            "domain": domain,
            "scale_factor": entry.get("scale_factor"),
            "weight": entry.get("weight"),
            # PRD §2.10 declares each definition entry as carrying a
            # `multiplier`; PRD §3.5 multiplies it into the domain term and
            # into the effective weight. Dropping it here makes every domain
            # fall back to a multiplier of 1 and inflates the composite.
            "multiplier": entry.get("multiplier", 1),
            "peer_mean": entry.get("peer_mean"),
            "peer_sd": entry.get("peer_sd"),
            "higher_is_better": entry.get("higher_is_better", True),
            "derivation_rule": rule,
        }
        if entry.get("domain_multiplier") is not None:
            definition["domain_multiplier"] = entry.get("domain_multiplier")
        definitions.append(definition)
    return definitions


def create_methodology_version(payload):
    label = payload.get("label")
    if not isinstance(label, str) or label.strip() == "":
        raise ApiError(ERR_INVALID_REQUEST)
    definitions = _validate_definitions(payload.get("measure_definitions"))
    publication_date = payload.get("publication_date")
    if not isinstance(publication_date, str):
        raise ApiError(ERR_INVALID_REQUEST)
    previous_version_id = payload.get("previous_version_id")
    if previous_version_id is not None:
        if not isinstance(previous_version_id, str):
            raise ApiError(ERR_INVALID_REQUEST)
        if previous_version_id not in store.methodology_versions:
            raise ApiError(ERR_METHODOLOGY_VERSION_NOT_FOUND)

    version = MethodologyVersion(
        label=label,
        previous_version_id=previous_version_id,
        measure_definitions=definitions,
        status="DRAFT",
        publication_date=publication_date,
        comparability_index=None,
    )
    store.methodology_versions[version["id"]] = version
    return version


def publish_methodology_version(version):
    if version.get("status") != "PUBLISHED":
        version["status"] = "PUBLISHED"
    previous_id = version.get("previous_version_id")
    if previous_id is None:
        version["comparability_index"] = None
    else:
        previous = store.methodology_versions.get(previous_id)
        if previous is None:
            version["comparability_index"] = None
        else:
            version["comparability_index"] = methodology_comparability_index(
                version.get("measure_definitions") or [],
                previous.get("measure_definitions") or [],
            )
    version.touch()
    return version


# ---------------------------------------------------------------------------
# Comparability between two versions (the pin/change floor)
# ---------------------------------------------------------------------------

def comparability_between(earlier_version_id, later_version_id):
    earlier = store.methodology_versions.get(earlier_version_id)
    later = store.methodology_versions.get(later_version_id)
    if earlier is None or later is None:
        return None
    return methodology_comparability_index(
        later.get("measure_definitions") or [],
        earlier.get("measure_definitions") or [],
    )


def enforce_comparable(earlier_version_id, later_version_id):
    """A change whose index falls below the 0.80 floor is refused."""
    if earlier_version_id is None:
        return None
    index = comparability_between(earlier_version_id, later_version_id)
    if index is None:
        return None
    if not is_comparable(index):
        raise ApiError(ERR_METHODOLOGY_NOT_COMPARABLE)
    return index


# ---------------------------------------------------------------------------
# Pinning
# ---------------------------------------------------------------------------

def pin_version(hospital, methodology_version_id):
    version = get_methodology_version(methodology_version_id)
    current = current_pin(hospital["id"])
    enforce_comparable(current["methodology_version_id"] if current else None, version["id"])

    if current is not None:
        current["is_current"] = False
        current.touch()

    row = HospitalMethodologyVersion(
        hospital_id=hospital["id"],
        methodology_version_id=version["id"],
        pinned_at=format_instant(clock.now()),
        is_current=True,
    )
    store.hospital_methodology_versions[row["id"]] = row
    hospital["active_methodology_version_id"] = version["id"]
    hospital.touch()
    return row


# ---------------------------------------------------------------------------
# Pending methodology changes
# ---------------------------------------------------------------------------

def create_pending_change(hospital, payload):
    to_version_id = payload.get("to_methodology_version_id")
    if not isinstance(to_version_id, str) or to_version_id.strip() == "":
        raise ApiError(ERR_INVALID_REQUEST)
    get_methodology_version(to_version_id)

    current = current_pin(hospital["id"])
    if current is None:
        raise ApiError(ERR_INVALID_REQUEST)

    change = PendingMethodologyChange(
        hospital_id=hospital["id"],
        to_methodology_version_id=to_version_id,
        from_hospital_methodology_version_id=current["id"],
        comparability_index=comparability_between(current["methodology_version_id"], to_version_id),
        status="PENDING",
        decided_by_user_id=None,
    )
    store.pending_methodology_changes[change["id"]] = change
    hospital.touch()
    return change


def review_pending_change(change, decision, reviewer_user_id):
    if not isinstance(decision, str) or decision.strip() == "":
        raise ApiError(ERR_INVALID_REQUEST)
    decision = decision.strip().upper()

    hospital = get_hospital(change["hospital_id"])
    source_row = store.hospital_methodology_versions.get(change["from_hospital_methodology_version_id"])
    source_version_id = source_row["methodology_version_id"] if source_row else None

    change["decided_by_user_id"] = reviewer_user_id

    if decision == "APPLY":
        enforce_comparable(source_version_id, change["to_methodology_version_id"])
        change["status"] = "APPLIED"
        if source_row is not None:
            source_row["is_current"] = False
            source_row.touch()
        row = HospitalMethodologyVersion(
            hospital_id=hospital["id"],
            methodology_version_id=change["to_methodology_version_id"],
            pinned_at=format_instant(clock.now()),
            is_current=True,
        )
        store.hospital_methodology_versions[row["id"]] = row
        hospital["active_methodology_version_id"] = change["to_methodology_version_id"]
    elif decision == "REJECT_NOT_COMPARABLE":
        change["status"] = "REJECTED_NOT_COMPARABLE"
    elif decision == "WITHDRAW":
        change["status"] = "WITHDRAWN"
    else:
        raise ApiError(ERR_INVALID_REQUEST)

    change.touch()
    hospital.touch()
    return change