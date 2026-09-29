"""Registration search attempts, patient records, site duplicate metric runs."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, g

from core import (
    ALL_ROLES, METRIC_MIN_SAMPLE_SIZE, SEARCH_ATTEMPT_TTL_MINUTES, authenticate,
    base_entity, created, enforce_site_scope, err, field_date, field_enum,
    field_id, field_int, field_string, get_body, now, ok, ok_list, paginate,
    parse_datetime, query_filter, store, touch,
)
import domain
import scoring
import serializers
from routes_config import active_rule_set

bp = Blueprint("records", __name__)

SEX_VALUES = ["M", "F", "X", "U"]
SSN4_PATTERN = r"^\d{4}$"


# --------------------------------------------------------------------------
# Registration search attempts
# --------------------------------------------------------------------------
@bp.post("/mpi/registration-sites/<site_id>/search-attempts")
def create_search_attempt(site_id):
    authenticate(["SiteRegistrar", "IdentityAnalyst"])
    enforce_site_scope(site_id)
    body = get_body()
    last_name = field_string(body, "searched_last_name", required=True)
    first_name = field_string(body, "searched_first_name")
    dob = field_date(body, "searched_dob")
    sex = field_enum(body, "searched_sex", SEX_VALUES)
    ssn_last4 = field_string(body, "searched_ssn_last4", min_len=4, max_len=4,
                             pattern=SSN4_PATTERN)
    postal_code = field_string(body, "searched_postal_code")
    phone = field_string(body, "searched_phone")

    site = store.sites.get(site_id)
    if site is None:
        raise err("ERR_SITE_NOT_FOUND", "No registration site with id %s" % site_id)
    if site["status"] != "ACTIVE":
        raise err("ERR_SITE_SUSPENDED",
                  "Registration site %s is SUSPENDED and accepts no new search attempts" % site_id)

    virtual = {
        "last_name": last_name,
        "first_name": first_name,
        "dob": dob,
        "ssn_last4": ssn_last4,
        "sex": sex,
        "postal_code": postal_code,
        "phone": phone,
        "biometric_template_hash": None,
        "insurance_member_id": None,
    }

    rule_set = active_rule_set()
    result_count = 0
    top_score = Decimal("0.00")
    top_mrn = None
    blocked = False
    label = None
    if rule_set is not None:
        label = rule_set["version_label"]
        pool = [r for r in store.records.values() if r["identity_state"] == "ACTIVE"]
        scored = []
        for candidate in pool:
            outcome = scoring.score(virtual, scoring.record_attrs(candidate), rule_set, "STRICT")
            scored.append((outcome["match_score"], candidate))
        result_count = sum(1 for s, _ in scored if s >= rule_set["review_threshold"])
        if scored:
            top_score = max(s for s, _ in scored)
            if top_score > Decimal("0.00"):
                ranked = sorted(
                    scored,
                    key=lambda item: (-item[0], item[1]["created_at"], item[1]["mrn"]),
                )
                top_mrn = ranked[0][1]["mrn"]
        blocked = top_score >= rule_set["auto_link_threshold"]

    row = base_entity(with_audit=False)
    row.update({
        "site_id": site_id,
        "searched_last_name": last_name,
        "searched_first_name": first_name,
        "searched_dob": dob,
        "searched_sex": sex,
        "searched_ssn_last4": ssn_last4,
        "searched_postal_code": postal_code,
        "searched_phone": phone,
        "result_count": result_count,
        "top_score": top_score,
        "top_match_record_mrn": top_mrn,
        "blocked_creation": bool(blocked),
        "rule_set_version_label": label,
    })
    store.search_attempts[row["id"]] = row
    return created(serializers.search_attempt(row))


@bp.get("/mpi/registration-sites/<site_id>/search-attempts")
def list_search_attempts(site_id):
    authenticate(ALL_ROLES)
    from core import pagination
    pagination()
    if site_id not in store.sites:
        raise err("ERR_SITE_NOT_FOUND", "No registration site with id %s" % site_id)
    rows = [r for r in store.search_attempts.values() if r["site_id"] == site_id]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    window, page = paginate(rows)
    return ok_list([serializers.search_attempt(r) for r in window], page)


# --------------------------------------------------------------------------
# Patient records
# --------------------------------------------------------------------------
@bp.post("/mpi/patient-records")
def create_record():
    authenticate(["SiteRegistrar", "IdentityAnalyst"])
    body = get_body()
    # rank 3 reads the raw body value before rank 4 validates its shape
    if g.user_role == "SiteRegistrar":
        enforce_site_scope(body.get("site_id"))

    site_id = field_id(body, "site_id", required=True)
    mrn = field_string(body, "mrn", required=True, min_len=1, max_len=20)
    last_name = field_string(body, "last_name", required=True)
    first_name = field_string(body, "first_name", required=True)
    dob = field_date(body, "dob", required=True)
    sex = field_enum(body, "sex", SEX_VALUES, required=True)
    ssn_last4 = field_string(body, "ssn_last4", min_len=4, max_len=4, pattern=SSN4_PATTERN)
    address_line = field_string(body, "address_line")
    postal_code = field_string(body, "postal_code")
    phone = field_string(body, "phone")
    biometric = field_string(body, "biometric_template_hash")
    insurance = field_string(body, "insurance_member_id")
    element_count = field_int(body, "clinical_element_count", minimum=0, default=0)
    origin_id = field_id(body, "origin_search_attempt_id")

    site = store.sites.get(site_id)
    if site is None:                                                    # rank 5
        raise err("ERR_SITE_NOT_FOUND", "No registration site with id %s" % site_id)

    attempt = None
    if origin_id is not None:                                           # rank 7
        attempt = store.search_attempts.get(origin_id)
        if attempt is None:
            raise err("ERR_SEARCH_ATTEMPT_NOT_FOUND",
                      "No registration search attempt with id %s" % origin_id)

    if g.user_role == "SiteRegistrar" and origin_id is None:            # rank 18
        raise err("ERR_SEARCH_ATTEMPT_REQUIRED",
                  "A SiteRegistrar must cite origin_search_attempt_id")

    if site["status"] != "ACTIVE":                                      # rank 24
        raise err("ERR_SITE_SUSPENDED",
                  "Registration site %s is SUSPENDED and accepts no new records" % site_id)

    for existing in store.records.values():                             # rank 39
        if existing["site_id"] == site_id and existing["mrn"] == mrn:
            raise err("ERR_DUPLICATE_MRN",
                      "A patient record with mrn %s already exists at this site" % mrn)

    if attempt is not None:                                             # rank 41
        expiry = parse_datetime(attempt["created_at"]) + timedelta(minutes=SEARCH_ATTEMPT_TTL_MINUTES)
        if now() > expiry:
            raise err("ERR_SEARCH_ATTEMPT_EXPIRED",
                      "The cited registration search attempt is older than 15 minutes")
        if attempt["blocked_creation"]:                                 # rank 46
            raise err("ERR_DUPLICATE_CREATION_BLOCKED",
                      "The cited registration search attempt blocked record creation")

    row = base_entity()
    row.update({
        "site_id": site_id,
        "origin_search_attempt_id": origin_id,
        "mrn": mrn,
        "last_name": last_name,
        "first_name": first_name,
        "dob": dob,
        "sex": sex,
        "ssn_last4": ssn_last4,
        "address_line": address_line,
        "postal_code": postal_code,
        "phone": phone,
        "biometric_template_hash": biometric,
        "insurance_member_id": insurance,
        "clinical_element_count": element_count,
        "identity_state": "ACTIVE",
        "integrity_state": "CLEAR",
        "survivor_record_id": None,
        "enterprise_id": "EID-" + site["site_code"] + "-" + mrn,
    })
    store.records[row["id"]] = row
    return created(serializers.record(row))


@bp.get("/mpi/patient-records/<record_id>")
def get_record(record_id):
    authenticate(ALL_ROLES)
    row = store.records.get(record_id)
    if row is None:
        raise err("ERR_RECORD_NOT_FOUND", "No patient record with id %s" % record_id)
    return ok(serializers.record(row))


@bp.get("/mpi/patient-records")
def list_records():
    authenticate(ALL_ROLES)
    rows = sorted(store.records.values(), key=lambda r: (r["created_at"], r["_seq"]))
    for key in ("site_id", "survivor_record_id", "origin_search_attempt_id",
                "identity_state", "integrity_state", "enterprise_id", "mrn"):
        rows = query_filter(rows, key)
    window, page = paginate(rows)
    return ok_list([serializers.record(r) for r in window], page)


# --------------------------------------------------------------------------
# Site duplicate metric runs
# --------------------------------------------------------------------------
ATTRIBUTION_VARIANTS = ["CREATION_SITE_ATTRIBUTION", "SURVIVOR_SITE_ATTRIBUTION"]


@bp.post("/mpi/registration-sites/<site_id>/duplicate-metric-runs")
def create_metric_run(site_id):
    authenticate(["MpiAdmin", "IdentityAnalyst"])
    body = get_body()
    start = field_date(body, "window_start_date", required=True)
    end = field_date(body, "window_end_date", required=True)
    variant = field_enum(body, "attribution_variant", ATTRIBUTION_VARIANTS, required=True)
    if end < start:
        from core import bad_request
        raise bad_request("window_end_date must not be earlier than window_start_date")

    if site_id not in store.sites:                                      # rank 5
        raise err("ERR_SITE_NOT_FOUND", "No registration site with id %s" % site_id)

    for existing in store.metrics.values():                             # rank 44
        if existing["site_id"] != site_id or existing["attribution_variant"] != variant:
            continue
        # CLOSED date windows: touching boundaries DO collide.
        if existing["window_start_date"] <= end and start <= existing["window_end_date"]:
            raise err("ERR_METRIC_WINDOW_OVERLAP",
                      "The requested window collides with an existing metric run")

    records_created = 0
    for record in store.records.values():
        if record["site_id"] != site_id:
            continue
        if start <= record["created_at"][:10] <= end:
            records_created += 1

    confirmed = 0
    for merge in store.merges.values():
        if merge["state"] not in ("PENDING_PROPAGATION", "COMPLETED"):
            continue
        attributed_id = (
            merge["subsumed_record_id"] if variant == "CREATION_SITE_ATTRIBUTION"
            else merge["survivor_record_id"]
        )
        attributed = store.records.get(attributed_id)
        if attributed is None or attributed["site_id"] != site_id:
            continue
        if start <= attributed["created_at"][:10] <= end:
            confirmed += 1

    rule_set = active_rule_set()
    row = base_entity(with_audit=False)
    row.update({
        "site_id": site_id,
        "window_start_date": start,
        "window_end_date": end,
        "attribution_variant": variant,
        "records_created": records_created,
        "confirmed_duplicates": confirmed,
        "duplicate_rate_bps": scoring.duplicate_rate_bps(confirmed, records_created),
        "sample_size_sufficient": records_created >= METRIC_MIN_SAMPLE_SIZE,
        "rule_set_version_label": rule_set["version_label"] if rule_set else None,
    })
    store.metrics[row["id"]] = row
    return created(serializers.metric(row))


@bp.get("/mpi/registration-sites/<site_id>/duplicate-metric-runs")
def list_metric_runs(site_id):
    authenticate(ALL_ROLES)
    from core import pagination
    pagination()
    if site_id not in store.sites:
        raise err("ERR_SITE_NOT_FOUND", "No registration site with id %s" % site_id)
    rows = [r for r in store.metrics.values() if r["site_id"] == site_id]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    rows = query_filter(rows, "attribution_variant")
    window, page = paginate(rows)
    return ok_list([serializers.metric(r) for r in window], page)
