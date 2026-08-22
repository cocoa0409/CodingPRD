"""Route blueprints, one module per resource group."""

from routes import (
    affidavits,
    appeals,
    clock,
    districts,
    materials,
    proctors,
    registrations,
    reports,
    schools,
    sessions,
    windows,
)

BLUEPRINTS = (
    districts.bp,
    schools.bp,
    windows.bp,
    materials.bp,
    proctors.bp,
    affidavits.bp,
    sessions.bp,
    registrations.bp,
    reports.bp,
    appeals.bp,
    clock.bp,
)
