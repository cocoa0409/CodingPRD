"""Managed package version routes (PRD §4)."""

from flask import Blueprint

import middleware
import response
import validate
from services import common, packages

bp = Blueprint("package_versions", __name__)


@bp.post("/platform/package-versions")
def publish_version():
    actor = middleware.require("PlatformAdmin")
    b = validate.body()
    version = packages.publish_version(actor, b)
    return response.ok(_ser(version), 201)


@bp.get("/platform/package-versions/<version_id>")
def read_version(version_id):
    middleware.require(*middleware.ANY_ROLE)
    version = common.get_package_version(version_id)
    return response.ok(_ser(version))


@bp.get("/platform/package-versions/<version_id>/installations")
def list_installations(version_id):
    middleware.require(*middleware.ANY_ROLE)
    version = common.get_package_version(version_id)
    rows = packages.installations_of(version["id"])
    limit, offset = validate.pagination_args()
    page, total = validate.paginate(rows, limit, offset)
    from serializers import installed_package

    return response.ok_list([installed_package(r) for r in page], limit, offset, total)


@bp.get("/platform/package-versions/<version_id>/successors")
def list_successors(version_id):
    middleware.require(*middleware.ANY_ROLE)
    version = common.get_package_version(version_id)
    rows = packages.successors_of(version["id"])
    import calculations

    rows = calculations.sort_asc(rows)
    limit, offset = validate.pagination_args()
    page, total = validate.paginate(rows, limit, offset)
    return response.ok_list([_ser(r) for r in page], limit, offset, total)


def _ser(row):
    from serializers import package_version

    return package_version(row)