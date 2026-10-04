"""Row serializers: internal dicts (datetime objects) -> API JSON shapes."""
from respond import iso

COMMON = ("id", "created_at", "updated_at", "version")


def serialize(row, kind):
    out = {"id": row["id"], "created_at": iso(row["created_at"])}
    if kind == "smart_account":
        out.update({
            "account_ref": row["account_ref"],
            "display_name": row["display_name"],
            "status": row["status"],
            "managing_partner_id": row.get("managing_partner_id"),
            "compliance_posture": row["compliance_posture"],
        })
    elif kind == "partner_org":
        out.update({
            "partner_ref": row["partner_ref"],
            "display_name": row["display_name"],
            "status": row["status"],
        })
    elif kind == "partner_delegation":
        out.update({
            "partner_org_id": row["partner_org_id"],
            "smart_account_id": row["smart_account_id"],
            "scope": row["scope"],
            "status": row["status"],
            "granted_at": iso(row["granted_at"]),
            "revoked_at": iso(row["revoked_at"]),
        })
    elif kind == "virtual_account":
        out.update({
            "smart_account_id": row["smart_account_id"],
            "name": row["name"],
            "status": row["status"],
        })
    elif kind == "license_pool":
        out.update({
            "virtual_account_id": row["virtual_account_id"],
            "sku": row["sku"],
            "license_model": row["license_model"],
            "feature_tier": row["feature_tier"],
            "purchased_quantity": row["purchased_quantity"],
            "consumed_quantity": row["consumed_quantity"],
            "compliance_state": row["compliance_state"],
            "grace_deadline": iso(row["grace_deadline"]),
            "overage_detected_at": iso(row["overage_detected_at"]),
            "subscription_expires_at": iso(row["subscription_expires_at"]),
        })
    elif kind == "device":
        out.update({
            "virtual_account_id": row["virtual_account_id"],
            "serial_number": row["serial_number"],
            "product_family": row["product_family"],
            "registration_state": row["registration_state"],
            "registered_at": iso(row["registered_at"]),
            "last_sync_at": iso(row["last_sync_at"]),
        })
    elif kind == "assignment":
        out.update({
            "device_id": row["device_id"],
            "license_pool_id": row["license_pool_id"],
            "quantity": row["quantity"],
            "status": row["status"],
            "assigned_at": iso(row["assigned_at"]),
        })
    elif kind == "usage_report":
        out.update({
            "device_id": row["device_id"],
            "reported_at": iso(row["reported_at"]),
            "lines": row["lines"],
            "status": row["status"],
            "rejection_reason": row["rejection_reason"],
        })
        return out
    elif kind == "compliance_event":
        out.update({
            "license_pool_id": row["license_pool_id"],
            "event_type": row["event_type"],
            "occurred_at": iso(row["occurred_at"]),
            "consumed_quantity": row["consumed_quantity"],
            "purchased_quantity": row["purchased_quantity"],
        })
        return out
    elif kind == "milestone":
        out.update({
            "product_family": row["product_family"],
            "milestone_type": row["milestone_type"],
            "effective_date": iso(row["effective_date"]),
        })
        return out
    elif kind == "service_contract":
        out.update({
            "smart_account_id": row["smart_account_id"],
            "contract_number": row["contract_number"],
            "service_level": row["service_level"],
            "support_tier": row["support_tier"],
            "start_date": iso(row["start_date"]),
            "end_date": iso(row["end_date"]),
            "status": row["status"],
        })
    elif kind == "contract_coverage":
        out.update({
            "service_contract_id": row["service_contract_id"],
            "device_id": row["device_id"],
            "status": row["status"],
            "covered_from": iso(row["covered_from"]),
        })
    elif kind == "rma_case":
        out.update({
            "contract_coverage_id": row["contract_coverage_id"],
            "device_id": row["device_id"],
            "failure_description": row["failure_description"],
            "status": row["status"],
            "ship_by": iso(row["ship_by"]),
            "opened_at": iso(row["opened_at"]),
            "sla_breached": row["sla_breached"],
        })
    elif kind == "transfer_request":
        out.update({
            "source_pool_id": row["source_pool_id"],
            "target_virtual_account_id": row["target_virtual_account_id"],
            "quantity": row["quantity"],
            "reason": row["reason"],
            "status": row["status"],
            "requested_by_partner_org_id": row["requested_by_partner_org_id"],
            "decided_by": row["decided_by"],
        })
    if "updated_at" in row:
        out["updated_at"] = iso(row["updated_at"])
    if "version" in row:
        out["version"] = row["version"]
    return out
