"""Shared helpers for the route modules."""
import response

ALL_ROLES = (
    "ProgramAdmin",
    "SponsorRepresentative",
    "Patient",
    "LogisticsCoordinator",
    "IntakeTechnician",
    "DestructionOfficer",
)


def page(kind, rows, limit, offset):
    total_count = len(rows)
    window = rows[offset:offset + limit]
    return response.listing(response.view_all(kind, window), limit, offset, total_count)
