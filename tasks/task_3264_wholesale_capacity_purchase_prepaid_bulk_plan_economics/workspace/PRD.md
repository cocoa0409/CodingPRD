# Wholesale Capacity Prepaid Plans API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Wholesale Capacity Prepaid Plans API, the platform
layer through which a value-added reseller buys bulk data, voice and messaging capacity from a host network
and resells it as prepaid multi-month plans. The commercial engine underneath the product is a capacity
purchase: the operator negotiates per-unit rates with a host network, commits to a monthly volume of data,
voice and messaging, and then sells that committed volume forward through a catalogue of prepaid plans. Every
sale draws capacity out of the bought pipe, so the operator must always be able to answer, at any instant, how
much of the pipe is already promised and how much is still free to sell. The API is the system of record for
that answer.

The product is deliberately digital-first. There are no retail storefronts to provision service from; a
subscriber buys a term, activates it, and where they wish to keep their existing number, ports it in from a
losing carrier, all through programmatic flows. Physical subscriber identity module cards and embedded
profiles reach customers either directly by shipment or through retail partners who carry state-scoped
inventory, and support is delivered through an outsourced agent pool with explicit self-service deflection
targets. Because money is collected up front for a service that is delivered over three, six or twelve
subsequent months, revenue is recognised progressively across monthly billing cycles; the unearned balance
sits as deferred revenue and converts to earned revenue as cycles roll, with quality-sensitive adjustments
and breakage recognition for terms that end early. The remainder of this document fixes the global contracts
(RBAC, response envelope, pagination, precision, concurrency) and then describes, domain-first, the
workflows that move capacity out of the agreement and into live subscriber service.

All resources in this API are mounted under the `/carriers` prefix.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two mandatory headers: `X-User-ID` names the acting user, and `X-User-Role` names the
capacity in which they act. The API recognises six roles, spelled exactly as follows: `CapacityPlanner`,
`SupportAgent`, `FulfillmentOperator`, `PlatformAdmin`, `Subscriber`, and `RetailPartner`. A request whose
headers are absent, whose `X-User-Role` is not one of those six names, or whose `X-User-ID` fails to resolve
for an entity-backed role is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Even with valid credentials, a
role may only call the operations it is listed for; acting outside that set is rejected with
`ERR_FORBIDDEN_ROLE` (HTTP 403).

The identity semantics of the header differ per role, and this distinction governs resource ownership. When
`X-User-Role` is `Subscriber`, `X-User-ID` is the `id` of the acting `Subscriber`; ownership checks on any
subscriber-scoped resource compare that resource's `subscriber_id` to `X-User-ID`. When `X-User-Role` is
`RetailPartner`, `X-User-ID` is the `id` of the acting `RetailPartner`; ownership checks on a SIM inventory
block compare the block's `retail_partner_id` to `X-User-ID`. A `Subscriber` acting on a row belonging to a
different subscriber, or a `RetailPartner` acting on a block belonging to a different partner, is rejected
with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). The remaining four roles — `CapacityPlanner`, `SupportAgent`,
`FulfillmentOperator`, and `PlatformAdmin` — are opaque operator identities: their `X-User-ID` is an operator
identifier that is not tied to any persisted entity, so the server does not compare it to any entity's `id`.
A `CapacityPlanner` purchases capacity and curates the prepaid catalogue; a `SupportAgent` works the care
queue and activation exceptions; a `FulfillmentOperator` handles SIM media; a `PlatformAdmin` owns the
logical clock.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items
returned, defaulting to 10 when omitted, and may be set no lower than 1 nor higher than 100. The `offset`
parameter gives the number of leading items to skip and defaults to 0. Unless a workflow states otherwise,
list endpoints return records sorted by their creation timestamp in ascending order. Every list response
carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the
response envelope.

### 2.4. The Conserved Megabyte Balance and Cascade Discipline

The platform's central invariant is a balance of megabytes held on each wholesale agreement. Two fields on a
`CapacityAgreement` — `allocated_data_mb`, the sum of the allotments promised to subscribers, and
`remaining_data_mb`, the volume still free to sell — are never adjusted in place. Instead, on every
capacity-allocation event both are recomputed from scratch in a single pass by the balance rule
`wholesale_allocated_data_mb` over the same set of contributing subscribers, and the invariant
`allocated_data_mb` plus `remaining_data_mb` equals `committed_data_mb` holds
after every event while the agreement is in `ACTIVE` or `SUSPENDED`. Because the balance is derived rather
than decremented, a purchase followed by a refund of that same term returns `allocated_data_mb` to exactly its
pre-purchase value. A subscriber whose `allocation_status` is `HELD` counts exactly once toward
`allocated_data_mb`, whether the hold came from an in-flight port reservation or from a term awaiting
activation; a subscriber in `PENDING_PORT` carrying `allocation_status` `HELD` or `NONE` never double-counts,
and every `CHURNED` subscriber contributes nothing.

Operations cascade across the entity graph without further client requests. Closing an agreement sets
`plan_status` to `RETIRED` on every plan it contains. Cancelling a subscriber writes the term to `EXPIRED`,
voids its add-ons, and closes its support cases, and any of those movements that changes the set of
contributing subscribers triggers a fresh recomputation of the agreement's balance. Automatic, system-actored
transitions happen whenever their preconditions are met — an agreement suspends itself once a recompute shows
over-allocation, a plan falls back from `ACTIVE` to `OFFERED` once its last live term leaves the book, a
subscriber still parked in `GRACE` churns at the first cycle roll. Every one of these mutations refreshes the
affected row's `updated_at` and increments its `version`.

### 2.5. Common Resource Properties

Top-level resources in this API share a system-managed identity block. Every `CapacityAgreement`, `Plan`,
`Subscriber`, `PrepaidTerm`, `Activation`, `RetailPartner`, `SimInventory`, `SupportCase`, and `AddOn` carries:

- `id` — a unique, system-generated identifier formatted as a UUID with no type prefix. The server mints it;
  clients never supply it.
- `created_at` — an ISO 8601 timestamp in UTC with three fractional digits (for example
  `2025-05-24T10:30:00.123Z`) recording when the row was first created.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits recording the last mutation.
- `version` — a system-managed integer that starts at 1 and increments by 1 on every modification to the row,
  including modifications performed by derived-field recomputation.

`CycleRecord` is the one exception. It is an immutable record of a billing cycle, so it carries only `id` and
`created_at`; it has no `updated_at` and no `version`, and no endpoint accepts a version expectation against
it. Cycle rows are created for every cycle of a term at the moment the term activates, which is why their
`created_at` values carry no ordering meaning and why ordering within a term is always performed by
`cycle_index`.

### 2.6. Money, Microcents, and Rounding Discipline

The platform keeps two distinct monetary scales and never mixes them. Wholesale costs are expressed in
integer microcents — millionths of a cent — and are never stored as floating point; retail prices, revenue
figures and budgets are expressed in integer cents. Every rounding step in the system is named and pinned, and
no unrounded intermediate is ever summed and rounded afterwards:

- The overage unit rate and the discounted tier rate are each rounded **up** to the next whole microcent at
  the moment the rate is derived, and that rounded rate is what every subsequent multiplication uses.
- Per-cycle earned revenue is rounded **up** to the next whole cent before being frozen on a `CycleRecord`,
  and the running totals that follow are integer sums of already-rounded integers.
- Breakage recognition floors to whole cents, using round-toward-zero on the fractional cent.
- The `congestion_index` and the agreement-level `breakage_rate_ppm` use **round half up** on their single
  division step.
- The roaming base day rate uses **round half up** on its division; every short-term roaming tier is rounded
  **up** to the next whole cent.

### 2.7. Optimistic Concurrency Control

Two write paths in this API are guarded by optimistic concurrency control, and both use the same rejection.
A client that quotes a prepaid term must carry `expected_CapacityAgreement_version` in the request body, and
that value must equal the target agreement's current `version`; a client that cancels a subscriber must carry
`expected_Subscriber_version` in the body, and that value must equal that subscriber's current `version`.
When a client's expected value no longer matches the parent's current `version`, the request is rejected with
`ERR_STALE_VERSION` (HTTP 412), so a writer cannot commit against a parent whose allocation, cycle counters
or status it has not observed. The agreement expectation is mandatory on the term-quoting request; every other
agreement-versioned endpoint treats `expected_CapacityAgreement_version` as optional and performs the identical
check whenever the field is present. The subscriber expectation is mandatory on the subscriber-cancel request.
Two further writes accept an optional expectation of their own row: the partner lifecycle writes take
`expected_RetailPartner_version`, and the inventory return takes `expected_SimInventory_version`, each
carrying the client's last observed `version` of that row, and a mismatch is rejected with the same
`ERR_STALE_VERSION` (HTTP 412). Endpoints not covered by any of these rules take no version field.

### 2.8. The Logical Clock

All time-dependent behaviour in this API — SLA windows, add-on expiry, shipment delivery, breakage ageing —
is evaluated against a single server-side logical clock, never against wall-clock time. That clock reads
exactly `2026-09-01T00:00:00Z` at startup and holds that value until it is moved. Only a `PlatformAdmin` may
move it, through a capability that sets the clock to a supplied `current_utc` instant; the capability returns
the new clock reading. Because the clock is the only source of "now", a wait such as a self-service cooling
window, an SLA due date, or a shipment transit window is deterministic and reproducible.

### 2.9. Nested Resource Retrieval and Identifier Resolution

Requests that address a resource through an identifier resolve that identifier strictly left to right, and
the *first* identifier that does not name an existing resource decides the error returned. A missing
agreement yields `ERR_AGREEMENT_NOT_FOUND`, a missing plan `ERR_PLAN_NOT_FOUND`, a missing subscriber
`ERR_SUBSCRIBER_NOT_FOUND`, a missing prepaid term `ERR_TERM_NOT_FOUND`, a missing activation
`ERR_ACTIVATION_NOT_FOUND`, a missing partner `ERR_PARTNER_NOT_FOUND`, a missing SIM inventory block
`ERR_SIM_INVENTORY_NOT_FOUND`, a missing support case `ERR_CASE_NOT_FOUND`, a missing cycle
`ERR_CYCLE_NOT_FOUND`, and a missing add-on `ERR_ADDON_NOT_FOUND`; all of these are HTTP 404. The same
left-to-right discipline applies to foreign keys carried in a request body: those are checked in the order the
fields appear in the endpoint's input list.

### 2.10. Validation Ordering and Precedence

Validation is a single ordered cascade. When more than one check would fail, the earliest check in the order
below decides the response, and no later check is evaluated. The order is: (1) header authentication, yielding
`ERR_UNAUTHENTICATED`; (2) role authorization, yielding `ERR_FORBIDDEN_ROLE`; (3) resource ownership,
yielding `ERR_NOT_RESOURCE_OWNER`; (4) existence of the identifiers in the path, resolved left to right and
yielding the corresponding `..._NOT_FOUND` error; (5) existence of foreign keys in the body, checked in input
order and yielding the corresponding `..._NOT_FOUND` error; (6) the target row's lifecycle state, yielding
`ERR_INVALID_STATE`; (7) terminality of the target row, yielding `ERR_TERM_ALREADY_TERMINAL`,
`ERR_ACTIVATION_ALREADY_TERMINAL`, `ERR_PORT_ALREADY_TERMINAL`, or `ERR_CYCLE_ALREADY_ROLLED`; (8) suspension
of the agreement for a capacity-allocating action, yielding `ERR_AGREEMENT_SUSPENDED`; (9) closure of the
agreement or retirement of the plan for a sale or extension, yielding `ERR_AGREEMENT_CLOSED` or
`ERR_PLAN_RETIRED`; (10) capacity admission, yielding `ERR_INSUFFICIENT_AGREEMENT_CAPACITY`; (11) the
one-live-term rule, yielding `ERR_DUPLICATE_ACTIVE_TERM`; (12) retail-partner authorization for a state,
yielding `ERR_PARTNER_NOT_AUTHORIZED_FOR_STATE` or `ERR_PARTNER_SUSPENDED`; (13) availability of activatable
SIM media, yielding `ERR_NO_ACTIVATABLE_SIM_MEDIA`; (14) aggregate reservation capacity, yielding
`ERR_SIM_INVENTORY_DEPLETED`; (15) the subscriber-and-term active rule, yielding `ERR_SUBSCRIBER_NOT_ACTIVE`
or `ERR_TERM_NOT_ACTIVE`; (16) an in-flight port on the same losing-carrier account, yielding
`ERR_MSISDN_ALREADY_IN_FLIGHT`; (17) agreement between the submitted port number and the subscriber's own
number, yielding `ERR_MSISDN_MISMATCH`; (18) a client-supplied derived field, yielding `ERR_INVALID_REQUEST`;
(19) plan term and price validity, yielding `ERR_INVALID_PLAN_TERM`; (20) add-on window and allotment
validity, yielding `ERR_INVALID_ADDON_WINDOW`; (21) the self-service cooling window, yielding
`ERR_SELF_SERVICE_TOO_EARLY`; (22) the support budget ceiling, yielding `ERR_SUPPORT_BUDGET_EXCEEDED`;
(23) the manual-escalation SLA gate, yielding `ERR_SLA_NOT_DUE`; (24) retail-channel consistency, yielding
`ERR_RETAIL_CHANNEL_MISMATCH`; (25) an in-flight port blocking churn, yielding `ERR_PORT_IN_FLIGHT`;
(26) refund eligibility of a started term, yielding `ERR_TERM_ALREADY_STARTED`; and (27) add-on window
overlap, yielding `ERR_ADDON_WINDOW_OVERLAP`.

### 2.11. Derived and Computed Fields Are Never Client-Supplied

Several fields exist only as consequences of other data and are therefore read-only: a plan's
`deprioritization_threshold_mb`, a subscriber's `cycle_index`, `cycles_rolled`, `data_used_mb_cycle`,
`deprioritized_this_cycle`, `cycle_deprioritization_days`, `support_seconds_used`, `support_seconds_budget`
and `self_service_deflection_count`, a term's `expires_at`, `deferred_revenue_cents`, `earned_revenue_cents`,
`breakage_days` and `breakage_cents_recognized`, an activation's `provisioned_msisdn` and `accepted_msisdn`, a
block's `reserved_count`, `shipment_channel`, `units_shipped` and `shipment_sla_days`, a case's
`handling_seconds` and `sla_due_at`, and an add-on's `end_at` and `addon_price_cents`. An agreement's
`allocated_data_mb`, `remaining_data_mb`, `congestion_index` and `congestion_active` are likewise derived from
the catalogue and the subscriber book; `congestion_active` may be supplied only at agreement creation, where
it defaults to `false`, and is derived everywhere thereafter. When a client sends a derived field whose value
the server is required to compute — most notably `deprioritization_threshold_mb` on a plan write — the supplied
value is ignored and the derived value is stored; a request that supplies an unknown field, or omits a
required one, is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

## 3. Business Logic & Workflows

### 3.1. Buying Capacity: Agreements, Commitments and the Cost Book

A `CapacityPlanner` opens the commercial relationship by registering a wholesale agreement with a host
network. The registration names the counterparty through `host_network_name`, fixes the two-letter
`state_code` the agreement is priced for, and records the three negotiated unit rates —
`data_rate_microcents_per_mb`, `voice_rate_microcents_per_min`, and `sms_rate_microcents_per_msg` — together
with the monthly volume the operator commits to buying, expressed as `committed_data_mb`,
`committed_voice_minutes`, and `committed_sms_messages`. Each of the three committed volumes must be at least
1. A newly registered agreement sits in `DRAFT` — its `agreement_status` is `DRAFT` — so nothing is sellable yet,
`congestion_active` is `false`,
`congestion_index` is 0, `allocated_data_mb` is 0, and `remaining_data_mb` equals `committed_data_mb` because
none of the bought volume has been promised to anyone.

Activation by a `CapacityPlanner` moves the agreement from `DRAFT` to `ACTIVE`, and it is admitted only when
the three committed volumes are each at least 1 and at least one plan on the agreement is already in status
`OFFERED`. Going live recomputes `allocated_data_mb` and `remaining_data_mb` in a single pass and derives
`congestion_index` at the same instant. From that point the agreement's health is expressed through its
congestion index: the index is the percentage of the bought pipe that sold allotment already occupies, produced
by the `congestion_index` rule as 100 times `allocated_data_mb` divided by `committed_data_mb`, rounded half up to a whole percent and
floored at 0. It reads above 100 whenever the catalogue has been oversold past the contracted volume.
`congestion_active` becomes true the moment the index reaches the congestion trigger index, and false
otherwise; the flag is never taken from a client after creation.

Capacity is admitted up to a sellable ceiling rather than up to the committed volume exactly. A sale is
admitted while the agreement's `allocated_data_mb` plus the allotment being sold would stay at or below
`committed_data_mb` multiplied by `OVERSALE_LIMIT_NUM` divided by `OVERSALE_LIMIT_DEN` — that is, 120 percent
of the committed volume. At the boundary the sale succeeds; one megabyte past the boundary it is rejected with
`ERR_INSUFFICIENT_AGREEMENT_CAPACITY` (HTTP 409). This is why `remaining_data_mb` is legitimately allowed to
go negative: it is recomputed as `committed_data_mb` minus `allocated_data_mb` and never incremented, and when
the sold catalogue exceeds the contracted volume its magnitude is exactly the billable overage volume. If a
recompute — triggered by any capacity-allocation event — finds `allocated_data_mb` strictly exceeding
`committed_data_mb` multiplied by `OVERSALE_LIMIT_NUM` divided by `OVERSALE_LIMIT_DEN`, the agreement suspends
itself into `SUSPENDED` with no client action, pinning `remaining_data_mb` to the negative overshoot so the
overshoot stays readable as billable overage. A `CapacityPlanner` may also suspend an `ACTIVE` agreement
directly. Either way, while an agreement is `SUSPENDED` any action that would allocate capacity against it is
rejected with `ERR_AGREEMENT_SUSPENDED` (HTTP 409), though the terms and subscribers already live on it are
left untouched so existing service continues. A `CapacityPlanner` returns a suspended agreement to service
once `allocated_data_mb` is back at or below `committed_data_mb`, which can happen through a churn, the release
of a held port, or a plan withdrawal; that reinstatement recomputes the balance and the congestion index. Every one of these recomputations is the
same settlement pass — the `settlement_clearing` rule — which derives both balance fields afresh from the
current term set rather than incrementing or decrementing them in place, which is why a purchase followed by
a refund of the same term restores the balance exactly.

The cost book is resolved on demand rather than stored per order. Resolving the purchase commitment for an
agreement — the `wholesale_forward_overage_cost` rule's forward variant, whose trigger is the resolve-purchase
capability — computes, and stores as `resolved_purchase_cost_microcents`, a forward-looking figure that prices
the obligations the operator has taken on. Two legs make it up. The committed-volume leg,
`committed_volume_cost_microcents`, is the data leg plus the variable legs: `committed_voice_minutes`
multiplied by `voice_rate_microcents_per_min`, and `committed_sms_messages` multiplied by
`sms_rate_microcents_per_msg`, added to the data volume cost. The data leg, `data_volume_cost_microcents`, is
the marginal reading of the `wholesale_volume_tier_cost` rule and is reported on its own: the first `TIER1_DATA_MB`, 500,000 megabytes of
`committed_data_mb` are charged at `data_rate_microcents_per_mb`, and every megabyte above that breakpoint is
charged at `tier2_rate`, where `tier2_rate` is `data_rate_microcents_per_mb` multiplied by
`TIER2_MULT_NUM` divided by `TIER2_MULT_DEN` — 92 percent of the headline rate — rounded up to the next whole
microcent. The marginal tier rate is surfaced as `marginal_tier_rate_microcents` and the monthly commitment as
`monthly_committed_cost_microcents`.

The second leg is overage, and it is priced off a derived rate rather than the negotiation rate:
`overage_rate_data` is `data_rate_microcents_per_mb` multiplied by `OVERAGE_MULTIPLIER_NUM` divided by
`OVERAGE_MULTIPLIER_DEN` — 115 percent of the headline rate — rounded up to the next whole microcent. The
forward-looking reading projects how much allotment the current catalogue would consume if it were fully
placed: it sums, over every plan on the agreement whose `plan_status` is `OFFERED` or `ACTIVE`, that plan's
`data_allotment_mb` multiplied by its `contributing_subscribers(p)`, giving `projected_allotment_mb`. The
projected overage `projected_overage_mb` is the excess of that projection over `committed_data_mb`, or 0 when
there is none, and the projected overage cost is that volume multiplied by `overage_rate_data`. The resolved
cost is the committed-volume leg plus the projected-overage cost. Because the projection reads the catalogue
rather than the sold book, a plan that is `OFFERED` but never sold still raises the resolved cost; plans in
`DRAFT` or `RETIRED` contribute nothing. The returned projection also reports the projected overage volume as
`projected_overage_data_mb`.

A summary of the agreement reports the same cost book on an as-incurred basis instead — the
`wholesale_forward_overage_cost` rule's chronological variant — which is what a
`CapacityPlanner`, `SupportAgent`, or `PlatformAdmin` reads when reconciling an invoice. Here the overage leg
counts only volume that has actually rolled: it sums, over every cycle record of this agreement whose
`cycle_status` is `ROLLED`, the excess of that cycle's frozen `cycle_data_used_mb` over the
`data_allotment_mb` of the plan the cycle belongs to — again floored at 0 per cycle — to produce
`rolled_overage_mb`. That volume is priced at the same `overage_rate_data` to give
`as_incurred_overage_cost_microcents`, and the as-incurred total is the committed-volume leg plus it. The two
readings share an identical committed-volume term and differ only in whether they charge projected or rolled
overage, so the as-incurred figure is strictly lower whenever any offered plan has unsold allotment. The same
summary reports the blended tier reading as `retroactive_volume_cost_microcents`: once `committed_data_mb`
strictly exceeds the `TIER1_DATA_MB` breakpoint of 500,000 megabytes, the ceilinged `tier2_rate` applies to the *whole* committed
volume rather than only to the volume above the breakpoint, so the blended figure is lower than the marginal
figure by the 500,000-megabyte band's rate saving and identical to it below the breakpoint. Below the
breakpoint the blended rate is simply `data_rate_microcents_per_mb`. The summary also exposes the live
`allocated_data_mb`, `remaining_data_mb`, `congestion_index` and `congestion_active` alongside a breakage
figure described in §3.6.

Finally, the agreement can be closed, which is terminal. A `CapacityPlanner` may close an `ACTIVE` agreement
only when no plan on it is still in `DRAFT` and no term on any of its plans is in `QUOTED`, `PURCHASED`,
`AWAITING_ACTIVATION`, or `RENEWAL_DUE`; a `SUSPENDED` agreement may be closed with the narrower bar that no
term is in `QUOTED`, `PURCHASED`, or `AWAITING_ACTIVATION`. Closing sets `plan_status` to `RETIRED` on every
plan the agreement contains, and a sale attempted afterwards against the closed agreement is rejected with
`ERR_AGREEMENT_CLOSED` (HTTP 409), while a sale attempted against a retired plan is rejected with
`ERR_PLAN_RETIRED` (HTTP 409).

### 3.2. The Prepaid Catalogue: Plans, Allotments and Deprioritization Thresholds

Against an agreement, a `CapacityPlanner` builds the prepaid catalogue. A plan is registered with the
`agreement_id` it draws from, an operator-facing `plan_code` that must be unique within that agreement, a
`term_months` prepaid length, an `intro_price_cents`, a `renewal_price_cents`, a monthly
`data_allotment_mb`, a monthly `voice_allotment_min` and a monthly `sms_allotment_msg`. The term length must
be one of 3, 6, or 12 months, the intro price must be at least 1 cent, the renewal price must be strictly
greater than the intro price, and the data allotment must be at least 1 megabyte. A plan whose `term_months`
is outside those three values, or whose `renewal_price_cents` is not strictly greater than
`intro_price_cents`, is rejected with `ERR_INVALID_PLAN_TERM` (HTTP 422) — the same code guards a plan offer
made against such a plan. A freshly registered plan sits in `DRAFT` and is not sellable.

Offering a plan is what makes it sellable, moving its `plan_status` from `DRAFT` to `OFFERED`. A
`CapacityPlanner` may offer a plan only while the parent agreement is `DRAFT` or `ACTIVE`, and the offer is
what derives the plan's `deprioritization_threshold_mb`: it is set equal to `data_allotment_mb`, not taken
from the request. A client that supplies `deprioritization_threshold_mb` in a plan write has the value
ignored and the derived value stored — the request does not fail for that reason alone, but supplying an
unknown field or omitting a required one yields `ERR_INVALID_REQUEST` (HTTP 400). Offering also recomputes the
parent agreement's `allocated_data_mb` and `remaining_data_mb`, since a plan that is `OFFERED` begins to count
toward the catalogue projection. A plan that is not yet placed can be withdrawn by a `CapacityPlanner`,
returning it from `OFFERED` to `DRAFT`; withdrawal is admitted only when no term on the plan is in `QUOTED`,
`PURCHASED`, `AWAITING_ACTIVATION`, `ACTIVE`, `RENEWAL_DUE`, or `ACTIVE_RENEWAL`.

The plan status machine is cyclic rather than one-way. The first purchase against a plan moves it from
`OFFERED` to `ACTIVE`, and the plan falls back from `ACTIVE` to `OFFERED` on its own once its last
non-terminal term leaves a non-terminal status — that is, once no term on it is in `QUOTED`, `PURCHASED`,
`AWAITING_ACTIVATION`, `ACTIVE`, `RENEWAL_DUE`, or `ACTIVE_RENEWAL`. Both movements recompute the parent
agreement's balance, and both refresh the plan's own `updated_at` and `version`. A plan reaches `RETIRED`
only through the closure of its parent agreement, described in §3.1.

The deprioritization threshold is the hinge between capacity economics and the subscriber experience, and it
is described more fully from the usage side in §3.4. A subscriber on the plan is deprioritized once their
consumption in the open cycle has reached the threshold while the serving agreement is congested; the plan's
monthly voice and messaging allotments (`voice_allotment_min` and `sms_allotment_msg`) are carried alongside
the data allotment as the plan's included quantities. A `CapacityPlanner`, `SupportAgent`,
`FulfillmentOperator`, `PlatformAdmin`, `Subscriber`, or `RetailPartner` may read a plan or list plans,
filtered by the `agreement_id` they belong to and optionally by `plan_status`.

### 3.3. The Subscriber Book and the One-Live-Term Rule

A subscriber enters the platform before their service is live, on a number they intend to bring with them. A
`CapacityPlanner` or `SupportAgent` registers the subscriber with the `msisdn` they wish to keep, their
`full_name`, and the `state_code` they live in, which decides both which agreement can serve them and which
state-scoped SIM media may be issued to them. The `msisdn` must be eleven digits and must be unique among all
subscribers who have not churned. A newly registered subscriber sits in `PENDING_PORT` with
`allocation_status` `NONE` — nothing is yet promised to them out of the agreement — and with all cycle
counters reset: `cycle_index` is 0, `cycles_rolled` is 0, `data_used_mb_cycle` is 0,
`deprioritized_this_cycle` is `false`, and `cycle_deprioritization_days` is 0. Their outsourced support
budget opens at 600 agent seconds — `DEFAULT_SUPPORT_BUDGET_SECONDS`, ten minutes of agent handling — recorded as `support_seconds_budget`,
with `support_seconds_used` at 0 and `self_service_deflection_count` at 0, as set out further in §3.9.

Service is committed one term at a time. A subscriber holds at most one prepaid term in a non-terminal status,
so a request to quote, purchase, or step up a term is rejected with `ERR_DUPLICATE_ACTIVE_TERM` (HTTP 409)
when a live term already exists for that number; one number carries one live term. The same three endpoints
are also the ones that must respect a suspended agreement (rejected with `ERR_AGREEMENT_SUSPENDED`) and a
closed agreement or retired plan (rejected with `ERR_AGREEMENT_CLOSED` or `ERR_PLAN_RETIRED`), per §3.1 and
§3.2.

A live subscriber can be moved out of service and back. A `SupportAgent` suspends an `ACTIVE` subscriber into
`SUSPENDED`, and the important economic consequence is that the agreement's `allocated_data_mb` is left
unchanged: the prepaid term is still committed capacity the operator has sold, even though the subscriber is
not using it. While suspended, the subscriber cannot take new add-ons — the attempt is rejected with
`ERR_SUBSCRIBER_NOT_ACTIVE` (HTTP 409). A `SupportAgent` returns the subscriber from `SUSPENDED` to `ACTIVE`,
which recomputes the parent agreement's congestion index.

Churn is the subscriber's own act, and it is guarded by optimistic concurrency. Cancelling a subscriber
requires the acting `Subscriber` to own the resource — `X-User-ID` must equal the subscriber's `id` — and to
carry `expected_Subscriber_version` matching the subscriber's current `version`; a stale expectation is
rejected with `ERR_STALE_VERSION` (HTTP 412). A subscriber with a port request still in flight cannot churn:
while any activation for them holds a submitted port, both the subscriber cancel and a term cancel are
rejected with `ERR_PORT_IN_FLIGHT` (HTTP 409), so the in-flight port must be cancelled or rejected first. A
successful churn is a wide cascade. It writes the subscriber's prepaid term to `EXPIRED` and writes
`breakage_days`, `breakage_cents_recognized`, `earned_revenue_cents` and `deferred_revenue_cents` through the
early-churn recognition described in §3.6; it voids every add-on for the subscriber whose `addon_status` is
`REQUESTED` or `ACTIVE`, setting `addon_status` to `VOIDED` and recording the number actually deprovisioned in
`deprovisioned_msisdn`; it closes every support case for the subscriber that is `OPEN`, `ASSIGNED` or
`ESCALATED` as `CLOSED`; it re-evaluates the parent plan's `plan_status`; and it recomputes the agreement's
`allocated_data_mb`, `remaining_data_mb` and `congestion_index`. A subscriber who is churned from `SUSPENDED`
follows the same cascade, though only add-ons in `REQUESTED` or `ACTIVE` are voided and no port check applies.

Grace is the holding state for a subscriber whose activation has failed rather than completed, and it is
described in full in §3.7. What matters at the subscriber-book level is that a subscriber parked in `GRACE`
is neither serving nor churned: the term is parked with it and commits no capacity while it waits, and if the
subscriber is not resumed, the first cycle roll after they entered `GRACE` churns them automatically. The
subscriber fields visible to readers of the book — `msisdn`, `full_name`, `state_code`, `subscriber_status`,
`allocation_status`, `cycle_index`, `cycles_rolled`, `data_used_mb_cycle`, `deprioritized_this_cycle`,
`cycle_deprioritization_days`, `support_seconds_used`, `support_seconds_budget` and
`self_service_deflection_count` — are readable by any role, and the collection can be filtered by `state_code`
and `subscriber_status`.

### 3.4. The Monthly Cycle: Consumption, Deprioritization and Overage

A live prepaid term is delivered as a sequence of monthly cycles, one per month of the term, and the last
cycle of a term is the one whose ordinal equals the plan's `term_months`. Each cycle is recorded as a
`CycleRecord` carrying its `cycle_index` ordinal within the term, a `cycle_status` of `OPEN` or `ROLLED`, the
instant it `opened_at` and, once rolled, the `closed_at` instant, together with the frozen readings
`cycle_data_used_mb` and `cycle_deprioritization_days` and the `earned_cents` recognised for that cycle. Rows
for every cycle of the term are created in one go when the term activates, so a cycle is addressed by its
`cycle_index` and never by creation order. Exactly one cycle is `OPEN` at a time; a subscriber's
`cycle_index` is the ordinal of that open cycle, and `cycles_rolled` counts how many have rolled closed
within the current term.

Consumption is booked against the open cycle. A `CapacityPlanner` records megabytes of high-speed usage by
supplying `data_mb`, and the call is admitted only when the subscriber is `ACTIVE` and their term is in
`ACTIVE` or `ACTIVE_RENEWAL`; otherwise it is rejected with `ERR_SUBSCRIBER_NOT_ACTIVE` or
`ERR_TERM_NOT_ACTIVE` (HTTP 409). A successful booking adds the megabytes to `data_used_mb_cycle` and leaves
the cycle `OPEN`. Booking requires an open cycle to exist, so a subscriber in `PENDING_PORT` has nothing to
consume against.

The deprioritization rule is the plan's throttle, and it is deliberately conjunctive — the
`deprioritization_check` rule. Once `data_used_mb_cycle`
has reached the plan's `deprioritization_threshold_mb` *and* the serving agreement's `congestion_active` is
true, the subscriber's `deprioritized_this_cycle` is set true. The comparison is inclusive: a subscriber
landing exactly on the threshold is deprioritized, while one megabyte below it is not. There is no tolerance
band around the threshold: the allowance is `DEPRIORITIZATION_GRACE_MB`, which is 0 megabytes, so the
comparison is exact. Once true, the flag
stays true for the remainder of the cycle — it is never cleared mid-cycle. The subscriber's
`cycle_deprioritization_days` counts the distinct calendar days in the open cycle on which
`deprioritized_this_cycle` was true; it is incremented at most once per distinct day, including the current
day at the moment the threshold is first met, and a cycle that closes with the flag still true and
`cycle_data_used_mb` exactly equal to the threshold still records a deprioritization day. The count freezes
onto the cycle record at roll as `cycle_deprioritization_days`. This count is not cosmetic: it feeds the
quality term of the revenue schedule in §3.6, which is how a congested, deprioritized cycle earns the
operator a little more of the term's price than a clean one.

Usage is also split at the allotment boundary — the `overage_threshold_split` rule — so that the agreement-level cost book can see overage. For a
subscriber on a plan whose `data_allotment_mb` is A and whose cycle usage is U, the in-allotment volume is
the smaller of U and A, and the overage volume is the excess of U over A, floored at 0. The boundary is
inclusive in the sense that consuming exactly the allotment produces no overage while one megabyte more
produces exactly one megabyte of overage. A prepaid subscriber is never billed individually for that overage;
the split exists solely so that the chronological reading of the agreement's cost book, described in §3.1,
can sum rolled overage across all subscribers.

A cycle is rolled closed by a `CapacityPlanner` — or by the system — and the roll is the richest single
operation in the system. It is admitted only on an `OPEN` cycle; a roll attempted on an already `ROLLED`
cycle is rejected with `ERR_CYCLE_ALREADY_ROLLED` (HTTP 409), because a rolled cycle is terminal for this
machine. A successful roll stamps `closed_at` with the current logical clock, freezes `cycle_data_used_mb`
and `cycle_deprioritization_days`, and writes the cycle's `earned_cents` under the final revenue schedule of
§3.6, from which the term's `deferred_revenue_cents` is recomputed. It then increments the subscriber's
`cycles_rolled` and resets `data_used_mb_cycle` to 0, `deprioritized_this_cycle` to `false`, and
`cycle_deprioritization_days` to 0 for the cycle about to begin. If the cycle that closed was not the last
one, a fresh cycle record opens at the next `cycle_index` and the subscriber's `cycle_index` advances to it.
If it was the last one, the term moves to `RENEWAL_DUE` and a support case with `topic_code` `RENEWAL_PRICING`
opens, which is where the renewal conversation described in §3.5 begins. The roll also settles everything
descending from the cycle: every support case for the subscriber whose `sla_due_at` is at or before
`closed_at` is escalated with `escalation_reason` set to `SLA_BREACH`; every case in `RESOLVED_SELF_SERVICE`
or `RESOLVED_AGENT` is closed as `CLOSED`; every add-on whose `end_at` is at or before `closed_at` is
expired; a shipped SIM inventory block whose `shipment_sla_days` window has elapsed is delivered; and a
subscriber still parked in `GRACE` is churned. Each of these cascades is described with its own mechanics in
§3.7 and §3.8. Cycle records may be read individually or listed by their `prepaid_term_id`, optionally
filtered by `cycle_status`.

### 3.5. Selling Time: Quoting, Purchase, Renewal Step-Up and Refund

A prepaid term is the unit of sale, and it moves through a long lifecycle: `QUOTED`, `PURCHASED`,
`AWAITING_ACTIVATION`, `ACTIVE`, `RENEWAL_DUE`, `ACTIVE_RENEWAL`, `GRACE`, `EXPIRED`, `REFUNDED`, and
`VOIDED`. The terminal states are `EXPIRED`, `REFUNDED`, and `VOIDED`. A term is always associated with the
subscriber who will use it and the plan whose allotments it draws, and it is quoted before it is paid for.

Quoting is the subscriber's own act. The acting `Subscriber` supplies `subscriber_id` and `plan_id` together
with `expected_CapacityAgreement_version`, and the server creates a term in `QUOTED` with `term_price_cents`
at 0 and both revenue fields at 0. The agreement version expectation is mandatory here: if the agreement's
`version` has advanced since the subscriber last read it — because another writer has just quoted or
purchased a term and thereby recomputed the agreement's allocation — the quote is rejected with
`ERR_STALE_VERSION` (HTTP 412), so the subscriber cannot commit against a capacity picture they have not
observed. Quoting bumps the agreement's `version` by 1.

Purchasing converts the quote into a paid term, moving it from `QUOTED` to `PURCHASED`. It is admitted only
when the parent plan is `OFFERED` or `ACTIVE`, the plan's parent agreement is `ACTIVE`, the agreement's
`remaining_data_mb` is at least the plan's `data_allotment_mb`, and no other term for the same `subscriber_id`
is in a non-terminal status. The capacity condition failing yields `ERR_INSUFFICIENT_AGREEMENT_CAPACITY`, and
a second live term for the same number yields `ERR_DUPLICATE_ACTIVE_TERM`; a suspended agreement yields
`ERR_AGREEMENT_SUSPENDED`, and a closed agreement or retired plan yields `ERR_AGREEMENT_CLOSED` or
`ERR_PLAN_RETIRED`. On success the term's `term_price_cents` is resolved by the `prepaid_term_price` rule and
the two revenue fields are seeded with the provisional schedule; the plan is moved from `OFFERED` to `ACTIVE`, and
the agreement's `allocated_data_mb` and `remaining_data_mb` are recomputed.

The price rule is quantity-of-term-history-based, not calendar-based, and it is the sole resolver behind both
the purchase and the renewal step-up. A subscriber's first term on a given plan — the term whose ordinal
equals `FIRST_TERM_ORDINAL`, which is 1 — is charged the plan's `intro_price_cents`; every later term on that
same plan is charged the `renewal_price_cents`. Whether a prior term exists is decided by looking at the subscriber's earlier terms on
that plan: a prior term counts when its `term_status` is `PURCHASED`, `AWAITING_ACTIVATION`, `ACTIVE`,
`RENEWAL_DUE`, `ACTIVE_RENEWAL`, `GRACE`, or `EXPIRED`, and does not count when it is `REFUNDED` or `VOIDED`
— so a subscriber whose first purchase was refunded is still entitled to the introductory price. Terms still
in `QUOTED` do not count either, since they represent no commitment yet. When several prior terms exist, which
one is "prior" is decided by ascending `created_at`, the earliest being the first.

A purchased term cannot go live until it is activated, which is the subject of §3.7. Purchasing also acquires
a hard constraint on the subscriber's number: no second term may be live on the same number, and the
renewal step-up and the quote are subject to the same rule, each rejecting with `ERR_DUPLICATE_ACTIVE_TERM`.

When the final cycle of a live term rolls, the term enters `RENEWAL_DUE` and a `RENEWAL_PRICING` support case
opens against the subscriber — this is the moment the introductory period ends and the renewal conversation
starts. The subscriber accepts the step-up, moving the term from `RENEWAL_DUE` to `ACTIVE_RENEWAL`, and that
acceptance is admitted only when the parent plan is `OFFERED` or `ACTIVE`, the parent agreement is `ACTIVE`,
and the agreement's `remaining_data_mb` is at least the plan's `data_allotment_mb`. Accepting sets
`term_price_cents` to the plan's `renewal_price_cents` and extends `expires_at` forward by `term_months`
calendar months from its current value. It resets the subscriber's cycle position to the start of a fresh
term — `cycle_index` to 1, `cycles_rolled` to 0, `data_used_mb_cycle` to 0, `deprioritized_this_cycle` to
`false`, and `cycle_deprioritization_days` to 0 — and opens a new cycle record at index 1. It closes the
renewal support case as `CLOSED`, voids every add-on for the subscriber that is in `REQUESTED` or `ACTIVE`
and records the number deprovisioned in `deprovisioned_msisdn`, and recomputes the agreement's balance. A
renewed term is not renewed forever on its own: when the renewed term's own final cycle rolls, the term
returns from `ACTIVE_RENEWAL` to `RENEWAL_DUE` and another `RENEWAL_PRICING` case opens, so the cycle can
repeat.

A term leaves the book early in one of three ways, and the distinction is entirely about whether any cycle
ever opened. If `starts_at` is still null — the term was purchased but never activated — cancelling it moves
it from `PURCHASED` or `AWAITING_ACTIVATION` to `REFUNDED`, zeroes both `deferred_revenue_cents` and
`earned_revenue_cents`, and releases the capacity the term was holding; this is the refund path a
`Subscriber` or `SupportAgent` uses. If the term has already started, a refund-style cancel is refused with
`ERR_TERM_ALREADY_STARTED` (HTTP 409), because from that point the term leaves the book only through breakage
recognition, which is described in §3.6. A cancel attempted on a term already in `REFUNDED` or `VOIDED` is
refused with `ERR_TERM_ALREADY_TERMINAL` (HTTP 409). Cancelling a started term writes breakage through the
early-churn recognition, recomputes the parent plan's `plan_status`, and recomputes the agreement's balance —
and, like the subscriber-level cancel, it is refused with `ERR_PORT_IN_FLIGHT` while the subscriber's
activation holds a submitted port. Two further paths void a term outright: a term still awaiting activation
whose state has no reservable SIM media at all moves to `VOIDED` with `void_reason` `SPARE_INVENTORY`, zeroed
revenue fields, and released capacity; and a term whose port was rejected and whose subscriber then declined
the spare number moves to `VOIDED` with `void_reason` `PORT_TERMINATED`, churning the subscriber with it. A
term that reaches `EXPIRED` without any successor term records its breakage and churns its subscriber; a term
that reaches `EXPIRED` while its subscriber sits in `GRACE` does the same at the first cycle-less churn. All
of these movements recompute the agreement's `allocated_data_mb`, `remaining_data_mb` and `congestion_index`
and may pull the parent plan back from `ACTIVE` to `OFFERED`.

### 3.6. Revenue Recognition, Deferred Balances and Breakage

Money collected up front for a term is not earned up front. A term carries `term_price_cents`, the amount
charged for that term, and splits it into an earned part, `earned_revenue_cents`, and an unearned part,
`deferred_revenue_cents`. The two are always complements: the deferred balance is `term_price_cents` minus
`earned_revenue_cents`, so it falls as revenue is recognised and can never exceed the term price.

Two schedules — the `schedule_formula_provisional_vs_final` pair — write those fields, and they are
deliberately different. The provisional schedule is applied at the moment of purchase, when no usage exists
yet. For a cycle ordinal written as k it takes the per-cycle
earned amount as `term_price_cents` multiplied by k and divided by `term_months`, rounded up to the next whole
cent, and the provisional deferred balance for that ordinal as the term price less that earned amount. At
purchase the term is seeded at the first ordinal, so `earned_revenue_cents` becomes one month's share of the
price rounded up and `deferred_revenue_cents` becomes the remainder. The provisional schedule ignores
deprioritization entirely; that is what makes it provisional.

The final schedule — the `schedule_formula_provisional_vs_final` pair's final variant — is applied each time a
cycle is rolled closed, and it blends a formula floor with a quality term. The floor for a cycle is `term_price_cents` divided by `term_months`, rounded up to the next
whole cent. The quality term rewards a cycle on which service was deprioritized: it is `term_price_cents`
multiplied by `QUALITY_SHARE_NUM` divided by `QUALITY_SHARE_DEN` — three twentieths, that is 15 percent of the
term price — multiplied by that cycle's `cycle_deprioritization_days` and divided by `DAYS_PER_CYCLE`, the 30 days of a
billing month, rounded up to the next whole cent. The cycle's `earned_cents` is the floor plus
the quality term, and it is frozen on the cycle record as a whole number of cents. The term's
`earned_revenue_cents` is then the running sum of the frozen `earned_cents` values across the cycle records
of that term whose `cycle_status` is `ROLLED`, capped at `term_price_cents` so a term can never over-earn,
and `deferred_revenue_cents` is the term price less that capped sum. The order of operations is pinned and
must not be varied: each per-cycle figure is rounded up and frozen on its own cycle record first, and only
then are the frozen integers summed. The system never sums unrounded values and never rounds after summing.
Because the quality term is added per cycle, a subscriber who was deprioritized throughout cycle one earns
strictly more for that cycle under the final schedule than the provisional schedule predicted, and two terms
with identical `term_price_cents` and `term_months` diverge as soon as their `cycle_deprioritization_days`
differ.

The deferred balance also has its own ageing reading, the `deferred_revenue_aging` walk. Processing a term's
cycle records in ascending `cycle_index` while carrying an integer accumulator, the carry after cycle k is
that cycle's `earned_cents` plus the carry after the preceding cycle — with the carry starting at 0 — and the
deferred balance at k is the term price less that carry. The ordering is strictly by ascending `cycle_index`; it is never by `created_at`
and never by `id`, because all of a term's cycle rows are created together at activation and their creation
timestamps therefore carry no ordering meaning. Replaying the same cycles in descending order would produce a
different deferred sequence, which is exactly why the order is pinned. After the final cycle — the cycle whose
ordinal equals `term_months` — the deferred balance is 0.

When a term ends before its cycles are exhausted, the operator keeps a slice of the unearned balance as
breakage, recognised by the `early_churn_revenue_recognition` rule. Counting the cycles that remain as the
term's `term_months` less the number of its cycle records
whose `cycle_status` is `ROLLED` — the currently open cycle counts neither as remaining nor as elapsed — the
remaining days are that count multiplied by `DAYS_PER_CYCLE`, the 30 days of a billing month. Those days are then capped: the
breakage window is the smaller of the remaining days and `BREAKAGE_CAP_DAYS`, 30 days, recorded as `breakage_days`. The breakage
recognised is `term_price_cents` multiplied by `breakage_days`, divided by `term_months` multiplied by 30,
floored to a whole cent, and recorded as `breakage_cents_recognized`. Recognition then adds that amount to
`earned_revenue_cents`, capped once more at `term_price_cents`, and sets `deferred_revenue_cents` to the term
price less the new earned balance. This write-back is one-way: the deferred balance only ever decreases here,
never increases. The 30-day cap is the reason a twelve-month term churned in its first cycle recognises at
most one extra cycle of revenue rather than eleven.

Breakage is also reported at the agreement level by the `breakage_revenue` roll-up. Summing `breakage_cents_recognized` over every term on the
agreement that is in `EXPIRED` gives the total breakage cents, and summing `term_price_cents` over those same
terms gives the total term price cents; terms in `REFUNDED`, terms in `VOIDED`, and terms that are not terminal
are excluded from both the numerator and the denominator. The agreement's `breakage_rate_ppm` is
`BREAKAGE_RATE_SCALE` — one million — times the total breakage divided by the total term price, rounded half up to a whole part per million, and is
0 when the total term price is 0. A term that was recognised with zero breakage still sits in the denominator,
so the rate measures breakage against the entire expired book rather than only against the terms that broke.
This figure, together with the allocation, congestion and cost readings of §3.1, is what the agreement summary
reports to a `CapacityPlanner`, `SupportAgent`, or `PlatformAdmin`.

### 3.7. Activation, Porting and the Grace Path

A purchased term is consumed by an activation, and an activation carries two independent dimensions that move
in parallel on the same record. The provisioning dimension, `activation_status`, runs `REQUESTED` →
`PROVISIONED` → `COMPLETED`, with `FAILED` reachable from either live state; `COMPLETED` and `FAILED` are
terminal. The porting dimension, `port_status`, runs `NONE` → `SUBMITTED` → `CONFIRMED`, and separately
`SUBMITTED` → `REJECTED` or `SUBMITTED` → `CANCELLED`; `REJECTED` and `CANCELLED` are terminal for that
dimension. The two dimensions are genuinely independent: a number can be live before its port settles, and a
rejected port does not by itself stop an activation from going live on a spare number, which is why the
completion rule accepts a port that is `NONE`, `CANCELLED`, `CONFIRMED`, or `REJECTED`.

A `Subscriber` requests an activation by supplying `subscriber_id` and `prepaid_term_id` together with an
`activation_channel` of `DIGITAL` or `RETAIL_PARTNER`; when the channel is `RETAIL_PARTNER` a
`retail_partner_id` is required, and when it is `DIGITAL` supplying `retail_partner_id` is an error — both
mismatches are rejected with `ERR_RETAIL_CHANNEL_MISMATCH` (HTTP 422). Requesting an activation also runs the full admission gate for the
capacity it will consume: it is rejected with `ERR_INSUFFICIENT_AGREEMENT_CAPACITY` (HTTP 409) when the
agreement cannot admit one more allotment of the plan's `data_allotment_mb`, rejected with
`ERR_NO_ACTIVATABLE_SIM_MEDIA` (HTTP 422) when no block scoped to the subscriber's `state_code` has a free
unit, and, on the retail channel, rejected with `ERR_PARTNER_NOT_AUTHORIZED_FOR_STATE` or
`ERR_PARTNER_SUSPENDED` (HTTP 422) when the named partner is not active for that state. The porting particulars may be supplied
at creation as `porting_msisdn`, `losing_carrier`, and `account_number_last4`, or later. The activation opens
in `REQUESTED` with `port_status` `NONE`, and it pulls the parent term from `PURCHASED` into
`AWAITING_ACTIVATION`; an activation may not reference a `prepaid_term_id` that already has one.

Provisioning is where capacity is held and media is drawn. A `CapacityPlanner` provisions a `REQUESTED`
activation, which requires a SIM inventory block scoped to the subscriber's `state_code` with at least one
unit still reservable, and, for a retail-channel activation, a partner that is `ACTIVE` and that lists that
`state_code` in its `partner_state_codes`. Provisioning reserves one unit on the matching block — incrementing
its `reserved_count`, setting its `reserved_for_activation_id`, and moving its `inventory_status` to
`RESERVED_PREPAID` — and mints the number the activation will go live on as `provisioned_msisdn`: the
subscriber's requested number when the subscriber is still `PENDING_PORT` on that same number, and otherwise
the subscriber's current `msisdn`. On the retail channel it additionally sets the block's `shipment_channel` to
`RETAIL_PARTNER_STOCK` and copies the receiving partner's `shipment_sla_days` onto the block. Provisioning also
sets the parent subscriber's `allocation_status` to `HELD` and recomputes the agreement's `allocated_data_mb`
and `remaining_data_mb`, so the volume the term will consume is held, not merely promised.

Completing an activation is what makes service live, and it can be performed by the `Subscriber` or by a
`SupportAgent`. It is admitted only while the subscriber's term is `AWAITING_ACTIVATION` and while
`port_status` is `NONE`, `CANCELLED`, `CONFIRMED`, or `REJECTED`. Completion sets `accepted_msisdn` to
`provisioned_msisdn` when no port settled and to `porting_msisdn` when one did, and clears `held_data_mb` to 0
because the hold converts into a real commitment. It moves the subscriber from `PENDING_PORT` to `ACTIVE`
with `allocation_status` `ALLOCATED`, moves the term from `AWAITING_ACTIVATION` to `ACTIVE`, and opens the
term's first cycle. Setting the term live also stamps `starts_at` with the instant the first cycle opened and
derives `expires_at` as `starts_at` plus `term_months` calendar months, and resets the subscriber's
`cycle_index` to 1 with `data_used_mb_cycle` at 0. The completion recomputes the parent plan's `plan_status`
and the agreement's `allocated_data_mb`, `remaining_data_mb` and `congestion_index`. Because rows for every
cycle of the term are created at this moment, the cycle book described in §3.4 is fully materialised as soon
as service starts.

Failure is the other way out, and it is `SupportAgent`-acted. An activation in `REQUESTED` fails when no SIM
inventory block scoped to the subscriber's `state_code` has a unit still reservable; an activation in
`PROVISIONED` fails when its block has reached `SHIPPED` or `DELIVERED` and the `shipment_sla_days` window has
elapsed without delivery. Both paths move the activation to `FAILED`, send the subscriber to `GRACE`, and push
the term back to `PURCHASED`, and both accept a `failure_reason` recording why the attempt did not land. the first path also decrements the reserving block's `reserved_count` when a
reservation had been taken, and the second sets that block back to `RETURNED` and reopens its `reserved_count`
by the reserved units. A term sitting in `GRACE` parks: it neither commits capacity nor earns revenue while it
waits there, and its recompute of `allocated_data_mb` and `remaining_data_mb` is what releases the hold. If the
subscriber's activation fails, the subscriber's own row moves from `PENDING_PORT` to `GRACE` and the first
cycle roll after that automatically churns them, which resolves the term to `EXPIRED` with breakage written by
the recognition rule of §3.6 and closes every `OPEN` or `ASSIGNED` support case for them.

A support agent can also rescue a subscriber from grace. A `SupportAgent` resumes the activation, and that is
admitted only when some activation for the subscriber is in `REQUESTED` or `PROVISIONED` and the subscriber's
term is in `GRACE`. Resuming sets the subscriber's `allocation_status` back to `HELD` and the term back to
`AWAITING_ACTIVATION`, and recomputes the agreement's balance; the activation then proceeds through
provisioning and completion as normal.

Porting runs alongside provisioning. A `Subscriber` submits a port request by naming `porting_msisdn`,
`losing_carrier`, and `account_number_last4`, and the submission is admitted only while the activation is
`PROVISIONED` or `COMPLETED` — so both a not-yet-live number and a live number can be ported — and only when,
in the `PROVISIONED` case, the subscriber's `msisdn` equals the submitted `porting_msisdn`. A submission whose
number disagrees with the subscriber's own number is rejected with `ERR_MSISDN_MISMATCH` (HTTP 422), and a
submission whose `losing_carrier` and `account_number_last4` are already held by another activation with
`port_status` `SUBMITTED` is rejected with `ERR_MSISDN_ALREADY_IN_FLIGHT` (HTTP 409). A successful submission
sets `port_status` to `SUBMITTED`, sets the activation's `held_data_mb` to the plan's `data_allotment_mb`, and
sets the parent subscriber's `allocation_status` to `HELD`; the agreement's allocation is recomputed so that
the hold and the allocation are counted exactly once and never twice. A `SupportAgent` confirms the port, which
is admitted only from `SUBMITTED` and puts the subscriber `ACTIVE` with `allocation_status` `ALLOCATED`. A
`SupportAgent` rejects the port with a supplied `rejection_code` recorded on the activation; when the
activation has not yet gone live (`PROVISIONED`), rejection sends the subscriber to `GRACE` with
`allocation_status` `NONE`, while on a live activation (`COMPLETED`) the subscriber stays `ACTIVE` with
`allocation_status` `ALLOCATED` because the live term still holds its capacity — either way `held_data_mb` is
cleared and the agreement's balance and congestion index are recomputed. A confirmed port can also be rejected
while the activation is not `COMPLETED`, which clears the hold and sets `allocation_status` to `NONE`. Finally
a `Subscriber` may withdraw a submitted port: cancelling it sets `port_status` to `CANCELLED` and clears
`held_data_mb`, leaving `allocation_status` at `HELD` when the activation is still `PROVISIONED` but at
`ALLOCATED` when it is `COMPLETED`. When an activation completes at the end of a port whose port status was
`CONFIRMED`, the port dimension settles back to `NONE`, `held_data_mb` clears to 0, and `accepted_msisdn` is
set to `porting_msisdn`. Each of the port actions advances the activation's `version` and refreshes
`updated_at`. A port action attempted after the port is already `REJECTED` is refused with
`ERR_PORT_ALREADY_TERMINAL` (HTTP 409), and a completion or failure attempted on an activation already
`COMPLETED` or `FAILED` is refused with `ERR_ACTIVATION_ALREADY_TERMINAL` (HTTP 409).

The activation record exposes both dimensions to readers, along with the subscriber it serves, the term it
consumes, the partner it ships through, the resolved number fields `provisioned_msisdn` and `accepted_msisdn`,
the in-flight hold `held_data_mb`, and — for a rejected port — the `rejection_code`; the porting inputs
`porting_msisdn`, `losing_carrier`, and `account_number_last4` are visible on the result once supplied. The
collection can be filtered by `subscriber_id`, `prepaid_term_id`, `retail_partner_id`, `activation_status`, and
`port_status`, which lets an operator follow the two dimensions independently. One porting outcome does not wait for the logical
clock at all: when a port is rejected and the subscriber then declines the spare number rather than invoking
the `keep_requested_msisdn` capability to keep the number being ported, the subscriber is churned directly
from `PENDING_PORT`, the in-flight hold on the activation is released by clearing its `held_data_mb`, the
agreement's balance is recomputed, and every support case for the subscriber that is `OPEN` or `ASSIGNED` is
closed as `CLOSED`. Declining the spare in that situation is also one of the two ways a purchased term becomes
`VOIDED` with `void_reason` `PORT_TERMINATED`, as described in §3.5.

### 3.8. SIM Media, Retail Partners, Shipment and Add-Ons

Subscriber identity media is modelled as state-scoped inventory blocks, and the state scope is absolute: SIM
media never crosses state lines. A block is registered with the `state_code` it is scoped to, a
`sim_media_type` of `PHYSICAL_SIM` or `ESIM_PROFILE`, and a `unit_count` of at least 1 unit or profile; it may
optionally be attached to a `retail_partner_id`, and when it is not it belongs to direct-to-subscriber
inventory. A block opens in `AVAILABLE` with `reserved_count` at 0, `units_shipped` at 0, and no
`shipment_channel`. A `CapacityPlanner` or a `RetailPartner` may register blocks; the partner may register only
its own, and a partner acting on a block whose `retail_partner_id` is not their own identifier is rejected
with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). Registration against a partner in `DEFLECTED` or `SUSPENDED` is
rejected with `ERR_PARTNER_SUSPENDED` (HTTP 422), and registration naming a state the partner does not list
in its `partner_state_codes` is rejected with `ERR_PARTNER_NOT_AUTHORIZED_FOR_STATE` (HTTP 422). The
`shipment_channel` recorded on a block must agree with whether the block has a partner at all, and a
disagreement is rejected with `ERR_RETAIL_CHANNEL_MISMATCH` (HTTP 422). Reservation capacity is checked in
aggregate: the units already reserved by activations whose reservation window is still open, plus the units
this request would reserve, must stay at or below the block's `unit_count`, with exact equality admitted and
one unit past it rejected. A reservation attempted against a block with no free unit is rejected with
`ERR_SIM_INVENTORY_DEPLETED` (HTTP 409), and a provisioning request that cannot find any block in the
subscriber's state with a free unit is rejected with `ERR_NO_ACTIVATABLE_SIM_MEDIA` (HTTP 422) — the same
condition that, when it cannot be resolved at all, drives a waiting term to `VOIDED` with
`void_reason` `SPARE_INVENTORY` as described in §3.5.

A block's own status machine tracks its journey from stock to service. Reserving a unit moves it from
`AVAILABLE` to `RESERVED_PREPAID`, incrementing `reserved_count` by 1 and recording the activation in
`reserved_for_activation_id`; the reserving subscriber's `state_code` must equal the block's own. A
direct-to-subscriber provisioning reserves the unit but leaves the block in `AVAILABLE` on the
`DIRECT_TO_SUBSCRIBER` channel and leaves `shipment_sla_days` null, because the media ships straight to the
subscriber rather than to a partner's shelf; a retail-partner provisioning instead records
`RETAIL_PARTNER_STOCK` and copies the partner's `shipment_sla_days`. When a shipment release reaches a
reserved block, it moves to `SHIPPED`, setting `units_shipped` to the reserved count and decrementing
`reserved_count` by that same amount. When the `shipment_sla_days` window elapses on the logical clock and the
block's `state_code` matches the destination state recorded on the activation, it moves to `DELIVERED`. A
`FulfillmentOperator` may return shipped media: returning a block that is `RESERVED_PREPAID`, `SHIPPED`, or
`DELIVERED` moves it to `RETURNED`, reopens `reserved_count` by `units_shipped`, and zeroes `units_shipped` —
and because the media can no longer serve the waiting activation, that activation is set to `FAILED`, which
cascades its subscriber into `GRACE` and its term back to `PURCHASED`, exactly as the failure path of §3.7
does. A block reaches `DEPLETED` on its own once every unit has shipped, that is once `unit_count` minus
`reserved_count` equals 0; further reservations from a depleted block are rejected with
`ERR_SIM_INVENTORY_DEPLETED`. Blocks may be read individually, or listed and filtered by `state_code`,
`sim_media_type`, `inventory_status`, `retail_partner_id`, and `reserved_for_activation_id`.

Retail partners are the distribution channel, and they are held to delivery performance. A `CapacityPlanner`
onboards a partner with a unique `partner_name`, the set of states it may hold media for as
`partner_state_codes` — which must be non-empty — and an optional `shipment_sla_days`, defaulting to 2 days
when omitted. A partner opens with its `partner_status` set to `ACTIVE`. A partner is deflected automatically when its fulfilment track
record degrades: once two or more of the partner's blocks are in `SHIPPED` with an elapsed
`shipment_sla_days` window — released but never delivered — the partner has fallen two or more deliveries
behind what it released, and it moves from `ACTIVE` to `DEFLECTED`. A `CapacityPlanner` reinstates a deflected partner back to
`ACTIVE`, which is admitted only once the partner has no block that is `SHIPPED` with an elapsed SLA window,
and may also suspend a partner outright from `ACTIVE` or `DEFLECTED`, landing it in the terminal `SUSPENDED`
state. A partner in `DEFLECTED` or `SUSPENDED` cannot serve new activations: retail-channel activations
against it are rejected with `ERR_PARTNER_SUSPENDED` (HTTP 422), and new inventory blocks registered against
it are rejected the same way.

Add-ons extend live service beyond domestic plans, and their pricing is resolved when they go live. A
`Subscriber` requests an add-on by naming the `subscriber_id`, an `addon_type` of `ROAMING` or
`INTERNATIONAL_LD`, an `addon_days` window, and a `per_day_allotment_mb`. The window must be one of 1, 7, or
30 days, and the daily allotment must be 0 for an international long-distance add-on and at least 1 megabyte
for a roaming add-on; a request that violates either is rejected with `ERR_INVALID_ADDON_WINDOW` (HTTP 422).
A requested add-on opens in `REQUESTED` with `addon_price_cents` at 0.

Activating an add-on resolves its price from the roaming rate card. The card's base is
`BASE_ROAMING_30D_CENTS`, a thirty-day price of 900 cents, from which the base day rate is derived as that
thirty-day price divided by 30, rounded half up to a whole cent — 30 cents for the standard card. The
thirty-day tier is `BASE_ROAMING_30D_CENTS` itself, 900 cents. The seven-day
tier is the base day rate multiplied by 7, then multiplied by `SHORT_TERM_MULT_NUM` and divided by
`SHORT_TERM_MULT_DEN` — a 30 percent uplift — rounded up to the next whole cent; the one-day tier is the base
day rate multiplied by 1 and uplifted the same way, also rounded up. The tiers are evaluated in the order
thirty days, then seven days, then one day, and the first matching tier wins, so no ladder is ever applied
twice. An add-on of type `INTERNATIONAL_LD` ignores the ladder entirely and takes the flat
`INTL_LD_FLAT_CENTS` price of 500 cents. Activation also sets `start_at` to the current logical clock and derives `end_at`
as `start_at` plus `addon_days` calendar days, and it is admitted only when the parent subscriber is `ACTIVE`
and that subscriber's term is in `ACTIVE` or `ACTIVE_RENEWAL`; otherwise it is rejected with
`ERR_SUBSCRIBER_NOT_ACTIVE` or `ERR_TERM_NOT_ACTIVE` (HTTP 409).

Add-on windows may not overlap for the same subscriber. Activating an add-on whose window intersects a window
already `ACTIVE` for that subscriber is rejected with `ERR_ADDON_WINDOW_OVERLAP` (HTTP 409), and the windows
are compared as half-open intervals: a new add-on that starts exactly at an existing window's `end_at` is
admitted, while one starting a second earlier is rejected. Activating the add-on early in this window calls
`roaming_rate_card` to resolve the price; add-ons may be read individually or listed and filtered by
`subscriber_id`, `addon_status`, and `addon_type`. An add-on expires on its own at the first cycle
roll whose `closed_at` is at or after its `end_at`, moving from `ACTIVE` to `EXPIRED`, setting its resolved
price to 0 and leaving `end_at` unchanged. A `Subscriber` may also cancel an add-on that is `REQUESTED` or
`ACTIVE`, moving it to `CANCELLED` with its price set to 0 and its `end_at` set equal to `start_at`. When the
parent subscriber churns, or when a renewal step-up is accepted, every add-on in `REQUESTED` or `ACTIVE` is
moved to `VOIDED`, its price set to 0, and the number actually deprovisioned recorded in `deprovisioned_msisdn`
— the subscriber's `accepted_msisdn`.

### 3.9. Support Economics: SLA Windows, Deflection and the Agent-Second Budget

Customer care is outsourced, and the platform meters it in agent seconds against a per-subscriber budget under
the `support_outsourcing_budget` rule, with each case's window and bookings fixed by
`support_case_topic_window`. A
`Subscriber` or a `SupportAgent` opens a case by supplying the `subscriber_id` and a `topic_code`, and the
case opens in `OPEN` with `handling_seconds` at 0. The topic determines both the response window and the
time the work is expected to consume. The case's `sla_due_at` is its `created_at` plus the topic's SLA hours
from the `SLA_HOURS` table: four hours for `PORT_STATUS`, eight for `DEPRIORITIZATION_COMPLAINT`, twelve for
`SIM_REPLACEMENT`, twenty-four for `ROAMING_SETUP` and `RENEWAL_PRICING`, and forty-eight for
`REFUND_REQUEST`. Each topic also carries a routing estimate in agent seconds from the `ROUTING_SECONDS`
table — 120 for `PORT_STATUS`, 240 for `DEPRIORITIZATION_COMPLAINT`, 150 for `SIM_REPLACEMENT`, 180 for
`ROAMING_SETUP`, 180 for `RENEWAL_PRICING`, and 300 for `REFUND_REQUEST` — and the single
`ESCALATION_SECONDS` allowance of 60 seconds that applies to every topic when a case is escalated. All of
these windows are evaluated against the logical clock and never against wall-clock time.

The case lifecycle runs `OPEN` → `ASSIGNED` → `RESOLVED_AGENT`, with `RESOLVED_SELF_SERVICE` reachable
directly from `OPEN`, `ESCALATED` reachable from `OPEN` or `ASSIGNED`, and `CLOSED` terminal. A `SupportAgent`
assigns an open case, moving it to `ASSIGNED` and booking the topic's routing estimate into
`handling_seconds`; assignment is admitted only while the case is `OPEN` and only while the subscriber's
`support_seconds_used` plus the routing estimate would not exceed the subscriber's `support_seconds_budget`.
Resolution through an agent is available from `ASSIGNED` or from `ESCALATED`; it books the reported
`agent_seconds` into `handling_seconds` and onto the subscriber's `support_seconds_used`, and it is admitted
only while that running total plus the reported seconds would stay within the budget. Escalation increments
the subscriber's `support_seconds_used` by the topic's escalation estimate of 60 seconds, and can happen in
two ways: a `SupportAgent` escalates a case manually, which is admitted only when the current logical clock is
at or after the case's `sla_due_at` and which records `escalation_reason` `SELF_SERVICE_FAILED`; or the system
escalates a case automatically at a cycle roll whose `closed_at` is at or after `sla_due_at` while the case is
`OPEN` or `ASSIGNED`, which records `escalation_reason` `SLA_BREACH`. When a manual escalation is attempted
before the case's `sla_due_at`, it is rejected with `ERR_SLA_NOT_DUE` (HTTP 409). Any booking that would push
the subscriber past their budget — an assignment, an escalation, or an agent resolution — is rejected with
`ERR_SUPPORT_BUDGET_EXCEEDED` (HTTP 402), which is the platform's way of holding the outsourcing cost line.

Self-service is the deliberate alternative to an agent, and it is rewarded but not free of conditions. A
`Subscriber` resolves their own case in self-service, moving it from `OPEN` to `RESOLVED_SELF_SERVICE`; the
resolution leaves `handling_seconds` at 0 and books nothing against the budget, and it increments the
subscriber's `self_service_deflection_count` by 1. It is admitted only once the case is at least 60 seconds
old on the logical clock, and an attempt inside that cooling window is rejected with `ERR_SELF_SERVICE_TOO_EARLY`
(HTTP 409). The budget itself is both a ceiling and a quantity that can be topped up: a `SupportAgent` raises
the subscriber's `support_seconds_budget` by a `granted_seconds` amount on request, and the used total is the
sum of `handling_seconds` across every one of the subscriber's cases, including cases that are already
`CLOSED`. The deflection count is the number of the subscriber's cases in `RESOLVED_SELF_SERVICE` or `CLOSED`
whose `handling_seconds` is 0 and whose `escalation_reason` is null — so a case that was escalated and then
closed does not count as a deflection, while a case resolved in self-service and later swept closed by a cycle
roll does. The budget's headroom is `support_seconds_budget` less `support_seconds_used`, and a case that is
`OPEN` or `ASSIGNED` with no booked seconds contributes nothing to the used total.

A case's `handling_seconds` is a running sum of every booking ever made against it, so one case can carry
routing, escalation and agent seconds together: a case that is assigned, then escalated, then resolved
through an agent carries 120 plus 60 plus the reported agent seconds for a `PORT_STATUS` case, and the
subscriber's `support_seconds_used` carries the same running total across all of their cases. Cases are
swept up by the cycle roll described in §3.4: every resolved case is closed as `CLOSED` with its
`handling_seconds` and the deflection count left unchanged, and every case whose SLA window has passed is
escalated. Cases may be read individually or listed and filtered by `subscriber_id`, `case_status`, and
`topic_code`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource, such as a capacity agreement, a plan, a subscriber, a
quoted term, an activation, a partner, a SIM inventory block, a support case, or an add-on, return a
`201 Created` status code. Operations that modify an existing resource — every lifecycle action, state
transition, allocation and clock movement — return a `200 OK` status code, including reads on lists and single
resources. The table below is the complete surface; request bodies, response bodies, derived-field
recomputations and cascades are deliberately omitted here, because they are specified in §2 and §3. Roles
listed as "Any authenticated role" are the six roles named in §2.1.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/carriers/capacity-agreements` | Register a wholesale capacity agreement with a host network | CapacityPlanner |
| GET | `/carriers/capacity-agreements/{id}` | Read one agreement with its derived allocation and congestion fields | Any authenticated role |
| POST | `/carriers/capacity-agreements/{id}/activate` | Move an agreement from `DRAFT` to `ACTIVE` and open its capacity for sale | CapacityPlanner |
| POST | `/carriers/capacity-agreements/{id}/suspend` | Suspend an agreement so no further capacity can be sold against it | CapacityPlanner |
| POST | `/carriers/capacity-agreements/{id}/reactivate` | Return a suspended agreement to service once over-allocation is resolved | CapacityPlanner |
| POST | `/carriers/capacity-agreements/{id}/close` | Close an agreement permanently and retire every plan on it | CapacityPlanner |
| POST | `/carriers/capacity-agreements/{id}/resolve-purchase` | Resolve the forward-looking purchase commitment and store the resolved cost | CapacityPlanner |
| GET | `/carriers/capacity-agreements/{id}/usage-summary` | Read the as-incurred cost, blended tier cost, allocation and breakage rate | CapacityPlanner, SupportAgent, PlatformAdmin |
| POST | `/carriers/plans` | Register a prepaid plan on an agreement | CapacityPlanner |
| GET | `/carriers/plans/{id}` | Read one plan, including its derived deprioritization threshold | Any authenticated role |
| GET | `/carriers/plans` | List plans, filterable by the agreement they belong to | Any authenticated role |
| POST | `/carriers/plans/{id}/offer` | Offer a draft plan for sale and derive its deprioritization threshold | CapacityPlanner |
| POST | `/carriers/plans/{id}/withdraw` | Withdraw an offered plan back to draft | CapacityPlanner |
| POST | `/carriers/subscribers` | Register a subscriber awaiting activation on a number they intend to port in | CapacityPlanner, SupportAgent |
| GET | `/carriers/subscribers/{id}` | Read one subscriber with usage, allocation and support counters | Any authenticated role |
| GET | `/carriers/subscribers` | List subscribers, filterable by state and status | CapacityPlanner, SupportAgent, FulfillmentOperator, PlatformAdmin |
| POST | `/carriers/subscribers/{id}/cancel` | Churn a subscriber, recognising breakage and returning capacity | Subscriber |
| POST | `/carriers/subscribers/{id}/suspend` | Suspend an active subscriber, keeping the term's capacity committed | SupportAgent |
| POST | `/carriers/subscribers/{id}/resume` | Return a suspended subscriber to active service | SupportAgent |
| POST | `/carriers/subscribers/{id}/consume_data` | Record high-speed data consumed in the subscriber's open cycle | CapacityPlanner |
| POST | `/carriers/subscribers/{id}/run_cycle` | Roll the open cycle closed, ageing revenue and firing the cycle's cascades | CapacityPlanner |
| POST | `/carriers/subscribers/{id}/support_top_ups` | Raise the subscriber's outsourced support budget in agent seconds | SupportAgent |
| POST | `/carriers/prepaid-terms` | Quote a prepaid term for a subscriber against a plan, under OCC on the agreement | Subscriber |
| GET | `/carriers/prepaid-terms/{id}` | Read one prepaid term with its deferred and earned revenue fields | Any authenticated role |
| GET | `/carriers/prepaid-terms` | List prepaid terms, filterable by subscriber, plan and status | Any authenticated role |
| POST | `/carriers/prepaid-terms/{id}/purchase` | Purchase the quoted term, charging the intro price and deferring the unearned part | Subscriber |
| POST | `/carriers/prepaid-terms/{id}/accept_step_up` | Renew a term at the step-up price after the introductory period | Subscriber |
| POST | `/carriers/prepaid-terms/{id}/cancel` | Cancel a term, refunding an unstarted term or recognising breakage on a started one | Subscriber, SupportAgent |
| GET | `/carriers/cycles/{id}` | Read one cycle record with its frozen usage and earned cents | Any authenticated role |
| GET | `/carriers/cycles` | List cycle records, filterable by the term they belong to | Any authenticated role |
| POST | `/carriers/activations` | Request a digital or retail-partner activation for a purchased term | Subscriber |
| GET | `/carriers/activations/{id}` | Read one activation with both its provisioning and porting dimensions | Any authenticated role |
| GET | `/carriers/activations` | List activations, filterable by subscriber, term, partner and both state dimensions | Any authenticated role |
| POST | `/carriers/activations/{id}/provision` | Reserve state-scoped SIM media and mint the number the activation will go live on | CapacityPlanner |
| POST | `/carriers/activations/{id}/complete` | Complete an activation, settling any submitted port and starting the first cycle | Subscriber, SupportAgent |
| POST | `/carriers/activations/{id}/fail` | Fail an activation, sending the subscriber into grace and the term back to purchased | SupportAgent |
| POST | `/carriers/activations/{id}/submit-port` | Submit a port-in request that holds capacity for the number being ported | Subscriber |
| POST | `/carriers/activations/{id}/reject-port` | Record a losing-carrier rejection and release the held capacity | SupportAgent |
| POST | `/carriers/activations/{id}/confirm-port` | Record a losing-carrier confirmation, putting the ported number live | SupportAgent |
| POST | `/carriers/activations/{id}/cancel-port` | Withdraw a submitted port request and release the capacity it held | Subscriber |
| POST | `/carriers/retail-partners` | Onboard a retail partner that will hold SIM media for a set of states | CapacityPlanner |
| GET | `/carriers/retail-partners/{id}` | Read one retail partner | Any authenticated role |
| POST | `/carriers/retail-partners/{id}/suspend` | Suspend a partner so its media can no longer serve new activations | CapacityPlanner |
| POST | `/carriers/retail-partners/{id}/reinstate` | Return a deflected partner to active service | CapacityPlanner |
| POST | `/carriers/sim-inventories` | Register a state-scoped block of physical SIM units or eSIM profiles | CapacityPlanner, RetailPartner |
| GET | `/carriers/sim-inventories/{id}` | Read one SIM inventory block with its reservation and shipment fields | Any authenticated role |
| GET | `/carriers/sim-inventories` | List SIM inventory blocks, filterable by state, media, partner and reservation | CapacityPlanner, SupportAgent, FulfillmentOperator, PlatformAdmin, RetailPartner |
| POST | `/carriers/sim-inventories/{id}/return` | Return shipped SIM media, reopening the reservation and failing the waiting activation | FulfillmentOperator |
| POST | `/carriers/support-cases` | Open a support case against a subscriber | Subscriber, SupportAgent |
| GET | `/carriers/support-cases/{id}` | Read one support case with its SLA window and escalation reason | CapacityPlanner, SupportAgent, FulfillmentOperator, PlatformAdmin, Subscriber |
| GET | `/carriers/support-cases` | List support cases, filterable by subscriber and status | CapacityPlanner, SupportAgent, FulfillmentOperator, PlatformAdmin |
| POST | `/carriers/support-cases/{id}/assign` | Assign an open case to an agent and book its routing estimate | SupportAgent |
| POST | `/carriers/support-cases/{id}/resolve_self_service` | Resolve a case in self-service with zero agent seconds | Subscriber |
| POST | `/carriers/support-cases/{id}/resolve_agent` | Resolve a case through an agent, booking the reported handling seconds | SupportAgent |
| POST | `/carriers/support-cases/{id}/escalate` | Escalate a case once its SLA window has elapsed | SupportAgent |
| POST | `/carriers/add-ons` | Request a roaming or international long-distance add-on | Subscriber |
| GET | `/carriers/add-ons/{id}` | Read one add-on with its resolved price and window | CapacityPlanner, SupportAgent, FulfillmentOperator, PlatformAdmin, Subscriber |
| GET | `/carriers/add-ons` | List add-ons, filterable by subscriber and status | CapacityPlanner, SupportAgent, FulfillmentOperator, PlatformAdmin, Subscriber |
| POST | `/carriers/add-ons/{id}/activate` | Activate a requested add-on and resolve its price from the rate card | CapacityPlanner |
| POST | `/carriers/_clock/set_current_utc` | Set the logical clock used by SLA windows, add-on expiry and shipment delivery | PlatformAdmin |

## 5. Error Code Catalogue

The table below lists every error the API can return with its HTTP status. The conditions that trigger each
error are specified in the workflow narrative of §2 and §3, not here; a reader looking for *why* an error is
raised should follow the error's discussion at the point of the rule it guards.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_SUBSCRIBER_NOT_FOUND` | 404 Not Found |
| `ERR_TERM_NOT_FOUND` | 404 Not Found |
| `ERR_ACTIVATION_NOT_FOUND` | 404 Not Found |
| `ERR_PARTNER_NOT_FOUND` | 404 Not Found |
| `ERR_SIM_INVENTORY_NOT_FOUND` | 404 Not Found |
| `ERR_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_CYCLE_NOT_FOUND` | 404 Not Found |
| `ERR_ADDON_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_TERM_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_ACTIVATION_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_PORT_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_CYCLE_ALREADY_ROLLED` | 409 Conflict |
| `ERR_AGREEMENT_SUSPENDED` | 409 Conflict |
| `ERR_AGREEMENT_CLOSED` | 409 Conflict |
| `ERR_PLAN_RETIRED` | 409 Conflict |
| `ERR_INSUFFICIENT_AGREEMENT_CAPACITY` | 409 Conflict |
| `ERR_DUPLICATE_ACTIVE_TERM` | 409 Conflict |
| `ERR_PARTNER_NOT_AUTHORIZED_FOR_STATE` | 422 Unprocessable Entity |
| `ERR_PARTNER_SUSPENDED` | 422 Unprocessable Entity |
| `ERR_NO_ACTIVATABLE_SIM_MEDIA` | 422 Unprocessable Entity |
| `ERR_SIM_INVENTORY_DEPLETED` | 409 Conflict |
| `ERR_SUBSCRIBER_NOT_ACTIVE` | 409 Conflict |
| `ERR_TERM_NOT_ACTIVE` | 409 Conflict |
| `ERR_MSISDN_ALREADY_IN_FLIGHT` | 409 Conflict |
| `ERR_MSISDN_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_PLAN_TERM` | 422 Unprocessable Entity |
| `ERR_INVALID_ADDON_WINDOW` | 422 Unprocessable Entity |
| `ERR_SELF_SERVICE_TOO_EARLY` | 409 Conflict |
| `ERR_SUPPORT_BUDGET_EXCEEDED` | 402 Payment Required |
| `ERR_SLA_NOT_DUE` | 409 Conflict |
| `ERR_RETAIL_CHANNEL_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PORT_IN_FLIGHT` | 409 Conflict |
| `ERR_TERM_ALREADY_STARTED` | 409 Conflict |
| `ERR_ADDON_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |