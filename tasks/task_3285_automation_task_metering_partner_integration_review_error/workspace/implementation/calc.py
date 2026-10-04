"""Calculation rules (scaffold §1.3, PRD §2.5/§2.6/§2.7/§2.9)."""
import math
from decimal import Decimal, ROUND_HALF_UP

from clock import Clock
from db import db
from errors import ApiError
from models import touch

RETRY_SURCHARGE_CENTS = 50
USD_CENTS = 100
DEFAULT_MAX_RETRIES = 3
COVERAGE_MIN = Decimal("0.8")


def _round_half_up(value, places):
    q = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP))


# ------------------------------------------------------------ metering_factor
def metering_factor(trigger_type):
    if trigger_type == "POLLING":
        return 4
    if trigger_type == "WEBHOOK":
        return 1
    if trigger_type == "INSTANT_WEBHOOK":
        return 0.25
    return 1


# -------------------------------------------------- trigger_latency_multiplier
def trigger_latency_multiplier(latency_seconds):
    if latency_seconds == 0:
        return 1
    if latency_seconds <= 60:
        return 1
    if latency_seconds <= 300:
        return 1.5
    if latency_seconds <= 900:
        return 2
    return 3


def charged_tasks_for(workflow, attempt_no, max_retries):
    retry_class = math.ceil(attempt_no / max_retries) if max_retries else 1
    product = (metering_factor(workflow["trigger_type"])
               * trigger_latency_multiplier(workflow["trigger_latency_seconds"])
               * retry_class)
    return int(math.ceil(product - 1e-9))


# --------------------------------------------------------------- charge_task
def charge_task(account, workflow, attempt_no, max_retries, expected_account_version):
    """ORDER OF OPERATIONS IS PINNED (scaffold §1.3 charge_task):
    OCC check first, then the metered product ceiled to whole tasks, then the
    allowance decision on that whole-task count, then counters advanced.
    """
    if account["version"] != expected_account_version:
        raise ApiError("ERR_STALE_ACCOUNT_VERSION")

    charged_tasks = charged_tasks_for(workflow, attempt_no, max_retries)
    if (account["tasks_used_current"] + charged_tasks > account["task_allowance"]
            and not account["overage_enabled"]):
        raise ApiError("ERR_TASK_ALLOWANCE_EXHAUSTED")

    rate_cents = account["closer_cost_per_task_cents"] * USD_CENTS
    before = account["tasks_used_current"]
    account["tasks_used_current"] = before + charged_tasks
    beyond = (max(0, account["tasks_used_current"] - account["task_allowance"])
              - max(0, before - account["task_allowance"]))
    account["overage_tasks_used"] += beyond
    # The action's charged cost: the CLOSING rate applied to the tasks that land
    # beyond the allowance, plus the fixed 50-cent surcharge on every whole task
    # charged (PRD §2.5). This is the figure the retry envelope is computed from.
    charged_cents = rate_cents * beyond + RETRY_SURCHARGE_CENTS * charged_tasks
    # The base overage figure covers what the customer is billed beyond the
    # allowance; a charge that stays inside the allowance adds nothing to it.
    if beyond > 0:
        account["overage_amount_cents"] += charged_cents
    _refresh_account_derived(account)
    touch(account)
    return charged_tasks, charged_cents


def _refresh_account_derived(account):
    allowance = account["task_allowance"]
    if allowance == 0:
        account["usage_pct_current"] = 0
    else:
        account["usage_pct_current"] = _round_half_up(
            account["tasks_used_current"] / allowance, 2)
    account["overage_amount_cents"] = int(account["overage_amount_cents"])
    account["projected_overage_amount_cents"] = projected_overage(account)


def projected_overage(account):
    """Maximum variant: every epoch re-charged at the higher of the two rates.

    Mirrors the charge_task accumulation across both epochs, so the figure
    equals the base figure when the two rates agree and exceeds it whenever the
    OPENING rate is the larger one (PRD §2.5).
    """
    higher = max(account["closer_cost_per_task_cents"],
                 account["opening_cost_per_task_cents"])
    allowance = account["task_allowance"]
    tasks_now = account["tasks_used_current"]
    tasks_prev = account["tasks_used_previous"]
    beyond_now = max(0, tasks_now - allowance)
    beyond_prev = max(0, tasks_prev - allowance)
    return int(higher * USD_CENTS * (beyond_now + beyond_prev)
               + RETRY_SURCHARGE_CENTS * (tasks_now + tasks_prev))


# ------------------------------------------------------------ retry_envelope
def retry_envelope(charged_cents, connection_status):
    base = max(1, 5 - int(charged_cents / 100))
    if connection_status == "TOKEN_EXPIRED":
        base = base // 2
    return max(1, base)


def retry_rank(charged_cents):
    return max(1, 5 - int(charged_cents / 100))


# --------------------------------------------------------- endpoint_coverage
def endpoint_coverage(integration_id):
    rows = [e for e in db.integration_endpoints.values()
            if e["integration_id"] == integration_id]
    total = len(rows)
    if total == 0:
        return 0.0
    with_schema = len([e for e in rows if e["has_response_schema"] is True])
    return _round_half_up(with_schema / total, 2)


def recompute_integration_coverage(integration):
    integration["endpoint_coverage"] = endpoint_coverage(integration["id"])
    touch(integration)
    return integration["endpoint_coverage"]


# ---------------------------------------------------------------- review_gate
def review_gate(integration):
    """Fixed order: auth method, then coverage (PRD §2.9)."""
    if integration["auth_method"] != "OAUTH2":
        return "REJECT", "ERR_AUTH_METHOD_NOT_OAUTH2"
    if integration["endpoint_coverage"] < COVERAGE_MIN:
        return "REJECT", "ERR_INTEGRATION_COVERAGE_INSUFFICIENT"
    return "PASS", None


def review_latency_hours(integration):
    opened = integration.get("_review_opened_at")
    if not opened:
        return 0
    delta = Clock.now() - opened
    return _round_half_up(delta.total_seconds() / 3600.0, 2)