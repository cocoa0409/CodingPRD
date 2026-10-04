"""Entity assertions and domain invariant checkers (PRD §2.2–§2.4, §3).

assert_{entity}(data) validates the wire shape of one resource. The three
light resource types (OrderLine, Lot, TrainingCertification) must NOT
carry updated_at/version (PRD §2.4) — their assertions assert absence.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data, entity_name):
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity_name}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity_name}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be a positive int"
    )


def _assert_light_fields(data, entity_name):
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity_name}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{entity_name} must not carry updated_at (PRD §2.4)"
    assert "version" not in data, f"{entity_name} must not carry version (PRD §2.4)"


def assert_distributor(data):
    _assert_common_fields(data, "Distributor")
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in ["PROSPECT", "ACTIVE", "SUSPENDED", "TERMINATED"]
    assert data["service_level_tier"] in ["STANDARD", "PREFERRED", "ELITE"]
    assert isinstance(data["performance_score_provisional"], (int, float))
    assert isinstance(data["performance_score_final"], (int, float))


def assert_territory(data):
    _assert_common_fields(data, "Territory")
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region"], str)
    assert data["status"] in ["OPEN", "GRANTED", "REVOKED"]
    assert data.get("granted_distributor_id") is None or is_valid_uuid(data["granted_distributor_id"])
    assert data.get("granted_at") is None or is_iso8601_timestamp(data["granted_at"])
    assert data.get("revoked_at") is None or is_iso8601_timestamp(data["revoked_at"])
    assert isinstance(data["min_weekly_visits_per_account"], int)


def assert_account(data):
    _assert_common_fields(data, "Account")
    assert isinstance(data["name"], str) and data["name"]
    assert data["channel"] in [
        "INDEPENDENT_GROCER", "CONVENIENCE", "FOODSERVICE", "MASS_MERCHANT", "CLUB_STORE",
    ]
    assert data["approval_status"] in ["UNDER_REVIEW", "APPROVED", "REJECTED", "SUSPENDED"]
    assert is_valid_uuid(data.get("territory_id", ""))
    assert is_valid_uuid(data.get("distributor_id", ""))
    assert data.get("approved_at") is None or is_iso8601_timestamp(data["approved_at"])
    assert isinstance(data["late_pulls_30d"], int) and data["late_pulls_30d"] >= 0
    assert isinstance(data["training_compliant"], bool)


def assert_product(data):
    _assert_common_fields(data, "Product")
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] > 0
    assert isinstance(data["shelf_life_opened_hours"], int) and data["shelf_life_opened_hours"] > 0
    assert isinstance(data["shelf_life_unopened_days"], int) and data["shelf_life_unopened_days"] > 0
    assert isinstance(data["allergen_tags"], list)
    for tag in data["allergen_tags"]:
        assert tag in ["MILK", "EGG", "WHEAT", "SOY", "PEANUT", "TREE_NUT", "SESAME"]
    assert isinstance(data["requires_dedicated_slicer"], bool)
    assert isinstance(data["channel_restricted"], bool)
    assert data["status"] in ["ACTIVE", "DISCONTINUED"]


def assert_authorization(data):
    _assert_common_fields(data, "AccountProductAuthorization")
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_valid_uuid(data.get("product_id", ""))
    assert data["status"] in ["REQUESTED", "AUTHORIZED", "SUSPENDED", "REVOKED"]
    assert data["suspension_source"] in ["NONE", "INCIDENT", "ACCOUNT_SUSPEND"]


def assert_order(data):
    _assert_common_fields(data, "Order")
    assert is_valid_uuid(data.get("distributor_id", ""))
    assert isinstance(data["delivery_week"], str) and len(data["delivery_week"]) == 10
    assert data["allocation_status"] in ["PENDING", "ALLOCATED", "PARTIAL", "SHORTED", "CANCELLED"]
    assert data["fulfillment_status"] in ["UNSHIPPED", "IN_TRANSIT", "DELIVERED", "REJECTED"]
    for field in ("merchandise_total_cents", "discount_cents", "delivery_fee_cents", "total_cents"):
        assert isinstance(data[field], int) and data[field] >= 0, f"Order.{field} must be a non-negative int"


def assert_order_line(data):
    _assert_light_fields(data, "OrderLine")
    assert is_valid_uuid(data.get("order_id", ""))
    assert is_valid_uuid(data.get("product_id", ""))
    assert isinstance(data["qty_requested"], int) and data["qty_requested"] > 0
    assert isinstance(data["qty_allocated"], int) and data["qty_allocated"] >= 0
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] > 0
    assert isinstance(data["line_total_cents"], int) and data["line_total_cents"] >= 0


def assert_plant(data):
    _assert_common_fields(data, "Plant")
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in ["ACTIVE", "SHUTDOWN"]


def assert_production_run(data):
    _assert_common_fields(data, "ProductionRun")
    assert is_valid_uuid(data.get("plant_id", ""))
    assert isinstance(data["line_code"], str) and data["line_code"]
    assert is_valid_uuid(data.get("product_id", ""))
    assert is_iso8601_timestamp(data.get("window_start", ""))
    assert is_iso8601_timestamp(data.get("window_end", ""))
    assert data["window_start"] < data["window_end"], "window_start must precede window_end"
    assert isinstance(data["capacity_units"], int) and data["capacity_units"] > 0
    assert isinstance(data["planned_units"], int) and data["planned_units"] > 0
    assert data.get("actual_units") is None or isinstance(data["actual_units"], int)
    assert data.get("waste_units") is None or isinstance(data["waste_units"], int)
    assert data["status"] in ["SCHEDULED", "COMPLETED", "CANCELLED"]


def assert_lot(data):
    _assert_light_fields(data, "Lot")
    assert is_valid_uuid(data.get("production_run_id", ""))
    assert is_valid_uuid(data.get("product_id", ""))
    for field in ("available_units", "allocated_units", "delivered_units"):
        assert isinstance(data[field], int) and data[field] >= 0, f"Lot.{field} must be a non-negative int"
    assert is_iso8601_timestamp(data.get("expires_at", ""))
    assert data["status"] in ["AVAILABLE", "QUARANTINED", "RECALLED", "EXHAUSTED"]


def assert_delivery(data):
    _assert_common_fields(data, "Delivery")
    assert is_valid_uuid(data.get("order_id", ""))
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_valid_uuid(data.get("distributor_id", ""))
    assert isinstance(data["lines"], list) and len(data["lines"]) > 0
    for line in data["lines"]:
        assert is_valid_uuid(line.get("lot_id", ""))
        assert isinstance(line["qty"], int) and line["qty"] > 0
    assert data["status"] in ["PENDING", "CONFIRMED", "REJECTED"]
    assert data.get("confirmed_at") is None or is_iso8601_timestamp(data["confirmed_at"])


def assert_service_visit(data):
    _assert_common_fields(data, "ServiceVisit")
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_valid_uuid(data.get("distributor_id", ""))
    assert is_iso8601_timestamp(data.get("window_start", ""))
    assert is_iso8601_timestamp(data.get("window_end", ""))
    assert data["window_start"] < data["window_end"]
    assert data["status"] in ["SCHEDULED", "SUBMITTED", "VERIFIED", "REWORK", "CANCELLED"]
    if data.get("score") is not None:
        assert isinstance(data["score"], int) and 0 <= data["score"] <= 100
    assert data.get("submitted_at") is None or is_iso8601_timestamp(data["submitted_at"])


def assert_slicer(data):
    _assert_common_fields(data, "Slicer")
    assert is_valid_uuid(data.get("account_id", ""))
    assert isinstance(data["label"], str) and data["label"]
    assert data["dedicated_allergen"] in [
        "NONE", "MILK", "EGG", "WHEAT", "SOY", "PEANUT", "TREE_NUT", "SESAME",
    ]
    assert data.get("cleaning_verified_at") is None or is_iso8601_timestamp(data["cleaning_verified_at"])
    assert data["status"] in ["ACTIVE", "DECOMMISSIONED"]


def assert_opened_product_log(data):
    _assert_common_fields(data, "OpenedProductLog")
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_valid_uuid(data.get("product_id", ""))
    assert is_valid_uuid(data.get("slicer_id", ""))
    assert is_iso8601_timestamp(data.get("opened_at", ""))
    assert is_iso8601_timestamp(data.get("pull_deadline", ""))
    assert data["opened_at"] < data["pull_deadline"], "pull_deadline must be after opened_at"
    assert data.get("pulled_at") is None or is_iso8601_timestamp(data["pulled_at"])
    assert data["status"] in ["OPEN", "PULLED_ON_TIME", "PULLED_LATE", "FORCE_PULLED"]


def assert_training_certification(data):
    _assert_light_fields(data, "TrainingCertification")
    assert is_valid_uuid(data.get("account_id", ""))
    assert isinstance(data["associate_name"], str) and data["associate_name"]
    assert isinstance(data["slicing_module_passed"], bool)
    assert isinstance(data["allergen_module_passed"], bool)
    assert is_iso8601_timestamp(data.get("certified_at", ""))
    assert is_iso8601_timestamp(data.get("expires_at", ""))
    assert data["certified_at"] < data["expires_at"]
    assert data["status"] in ["ACTIVE", "EXPIRED", "REVOKED"]


def assert_promo_program(data):
    _assert_common_fields(data, "PromoProgram")
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_valid_uuid(data.get("product_id", ""))
    assert isinstance(data["promo_price_cents"], int) and data["promo_price_cents"] > 0
    assert isinstance(data["start_date"], str) and isinstance(data["end_date"], str)
    assert data["start_date"] <= data["end_date"], "start_date must be on or before end_date"
    assert isinstance(data["budget_cents"], int) and data["budget_cents"] > 0
    assert isinstance(data["estimated_units"], int) and data["estimated_units"] > 0
    assert data["status"] in ["DRAFT", "AUTHORIZED", "REJECTED", "SUSPENDED", "SETTLED"]
    for field in ("unit_allowance_cents", "reserved_cents", "spent_cents", "released_cents"):
        assert isinstance(data[field], int) and data[field] >= 0, f"PromoProgram.{field} must be a non-negative int"


def assert_incident(data):
    _assert_common_fields(data, "Incident")
    assert is_valid_uuid(data.get("plant_id", ""))
    assert isinstance(data["title"], str) and data["title"]
    assert data["severity"] in ["LOW", "HIGH", "CRITICAL"]
    assert isinstance(data["affected_run_ids"], list)
    assert data["status"] in ["REPORTED", "TRIAGED", "CONFIRMED_RECALL", "CONTAINED", "RESOLVED", "CLOSED"]
    assert data.get("resolution_outcome") is None or data["resolution_outcome"] in ["CONFIRMED", "FALSE_ALARM"]
    assert isinstance(data["affected_account_count"], int) and data["affected_account_count"] >= 0


# ---------------- Domain invariant checkers ----------------

def assert_lot_conservation(lot, production_run):
    """PRD §3.4: available + allocated + delivered + run waste == run actual."""
    total = (
        lot["available_units"] + lot["allocated_units"] + lot["delivered_units"]
        + production_run["waste_units"]
    )
    assert total == production_run["actual_units"], (
        f"lot conservation violated: {lot['available_units']} + {lot['allocated_units']} "
        f"+ {lot['delivered_units']} + {production_run['waste_units']} != {production_run['actual_units']}"
    )


def assert_order_money_consistency(order):
    """PRD §3.3: total = merchandise - discount + fee, fee in {0, 1500}."""
    assert order["delivery_fee_cents"] in (0, 1500)
    assert order["total_cents"] == (
        order["merchandise_total_cents"] - order["discount_cents"] + order["delivery_fee_cents"]
    ), (
        f"total {order['total_cents']} != merch {order['merchandise_total_cents']} "
        f"- discount {order['discount_cents']} + fee {order['delivery_fee_cents']}"
    )


def assert_promo_reserve_consistency(promo_program):
    """PRD §3.7: after settlement, reserved == spent + released."""
    if promo_program["status"] == "SETTLED":
        assert promo_program["reserved_cents"] == (
            promo_program["spent_cents"] + promo_program["released_cents"]
        ), (
            f"reserve {promo_program['reserved_cents']} != spent {promo_program['spent_cents']} "
            f"+ released {promo_program['released_cents']}"
        )
