"""Test-driving logical clock endpoint (PRD 2.11)."""
from core import clock, validate
from core.auth import require_role
from core.blueprint import bp
from core.envelope import success
from core.errors import ApiError


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_role(["PlatformAdmin"])
    values = validate.shape([validate.f("to_iso8601", validate.DATETIME, required=True)])
    clock.set_now(values["to_iso8601"])
    return success({"current_utc": clock.now_iso()})
