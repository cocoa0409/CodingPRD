"""Source masters and the quality-control desk (PRD 3.1, 3.2)."""

from flask import Blueprint

from db import db, new_row, now, q2, rows, sort_rows, touch
from errors import ApiError
from middleware import endpoint
from response import created, ok, read_page_params
from routes.common import get_asset, get_title, send_list
from services import calc
from services.domain import recompute_readiness
from validation import S, parse_body, parse_query

bp = Blueprint("assets", __name__)

FRAME_RATES = ("23.976", "24.0", "25.0", "29.97", "50.0", "59.94")

LANGUAGE_PATTERN = r"^[a-z]{2}$"

ASSET_CREATE = [
    S("title_id", "string"),
    S("source_uri", "string", min_len=1, max_len=300),
    S("duration_seconds", "integer", minimum=1),
    S("frame_rate", "number", one_of=FRAME_RATES),
    S("peak_audio_lufs", "number", minimum="-60.0", maximum="0.0"),
    S("artifact_defect_count", "integer", minimum=0),
    S("caption_languages", "array", required=False, default=None, unique=True,
      item=S("caption_languages[]", "string", pattern=LANGUAGE_PATTERN)),
    S("audio_language", "string", pattern=LANGUAGE_PATTERN),
]

RESUBMIT = [
    S("source_uri", "string", required=False, min_len=1, max_len=300),
    S("peak_audio_lufs", "number", required=False, minimum="-60.0", maximum="0.0"),
    S("artifact_defect_count", "integer", required=False, minimum=0),
    S("caption_languages", "array", required=False, unique=True,
      item=S("caption_languages[]", "string", pattern=LANGUAGE_PATTERN)),
]


@bp.post("/mezzanine-assets")
@endpoint(["ContentOps"])
def register_asset():
    payload = parse_body(ASSET_CREATE)
    title = get_title(payload["title_id"])
    asset = new_row()
    asset["title_id"] = title["id"]
    asset["source_uri"] = payload["source_uri"]
    asset["duration_seconds"] = payload["duration_seconds"]
    asset["frame_rate"] = payload["frame_rate"]
    asset["peak_audio_lufs"] = payload["peak_audio_lufs"]
    asset["artifact_defect_count"] = payload["artifact_defect_count"]
    asset["caption_languages"] = payload.get("caption_languages") or []
    asset["audio_language"] = payload["audio_language"]
    asset["qc_state"] = "INGESTED"
    asset["qc_attempt_count"] = 0
    asset["latest_severity_index"] = q2(0)
    asset["blocking_defect_code"] = "NONE"
    asset["last_qc_report_id"] = None
    db.assets[asset["id"]] = asset
    recompute_readiness(title)
    return created(asset)


@bp.get("/mezzanine-assets/<asset_id>")
@endpoint(["ContentOps", "QcAnalyst", "EncodingEngineer", "PlatformAdmin"])
def read_asset(asset_id):
    parse_query([], allow_paging=False)
    return ok(get_asset(asset_id))


@bp.post("/mezzanine-assets/<asset_id>/qc-runs")
@endpoint(["QcAnalyst"])
def run_qc(asset_id):
    parse_body([])
    asset = get_asset(asset_id)
    if asset["qc_state"] != "INGESTED" or asset["qc_attempt_count"] >= 3:
        raise ApiError("ERR_ASSET_STATE_INVALID")
    figures = calc.qc_figures(asset)
    prior_attempts = asset["qc_attempt_count"]
    report = new_row(versioned=False)
    report["asset_id"] = asset["id"]
    report["attempt_number"] = prior_attempts + 1
    report["verdict"] = figures["verdict"]
    report["severity_index"] = figures["severity_index"]
    report["artifact_penalty"] = figures["artifact_penalty"]
    report["loudness_deviation_db"] = figures["loudness_deviation_db"]
    report["caption_coverage_pct"] = figures["caption_coverage_pct"]
    report["blocking_defect_code"] = figures["blocking_defect_code"]
    report["evaluated_at"] = now()
    db.qc_reports[report["id"]] = report

    asset["qc_attempt_count"] = prior_attempts + 1
    asset["latest_severity_index"] = figures["severity_index"]
    asset["last_qc_report_id"] = report["id"]
    if figures["verdict"] in ("PASS", "WARN"):
        asset["qc_state"] = "QC_PASSED"
        asset["blocking_defect_code"] = "NONE"
    else:
        asset["blocking_defect_code"] = figures["blocking_defect_code"]
        asset["qc_state"] = "QC_REJECTED" if prior_attempts == 2 else "QC_FAILED"
    touch(asset)
    recompute_readiness(db.titles[asset["title_id"]])
    return created(report)


@bp.post("/mezzanine-assets/<asset_id>/remediation-request")
@endpoint(["QcAnalyst"])
def request_remediation(asset_id):
    parse_body([])
    asset = get_asset(asset_id)
    if asset["qc_state"] != "QC_FAILED":
        raise ApiError("ERR_ASSET_STATE_INVALID")
    asset["qc_state"] = "REMEDIATION_REQUESTED"
    touch(asset)
    return ok(asset)


@bp.post("/mezzanine-assets/<asset_id>/resubmit")
@endpoint(["ContentOps"])
def resubmit_asset(asset_id):
    payload = parse_body(RESUBMIT)
    asset = get_asset(asset_id)
    if asset["qc_state"] != "REMEDIATION_REQUESTED" or asset["qc_attempt_count"] >= 3:
        raise ApiError("ERR_ASSET_STATE_INVALID")
    if "source_uri" in payload:
        asset["source_uri"] = payload["source_uri"]
    if "peak_audio_lufs" in payload:
        asset["peak_audio_lufs"] = payload["peak_audio_lufs"]
    if "artifact_defect_count" in payload:
        asset["artifact_defect_count"] = payload["artifact_defect_count"]
    if "caption_languages" in payload:
        asset["caption_languages"] = payload["caption_languages"]
    asset["qc_state"] = "INGESTED"
    asset["blocking_defect_code"] = "NONE"
    asset["latest_severity_index"] = q2(0)
    # qc_attempt_count is deliberately not reset.
    touch(asset)
    recompute_readiness(db.titles[asset["title_id"]])
    return ok(asset)


@bp.get("/mezzanine-assets/<asset_id>/qc-reports")
@endpoint(["ContentOps", "QcAnalyst", "PlatformAdmin"])
def list_qc_reports(asset_id):
    parse_query([])
    page, page_size = read_page_params()
    asset = get_asset(asset_id)
    items = [r for r in rows(db.qc_reports) if r["asset_id"] == asset["id"]]
    ordered = sort_rows(items, [(lambda r: r["attempt_number"], False)])
    return send_list(ordered, page, page_size)
