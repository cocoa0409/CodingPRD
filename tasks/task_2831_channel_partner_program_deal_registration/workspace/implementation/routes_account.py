"""Account, direct pursuit and AccountMapping endpoints."""
from flask import g

import calc
import cascades
import serialize
import store
import validate as v
from auth import acting_partner_scope, endpoint
from constants import (EXCLUSIVITY_SCOPES, MAPPING_COOLDOWN_DAYS, MAX_COUNTER_ROUNDS,
                       MAX_NAME_LEN, PRODUCT_LINES, REGION_CODES)
from errors import ApiError
from guards import (check_no_overdue_audit, find, find_account, find_partner,
                    invalid_state)
from response import created, filtered, listing, object_response


def register(app):
    # ---------------------------------------------------------------- Account
    @app.route("/accounts", methods=["POST"])
    @endpoint("ChannelOpsAnalyst")
    def create_account():
        body = v.body()
        account_name = v.req_string(body, "account_name", max_len=MAX_NAME_LEN)
        region_code = v.req_enum(body, "region_code", REGION_CODES)
        row = {
            "account_name": account_name,
            "region_code": region_code,
            "coverage_state": "OPEN_CHANNEL",
            "protected_until": None,
            "protected_partner_id": None,
            "protected_product_line": None,
            "direct_pursuit_owner_id": None,
            "direct_pursuit_declared_at": None,
        }
        store.insert("accounts", row)
        return created(serialize.account(row))

    @app.route("/accounts", methods=["GET"])
    @endpoint("ChannelOpsAnalyst", "ChannelDirector", "DirectSalesRep", "Partner")
    def list_accounts():
        rows = store.ordered(store.all_rows("accounts"))
        rows = filtered(rows, [("region_code", "region_code"),
                               ("coverage_state", "coverage_state"),
                               ("protected_partner_id", "protected_partner_id")])
        return listing(rows, serialize.account)

    @app.route("/accounts/<account_id>", methods=["GET"])
    @endpoint("ChannelOpsAnalyst", "ChannelDirector", "DirectSalesRep", "Partner")
    def read_account(account_id):
        account = find_account(account_id)
        return object_response(serialize.account(account))

    @app.route("/accounts/<account_id>/direct-pursuit", methods=["POST"])
    @endpoint("DirectSalesRep")
    def declare_direct_pursuit(account_id):
        account = find_account(account_id)
        body = v.body()
        v.opt_string(body, "pursuit_note", non_empty=False)
        state = account["coverage_state"]
        if state not in ("OPEN_CHANNEL", "CHANNEL_PROTECTED"):
            raise invalid_state("Direct pursuit cannot be declared on a %s account." % state)
        account["direct_pursuit_owner_id"] = g.user_id
        account["direct_pursuit_declared_at"] = store.now()
        if state == "OPEN_CHANNEL":
            account["coverage_state"] = "NAMED_DIRECT"
            store.touch(account)
        else:
            store.touch(account)
            cascades.cascade_d(account)
        return object_response(serialize.account(account))

    @app.route("/accounts/<account_id>/deal-registrations", methods=["GET"])
    @endpoint("ChannelOpsAnalyst", "ChannelDirector", "DirectSalesRep")
    def list_account_registrations(account_id):
        account = find_account(account_id)
        rows = [r for r in store.ordered(store.all_rows("registrations"))
                if r["account_id"] == account["id"]]
        rows = filtered(rows, [("status", "status"), ("product_line", "product_line")])
        return listing(rows, serialize.registration)

    @app.route("/accounts/<account_id>/conflict-cases", methods=["GET"])
    @endpoint("ChannelOpsAnalyst", "ChannelDirector", "DirectSalesRep")
    def list_account_conflicts(account_id):
        account = find_account(account_id)
        rows = [r for r in store.ordered(store.all_rows("conflicts"))
                if r["account_id"] == account["id"]]
        rows = filtered(rows, [("status", "status")])
        return listing(rows, serialize.conflict)

    # ---------------------------------------------------------- AccountMapping
    @app.route("/account-mappings", methods=["POST"])
    @endpoint("ChannelOpsAnalyst")
    def create_mapping():
        body = v.body()
        # existence (3) resolves body foreign keys in declaration order
        partner_ref = v.fk_candidate(body, "partner_id")
        if partner_ref is not None:
            find_partner(partner_ref)
        account_ref = v.fk_candidate(body, "account_id")
        if account_ref is not None:
            account = find_account(account_ref)
        else:
            account = None
        # request shape (5)
        partner_id = v.req_string(body, "partner_id")
        account_id = v.req_string(body, "account_id")
        product_line = v.req_enum(body, "product_line", PRODUCT_LINES)
        scope = v.req_enum(body, "exclusivity_scope", EXCLUSIVITY_SCOPES)
        effective_from = v.req_instant(body, "effective_from")
        effective_until = v.req_instant(body, "effective_until")
        v.interval(effective_from, effective_until, "effective_from", "effective_until")
        expected_version = v.req_int(body, "expected_account_version", minimum=0)
        # account stale-version guard (8)
        if account["version"] != expected_version:
            raise ApiError("ERR_STALE_ACCOUNT_VERSION",
                           "The account has been modified since it was read.")
        # the mapping sweep runs before the candidate window is tested
        cascades.mapping_expiry_sweep()
        candidate = {
            "id": None,
            "account_id": account_id,
            "product_line": product_line,
            "exclusivity_scope": scope,
            "effective_from": effective_from,
            "effective_until": effective_until,
        }
        clash = calc.mapping_window_conflict(
            candidate, ("PROPOSED", "COUNTERED", "ACTIVE", "EXPIRED"),
            MAPPING_COOLDOWN_DAYS)
        if clash is not None:
            raise ApiError("ERR_MAPPING_WINDOW_CONFLICT",
                           "The proposed window collides with an existing agreement.")
        row = {
            "partner_id": partner_id,
            "account_id": account_id,
            "product_line": product_line,
            "exclusivity_scope": scope,
            "effective_from": effective_from,
            "effective_until": effective_until,
            "mapping_status": "PROPOSED",
            "counter_round": 0,
            "activated_at": None,
            "closure_reason": None,
        }
        store.insert("mappings", row)
        store.touch(account)
        return created(serialize.mapping(row))

    @app.route("/account-mappings", methods=["GET"])
    @endpoint("ChannelOpsAnalyst", "ChannelDirector", "Partner")
    def list_mappings():
        rows = store.ordered(store.all_rows("mappings"))
        rows = filtered(rows, [("partner_id", "partner_id"),
                               ("account_id", "account_id"),
                               ("mapping_status", "mapping_status"),
                               ("product_line", "product_line")])
        return listing(rows, serialize.mapping)

    @app.route("/account-mappings/<mapping_id>", methods=["GET"])
    @endpoint("ChannelOpsAnalyst", "ChannelDirector", "Partner")
    def read_mapping(mapping_id):
        row = find("mappings", mapping_id)
        return object_response(serialize.mapping(row))

    @app.route("/account-mappings/<mapping_id>/respond", methods=["POST"])
    @endpoint("Partner", "ChannelOpsAnalyst")
    def respond_mapping(mapping_id):
        mapping = find("mappings", mapping_id)
        acting_partner_scope(mapping["partner_id"])
        body = v.body()
        action = v.req_enum(body, "action", ("COUNTER", "ACCEPT", "TERMINATE"))
        status = mapping["mapping_status"]
        role = g.role
        if action == "COUNTER":
            effective_from = v.req_instant(body, "effective_from")
            effective_until = v.req_instant(body, "effective_until")
            v.interval(effective_from, effective_until, "effective_from", "effective_until")
            expected = "PROPOSED" if role == "Partner" else "COUNTERED"
            if status != expected:
                raise invalid_state(
                    "A %s cannot counter an agreement in %s." % (role, status))
            if mapping["counter_round"] >= MAX_COUNTER_ROUNDS:
                raise invalid_state("The counter round limit has been reached.")
            candidate = dict(mapping)
            candidate["effective_from"] = effective_from
            candidate["effective_until"] = effective_until
            clash = calc.mapping_window_conflict(
                candidate, ("PROPOSED", "COUNTERED", "ACTIVE"), MAPPING_COOLDOWN_DAYS)
            if clash is not None:
                raise ApiError("ERR_MAPPING_WINDOW_CONFLICT",
                               "The countered window collides with an existing agreement.")
            mapping["effective_from"] = effective_from
            mapping["effective_until"] = effective_until
            mapping["counter_round"] = mapping["counter_round"] + 1
            mapping["mapping_status"] = "COUNTERED" if role == "Partner" else "PROPOSED"
            store.touch(mapping)
        elif action == "ACCEPT":
            expected = "PROPOSED" if role == "Partner" else "COUNTERED"
            if status != expected:
                raise invalid_state(
                    "A %s cannot accept an agreement in %s." % (role, status))
            partner = store.get("partners", mapping["partner_id"])
            if partner is not None:
                check_no_overdue_audit(partner)
            clash = calc.mapping_window_conflict(
                mapping, ("ACTIVE",), MAPPING_COOLDOWN_DAYS)
            if clash is not None:
                raise ApiError("ERR_MAPPING_WINDOW_CONFLICT",
                               "The stored window collides with an active agreement.")
            mapping["mapping_status"] = "ACTIVE"
            mapping["activated_at"] = store.now()
            store.touch(mapping)
        else:
            reason = v.req_string(body, "terminated_reason")
            if role != "ChannelOpsAnalyst" or status not in ("ACTIVE", "PROPOSED"):
                raise invalid_state(
                    "A %s cannot terminate an agreement in %s." % (role, status))
            mapping["mapping_status"] = "TERMINATED"
            mapping["closure_reason"] = reason
            store.touch(mapping)
        return object_response(serialize.mapping(mapping))
