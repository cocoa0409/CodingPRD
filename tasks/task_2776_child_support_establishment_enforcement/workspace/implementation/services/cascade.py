"""Shared cascade side effects (PRD 2.8).  Every cascaded row that carries a
version gets its own increment and refreshed updated_at, including rows the
caller never named.
"""
import db
import util
from services import interest, withholding

# Which participant flag each remedy sets when it activates (PRD 3.6).
REMEDY_FLAGS = {
    "LICENSE_SUSPENSION": ("license_suspension_active", True),
    "PROPERTY_LIEN": ("lien_recorded", True),
    "CREDIT_BUREAU_REPORT": ("credit_bureau_reported", True),
    "TAX_REFUND_INTERCEPT": None,
    "CONTEMPT_REFERRAL": None,
}


def apply_remedy_flag(participant, action_type):
    spec = REMEDY_FLAGS.get(action_type)
    if spec is None:
        return
    field, _ = spec
    participant[field] = True
    if action_type == "LICENSE_SUSPENSION":
        participant["has_valid_drivers_license"] = False


def reverse_remedy_flag(participant, action_type):
    spec = REMEDY_FLAGS.get(action_type)
    if spec is None:
        return
    field, _ = spec
    participant[field] = False
    if action_type == "LICENSE_SUSPENSION":
        participant["has_valid_drivers_license"] = True


def other_active_of_type(participant_id, action_type, exclude_action_id):
    for action in db.enforcement_actions.values():
        if action["id"] == exclude_action_id or action["status"] != "ACTIVE":
            continue
        if action["action_type"] != action_type:
            continue
        case = db.cases.get(action["case_id"])
        if case is not None and case["noncustodial_party_id"] == participant_id:
            return True
    return False


def settle_posture(case):
    """Posture returns to NORMAL once no ACTIVE action remains on the case."""
    live = [a for a in db.case_actions(case["id"]) if a["status"] == "ACTIVE"]
    if not live:
        case["enforcement_posture"] = "NORMAL"


def release_action(action, case, reason, reverse_flag=True, restore_posture=True):
    """ACTIVE -> RELEASED with the flag reversal and posture settlement."""
    participant = db.participants.get(case["noncustodial_party_id"])
    action["status"] = "RELEASED"
    action["released_at"] = db.now()
    action["release_reason"] = reason
    action["remedy_applied"] = False
    db.touch(action)
    if participant is not None:
        if reverse_flag and not other_active_of_type(
                participant["id"], action["action_type"], action["id"]):
            reverse_remedy_flag(participant, action["action_type"])
        db.touch(participant)
    if restore_posture:
        settle_posture(case)
    db.touch(case)


def release_noticed_action(action, case, reason):
    """NOTICE_SENT -> RELEASED: no participant flag is touched at all."""
    action["status"] = "RELEASED"
    action["released_at"] = db.now()
    action["release_reason"] = reason
    action["remedy_applied"] = False
    db.touch(action)


def void_charge(charge, case, refund_paid):
    """Void a charge; the cascade path returns applied money as credit."""
    if charge["status"] == "VOID":
        return
    case["total_charged_principal_cents"] -= charge["amount_cents"]
    if refund_paid and charge["paid_cents"] > 0:
        case["unapplied_credit_cents"] += charge["paid_cents"]
    charge["status"] = "VOID"
    charge["unpaid_balance_cents"] = 0


def terminate_iwo(iwo, reason):
    """Terminate a withholding order and settle the employer's active count."""
    if iwo["service_status"] == "TERMINATED":
        return
    was_serving = iwo["service_status"] in ("SERVED", "AMENDED")
    iwo["service_status"] = "TERMINATED"
    iwo["terminated_reason"] = reason
    if was_serving:
        iwo["next_remittance_due_at"] = None
        employer = db.employers.get(iwo["employer_id"])
        if employer is not None:
            employer["active_iwo_count"] = max(0, employer["active_iwo_count"] - 1)
            db.touch(employer)
    db.touch(iwo)


def terminate_case_iwos(case, reason):
    for iwo in db.case_iwos(case["id"]):
        if iwo["service_status"] in ("SERVED", "AMENDED"):
            terminate_iwo(iwo, reason)


def terminate_order_iwos(order, reason, from_states=("SERVED", "AMENDED")):
    for iwo in db.order_iwos(order["id"]):
        if iwo["service_status"] in from_states:
            terminate_iwo(iwo, reason)


def refresh_open_case_counts(case):
    """open_case_count is derived on read; touch the rows so versions move."""
    for pid in (case["custodial_party_id"], case["noncustodial_party_id"]):
        participant = db.participants.get(pid)
        if participant is not None:
            db.touch(participant)


def vacate_entered_order(order, case, reason):
    """Order vacatur cascade (PRD 3.3): charges, money, withholding."""
    order["status"] = "VACATED"
    order["vacate_reason"] = reason
    order["terminated_date"] = db.now().date()
    db.touch(order)
    for charge in db.order_charges(order["id"]):
        if charge["status"] == "OPEN":
            void_charge(charge, case, refund_paid=True)
    terminate_order_iwos(order, "ORDER_VACATED")
    for action in db.case_actions(case["id"]):
        if action["status"] == "ACTIVE":
            release_action(action, case, "ORDER_VACATED")
    db.touch(case)


def close_case(case, reason):
    """Case closure cascade (PRD 3.9)."""
    case["case_status"] = "CLOSED"
    case["closed_reason"] = reason
    case["closed_at"] = db.now()
    terminate_case_iwos(case, "CASE_CLOSED")
    db.touch(case)
    refresh_open_case_counts(case)


def paternity_excluded_cascade(action, case):
    """Four-level cascade on genetic exclusion (PRD 3.2)."""
    case["case_status"] = "CLOSED"
    case["closed_reason"] = "NO_JURISDICTION"
    case["closed_at"] = db.now()
    for order in db.case_orders(case["id"]):
        if order["status"] in ("SUPERSEDED", "VACATED"):
            continue
        order["status"] = "VACATED"
        order["vacate_reason"] = "PATERNITY_EXCLUDED"
        order["terminated_date"] = db.now().date()
        db.touch(order)
        for charge in db.order_charges(order["id"]):
            if charge["status"] == "OPEN":
                void_charge(charge, case, refund_paid=True)
        terminate_order_iwos(order, "ORDER_VACATED")
    for enf in db.case_actions(case["id"]):
        if enf["status"] in ("DENIED", "RELEASED"):
            continue
        enf["status"] = "RELEASED"
        enf["released_at"] = db.now()
        enf["release_reason"] = "ORDER_VACATED"
        enf["remedy_applied"] = False
        db.touch(enf)
    obligor = db.participants.get(case["noncustodial_party_id"])
    if obligor is not None:
        obligor["license_suspension_active"] = False
        obligor["lien_recorded"] = False
        obligor["credit_bureau_reported"] = False
        obligor["has_valid_drivers_license"] = True
        db.touch(obligor)
    custodian = db.participants.get(case["custodial_party_id"])
    if custodian is not None:
        db.touch(custodian)
    db.touch(case)
