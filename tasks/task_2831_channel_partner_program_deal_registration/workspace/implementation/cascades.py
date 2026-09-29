"""The five multi-hop cascades and the three deterministic sweeps."""
import calc
import store


def create_conflict_case(subject, counter, account, conflict_type):
    detected_at = store.now()
    applied, chosen, reg_first, cov_first = calc.conflict_recommendations(
        subject, counter, account, detected_at, conflict_type)
    row = {
        "account_id": account["id"],
        "subject_registration_id": subject["id"],
        "counter_registration_id": counter["id"] if counter is not None else None,
        "conflict_type": conflict_type,
        "status": "OPEN",
        "detected_at": detected_at,
        "escalation_level": 0,
        "applied_variant": applied,
        "recommended_resolution": chosen,
        "recommended_resolution_registration_first": reg_first,
        "recommended_resolution_coverage_first": cov_first,
        "resolution_note": None,
        "resolved_by_user_id": None,
    }
    return store.insert("conflicts", row)


# ---------------------------------------------------------------------------
# Cascade A: an approving registration decision
# ---------------------------------------------------------------------------
def cascade_a(registration, account):
    # hop 1: the account becomes protected
    account["coverage_state"] = "CHANNEL_PROTECTED"
    account["protected_until"] = registration["exclusivity_end_at"]
    account["protected_partner_id"] = registration["partner_id"]
    account["protected_product_line"] = registration["product_line"]
    store.touch(account)

    # hop 2: sibling registrations on the same (account, product_line) are held
    siblings = []
    for other in store.ordered(store.all_rows("registrations")):
        if other["id"] == registration["id"]:
            continue
        if other["account_id"] != registration["account_id"]:
            continue
        if other["product_line"] != registration["product_line"]:
            continue
        if other["status"] not in ("SUBMITTED", "UNDER_REVIEW", "CHANGES_REQUESTED"):
            continue
        siblings.append(other)

    for sibling in siblings:
        sibling["status"] = "CONFLICT_HELD"
        sibling["closure_reason"] = "ACCOUNT_PROTECTED_BY_OTHER_PARTNER"
        store.touch(sibling)
        # hop 3: a conflict case for each held registration
        create_conflict_case(sibling, registration, account, "PARTNER_VS_PARTNER")
        # hop 4: the held registration's partner may go on probation
        partner = store.get("partners", sibling["partner_id"])
        if partner is not None:
            calc.apply_conflict_probation(partner)


# ---------------------------------------------------------------------------
# Cascade D: a direct sales rep declares pursuit of a protected account
# ---------------------------------------------------------------------------
def cascade_d(account):
    protecting = None
    for reg in store.ordered(store.all_rows("registrations")):
        if reg["account_id"] != account["id"]:
            continue
        if reg["status"] != "APPROVED":
            continue
        if reg["partner_id"] != account.get("protected_partner_id"):
            continue
        if reg["product_line"] != account.get("protected_product_line"):
            continue
        protecting = reg
        break
    if protecting is None:
        return None
    # hop 1
    case = create_conflict_case(protecting, None, account, "PARTNER_VS_DIRECT")
    # hop 2
    protecting["closure_reason"] = "DIRECT_PURSUIT_CONTESTED"
    store.touch(protecting)
    # hop 3
    partner = store.get("partners", protecting["partner_id"])
    if partner is not None:
        calc.apply_conflict_probation(partner)
    return case


# ---------------------------------------------------------------------------
# Cascade B: clawing back a validated but unpaid claim
# ---------------------------------------------------------------------------
def cascade_b(claim, allocation, partner, reason, actor_id):
    previous_approved = claim["approved_cents"] or 0
    # hop 1
    claim["validation_state"] = "REJECTED"
    claim["approved_cents"] = 0
    claim["rejection_reason"] = reason
    claim["validated_by_user_id"] = actor_id
    # hop 2
    allocation["committed_cents"] = allocation["committed_cents"] - previous_approved
    calc.recompute_available(allocation)
    store.touch(allocation)
    # hops 3 and 4
    calc.apply_marketing_standing(partner, "down")


# ---------------------------------------------------------------------------
# Cascade C: closing a fund period, in a pinned four-step order
# ---------------------------------------------------------------------------
def cascade_c(allocation):
    claims = [c for c in store.ordered(store.all_rows("claims"))
              if c["allocation_id"] == allocation["id"]]
    # step 1
    for claim in claims:
        if claim["validation_state"] in ("SUBMITTED", "PROOF_REQUESTED"):
            claim["validation_state"] = "REJECTED"
            claim["approved_cents"] = 0
            claim["rejection_reason"] = "PERIOD_CLOSED"
            allocation["committed_cents"] = (allocation["committed_cents"]
                                             - claim["requested_cents"])
            store.touch(claim)
    # step 2
    for claim in claims:
        if (claim["validation_state"] == "VALIDATED"
                and claim["settlement_state"] in ("UNPAID", "APPROVED_FOR_PAYMENT")):
            approved = claim["approved_cents"] or 0
            claim["settlement_state"] = "WRITTEN_OFF"
            claim["rejection_reason"] = "PERIOD_CLOSED"
            allocation["committed_cents"] = allocation["committed_cents"] - approved
            allocation["expired_cents"] = allocation["expired_cents"] + approved
            store.touch(claim)
    # step 3, on the balance the first two steps produced
    calc.recompute_available(allocation)
    allocation["expired_cents"] = allocation["expired_cents"] + allocation["available_cents"]
    calc.recompute_available(allocation)
    # step 4
    allocation["status"] = "CLOSED"
    allocation["closed_at"] = store.now()
    store.touch(allocation)


# ---------------------------------------------------------------------------
# Cascade E: the certification expiry sweep at review preparation
# ---------------------------------------------------------------------------
def cascade_e(partner):
    instant = store.now()
    for record in store.ordered(store.all_rows("certifications")):
        if record["partner_id"] != partner["id"]:
            continue
        if record["status"] != "ACTIVE":
            continue
        if record["expires_at"] <= instant:
            record["status"] = "EXPIRED"
            store.touch(record)
    before = (partner["cert_credit_total"], partner["portal_entitlement_level"])
    calc.recompute_cert_credits(partner)
    after = (partner["cert_credit_total"], partner["portal_entitlement_level"])
    if before != after:
        store.touch(partner)


# ---------------------------------------------------------------------------
# sweeps
# ---------------------------------------------------------------------------
def registration_expiry_sweep(account_id, product_line):
    """PRD 3.3: runs before every window precondition on submit."""
    instant = store.now()
    for reg in store.ordered(store.all_rows("registrations")):
        if reg["account_id"] != account_id or reg["product_line"] != product_line:
            continue
        if reg["status"] != "APPROVED":
            continue
        end = reg["exclusivity_end_at"]
        if end is None or not (end <= instant):
            continue
        reg["status"] = "EXPIRED"
        reg["closure_reason"] = "WINDOW_ELAPSED"
        reg["registration_margin_uplift_pct"] = calc.q4("0.02")
        store.touch(reg)
        account = store.get("accounts", reg["account_id"])
        if account is None:
            continue
        if (account["coverage_state"] == "CHANNEL_PROTECTED"
                and account.get("protected_partner_id") == reg["partner_id"]
                and account.get("protected_product_line") == reg["product_line"]
                and account.get("protected_until") is not None
                and account["protected_until"] <= instant):
            account["coverage_state"] = "OPEN_CHANNEL"
            account["protected_until"] = None
            account["protected_partner_id"] = None
            account["protected_product_line"] = None
            store.touch(account)


def mapping_expiry_sweep():
    """PRD 3.2: runs before the proposed window is tested against anything."""
    instant = store.now()
    for mapping in store.ordered(store.all_rows("mappings")):
        if mapping["mapping_status"] != "ACTIVE":
            continue
        if mapping["effective_until"] < instant:
            mapping["mapping_status"] = "EXPIRED"
            mapping["closure_reason"] = "WINDOW_ELAPSED"
            store.touch(mapping)
