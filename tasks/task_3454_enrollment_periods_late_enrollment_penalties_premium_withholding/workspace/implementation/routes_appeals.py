"""AppealCase: file (UNDER_REVIEW), list, adjudicate (SoD + cycle), respond."""
from __future__ import annotations

from authn import (ROLE_APPEALS_OFFICER, ROLE_BENEFICIARY, ROLE_FIELD_OFFICER,
                   authenticate, authorize, check_ownership)
from db import find, get, make_entity, public, sort_entities, touch
from domain import (rate_schedule_for_year, reprice_invoices,
                    tax_record_for)
from calcs import bracket_for_tier, calc_irmaa_tier
from envelope import success_list, success_object
from errors import fail
from validate import (body_json, pagination_args, paginate, req_date_str,
                      req_enum, req_int, req_str)

LIFE_EVENT_TYPES = ("WORK_STOPPAGE", "WORK_REDUCTION", "MARRIAGE", "DIVORCE",
                    "SPOUSE_DEATH", "PENSION_LOSS", "PROPERTY_LOSS")
APPEAL_READ_ROLES = [ROLE_BENEFICIARY, ROLE_FIELD_OFFICER,
                     ROLE_APPEALS_OFFICER]


def _load_appeal(appeal_id, role, uid, ownership):
    appeal = get("appeals", appeal_id)
    if not appeal:
        fail("ERR_APPEAL_NOT_FOUND", "No appeal with that id")
    if ownership:
        check_ownership(role, uid, appeal["beneficiary_id"])
    return appeal


def file_appeal():
    role, uid = authenticate()
    authorize(role, [ROLE_BENEFICIARY])
    body = body_json()
    det_id = req_str(body, "premium_determination_id")
    life_event = req_enum(body, "life_event_type", LIFE_EVENT_TYPES)
    event_date = req_date_str(body, "event_date")
    claimed_magi = req_int(body, "claimed_magi_cents", minimum=0)
    det = get("determinations", det_id)
    if not det:
        fail("ERR_DETERMINATION_NOT_FOUND",
             "No premium determination with that id")
    check_ownership(role, uid, det["beneficiary_id"])
    if det["status"] != "FINAL":
        fail("ERR_INVALID_STATE",
             "Only a FINAL determination may be appealed")
    appeal = make_entity("appeals", {
        "beneficiary_id": det["beneficiary_id"],
        "premium_determination_id": det["id"],
        "life_event_type": life_event,
        "event_date": event_date,
        "claimed_magi_cents": claimed_magi,
        "status": "UNDER_REVIEW",
        "adjudicated_by_user_id": None,
    })
    return success_object(public(appeal), 201)


def adjudicate_appeal(appeal_id):
    role, uid = authenticate()
    authorize(role, [ROLE_APPEALS_OFFICER])
    body = body_json()
    decision = req_enum(body, "decision",
                        ("APPROVED", "DENIED", "MORE_INFO_REQUESTED"))
    appeal = _load_appeal(appeal_id, role, uid, ownership=False)
    det = get("determinations", appeal["premium_determination_id"])
    # Segregation of duties runs BEFORE the appeal state check
    if det and uid == det["created_by_user_id"]:
        fail("ERR_SOD_SAME_ACTOR",
             "The determination's author may not adjudicate its appeal")
    if appeal["status"] != "UNDER_REVIEW":
        fail("ERR_APPEAL_NOT_REVIEWABLE",
             "Adjudication requires an UNDER_REVIEW appeal")
    if decision == "MORE_INFO_REQUESTED":
        appeal["status"] = "MORE_INFO_REQUESTED"
        touch(appeal)
        return success_object(public(appeal))
    appeal["adjudicated_by_user_id"] = uid
    if decision == "DENIED":
        appeal["status"] = "DENIED"
        touch(appeal)
        return success_object(public(appeal))
    # APPROVED: calc_appeal_redetermination
    old = det
    old["status"] = "SUPERSEDED"
    touch(old)
    schedule = rate_schedule_for_year(old["coverage_year"])
    tier = calc_irmaa_tier(schedule["irmaa_brackets"],
                           _basis_filing_status(old),
                           appeal["claimed_magi_cents"])
    bracket = bracket_for_tier(schedule["irmaa_brackets"], tier)
    surcharge = (bracket["part_b_surcharge_cents"] if old["part"] == "PART_B"
                 else bracket["part_d_surcharge_cents"])
    new_det = make_entity("determinations", {
        "beneficiary_id": old["beneficiary_id"],
        "coverage_year": old["coverage_year"],
        "part": old["part"],
        "status": "FINAL",
        "tax_year_used": old["tax_year_used"],
        "irmaa_tier": tier,
        "base_premium_cents": old["base_premium_cents"],
        "irmaa_surcharge_cents": surcharge,
        "lep_cents": old["lep_cents"],
        "total_premium_cents": (old["base_premium_cents"] + surcharge
                                + old["lep_cents"]),
        "created_by_user_id": uid,
    })
    # Invoice repricing: same rules as equitable relief, scoped to the
    # appealed determination's (part, coverage_year).
    year = old["coverage_year"]

    def affected(service_ym):
        return service_ym[0] == year

    def amount_for(service_ym):
        return new_det["total_premium_cents"]

    reprice_invoices(old["beneficiary_id"], old["part"], affected, amount_for)
    appeal["status"] = "APPROVED"
    touch(appeal)
    return success_object(public(appeal))


def _basis_filing_status(det):
    rec = tax_record_for(det["beneficiary_id"], det["tax_year_used"])
    return rec["filing_status"] if rec else "SINGLE"


def respond_appeal(appeal_id):
    role, uid = authenticate()
    authorize(role, [ROLE_BENEFICIARY])
    body = body_json()
    req_str(body, "note")
    appeal = _load_appeal(appeal_id, role, uid, ownership=True)
    if appeal["status"] != "MORE_INFO_REQUESTED":
        fail("ERR_APPEAL_NOT_REVIEWABLE",
             "A response requires a MORE_INFO_REQUESTED appeal")
    appeal["status"] = "UNDER_REVIEW"
    touch(appeal)
    return success_object(public(appeal))


def list_appeals(beneficiary_id):
    role, uid = authenticate()
    authorize(role, APPEAL_READ_ROLES)
    check_ownership(role, uid, beneficiary_id)
    if not get("beneficiaries", beneficiary_id):
        fail("ERR_BENEFICIARY_NOT_FOUND", "No beneficiary with that id")
    limit, offset = pagination_args()
    rows = sort_entities(find("appeals",
                              lambda e: e["beneficiary_id"] == beneficiary_id))
    page, total = paginate(rows, limit, offset)
    return success_list([public(e) for e in page], limit, offset, total)


def register(app):
    app.add_url_rule("/medicare/appeals", "file_appeal", file_appeal,
                     methods=["POST"])
    app.add_url_rule("/medicare/beneficiaries/<beneficiary_id>/appeals",
                     "list_appeals", list_appeals, methods=["GET"])
    app.add_url_rule("/medicare/appeals/<appeal_id>/adjudicate",
                     "adjudicate_appeal", adjudicate_appeal, methods=["POST"])
    app.add_url_rule("/medicare/appeals/<appeal_id>/respond",
                     "respond_appeal", respond_appeal, methods=["POST"])
