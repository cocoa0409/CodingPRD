"""Environment routes (PRD §4).

Existence checks resolve path templates left to right: the environment
identifier is resolved (and reported as ERR_ENVIRONMENT_NOT_FOUND when absent)
before any child collection of that environment is served.
"""

from flask import Blueprint, request

import calculations
import db
import middleware
import response
import validate
from services import common, environments, permissions, releases, storage

bp = Blueprint("environments", __name__)

READ = middleware.ANY_ROLE


@bp.post("/platform/environments")
def create_environment():
    actor = middleware.require("PlatformAdmin")
    b = validate.body()
    env = environments.create_environment(actor, b)
    return response.ok(_env(env), 201)


@bp.get("/platform/environments/<env_id>")
def read_environment(env_id):
    middleware.require(*READ)
    env = common.get_environment(env_id)
    return response.ok(_env(env))


@bp.get("/platform/environments/<env_id>/sandboxes")
def list_sandboxes(env_id):
    middleware.require(*READ)
    env = common.get_environment(env_id)
    rows = [
        child
        for child in db.environments.values()
        if child.get("parent_environment_id") == env["id"]
    ]
    rows = calculations.sort_asc(rows)
    limit, offset = validate.pagination_args()
    page, total = validate.paginate(rows, limit, offset)
    return response.ok_list([_env(r) for r in page], limit, offset, total)


@bp.get("/platform/environments/<env_id>/refresh-jobs")
def list_refresh_jobs(env_id):
    middleware.require(*READ)
    env = common.get_environment(env_id)
    rows = common.children(db.refresh_jobs, env["id"])
    rows = calculations.sort_desc(rows)
    limit, offset = validate.pagination_args()
    page, total = validate.paginate(rows, limit, offset)
    return response.ok_list([_refresh(j) for j in page], limit, offset, total)


@bp.get("/platform/environments/<env_id>/package-installations")
def list_installations(env_id):
    middleware.require(*READ)
    env = common.get_environment(env_id)
    rows = common.children(db.installed_packages, env["id"])
    rows = calculations.sort_asc(rows)
    limit, offset = validate.pagination_args()
    page, total = validate.paginate(rows, limit, offset)
    return response.ok_list([_installed(r) for r in page], limit, offset, total)


@bp.get("/platform/environments/<env_id>/change-sets")
def list_change_sets(env_id):
    middleware.require(*READ)
    env = common.get_environment(env_id)
    rows = common.change_sets_under(env["id"])
    rows = calculations.sort_asc(rows)
    limit, offset = validate.pagination_args()
    page, total = validate.paginate(rows, limit, offset)
    return response.ok_list([_change_set(r) for r in page], limit, offset, total)


@bp.get("/platform/environments/<env_id>/governor-limit-requests")
def list_governor_requests(env_id):
    middleware.require(*READ)
    env = common.get_environment(env_id)
    rows = common.children(db.governor_requests, env["id"])
    rows = calculations.sort_asc(rows)
    limit, offset = validate.pagination_args()
    page, total = validate.paginate(rows, limit, offset)
    return response.ok_list([_governor(r) for r in page], limit, offset, total)


@bp.get("/platform/environments/<env_id>/storage-ledgers")
def list_storage_ledgers(env_id):
    middleware.require(*READ)
    env = common.get_environment(env_id)
    rows = common.children(db.storage_ledgers, env["id"])
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = calculations.sort_asc(rows)
    limit, offset = validate.pagination_args()
    page, total = validate.paginate(rows, limit, offset)
    return response.ok_list([_ledger(r) for r in page], limit, offset, total)


@bp.get("/platform/environments/<env_id>/permissions")
def list_permissions(env_id):
    middleware.require(*READ)
    env = common.get_environment(env_id)
    rows = common.children(db.permission_assignments, env["id"])
    user_id = request.args.get("user_id")
    if user_id is not None:
        rows = [r for r in rows if r["user_id"] == user_id]
    rows = calculations.sort_asc(rows)
    limit, offset = validate.pagination_args()
    page, total = validate.paginate(rows, limit, offset)
    return response.ok_list([_grant(r) for r in page], limit, offset, total)


@bp.get("/platform/environments/<env_id>/access-audits")
def list_access_audits(env_id):
    middleware.require(*READ)
    env = common.get_environment(env_id)
    rows = common.children(db.access_audits, env["id"])
    rows = calculations.sort_asc(rows)
    limit, offset = validate.pagination_args()
    page, total = validate.paginate(rows, limit, offset)
    return response.ok_list([_audit(r) for r in page], limit, offset, total)


@bp.post("/platform/environments/<env_id>/schedule-release")
def schedule_release(env_id):
    actor = middleware.require("ReleaseManager")
    env = common.get_environment(env_id)
    b = validate.body()
    env = releases.schedule_release(actor, env, b)
    return response.ok(_env(env))


@bp.post("/platform/environments/<env_id>/apply-release")
def apply_release(env_id):
    actor = middleware.require("ReleaseManager")
    env = common.get_environment(env_id)
    env = releases.apply_release(actor, env)
    return response.ok(_env(env))


@bp.post("/platform/environments/<env_id>/open-release-window")
def open_release_window(env_id):
    actor = middleware.require("ReleaseManager")
    env = common.get_environment(env_id)
    env = releases.open_release_window(actor, env)
    return response.ok(_env(env))


@bp.post("/platform/environments/<env_id>/package-installations")
def install_package(env_id):
    actor = middleware.require("ReleaseManager")
    env = common.get_environment(env_id)
    b = validate.body()
    from services import packages

    row = packages.install_package(actor, env, b)
    return response.ok(_installed(row), 201)


@bp.post("/platform/environments/<env_id>/permissions")
def create_grant(env_id):
    actor = middleware.require("SecurityAuditor", "PlatformAdmin")
    env = common.get_environment(env_id)
    b = validate.body()
    grant = permissions.create_grant(actor, env, b)
    return response.ok(_grant(grant), 201)


@bp.post("/platform/environments/<env_id>/storage-ledgers")
def create_ledger(env_id):
    actor = middleware.require("StorageArchivist")
    env = common.get_environment(env_id)
    b = validate.body()
    ledger = storage.create_ledger(actor, env, b)
    return response.ok(_ledger(ledger), 201)


@bp.post("/platform/environments/<env_id>/storage/archive")
def archive_window(env_id):
    actor = middleware.require("StorageArchivist")
    env = common.get_environment(env_id)
    b = validate.body()
    env = storage.archive_window(actor, env, b)
    return response.ok(_env(env))


@bp.post("/platform/environments/<env_id>/governor-limit-requests")
def create_governor_request(env_id):
    actor = middleware.require("AppDeveloper")
    env = common.get_environment(env_id)
    b = validate.body()
    from services import governor

    row = governor.create_request(actor, env, b)
    return response.ok(_governor(row), 201)


# --- serializers ------------------------------------------------------------

def _env(env):
    from serializers import environment as ser

    return ser(env)


def _refresh(row):
    from serializers import refresh_job

    return refresh_job(row)


def _installed(row):
    from serializers import installed_package

    return installed_package(row)


def _change_set(row):
    from serializers import change_set

    return change_set(row)


def _governor(row):
    from serializers import governor_request

    return governor_request(row)


def _ledger(row):
    from serializers import storage_ledger

    return storage_ledger(row)


def _grant(row):
    from serializers import permission_assignment

    return permission_assignment(row)


def _audit(row):
    from serializers import access_audit

    return access_audit(row)