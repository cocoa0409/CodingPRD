"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "HOST_NETWORK_NAME": "Pacific Host Network",
    "STATE_CODE": "CA",
    "DATA_RATE_MICROCENTS_PER_MB": 1237,
    "VOICE_RATE_MICROCENTS_PER_MIN": 60,
    "SMS_RATE_MICROCENTS_PER_MSG": 3,
    "COMMITTED_DATA_MB": 16000,
    "COMMITTED_VOICE_MINUTES": 200000,
    "COMMITTED_SMS_MESSAGES": 400000,
    "PLAN_CODE": "H3",
    "TERM_MONTHS": 3,
    "INTRO_PRICE_CENTS": 1999,
    "RENEWAL_PRICE_CENTS": 3042,
    "DATA_ALLOTMENT_MB": 3000,
    "VOICE_ALLOTMENT_MIN": 500,
    "SMS_ALLOTMENT_MSG": 1000,
    "MSISDN": "13055550001",
    "FULL_NAME": "Mia Herrera",
    "PARTNER_NAME": "Corner Wireless Retail",
    "PARTNER_STATE_CODES": ["CA"],
    "UNIT_COUNT": 10,
    "ADDON_PER_DAY_ALLOTMENT_MB": 500,
}


def create_agreement_payload(**overrides) -> dict:
    payload = {
        "host_network_name": DEFAULTS["HOST_NETWORK_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
        "data_rate_microcents_per_mb": DEFAULTS["DATA_RATE_MICROCENTS_PER_MB"],
        "voice_rate_microcents_per_min": DEFAULTS["VOICE_RATE_MICROCENTS_PER_MIN"],
        "sms_rate_microcents_per_msg": DEFAULTS["SMS_RATE_MICROCENTS_PER_MSG"],
        "committed_data_mb": DEFAULTS["COMMITTED_DATA_MB"],
        "committed_voice_minutes": DEFAULTS["COMMITTED_VOICE_MINUTES"],
        "committed_sms_messages": DEFAULTS["COMMITTED_SMS_MESSAGES"],
    }
    payload.update(overrides)
    return payload


_PLAN_CODE_SEQ = iter(range(1000, 9000))


def next_plan_code() -> str:
    """A plan code unique within one agreement.

    PRD 3.2: "an operator-facing `plan_code` that must be unique within that agreement",
    so a factory that always emitted the same default would make two plans on one
    agreement collide. Callers that assert on the code pass it explicitly.
    """
    return "P" + str(next(_PLAN_CODE_SEQ))


def create_plan_payload(agreement_id: str, **overrides) -> dict:
    overrides.setdefault("plan_code", next_plan_code())
    payload = {
        "agreement_id": agreement_id,
        "plan_code": overrides.pop("plan_code"),
        "term_months": DEFAULTS["TERM_MONTHS"],
        "intro_price_cents": DEFAULTS["INTRO_PRICE_CENTS"],
        "renewal_price_cents": DEFAULTS["RENEWAL_PRICE_CENTS"],
        "data_allotment_mb": DEFAULTS["DATA_ALLOTMENT_MB"],
        "voice_allotment_min": DEFAULTS["VOICE_ALLOTMENT_MIN"],
        "sms_allotment_msg": DEFAULTS["SMS_ALLOTMENT_MSG"],
    }
    payload.update(overrides)
    return payload


def create_subscriber_payload(**overrides) -> dict:
    payload = {
        "msisdn": DEFAULTS["MSISDN"],
        "full_name": DEFAULTS["FULL_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
    }
    payload.update(overrides)
    return payload


def quote_term_payload(subscriber_id: str, plan_id: str, agreement_version: int, **overrides) -> dict:
    payload = {
        "subscriber_id": subscriber_id,
        "plan_id": plan_id,
        "expected_CapacityAgreement_version": agreement_version,
    }
    payload.update(overrides)
    return payload


def create_activation_payload(subscriber_id: str, prepaid_term_id: str, **overrides) -> dict:
    payload = {
        "subscriber_id": subscriber_id,
        "prepaid_term_id": prepaid_term_id,
        "activation_channel": "DIGITAL",
    }
    payload.update(overrides)
    return payload


def create_partner_payload(**overrides) -> dict:
    payload = {
        "partner_name": DEFAULTS["PARTNER_NAME"],
        "partner_state_codes": list(DEFAULTS["PARTNER_STATE_CODES"]),
    }
    payload.update(overrides)
    return payload


def create_inventory_payload(**overrides) -> dict:
    payload = {
        "state_code": DEFAULTS["STATE_CODE"],
        "sim_media_type": "ESIM_PROFILE",
        "unit_count": DEFAULTS["UNIT_COUNT"],
    }
    payload.update(overrides)
    return payload


def create_case_payload(subscriber_id: str, **overrides) -> dict:
    payload = {
        "subscriber_id": subscriber_id,
        "topic_code": "PORT_STATUS",
    }
    payload.update(overrides)
    return payload


def create_addon_payload(subscriber_id: str, **overrides) -> dict:
    payload = {
        "subscriber_id": subscriber_id,
        "addon_type": "ROAMING",
        "addon_days": 7,
        "per_day_allotment_mb": DEFAULTS["ADDON_PER_DAY_ALLOTMENT_MB"],
    }
    payload.update(overrides)
    return payload