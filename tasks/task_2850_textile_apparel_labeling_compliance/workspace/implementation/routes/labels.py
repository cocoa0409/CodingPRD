"""Label artifacts: authoring, the approval gate, publication, hangtags (PRD 3.5-3.7)."""
from flask import Blueprint, request

import calc
import services
from auth import acting_user, require_roles, scope_brand
from envelope import created, listing, ok
from errors import fail
from serializers import label_json
from store import create_row, db, ordered, touch
from util import normalize, parse_second_instant
from validate import (body, distinct_codes, distinct_members, find_label_spec,
                      find_lab_test, find_market, find_origin_determination,
                      find_style, present, req_array, req_enum, req_int,
                      req_string)

bp = Blueprint("labels", __name__)

PLACEMENTS = ("NECK_CENTER_INSIDE", "SIDE_SEAM_INSIDE", "WAISTBAND_INSIDE", "NOT_PERMANENT")
BLEACH_CODES = ("NO_BLEACH", "NON_CHLORINE_ONLY", "ANY_BLEACH")
DRY_CODES = ("TUMBLE_LOW", "TUMBLE_NORMAL", "LINE_DRY", "FLAT_DRY")
IRON_CODES = ("IRON_LOW", "IRON_MEDIUM", "DO_NOT_IRON")
DRYCLEAN_CODES = ("DO_NOT_DRYCLEAN", "ANY_SOLVENT", "PETROLEUM_ONLY")
IDENTITY_MODES = ("RN", "COMPANY_NAME")
CLAIMS = ("MADE_IN_USA", "ORGANIC_COTTON", "WRINKLE_FREE")
WASH_TEMPS = (20, 30, 40, 60, 95)
MARKET_CODE_RE = r"^[A-Z_]{2,8}$"
READ_ROLES = ("ComplianceAdmin", "BrandAdmin", "LabelingSpecialist", "LabelingApprover",
              "CustomsOfficer", "Auditor")


def owning_brand(style):
    return db.brands.get(style["brand_id"]) if style else None


def recompute_hash(spec):
    style = db.styles.get(spec["style_id"])
    spec["content_hash"] = calc.label_content_hash(spec, owning_brand(style))


def check_market_subset(spec_markets, style):
    """Ladder 22 -- the market half of the label_market_compliance calculation.
    The language half lives inline in the approval gate below."""
    for code in spec_markets:
        if code not in style["target_market_codes"]:
            fail("ERR_MARKET_NOT_TARGETED",
                 "Market %s is not among the style's target markets." % code)


def check_permanent_references(style, determination, care_test):
    """Ladder 16 for a permanent label's two pinned evidence rows."""
    if determination is not None and determination["style_id"] != style["id"]:
        fail("ERR_REFERENCE_NOT_ELIGIBLE",
             "The origin determination belongs to another style.")
    if care_test is not None:
        if (care_test["test_type"] != "CARE_PERFORMANCE"
                or care_test["style_id"] != style["id"]
                or care_test["state"] != "PASSED"):
            fail("ERR_REFERENCE_NOT_ELIGIBLE",
                 "The care test must be a passed care-performance run of the same style.")


def resolve_markets(payload, field):
    value = payload.get(field)
    if isinstance(value, list):
        for entry in value:
            if isinstance(entry, str):
                find_market(entry)


@bp.post("/labeling/label-specs")
def draft_permanent_label():
    require_roles("LabelingSpecialist", "ComplianceAdmin")
    payload = body()
    style = None                                                # ladder 5
    if present(payload, "style_id"):
        style = find_style(payload["style_id"])
    resolve_markets(payload, "market_codes")
    determination = None
    if present(payload, "origin_determination_id"):
        determination = find_origin_determination(payload["origin_determination_id"])
    care_test = None
    if present(payload, "care_test_id"):
        care_test = find_lab_test(payload["care_test_id"])
    req_string(payload, "style_id")                              # ladder 6
    markets = distinct_codes(req_array(payload, "market_codes"), "market_codes",
                             MARKET_CODE_RE)
    languages = distinct_codes(req_array(payload, "languages"), "languages", r"^[a-z]{2}$")
    placement = req_enum(payload, "placement_code", PLACEMENTS)
    durability = req_int(payload, "durability_cycles_rating", minimum=0)
    wash_temp = req_int(payload, "wash_temp_c", allowed=WASH_TEMPS)
    bleach = payload.get("bleach_code") or "NO_BLEACH"
    if present(payload, "bleach_code"):
        bleach = req_enum(payload, "bleach_code", BLEACH_CODES)
    dry = "TUMBLE_LOW"
    if present(payload, "dry_code"):
        dry = req_enum(payload, "dry_code", DRY_CODES)
    iron = "IRON_LOW"
    if present(payload, "iron_code"):
        iron = req_enum(payload, "iron_code", IRON_CODES)
    dryclean = "DO_NOT_DRYCLEAN"
    if present(payload, "dryclean_code"):
        dryclean = req_enum(payload, "dryclean_code", DRYCLEAN_CODES)
    identity_mode = req_enum(payload, "identity_display_mode", IDENTITY_MODES)
    fiber_text = req_string(payload, "fiber_content_text", min_len=1, max_len=200)
    origin_text = req_string(payload, "origin_text", min_len=1, max_len=64)
    req_string(payload, "origin_determination_id")
    req_string(payload, "care_test_id")
    if present(payload, "marketing_claims"):
        distinct_members(req_array(payload, "marketing_claims", non_empty=False),
                         "marketing_claims", CLAIMS)
    check_permanent_references(style, determination, care_test)   # ladder 16
    check_market_subset(markets, style)                           # ladder 22
    if not style["declared_fibers"]:                              # ladder 24
        fail("ERR_FIBER_DECLARATION_EMPTY", "The style carries no fiber declaration.")
    spec = create_row(db.label_specs, {
        "style_id": style["id"],
        "artifact_type": "PERMANENT_LABEL",
        "parent_label_spec_id": None,
        "origin_determination_id": determination["id"],
        "care_test_id": care_test["id"],
        "market_codes": markets,
        "languages": languages,
        "placement_code": placement,
        "durability_cycles_rating": durability,
        "wash_temp_c": wash_temp,
        "bleach_code": bleach,
        "dry_code": dry,
        "iron_code": iron,
        "dryclean_code": dryclean,
        "identity_display_mode": identity_mode,
        "fiber_content_text": fiber_text,
        "origin_text": origin_text,
        # PRD 3.5: marketing_claims stays empty on a permanent label.
        "marketing_claims": [],
        "state": "DRAFT",
        "authored_by_user_id": acting_user(),
        "approved_by_user_id": None,
        "revision_note": None,
        "withdrawn_reason": None,
        "effective_from": None,
        "effective_to": None,
        "content_hash": None,
        "consistency_state": "NOT_APPLICABLE",
    })
    recompute_hash(spec)
    return created(label_json(spec))


@bp.patch("/labeling/label-specs/<lid>")
def edit_label(lid):
    require_roles("LabelingSpecialist", "ComplianceAdmin")
    spec = find_label_spec(lid)                                   # ladder 3
    payload = body()
    resolve_markets(payload, "market_codes")                      # ladder 5
    determination = None
    if present(payload, "origin_determination_id"):
        determination = find_origin_determination(payload["origin_determination_id"])
    care_test = None
    if present(payload, "care_test_id"):
        care_test = find_lab_test(payload["care_test_id"])
    updates = {}                                                  # ladder 6
    if present(payload, "market_codes"):
        updates["market_codes"] = distinct_codes(
            req_array(payload, "market_codes"), "market_codes", MARKET_CODE_RE)
    if present(payload, "languages"):
        updates["languages"] = distinct_codes(
            req_array(payload, "languages"), "languages", r"^[a-z]{2}$")
    if present(payload, "placement_code"):
        updates["placement_code"] = req_enum(payload, "placement_code", PLACEMENTS)
    if present(payload, "durability_cycles_rating"):
        updates["durability_cycles_rating"] = req_int(payload, "durability_cycles_rating",
                                                      minimum=0)
    if present(payload, "wash_temp_c"):
        updates["wash_temp_c"] = req_int(payload, "wash_temp_c", allowed=WASH_TEMPS)
    if present(payload, "bleach_code"):
        updates["bleach_code"] = req_enum(payload, "bleach_code", BLEACH_CODES)
    if present(payload, "dry_code"):
        updates["dry_code"] = req_enum(payload, "dry_code", DRY_CODES)
    if present(payload, "iron_code"):
        updates["iron_code"] = req_enum(payload, "iron_code", IRON_CODES)
    if present(payload, "dryclean_code"):
        updates["dryclean_code"] = req_enum(payload, "dryclean_code", DRYCLEAN_CODES)
    if present(payload, "identity_display_mode"):
        updates["identity_display_mode"] = req_enum(payload, "identity_display_mode",
                                                    IDENTITY_MODES)
    if present(payload, "fiber_content_text"):
        updates["fiber_content_text"] = req_string(payload, "fiber_content_text",
                                                    min_len=1, max_len=200)
    if present(payload, "origin_text"):
        updates["origin_text"] = req_string(payload, "origin_text", min_len=1, max_len=64)
    if present(payload, "marketing_claims"):
        claims = distinct_members(req_array(payload, "marketing_claims", non_empty=False),
                                  "marketing_claims", CLAIMS)
        if spec["artifact_type"] == "HANGTAG":
            updates["marketing_claims"] = claims
    if spec["artifact_type"] == "PERMANENT_LABEL":
        if determination is not None:
            updates["origin_determination_id"] = determination["id"]
        if care_test is not None:
            updates["care_test_id"] = care_test["id"]
    if spec["state"] not in ("DRAFT", "REVISION_REQUESTED"):      # ladder 9
        fail("ERR_LABEL_STATE_INVALID", "Only a draft or returned artifact may be edited.")
    style = db.styles.get(spec["style_id"])
    if spec["artifact_type"] == "PERMANENT_LABEL":                # ladder 16
        resulting_det = db.origin_determinations.get(
            updates.get("origin_determination_id", spec["origin_determination_id"]))
        resulting_care = db.lab_tests.get(
            updates.get("care_test_id", spec["care_test_id"]))
        check_permanent_references(style, resulting_det, resulting_care)
    resulting_markets = updates.get("market_codes", spec["market_codes"])
    check_market_subset(resulting_markets, style)                 # ladder 22
    spec.update(updates)
    spec["state"] = "DRAFT"
    spec["revision_note"] = None
    spec["authored_by_user_id"] = acting_user()
    if spec["artifact_type"] == "HANGTAG":
        spec["consistency_state"] = calc.hangtag_consistency(spec)
    recompute_hash(spec)
    touch(spec)
    return ok(label_json(spec))


@bp.post("/labeling/label-specs/<lid>/submit")
def submit_label(lid):
    require_roles("LabelingSpecialist", "ComplianceAdmin")
    spec = find_label_spec(lid)
    if spec["state"] != "DRAFT":                                  # ladder 9
        fail("ERR_LABEL_STATE_INVALID", "Only a draft artifact may be submitted.")
    if spec["artifact_type"] == "PERMANENT_LABEL" and (
            spec["origin_determination_id"] is None or spec["care_test_id"] is None):
        fail("ERR_LABEL_STATE_INVALID",
             "A permanent label must pin both an origin determination and a care test.")
    spec["state"] = "PENDING_APPROVAL"
    touch(spec)
    return ok(label_json(spec))


@bp.post("/labeling/label-specs/<lid>/request-revision")
def request_revision(lid):
    require_roles("LabelingApprover", "ComplianceAdmin")
    spec = find_label_spec(lid)
    payload = body()
    note = req_string(payload, "revision_note", min_len=1)         # ladder 6
    if spec["state"] != "PENDING_APPROVAL":                        # ladder 9
        fail("ERR_LABEL_STATE_INVALID", "Only a pending artifact may be sent back.")
    spec["state"] = "REVISION_REQUESTED"
    spec["revision_note"] = note
    touch(spec)
    return ok(label_json(spec))


def _check_identity(spec, brand):
    """Approval content step one: identity disclosure availability."""
    for code in spec["market_codes"]:
        regime = find_market(code)
        if not regime["requires_identity_disclosure"]:
            continue
        if spec["identity_display_mode"] == "RN":
            if brand is None or not brand["rn_number"]:
                fail("ERR_IDENTITY_DISCLOSURE_MISSING",
                     "The party has no registered identification number to print.")
        else:
            if brand is None or str(brand["legal_name"]).strip() == "":
                fail("ERR_IDENTITY_DISCLOSURE_MISSING",
                     "The party has no legal name to print.")


def _check_claims(spec, style):
    """Ladder 15: every marketing claim must be supported."""
    parent = db.label_specs.get(spec["parent_label_spec_id"])
    for claim in spec["marketing_claims"]:
        if parent is None or not calc.claim_supported(claim, parent, style):
            fail("ERR_HANGTAG_CLAIM_UNSUPPORTED",
                 "Marketing claim %s is not supported by substantiated evidence." % claim)


def _check_posture(of_record):
    if of_record is None:
        return
    posture = calc.brand_posture(of_record["id"])
    if posture == "SUSPENDED":                                     # ladder 34
        fail("ERR_BRAND_POSTURE_SUSPENDED", "The brand of record is suspended.")
    if posture == "RESTRICTED":                                    # ladder 35
        fail("ERR_BRAND_POSTURE_RESTRICTED", "The brand of record is restricted.")


@bp.post("/labeling/label-specs/<lid>/approve")
def approve_label(lid):
    require_roles("LabelingApprover")
    spec = find_label_spec(lid)                                    # ladder 3
    if spec["state"] != "PENDING_APPROVAL":                        # ladder 9
        fail("ERR_LABEL_STATE_INVALID", "Only a pending artifact may be approved.")
    if acting_user() == spec["authored_by_user_id"]:               # ladder 10
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The approver must differ from the operator that authored the artifact.")
    style = db.styles.get(spec["style_id"])
    brand = owning_brand(style)
    of_record = calc.brand_of_record(brand)
    clock = db.now()
    if spec["artifact_type"] == "PERMANENT_LABEL":
        if style["substantiation_state"] != "FIBER_SUBSTANTIATED":  # ladder 11
            fail("ERR_FIBER_NOT_SUBSTANTIATED", "The style's fiber content is not substantiated.")
        current = calc.current_issued_determination(style["id"])    # ladder 12
        if (style["origin_state"] != "ORIGIN_ISSUED" or current is None
                or current["id"] != spec["origin_determination_id"]):
            fail("ERR_ORIGIN_NOT_ISSUED",
                 "The pinned determination is not the style's current issued row.")
        care = db.lab_tests.get(spec["care_test_id"])               # ladder 13
        if (care is None or care["test_type"] != "CARE_PERFORMANCE"
                or care["style_id"] != style["id"] or care["state"] != "PASSED"
                or care["wash_temp_c"] != spec["wash_temp_c"]):
            fail("ERR_CARE_NOT_SUBSTANTIATED",
                 "The printed wash temperature was never substantiated.")
        _check_identity(spec, brand)                               # ladder 14 (step 1)
        if spec["placement_code"] == "NOT_PERMANENT":              # ladder 14 (step 2)
            fail("ERR_PLACEMENT_NOT_PERMANENT",
                 "A permanent label may not be affixed non-permanently.")
        _check_claims(spec, style)                                 # ladder 15
        determination = db.origin_determinations.get(spec["origin_determination_id"])
        check_permanent_references(style, determination, care)     # ladder 16
        expected_fiber = calc.effective_fiber_content_text(style["declared_fibers"])
        expected_origin = "MADE IN " + str(determination["determined_country"])
        if (normalize(spec["fiber_content_text"]) != normalize(expected_fiber)
                or normalize(spec["origin_text"]) != expected_origin):   # ladder 17
            fail("ERR_LABEL_CONTENT_MISMATCH",
                 "The printed statements do not match the facts at approval time.")
        fiber_test = calc.passed_fiber_test(style["id"])            # ladder 18
        if care["valid_until"] is None or care["valid_until"] < clock:
            fail("ERR_TEST_EVIDENCE_EXPIRED", "The care evidence horizon has passed.")
        if fiber_test is not None and (fiber_test["valid_until"] is None
                                      or fiber_test["valid_until"] < clock):
            fail("ERR_TEST_EVIDENCE_EXPIRED", "The fiber evidence horizon has passed.")
        required = set()                                           # ladder 21
        for code in spec["market_codes"]:
            required |= set(find_market(code)["required_languages"])
        if not required.issubset(set(spec["languages"])):
            fail("ERR_LANGUAGE_REQUIREMENT_UNMET",
                 "The artifact does not print every required language.")
        check_market_subset(spec["market_codes"], style)            # ladder 22
        _check_posture(of_record)                                   # ladder 34 / 35
        if not calc.durability_adequacy(spec, style, care):          # ladder 36
            fail("ERR_DURABILITY_INSUFFICIENT",
                 "The substantiated legibility does not reach the market durability floor.")
    else:
        _check_claims(spec, style)                                  # ladder 15
        if calc.hangtag_consistency(spec) != "CONSISTENT":           # ladder 27
            fail("ERR_HANGTAG_INCONSISTENT",
                 "The hangtag text does not agree with its permanent label.")
        _check_posture(of_record)                                   # ladder 34 / 35
    spec["state"] = "APPROVED"
    spec["approved_by_user_id"] = acting_user()
    touch(spec)
    touch(style)
    return ok(label_json(spec))


@bp.post("/labeling/label-specs/<lid>/publish")
def publish_label(lid):
    require_roles("LabelingApprover", "ComplianceAdmin")
    spec = find_label_spec(lid)                                    # ladder 3
    payload = body()
    effective_from = parse_second_instant(payload.get("effective_from"))   # ladder 6
    effective_to = parse_second_instant(payload.get("effective_to"))
    if spec["state"] != "APPROVED":                                # ladder 9
        fail("ERR_LABEL_STATE_INVALID", "Only an approved artifact may be published.")
    if not (effective_to > effective_from):                        # ladder 20
        fail("ERR_INVALID_EFFECTIVE_WINDOW",
             "effective_to must be strictly after effective_from.")
    for other in db.label_specs.values():                          # ladder 29
        if other["id"] == spec["id"] or other["state"] != "PUBLISHED":
            continue
        if other["style_id"] != spec["style_id"]:
            continue
        if not set(other["market_codes"]) & set(spec["market_codes"]):
            continue
        # Half-open windows: touching windows are allowed, intersections are not.
        if effective_from < other["effective_to"] and other["effective_from"] < effective_to:
            fail("ERR_LABEL_WINDOW_OVERLAP",
                 "Another published artifact already occupies that style and market window.")
    style = db.styles.get(spec["style_id"])
    of_record = calc.brand_of_record(owning_brand(style))
    if of_record is not None and calc.brand_posture(of_record["id"]) == "SUSPENDED":
        fail("ERR_BRAND_POSTURE_SUSPENDED", "The brand of record is suspended.")  # ladder 34
    spec["state"] = "PUBLISHED"
    spec["effective_from"] = effective_from
    spec["effective_to"] = effective_to
    touch(spec)
    touch(style)
    return ok(label_json(spec))


@bp.post("/labeling/label-specs/<lid>/withdraw")
def withdraw_label(lid):
    require_roles("LabelingSpecialist", "LabelingApprover", "ComplianceAdmin")
    spec = find_label_spec(lid)                                    # ladder 3
    payload = body()
    reason = req_string(payload, "withdrawn_reason", min_len=1)     # ladder 6
    if spec["state"] not in ("APPROVED", "PUBLISHED"):             # ladder 9
        fail("ERR_LABEL_STATE_INVALID",
             "Only an approved or published artifact may be withdrawn.")
    spec["state"] = "WITHDRAWN"
    spec["withdrawn_reason"] = reason
    touch(spec)
    services.withdraw_hangtags_of({spec["id"]})
    style = db.styles.get(spec["style_id"])
    if style is not None:
        touch(style)
    return ok(label_json(spec))


@bp.post("/labeling/label-specs/<lid>/hangtags")
def create_hangtag(lid):
    require_roles("LabelingSpecialist", "BrandAdmin", "ComplianceAdmin")
    parent = find_label_spec(lid)                                  # ladder 3
    parent_style = db.styles.get(parent["style_id"])
    scope_brand(parent_style["brand_id"] if parent_style else None)  # ladder 4
    payload = body()
    resolve_markets(payload, "market_codes")                       # ladder 5
    markets = distinct_codes(req_array(payload, "market_codes"), "market_codes",
                             MARKET_CODE_RE)                       # ladder 6
    languages = distinct_codes(req_array(payload, "languages"), "languages", r"^[a-z]{2}$")
    claims = []
    if present(payload, "marketing_claims"):
        claims = distinct_members(req_array(payload, "marketing_claims", non_empty=False),
                                  "marketing_claims", CLAIMS)
    fiber_text = req_string(payload, "fiber_content_text", min_len=1, max_len=200)
    origin_text = req_string(payload, "origin_text", min_len=1, max_len=64)
    expected = req_int(payload, "expected_parent_label_spec_version")
    if expected != parent["version"]:                              # ladder 8
        fail("ERR_STALE_LABEL_VERSION", "The parent label has moved since it was read.")
    candidate = {
        "style_id": parent["style_id"],
        "artifact_type": "HANGTAG",
        "parent_label_spec_id": parent["id"],
        "market_codes": markets,
        "languages": languages,
        "marketing_claims": claims,
        "fiber_content_text": fiber_text,
        "origin_text": origin_text,
    }
    _check_claims(candidate, parent_style)                         # ladder 15
    if parent["artifact_type"] != "PERMANENT_LABEL":               # ladder 16
        fail("ERR_REFERENCE_NOT_ELIGIBLE",
             "A hangtag may only hang off a permanent label.")
    if not calc.hangtag_text_ok(candidate, parent):                # ladder 27
        fail("ERR_HANGTAG_INCONSISTENT",
             "The hangtag text does not agree with its permanent label.")
    spec = create_row(db.label_specs, {
        "style_id": parent["style_id"],
        "artifact_type": "HANGTAG",
        "parent_label_spec_id": parent["id"],
        "origin_determination_id": None,
        "care_test_id": None,
        "market_codes": markets,
        "languages": languages,
        "placement_code": "NOT_PERMANENT",
        "durability_cycles_rating": 0,
        # The care code set and the identity mode are inherited verbatim so that
        # two artifacts printing the same words fingerprint identically.
        "wash_temp_c": parent["wash_temp_c"],
        "bleach_code": parent["bleach_code"],
        "dry_code": parent["dry_code"],
        "iron_code": parent["iron_code"],
        "dryclean_code": parent["dryclean_code"],
        "identity_display_mode": parent["identity_display_mode"],
        "fiber_content_text": fiber_text,
        "origin_text": origin_text,
        "marketing_claims": claims,
        "state": "DRAFT",
        "authored_by_user_id": acting_user(),
        "approved_by_user_id": None,
        "revision_note": None,
        "withdrawn_reason": None,
        "effective_from": None,
        "effective_to": None,
        "content_hash": None,
        "consistency_state": None,
    })
    spec["consistency_state"] = calc.hangtag_consistency(spec)
    recompute_hash(spec)
    touch(parent)
    return created(label_json(spec))


@bp.get("/labeling/label-specs/<lid>")
def read_label(lid):
    require_roles(*READ_ROLES)
    return ok(label_json(find_label_spec(lid)))


@bp.get("/labeling/label-specs")
def list_labels():
    require_roles(*READ_ROLES)
    rows = ordered(list(db.label_specs.values()))
    args = request.args
    for field in ("style_id", "parent_label_spec_id", "origin_determination_id",
                  "care_test_id", "artifact_type", "state", "consistency_state"):
        if args.get(field) is not None:
            rows = [r for r in rows if r[field] == args.get(field)]
    if args.get("market_code") is not None:
        rows = [r for r in rows if args.get("market_code") in r["market_codes"]]
    return listing(rows, label_json)
