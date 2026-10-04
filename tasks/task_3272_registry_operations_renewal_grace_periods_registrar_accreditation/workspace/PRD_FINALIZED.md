# Registry Operations API — Product Requirements Document

## 1. Introduction

Operating a generic top-level domain is, at its core, an exercise in regulated trust. A registry holds the authoritative database of second-level domain registrations, runs the resolution infrastructure the world queries, and coordinates a federation of independently operated registrars who sell registrations to the public. That coordination is not casual: every registrar must pass technical evaluation and demonstrate financial standing before it may transact, every wholesale price change is constrained by contractual caps and advance-notice obligations, and every domain travels a precisely timed lifecycle — registration, auto-renew grace, redemption grace, pending delete — where the fee charged and the reversibility of the operation depend on exactly where the name sits on that timeline.

This document specifies the Registry Operations API, the system of record for registrar accreditation, wholesale price schedules, the domain lifecycle, inter-registrar transfers with authorization codes and dispute adjudication, security locks, abuse handling, court-order compliance, and the invoicing and ledger that tie money movement to every billable event. Because so much of the domain lifecycle is driven by the passage of time — grace windows lapsing, transfer auto-acknowledgement, deferred court orders, price schedules taking effect — the API exposes an explicit logical clock that test harnesses and operators can advance deterministically. Every rule in this document, from the 80-point technical-test threshold for accreditation to the 180-day price-increase notice, is part of the contract implementers must honor.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, declaring the operational capacity. The system recognizes four roles, spelled exactly as follows: `RegistryAdmin`, `RegistrarOperator`, `RegistryFinance`, and `AbuseAnalyst`. A request missing either header, or presenting a role outside this enumeration, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose authenticated role is not permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

Role identity is interpreted as follows. When `X-User-Role` is `RegistrarOperator`, `X-User-ID` is the `id` of the acting `Registrar`; ownership checks on any resource that references a `Registrar` — for example, transfer ack/nack where the acting registrar must be the losing party, or transfer completion where the acting registrar must be the gaining party — compare the resource's registrar foreign-key field to `X-User-ID`. When `X-User-Role` is `RegistryAdmin`, `RegistryFinance`, or `AbuseAnalyst`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit purposes but does not compare it to any entity's `id`.

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a unique, machine-readable string that identifies the specific error.
- The `message` provides a human-readable explanation of what went wrong.

### 2.3. Pagination

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter says how many items to skip and defaults to 0. Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. Paginated list responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties

All primary resources — `Registrar`, `PriceSchedule`, `Domain`, `Nameserver`, `Transfer`, `Invoice`, `AbuseReport`, and `CourtOrder` — carry a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits, recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by exactly one on every mutation, and underpins optimistic concurrency control. The counter is strictly per-record: each entity instance has its own `version` sequence, and `version` values of different records — even of the same resource type — are never numerically comparable to one another.

Two resource types are intentionally lighter. `DomainNameserverLink` and `RegistrarAccreditationNotice` carry only `id` and `created_at`; both `updated_at` and `version` are absent from them, and they are never the target of OCC checks. Any mutation that cascades into an entity — a state transition, a recomputed field, a foreign-key reassignment — refreshes that entity's `updated_at` and increments its `version`, even when the mutation was triggered indirectly by an operation on another resource.

### 2.5. The Logical Clock and Time-Driven Transitions

Registry behavior depends on time, so the system runs on an explicit **logical clock** rather than wall-clock time. Before any operator touches it, the logical clock starts at exactly 2026-09-01T00:00:00Z and must never fall back to wall-clock time. A `RegistryAdmin` advances it through an admin-only test-driving capability that accepts a `to_iso8601` instant and sets the clock forward; the response reports the new `current_utc`.

Advancing the clock fires every time-driven transition whose moment has arrived, in one sweep: domains whose `expires_on` has passed auto-renew into `AUTO_RENEW_GRACE`; auto-renew grace lapses drop domains into `REDEMPTION_GRACE`; un-restored names enter `PENDING_DELETE` and are later purged to `DELETED`; unanswered transfer requests auto-acknowledge once five days have elapsed; lodged court orders with deferred enforcement take effect after 48 hours; and proposed price schedules become `EFFECTIVE` when the clock reaches their `effective_on`. Each of these transitions carries its own cascades, described in §3. Within a single sweep, transitions of the same kind are applied in a deterministic order: domains, transfers, and court orders are processed in ascending `created_at` order with `id` as the tiebreaker when two records share a `created_at`, and price schedules are processed in ascending `effective_on` order with `id` as the tiebreaker.

### 2.6. Monetary Values, Invoicing, and the Registrar Ledger

All money in the system is expressed as integer cents — there are no fractional-cent amounts anywhere. Where a computation produces a fraction of a cent (proration of an annual fee, the premium surcharge, a price-cap ceiling), the result is rounded half-up to the nearest whole cent, and rounding is applied exactly once at the end of the computation with no intermediate rounding.

Every billable event mints an `Invoice` recording its `kind` — one of `CREATE`, `RENEW`, `AUTO_RENEW`, `RESTORE`, `TRANSFER`, or `ACCREDITATION` — together with `base_cents` (the wholesale amount before any surcharge), `premium_surcharge_cents`, and `total_cents`, which is always the sum of the other two. Premium names — domains created with the `premium` flag set — carry a ten-percent registry service surcharge on every lifecycle invoice: `premium_surcharge_cents` is ten percent of the base, rounded half-up to whole cents. Non-premium domains and all accreditation invoices carry a surcharge of zero. Every invoice references the `price_schedule_id` of the schedule in force at the moment it was minted, except accreditation invoices, which are contractual rather than schedule-priced and leave both `price_schedule_id` and `domain_id` null. An invoice's `status` is `OPEN` until it is voided, at which point it becomes `VOIDED`.

Each invoice is mirrored into the debited registrar's account as a `LedgerEntry` with a signed `amount_cents`: credits are positive and debits are negative. A minted invoice posts a `DEBIT` entry of negative `total_cents`; a voided invoice posts a compensating `VOID_CREDIT` entry of positive `total_cents` and flips the invoice to `VOIDED`. Registry finance staff may credit an account directly with a `TOP_UP` entry, and registrar termination may produce a `WRITE_OFF` credit; the `entry_type` of every ledger entry is one of `TOP_UP`, `DEBIT`, `VOID_CREDIT`, or `WRITE_OFF`. Top-ups and write-offs reference no invoice, so their `invoice_id` is null.

### 2.7. Wholesale Pricing Governance

Wholesale prices are published as `PriceSchedule` records, each carrying four per-action fees — `create_fee_cents`, `renew_fee_cents`, `restore_fee_cents`, and `transfer_fee_cents`, all non-negative integer cents — plus an `effective_on` instant that must be strictly in the future at submission time, and an optional `supersedes_schedule_id` naming the schedule it replaces (null for the very first schedule). A schedule is born `PROPOSED`, becomes `EFFECTIVE` when the logical clock reaches `effective_on`, and becomes `SUPERSEDED` when a later schedule takes effect; the previously `EFFECTIVE` schedule flips to `SUPERSEDED` at the same instant. The submission timestamp is recorded as `announced_at` and drives the notice rule below.

Two contractual guardrails apply at submission, enforced in this order relative to each other after all structural checks: the annual price cap and the increase-notice period. For the cap, the baseline is the fee set of the schedule that was `EFFECTIVE` on January 1 of the calendar year containing the new schedule's `effective_on`; if no schedule was effective yet at that instant, the first schedule ever proposed is the baseline. For each of the four fees, the proposed fee may not exceed the corresponding baseline fee multiplied by 1.10, with the ceiling rounded half-up to whole cents; a violation is rejected with `ERR_PRICE_CAP_EXCEEDED`. Multiple increases within the same calendar year compound against that same January-1 baseline, not against each other. For the notice, the gap between `effective_on` and `announced_at` must be at least 180 days; a shorter gap is rejected with `ERR_PRICE_NOTICE_TOO_SHORT`. This notice requirement applies to every schedule submission, including the very first schedule the registry ever announces.

Effectiveness is also gated per registrar by a version pin captured at accreditation. Every registrar stores an `accredited_version` — the registrar's own `version` snapshot taken at the moment of accreditation. A newly effective schedule does not apply to invoices minted for a registrar whose `accredited_version` is greater than or equal to the schedule's `version`; it takes effect for that registrar's invoices only once the registrar's `accredited_version` is less than the schedule's `version`. This comparison between a registrar's `accredited_version` and a schedule's `version` is the sole defined cross-entity use of `version` values, and exists only to evaluate this pinning rule. When a schedule becomes `EFFECTIVE`, the registry emits a `RegistrarAccreditationNotice` of kind `PRICE_INCREASE_EFFECTIVE` to every registrar in `ACTIVE` or `SUSPENDED` status whose `accredited_version` is less than the new schedule's `version`; at submission time, a `PRICE_INCREASE_ANNOUNCED` notice goes to every registrar in `ACTIVE` or `SUSPENDED` status. Each notice records its `registrar_id`, `price_schedule_id`, `notice_kind`, and the logical-clock `sent_at` timestamp.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and no others take a version field. Patching a registrar's mutable fields requires a non-optional `expected_registrar_version` carrying the client's last observed `version` of that registrar; if the registrar's current `version` has advanced — for instance, another writer has flipped `credit_hold` since the client read the record — the patch is rejected with `ERR_STALE_VERSION` (HTTP 412). Engaging or releasing a lock on a domain requires a non-optional `expected_domain_version` carrying the client's last observed `version` of that domain; a mismatch against the domain's current `version` — for instance, after a cascaded lifecycle mutation bumped it — is likewise rejected with `ERR_STALE_VERSION` (HTTP 412). A successful OCC-guarded mutation increments the parent entity's `version` by one.

### 2.9. Validation Ordering and Nested Resource Retrieval

Incoming requests are validated in a fixed priority order, and the first failing check determines the error returned. Authentication comes first (missing or invalid headers, `ERR_UNAUTHENTICATED`), followed by role authorization (`ERR_FORBIDDEN`), then path-id existence checked left-to-right — registrar before domain before transfer, and so on along the URL — with the first missing identifier yielding `ERR_NOT_FOUND`. Only then does the system evaluate whether the target resource is in a state from which the requested transition exists (`ERR_INVALID_STATE`), followed by the business-safety checks (suspension holds and locks), the temporal-window checks, referential-integrity checks (registrar activity, nameserver linkage), constraint checks (uniqueness, pending-transfer exclusivity, authorization-code match), and finally the fiscal checks (credit holds, price cap, notice period, accreditation gates).

For nested paths, existence validation proceeds strictly left-to-right: a request naming a non-existent registrar in the first path segment fails with `ERR_NOT_FOUND` before the system even considers whether the domain or transfer named later in the path exists. A malformed body or a missing required input field is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

## 3. Business Logic & Workflows

### 3.1. Registrar Accreditation: Application, Testing, and Standing

A `RegistryAdmin` onboards a prospective registrar by creating an applicant record carrying the IANA-assigned `iana_number` (unique across all registrars, an integer from 1 to 99999; a duplicate is rejected with `ERR_DUPLICATE_IANA_NUMBER`), the applicant's `legal_name`, three fee fields — the non-refundable `application_fee_cents`, the pre-proration `annual_fee_cents`, and the `escrow_deposit_cents` held against financial standing (each zero or greater) — plus the results of the applicant's operational test and evaluation: a `technical_test_score` from 0 to 100, and a `financial_statement_verified` boolean recording whether audited financial statements passed registry verification. An optional `credit_hold` flag (defaulting to false) lets finance mark the account. A new applicant starts in `PENDING_TESTS`, with `accredited_on` null and `accredited_version` unset until accreditation actually happens.

Accreditation is a deliberate `RegistryAdmin` act, and it enforces two gates: the `technical_test_score` must be at least 80 (otherwise `ERR_TECHNICAL_TEST_FAILED`), and `financial_statement_verified` must be true (otherwise `ERR_FINANCIAL_STANDING_UNVERIFIED`). On success the registrar moves from `PENDING_TESTS` to `ACTIVE`. The transition stamps `accredited_on` with the current logical time and captures `accredited_version` as the registrar's `version` value *before* the transition itself increments it — this snapshot is the pin that later gates price-increase effectiveness per §2.7. The `annual_fee_mode` is set to `PROVISIONAL` and the all-in accreditation cost is computed on that basis: the prorated annual fee is the `annual_fee_cents` multiplied by the number of remaining days in the calendar year and divided by the number of days in that year — 366 in a leap year, 365 otherwise — where "remaining days" counts from `accredited_on` through December 31 of the accreditation year, inclusive on both ends, and the result is rounded half-up to whole cents exactly once at the end, after the multiplication, with no intermediate rounding. The `all_in_cost_cents` is then the sum of `application_fee_cents`, that prorated annual amount, and `escrow_deposit_cents`. Accreditation also mints an `ACCREDITATION` invoice on the same terms — base equal to `all_in_cost_cents`, no premium surcharge, no price schedule or domain attached — and posts a `DEBIT` ledger entry against the registrar for the invoice total.

Suspension and reinstatement form the compliance loop. Suspending an `ACTIVE` registrar moves it to `SUSPENDED`; from that moment the registrar fails the active-registrar precondition on domain creation, renewal, restore, and transfer requests, surfacing as `ERR_REGISTRAR_NOT_ACTIVE` on those operations. Reinstating a `SUSPENDED` registrar returns it to `ACTIVE` and recomputes the all-in cost under the `AUDIT` basis: `annual_fee_mode` becomes `AUDIT`, and `all_in_cost_cents` now reflects the full `annual_fee_cents` at face value with no proration — for the same fee fields this yields a strictly larger figure than the provisional basis whenever the accreditation year was partial. Either an `ACTIVE` or a `SUSPENDED` registrar may be terminated, but only when it sponsors no live domain: if any domain under that registrar is `ACTIVE`, in `AUTO_RENEW_GRACE`, in `REDEMPTION_GRACE`, or `TRANSFERRING`, termination is rejected with `ERR_REGISTRAR_HAS_LIVE_DOMAINS`. Termination is final (`TERMINATED`) and credits the `escrow_deposit_cents` back as a `WRITE_OFF` ledger entry when the deposit is positive.

A registrar's day-to-day account is visible through its ledger: `RegistryFinance` tops the account up by crediting a positive `amount_cents` as a `TOP_UP` entry, and the full entry history — `TOP_UP`, `DEBIT`, `VOID_CREDIT`, `WRITE_OFF` — is listable per registrar or filterable across the registry by `registrar_id` or `invoice_id`. The mutable-field patch mentioned in §2.8 exists so a `RegistryAdmin` can correct `legal_name` or flip `credit_hold`; a registrar with `credit_hold` set is blocked from every billable mutation — new domain creates, renewals, restores, and transfer requests — with `ERR_REGISTRAR_CREDIT_HOLD`.

### 3.2. Registering a Domain and the Registration Term

A `RegistrarOperator` registers a second-level domain by supplying its `name`, the sponsoring `registrar_id`, an initial `years` term, and an optional `premium` flag (defaulting to false). The `name` must be unique among all non-`DELETED` domains — a clash is rejected with `ERR_DOMAIN_NAME_TAKEN` — and must be a lowercase label of letters, digits, and hyphens between 1 and 63 characters with no leading or trailing hyphen. The initial term is at least 1 and at most 10 years. The sponsoring registrar must be `ACTIVE` (`ERR_REGISTRAR_NOT_ACTIVE` otherwise) and free of a credit hold. The operator's own identity is bound to the sponsoring registrar, so a `RegistrarOperator` may only act on domains their own registrar sponsors.

A successful registration creates the domain in `ACTIVE` status with `expires_on` set to the current logical time plus the requested years, `grace_deadline` set to forty-five days past that expiry, `lock_status` and `suspension_status` both `NONE`, `registry_lock_token_hash` and `auto_renewed_on` and `delete_scheduled_on` all null. It also mints a `CREATE` invoice whose base is the effective schedule's `create_fee_cents` multiplied by the number of years — plus the ten-percent premium surcharge when the name is premium — and debits the sponsoring registrar's ledger. When a name is eventually purged from `DELETED`, the uniqueness constraint no longer sees it, so the same `name` may be registered again by anyone.

Domains are listed with optional filters on `registrar_id`, `status`, and `name`; the same records are reachable in reverse by listing the domains a given registrar sponsors.

### 3.3. Renewal, Grace Periods, and Deletion

While a domain is `ACTIVE`, its sponsoring `RegistrarOperator` may renew it explicitly by supplying a `years` extension of at least one year, provided the current logical time is at or before the domain's `grace_deadline` — attempting to renew after that boundary is rejected with `ERR_GRACE_WINDOW_CLOSED`, and this temporal check is reported for an `ACTIVE` domain whenever the clock is past the deadline, even if the domain no longer qualifies for renewal for other reasons — and provided the extension does not push the domain's total term beyond ten years beyond its current `expires_on`. A domain under suspension cannot be renewed: any renewal attempt while `suspension_status` is `HOLD` fails with `ERR_DOMAIN_SUSPENDED`, and the same hold blocks registrar-initiated deletes, restores, and transfer requests. The sponsoring registrar must also be `ACTIVE` and free of credit hold. A successful explicit renewal extends `expires_on` by the requested years, recomputes `grace_deadline` as forty-five days past the new expiry, and mints a `RENEW` invoice whose base is the effective schedule's `renew_fee_cents` multiplied by the requested years.

If the logical clock passes `expires_on` while the domain is still `ACTIVE`, the registry itself renews the name for one year: the domain enters `AUTO_RENEW_GRACE`, `auto_renewed_on` is stamped with the old `expires_on`, `expires_on` advances by one year, `grace_deadline` is recomputed from the new expiry, and an `AUTO_RENEW` invoice is minted at the renewal fee for a single year from the schedule effective at the auto-renew instant. From `AUTO_RENEW_GRACE` the registrar has two exits. An explicit renewal moves the domain back to `ACTIVE`, clears `auto_renewed_on` to null, extends `expires_on` by the requested years, and mints a normal `RENEW` invoice. Alternatively — either because the registrar explicitly deletes the name during the grace window or because the logical clock passes forty-five days past `auto_renewed_on` without action — the domain falls into `REDEMPTION_GRACE`, and the auto-renew is unwound: the outstanding `AUTO_RENEW` invoice is voided, a `VOID_CREDIT` ledger entry repays the registrar the full invoice total, and `expires_on` reverts by one year.

A registrar may also delete an `ACTIVE` domain outright, dropping it straight into `REDEMPTION_GRACE` with no invoicing side effects; that path requires the suspension status to be `NONE`. From `REDEMPTION_GRACE`, the name can be restored within thirty days of redemption-grace entry — later attempts fail with `ERR_REDEMPTION_WINDOW_CLOSED`. A restore moves the domain back to `ACTIVE`, extends `expires_on` by one year, recomputes the grace deadline, clears `auto_renewed_on`, and mints a `RESTORE` invoice whose base is the effective schedule's `renew_fee_cents` plus its `restore_fee_cents`. If thirty days pass with no restore, the domain enters `PENDING_DELETE` and `delete_scheduled_on` is set to the date thirty-five days after redemption entry; five days later — that is, once the clock passes thirty-five days past redemption entry — the name is purged to `DELETED`, its uniqueness constraint lapses, and the label becomes available for fresh registration.

The effective schedule used by every lifecycle invoice is the `PriceSchedule` whose status is `EFFECTIVE` at the invoice-minting instant — the one with the greatest `effective_on` at or before that instant among effective rows — subject to the per-registrar version pinning of §2.7.

### 3.4. Registry Locks, Nameservers, and Resolution Capacity

Security locks form an independent dimension on every domain. A `RegistrarOperator` or `RegistryAdmin` may engage or release a lock by submitting a `lock_action` — one of `CLIENT_LOCK` or `REGISTRY_LOCK` to engage the corresponding lock, or `NONE` to release any engaged lock — together with the OCC-guarded `expected_domain_version`; engaging `REGISTRY_LOCK` additionally requires a `lock_token` passphrase whose hash is stored as `registry_lock_token_hash` — null whenever no registry lock is engaged, and cleared to null again when the lock is released via `lock_action` `NONE`. `lock_status` is one of `NONE`, `CLIENT_LOCK`, or `REGISTRY_LOCK`, and any value other than `NONE` blocks new transfer requests and registrar-initiated deletes with `ERR_DOMAIN_LOCKED`. Suspension is the orthogonal legal dimension, recorded in `suspension_status` as `NONE` or `HOLD`, and is driven by abuse resolution and court orders rather than by the lock endpoint.

Authoritative nameservers are registered by a `RegistryAdmin` with a unique `hostname`, a list of one or more glue `ip_addresses` (v4 or v6 strings), and a provisioned `capacity_qps` in queries per second. Every individual nameserver must provision at least 2,000 queries per second; anything less is rejected with `ERR_CAPACITY_BELOW_MINIMUM`. A `RegistrarOperator` links a nameserver to a domain they sponsor by submitting the `nameserver_id`; the resulting `DomainNameserverLink` records the `domain_id` and `nameserver_id` pair, and links are listable per domain or filterable globally by `domain_id` or `nameserver_id`. A nameserver still referenced by any non-`DELETED` domain cannot be deleted — the attempt fails with `ERR_NAMESERVER_IN_USE`.

The registry's resolution-infrastructure commitment is observable through a capacity summary: `provisioned_qps` is the sum of `capacity_qps` across all nameservers (nameservers are never soft-deleted, so the sum covers every row), `commitment_qps` is the contracted commitment of 8,000 queries per second, `utilization_ratio` is the exact unrounded decimal ratio of provisioned to committed capacity, and the reported `status` is `OK` when the ratio is at least 1.0 and `BELOW_COMMITMENT` otherwise.

### 3.5. Inter-Registrar Transfers: Authorization, Acknowledgement, and Disputes

A transfer begins when the gaining registrar's `RegistrarOperator` requests it with a payload naming the `domain_id` and their own `to_registrar_id`. The domain must be `ACTIVE`, unsuspended, and unlocked — a `CLIENT_LOCK` or `REGISTRY_LOCK` fails with `ERR_DOMAIN_LOCKED` — and must have been registered for at least sixty days, meaning the current logical time is at or past `created_at` plus sixty days (younger names are rejected with `ERR_TRANSFER_WINDOW_CLOSED`). Only one transfer per domain may be open at a time: if another transfer for the domain is still `REQUESTED`, the request is rejected with `ERR_TRANSFER_ALREADY_PENDING`. The gaining registrar must be `ACTIVE` and free of credit hold.

A successful request flips the domain to `TRANSFERRING` and creates the transfer record in `REQUESTED` status with `from_registrar_id` copied from the domain's current sponsoring registrar, `requested_at` stamped from the logical clock, and `auth_code_expires_at` set to fourteen days after the request. The registry issues a plaintext `auth_code` with the transfer; its hash is stored as `auth_code_hash`, and the plaintext appears **only** in the creation response — no later retrieval ever exposes it. Transfers are listable with filters on `domain_id`, `from_registrar_id`, `to_registrar_id`, and `status`.

The losing registrar then decides. Acknowledging requires submitting the `auth_code`: the acting registrar must be the `from_registrar_id` party (anyone else gets `ERR_NOT_TRANSFER_PARTY`, HTTP 403), the clock must be at or before `auth_code_expires_at` (later attempts fail with `ERR_AUTH_CODE_EXPIRED`), and the submitted code must match the stored hash (a mismatch fails with `ERR_AUTH_CODE_INVALID`). These party, expiry, and code checks are evaluated before the transfer's status gate, so they are reported even when the transfer has already left `REQUESTED` status (for instance, when the clock passing `auth_code_expires_at` has already cascaded the transfer to `AUTO_ACKED`). Acknowledgement moves the transfer to `ACKED`. Refusal — a nack by the same losing party — moves it to `NACKED` and returns the domain to `ACTIVE` under the original registrar with no invoice. If five days pass after `requested_at` with neither an ack nor a nack, the system auto-acknowledges the transfer into `AUTO_ACKED`.

Completion is the gaining registrar's act on an `ACKED` or `AUTO_ACKED` transfer — again, the acting registrar must be the `to_registrar_id` party. Completion moves the transfer to `COMPLETED`, switches the domain's `registrar_id` to the gaining registrar and returns the domain to `ACTIVE`, extends `expires_on` by one year, recomputes `grace_deadline`, and mints a `TRANSFER` invoice against the *gaining* registrar at the effective schedule's `transfer_fee_cents` — that fee funds the mandatory one-year extension. Whether reached through an explicit ack or the auto-ack path, the completion side effects are identical.

A completed transfer can still be contested. The losing registrar may dispute it within six months of completion by submitting a `dispute_reason`; a later dispute is rejected with `ERR_DISPUTE_WINDOW_CLOSED`. Disputing moves the transfer to `DISPUTED` and freezes the domain: any new transfer request for it is rejected with `ERR_TRANSFER_DISPUTED`. Adjudication belongs to the `RegistryAdmin`, who either reverses or upholds. Reversal moves the transfer to `REVERSED`, reverts the domain's `registrar_id` to the original losing registrar, unwinds the one-year extension from `expires_on`, recomputes the grace deadline, voids the `TRANSFER` invoice, and posts a `VOID_CREDIT` repaying the gaining registrar. If the admin instead submits the adjudication with `uphold` set to true, the transfer cycles back to `COMPLETED`: the domain stays with the gaining registrar, the extension stands, and no money moves.

### 3.6. Abuse Reports and Court Orders

An `AbuseAnalyst` (or a `RegistryAdmin`) files an abuse report against a domain by supplying the `domain_id`, a `reporter_contact` reference, a `category` of `PHISHING`, `MALWARE`, `SPAM`, or `OTHER`, and free-text `detail`. The report is born `FILED`. An `AbuseAnalyst` then triages it: reviewing moves it to `UNDER_REVIEW`, requeueing cycles an under-review report back to `FILED`, and resolving an under-review report takes an `action` of either `ACTIONED` or `DISMISSED`, both terminal. Resolving as `ACTIONED` is the enforcement path — it sets the domain's `suspension_status` to `HOLD`, which immediately blocks renewals, deletes, restores, and new transfer requests on that name with `ERR_DOMAIN_SUSPENDED`. Reports are listable with `domain_id` and `status` filters.

Court orders follow their own track. A `RegistryAdmin` lodges an order with a unique `case_reference` (a duplicate is rejected with `ERR_DUPLICATE_CASE_REFERENCE`), the `domain_id` named in the order, an `action` of `SUSPEND`, `UNSUSPEND`, or `TRANSFER_TO_REGISTRY`, and an `effective_immediately` flag. The order is lodged in `LODGED` status; when `effective_immediately` is true it is enforced at lodge time, otherwise enforcement fires once the logical clock passes forty-eight hours after lodging. Enforcement effects depend on the action: `SUSPEND` places the domain's `suspension_status` on `HOLD`; `UNSUSPEND` lifts it back to `NONE`; `TRANSFER_TO_REGISTRY` strips the domain from its registrar by nulling `registrar_id`, places it on `HOLD`, and force-nacks any in-flight transfer for the domain — a transfer in `REQUESTED`, `ACKED`, or `AUTO_ACKED` becomes `NACKED`. Once enforced, an order's `status` is `ENFORCED` and final. Orders are listable with `domain_id` and `status` filters.

### 3.7. Announcing a Price Increase

When a `RegistryAdmin` announces a new wholesale schedule, the submission names the four fees, the `effective_on` instant, and optionally the `supersedes_schedule_id` of the schedule being replaced. The cap and notice rules of §2.7 are enforced at this moment — not at effectiveness — so a schedule that breaches the January-1 baseline by more than ten percent (`ERR_PRICE_CAP_EXCEEDED`) or gives registrars less than 180 days of warning (`ERR_PRICE_NOTICE_TOO_SHORT`) never enters the system at all. A schedule that passes both gates is stored as `PROPOSED`, and the registry immediately emits a `PRICE_INCREASE_ANNOUNCED` notice to every registrar in `ACTIVE` or `SUSPENDED` status, recording the announced `price_schedule_id` and the logical-clock `sent_at` on each notice.

When the logical clock reaches a proposed schedule's `effective_on`, the schedule becomes `EFFECTIVE`, the schedule it replaces becomes `SUPERSEDED`, and the registry emits `PRICE_INCREASE_EFFECTIVE` notices — but only to `ACTIVE` or `SUSPENDED` registrars whose `accredited_version` is less than the new schedule's `version`. A registrar whose accreditation snapshot pins them at or beyond the schedule's version is neither notified nor billed under the new fees until that pin condition clears. Schedules are listable with `status` and `supersedes_schedule_id` filters; notices are listable per registrar, or globally with `registrar_id` and `price_schedule_id` filters.

Invoices, finally, are queryable across the registry with filters on `registrar_id`, `domain_id`, `kind`, `status`, and `price_schedule_id`, giving finance and registrars a complete audit trail from every billable event back to the schedule that priced it.

## 4. Endpoint Definitions

All endpoints are mounted under the `/registry` prefix. Operations that create a new resource — a registrar applicant, a price schedule, a domain, a nameserver, a domain-nameserver link, a transfer, a ledger top-up entry, an abuse report, or a court order — return `201 Created`. Operations that modify an existing resource in place (accredit, suspend, reinstate, terminate, renew, delete, restore, lock, ack, nack, complete, dispute, reverse, review, requeue, resolve, patch, clock advance) return `200 OK`. The nameserver deletion endpoint returns `204 No Content` with no response body.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/registry/_clock/set_current_utc` | Advance the logical clock | RegistryAdmin |
| POST | `/registry/registrars` | Create a registrar applicant in `PENDING_TESTS` | RegistryAdmin |
| GET | `/registry/registrars` | List registrars, optional `status` filter | RegistryAdmin, RegistrarOperator, RegistryFinance, AbuseAnalyst |
| GET | `/registry/registrars/{id}` | Get one registrar | RegistryAdmin, RegistrarOperator, RegistryFinance |
| PATCH | `/registry/registrars/{id}` | Patch mutable registrar fields (OCC-guarded) | RegistryAdmin |
| POST | `/registry/registrars/{id}/accredit` | Accredit a `PENDING_TESTS` registrar | RegistryAdmin |
| POST | `/registry/registrars/{id}/suspend` | Suspend an `ACTIVE` registrar | RegistryAdmin |
| POST | `/registry/registrars/{id}/reinstate` | Reinstate a `SUSPENDED` registrar (AUDIT recompute) | RegistryAdmin |
| POST | `/registry/registrars/{id}/terminate` | Terminate a registrar with no live domains | RegistryAdmin |
| POST | `/registry/registrars/{id}/ledger-topups` | Credit a registrar's ledger account | RegistryFinance |
| GET | `/registry/registrars/{id}/ledger` | List a registrar's ledger entries | RegistryAdmin, RegistryFinance, RegistrarOperator |
| GET | `/registry/registrars/{id}/domains` | List domains sponsored by a registrar | RegistryAdmin, RegistrarOperator, RegistryFinance |
| GET | `/registry/registrars/{id}/accreditation-notices` | List price-increase notices sent to a registrar | RegistryAdmin, RegistrarOperator |
| GET | `/registry/accreditation-notices` | List notices, filterable by `registrar_id` or `price_schedule_id` | RegistryAdmin, RegistrarOperator |
| GET | `/registry/accreditation-notices/{id}` | Get one accreditation notice | RegistryAdmin, RegistrarOperator |
| POST | `/registry/price-schedules` | Announce a new wholesale price schedule | RegistryAdmin |
| GET | `/registry/price-schedules` | List price schedules | RegistryAdmin, RegistrarOperator, RegistryFinance |
| GET | `/registry/price-schedules/{id}` | Get one price schedule | RegistryAdmin, RegistrarOperator, RegistryFinance |
| POST | `/registry/domains` | Register a second-level domain | RegistrarOperator |
| GET | `/registry/domains` | List domains with optional filters | RegistryAdmin, RegistrarOperator, RegistryFinance, AbuseAnalyst |
| GET | `/registry/domains/{id}` | Get one domain | RegistryAdmin, RegistrarOperator, RegistryFinance, AbuseAnalyst |
| POST | `/registry/domains/{id}/renew` | Explicit renewal from `ACTIVE` or `AUTO_RENEW_GRACE` | RegistrarOperator |
| POST | `/registry/domains/{id}/delete` | Registrar-initiated delete into `REDEMPTION_GRACE` | RegistrarOperator |
| POST | `/registry/domains/{id}/restore` | Restore from `REDEMPTION_GRACE` within 30 days | RegistrarOperator |
| POST | `/registry/domains/{id}/lock` | Engage or release a domain lock (OCC-guarded) | RegistrarOperator, RegistryAdmin |
| POST | `/registry/domains/{id}/nameservers` | Link a nameserver to a domain | RegistrarOperator |
| GET | `/registry/domains/{id}/nameservers` | List nameserver links for a domain | RegistryAdmin, RegistrarOperator, AbuseAnalyst |
| POST | `/registry/nameservers` | Register an authoritative nameserver host | RegistryAdmin |
| GET | `/registry/nameservers` | List nameservers | RegistryAdmin, RegistrarOperator |
| GET | `/registry/nameservers/{id}` | Get one nameserver | RegistryAdmin, RegistrarOperator |
| DELETE | `/registry/nameservers/{id}` | Delete an unreferenced nameserver | RegistryAdmin |
| GET | `/registry/domain-nameserver-links` | List links, filterable by `domain_id` or `nameserver_id` | RegistryAdmin, RegistrarOperator, AbuseAnalyst |
| GET | `/registry/domain-nameserver-links/{id}` | Get one domain-nameserver link | RegistryAdmin, RegistrarOperator, AbuseAnalyst |
| POST | `/registry/transfers` | Gaining registrar requests a transfer | RegistrarOperator |
| GET | `/registry/transfers` | List transfers with optional filters | RegistryAdmin, RegistrarOperator |
| GET | `/registry/transfers/{id}` | Get one transfer | RegistryAdmin, RegistrarOperator |
| POST | `/registry/transfers/{id}/ack` | Losing registrar acknowledges with the auth code | RegistrarOperator |
| POST | `/registry/transfers/{id}/nack` | Losing registrar refuses the transfer | RegistrarOperator |
| POST | `/registry/transfers/{id}/complete` | Gaining registrar completes an `ACKED` or `AUTO_ACKED` transfer | RegistrarOperator |
| POST | `/registry/transfers/{id}/dispute` | Losing registrar disputes a `COMPLETED` transfer | RegistrarOperator |
| POST | `/registry/transfers/{id}/reverse` | Registry adjudicates a dispute (reverse or uphold) | RegistryAdmin |
| GET | `/registry/invoices` | List invoices with optional filters | RegistryAdmin, RegistryFinance, RegistrarOperator |
| GET | `/registry/invoices/{id}` | Get one invoice | RegistryAdmin, RegistryFinance, RegistrarOperator |
| GET | `/registry/ledger-entries` | List ledger entries, filterable by `registrar_id` or `invoice_id` | RegistryAdmin, RegistryFinance, RegistrarOperator |
| GET | `/registry/ledger-entries/{id}` | Get one ledger entry | RegistryAdmin, RegistryFinance, RegistrarOperator |
| POST | `/registry/abuse-reports` | File an abuse report against a domain | AbuseAnalyst, RegistryAdmin |
| GET | `/registry/abuse-reports` | List abuse reports with optional filters | AbuseAnalyst, RegistryAdmin |
| GET | `/registry/abuse-reports/{id}` | Get one abuse report | AbuseAnalyst, RegistryAdmin |
| POST | `/registry/abuse-reports/{id}/review` | Move a `FILED` report to `UNDER_REVIEW` | AbuseAnalyst |
| POST | `/registry/abuse-reports/{id}/requeue` | Cycle an `UNDER_REVIEW` report back to `FILED` | AbuseAnalyst |
| POST | `/registry/abuse-reports/{id}/resolve` | Resolve a report as `ACTIONED` or `DISMISSED` | AbuseAnalyst |
| POST | `/registry/court-orders` | Lodge a court order against a domain | RegistryAdmin |
| GET | `/registry/court-orders` | List court orders with optional filters | RegistryAdmin, AbuseAnalyst |
| GET | `/registry/court-orders/{id}` | Get one court order | RegistryAdmin, AbuseAnalyst |
| GET | `/registry/capacity/summary` | Resolution-infrastructure capacity commitment summary | RegistryAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_DOMAIN_SUSPENDED` | 409 |
| `ERR_DOMAIN_LOCKED` | 409 |
| `ERR_TRANSFER_WINDOW_CLOSED` | 409 |
| `ERR_GRACE_WINDOW_CLOSED` | 409 |
| `ERR_REDEMPTION_WINDOW_CLOSED` | 409 |
| `ERR_DISPUTE_WINDOW_CLOSED` | 409 |
| `ERR_AUTH_CODE_EXPIRED` | 409 |
| `ERR_AUTH_CODE_INVALID` | 409 |
| `ERR_NOT_TRANSFER_PARTY` | 403 |
| `ERR_TRANSFER_ALREADY_PENDING` | 409 |
| `ERR_TRANSFER_DISPUTED` | 409 |
| `ERR_REGISTRAR_NOT_ACTIVE` | 409 |
| `ERR_REGISTRAR_CREDIT_HOLD` | 409 |
| `ERR_REGISTRAR_HAS_LIVE_DOMAINS` | 409 |
| `ERR_TECHNICAL_TEST_FAILED` | 409 |
| `ERR_FINANCIAL_STANDING_UNVERIFIED` | 409 |
| `ERR_DUPLICATE_IANA_NUMBER` | 409 |
| `ERR_DOMAIN_NAME_TAKEN` | 409 |
| `ERR_DUPLICATE_CASE_REFERENCE` | 409 |
| `ERR_PRICE_CAP_EXCEEDED` | 409 |
| `ERR_PRICE_NOTICE_TOO_SHORT` | 409 |
| `ERR_NAMESERVER_IN_USE` | 409 |
| `ERR_CAPACITY_BELOW_MINIMUM` | 409 |
