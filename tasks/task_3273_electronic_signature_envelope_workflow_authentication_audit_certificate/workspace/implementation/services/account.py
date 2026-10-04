"""Accounts, retention policies, templates and bulk send (PRD §3.1, §3.8, §3.9)."""

from db import db, new_id, now_clock
from errors import (
    ApiError,
    ERR_BULK_ROW_INVALID,
    ERR_DUPLICATE_TEMPLATE_NAME,
    ERR_INSUFFICIENT_CREDIT,
    ERR_INVALID_REQUEST,
    ERR_TEMPLATE_NOT_FOUND,
    ERR_TEMPLATE_NOT_PUBLISHED,
)
from services.calculations import credit_spend_consumption
from services.common import stamp_new, touch
from services.envelope import (
    build_envelope,
    load_account,
    load_policy,
    load_template,
    guard_routing_contiguous,
    guard_credit_sufficient,
    routing_order_gap,
    VALID_AUTH_LEVELS,
    VALID_ROUTING_MODES,
)
from services.recipient import SIGNER_APPROVER

ACCOUNT_STATUSES = ("ACTIVE", "SUSPENDED", "CLOSED")
ACCOUNT_TIERS = ("STANDARD", "PRO", "ENTERPRISE")
POLICY_SCOPES = ("ACCOUNT", "GLOBAL")
PURGE_MODES = ("ANONYMIZE_METADATA", "DELETE_ALL")
TEMPLATE_STATUSES = ("DRAFT", "PUBLISHED", "ARCHIVED")


# --- accounts -----------------------------------------------------------

def create_account(body):
    name = body.get("name")
    if name is None or str(name).strip() == "":
        raise ApiError(
            ERR_INVALID_REQUEST[0], "required field 'name' is missing",
            ERR_INVALID_REQUEST[1],
        )
    state_code = body.get("state_code")
    if state_code is None or str(state_code).strip() == "":
        raise ApiError(
            ERR_INVALID_REQUEST[0], "required field 'state_code' is missing",
            ERR_INVALID_REQUEST[1],
        )
    tier = body.get("tier") or "STANDARD"
    if tier not in ACCOUNT_TIERS:
        raise ApiError(
            ERR_INVALID_REQUEST[0],
            "tier must be one of %s" % "|".join(ACCOUNT_TIERS),
            ERR_INVALID_REQUEST[1],
        )
    page_allowance = body.get("page_allowance")
    page_allowance = 25 if page_allowance is None else int(page_allowance)

    account = {
        "id": new_id(),
        "name": name,
        "state_code": state_code,
        "status": "ACTIVE",
        "credit_balance": 1000,
        "tier": tier,
        "page_allowance": page_allowance,
    }
    stamp_new(account)
    db.insert(db.accounts, account)
    return account


def adjust_credit(account, body):
    if "delta_units" not in body or body["delta_units"] is None:
        raise ApiError(
            ERR_INVALID_REQUEST[0], "required field 'delta_units' is missing",
            ERR_INVALID_REQUEST[1],
        )
    if body.get("reason") is None:
        raise ApiError(
            ERR_INVALID_REQUEST[0], "required field 'reason' is missing",
            ERR_INVALID_REQUEST[1],
        )
    account["credit_balance"] = int(account["credit_balance"]) + int(
        body["delta_units"]
    )
    touch(account)
    return account


def set_account_status(account, body):
    status = body.get("status")
    if status not in ACCOUNT_STATUSES:
        raise ApiError(
            ERR_INVALID_REQUEST[0],
            "status must be one of %s" % "|".join(ACCOUNT_STATUSES),
            ERR_INVALID_REQUEST[1],
        )
    account["status"] = status
    touch(account)
    return account


# --- retention policies -------------------------------------------------

def create_policy(body):
    name = body.get("name")
    if name is None or str(name).strip() == "":
        raise ApiError(
            ERR_INVALID_REQUEST[0], "required field 'name' is missing",
            ERR_INVALID_REQUEST[1],
        )
    scope = body.get("scope")
    if scope not in POLICY_SCOPES:
        raise ApiError(
            ERR_INVALID_REQUEST[0],
            "scope must be one of %s" % "|".join(POLICY_SCOPES),
            ERR_INVALID_REQUEST[1],
        )
    retention_years = body.get("retention_years")
    if retention_years is None:
        raise ApiError(
            ERR_INVALID_REQUEST[0],
            "required field 'retention_years' is missing",
            ERR_INVALID_REQUEST[1],
        )
    retention_years = int(retention_years)
    if retention_years < 1 or retention_years > 50:
        raise ApiError(
            ERR_INVALID_REQUEST[0],
            "retention_years must be between 1 and 50",
            ERR_INVALID_REQUEST[1],
        )
    purge_mode = body.get("purge_mode")
    if purge_mode not in PURGE_MODES:
        raise ApiError(
            ERR_INVALID_REQUEST[0],
            "purge_mode must be one of %s" % "|".join(PURGE_MODES),
            ERR_INVALID_REQUEST[1],
        )
    grace = body.get("purge_grace_days")
    grace = 0 if grace is None else int(grace)
    if grace < 0:
        raise ApiError(
            ERR_INVALID_REQUEST[0], "purge_grace_days must be >= 0",
            ERR_INVALID_REQUEST[1],
        )

    policy = {
        "id": new_id(),
        "name": name,
        "scope": scope,
        "retention_years": retention_years,
        "purge_mode": purge_mode,
        "purge_grace_days": grace,
    }
    stamp_new(policy)
    db.insert(db.retention_policies, policy)
    return policy


def update_policy(policy, body):
    if "retention_years" in body and body["retention_years"] is not None:
        years = int(body["retention_years"])
        if years < 1 or years > 50:
            raise ApiError(
                ERR_INVALID_REQUEST[0],
                "retention_years must be between 1 and 50",
                ERR_INVALID_REQUEST[1],
            )
        policy["retention_years"] = years
    if "purge_mode" in body and body["purge_mode"] is not None:
        if body["purge_mode"] not in PURGE_MODES:
            raise ApiError(
                ERR_INVALID_REQUEST[0],
                "purge_mode must be one of %s" % "|".join(PURGE_MODES),
                ERR_INVALID_REQUEST[1],
            )
        policy["purge_mode"] = body["purge_mode"]
    if "purge_grace_days" in body and body["purge_grace_days"] is not None:
        grace = int(body["purge_grace_days"])
        if grace < 0:
            raise ApiError(
                ERR_INVALID_REQUEST[0], "purge_grace_days must be >= 0",
                ERR_INVALID_REQUEST[1],
            )
        policy["purge_grace_days"] = grace
    touch(policy)
    # Eligibility is re-resolved from the live policy on every read, so no
    # stored per-envelope field needs rewriting here (PRD §2.11).
    return policy


# --- templates ----------------------------------------------------------

def create_template(body):
    account = load_account(body.get("owning_account_id"))
    name = body.get("name")
    if name is None or str(name).strip() == "":
        raise ApiError(
            ERR_INVALID_REQUEST[0], "required field 'name' is missing",
            ERR_INVALID_REQUEST[1],
        )
    # priority 28: template.name unique within owning_account_id
    for template in db.templates.values():
        if (
            template["owning_account_id"] == account["id"]
            and template["name"] == name
        ):
            raise ApiError(
                ERR_DUPLICATE_TEMPLATE_NAME[0],
                "account %s already owns a template named %s"
                % (account["id"], name),
                ERR_DUPLICATE_TEMPLATE_NAME[1],
            )

    routing_mode = body.get("default_routing_mode") or "SEQUENTIAL"
    if routing_mode not in VALID_ROUTING_MODES:
        raise ApiError(
            ERR_INVALID_REQUEST[0],
            "default_routing_mode must be one of %s"
            % "|".join(VALID_ROUTING_MODES),
            ERR_INVALID_REQUEST[1],
        )
    auth_level = body.get("default_auth_level") or "EMAIL_ACCESS"
    if auth_level not in VALID_AUTH_LEVELS:
        raise ApiError(
            ERR_INVALID_REQUEST[0],
            "default_auth_level must be one of %s"
            % "|".join(VALID_AUTH_LEVELS),
            ERR_INVALID_REQUEST[1],
        )
    page_count = body.get("page_count")
    if page_count is None:
        raise ApiError(
            ERR_INVALID_REQUEST[0], "required field 'page_count' is missing",
            ERR_INVALID_REQUEST[1],
        )
    page_count = int(page_count)
    if page_count < 1:
        raise ApiError(
            ERR_INVALID_REQUEST[0], "page_count must be at least 1",
            ERR_INVALID_REQUEST[1],
        )
    role_slot_count = body.get("role_slot_count")
    if role_slot_count is None:
        raise ApiError(
            ERR_INVALID_REQUEST[0], "required field 'role_slot_count' is missing",
            ERR_INVALID_REQUEST[1],
        )
    role_slot_count = int(role_slot_count)
    if role_slot_count < 1:
        raise ApiError(
            ERR_INVALID_REQUEST[0], "role_slot_count must be at least 1",
            ERR_INVALID_REQUEST[1],
        )

    template = {
        "id": new_id(),
        "owning_account_id": account["id"],
        "name": name,
        "default_routing_mode": routing_mode,
        "default_auth_level": auth_level,
        "page_count": page_count,
        "status": "DRAFT",
        "role_slot_count": role_slot_count,
        "times_used": 0,
    }
    stamp_new(template)
    db.insert(db.templates, template)
    return template


def publish_template(template):
    if template["status"] != "DRAFT":
        raise ApiError(
            ERR_TEMPLATE_NOT_PUBLISHED[0],
            "only a DRAFT template may be published (status is %s)"
            % template["status"],
            ERR_TEMPLATE_NOT_PUBLISHED[1],
        )
    if int(template["page_count"]) < 1 or int(template["role_slot_count"]) < 1:
        raise ApiError(
            ERR_TEMPLATE_NOT_PUBLISHED[0],
            "page_count and role_slot_count must both be at least 1",
            ERR_TEMPLATE_NOT_PUBLISHED[1],
        )
    template["status"] = "PUBLISHED"
    touch(template)
    return template


def archive_template(template):
    if template["status"] != "PUBLISHED":
        raise ApiError(
            ERR_TEMPLATE_NOT_PUBLISHED[0],
            "only a PUBLISHED template may be archived (status is %s)"
            % template["status"],
            ERR_TEMPLATE_NOT_PUBLISHED[1],
        )
    template["status"] = "ARCHIVED"
    touch(template)
    return template


def guard_template_published(template):
    if template["status"] != "PUBLISHED":
        raise ApiError(
            ERR_TEMPLATE_NOT_PUBLISHED[0],
            "template must be PUBLISHED (status is %s)" % template["status"],
            ERR_TEMPLATE_NOT_PUBLISHED[1],
        )


def instantiate_template(template, body):
    """Create an envelope from a PUBLISHED template and its role slots."""
    guard_template_published(template)
    load_account(body.get("sender_account_id"))
    load_policy(body.get("retention_policy_id"))

    recipients = body.get("recipients")
    if not isinstance(recipients, list) or not recipients:
        raise ApiError(
            ERR_INVALID_REQUEST[0],
            "required field 'recipients' must be a non-empty list",
            ERR_INVALID_REQUEST[1],
        )

    envelope = build_envelope(
        body, routing_mode=template["default_routing_mode"], template=template
    )
    envelope["template_id"] = template["id"]

    from services.envelope import add_recipient

    for slot in recipients:
        row = dict(slot)
        row.setdefault("auth_level", template["default_auth_level"])
        add_recipient(envelope, row)

    guard_routing_contiguous(envelope)

    template["times_used"] = int(template.get("times_used", 0)) + 1
    touch(template)
    touch(envelope)
    return envelope


# --- bulk send ----------------------------------------------------------

def create_bulk_send(body):
    account = load_account(body.get("account_id"))
    template = load_template(body.get("template_id"))
    total_rows = body.get("total_rows")
    if total_rows is None:
        raise ApiError(
            ERR_INVALID_REQUEST[0], "required field 'total_rows' is missing",
            ERR_INVALID_REQUEST[1],
        )
    total_rows = int(total_rows)
    if total_rows < 1:
        raise ApiError(
            ERR_INVALID_REQUEST[0], "total_rows must be at least 1",
            ERR_INVALID_REQUEST[1],
        )

    batch = {
        "id": new_id(),
        "account_id": account["id"],
        "template_id": template["id"],
        "total_rows": total_rows,
        "status": "CREATED",
        "succeeded_count": 0,
        "failed_count": 0,
    }
    stamp_new(batch)
    db.insert(db.bulk_sends, batch)
    return batch


def _row_slots(row, template):
    """The role-slot payloads a bulk row carries (PRD §3.8).

    A row may carry explicit slots under `recipients`/`role_slots`; when it does
    not, its own `email` fills the single slot the template declares, which is
    how a one-role-slot template is driven by a flat row shape.
    """
    slots = row.get("recipients")
    if not isinstance(slots, list):
        slots = row.get("role_slots")
    if isinstance(slots, list):
        return slots
    slot_count = int(template["role_slot_count"])
    filled = [{"email": row.get("email"), "role": "SIGNER"}]
    while len(filled) < slot_count:
        filled.append({"email": row.get("email"), "role": "SIGNER"})
    return filled


def _row_is_valid(row, template):
    """A row must carry a resolvable email and the role slots the template
    declares (priority 32, PRD §3.8)."""
    if not isinstance(row, dict):
        return False
    slots = _row_slots(row, template)
    if len(slots) < int(template["role_slot_count"]):
        return False
    for slot in slots:
        if not isinstance(slot, dict):
            return False
        email = slot.get("email") or row.get("email")
        if email is None or "@" not in str(email):
            return False
        if slot.get("role") and slot.get("role") not in (
            "SIGNER", "APPROVER", "COPY"
        ):
            return False
    return True


def process_bulk_send(batch, body):
    """Process the rows with deliberate partial-success semantics (PRD §3.8)."""
    if batch["status"] != "CREATED":
        raise ApiError(
            ERR_INVALID_REQUEST[0],
            "batch %s has already been processed (status %s)"
            % (batch["id"], batch["status"]),
            ERR_INVALID_REQUEST[1],
        )
    account = load_account(batch["account_id"])
    template = load_template(batch["template_id"])
    # priority 27: the template must still be PUBLISHED
    guard_template_published(template)

    rows = body.get("rows")
    if not isinstance(rows, list):
        raise ApiError(
            ERR_INVALID_REQUEST[0],
            "required field 'rows' must be a list",
            ERR_INVALID_REQUEST[1],
        )
    if not rows:
        raise ApiError(
            ERR_BULK_ROW_INVALID[0],
            "no rows were supplied",
            ERR_BULK_ROW_INVALID[1],
        )

    # priority 31: credit must cover the work before any row is processed.
    valid_rows = [r for r in rows if _row_is_valid(r, template)]
    if valid_rows:
        projected = max(1, len(valid_rows))
        per_row = max(1, 1)
        if int(account["credit_balance"]) < projected * per_row:
            raise ApiError(
                ERR_INSUFFICIENT_CREDIT[0],
                "account credit_balance %s cannot cover the bulk send"
                % account["credit_balance"],
                ERR_INSUFFICIENT_CREDIT[1],
            )

    succeeded = 0
    failed = 0
    sender_default = account["id"]
    for row in rows:
        if not _row_is_valid(row, template):
            failed += 1
            continue
        sender_id = row.get("sender_account_id") or sender_default
        policy_id = row.get("retention_policy_id")
        if policy_id is None:
            policy_id = _default_policy_id()
        if policy_id is None or db.policy(policy_id) is None:
            failed += 1
            continue
        payload = {
            "sender_account_id": sender_id,
            "subject": row.get("subject") or ("Bulk send for %s" % template["name"]),
            "retention_policy_id": policy_id,
            "routing_mode": template["default_routing_mode"],
            "template_id": template["id"],
        }
        try:
            envelope = build_envelope(
                payload,
                routing_mode=template["default_routing_mode"],
                template=template,
            )
        except ApiError:
            failed += 1
            continue
        envelope["template_id"] = template["id"]

        from services.envelope import add_document, add_recipient

        add_document(
            envelope, {"name": template["name"] + ".pdf",
                       "page_count": template["page_count"]}
        )
        for slot in _row_slots(row, template):
            add_recipient(envelope, slot)
        if routing_order_gap(envelope):
            db.envelopes.pop(envelope["id"], None)
            failed += 1
            continue
        try:
            guard_credit_sufficient(envelope)
        except ApiError:
            db.envelopes.pop(envelope["id"], None)
            failed += 1
            continue
        succeeded += 1

    batch["succeeded_count"] = succeeded
    batch["failed_count"] = failed
    if failed == 0:
        batch["status"] = "COMPLETED"
    elif succeeded == 0:
        batch["status"] = "FAILED"
    else:
        batch["status"] = "PARTIAL"
    touch(batch)
    return batch


def _default_policy_id():
    for policy in db.retention_policies.values():
        return policy["id"]
    return None