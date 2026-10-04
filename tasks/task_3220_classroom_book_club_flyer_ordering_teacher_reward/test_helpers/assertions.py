"""Entity assertions and domain invariant checkers.

Each ``assert_<entity>`` checks the fields the contract guarantees on the
response body: a server-minted UUID id, ISO 8601 timestamps, the integer
version, and the entity's declared fields. Domain invariants (points balance
reconciliation) are checked separately.
"""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str) -> None:
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_school(data: dict) -> None:
    _assert_common_fields(data, "School")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["address"], str) and data["address"]
    assert isinstance(data["low_income_program"], bool)
    assert data["posture"] in ("NORMAL", "RESTRICTED")
    assert "active_fair_id" in data


def assert_teacher(data: dict) -> None:
    _assert_common_fields(data, "Teacher")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["grade_band"] in ("K_2", "G3_5", "G6_8")
    for field in (
        "points_balance",
        "points_earned_total",
        "points_redeemed_total",
        "points_expired_total",
        "donated_books_received",
    ):
        assert isinstance(data[field], int), f"Teacher.{field} must be an integer"


def assert_title(data: dict) -> None:
    _assert_common_fields(data, "Title")
    assert isinstance(data["isbn"], str) and data["isbn"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["format"] in ("HARDCOVER", "PAPERBACK", "CLUB_PAPERBACK")
    assert data["grade_band"] in ("K_2", "G3_5", "G6_8")
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] > 0
    assert isinstance(data["points_cost"], int) and data["points_cost"] > 0
    assert isinstance(data["rights_holder"], str)
    assert isinstance(data["royalty_cap_cents"], int) and data["royalty_cap_cents"] > 0
    assert data["license_status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["royalty_accrued_cents"], int) and data["royalty_accrued_cents"] >= 0
    assert isinstance(data["fair_count_used"], int) and data["fair_count_used"] >= 0


def assert_promotion(data: dict) -> None:
    _assert_common_fields(data, "Promotion")
    assert isinstance(data["name"], str) and data["name"]
    assert data["kind"] in ("BONUS_POINTS", "TITLE_INCENTIVE")
    assert data["status"] in ("ACTIVE", "EXPIRED")
    assert isinstance(data["starts_on"], str)
    assert isinstance(data["ends_on"], str)


def assert_flyer_cycle(data: dict) -> None:
    _assert_common_fields(data, "FlyerCycle")
    assert isinstance(data["month"], str) and len(data["month"]) == 7
    assert data["grade_band"] in ("K_2", "G3_5", "G6_8")
    assert data["status"] in ("DRAFT", "PUBLISHED", "CLOSED")
    assert isinstance(data["offering_count"], int) and data["offering_count"] >= 0


def assert_flyer_offering(data: dict) -> None:
    _assert_common_fields(data, "FlyerOffering")
    assert is_valid_uuid(data["cycle_id"])
    assert is_valid_uuid(data["title_id"])
    assert isinstance(data["flyer_price_cents"], int) and data["flyer_price_cents"] > 0
    assert isinstance(data["fair_overlap"], bool)


def assert_class_order(data: dict) -> None:
    _assert_common_fields(data, "ClassOrder")
    assert is_valid_uuid(data["cycle_id"])
    assert is_valid_uuid(data["teacher_id"])
    assert data["status"] in ("OPEN", "SUBMITTED", "CANCELLED")
    assert data["ship_status"] in ("PENDING", "PARTIAL", "SHIPPED")
    assert data["points_status"] in ("UNAWARDED", "AWARDED", "CLAWED_BACK")
    for field in (
        "subtotal_cents",
        "rewardable_subtotal_cents",
        "discount_cents",
        "net_total_cents",
        "shipping_fee_cents",
        "awarded_base_points",
        "awarded_bonus_points",
        "awarded_total_points",
    ):
        assert isinstance(data[field], int), f"ClassOrder.{field} must be an integer, got {data.get(field)!r}"


def assert_order_line(data: dict) -> None:
    _assert_common_fields(data, "OrderLine")
    assert is_valid_uuid(data["class_order_id"])
    assert is_valid_uuid(data["offering_id"])
    assert isinstance(data["student_name"], str) and data["student_name"]
    assert data["submitted_by"] in ("PARENT_ONLINE", "TEACHER")
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["fair_overlap"], bool)
    assert isinstance(data["donation_funded"], bool)
    assert data["status"] in ("ACTIVE", "BACKORDERED", "CANCELLED")
    assert isinstance(data["points_earned"], int)


def assert_book_fair(data: dict) -> None:
    _assert_common_fields(data, "BookFair")
    assert is_valid_uuid(data["school_id"])
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert data["status"] in ("SCHEDULED", "ACTIVE", "COMPLETED", "CANCELLED")


def assert_fair_title(data: dict) -> None:
    _assert_common_fields(data, "FairTitle")
    assert is_valid_uuid(data["fair_id"])
    assert is_valid_uuid(data["title_id"])


def assert_donation_request(data: dict) -> None:
    _assert_common_fields(data, "DonationRequest")
    assert is_valid_uuid(data["school_id"])
    assert is_valid_uuid(data["teacher_id"])
    assert is_valid_uuid(data["title_id"])
    assert isinstance(data["qty_requested"], int) and data["qty_requested"] >= 1
    assert data["status"] in ("OPEN", "MATCHED", "FULFILLED", "CANCELLED")


def assert_redemption(data: dict) -> None:
    _assert_common_fields(data, "Redemption")
    assert is_valid_uuid(data["teacher_id"])
    assert data["kind"] in ("BOOK", "SUPPLY")
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert isinstance(data["points_cost"], int) and data["points_cost"] >= 0
    assert data["status"] in ("PENDING", "CONFIRMED", "CANCELLED")


def assert_program_enrollment(data: dict) -> None:
    _assert_common_fields(data, "ProgramEnrollment")
    assert is_valid_uuid(data["school_id"])
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["enrolled_on"], str)


def assert_points_ledger_entry(data: dict) -> None:
    _assert_common_fields(data, "PointsLedger")
    assert is_valid_uuid(data["teacher_id"])
    assert data["entry_type"] in ("EARN", "REDEEM", "EXPIRE", "CLAWBACK", "ADJUST")
    assert isinstance(data["points"], int)
    assert data["ref_type"] in ("CLASS_ORDER", "REDEMPTION", "OPS_RUN", "MANUAL")
    assert isinstance(data["ref_id"], str) and data["ref_id"]
    assert isinstance(data["note"], str)


def assert_teacher_points_reconcile(teacher: dict) -> None:
    """The balance must always equal earned minus redeemed minus expired."""
    expected = (
        teacher["points_earned_total"]
        - teacher["points_redeemed_total"]
        - teacher["points_expired_total"]
    )
    assert teacher["points_balance"] == expected, (
        f"points_balance {teacher['points_balance']} must reconcile to "
        f"earned({teacher['points_earned_total']}) - redeemed({teacher['points_redeemed_total']}) "
        f"- expired({teacher['points_expired_total']}) = {expected}"
    )
