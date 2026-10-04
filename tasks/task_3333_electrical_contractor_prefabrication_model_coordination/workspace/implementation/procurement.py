"""MaterialRelease: procurement creation, declaration and receipt."""

from core import CLOCK, DB, fail, new_record, num, rhu, to_dt, touch, whole_days_between
from calculations import material_release_timing, update_project_pipeline


def require_release(release_id):
    if not release_id:
        fail("ERR_REFERENCED_ENTITY_NOT_FOUND")
    release = DB.find("material_releases", release_id)
    if release is None:
        fail("ERR_REFERENCED_ENTITY_NOT_FOUND")
    return release


def create_material_release(body):
    project = DB.find("projects", body.get("project_id"))
    if project is None:
        fail("ERR_PROJECT_NOT_FOUND")
    model_version = DB.find("model_versions", body.get("model_version_id"))
    if model_version is None:
        fail("ERR_MODEL_VERSION_NOT_FOUND")
    # receiving_user_id holds an opaque operator identity (PRD §2.1): it names
    # the operator who will acknowledge receipt and is never resolved against a
    # persisted entity, so it carries no existence check.
    receiving_user_id = body.get("receiving_user_id")

    release = new_record(
        project_id=project["id"],
        model_version_id=model_version["id"],
        vendor_key=body.get("vendor_key"),
        material_commodity=body.get("material_commodity"),
        quantity=num(body.get("quantity"), 0.0),
        unit_price_cents=num(body.get("unit_price_cents"), 0.0),
        lead_time_days=num(body.get("lead_time_days"), 0.0),
        service_priority=body.get("service_priority"),
        commitment_mode=body.get("commitment_mode"),
        planned_release_iso=body.get("planned_release_iso"),
        receiving_user_id=receiving_user_id,
        status="PLANNED",
        locked_release_iso=None,
        priced_hours=0.0,
        list_value_cents=0,
        ship_cost_cents=0,
        value_cents=0,
        declared_for_procurement=False,
        restriction_since_iso=None,
    )
    DB.put("material_releases", release)
    material_release_timing(release, project)
    refresh_release_values(release)
    from orders import recompute_all_releasable
    from projects import fabrication_locked
    recompute_all_releasable(project)
    fabrication_locked(project)
    return release


def refresh_release_values(release):
    quantity = num(release.get("quantity"), 0.0)
    unit_price = num(release.get("unit_price_cents"), 0.0)
    release["list_value_cents"] = rhu(unit_price * quantity, 0)
    release["ship_cost_cents"] = 0
    release["value_cents"] = int(release["list_value_cents"] + release["ship_cost_cents"])
    release["declared_for_procurement"] = release.get("status") in ("RELEASED", "SHIPPED", "RECEIVED")
    return release


DECLARE_STEPS = {"PLANNED": "RELEASED", "RELEASED": "SHIPPED", "SHIPPED": "RECEIVED"}


def declare_release(release, body):
    project = DB.find("projects", release.get("project_id"))
    if project is None:
        fail("ERR_PROJECT_NOT_FOUND")

    expected = body.get("expected_project_version")
    if expected is None:
        fail("ERR_STALE_VERSION")
    if int(expected) != int(project.get("version", 0)):
        fail("ERR_STALE_VERSION")

    current = release.get("status")
    if current not in DECLARE_STEPS:
        fail("ERR_INVALID_PREFAB_TRANSITION")

    target = body.get("target_status")
    if target is None:
        target = DECLARE_STEPS[current]
    if target == "RESTRICTED":
        if current != "PLANNED":
            fail("ERR_INVALID_PREFAB_TRANSITION")
        release["status"] = "RESTRICTED"
        release["restriction_since_iso"] = CLOCK.now_iso()
        touch(release)
        touch(project)
        return release
    if target not in ("RELEASED", "SHIPPED", "RECEIVED"):
        fail("ERR_INVALID_PREFAB_TRANSITION")
    if target != DECLARE_STEPS[current]:
        fail("ERR_INVALID_PREFAB_TRANSITION")

    if current == "PLANNED":
        if release.get("commitment_mode") not in ("PLANNED", "CONFIRMED"):
            fail("ERR_INVALID_PREFAB_TRANSITION")
        if project.get("project_posture") == "FROZEN":
            fail("ERR_INVALID_PREFAB_TRANSITION")
        planned = to_dt(release.get("planned_release_iso")) or to_dt(release.get("derived_planned_release_iso"))
        now = CLOCK.now()
        if planned is not None and now > planned:
            num_days_late = max(0, whole_days_between(planned, now))
            fail("ERR_MATERIAL_RELEASE_DEADLINE", None, num_days_late=num_days_late)
    elif current == "SHIPPED":
        locked = to_dt(release.get("locked_release_iso"))
        if locked is not None and CLOCK.now() <= locked:
            fail("ERR_INVALID_PREFAB_TRANSITION")

    was_restricted = release.get("status") == "RESTRICTED"
    release["status"] = target
    refresh_release_values(release)
    material_release_timing(release, project)
    if target in ("RELEASED", "SHIPPED", "RECEIVED") and release.get("locked_release_iso") is None:
        release["locked_release_iso"] = release.get("derived_planned_release_iso")
    touch(release)
    touch(project)

    from orders import recompute_all_releasable
    from projects import fabrication_locked
    recompute_all_releasable(project)
    fabrication_locked(project)
    update_project_pipeline(project)
    _ = was_restricted
    return release


def filter_releases(args):
    records = DB.all("material_releases")
    for key in ("project_id", "model_version_id", "material_commodity"):
        value = args.get(key)
        if value:
            records = [r for r in records if r.get(key) == value]
    return records