"""/survey/cell-estimates: list and read (PRD 3.5)."""
from flask import Blueprint, request

from authz import get_auth
from envelope import ok, ok_list, paginate
from errors import raise_err, ERR_ESTIMATE_NOT_FOUND
from store import DB, sorted_entities

bp = Blueprint("estimates", __name__)


@bp.get("/cell-estimates")
def list_estimates():
    get_auth()
    items = sorted_entities("cells")
    for param in ("cycle_id", "industry_code", "size_class",
                  "estimate_status", "suppression_status"):
        value = request.args.get(param)
        if value is not None:
            items = [c for c in items if c[param] == value]
    page, pagination = paginate(items)
    return ok_list(page, pagination)


@bp.get("/cell-estimates/<cid>")
def get_estimate(cid):
    get_auth()
    cell = DB["cells"].get(cid)
    if cell is None:
        raise_err(ERR_ESTIMATE_NOT_FOUND, "cell estimate not found")
    return ok(cell)
