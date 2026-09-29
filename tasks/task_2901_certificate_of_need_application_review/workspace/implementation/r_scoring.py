"""Score sheets and the comparative score recomputation (PRD §3.7)."""

from flask import Blueprint

import auth
import envelope
import services
import shape
import store
from errors import ApiError

bp = Blueprint("scoring", __name__)

SHEET_READ_ROLES = ["ProgramAdmin", "IntakeAnalyst", "ReviewAnalyst", "DecisionOfficer",
                    "AppealBoardMember"]
CRITERION_FIELDS = ("need_conformity_score", "financial_feasibility_score",
                    "cost_containment_score", "access_underserved_score",
                    "quality_record_score")


@bp.post("/score-sheets")
def submit_score_sheet():
    user_id, _role = auth.identity(["ReviewAnalyst"])
    body = shape.body()
    application_id = shape.string_field(body, "application_id")
    scores = {}
    for field in CRITERION_FIELDS:
        scores[field] = shape.int_field(body, field, minimum=0, maximum=100)
    narrative = shape.string_field(body, "narrative", required=False, default=None)
    expected_version = shape.int_field(body, "expected_application_version", minimum=0)

    app = services.application(application_id)

    for review in services.reviews_of_application(app["id"]):
        if review["issued_by_user_id"] == user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "An analyst who issued a deficiency notice may not score this "
                           "application.")

    if expected_version != app["version"]:
        raise ApiError("ERR_STALE_APPLICATION_VERSION",
                       "expected_application_version does not match the application's version.")

    for sheet in services.sheets_of_application(app["id"], "ACTIVE"):
        if sheet["reviewer_user_id"] == user_id:
            sheet["status"] = "SUPERSEDED"
            store.touch(sheet)

    fields = {"application_id": app["id"], "reviewer_user_id": user_id}
    fields.update(scores)
    fields["narrative"] = narrative
    fields["status"] = "ACTIVE"
    record = store.create("score_sheets", fields)

    services.recompute_application_score(app)
    store.touch(app)
    return envelope.ok(record, 201)


@bp.get("/applications/<record_id>/score-sheets")
def list_score_sheets(record_id):
    auth.identity(SHEET_READ_ROLES)
    app = services.application(record_id)
    limit, offset = shape.pagination()
    rows = store.sort_created(services.sheets_of_application(app["id"]))
    return envelope.ok_list(rows[offset:offset + limit], limit, offset, len(rows))
