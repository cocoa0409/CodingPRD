"""Shared API blueprint (mounted under the scaffold's /api prefix)."""
from flask import Blueprint

bp = Blueprint("api", __name__)
