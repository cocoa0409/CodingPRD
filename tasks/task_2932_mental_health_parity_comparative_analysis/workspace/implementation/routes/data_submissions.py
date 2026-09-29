"""Reads over produced as-applied data submissions (PRD 3.6)."""

from flask import Blueprint

import serialize
from auth import guard
from enums import ALL_ROLES
from envelope import success
from helpers import list_response
from store import db, lookup_path

bp = Blueprint("data_submissions", __name__)


@bp.route("/data-submissions/<submission_id>", methods=["GET"])
@guard(*ALL_ROLES)
def read_data_submission(submission_id):
    row = lookup_path(db.data_submissions, submission_id, "ERR_DATA_SUBMISSION_NOT_FOUND")
    return success(serialize.data_submission(row))


@bp.route("/data-submissions", methods=["GET"])
@guard(*ALL_ROLES)
def list_data_submissions():
    return list_response(db.data_submissions.values(), serialize.data_submission,
                         ("vendor_request_id", "classification_id", "submission_type",
                          "status"))
