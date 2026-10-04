"""School registry: POST /giving/schools, GET /giving/schools/{id}."""
import store
from envelope import ok
from errors import bad_request, not_found
from security import actor, require_roles
from serializers import school_json
from services import pricing
from validators import as_num, as_str, json_body, require_present


def register(app):
    @app.route("/giving/schools", methods=["POST"])
    def create_school():
        data = json_body()
        name = as_str(require_present(data, "name"), "name")
        state_code = as_str(require_present(data, "state_code"), "state_code")
        district = as_str(require_present(data, "district"), "district")
        poverty_pct = as_num(require_present(data, "poverty_pct"), "poverty_pct")
        ell_pct = as_num(require_present(data, "ell_pct"), "ell_pct")
        if not (0.0 <= poverty_pct <= 100.0) or not (0.0 <= ell_pct <= 100.0):
            raise bad_request("poverty_pct and ell_pct must lie between 0.0 and 100.0 inclusive")
        _, role = actor()
        require_roles(role, ("PlatformAdmin",))
        rec = store.base_record()
        rec.update({
            "name": name,
            "state_code": state_code,
            "district": district,
            "poverty_pct": float(poverty_pct),
            "ell_pct": float(ell_pct),
            "equity_score_banded": pricing.equity_banded(poverty_pct),
            "equity_score_weighted": pricing.equity_weighted(poverty_pct, ell_pct),
        })
        store.schools[rec["id"]] = rec
        return ok(school_json(rec), 201)

    @app.route("/giving/schools/<school_id>", methods=["GET"])
    def get_school(school_id):
        _, role = actor()
        require_roles(role, ("PlatformAdmin", "Reviewer", "Teacher"))
        school = store.schools.get(school_id)
        if school is None:
            raise not_found("School not found")
        return ok(school_json(school), 200)
