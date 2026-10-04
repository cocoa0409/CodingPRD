"""Shared business services: charges, cascades, queue drain, send gates."""
from datetime import timedelta

import store
from constants import (
    CAMPAIGN_RECURRING_FEE_CENTS,
    RECURRING_FEE_PERIOD_DAYS,
    NUMBER_MONTHLY_FEE_CENTS,
    NUMBER_FEE_PERIOD_DAYS,
    DRAIN_SECONDS_PER_RUN,
    STALE_QUEUE_RUNS,
    TOLL_FREE_MIN_SCORE,
    SPAM_FLOOR_BPS,
    SPAM_FLOOR_MIN_VOLUME,
)
from errors import ApiError, ERR_ACCOUNT_SUSPENDED, ERR_ACCOUNT_CLOSED
from services.calc import (
    compute_allocated_mps,
    message_fee_cents,
    carrier_fee_cents,
)
from util import new_id, now_dt, parse_iso, format_iso, sort_by_created, touch


def record_charge(account_id, kind, reference_type, reference_id, amount_cents):
    charge = {
        "id": new_id(),
        "created_at": store.now_iso(),
        "account_id": account_id,
        "kind": kind,
        "reference_type": reference_type,
        "reference_id": reference_id,
        "amount_cents": amount_cents,
        "currency": "USD",
        "status": "RECORDED",
    }
    store.CHARGES[charge["id"]] = charge
    return charge


def check_account_gate(account):
    """PRD 2.8 step 4: mutating endpoints rejected when account not ACTIVE.
    Caller exempts reinstate/close and reads."""
    if account["status"] == "SUSPENDED":
        raise ApiError(ERR_ACCOUNT_SUSPENDED, "Account is suspended", 409)
    if account["status"] == "CLOSED":
        raise ApiError(ERR_ACCOUNT_CLOSED, "Account is closed", 409)


def cascade_suspend_campaign(campaign, reason):
    """Suspend every ACTIVE number attached to the campaign (created_at ASC),
    stamping the given suspended_reason. Each cascaded child gets its own
    updated_at + version bump."""
    numbers = [
        n for n in store.NUMBERS.values()
        if n.get("campaign_id") == campaign["id"] and n["status"] == "ACTIVE"
    ]
    for number in sort_by_created(numbers):
        number["status"] = "SUSPENDED"
        number["suspended_reason"] = reason
        touch(number)


def cascade_suspend_account(account):
    """PRD 2.9: every APPROVED campaign of the account (created_at ASC) is
    suspended, then each of those campaigns' ACTIVE numbers suspended with
    suspended_reason ACCOUNT_SUSPENDED."""
    campaigns = [
        c for c in store.CAMPAIGNS.values()
        if c["account_id"] == account["id"] and c["status"] == "APPROVED"
    ]
    for campaign in sort_by_created(campaigns):
        campaign["status"] = "SUSPENDED"
        touch(campaign)
        numbers = [
            n for n in store.NUMBERS.values()
            if n.get("campaign_id") == campaign["id"] and n["status"] == "ACTIVE"
        ]
        for number in sort_by_created(numbers):
            number["status"] = "SUSPENDED"
            number["suspended_reason"] = "ACCOUNT_SUSPENDED"
            touch(number)


def is_filtered(campaign, brand, number, message):
    """Deterministic carrier filtering per PRD 3.7."""
    body = message["body"]
    if (
        campaign["path_kind"] == "TEN_DLC"
        and message["carrier_code"] == "ATT"
        and len(body) > 160
    ):
        return True
    if message["carrier_code"] == "TMO" and "FREE" in body:
        return True
    if (
        number["number_type"] == "TOLL_FREE"
        and brand["identity_score"] < TOLL_FREE_MIN_SCORE
    ):
        return True
    return False


def drain_campaign_queue(campaign, run_index):
    """Drain up to capacity QUEUED messages of an APPROVED campaign.
    Returns (sent_or_filtered_count)."""
    capacity = campaign["allocated_mps"] * DRAIN_SECONDS_PER_RUN
    candidates = [
        m for m in store.MESSAGES.values()
        if m["campaign_id"] == campaign["id"] and m["status"] == "QUEUED"
    ]
    candidates.sort(key=lambda m: (m["queued_at"] or "", m["created_at"], m["id"]))
    drained = 0
    brand = store.BRANDS.get(campaign["brand_id"])
    for message in candidates:
        if drained >= capacity:
            break
        number = store.NUMBERS.get(message["sender_number_id"])
        if is_filtered(campaign, brand, number, message):
            message["status"] = "FILTERED"
            touch(message)
            record_charge(
                campaign["account_id"], "MESSAGE", "MESSAGE", message["id"],
                message_fee_cents(message["segments"]),
            )
        else:
            message["status"] = "SENT"
            touch(message)
            record_charge(
                campaign["account_id"], "MESSAGE", "MESSAGE", message["id"],
                message_fee_cents(message["segments"]),
            )
            record_charge(
                campaign["account_id"], "CARRIER_PASSTHROUGH", "MESSAGE",
                message["id"],
                carrier_fee_cents(message["segments"], message["carrier_code"]),
            )
        drained += 1
    return drained


def stale_sweep(account_id, run_index):
    """Any still-QUEUED message with (run_index - queued_run_index) >= 3 is
    STALE_CANCELLED; no charges. Returns count cancelled."""
    cancelled = 0
    for message in store.MESSAGES.values():
        if message["account_id"] != account_id:
            continue
        if message["status"] != "QUEUED":
            continue
        if run_index - message.get("queued_run_index", 0) >= STALE_QUEUE_RUNS:
            message["status"] = "STALE_CANCELLED"
            touch(message)
            cancelled += 1
    return cancelled


def recurring_fee_pass(account, now):
    """Recurring + number monthly fee pass per PRD 3.7.
    Returns (recurring_fees_charged, number_fees_charged)."""
    recurring_count = 0
    campaigns = [
        c for c in store.CAMPAIGNS.values()
        if c["account_id"] == account["id"] and c["status"] == "APPROVED"
    ]
    for campaign in sort_by_created(campaigns):
        last = campaign.get("recurring_fee_last_charge_at")
        if last is None or now >= parse_iso(last) + timedelta(days=RECURRING_FEE_PERIOD_DAYS):
            record_charge(
                account["id"], "CAMPAIGN_RECURRING", "CAMPAIGN", campaign["id"],
                CAMPAIGN_RECURRING_FEE_CENTS,
            )
            campaign["recurring_fee_last_charge_at"] = format_iso(now)
            touch(campaign)
            recurring_count += 1

    number_count = 0
    window_start = now - timedelta(days=NUMBER_FEE_PERIOD_DAYS)
    numbers = [
        n for n in store.NUMBERS.values()
        if n["account_id"] == account["id"] and n["status"] in ("ACTIVE", "SUSPENDED")
    ]
    for number in sort_by_created(numbers):
        activated_at = number.get("activated_at")
        if activated_at is None:
            continue
        if parse_iso(activated_at) > window_start:
            continue
        recent = any(
            ch["reference_type"] == "NUMBER"
            and ch["reference_id"] == number["id"]
            and ch["kind"] == "NUMBER_MONTHLY"
            and parse_iso(ch["created_at"]) > window_start
            for ch in store.CHARGES.values()
        )
        if recent:
            continue
        record_charge(
            account["id"], "NUMBER_MONTHLY", "NUMBER", number["id"],
            NUMBER_MONTHLY_FEE_CENTS[number["number_type"]],
        )
        number_count += 1
    return recurring_count, number_count


def final_number_fee_on_release(number, now):
    """Fiscal last-resort rule (PRD 3.5): releasing a number carrying an
    unsettled NUMBER_MONTHLY charge younger than 30 days immediately bills one
    final NUMBER_MONTHLY charge. Never a client-visible rejection."""
    window_start = now - timedelta(days=NUMBER_FEE_PERIOD_DAYS)
    recent_unsettled = any(
        ch["reference_type"] == "NUMBER"
        and ch["reference_id"] == number["id"]
        and ch["kind"] == "NUMBER_MONTHLY"
        and ch["status"] == "RECORDED"
        and parse_iso(ch["created_at"]) > window_start
        for ch in store.CHARGES.values()
    )
    if recent_unsettled:
        record_charge(
            number["account_id"], "NUMBER_MONTHLY", "NUMBER", number["id"],
            NUMBER_MONTHLY_FEE_CENTS[number["number_type"]],
        )


def spam_floor_check(campaign, snapshot):
    """PRD 3.8: inclusive boundaries on both volume and rate."""
    if (
        snapshot["attempted"] >= SPAM_FLOOR_MIN_VOLUME
        and snapshot["spam_rate_bps"] >= SPAM_FLOOR_BPS
    ):
        if campaign["status"] != "SUSPENDED":
            campaign["status"] = "SUSPENDED"
            touch(campaign)
        cascade_suspend_campaign(campaign, "SPAM_FLOOR_BREACH")


def queue_message(message, run_index):
    """ACCEPTED -> QUEUED: stamp queued_at and queued_run_index."""
    message["status"] = "QUEUED"
    message["queued_at"] = store.now_iso()
    message["queued_run_index"] = run_index
    touch(message)


def current_run_index(account_id):
    """The account's current ops-run index, or 0 if it has never run ops."""
    indexes = [
        r["run_index"] for r in store.OPSRUNS.values()
        if r["account_id"] == account_id
    ]
    return max(indexes) if indexes else 0


def check_throughput(campaign, now):
    """PRD 3.6 gate 5: count of this campaign's messages created within the
    trailing 1 second must be strictly below allocated_mps."""
    from errors import ERR_THROUGHPUT_EXCEEDED

    allocated = campaign["allocated_mps"]
    window_start = now - timedelta(seconds=1)
    count = sum(
        1
        for m in store.MESSAGES.values()
        if m["campaign_id"] == campaign["id"]
        and parse_iso(m["created_at"]) > window_start
    )
    if count >= allocated:
        raise ApiError(
            ERR_THROUGHPUT_EXCEEDED,
            "Campaign throughput cap reached within trailing 1 second",
            429,
        )


def active_consent_for(brand_id, phone_number):
    """Resolve the ACTIVE consent record for (brand, phone_number), if any."""
    matches = [
        c for c in store.CONSENTS.values()
        if c["brand_id"] == brand_id
        and c["phone_number"] == phone_number
        and c["status"] == "ACTIVE"
    ]
    if not matches:
        return None
    return sort_by_created(matches)[-1]


def check_recipient_not_busy(campaign_id, to_number):
    from errors import ERR_RECIPIENT_BUSY

    for m in store.MESSAGES.values():
        if (
            m["campaign_id"] == campaign_id
            and m["to_number"] == to_number
            and m["status"] == "QUEUED"
        ):
            raise ApiError(
                ERR_RECIPIENT_BUSY,
                "Recipient already has an in-flight QUEUED message from this campaign",
                409,
            )
