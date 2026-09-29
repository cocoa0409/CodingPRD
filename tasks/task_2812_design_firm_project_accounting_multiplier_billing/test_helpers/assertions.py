"""
Domain assertions for the design-firm project accounting API.

Money is compared at exactly 2 decimal places and ratios at exactly 4, in
decimal rather than binary floating point, because PRD §2.5 pins both the
precision and the arithmetic. Every comparison therefore quantises both sides
through ``Decimal`` — a test must never fail because 3389.85 came back as
3389.8500000000004.

The ledger identity of PRD §2.10 has its own assertion because it must hold
"after every request and after every hop of every cascade", which makes it the
single most-repeated check in the suite.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import raw_json
from .api_errors import ladder_position, ladder_rung
from .constants import (
    API_REQUEST_ID_PREFIX,
    MONEY_DECIMAL_PLACES,
    RATIO_DECIMAL_PLACES,
)

_MONEY_Q = Decimal(10) ** -MONEY_DECIMAL_PLACES
_RATIO_Q = Decimal(10) ** -RATIO_DECIMAL_PLACES


def _dec(value: Any) -> Decimal:
    """Decimal view of a JSON number, without going through binary float."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def quantize_money(value: Any) -> Decimal:
    return _dec(value).quantize(_MONEY_Q, rounding=ROUND_HALF_UP)


def quantize_ratio(value: Any) -> Decimal:
    return _dec(value).quantize(_RATIO_Q, rounding=ROUND_HALF_UP)


# ─── Scalar comparisons (PRD §2.5) ────────────────────────────────────


def assert_money(actual: Any, expected: Any, label: str = "amount") -> None:
    """Assert a monetary figure equals its expectation at 2 decimal places."""
    assert actual is not None, f"{label} is missing from the response"
    assert quantize_money(actual) == quantize_money(expected), (
        f"{label}: expected {quantize_money(expected)}, got {actual}"
    )


def assert_ratio(actual: Any, expected: Any, label: str = "ratio") -> None:
    """Assert a ratio-valued figure equals its expectation at 4 decimal places."""
    assert actual is not None, f"{label} is missing from the response"
    assert quantize_ratio(actual) == quantize_ratio(expected), (
        f"{label}: expected {quantize_ratio(expected)}, got {actual}"
    )


def assert_money_scale(value: Any, label: str = "amount") -> None:
    """Assert a monetary figure carries no more than 2 decimal places."""
    assert _dec(value) == quantize_money(value), (
        f"{label} must be carried at 2 decimal places, got {value}"
    )


def assert_ratio_scale(value: Any, label: str = "ratio") -> None:
    """Assert a ratio-valued figure carries no more than 4 decimal places."""
    assert _dec(value) == quantize_ratio(value), (
        f"{label} must be carried at 4 decimal places, got {value}"
    )


def assert_null(value: Any, label: str) -> None:
    """PRD §2.5: an unknown rate is null rather than zero."""
    assert value is None, f"{label} must be null, got {value!r}"


# ─── Envelope and common fields (PRD §2.2, §2.4) ───────────────────────


def assert_envelope_meta(response) -> Dict[str, Any]:
    """
    Assert the envelope meta of PRD §2.2 on the untouched wire body: an
    ``api_request_id`` starting ``req_`` and an ISO 8601 UTC
    ``api_request_timestamp`` with three fractional digits.
    """
    body = raw_json(response)
    meta = body["meta"]
    request_id = meta["api_request_id"]
    assert request_id.startswith(API_REQUEST_ID_PREFIX), (
        f"meta.api_request_id must start with '{API_REQUEST_ID_PREFIX}', got {request_id!r}"
    )
    assert_iso8601_millis(meta["api_request_timestamp"], "meta.api_request_timestamp")
    return meta


def assert_iso8601_millis(value: Any, label: str) -> None:
    """PRD §2.4: an ISO 8601 UTC instant with three fractional digits."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{label} is not an ISO 8601 UTC instant: {value!r}"
    assert value.endswith("Z"), f"{label} must be expressed in UTC with a Z suffix: {value!r}"
    fraction = value[:-1].split(".")[1] if "." in value else ""
    assert len(fraction) == 3, (
        f"{label} must carry exactly three fractional digits, got {value!r}"
    )


def assert_uuid_id(data: Dict[str, Any]) -> None:
    """PRD §2.4: ``id`` is a server-minted UUID string carrying no type prefix."""
    resource_id = data.get("id")
    assert is_valid_uuid(resource_id), f"id must be a bare UUID, got {resource_id!r}"


def assert_mutable_common_fields(data: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """
    PRD §2.4: a mutable resource carries ``id``, ``created_at``, ``updated_at``
    and ``version``, and ``version`` starts at 1.
    """
    assert_uuid_id(data)
    for field in ("created_at", "updated_at"):
        assert field in data, f"a mutable resource must carry {field}"
    assert isinstance(data.get("version"), int), (
        f"version must be an integer, got {data.get('version')!r}"
    )
    if expected_version is not None:
        assert data["version"] == expected_version, (
            f"version: expected {expected_version}, got {data['version']}"
        )


def assert_immutable_common_fields(data: Dict[str, Any]) -> None:
    """
    PRD §2.4: Client and LaborRate carry only ``id`` and ``created_at`` — they
    have no ``updated_at`` field and no ``version`` field at all.
    """
    assert_uuid_id(data)
    assert "created_at" in data, "an immutable resource must still carry created_at"
    assert "updated_at" not in data, (
        f"an immutable resource must have no updated_at field, got {data.get('updated_at')!r}"
    )
    assert "version" not in data, (
        f"an immutable resource must have no version field, got {data.get('version')!r}"
    )


def assert_computed_report(data: Dict[str, Any]) -> None:
    """
    PRD §3.6 / §3.8: the earned-value and aging payloads are computed reports,
    not persisted entities, and carry none of the common resource properties.
    """
    for field in ("id", "created_at", "updated_at", "version"):
        assert field not in data, (
            f"a computed report must not carry {field}, got {data.get(field)!r}"
        )


# ─── Pagination (PRD §2.3) ────────────────────────────────────────────


def assert_pagination_meta(
    meta: Dict[str, Any],
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
) -> None:
    """Assert the four pagination fields PRD §2.3 requires in ``meta``."""
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field in meta, f"list meta must report {field}"
    if limit is not None:
        assert meta["limit"] == limit, f"meta.limit: expected {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, f"meta.offset: expected {offset}, got {meta['offset']}"
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"meta.total_count: expected {total_count}, got {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"meta.has_more: expected {has_more}, got {meta['has_more']}"
        )


def assert_created_at_ascending(rows: Sequence[Dict[str, Any]]) -> None:
    """PRD §2.3: list results are ordered by ``created_at`` ascending."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"rows are not ordered by created_at ascending: {stamps}"


# ─── The conserved ledger (PRD §2.10) ─────────────────────────────────


def assert_ledger_conserved(project: Dict[str, Any]) -> None:
    """
    PRD §2.10: ``total_charge_value`` is the sum of ``unbilled_wip``,
    ``billed_open``, ``paid_gross_to_date`` and ``written_off_gross``, and the
    identity must hold after every request.
    """
    buckets = (
        _dec(project["unbilled_wip"])
        + _dec(project["billed_open"])
        + _dec(project["paid_gross_to_date"])
        + _dec(project["written_off_gross"])
    )
    assert quantize_money(buckets) == quantize_money(project["total_charge_value"]), (
        "total_charge_value must equal unbilled_wip + billed_open + "
        f"paid_gross_to_date + written_off_gross: buckets sum to {quantize_money(buckets)} "
        f"but total_charge_value is {project['total_charge_value']}"
    )


def assert_project_ledger(
    project: Dict[str, Any],
    unbilled_wip: Optional[Any] = None,
    billed_open: Optional[Any] = None,
    paid_gross_to_date: Optional[Any] = None,
    written_off_gross: Optional[Any] = None,
    total_charge_value: Optional[Any] = None,
    raw_labor_cost_to_date: Optional[Any] = None,
    earned_revenue_to_date: Optional[Any] = None,
    net_multiplier_achieved: Optional[Any] = None,
) -> None:
    """Assert any subset of the project rollups, then the conservation identity."""
    money_fields = {
        "unbilled_wip": unbilled_wip,
        "billed_open": billed_open,
        "paid_gross_to_date": paid_gross_to_date,
        "written_off_gross": written_off_gross,
        "total_charge_value": total_charge_value,
        "raw_labor_cost_to_date": raw_labor_cost_to_date,
        "earned_revenue_to_date": earned_revenue_to_date,
    }
    for name, expected in money_fields.items():
        if expected is not None:
            assert_money(project[name], expected, f"project.{name}")
    if net_multiplier_achieved is not None:
        assert_ratio(
            project["net_multiplier_achieved"],
            net_multiplier_achieved,
            "project.net_multiplier_achieved",
        )
    assert_ledger_conserved(project)


def assert_billing_posture(project: Dict[str, Any], expected: str) -> None:
    """PRD §2.11: the derived project-level gate."""
    assert project["billing_posture"] == expected, (
        f"billing_posture: expected {expected}, got {project['billing_posture']}"
    )


# ─── Frozen charges (PRD §3.3, §3.4, §3.5) ────────────────────────────


def assert_time_entry_frozen(
    entry: Dict[str, Any],
    raw_cost: Any,
    applied_multiplier: Any,
    billable_amount: Any,
) -> None:
    """PRD §3.3: the three figures frozen onto a line at approval."""
    assert_money(entry["raw_cost"], raw_cost, "time_entry.raw_cost")
    assert_ratio(
        entry["applied_multiplier"], applied_multiplier, "time_entry.applied_multiplier"
    )
    assert_money(entry["billable_amount"], billable_amount, "time_entry.billable_amount")


def assert_time_entry_carries_no_money(entry: Dict[str, Any]) -> None:
    """
    PRD §3.3: a submitted line "carries no money yet: its raw_cost and
    billable_amount are both 0.00 and its applied_multiplier is null".
    """
    assert_money(entry["raw_cost"], 0.00, "time_entry.raw_cost")
    assert_money(entry["billable_amount"], 0.00, "time_entry.billable_amount")
    assert_null(entry["applied_multiplier"], "time_entry.applied_multiplier")


def assert_expense_decision(
    expense: Dict[str, Any],
    allowability_status: str,
    allowability_reason: str,
    billable_amount: Any,
) -> None:
    """PRD §3.4: the allowability decision and the billable amount that follows."""
    assert expense["allowability_status"] == allowability_status, (
        f"allowability_status: expected {allowability_status}, got {expense['allowability_status']}"
    )
    assert expense["allowability_reason"] == allowability_reason, (
        f"allowability_reason: expected {allowability_reason}, got {expense['allowability_reason']}"
    )
    assert_money(expense["billable_amount"], billable_amount, "expense.billable_amount")


def assert_payable_axes(
    payable: Dict[str, Any],
    approval_status: str,
    payment_status: str,
    billing_status: str,
) -> None:
    """PRD §3.5: a payable carries three independent status axes."""
    assert payable["approval_status"] == approval_status, (
        f"approval_status: expected {approval_status}, got {payable['approval_status']}"
    )
    assert payable["payment_status"] == payment_status, (
        f"payment_status: expected {payment_status}, got {payable['payment_status']}"
    )
    assert payable["billing_status"] == billing_status, (
        f"billing_status: expected {billing_status}, got {payable['billing_status']}"
    )


def assert_payable_markup(
    payable: Dict[str, Any],
    applied_markup_pct: Any,
    markup_amount: Any,
    billable_amount: Any,
) -> None:
    """PRD §3.5: the markup triple frozen on a payable at approval."""
    assert_ratio(
        payable["applied_markup_pct"], applied_markup_pct, "payable.applied_markup_pct"
    )
    assert_money(payable["markup_amount"], markup_amount, "payable.markup_amount")
    assert_money(payable["billable_amount"], billable_amount, "payable.billable_amount")


def assert_commitment_identity(subcontract: Dict[str, Any]) -> None:
    """
    PRD §3.5: "committed_remaining is always the committed_amount less
    approved_to_date".
    """
    expected = _dec(subcontract["committed_amount"]) - _dec(subcontract["approved_to_date"])
    assert_money(
        subcontract["committed_remaining"],
        expected,
        "subcontract.committed_remaining (committed_amount less approved_to_date)",
    )


def assert_subcontract_rollup(
    subcontract: Dict[str, Any],
    approved_to_date: Optional[Any] = None,
    released_to_date: Optional[Any] = None,
    committed_remaining: Optional[Any] = None,
    status: Optional[str] = None,
) -> None:
    """Assert any subset of the subcontract commitment rollup, then the identity."""
    if approved_to_date is not None:
        assert_money(
            subcontract["approved_to_date"], approved_to_date, "subcontract.approved_to_date"
        )
    if released_to_date is not None:
        assert_money(
            subcontract["released_to_date"], released_to_date, "subcontract.released_to_date"
        )
    if committed_remaining is not None:
        assert_money(
            subcontract["committed_remaining"],
            committed_remaining,
            "subcontract.committed_remaining",
        )
    if status is not None:
        assert subcontract["status"] == status, (
            f"subcontract.status: expected {status}, got {subcontract['status']}"
        )
    assert_commitment_identity(subcontract)


# ─── Invoice money (PRD §3.7) ─────────────────────────────────────────


def assert_invoice_money(
    invoice: Dict[str, Any],
    labor_billed: Optional[Any] = None,
    expense_billed: Optional[Any] = None,
    consultant_billed: Optional[Any] = None,
    gross_billed: Optional[Any] = None,
    volume_discount_pct: Optional[Any] = None,
    discount_amount: Optional[Any] = None,
    retainage_amount: Optional[Any] = None,
    net_due: Optional[Any] = None,
) -> None:
    """Assert any subset of the invoice waterfall, then its internal arithmetic."""
    for name, expected in (
        ("labor_billed", labor_billed),
        ("expense_billed", expense_billed),
        ("consultant_billed", consultant_billed),
        ("gross_billed", gross_billed),
        ("discount_amount", discount_amount),
        ("retainage_amount", retainage_amount),
        ("net_due", net_due),
    ):
        if expected is not None:
            assert_money(invoice[name], expected, f"invoice.{name}")
    if volume_discount_pct is not None:
        assert_ratio(
            invoice["volume_discount_pct"],
            volume_discount_pct,
            "invoice.volume_discount_pct",
        )
    assert_invoice_waterfall(invoice)


def assert_invoice_waterfall(invoice: Dict[str, Any]) -> None:
    """
    PRD §3.7: ``gross_billed`` is the sum of the three subtotals and ``net_due``
    is ``gross_billed`` less ``discount_amount`` less ``retainage_amount``.
    """
    subtotals = (
        _dec(invoice["labor_billed"])
        + _dec(invoice["consultant_billed"])
        + _dec(invoice["expense_billed"])
    )
    assert_money(
        invoice["gross_billed"],
        subtotals,
        "invoice.gross_billed (labor_billed + consultant_billed + expense_billed)",
    )
    net = (
        _dec(invoice["gross_billed"])
        - _dec(invoice["discount_amount"])
        - _dec(invoice["retainage_amount"])
    )
    assert_money(
        invoice["net_due"],
        net,
        "invoice.net_due (gross_billed less discount_amount less retainage_amount)",
    )


def assert_swept_counts(
    invoice: Dict[str, Any],
    swept_labor_count: Optional[int] = None,
    swept_expense_count: Optional[int] = None,
    swept_consultant_count: Optional[int] = None,
    backup_missing_count: Optional[int] = None,
) -> None:
    """PRD §3.7: what the invoice records about the population it swept."""
    for name, expected in (
        ("swept_labor_count", swept_labor_count),
        ("swept_expense_count", swept_expense_count),
        ("swept_consultant_count", swept_consultant_count),
        ("backup_missing_count", backup_missing_count),
    ):
        if expected is not None:
            assert invoice[name] == expected, (
                f"invoice.{name}: expected {expected}, got {invoice[name]}"
            )


# ─── Aging and earned value (PRD §3.6, §3.8) ──────────────────────────


def assert_aging_report(
    report: Dict[str, Any],
    bucket_0_30: Optional[Any] = None,
    bucket_31_60: Optional[Any] = None,
    bucket_61_90: Optional[Any] = None,
    bucket_over_90: Optional[Any] = None,
    total_unbilled: Optional[Any] = None,
    write_off_eligible_amount: Optional[Any] = None,
) -> None:
    """
    Assert any subset of the aging buckets, then the two identities of PRD §3.8:
    ``total_unbilled`` is the sum of the four buckets and
    ``write_off_eligible_amount`` is exactly ``bucket_over_90``.
    """
    for name, expected in (
        ("bucket_0_30", bucket_0_30),
        ("bucket_31_60", bucket_31_60),
        ("bucket_61_90", bucket_61_90),
        ("bucket_over_90", bucket_over_90),
        ("total_unbilled", total_unbilled),
        ("write_off_eligible_amount", write_off_eligible_amount),
    ):
        if expected is not None:
            assert_money(report[name], expected, f"wip_aging.{name}")
    bucket_sum = (
        _dec(report["bucket_0_30"])
        + _dec(report["bucket_31_60"])
        + _dec(report["bucket_61_90"])
        + _dec(report["bucket_over_90"])
    )
    assert_money(
        report["total_unbilled"], bucket_sum, "wip_aging.total_unbilled (sum of the four buckets)"
    )
    assert_money(
        report["write_off_eligible_amount"],
        report["bucket_over_90"],
        "wip_aging.write_off_eligible_amount (exactly bucket_over_90)",
    )


def assert_earned_value_report(
    report: Dict[str, Any],
    effort_based_percent_complete: Optional[Any] = None,
    effort_based_earned_value: Optional[Any] = None,
    assessed_percent_complete: Optional[Any] = None,
    assessed_earned_value: Optional[Any] = None,
    recognized_earned_value: Optional[Any] = None,
    selected_method: Optional[str] = None,
    actual_labor_cost_to_date: Optional[Any] = None,
    phase_fee: Optional[Any] = None,
) -> None:
    """Assert any subset of the side-by-side earned-value payload of PRD §3.6."""
    for name, expected in (
        ("effort_based_earned_value", effort_based_earned_value),
        ("assessed_earned_value", assessed_earned_value),
        ("recognized_earned_value", recognized_earned_value),
        ("actual_labor_cost_to_date", actual_labor_cost_to_date),
        ("phase_fee", phase_fee),
    ):
        if expected is not None:
            assert_money(report[name], expected, f"earned_value.{name}")
    for name, expected in (
        ("effort_based_percent_complete", effort_based_percent_complete),
        ("assessed_percent_complete", assessed_percent_complete),
    ):
        if expected is not None:
            assert_ratio(report[name], expected, f"earned_value.{name}")
    if selected_method is not None:
        assert report["selected_method"] == selected_method, (
            f"earned_value.selected_method: expected {selected_method}, got {report['selected_method']}"
        )


def assert_phase_earned_value(
    phase: Dict[str, Any],
    actual_labor_cost_to_date: Optional[Any] = None,
    effort_based_percent_complete: Optional[Any] = None,
    effort_based_earned_value: Optional[Any] = None,
    assessed_percent_complete: Optional[Any] = None,
    assessed_earned_value: Optional[Any] = None,
    recognized_earned_value: Optional[Any] = None,
    phase_fee: Optional[Any] = None,
    consultant_committed_open: Optional[Any] = None,
) -> None:
    """Assert any subset of a persisted phase's derived figures."""
    for name, expected in (
        ("actual_labor_cost_to_date", actual_labor_cost_to_date),
        ("effort_based_earned_value", effort_based_earned_value),
        ("assessed_earned_value", assessed_earned_value),
        ("recognized_earned_value", recognized_earned_value),
        ("phase_fee", phase_fee),
        ("consultant_committed_open", consultant_committed_open),
    ):
        if expected is not None:
            assert_money(phase[name], expected, f"phase.{name}")
    for name, expected in (
        ("effort_based_percent_complete", effort_based_percent_complete),
        ("assessed_percent_complete", assessed_percent_complete),
    ):
        if expected is not None:
            assert_ratio(phase[name], expected, f"phase.{name}")


# ─── Write-off routing (PRD §3.8) ─────────────────────────────────────


def assert_write_off_routing(
    write_off: Dict[str, Any],
    required_approver: Optional[str] = None,
    status: Optional[str] = None,
    aging_days: Optional[int] = None,
    allocated_time_entry_ids: Optional[List[str]] = None,
) -> None:
    """Assert the routing decision and the allocation frozen at preparation."""
    if required_approver is not None:
        assert write_off["required_approver"] == required_approver, (
            f"write_off.required_approver: expected {required_approver}, "
            f"got {write_off['required_approver']}"
        )
    if status is not None:
        assert write_off["status"] == status, (
            f"write_off.status: expected {status}, got {write_off['status']}"
        )
    if aging_days is not None:
        assert write_off["aging_days"] == aging_days, (
            f"write_off.aging_days: expected {aging_days}, got {write_off['aging_days']}"
        )
    if allocated_time_entry_ids is not None:
        assert write_off["allocated_time_entry_ids"] == list(allocated_time_entry_ids), (
            "write_off.allocated_time_entry_ids must be the ordered prefix "
            f"{list(allocated_time_entry_ids)}, got {write_off['allocated_time_entry_ids']}"
        )


# ─── Rejection ladder (PRD §2.8) ──────────────────────────────────────


def assert_outranks(winning_error_id: str, losing_error_id: str) -> None:
    """
    Assert the ladder of PRD §2.8 really does place the winner ahead of the
    loser, so a precedence test is anchored on the specification's own order.
    """
    assert ladder_position(winning_error_id) < ladder_position(losing_error_id), (
        f"{winning_error_id} must be evaluated ahead of {losing_error_id} "
        f"(ladder positions {ladder_position(winning_error_id)} and "
        f"{ladder_position(losing_error_id)}; rungs "
        f"{ladder_rung(winning_error_id)} and {ladder_rung(losing_error_id)})"
    )
