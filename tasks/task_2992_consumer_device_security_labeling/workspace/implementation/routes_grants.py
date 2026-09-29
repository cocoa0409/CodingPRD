"""Label issuance, registry content, publication, renewal and the public
registry lookup (PRD 3.6, 3.7)."""

import random
import string

from flask import Blueprint

import calc
import cascades
import lookups
import serialize
import store
import validation as v
from auth import (
    CONFORMITY_REVIEWER,
    CONSUMER,
    MANUFACTURER,
    PROGRAM_ADMINISTRATOR,
    RETAILER,
    caller,
    own,
    sod,
)
from envelope import add_days, clock_now, created, iso, ok
from errors import ApiError, bad_request
from store import base_row, touch
from validation import ensure

bp = Blueprint("grants", __name__)

GRANT_STATUSES = ("PENDING_REGISTRY", "ACTIVE", "SUSPENDED", "REVOKED", "EXPIRED")
PUBLICATION_STATUSES = ("DRAFT", "PUBLISHED", "WITHHELD")
UPDATE_CADENCES = ("AUTOMATIC", "USER_INITIATED", "NONE")
PUBLICATION_DECISIONS = ("PUBLISHED", "WITHHELD")
TERMINAL_GRANT_STATUSES = ("REVOKED", "EXPIRED")
GRANT_READERS = (PROGRAM_ADMINISTRATOR, CONFORMITY_REVIEWER, MANUFACTURER, RETAILER)
REGISTRY_READERS = (
    CONSUMER,
    RETAILER,
    PROGRAM_ADMINISTRATOR,
    CONFORMITY_REVIEWER,
    MANUFACTURER,
)

CODE_ALPHABET = string.ascii_uppercase + string.digits
CODE_LENGTH = 16


def _mint_scannable_code():
    while True:
        code = "".join(random.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
        if store.grant_by_code(code) is None:
            return code


def _issuance_gates(product, assessment, now):
    """The six business conditions shared by issuance and renewal, in the
    order PRD 2.6 fixes (rungs 15, 20, 21, 22, 28, 34)."""
    ensure(
        product["eligibility_status"] == "ELIGIBLE",
        "ERR_DEVICE_CLASS_EXCLUDED",
        "The product's device category is outside the program scope.",
    )
    ensure(
        assessment["product_id"] == product["id"],
        "ERR_ASSESSMENT_PRODUCT_MISMATCH",
        "The named assessment does not belong to the named product.",
    )
    ensure(
        assessment["status"] == "APPROVED",
        "ERR_ASSESSMENT_NOT_APPROVED",
        "The named assessment is not APPROVED.",
    )
    ensure(
        assessment["assessed_spec_revision"] == product["spec_revision"]
        and product["conformance_currency"] == "CURRENT",
        "ERR_ASSESSMENT_SPEC_STALE",
        "The assessment predates a spec change.",
    )
    ensure(
        product["declared_support_period_end"] > now,
        "ERR_SUPPORT_PERIOD_EXPIRED",
        "The declared support period has already ended.",
    )
    manufacturer = store.manufacturers.get(product["manufacturer_id"])
    ensure(
        manufacturer is not None and manufacturer["standing"] == "GOOD",
        "ERR_SPONSOR_DELINQUENT",
        "The sponsoring manufacturer is not in good standing.",
    )


@bp.post("/labeling/label-grants")
def create_label_grant():
    actor = caller(MANUFACTURER)
    body = v.raw_body()

    # Ownership (rung 3) reads the product behind the requested grant.
    pending_product = body.get("product_id")
    if isinstance(pending_product, str):
        product_row = store.products.get(pending_product)
        if product_row is not None:
            own(product_row["manufacturer_id"] == actor.user_id)

    lookups.resolve_fk(body, "product_id", lookups.need_product)
    lookups.resolve_fk(body, "assessment_id", lookups.need_assessment)

    product_id = v.field_str(body, "product_id")
    assessment_id = v.field_str(body, "assessment_id")

    product = lookups.need_product(product_id)
    assessment = lookups.need_assessment(assessment_id)

    now = clock_now()
    _issuance_gates(product, assessment, now)

    tier = store.tier_of_product(product)
    row = base_row()
    row.update(
        {
            "product_id": product["id"],
            "assessment_id": assessment["id"],
            "scannable_code": _mint_scannable_code(),
            "grant_status": "PENDING_REGISTRY",
            "registry_publication_status": "DRAFT",
            "suspension_reason": None,
            "renewal_required": False,
            "valid_from": None,
            "valid_until": None,
            "renewal_generation": 0,
            "issuance_fee_cents": calc.label_issuance_fee(tier, 0),
            "superseded_by_grant_id": None,
        }
    )
    store.label_grants[row["id"]] = row
    return created(serialize.label_grant(row))


@bp.get("/labeling/label-grants/<identifier>")
def read_label_grant(identifier):
    caller(*GRANT_READERS)
    return ok(serialize.label_grant(lookups.need_grant(identifier)))


@bp.get("/labeling/label-grants")
def list_label_grants():
    caller(*GRANT_READERS)
    product_id = v.query_str("product_id")
    assessment_id = v.query_str("assessment_id")
    superseded_by = v.query_str("superseded_by_grant_id")
    grant_status = v.query_enum("grant_status", GRANT_STATUSES)
    publication_status = v.query_enum("registry_publication_status", PUBLICATION_STATUSES)

    rows = list(store.label_grants.values())
    if product_id is not None:
        rows = [row for row in rows if row["product_id"] == product_id]
    if assessment_id is not None:
        rows = [row for row in rows if row["assessment_id"] == assessment_id]
    if superseded_by is not None:
        rows = [row for row in rows if row["superseded_by_grant_id"] == superseded_by]
    if grant_status is not None:
        rows = [row for row in rows if row["grant_status"] == grant_status]
    if publication_status is not None:
        rows = [
            row for row in rows if row["registry_publication_status"] == publication_status
        ]
    return lookups.listing(store.sort_created_id(rows), serialize.label_grant)


def _owned_grant(identifier, actor):
    grant = store.label_grants.get(identifier)
    if grant is not None:
        product = store.product_of_grant(grant)
        if product is not None:
            own(product["manufacturer_id"] == actor.user_id)
    return lookups.need_grant(identifier)


def _disclosure_completeness(entry):
    if (
        entry["support_period_end"] is not None
        and entry["update_policy_url"] is not None
        and entry["update_cadence"] != "NONE"
        and entry["vuln_disclosure_contact"] is not None
    ):
        return "COMPLETE"
    return "INCOMPLETE"


@bp.post("/labeling/label-grants/<identifier>/registry-entry")
def create_registry_entry(identifier):
    actor = caller(MANUFACTURER)
    grant = _owned_grant(identifier, actor)
    body = v.raw_body()

    update_policy_url = v.field_str(body, "update_policy_url", max_len=500)
    update_cadence = v.field_enum(body, "update_cadence", UPDATE_CADENCES)
    vuln_disclosure_contact = v.field_str(body, "vuln_disclosure_contact", max_len=320)
    if not update_policy_url.startswith("https://"):
        raise bad_request("Field 'update_policy_url' must begin with 'https://'.")

    existing = store.registry_entry_of_grant(grant["id"])
    ensure(
        existing is None and grant["grant_status"] == "PENDING_REGISTRY",
        "ERR_INVALID_GRANT_STATE",
        "The grant does not admit a registry entry.",
    )

    product = store.product_of_grant(grant)
    category = store.category_of_product(product)
    now = clock_now()
    support_period_end = product["declared_support_period_end"]
    ensure(
        support_period_end >= add_days(now, category["min_support_period_days"]),
        "ERR_SUPPORT_PERIOD_TOO_SHORT",
        "The disclosed support period is shorter than the category minimum.",
    )

    row = base_row()
    row.update(
        {
            "label_grant_id": grant["id"],
            "support_period_end": support_period_end,
            "update_policy_url": update_policy_url,
            "update_cadence": update_cadence,
            "vuln_disclosure_contact": vuln_disclosure_contact,
            "published_at": None,
            "published_by_user_id": None,
        }
    )
    row["disclosure_completeness"] = _disclosure_completeness(row)
    store.registry_entries[row["id"]] = row
    return created(serialize.registry_entry(row))


@bp.get("/labeling/label-grants/<identifier>/registry-entry")
def read_registry_entry(identifier):
    caller(*GRANT_READERS)
    grant = lookups.need_grant(identifier)
    entry = store.registry_entry_of_grant(grant["id"])
    rows = [entry] if entry is not None else []
    return lookups.listing(rows, serialize.registry_entry)


@bp.post("/labeling/label-grants/<identifier>/registry-publication")
def decide_registry_publication(identifier):
    actor = caller(CONFORMITY_REVIEWER)
    body = v.raw_body()

    # Segregation of duties (rung 4) bars the reviewer who scored the claim
    # from publishing it, and applies only to a PUBLISHED decision.
    pending = store.label_grants.get(identifier)
    if pending is not None and body.get("publication_decision") == "PUBLISHED":
        assessment = store.assessments.get(pending["assessment_id"])
        if assessment is not None:
            sod(actor.user_id != assessment["decided_by_user_id"])

    grant = lookups.need_grant(identifier)
    publication_decision = v.field_enum(body, "publication_decision", PUBLICATION_DECISIONS)
    v.field_str(body, "publication_note", required=False, max_len=2000)

    ensure(
        grant["grant_status"] not in TERMINAL_GRANT_STATUSES,
        "ERR_INVALID_GRANT_STATE",
        "A REVOKED or EXPIRED grant admits no publication decision.",
    )
    if publication_decision == "PUBLISHED":
        ensure(
            grant["registry_publication_status"] in ("DRAFT", "WITHHELD"),
            "ERR_INVALID_GRANT_STATE",
            "The registry entry is already published.",
        )
    else:
        ensure(
            grant["registry_publication_status"] in ("DRAFT", "PUBLISHED"),
            "ERR_INVALID_GRANT_STATE",
            "The registry entry is already withheld.",
        )

    product = store.product_of_grant(grant)
    entry = store.registry_entry_of_grant(grant["id"])
    now = clock_now()

    if publication_decision == "WITHHELD":
        # Withholding leaves grant_status and every display untouched.
        cascades.apply_changes(grant, {"registry_publication_status": "WITHHELD"})
        return created(serialize.label_grant(grant))

    ensure(
        entry is not None
        and entry["disclosure_completeness"] == "COMPLETE"
        and product["update_policy_disclosed"],
        "ERR_REGISTRY_DISCLOSURE_INCOMPLETE",
        "The registry disclosure is incomplete.",
    )
    category = store.category_of_product(product)
    ensure(
        entry["support_period_end"] >= add_days(now, category["min_support_period_days"]),
        "ERR_SUPPORT_PERIOD_TOO_SHORT",
        "The snapshotted support period is shorter than the category minimum.",
    )
    ensure(
        product["declared_support_period_end"] > now,
        "ERR_SUPPORT_PERIOD_EXPIRED",
        "The declared support period has already ended.",
    )
    manufacturer = store.manufacturers.get(product["manufacturer_id"])
    ensure(
        manufacturer is not None and manufacturer["standing"] == "GOOD",
        "ERR_SPONSOR_DELINQUENT",
        "The sponsoring manufacturer is not in good standing.",
    )

    first_publication = entry["published_at"] is None
    grant_changes = {"registry_publication_status": "PUBLISHED"}
    if first_publication:
        tier = store.tier_of_product(product)
        valid_from = now
        grant_changes.update(
            {
                "grant_status": "ACTIVE",
                "valid_from": valid_from,
                "valid_until": add_days(valid_from, tier["label_validity_days"]),
            }
        )
    cascades.apply_changes(grant, grant_changes)

    if first_publication:
        cascades.apply_changes(
            entry, {"published_at": now, "published_by_user_id": actor.user_id}
        )
        assessment = store.assessments.get(grant["assessment_id"])
        if (
            grant["renewal_generation"] >= 1
            and assessment is not None
            and assessment["assessed_spec_revision"] == product["spec_revision"]
        ):
            cascades.apply_changes(product, {"conformance_currency": "CURRENT"})

    return created(serialize.label_grant(grant))


@bp.post("/labeling/label-grants/<identifier>/renewals")
def create_renewal(identifier):
    actor = caller(MANUFACTURER)
    grant = _owned_grant(identifier, actor)
    body = v.raw_body()

    lookups.resolve_fk(body, "assessment_id", lookups.need_assessment)
    assessment_id = v.field_str(body, "assessment_id")
    expected_label_grant_version = v.field_int(body, "expected_label_grant_version")
    assessment = lookups.need_assessment(assessment_id)

    ensure(
        grant["grant_status"] in ("ACTIVE", "SUSPENDED"),
        "ERR_INVALID_GRANT_STATE",
        "Only an ACTIVE or SUSPENDED grant may be renewed.",
    )
    ensure(
        expected_label_grant_version == grant["version"],
        "ERR_STALE_GRANT_VERSION",
        "The predecessor grant has been modified since it was last read.",
    )

    product = store.product_of_grant(grant)
    now = clock_now()
    _issuance_gates(product, assessment, now)

    tier = store.tier_of_product(product)
    generation = grant["renewal_generation"] + 1
    row = base_row()
    row.update(
        {
            "product_id": product["id"],
            "assessment_id": assessment["id"],
            "scannable_code": _mint_scannable_code(),
            "grant_status": "PENDING_REGISTRY",
            "registry_publication_status": "DRAFT",
            "suspension_reason": None,
            "renewal_required": False,
            "valid_from": None,
            "valid_until": None,
            "renewal_generation": generation,
            "issuance_fee_cents": calc.label_issuance_fee(tier, generation),
            "superseded_by_grant_id": None,
        }
    )
    store.label_grants[row["id"]] = row

    # The predecessor is retired in the same operation.
    grant["grant_status"] = "REVOKED"
    grant["suspension_reason"] = None
    grant["superseded_by_grant_id"] = row["id"]
    touch(grant)
    touched = cascades.withdraw_grant_displays(grant, "GRANT_SUSPENDED")
    cascades.recount_retailers(touched)

    return created(serialize.label_grant(row))


@bp.get("/labeling/registry/<scannable_code>")
def public_registry_lookup(scannable_code):
    caller(*REGISTRY_READERS)
    grant = store.grant_by_code(scannable_code)
    if grant is None or grant["registry_publication_status"] != "PUBLISHED":
        raise ApiError(
            "ERR_REGISTRY_CODE_NOT_FOUND", "No published label carries that code."
        )
    entry = store.registry_entry_of_grant(grant["id"])
    if entry is None:
        raise ApiError(
            "ERR_REGISTRY_CODE_NOT_FOUND", "No published label carries that code."
        )

    product = store.product_of_grant(grant)
    manufacturer = store.manufacturers.get(product["manufacturer_id"])
    category = store.category_of_product(product)
    tier = store.tier_of_product(product)
    assessment = store.assessments.get(grant["assessment_id"])

    return ok(
        {
            "scannable_code": grant["scannable_code"],
            "model_name": product["model_name"],
            "manufacturer_legal_name": manufacturer["legal_name"] if manufacturer else None,
            "device_category_code": category["category_code"] if category else None,
            "program_tier_code": tier["tier_code"] if tier else None,
            "grade": assessment["grade"] if assessment else None,
            "decided_overall_score": serialize.num(
                assessment["decided_overall_score"] if assessment else None
            ),
            "valid_from": iso(grant["valid_from"]),
            "valid_until": iso(grant["valid_until"]),
            "support_period_end": iso(entry["support_period_end"]),
            "update_policy_url": entry["update_policy_url"],
            "update_cadence": entry["update_cadence"],
            "vuln_disclosure_contact": entry["vuln_disclosure_contact"],
            "grant_status": grant["grant_status"],
        }
    )
