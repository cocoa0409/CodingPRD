"""Methodology authoring, publishing, disclosure and superseding.

SCAFFOLD state_machines -> Methodology, PRD section 2.9.
"""

from db import base_row, db, now, touch
from errors import fail
from services import common


def create(name, version_code, methodology_code, sector):
    row = base_row()
    row.update(
        {
            "name": name,
            "version_code": version_code,
            "methodology_code": methodology_code,
            "sector": sector,
            "is_public": False,
            "effective_from": None,
            "effective_to": None,
            "status": "DRAFT",
        }
    )
    db.methodologies[row["id"]] = row
    return row


def publish(row):
    if row["status"] != "DRAFT":
        fail("ERR_INVALID_STATE")
    for other in db.methodologies.values():
        if other["id"] == row["id"]:
            continue
        if other["status"] == "PUBLISHED" and other["methodology_code"] == row[
            "methodology_code"
        ] and other["sector"] == row["sector"]:
            fail("ERR_METHODOLOGY_CODE_CONFLICT")
    row["status"] = "PUBLISHED"
    row["effective_from"] = now()
    return touch(row)


def publish_disclosure(row):
    if row["status"] != "PUBLISHED":
        fail("ERR_INVALID_STATE", "Only a published methodology can be publicly disclosed.")
    if row["is_public"]:
        fail("ERR_METHODOLOGY_ALREADY_PUBLIC")
    row["is_public"] = True
    return touch(row)


def supersede(row):
    if row["status"] != "PUBLISHED":
        fail("ERR_INVALID_STATE")
    replacement = False
    for other in db.methodologies.values():
        if other["id"] == row["id"]:
            continue
        if other["status"] == "PUBLISHED" and other["sector"] == row["sector"]:
            replacement = True
            break
    if not replacement:
        fail("ERR_NO_REPLACEMENT_METHODOLOGY")
    row["status"] = "SUPERSEDED"
    row["effective_to"] = now()
    # Existing issuers stay pinned to this version; only future pins are gated.
    return touch(row)


def pinned_or_fail(entity):
    """Resolve the issuer's pinned methodology (existence then ownership)."""
    return common.entity_pinned_methodology(entity)