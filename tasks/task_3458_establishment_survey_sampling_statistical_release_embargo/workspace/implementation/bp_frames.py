"""/survey/sample-frames: create (OCC on program, period rules, replacement),
read, freeze with Neyman allocation (PRD 3.1)."""
from flask import Blueprint

from authz import get_auth, require_role
from bp_programs import find_program_by_code
from calc_alloc import neyman_allocate
from envelope import ok
from errors import (
    raise_err, ERR_VALIDATION, ERR_PROGRAM_NOT_FOUND, ERR_FRAME_NOT_FOUND,
    ERR_INVALID_STATE, ERR_STALE_VERSION, ERR_DUPLICATE_FRAME_PERIOD,
    ERR_FRAME_PERIOD_GAP, ERR_SAMPLE_BUDGET_INFEASIBLE,
)
from store import DB, new_entity, now, touch, MIN_STRATUM_SAMPLE
from validate import (
    get_body, req_str, req_int, parse_quarter, quarter_next,
    INDUSTRIES, SIZE_CLASSES,
)

bp = Blueprint("frames", __name__)


def _validate_strata(data):
    strata = data.get("strata")
    if not isinstance(strata, list) or not strata:
        raise_err(ERR_VALIDATION, "strata must be a non-empty array")
    seen = set()
    out = []
    for entry in strata:
        if not isinstance(entry, dict):
            raise_err(ERR_VALIDATION, "each stratum must be an object")
        ind = entry.get("industry_code")
        size = entry.get("size_class")
        if ind not in INDUSTRIES:
            raise_err(ERR_VALIDATION, "stratum industry_code is invalid")
        if size not in SIZE_CLASSES:
            raise_err(ERR_VALIDATION, "stratum size_class is invalid")
        fuc = entry.get("frame_unit_count")
        if not isinstance(fuc, int) or isinstance(fuc, bool) or fuc < 1:
            raise_err(ERR_VALIDATION, "stratum frame_unit_count must be >= 1")
        if (ind, size) in seen:
            raise_err(ERR_VALIDATION,
                      "at most one stratum per (industry_code, size_class) pair")
        seen.add((ind, size))
        out.append({
            "industry_code": ind,
            "size_class": size,
            "frame_unit_count": fuc,
            "allocated_sample_size": None,
        })
    return out


@bp.post("/sample-frames")
def create_frame():
    _user, role = get_auth()
    require_role(role, {"ProgramAdmin"})
    data = get_body()

    # Stage 4: body-referenced resources resolve.
    program = None
    if data.get("program_code") is not None:
        program = find_program_by_code(data["program_code"])
        if program is None:
            raise_err(ERR_PROGRAM_NOT_FOUND, "program_code does not resolve")
    replaced = None
    if data.get("replaces_frame_id") is not None:
        replaced = DB["frames"].get(data["replaces_frame_id"])
        if replaced is None:
            raise_err(ERR_FRAME_NOT_FOUND, "replaces_frame_id does not resolve")

    # Stage 5: request shape.
    req_str(data, "program_code")
    quarter = parse_quarter(data.get("reference_quarter"))
    strata = _validate_strata(data)
    expected_version = req_int(data, "expected_program_version")

    # Stage 6: generic state (a replaced frame must be DRAFT or FROZEN).
    if replaced is not None and replaced["frame_status"] not in ("DRAFT", "FROZEN"):
        raise_err(ERR_INVALID_STATE, "replaces_frame_id must name a DRAFT or FROZEN frame")

    # Stage 7: optimistic concurrency on the program.
    if expected_version != program["version"]:
        raise_err(ERR_STALE_VERSION, "expected_program_version does not match the program version")

    # Stage 11: frame period rules, duplicate period first, gap second.
    live_frames = [
        f for f in DB["frames"].values()
        if f["program_code"] == program["code"] and f["frame_status"] != "SUPERSEDED"
    ]
    if replaced is None:
        if any(parse_quarter(f["reference_quarter"]) == quarter for f in live_frames):
            raise_err(ERR_DUPLICATE_FRAME_PERIOD,
                      "a non-SUPERSEDED frame already covers this reference_quarter")
        if live_frames:
            latest_q = max(parse_quarter(f["reference_quarter"]) for f in live_frames)
            if quarter != quarter_next(latest_q):
                raise_err(ERR_FRAME_PERIOD_GAP,
                          "reference_quarter must immediately follow the latest frame's quarter")
    else:
        if parse_quarter(replaced["reference_quarter"]) != quarter:
            raise_err(ERR_FRAME_PERIOD_GAP,
                      "replacement frame must cover the same reference_quarter")
        if replaced["program_code"] != program["code"]:
            raise_err(ERR_FRAME_PERIOD_GAP,
                      "replacement frame must belong to the same program")

    frame = new_entity("frames", {
        "program_code": program["code"],
        "reference_quarter": f"{quarter[0]:04d}-Q{quarter[1]}",
        "strata": strata,
        "total_sample_size": None,
        "frame_status": "DRAFT",
        "frozen_at": None,
        "replaced_by_frame_id": None,
    })
    if replaced is not None:
        replaced["frame_status"] = "SUPERSEDED"
        replaced["replaced_by_frame_id"] = frame["id"]
        touch(replaced)
    touch(program)  # frame creation mutates program lineage: version + 1
    return ok(frame, status=201)


@bp.get("/sample-frames/<fid>")
def get_frame(fid):
    get_auth()
    frame = DB["frames"].get(fid)
    if frame is None:
        raise_err(ERR_FRAME_NOT_FOUND, "sample frame not found")
    return ok(frame)


@bp.post("/sample-frames/<fid>/freeze")
def freeze_frame(fid):
    _user, role = get_auth()
    require_role(role, {"ProgramAdmin"})
    frame = DB["frames"].get(fid)
    if frame is None:
        raise_err(ERR_FRAME_NOT_FOUND, "sample frame not found")
    if frame["frame_status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "only a DRAFT frame can be frozen")

    program = find_program_by_code(frame["program_code"])
    if program["sample_budget"] < MIN_STRATUM_SAMPLE * len(frame["strata"]):
        raise_err(ERR_SAMPLE_BUDGET_INFEASIBLE,
                  "sample_budget must be at least twice the number of strata")

    allocs = neyman_allocate(frame["strata"], program["sample_budget"])
    for stratum, alloc in zip(frame["strata"], allocs):
        stratum["allocated_sample_size"] = alloc
    frame["total_sample_size"] = sum(allocs)
    frame["frame_status"] = "FROZEN"
    frame["frozen_at"] = now()
    touch(frame)
    return ok(frame)
