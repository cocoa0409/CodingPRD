"""The logical clock and the four immutable reference registers (PRD 3.1)."""
from flask import Blueprint

import calc
import serializers
import store
from authz import ALL_ROLES, authorize
from common import fmt_dt
from envelope import ok, created, paginated
from errors import ApiError
from shape import body, req_bool, req_dt, req_enum, req_int, req_num, req_str

bp = Blueprint("config", __name__)


def find_config(table, row_id):
    row = table.get(row_id)
    if row is None:
        raise ApiError("ERR_CONFIG_NOT_FOUND")
    return row


# ---------------------------------------------------------------------------
# Logical plant clock
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    authorize(("PlantAdmin",))
    payload = body()
    instant = req_dt(payload, "to_iso8601")
    store.clock_set(instant)
    return ok({"current_utc": fmt_dt(store.clock_now())})


# ---------------------------------------------------------------------------
# Jurisdictions
# ---------------------------------------------------------------------------
@bp.post("/jurisdictions")
def create_jurisdiction():
    authorize(("PlantAdmin",))
    payload = body()
    row = {
        "code": req_str(payload, "code", min_len=3, max_len=16),
        "name": req_str(payload, "name"),
        "seal_required": req_bool(payload, "seal_required"),
        "min_design_wind_speed_mph": req_int(
            payload, "min_design_wind_speed_mph", minimum=80, maximum=200
        ),
        "seismic_design_category": req_enum(
            payload, "seismic_design_category", ("A", "B", "C", "D")
        ),
        "permit_review_days": req_int(payload, "permit_review_days", minimum=0, maximum=90),
    }
    store.insert(store.jurisdictions, row, versioned=False)
    return created(serializers.jurisdiction(row))


@bp.get("/jurisdictions")
def list_jurisdictions():
    authorize(ALL_ROLES)
    return paginated(store.ordered(store.jurisdictions), serializers.jurisdiction)


@bp.get("/jurisdictions/<row_id>")
def read_jurisdiction(row_id):
    authorize(ALL_ROLES)
    return ok(serializers.jurisdiction(find_config(store.jurisdictions, row_id)))


# ---------------------------------------------------------------------------
# Grain profiles
# ---------------------------------------------------------------------------
@bp.post("/grain-profiles")
def create_grain_profile():
    authorize(("PlantAdmin",))
    payload = body()
    row = {
        "grain_code": req_str(payload, "grain_code"),
        "bulk_density_kg_per_m3": req_num(
            payload, "bulk_density_kg_per_m3", minimum=300, maximum=1400
        ),
        "janssen_k_ratio": req_num(payload, "janssen_k_ratio", minimum="0.20", maximum="0.70"),
        "max_safe_moisture_pct": req_num(
            payload, "max_safe_moisture_pct", minimum="8.0", maximum="20.0"
        ),
        "aeration_cfm_per_m3_base": req_num(
            payload, "aeration_cfm_per_m3_base", minimum="0.5", maximum="6.0"
        ),
        "drying_multiplier": req_num(payload, "drying_multiplier", minimum="1.0", maximum="8.0"),
    }
    store.insert(store.grain_profiles, row, versioned=False)
    return created(serializers.grain_profile(row))


@bp.get("/grain-profiles")
def list_grain_profiles():
    authorize(ALL_ROLES)
    return paginated(store.ordered(store.grain_profiles), serializers.grain_profile)


@bp.get("/grain-profiles/<row_id>")
def read_grain_profile(row_id):
    authorize(ALL_ROLES)
    return ok(serializers.grain_profile(find_config(store.grain_profiles, row_id)))


# ---------------------------------------------------------------------------
# Coating specifications
# ---------------------------------------------------------------------------
@bp.post("/coating-specs")
def create_coating_spec():
    authorize(("PlantAdmin",))
    payload = body()
    # An integer field: the four-band class comparison is on integers.
    zinc = req_int(payload, "zinc_mass_g_per_m2", minimum=150, maximum=900)
    row = {
        "coating_code": req_str(payload, "coating_code"),
        "zinc_mass_g_per_m2": zinc,
        "corrosion_class": calc.corrosion_class(zinc),
        "coating_cost_per_kg_cents": req_int(
            payload, "coating_cost_per_kg_cents", minimum=0, maximum=500
        ),
        "changeover_minutes": req_int(payload, "changeover_minutes", minimum=0, maximum=480),
        "max_ambient_moisture_pct": req_num(
            payload, "max_ambient_moisture_pct", minimum="8.0", maximum="24.0"
        ),
    }
    store.insert(store.coating_specs, row, versioned=False)
    return created(serializers.coating_spec(row))


@bp.get("/coating-specs")
def list_coating_specs():
    authorize(ALL_ROLES)
    return paginated(store.ordered(store.coating_specs), serializers.coating_spec)


@bp.get("/coating-specs/<row_id>")
def read_coating_spec(row_id):
    authorize(ALL_ROLES)
    return ok(serializers.coating_spec(find_config(store.coating_specs, row_id)))


# ---------------------------------------------------------------------------
# Roll-forming lines
# ---------------------------------------------------------------------------
@bp.post("/roll-forming-lines")
def create_roll_forming_line():
    authorize(("PlantAdmin",))
    payload = body()
    row = {
        "line_code": req_str(payload, "line_code"),
        "max_gauge_mm": req_num(payload, "max_gauge_mm", minimum="0.8", maximum="6.0"),
    }
    store.insert(store.roll_forming_lines, row, versioned=False)
    return created(serializers.roll_forming_line(row))


@bp.get("/roll-forming-lines")
def list_roll_forming_lines():
    authorize(ALL_ROLES)
    return paginated(store.ordered(store.roll_forming_lines), serializers.roll_forming_line)


@bp.get("/roll-forming-lines/<row_id>")
def read_roll_forming_line(row_id):
    authorize(ALL_ROLES)
    return ok(serializers.roll_forming_line(find_config(store.roll_forming_lines, row_id)))
