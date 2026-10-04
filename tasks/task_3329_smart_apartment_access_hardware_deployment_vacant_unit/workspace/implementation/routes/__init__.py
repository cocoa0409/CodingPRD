"""API blueprint; every route is mounted under the /smart-rent prefix."""

from flask import Blueprint

api = Blueprint("api", __name__, url_prefix="/smart-rent")