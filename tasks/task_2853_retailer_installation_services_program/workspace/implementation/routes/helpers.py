"""Small shared guards used by more than one route module."""
import store
from errors import ApiError


def owner_customer(project, actor):
    """Rank 29 for the customer-owned operations."""
    if actor.role == "Customer" and actor.user_id != project["customer_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def project_not_cancelled(project):
    """Rank 14."""
    if project["fulfillment_status"] == "CANCELLED":
        raise ApiError("ERR_PROJECT_CANCELLED")


def project_of(row):
    return store.get("projects", row["project_id"])


def category_and_jurisdiction(project):
    return (store.get("service_categories", project["service_category_id"]),
            store.get("jurisdictions", project["jurisdiction_id"]))
