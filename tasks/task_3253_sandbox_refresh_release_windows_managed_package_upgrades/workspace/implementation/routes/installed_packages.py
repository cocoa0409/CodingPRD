"""Installed-package routes (PRD §4)."""

from flask import Blueprint

import middleware
import response
import validate
from services import common, packages

bp = Blueprint("installed_packages", __name__)


@bp.post("/platform/installed-packages/<installed_id>/upgrade")
def upgrade(installed_id):
    actor = middleware.require("ReleaseManager")
    installed = common.get_installed_package(installed_id)
    b = validate.body()
    installed = packages.upgrade_installation(actor, installed, b)
    return response.ok(_ser(installed))


@bp.post("/platform/installed-packages/<installed_id>/uninstall")
def uninstall(installed_id):
    actor = middleware.require("ReleaseManager")
    installed = common.get_installed_package(installed_id)
    installed = packages.uninstall_installation(actor, installed)
    return response.ok(_ser(installed))


def _ser(row):
    from serializers import installed_package

    return installed_package(row)