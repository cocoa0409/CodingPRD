"""Route modules. Importing each module registers its handlers via @route."""

from routes import catalog, items, containers, stores, calendar, audits  # noqa: F401

__all__ = ["catalog", "items", "containers", "stores", "calendar", "audits"]