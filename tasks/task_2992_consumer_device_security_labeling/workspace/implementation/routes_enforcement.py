"""Misuse enforcement, penalties and appeal (PRD 3.9)."""

from flask import Blueprint

import calc
import cascades
import lookups
import serialize
import store
import validation as v
from auth import (
    MANUFACTURER,
    PROGRAM_ADMINISTRATOR,
    RETAILER,
    TEST_LAB_OPERATOR,
    caller,
    own,
    sod,
)
from envelope import created, ok
from errors import ApiError, bad_request
from store import base_row, touch
from validation import ensure

bp = Blueprint("enforcement", __name__)

VIOLATION_TYPES = ("UNAUTHORIZED_DISPLAY", "EXPIRED_LABEL_DISPLAY", "FALSE_CLAIM")
CHANNELS = ("IN_STORE", "ONLINE")
CASE_STATUSES = (
    "OPENED",
    "NOTICE_ISSUED",
    "LAB_REFERRAL",
    "ADJUDICATED_UPHELD",
    "ADJUDICATED_DISMISSED",
    "VACATED",
)
PENALTY_STATUSES = ("NONE", "ASSESSED", "PAID", "VACATED")
OUTCOMES = ("UPHELD", "DISMISSED")
MAX_LINE_ITEMS = 20
CASE_READERS = (PROGRAM_ADMINISTRATOR, MANUFACTURER, RETAILER, TEST_LAB_OPERATOR)


def _validate_line_items(body):
    """Each element is one penalty line; declared order is load-bearing."""
    elements = v.field_array(body, "violation_line_items", min_len=1, max_len=MAX_LINE_ITEMS)
    lines = []
    seen = set()
    for index, element in enumerate(elements):
        if not isinstance(element, dict):
            raise bad_request(
                "Element %d of 'violation_line_items' must be an object." % index
            )
        reference = v.field_str(element, "retail_listing_ref")
        channel = v.field_enum(element, "channel", CHANNELS)
        unit_count = v.field_int(element, "unit_count", minimum=1)
        if reference in seen:
            raise bad_request(
                "Field 'retail_listing_ref' must be unique within 'violation_line_items'."
            )
        seen.add(reference)
        lines.append(
            {
                "retail_listing_ref": reference,
                "channel": channel,
                "unit_count": unit_count,
            }
        )
    return lines


def _legitimately_issued(code, reported_retailer_id):
    """Rung 33: the reported display was in fact covered by an authorization."""
    if reported_retailer_id is None:
        return False
    grant = store.grant_by_code(code)
    if grant is None or grant["grant_status"] != "ACTIVE":
        return False
    now = store.clock_now()
    for authorization in store.authorizations_of_grant(grant["id"]):
        if authorization["retailer_id"] != reported_retailer_id:
            continue
        if authorization["status"] != "AUTHORIZED":
            continue
        if authorization["display_from"] <= now <= authorization["display_until"]:
            return True
    return False


@bp.post("/labeling/enforcement-cases")
def open_case():
    caller(PROGRAM_ADMINISTRATOR)
    body = v.raw_body()

    lookups.resolve_fk(body, "subject_manufacturer_id", lookups.need_manufacturer)
    lookups.resolve_fk(body, "reported_retailer_id", lookups.need_retailer)

    subject_manufacturer_id = v.field_str(body, "subject_manufacturer_id")
    reported_scannable_code = v.field_str(body, "reported_scannable_code")
    violation_type = v.field_enum(body, "violation_type", VIOLATION_TYPES)
    line_items = _validate_line_items(body)
    reported_retailer_id = v.field_str(body, "reported_retailer_id", required=False)
    reporter_note = v.field_str(body, "reporter_note", required=False)

    lookups.need_manufacturer(subject_manufacturer_id)
    if reported_retailer_id is not None:
        lookups.need_retailer(reported_retailer_id)

    ensure(
        not _legitimately_issued(reported_scannable_code, reported_retailer_id),
        "ERR_LABEL_LEGITIMATELY_ISSUED",
        "The reported display is covered by an authorized display of an active grant.",
    )

    row = base_row()
    row.update(
        {
            "subject_manufacturer_id": subject_manufacturer_id,
            "reported_retailer_id": reported_retailer_id,
            "reported_scannable_code": reported_scannable_code,
            # Evaluated once at creation and then frozen.
            "code_matches_registry": store.grant_by_code(reported_scannable_code) is not None,
            "violation_type": violation_type,
            "violation_line_items": line_items,
            "violation_unit_count": sum(line["unit_count"] for line in line_items),
            "case_status": "OPENED",
            "penalty_status": "NONE",
            "penalty_variant": None,
            "penalty_cents": 0,
            "aggravation_multiplier": None,
            "notice_reference": None,
            "notice_issued_by_user_id": None,
            "adjudicated_by_user_id": None,
            "referred_test_lab_id": None,
            "adjudicated_at": None,
            "vacate_reason": None,
            "payment_reference": None,
            "reporter_note": reporter_note,
        }
    )
    store.enforcement_cases[row["id"]] = row
    return created(serialize.enforcement_case(row))


@bp.get("/labeling/enforcement-cases/<identifier>")
def read_case(identifier):
    caller(*CASE_READERS)
    return ok(serialize.enforcement_case(lookups.need_case(identifier)))


@bp.get("/labeling/enforcement-cases")
def list_cases():
    caller(*CASE_READERS)
    subject_manufacturer_id = v.query_str("subject_manufacturer_id")
    reported_retailer_id = v.query_str("reported_retailer_id")
    referred_test_lab_id = v.query_str("referred_test_lab_id")
    case_status = v.query_enum("case_status", CASE_STATUSES)
    penalty_status = v.query_enum("penalty_status", PENALTY_STATUSES)

    rows = list(store.enforcement_cases.values())
    if subject_manufacturer_id is not None:
        rows = [r for r in rows if r["subject_manufacturer_id"] == subject_manufacturer_id]
    if reported_retailer_id is not None:
        rows = [r for r in rows if r["reported_retailer_id"] == reported_retailer_id]
    if referred_test_lab_id is not None:
        rows = [r for r in rows if r["referred_test_lab_id"] == referred_test_lab_id]
    if case_status is not None:
        rows = [r for r in rows if r["case_status"] == case_status]
    if penalty_status is not None:
        rows = [r for r in rows if r["penalty_status"] == penalty_status]
    rows = store.sort_created_id(rows)
    return lookups.listing(rows, serialize.enforcement_case)


@bp.post("/labeling/enforcement-cases/<identifier>/notice")
def issue_notice(identifier):
    actor = caller(PROGRAM_ADMINISTRATOR)
    case = lookups.need_case(identifier)
    body = v.raw_body()
    notice_reference = v.field_str(body, "notice_reference", max_len=200)

    # The notice is issued exactly once, from OPENED or from LAB_REFERRAL.
    ensure(
        case["case_status"] in ("OPENED", "LAB_REFERRAL")
        and case["notice_issued_by_user_id"] is None,
        "ERR_INVALID_CASE_STATE",
        "The case does not admit the notice leg.",
    )

    case["case_status"] = "NOTICE_ISSUED"
    case["notice_reference"] = notice_reference
    case["notice_issued_by_user_id"] = actor.user_id
    touch(case)
    return created(serialize.enforcement_case(case))


@bp.post("/labeling/enforcement-cases/<identifier>/lab-referral")
def refer_to_lab(identifier):
    caller(PROGRAM_ADMINISTRATOR)
    case = lookups.need_case(identifier)
    body = v.raw_body()

    lookups.resolve_fk(body, "test_lab_id", lookups.need_lab)
    test_lab_id = v.field_str(body, "test_lab_id")
    v.field_str(body, "referral_note", max_len=1000)
    lab = lookups.need_lab(test_lab_id)

    ensure(
        case["case_status"] in ("OPENED", "NOTICE_ISSUED"),
        "ERR_INVALID_CASE_STATE",
        "The case does not admit the lab-referral leg.",
    )
    # Unlike the notice leg, the referral leg demands an accredited laboratory.
    ensure(
        lab["accreditation_status"] == "ACCREDITED",
        "ERR_LAB_NOT_ACCREDITED",
        "The referred laboratory is not ACCREDITED.",
    )

    # notice_issued_by_user_id is deliberately preserved: the legs do not
    # overwrite one another's evidence.
    case["case_status"] = "LAB_REFERRAL"
    case["referred_test_lab_id"] = lab["id"]
    touch(case)
    return created(serialize.enforcement_case(case))


@bp.post("/labeling/enforcement-cases/<identifier>/adjudicate")
def adjudicate_case(identifier):
    actor = caller(PROGRAM_ADMINISTRATOR)

    # Segregation of duties (rung 4) precedes existence (rung 5).
    pending = store.enforcement_cases.get(identifier)
    if pending is not None and pending["notice_issued_by_user_id"] is not None:
        sod(actor.user_id != pending["notice_issued_by_user_id"])
    case = lookups.need_case(identifier)

    body = v.raw_body()
    outcome = v.field_enum(body, "outcome", OUTCOMES)
    v.field_str(body, "adjudication_note", max_len=2000)

    # The legs join here: whichever leg the case sits in, the notice leg must
    # have completed.
    ensure(
        case["case_status"] in ("NOTICE_ISSUED", "LAB_REFERRAL")
        and case["notice_issued_by_user_id"] is not None
        and case["penalty_status"] == "NONE",
        "ERR_INVALID_CASE_STATE",
        "The case is not adjudicable.",
    )

    subject = lookups.need_manufacturer(case["subject_manufacturer_id"])
    case["adjudicated_at"] = store.clock_now()
    case["adjudicated_by_user_id"] = actor.user_id

    if outcome == "DISMISSED":
        # A terminal case_status beside an untouched penalty_status: the two
        # dimensions advance independently.  No ledger recomputation at all.
        case["case_status"] = "ADJUDICATED_DISMISSED"
        touch(case)
        return created(serialize.enforcement_case(case))

    # The multiplier reads upheld_case_count as it stands immediately BEFORE
    # this adjudication increments it.
    multiplier = calc.aggravation_multiplier(subject["upheld_case_count"])
    variant, penalty_cents = calc.enforcement_penalty(case, subject, multiplier)
    case["case_status"] = "ADJUDICATED_UPHELD"
    case["penalty_status"] = "ASSESSED"
    case["aggravation_multiplier"] = multiplier
    case["penalty_variant"] = variant
    case["penalty_cents"] = penalty_cents
    touch(case)

    cascades.recompute_manufacturer_ledger(subject)
    return created(serialize.enforcement_case(case))


@bp.post("/labeling/enforcement-cases/<identifier>/vacate")
def vacate_case(identifier):
    actor = caller(PROGRAM_ADMINISTRATOR)

    pending = store.enforcement_cases.get(identifier)
    if pending is not None and pending["adjudicated_by_user_id"] is not None:
        sod(actor.user_id != pending["adjudicated_by_user_id"])
    case = lookups.need_case(identifier)

    body = v.raw_body()
    vacate_reason = v.field_str(body, "vacate_reason", max_len=2000)

    ensure(
        case["case_status"] == "ADJUDICATED_UPHELD" and case["penalty_status"] == "ASSESSED",
        "ERR_INVALID_CASE_STATE",
        "Only an upheld case carrying an assessed penalty may be vacated.",
    )

    case["case_status"] = "VACATED"
    case["penalty_status"] = "VACATED"
    case["vacate_reason"] = vacate_reason
    touch(case)

    subject = store.manufacturers.get(case["subject_manufacturer_id"])
    if subject is not None:
        cascades.recompute_manufacturer_ledger(subject)
    return created(serialize.enforcement_case(case))


@bp.post("/labeling/enforcement-cases/<identifier>/penalty-payments")
def pay_penalty(identifier):
    actor = caller(MANUFACTURER)

    pending = store.enforcement_cases.get(identifier)
    if pending is not None:
        own(pending["subject_manufacturer_id"] == actor.user_id)
    case = lookups.need_case(identifier)

    body = v.raw_body()
    payment_reference = v.field_str(body, "payment_reference", max_len=200)

    ensure(
        case["penalty_status"] == "ASSESSED",
        "ERR_PENALTY_NOT_ASSESSED",
        "The case carries no assessed penalty to settle.",
    )

    case["penalty_status"] = "PAID"
    case["payment_reference"] = payment_reference
    touch(case)

    subject = store.manufacturers.get(case["subject_manufacturer_id"])
    if subject is not None:
        # Paying never reduces upheld_case_count, so a BARRED subject stays barred.
        cascades.recompute_manufacturer_ledger(subject)
    return created(serialize.enforcement_case(case))
