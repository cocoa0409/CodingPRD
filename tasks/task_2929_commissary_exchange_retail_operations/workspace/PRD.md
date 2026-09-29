# Commissary & Exchange Retail Operations API — Product Requirements Document

## 1. Introduction

Military resale is two businesses wearing one uniform. On the commissary side, groceries are sold to authorized patrons at landed cost plus a legislated surcharge whose proceeds may only be spent on capital improvement of the stores themselves; on the exchange side, general merchandise carries a retail markup and the earnings are returned to the community as a dividend that funds morale, welfare and recreation programs. Both sides sell tax-free, both sides must prove that every shopper standing at the register was entitled to be there, and both sides answer to auditors who will ask, months later, exactly which fund received which cent and on whose authority it was spent.

Today that reconciliation is done with spreadsheets, faxed sponsor letters and a great deal of trust. Cashiers cannot tell whether the person presenting a dependent card still has a valid sponsor behind it. Category managers double-book the same shelf block to two vendors because nobody holds the planogram centrally. Fund controllers approve capital projects against a surcharge balance that has already been obligated elsewhere. Resale abuse — patrons buying controlled goods in bulk for off-installation resale — is discovered only after the fact, if at all. And at overseas and deployed sites, the appropriated-fund transportation subsidy that keeps prices flat gets muddled into the shelf price, which is precisely what the law forbids.

This document specifies the backend service that replaces all of it: a single system of record for stores, patrons, authorized-shopper delegations, the worldwide item file, shelf assortment, point-of-sale transactions, the two funds and their append-only ledgers, capital projects, MWR programs and special orders. It is a compliance engine first and a pricing engine second. Every rule below exists because somebody must be able to answer an auditor's question from stored data alone, and because a cashier's terminal must be told *no* at the moment of the attempt rather than in a quarterly exception report.

## 2. Global Specifications & System-Wide Principles

### 2.1. Operating Identities and Role-Based Access Control

Every request to this API carries two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the capacity in which the caller is acting. Both must be present and non-empty, and the value of `X-User-Role` must be one of the seven roles enumerated below. A request that omits either header, supplies an empty string for either, or names a role outside the seven is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is well-formed but is not among the roles authorised for the endpoint being called is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403). The authorised role list for each endpoint is given in the table in §4.

The seven roles are:

- **`SystemOperator`** — the test and operations harness identity whose sole purpose is to position the server's logical clock. It has no business capability beyond that.
- **`SurchargeFundController`** — the agency fund officer. This role registers stores, runs the period-close checkpoint, and drafts, submits and closes surcharge-funded capital projects. It may never render the board decision on a project, and it may not close a project it submitted itself.
- **`MwrBoardOfficer`** — a member of the morale, welfare and recreation board. This role registers dividend-funded programs and renders the board decision on capital projects. It cannot draft, submit or close a project.
- **`ComplianceOfficer`** — the patron eligibility and resale-compliance authority. This role enrols patrons, manages ID card status, grants and revokes authorized-shopper delegations, records resale strikes, and voids sales.
- **`AssortmentPlanner`** — the worldwide category manager. This role owns the item file, shelf allocations, direct-store-delivery vendor terms and promotional allowance windows.
- **`StoreCashier`** — the point-of-sale operator. This role opens sales, rings lines, tenders, and routes special orders. It cannot void a sale; voiding is the `ComplianceOfficer`'s exclusive power.
- **`Patron`** — the patron themselves, acting through a self-service kiosk. A patron may place and cancel their own special orders and read their own records.

Six of the seven roles are **opaque operator identities**. When `X-User-Role` is `SystemOperator`, `SurchargeFundController`, `MwrBoardOfficer`, `ComplianceOfficer`, `AssortmentPlanner` or `StoreCashier`, the accompanying `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server never compares it to any record's `id`. It is, however, recorded where the workflow demands an audit trail: a capital project stores the identifier of the controller who last submitted it in `submitted_by_user_id`, the identifier of the board officer who last decided it in `decided_by_user_id`, and the identifier of the controller who closed it in `closed_by_user_id`. Those three stored strings are compared to each other — never to an entity `id` — when the segregation-of-duties rule is enforced.

The seventh role is entity-backed. When `X-User-Role` is `Patron`, `X-User-ID` is the `id` of the acting `Patron` record; ownership checks on any resource that references a patron compare that resource's patron foreign key to `X-User-ID`. Concretely, a caller acting as `Patron` may read a patron record only when the addressed record is their own, may read a sale only when the sale's `patron_id` equals `X-User-ID`, may read or cancel a special order only when the order's `patron_id` equals `X-User-ID`, and may place a special order only when the `patron_id` in the request body equals `X-User-ID`. Any of these addressed with a different patron is rejected with `ERR_PATRON_SCOPE_VIOLATION` (HTTP 403). This ownership check applies to exactly five operations: reading one patron, reading one sale, reading one special order, placing a special order, and cancelling a special order. Reading one product carries no ownership dimension and is therefore unrestricted for the `Patron` role.

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

### 2.3. Pagination and List Ordering

Every collection-returning endpoint accepts two optional query parameters, `limit` and `offset`. When `limit` is omitted it defaults to 10; the smallest accepted value is 1 and the largest accepted value is 100. When `offset` is omitted it defaults to 0. A supplied value outside those bounds is a request-schema failure and is rejected with `ERR_INVALID_REQUEST` (HTTP 422).

List responses carry four pagination fields inside `meta`: `limit` (the page size actually applied), `offset` (the page start actually applied), `total_count` (the number of records matching the filters before paging) and `has_more` (true when records remain beyond the current page). Unless a particular endpoint's description in §4 states a different ordering, every list is sorted by `created_at` in ascending order. Two endpoints do state a different ordering: the store's fund ledger is returned in `created_at` ascending order as an append-only sequence, and the store's MWR program list is returned by `priority_rank` ascending with `created_at` ascending as the tie-break, because that is the order in which the dividend is actually distributed.

Filter query parameters, where an endpoint offers them, are additive: supplying two filters narrows the result to records matching both. Filters never change the sort order.

### 2.4. Record Identity, Timestamps and Version Counters

Every persisted record carries a server-minted `id`, a UUID string with no type prefix of any kind. Clients never supply an `id`; a client-supplied value is ignored. Every record also carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits, stamped once when the record is written and never altered.

Most record types additionally carry `updated_at`, an ISO 8601 UTC timestamp in the same format that is refreshed on every mutation, and `version`, an integer that begins at 1 when the record is created and is incremented by exactly 1 on every mutation of that record. These two properties are present on stores, patrons, shopper delegations, products, assortment allocations, sales, capital projects, MWR programs and special orders.

Two record types are append-only and therefore carry neither of them. A **sale line** — the priced record of one item rung onto one visit — is written once and never modified; a mistaken sale is voided whole rather than having lines edited or deleted. A **fund ledger entry** is likewise written once and never touched again. Both of these carry only `id` and `created_at`; both `updated_at` and `version` are absent from their representations entirely.

The `version` counter is not decoration. It is the coordination token described in §2.7, and it advances not only when a client writes a record directly but also whenever a record is mutated as a downstream consequence of some other operation. §2.9 describes those cascades and states precisely which records they touch.

### 2.5. The Logical Clock

Nothing in this system reads real wall-clock time for business purposes. All temporal reasoning — the instant stamped onto a sale, the coverage test for a delegation window, the promotional-window test for a vendor allowance, the reference instant used to resolve a shelf allocation, the thirty-day rolling window used for resale risk, and the lapse test that expires delegations at period close — is evaluated against a **logical clock** held by the server.

The logical clock's startup value is exactly `2026-08-01T00:00:00Z`. Until a caller repositions it, every one of the temporal tests above is evaluated against that fixed default. An operator acting as `SystemOperator` may reposition the clock by supplying a target instant in the `to_iso8601` field; the response reports the clock's new position in a `current_utc` field. Repositioning the clock mutates no entity and runs no sweep: it is purely a change of reference instant, and any state change that depends on the new instant happens only when a subsequent business operation or the period-close checkpoint is invoked.

All instants accepted or emitted by the API are ISO 8601 UTC. A supplied instant that cannot be parsed is a schema failure carrying `ERR_INVALID_REQUEST`.

### 2.6. Money, Basis Points and the Rounding Discipline

All money in this system is held and exchanged as an integer number of **cents**. There are no decimal money values anywhere in the API surface. A two-decimal currency amount of 5,000.00 US dollars is therefore the integer 500000, and every field name that carries money ends in `_cents` as a reminder.

All rates are held as integer **basis points**, one basis point being one ten-thousandth. A field name ending in `_bp` is a basis-point rate: 500 basis points is five percent, 1000 basis points is ten percent, 2500 basis points is twenty-five percent. To apply a basis-point rate to a cent amount, multiply the cent amount by the rate and divide by ten thousand.

Because that division rarely lands on a whole cent, the system pins one rounding rule and applies it everywhere: a non-negative rational result is rounded to the nearest whole cent, and an exact half is rounded away from zero — a remainder of exactly one half cent rounds up. This is the only rounding rule in the system; no other rounding mode is ever used for money. Two further disciplines constrain *where* the rounding happens, and both matter to the cent:

- **Round at the smallest chargeable unit, then add.** Where a rate applies to several sale lines, the rate is applied and rounded once per line, and the rounded line results are then added together. Applying the rate to a summed subtotal instead is forbidden, and it produces a different total whenever two or more lines each carry a half-cent remainder.
- **Round once, never again.** A value that has already been rounded is treated as an exact integer from that moment forward. It is never re-derived from unrounded inputs and never re-rounded.

Weight follows a different rule. Shipping is billed on whole kilograms, so a weight in grams is converted to kilograms by dividing by one thousand and **rounding up to the next whole kilogram** whenever there is any remainder at all. A shipment of 1,001 grams bills as 2 kilograms.

### 2.7. Stale-View Rejection on Shelf and Delegation Writes

Two write operations in this system commit a resource against a *shared aggregate* held on a parent record, and both are therefore guarded by an explicit version check. In each case the request body carries a non-optional field naming the `version` of the parent record that the client last observed. If that value does not equal the parent record's current `version` at the moment the request is processed, the write is refused: the client is working from a view of the parent that has since moved, and honouring the write could consume an aggregate that another writer has already claimed.

**Creating an assortment allocation** requires `expected_store_version`, carrying the client's last observed `version` of the store named by `store_id` in the body. Shelf-block facings are a store-level aggregate, so an allocation written from a stale view of the store may consume shelf capacity that another allocation already took. A mismatch is rejected with `ERR_STALE_STORE_VERSION` (HTTP 412). A successful allocation itself increments that store's `version` by 1, so a client creating several allocations against one store must re-read the store between writes.

**Creating a shopper delegation** requires `expected_delegate_patron_version`, carrying the client's last observed `version` of the patron named by `delegate_patron_id` in the body. The delegate's set of live delegations is a patron-level aggregate: another grant for the same delegate may already have been written and may already have superseded that delegate's prior delegation, in which case the current writer's picture of the delegate is out of date. A mismatch is rejected with `ERR_STALE_PATRON_VERSION` (HTTP 412). A successful grant itself increments the delegate patron's `version` by 1.

No other endpoint in this system takes a version field of any kind. Requests to every other write endpoint neither require nor accept one, and no other operation can be rejected for a stale view.

### 2.8. The Order in Which a Request Is Refused

Many operations in this system can fail for several reasons at once, and a caller must be able to predict *which* reason they will be told about. The system therefore evaluates checks in a fixed doctrinal order and returns the first failure it finds; later checks are never reached once an earlier one has failed. The doctrine reads, from first to last:

1. **Authentication** — headers present and the role recognised (`ERR_UNAUTHENTICATED`).
2. **Authorisation** — the role is permitted on this endpoint (`ERR_ROLE_NOT_PERMITTED`), and then, for the five patron-scoped operations, that the acting patron owns the addressed record (`ERR_PATRON_SCOPE_VIOLATION`).
3. **Path existence** — every identifier embedded in the URL path resolves, checked from left to right.
4. **Request schema** — required body fields present, types correct, enum members legal, integers inside their declared ranges, instants parseable (`ERR_INVALID_REQUEST`).
5. **Body reference existence** — every foreign key supplied in the body resolves.
6. **Field consistency** — cross-field rules within one payload, such as a dependent needing a sponsor or a direct-store-delivery line needing a vendor.
7. **Uniqueness** — for example a product's `sku` (`ERR_DUPLICATE_SKU`).
8. **Optimistic concurrency** — the two version checks of §2.7.
9. **State preconditions** — the target record is in a state from which the requested transition is legal.
10. **Compliance and safety** — patron card validity, sponsor card validity, channel and region eligibility, per-visit quantity limits, resale-watch restrictions.
11. **Temporal** — delegation window coverage and delegation window overlap.
12. **Referential** — the item is actually on the shelf, the route is actually available in this region.
13. **Capacity** — shelf-block facings.
14. **Fiscal** — spend caps, the tax-free rule, outlay against obligation.
15. **Segregation of duties** — the closing user is not the submitting user.

The deliberate consequence of this ordering is that **compliance outranks both referential and fiscal checks**. A patron who is not allowed to buy an item is told so before the system will discuss whether the item is even on the shelf or what it would have cost. Equally deliberately, state preconditions outrank compliance: a sale that has already been tendered is reported as not open before anyone asks whether the patron's card is still valid.

### 2.9. Cascade Discipline and Fund Recomputation

A great many operations here have consequences beyond the record the caller addressed. The system applies them **immediately and synchronously**, inside the same request, before the response is produced — there is no deferred queue and no eventual convergence. When a cascade mutates a record, that record's `updated_at` is refreshed and its `version` is incremented by 1, exactly as if it had been written directly. A single request can therefore advance the `version` of several records at once, and a client watching one of those records will see it move without having touched it.

Cascades in this system are *hop-ordered*: each hop is caused by the hop before it, and a hop's inputs are the state left behind by its predecessor, not the state at the start of the request. Where a hop recomputes a derived total from a ledger or from a set of child records, it recomputes from the current contents of that set rather than adjusting a running figure by a delta — the derived totals on a store are always the sum they claim to be, never an accumulator that could drift.

The four derived money figures on a store are all of this kind. `surcharge_fund_balance_cents` is the signed sum of the `amount_cents` of every fund ledger entry belonging to that store whose `fund` is `SURCHARGE` — collections positive, reversals and capital outlays negative. `dividend_fund_balance_cents` is the same signed sum over that store's entries whose `fund` is `DIVIDEND` — vendor promotional allowance credits in, MWR transfers out. `surcharge_obligated_cents` is the sum of `obligation_cents` over that store's capital projects currently in the `APPROVED` state, and an obligation is released from that sum when its project reaches `CLOSED`. `shipping_allowance_committed_cents` is the sum of `shipping_allowance_cents` over that store's special orders whose `state` is `LOCAL_FILL_PENDING`, `OVERSEAS_SHIP_PENDING` or `FULFILLED`.

From the first three of those the system derives the store's spending posture. The amount actually available to obligate — referred to throughout this document as the store's **available surcharge**, and equal to `surcharge_fund_balance_cents` minus `surcharge_obligated_cents` — is compared against two thresholds to produce `fund_posture`. When the available surcharge is at least 500000 cents (5,000.00 US dollars) the posture is `UNRESTRICTED`. When it is at least 100000 cents (1,000.00 US dollars) but less than 500000 cents the posture is `CONSTRAINED`. When it is below 100000 cents the posture is `FROZEN`. A newly registered store, with no ledger entries at all, therefore opens in `FROZEN`. `fund_posture` is re-derived every time any of its three inputs changes, and a single request may re-derive it more than once as successive cascade hops land.

### 2.10. Reading Nested Resources

Several read endpoints address a child collection through its parent, such as a store's fund ledger or a store's MWR programs. Path identifiers are resolved strictly from left to right, and the first identifier that fails to resolve determines the error. Asking for the fund ledger of a store that does not exist yields `ERR_STORE_NOT_FOUND` (HTTP 404); the server does not proceed to consider the child collection at all. Each addressable collection has its own dedicated not-found code — stores, patrons, products, assortment allocations, sales, sale lines, delegations, capital projects, special orders and MWR programs each have one — and the code returned always names the resource whose identifier failed, never the resource the caller was ultimately after. The same principle applies to identifiers supplied in a request body rather than a path: the missing store, patron, product or delegation is named specifically.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Store and Its Two Funds

A `SurchargeFundController` brings an installation store onto the platform by registering it with a `name` of between 1 and 120 characters, a `channel` and a `region`. The `channel` is either `COMMISSARY`, meaning a grocery operation that sells at landed cost plus surcharge, or `EXCHANGE`, meaning a general-merchandise operation that sells at cost plus a retail markup. The `region` is `CONUS`, `OVERSEAS` or `DEPLOYED`, and it is far more than a label: it drives who is eligible to shop there, whether an overseas transportation subsidy applies, what a kilogram of freight costs, and whether a special order may be routed for shipment at all.

Three pricing and capacity dials are settable at registration and each has a default. `surcharge_rate_bp` is the cost-plus surcharge applied to every sale line, expressed in basis points, defaulting to 500 — five percent — and accepted anywhere from 0 up to and including 1000. `exchange_markup_bp` is the retail markup, also in basis points, defaulting to 0 and accepted from 0 up to and including 5000. `shelf_block_capacity_facings` is how many facings a single shelf block in this store can hold, defaulting to 24 and required to be at least 1.

The no-markup grocery rule is absolute and it is enforced at registration time. A store whose `channel` is `COMMISSARY` must have `exchange_markup_bp` of 0, whether by omitting the field or by supplying zero explicitly; supplying any positive markup for a commissary is rejected with `ERR_MARKUP_FORBIDDEN_IN_COMMISSARY` (HTTP 422). This check runs after the payload has been schema-validated, so a markup of 6000 at a commissary is reported as an out-of-range integer rather than as a forbidden markup.

A freshly registered store is fiscally empty. All four derived money figures — `surcharge_fund_balance_cents`, `surcharge_obligated_cents`, `dividend_fund_balance_cents` and `shipping_allowance_committed_cents` — begin at 0, `fund_posture` is consequently derived as `FROZEN`, and `period_close_index` begins at 0. That last counter is a monotone integer stamped onto every fund ledger entry as `period_close_index` at the moment the entry is written, so an auditor can tell which accounting period a movement belongs to; it advances only when the store's period-close checkpoint runs.

Stores can be listed with optional `channel` and `region` filters, and a single store can be read to obtain all four derived fund figures together with its current `fund_posture`. Reading one store is available to fund controllers, category managers, compliance officers, board officers and cashiers alike, because almost every downstream decision — pricing, eligibility, routing, capital approval — depends on some field of the store record.

### 3.2. Enrolling Patrons and the Eligibility Matrix

A `ComplianceOfficer` enrols a patron with a `full_name` of between 1 and 120 characters, exactly as printed on the identification card, and an `id_card_class` drawn from six values: `ACTIVE_DUTY`, `RETIREE`, `DEPENDENT`, `DISABLED_VETERAN`, `GUARD_RESERVE` and `DOD_CIVILIAN_OVERSEAS`. The card class is the single most consequential field on a patron record, because it determines which channels and which regions that patron may shop.

Dependents do not hold privileges in their own right; they inherit them from a sponsor. A patron whose `id_card_class` is `DEPENDENT` must therefore supply `sponsor_patron_id`, naming another patron record, and a patron of any other class must leave `sponsor_patron_id` absent or null. Violating either half of that rule — a dependent without a sponsor, or a non-dependent with one — is rejected with `ERR_SPONSOR_REQUIRED` (HTTP 422). If a `sponsor_patron_id` is supplied but names no existing patron, the request fails earlier, with `ERR_PATRON_NOT_FOUND` (HTTP 404), because body references are resolved before cross-field consistency is judged.

Every newly enrolled patron starts clean on both of the two independent status dimensions the record carries. `card_status` starts at `VALID` with `suspension_reason` null, and `resale_watch_status` starts at `CLEAR`. The four derived compliance figures — `resale_risk_score`, `recent_sales_risk_score`, `restricted_units_30d` and `flagged_sale_count_30d` — all start at 0, and so does `manual_strike_count`, the tally of strikes an officer has recorded by hand. §3.7 explains how all of these move.

The eligibility matrix is evaluated whenever a patron attempts to transact at a store — both when a visit is opened and when a special order is placed — and it has two independent halves. The **channel** half asks whether the card class may shop that kind of store at all: `ACTIVE_DUTY`, `GUARD_RESERVE`, `RETIREE`, `DEPENDENT` and `DISABLED_VETERAN` are all authorised at both `COMMISSARY` and `EXCHANGE` stores, while `DOD_CIVILIAN_OVERSEAS` is authorised at `EXCHANGE` stores only — an overseas civilian employee has exchange privileges but no commissary privileges. A channel failure is reported as `ERR_PATRON_NOT_ELIGIBLE_FOR_CHANNEL` (HTTP 403).

The **region** half asks where the card class may travel. `ACTIVE_DUTY`, `GUARD_RESERVE` and `DEPENDENT` are authorised in all three regions, `CONUS`, `OVERSEAS` and `DEPLOYED`. A `RETIREE` is authorised in `CONUS` and `OVERSEAS` but not at a `DEPLOYED` site. A `DISABLED_VETERAN` is authorised in `CONUS` only. A `DOD_CIVILIAN_OVERSEAS` is authorised in `OVERSEAS` only — notably, not in `CONUS`. A region failure is reported as `ERR_PATRON_NOT_ELIGIBLE_IN_REGION` (HTTP 403), and because the channel half is evaluated first, a `DOD_CIVILIAN_OVERSEAS` patron attempting a `CONUS` commissary is told about the channel, not the region.

Two card-validity gates sit alongside the eligibility matrix and are evaluated before it. The transacting patron's own `card_status` must be `VALID`; a `SUSPENDED` or `REVOKED` card is refused with `ERR_PATRON_CARD_NOT_VALID` (HTTP 403), and that gate guards four operations — opening a visit, ringing a line onto a visit, tendering a visit, and placing a special order. Immediately after it, and only when the transacting patron's `id_card_class` is `DEPENDENT`, the sponsor named by `sponsor_patron_id` must itself have `card_status` of `VALID`; a dependent shopping behind a suspended or revoked sponsor is refused with `ERR_SPONSOR_CARD_NOT_VALID` (HTTP 403). The sponsor gate guards two operations — opening a visit and placing a special order — and is not re-evaluated at line-add or tender time.

Patrons can be listed with optional filters on `sponsor_patron_id` (the practical way to find a sponsor's dependents), `id_card_class`, `card_status` and `resale_watch_status`. A single patron record can be read by a compliance officer, by a cashier, and by that patron themselves; the read exposes both risk scores and both status dimensions.

### 3.3. Authorized Shoppers: Granting, Superseding and Retiring Delegations

Military resale has always allowed a patron to lend their privileges to somebody else for a defined stretch of time — an elderly retiree's neighbour, a deployed member's designated agent. This system models that as a **shopper delegation**, granted by a `ComplianceOfficer`, which names the `sponsor_patron_id` whose privileges are being lent and the `delegate_patron_id` who may use them, together with the window over which the grant is live and a fiscal ceiling.

The window is expressed by `valid_from` and `valid_to`, both ISO 8601 UTC instants, and it is **half-open**: the grant covers an instant when `valid_from` is at or before that instant and `valid_to` is strictly after it. An instant exactly equal to `valid_to` is *not* covered. `valid_to` must be strictly later than `valid_from`; a window where the end is at or before the start is a malformed payload and yields `ERR_INVALID_REQUEST` (HTTP 422). The fiscal ceiling is `per_sale_spend_cap_cents`, which must be at least 1 and which limits the total a single visit rung under this delegation may reach — §3.6 explains where that ceiling bites.

Because a delegate's live grants are a patron-level aggregate, the grant request must also carry `expected_delegate_patron_version` as described in §2.7, and a successful grant advances the delegate patron's `version` by 1.

A delegation is born with `status` of `ACTIVE`, and `status` moves through five values overall: `ACTIVE`, `REVOKED`, `EXPIRED`, `SUPERSEDED` and `SUSPENDED_BY_SPONSOR`. Two rules govern what happens when a new grant collides with an existing one, and the distinction between them is the *sponsor*:

- **Same sponsor, same delegate.** A new grant for the same pairing of `sponsor_patron_id` and `delegate_patron_id` may not overlap an existing `ACTIVE` grant of that same pairing. Because windows are half-open, two grants that merely meet at an endpoint are adjacent rather than overlapping and are perfectly legal — a grant running to a given instant and a grant starting at that same instant coexist happily. Two grants whose interiors intersect collide, and the new one is rejected with `ERR_DELEGATION_WINDOW_OVERLAP` (HTTP 409).
- **Different sponsor, same delegate.** A delegate may only shop for one sponsor at a time, so a new grant from a *different* sponsor whose window intersects an existing `ACTIVE` grant of that delegate does not collide — it displaces. The older grant transitions `ACTIVE → SUPERSEDED`, its `superseded_by_delegation_id` is set to the `id` of the new grant, its `version` is incremented, and every sale still open that was rung under the displaced grant has its compliance dimension moved `CLEARED → FLAGGED`, since those baskets were assembled under authority that has now been withdrawn.

The stale-view check on the delegate patron is evaluated *before* the same-sponsor overlap check, so a client working from an out-of-date view of the delegate is told about the version rather than about the window.

Revoking a grant is the compliance officer's manual withdrawal. It is legal only from `status` of `ACTIVE` or `SUSPENDED_BY_SPONSOR`; a grant already `REVOKED`, `EXPIRED` or `SUPERSEDED` cannot be revoked again and yields `ERR_DELEGATION_NOT_ACTIVE` (HTTP 409). An optional `reason` may accompany the withdrawal. On success `status` becomes `REVOKED`, `version` is incremented, and — exactly as with supersession — every sale still open under that grant has its compliance dimension moved `CLEARED → FLAGGED`.

Grants also lapse on their own. During the store's period-close checkpoint every grant whose `status` is `ACTIVE` and whose `valid_to` is at or before the logical clock's current instant transitions `ACTIVE → EXPIRED` with its `version` incremented. Note the inclusivity: a grant whose `valid_to` exactly equals the clock instant has already stopped covering that instant, so it lapses.

Two further transitions on a grant are never requested directly; they arrive as consequences of a sponsor's card being suspended and later reinstated, moving `ACTIVE → SUSPENDED_BY_SPONSOR` and `SUSPENDED_BY_SPONSOR → ACTIVE` respectively. §3.7 sets out those cascades in full. Independently of all of this, a grant may only be *used* as a visit's acting delegation while its `status` is `ACTIVE`; using one in any other status is refused with `ERR_DELEGATION_NOT_ACTIVE`, and that gate is applied both when the visit is opened and again when it is tendered.

Delegations can be listed with optional filters on `sponsor_patron_id`, `delegate_patron_id`, `status` and `superseded_by_delegation_id` — the last of which lets an auditor walk a chain of displacements forward — and any single grant can be read on its own.

### 3.4. The Worldwide Item File and Shelf Assortment

An `AssortmentPlanner` maintains the worldwide item file. A product record carries a `sku` — the worldwide item number, between 3 and 32 characters, which must be unique across every product in the system; a second product presenting an existing `sku` is rejected with `ERR_DUPLICATE_SKU` (HTTP 409). Alongside it sit a descriptive `name` and a `category` drawn from `GROCERY_STAPLE`, `INFANT_FORMULA`, `TOBACCO`, `ALCOHOL` and `GENERAL_MERCHANDISE`.

Three numeric attributes of a product feed downstream arithmetic. `unit_cost_cents` is the landed cost of one unit and must be at least 1; at a commissary this *is* the shelf price before surcharge. `unit_weight_grams` is the shipping weight of one unit, defaulting to 500 and required to be at least 1, and it is the only input to a special order's billable weight. `quantity_limit_per_visit` caps how many aggregate units of that product a single visit may contain; it defaults to null, meaning unlimited, and when supplied must be at least 1.

The `resale_restricted` flag, defaulting to false, marks an item as subject to resale-restriction enforcement — tobacco, alcohol, infant formula and other controlled goods that have historically been bought on-installation and resold outside it. Every unit of a flagged item that a patron buys is counted toward that patron's resale risk, and once a patron is under the heaviest watch level, flagged items may not be rung for them at all. Products can be listed with optional `category` and `resale_restricted` filters, and read individually — a read that is open even to patrons at the kiosk.

Allocating an item to a store is a separate act. An assortment allocation names the `store_id` receiving the item and the `product_id` being allocated, the `shelf_block` it occupies (a planogram block code of between 1 and 8 characters), and the number of `facings` it consumes there, which must be at least 1. Its `supply_mode` is either `WAREHOUSE`, meaning the item arrives through the distribution centre, or `DSD`, meaning direct store delivery by the vendor.

The direct-store-delivery terms are a tightly coupled group of four fields, and the system refuses any inconsistent combination with `ERR_VENDOR_REQUIRED_FOR_DSD` (HTTP 422). When `supply_mode` is `DSD`, `vendor_name` must be present. When `supply_mode` is `WAREHOUSE`, `vendor_name` must be null and `promo_allowance_bp` must be 0 — a warehouse line has no vendor to offer an allowance. And whenever `promo_allowance_bp` is greater than 0, *both* `promo_window_start` and `promo_window_end` must be present, because an allowance with no window could never be tested for collectability. `promo_allowance_bp` itself is a basis-point rate against line extended cost, defaulting to 0 and accepted from 0 up to and including 2000. Its window is **half-open**, applying while `promo_window_start` is at or before the instant under test and `promo_window_end` is strictly after it.

The shelf allocation window, by contrast, is **closed**. `effective_from` is the inclusive start and `effective_to` is the inclusive end, and `effective_to` must not be earlier than `effective_from` — an end before the start yields `ERR_INVALID_REQUEST`. The closed interval has a consequence that trips people up: two allocations that merely touch at a single endpoint instant *do* overlap, because that shared instant belongs to both of them.

That is what makes shelf capacity interesting. For the target pairing of `store_id` and `shelf_block`, the system adds up `facings` over every `ACTIVE` allocation whose closed window intersects the incoming closed window, adds the incoming `facings` to that sum, and requires the result to be no greater than the store's `shelf_block_capacity_facings`. A sum exactly equal to capacity passes; anything above it is rejected with `ERR_SHELF_CAPACITY_EXCEEDED` (HTTP 409). Allocations whose windows do not intersect the incoming one contribute nothing, and `RETIRED` allocations contribute nothing at all. This capacity test is the last check the allocation performs — it runs after the direct-store-delivery consistency group and after the stale-store-version check of §2.7 — so a client with a stale view of the store learns that before it learns anything about facings.

One further allocation field never reaches a price. `overseas_shipping_allowance_cents`, defaulting to 0 and required to be at least 0, is the appropriated-fund second-destination transportation allowance for one unit of this item at this store. It is *recorded* against the sale line and against the visit as a measure of how much subsidy the taxpayer absorbed, and it is never added to what the patron pays.

Whenever an item has to be priced or an order has to be routed, the system must decide *which* allocation governs, and it does so identically in both cases. It gathers every allocation whose `store_id` and `product_id` match the context, whose `status` is `ACTIVE`, and whose closed window contains a reference instant — where the reference instant is the visit's `business_date` when a sale line is being priced, and the logical clock's current instant when a special order is being routed. `RETIRED` allocations are never candidates. Among the candidates, the governing allocation is the one with the latest `effective_from`; where two candidates share the same `effective_from`, the one with the later `created_at` wins. If the candidate set is empty, the operation is refused with `ERR_ITEM_NOT_IN_ASSORTMENT` (HTTP 409) — no fallback allocation is ever invented.

Allocations can be listed with optional filters on `store_id`, `product_id`, `shelf_block`, `status` and `supply_mode`, and read individually. Retiring one is the planner's way of pulling an item off a shelf: it is legal only from `status` of `ACTIVE`, and retiring an allocation that is already `RETIRED` yields `ERR_ASSORTMENT_NOT_ACTIVE` (HTTP 409). An optional `reason` may accompany the retirement. On success the allocation moves `ACTIVE → RETIRED`, its facings stop counting toward the shelf block's aggregate, and its `version` is incremented — and then a three-hop cascade runs. First, every special order of the same `store_id` and `product_id` whose `state` is `OVERSEAS_SHIP_PENDING` is moved to `CANCELLED` with its `cancelled_reason` set to `ASSORTMENT_RETIRED`, because there is no longer a live allocation to fill it from. Second, and caused by the first, the store's `shipping_allowance_committed_cents` is recomputed, which releases each cancelled order's `shipping_allowance_cents` from the commitment total. Third, and caused by the second, the store's `version` is incremented. Orders in `LOCAL_FILL_PENDING`, `SUBMITTED`, `FULFILLED` or `CANCELLED` are untouched by this cascade.

### 3.5. Ringing a Visit: Opening a Sale and Pricing Its Lines

A **sale** in this system is one visit to one register. A `StoreCashier` opens it by naming the `store_id` where the transaction is happening and the `patron_id` whose privileges are being used — which is to say, the account being charged. When the person at the register is an authorized shopper rather than the privilege holder, the cashier additionally supplies `acting_delegation_id`, naming the grant being exercised; when the patron is shopping on their own card the field is omitted or null.

Opening a visit is where the whole eligibility gate fires, and the order matters because a cashier needs one actionable message rather than a list. After the payload has been schema-checked and after every identifier in it has been resolved, the system asks in sequence: is the acting delegation, if one was named, currently `ACTIVE` (`ERR_DELEGATION_NOT_ACTIVE`); is the patron's own `card_status` `VALID` (`ERR_PATRON_CARD_NOT_VALID`); if the patron is a `DEPENDENT`, is their sponsor's `card_status` `VALID` (`ERR_SPONSOR_CARD_NOT_VALID`); is the patron's `id_card_class` authorised for this store's `channel` (`ERR_PATRON_NOT_ELIGIBLE_FOR_CHANNEL`); is it authorised for this store's `region` (`ERR_PATRON_NOT_ELIGIBLE_IN_REGION`); and finally, does the acting delegation's half-open window actually cover this visit (`ERR_DELEGATION_WINDOW_NOT_COVERING`, HTTP 409)?

That last question needs the visit's own instant, and the visit gets one at creation: `business_date` is stamped from the logical clock's current position and is the date the sale is booked to for every purpose afterwards — allocation resolution, promotional-window evaluation, delegation coverage and the rolling risk window all read it. Coverage means `valid_from` at or before `business_date` and `valid_to` strictly after it, with a `business_date` exactly equal to `valid_to` therefore falling outside the grant.

A newly opened visit sits at `tender_state` of `OPEN` on the money axis and `compliance_state` of `CLEARED` on the compliance axis, with `line_count` of 0 and every money figure — `merchandise_cents`, `markup_total_cents`, `surcharge_total_cents`, `tax_cents`, `total_due_cents`, `provisional_allowance_cents` and `subsidized_shipping_cents` — at 0. Both `settled_allowance_cents` and `allowance_variance_cents` are null until tender writes them, `voided_reason` is null, and it will stay null unless the visit is voided.

Ringing an item onto the visit is a separate call carrying just two fields, `product_id` and `quantity`, where `quantity` must be at least 1. Lines are never deleted or amended; a sale line records `sale_id`, naming the visit it belongs to, and is otherwise entirely computed. Before anything is priced, four gates run in this order: the visit's `tender_state` must still be `OPEN`, or the request is refused with `ERR_SALE_NOT_OPEN` (HTTP 409); the patron's `card_status` must still be `VALID`; the per-visit quantity limit must not be breached; and the resale watch must not forbid the item. Only then does the system resolve the governing allocation, refusing the line with `ERR_ITEM_NOT_IN_ASSORTMENT` if none covers the visit's `business_date`.

The **per-visit quantity limit** is aggregate, not per-line. When the product's `quantity_limit_per_visit` is not null, the system adds the `quantity` of every existing line of this visit for that same product to the `quantity` now being requested, and requires the total to be no greater than the limit. A total exactly equal to the limit passes; a total above it is refused with `ERR_QUANTITY_LIMIT_EXCEEDED` (HTTP 409). Three units requested twice against a limit of five therefore succeeds and then fails, and the patron leaves with three.

The **resale watch** gate is blunt: when the patron's `resale_watch_status` is `RESTRICTED`, no line of any product whose `resale_restricted` is true may be added, and the attempt is refused with `ERR_RESTRICTED_ITEM_BLOCKED_BY_WATCH` (HTTP 403). Unrestricted items still ring normally for such a patron, and a patron at `WATCH` or `CLEAR` is not blocked at all.

Pricing a line is where the two channels part company. The system reads the product's `unit_cost_cents` and the store's `channel`. At a `COMMISSARY` store the line's `unit_price_cents` is exactly `unit_cost_cents` — no markup, ever, under any configuration. At an `EXCHANGE` store the line's `unit_price_cents` is `unit_cost_cents` plus the markup, where the markup is the product's `unit_cost_cents` multiplied by the store's `exchange_markup_bp`, divided by ten thousand, and rounded to the nearest whole cent with an exact half rounding up. Note carefully that the markup is rounded **per unit**, before quantity is involved: the rounded per-unit price is what gets multiplied.

From that per-unit price the rest of the line follows. `extended_cents` is `unit_price_cents` multiplied by `quantity`. `line_markup_cents` is the difference between `unit_price_cents` and the product's `unit_cost_cents`, multiplied by `quantity` — which is 0 at every commissary line by construction. `restricted_units` is `quantity` when the product's `resale_restricted` is true and 0 otherwise.

The transportation subsidy is recorded on the line and never priced into it. `line_shipping_allowance_cents` is the governing allocation's `overseas_shipping_allowance_cents` multiplied by `quantity`, but only when *both* conditions hold: the store's `region` is `OVERSEAS`, and the governing allocation's `supply_mode` is `WAREHOUSE`. A `DEPLOYED` store, a `CONUS` store, or an `OVERSEAS` store supplied by a `DSD` vendor all record 0 here.

Once the line is priced, the visit is rolled up, and the rounding order is pinned. For each line of the visit, walked in `created_at` ascending order, `line_surcharge_cents` is that line's `extended_cents` multiplied by the store's `surcharge_rate_bp`, divided by ten thousand, and rounded to the nearest whole cent with an exact half rounding up. The visit's `surcharge_total_cents` is then the sum of those already-rounded per-line figures. Applying the surcharge rate once to the visit's subtotal instead is forbidden and produces a different cent total whenever two or more lines each carry a half-cent remainder. The remaining rollups are plain sums: `merchandise_cents` is the sum of `extended_cents` over the lines, `markup_total_cents` the sum of `line_markup_cents`, `subsidized_shipping_cents` the sum of `line_shipping_allowance_cents`, and `line_count` the number of lines. `tax_cents` is always 0 — commissary and exchange sales are tax-free and there is no configuration in which they are not. Finally `total_due_cents` is `merchandise_cents` plus `markup_total_cents` plus `surcharge_total_cents` plus `tax_cents`.

Every line add also refreshes the visit's `provisional_allowance_cents` and the individual lines' `line_allowance_cents` as described in §3.6, recomputes both of the patron's risk scores as described in §3.7 — a recomputation that can suspend the card on the spot and cascade from there — and increments the visit's `version` by 1. Sales can be listed with optional filters on `store_id`, `patron_id`, `acting_delegation_id`, `tender_state` and `compliance_state`, and read individually with every computed money field exposed. Sale lines have their own listing, filterable by `sale_id` or by `product_id`, and can be read individually with their priced fields.

### 3.6. Tendering, the Vendor Allowance Settlement, and the Fund Ledger

Tender is the moment money and compliance meet. A `StoreCashier` tenders an open visit, optionally declaring `collected_tax_cents`, and the system runs eight gates in a fixed order before it moves anything. The visit's `tender_state` must be `OPEN`, or the attempt is refused with `ERR_SALE_NOT_OPEN`. If the visit named an acting delegation, that grant's `status` must still be `ACTIVE`, or the attempt is refused with `ERR_DELEGATION_NOT_ACTIVE`. The visit must have at least one line — `line_count` of at least 1 — or it is refused with `ERR_SALE_HAS_NO_LINES` (HTTP 409). The visit's `compliance_state` must be `CLEARED`, or it is refused with `ERR_SALE_COMPLIANCE_FLAGGED` (HTTP 409). The patron's `card_status` must be `VALID`. The acting delegation's half-open window must still cover the visit's `business_date`. The visit's `total_due_cents` must be no greater than the acting delegation's `per_sale_spend_cap_cents`, or the attempt is refused with `ERR_DELEGATION_SPEND_CAP_EXCEEDED` (HTTP 402) — a total exactly equal to the cap passes. And `collected_tax_cents`, when supplied at all, must be exactly 0, or the attempt is refused with `ERR_TAX_COLLECTION_FORBIDDEN` (HTTP 422).

The relative position of the delegation-status gate and the compliance gate is worth dwelling on, because in the ordinary case the delegation gate masks the compliance one. When a visit gets flagged because its sponsor's card was suspended, the acting grant is simultaneously suspended by that same cascade, so a tender attempt is refused for the grant's status before compliance is even considered. There is exactly one arrangement in which the compliance refusal surfaces on its own: a flag applied through the patron-mediated strike path of §3.7, which touches no delegation at all and therefore leaves an `ACTIVE` grant behind a `FLAGGED` basket.

Once the gates pass, the vendor promotional allowance is settled. The allowance exists because direct-store-delivery vendors fund promotions in basis points of what their goods actually rang, and the agency may only bank a claim that was filed while the vendor's window was open. The system computes a candidate amount per line: for each line of the visit it resolves the governing allocation, and when that allocation's `supply_mode` is `DSD` and its `promo_allowance_bp` is greater than 0, the candidate is that line's `extended_cents` multiplied by `promo_allowance_bp`, divided by ten thousand, and rounded to the nearest whole cent with an exact half rounding up; otherwise the candidate for that line is 0. Rounding again happens per line, and the rounded per-line candidates are then added — the same pinned order as the surcharge rollup.

What differs between the two allowance figures is only *which instant* the promotional window is tested against, and the window test is half-open in both cases: the allowance applies when `promo_window_start` is non-null and at or before the instant under test and `promo_window_end` is strictly after it.

- The **provisional** figure, held in `provisional_allowance_cents` and refreshed on every line add, tests each governing allocation's window against the visit's `business_date`. It is the forward-looking claim that the allowance will be filed for the day the sale was booked, and each line's own contribution to it is stored on that line as `line_allowance_cents`.
- The **settled** figure, held in `settled_allowance_cents` and written exactly once at tender, tests each governing allocation's window against the logical clock's instant **at tender**. It is the chronological claim that only a claim filed while the vendor window was still open is collectible. When the clock has advanced past a `promo_window_end` between the line add and the tender, the settled figure is 0 for that line while the provisional figure was positive.

The difference between them is recorded: `allowance_variance_cents` is `settled_allowance_cents` minus `provisional_allowance_cents`, written at tender alongside the settled figure and therefore negative whenever a window lapsed mid-basket. Only `settled_allowance_cents` ever reaches the dividend fund; the provisional figure is a planning number and posts nowhere.

With the allowance settled, two ledger entries may be written, in this order. First, unconditionally, an entry against the `SURCHARGE` fund with `entry_type` of `SURCHARGE_COLLECTION` and `amount_cents` equal to the visit's `surcharge_total_cents` as a positive amount, with `source_ref_kind` of `SALE` and `source_ref_id` naming the visit. Second, only when `settled_allowance_cents` is greater than 0, an entry against the `DIVIDEND` fund with `entry_type` of `ALLOWANCE_CREDIT` and `amount_cents` equal to `settled_allowance_cents` as a positive amount, again with `source_ref_kind` of `SALE` and `source_ref_id` naming the visit.

Fund ledger entries are the audit spine of the whole system and they are strictly append-only: each carries `store_id` identifying the fund-holding store, a `fund` of either `SURCHARGE` — the capital improvement fund — or `DIVIDEND` — exchange earnings destined for morale, welfare and recreation — and an `entry_type` drawn from `SURCHARGE_COLLECTION`, `SURCHARGE_REVERSAL`, `CAPITAL_OUTLAY`, `ALLOWANCE_CREDIT`, `ALLOWANCE_REVERSAL` and `DIVIDEND_TRANSFER`. The `amount_cents` is signed: credits are positive, while reversals, capital outlays and dividend transfers are negative. Each entry also records `balance_after_cents`, the running balance of its own pairing of `store_id` and `fund` as at that entry, computed by walking that pairing's entries in `created_at` ascending order and breaking ties on equal `created_at` by `entry_type` in ascending alphabetical order. Each entry stamps the store's `period_close_index` as it stood when the entry was written. And each entry records `source_ref_kind` — `SALE`, `CAPITAL_PROJECT`, `MWR_PROGRAM` or `SPECIAL_ORDER` — together with `source_ref_id`, the identifier of the originating record; that identifier is retained for audit purposes only and is deliberately **not** enforced as a foreign key, so a ledger row survives intact regardless of what happens to whatever produced it. A store's ledger can be read in `created_at` ascending order with optional `fund` and `entry_type` filters.

Writing those entries sets off a four-hop cascade. The first hop recomputes the store's `surcharge_fund_balance_cents` and `dividend_fund_balance_cents` from the ledger. The second hop, caused by the first, re-derives the store's `fund_posture` from its available surcharge. The third hop, caused by the second, is the one worth watching: when the freshly derived `fund_posture` is `UNRESTRICTED`, every capital project of this store currently in `AWAITING_FUNDS` is walked in `created_at` ascending order, and each one whose `obligation_cents` is no greater than the available surcharge *at the moment that project is walked* is auto-transitioned to `APPROVED`, with its `obligation_cents` added to the store's `surcharge_obligated_cents` before the next project is considered. A project too large for what remains is left in `AWAITING_FUNDS` and the walk continues to the next one. The fourth hop, caused by the third, re-derives `fund_posture` once more now that the new obligations are booked — so a tender can leave a store in `CONSTRAINED` or even `FROZEN` despite having just collected surcharge.

Alongside the fund cascade, tender recomputes both of the patron's risk scores and re-derives both patron status dimensions, which may fire the threshold-driven card suspension and its own three-hop cascade. Finally the store's `version` and the visit's `version` are each incremented by 1, and the visit's `tender_state` moves `OPEN → TENDERED`. The `compliance_state` axis is untouched by tender: no sale-scoped operation ever writes it.

Voiding is the `ComplianceOfficer`'s remedy and the only way to undo a visit, since lines cannot be removed. The officer supplies `voided_reason`, one of `RESALE_VIOLATION`, `OPERATOR_ERROR` or `COMPLIANCE_HOLD`. A visit may be voided from `tender_state` of either `OPEN` or `TENDERED`; a visit already at `VOIDED` cannot be voided again and yields `ERR_SALE_ALREADY_VOIDED` (HTTP 409). The two source states diverge sharply in what they do to the funds:

- Voiding from `OPEN → VOIDED` writes **no ledger entry at all**, because nothing was ever collected on an open basket. The supplied `voided_reason` is recorded, and the patron's risk scores are recomputed with this visit removed from every input set.
- Voiding from `TENDERED → VOIDED` reverses the collection. An entry is appended against the `SURCHARGE` fund with `entry_type` of `SURCHARGE_REVERSAL` and `amount_cents` equal to the negative of the visit's `surcharge_total_cents`, with `source_ref_kind` of `SALE` and `source_ref_id` naming the visit. When the visit's `settled_allowance_cents` is greater than 0, a second entry is appended against the `DIVIDEND` fund with `entry_type` of `ALLOWANCE_REVERSAL` and `amount_cents` equal to the negative of `settled_allowance_cents`, likewise referencing the sale. The store's `surcharge_fund_balance_cents`, `dividend_fund_balance_cents` and `fund_posture` are then recomputed, and because the reversal is the exact negation of the collection, the surcharge balance returns precisely to its pre-tender value — the compensating pair leaves no drift. The patron's risk scores are recomputed with this visit excluded, and the store's `version` and the visit's `version` are each incremented by 1.

### 3.7. Resale Compliance: Scoring, Watch Levels and the Card Lifecycle

Resale abuse is the compliance problem this system was built to see. A patron record carries **two entirely independent status dimensions**, and they advance separately. `card_status` is the entitlement axis and takes the values `VALID`, `SUSPENDED` and `REVOKED`, with `REVOKED` terminal. `resale_watch_status` is the compliance axis and takes the values `CLEAR`, `WATCH` and `RESTRICTED`. A patron can be `SUSPENDED` on the card axis while sitting at `CLEAR` on the watch axis, and can be `RESTRICTED` on the watch axis while remaining perfectly `VALID` on the card axis. Every enrolled patron begins at `VALID` on the card axis and `CLEAR` on the watch axis.

Both axes are driven by a single scoring rule, evaluated over a set of the patron's sales. For a given input set, the score is the sum of two weighted terms, capped at 100. The first term is 12 points for every unit of resale-restricted merchandise in the set — that is, 12 multiplied by the total of `restricted_units` across all sale lines of all sales in the set. The second term is 25 points for each strike, where the strike count is the number of sales in the set whose `compliance_state` is `FLAGGED` plus the patron's `manual_strike_count`. The two terms are added and the result is capped at 100; the score is always a whole number between 0 and 100 inclusive. A single manually recorded strike is therefore worth as much as a little over two units of a controlled item.

Which sales enter the set is where the two scores diverge, and the divergence is deliberate. The common qualification is the same for both: only sales of that patron whose `tender_state` is `OPEN` or `TENDERED` qualify. A `VOIDED` sale is excluded from **both** variants entirely — voiding a basket really does erase its compliance consequence. The patron's currently open basket does qualify, which is why ringing a controlled item moves the score immediately rather than at tender.

- The **rolling thirty-day** variant writes `resale_risk_score` and drives the watch axis. Its input set is filtered by *age*: qualifying sales whose `business_date` is at or after the logical clock's current instant minus thirty days, and at or before the logical clock's current instant. There is no cap on how many sales enter.
- The **last-five-sales** variant writes `recent_sales_risk_score` and drives the card axis. Its input set is filtered by *rank*, not age: the five most recent qualifying sales, ordered by `business_date` descending with `created_at` descending as the tie-break. A sale older than thirty days still counts if it is among the five most recent, and a sixth sale inside the thirty-day window does not count at all.

Two audit counters are maintained over the rolling thirty-day input set alongside the score. `restricted_units_30d` is the total units of resale-restricted product the patron bought inside that set, and `flagged_sale_count_30d` is the number of sales in that set whose `compliance_state` is `FLAGGED`.

The watch axis is re-derived from `resale_risk_score` on every recomputation. A score of at least 85 puts the patron at `RESTRICTED`; a score of at least 60 but below 85 puts them at `WATCH`; a score below 60 puts them at `CLEAR`. Both thresholds are inclusive at their lower bound. The system-driven transitions therefore read `CLEAR → WATCH` when the score reaches 60 and stays under 85, and `WATCH → RESTRICTED` when it reaches 85; arriving at `RESTRICTED` is what causes any subsequent attempt to ring a `resale_restricted` product for that patron to be refused with `ERR_RESTRICTED_ITEM_BLOCKED_BY_WATCH`. Both watch transitions require that the patron's `card_status` is not `REVOKED`, and each increments the patron's `version` by 1.

The card axis has its own threshold. When `recent_sales_risk_score` reaches 80 and the patron's `card_status` is `VALID`, the system suspends the card on the spot: `card_status` moves `VALID → SUSPENDED` with `suspension_reason` set to `RISK_THRESHOLD`, and the full three-hop cascade described below runs. All of this scoring and re-derivation happens after a line is rung, after a visit is tendered, after a visit is voided, and after a compliance review is recorded. A `REVOKED` card is frozen: its `resale_watch_status` stays at whatever value it held, and no further risk recomputation is applied to it.

A `ComplianceOfficer` also moves the card axis by hand, supplying an `action` of `SUSPEND`, `REINSTATE` or `REVOKE` together with an optional `reason`. Each action is legal only from a particular state.

**Suspension** (`VALID → SUSPENDED`, legal only while `card_status` is `VALID`) sets `suspension_reason` to `ADMIN_ACTION` and then runs three ordered cascade hops. Hop one: every patron whose `sponsor_patron_id` names this patron and whose own `card_status` is `VALID` is itself moved to `SUSPENDED` with `suspension_reason` set to `SPONSOR_SUSPENDED` — a sponsor losing their card takes their dependents down with them. Hop two, caused by hop one: every shopper delegation whose `delegate_patron_id` names one of those newly suspended dependents and whose `status` is `ACTIVE` is moved `ACTIVE → SUSPENDED_BY_SPONSOR`. Hop three, caused by hop two: every sale whose `acting_delegation_id` names one of those newly suspended delegations and whose `tender_state` is `OPEN` has its compliance axis moved `CLEARED → FLAGGED`, which blocks its tender until it is cleared. Every entity mutated anywhere in that chain has its `version` incremented by 1. The risk-threshold suspension described above runs exactly the same three hops; only `suspension_reason` differs, being `RISK_THRESHOLD` rather than `ADMIN_ACTION`.

**Reinstatement** (`SUSPENDED → VALID`, legal only while `card_status` is `SUSPENDED`) clears `suspension_reason` to null and then runs three compensating hops that mirror the suspension precisely. Hop one: every patron whose `sponsor_patron_id` names this patron, whose `card_status` is `SUSPENDED` **and** whose `suspension_reason` is `SPONSOR_SUSPENDED` is restored to `VALID` with `suspension_reason` cleared to null — a dependent suspended for its own reasons is deliberately left suspended. Hop two, caused by hop one: every delegation whose `delegate_patron_id` names one of those restored dependents and whose `status` is `SUSPENDED_BY_SPONSOR` is moved back `SUSPENDED_BY_SPONSOR → ACTIVE`. Hop three, caused by hop two: every sale whose `acting_delegation_id` names one of those reactivated delegations, whose `tender_state` is `OPEN` and whose `compliance_state` is `FLAGGED` is moved back `FLAGGED → CLEARED`. Again every mutated entity's `version` is incremented by 1.

**Revocation** (`SUSPENDED → REVOKED`, legal only while `card_status` is `SUSPENDED`, and terminal) leaves `suspension_reason` exactly as it stands. Its cascade is broader in one respect and narrower in another: every shopper delegation in which this patron appears **either** as `sponsor_patron_id` **or** as `delegate_patron_id`, and whose `status` is `ACTIVE` or `SUSPENDED_BY_SPONSOR`, is moved to `REVOKED`. The patron's `resale_watch_status` is frozen at its current value and no further risk recomputation ever touches the record.

Separately from the card axis, the officer records a compliance judgement by supplying a `decision` of either `CONFIRM_STRIKE` or `CLEAR_WATCH`. Both decisions recompute both risk scores and re-derive the watch axis from the fresh figures, and neither one touches any delegation — this is the patron-mediated path, and it is what makes a flagged basket with a still-`ACTIVE` grant possible.

`CONFIRM_STRIKE` increments `manual_strike_count` by 1, which adds 25 points to the recomputed `resale_risk_score`, and then re-derives `resale_watch_status` from that fresh score — typically moving a clean patron `CLEAR → WATCH`. It also flags the patron's baskets directly: every sale whose `patron_id` names this patron and whose `tender_state` is `OPEN` has its compliance axis moved `CLEARED → FLAGGED` with its `version` incremented, regardless of whether it carries an acting delegation. Recording a strike requires that the patron's `card_status` is not `REVOKED`.

`CLEAR_WATCH` is the pardon. It resets `manual_strike_count` to 0, recomputes both `resale_risk_score` and `recent_sales_risk_score`, and re-derives `resale_watch_status` from the fresh rolling score — which lands at `CLEAR` whenever that score is below 60. It is legal from a `resale_watch_status` of either `WATCH` or `RESTRICTED`, and so it serves as both `RESTRICTED → CLEAR` and `WATCH → CLEAR`, closing the cycle `CLEAR → WATCH → RESTRICTED → CLEAR`. It also un-flags the baskets: every sale whose `patron_id` names this patron, whose `tender_state` is `OPEN` and whose `compliance_state` is `FLAGGED` is moved `FLAGGED → CLEARED` with its `version` incremented.

### 3.8. Special Orders for Deployed and Remote Sites

Not everything a patron needs is on the shelf, particularly at a remote or deployed site. A special order lets a `StoreCashier` — or the patron themselves, at the kiosk — request an item for later fulfilment. The order names the `store_id` placing it, the `patron_id` ordering, the `product_id` wanted and the `quantity`, which must be at least 1. Placing an order runs the same eligibility gate as opening a visit, in the same order: the patron's `card_status` must be `VALID`, a `DEPENDENT`'s sponsor must also hold a `VALID` card, and the patron's `id_card_class` must be authorised for the store's `channel` and then for its `region`. A patron placing their own order must also match the `patron_id` in the body, per §2.1.

A newly placed order sits at `state` of `SUBMITTED` with `route` still null, and every shipping figure — `billable_weight_kg`, `gross_ship_cents`, `patron_share_cents` and `shipping_allowance_cents` — at 0, with `cancelled_reason` null.

Routing is the fork. A cashier supplies a `route` of either `LOCAL_FILL` or `OVERSEAS_SHIP`, and the order may only be routed while its `state` is `SUBMITTED`; routing anything else yields `ERR_SPECIAL_ORDER_NOT_ROUTABLE` (HTTP 409). Two referential checks then run, in this order. First, a governing allocation must exist for this store and product at the logical clock's current instant — resolved exactly as described in §3.4, with an empty candidate set refused as `ERR_ITEM_NOT_IN_ASSORTMENT`. Second, and only after that, a `route` of `OVERSEAS_SHIP` requires the store's `region` to be `OVERSEAS` or `DEPLOYED`; requesting overseas shipment from a `CONUS` store is refused with `ERR_ROUTE_NOT_AVAILABLE_IN_REGION` (HTTP 409).

Whichever branch is taken, billable weight is computed the same way: the product's `unit_weight_grams` multiplied by the order's `quantity`, divided by one thousand, and **rounded up** to the next whole kilogram whenever there is any remainder. That figure is stored as `billable_weight_kg`. The freight rate then depends purely on the store's `region`: a `CONUS` store bills 0 cents per kilogram, an `OVERSEAS` store bills 210 cents per kilogram, and a `DEPLOYED` store bills 340 cents per kilogram.

The two branches then diverge completely.

- **`SUBMITTED → LOCAL_FILL_PENDING`.** The order will be filled from local stock, so no freight is incurred at all: `gross_ship_cents`, `patron_share_cents` and `shipping_allowance_cents` are all set to 0. The store's `shipping_allowance_committed_cents` is left unchanged, and only the order's own `version` is incremented by 1.
- **`SUBMITTED → OVERSEAS_SHIP_PENDING`.** The freight is real and it is split. `gross_ship_cents` is `billable_weight_kg` multiplied by the region's rate per kilogram. The patron pays a quarter of it: `patron_share_cents` is `gross_ship_cents` multiplied by 2500 basis points, divided by ten thousand, and rounded to the nearest whole cent with an exact half rounding up. The taxpayer absorbs the rest, subject to a ceiling: `shipping_allowance_cents` is the smaller of 15000 cents (150.00 US dollars) and the larger of 0 and the difference between `gross_ship_cents` and `patron_share_cents` — so the allowance is never negative and never exceeds the ceiling, and a shipment whose subsidised portion would have run to 200.00 US dollars is capped at 150.00. That allowance is then added to the store's `shipping_allowance_committed_cents`, and both the store's `version` and the order's `version` are incremented by 1.

Both pending branches join at the same place. During the store's period-close checkpoint, every special order of that store whose `state` is `LOCAL_FILL_PENDING` or `OVERSEAS_SHIP_PENDING` is moved to `FULFILLED` with its `version` incremented. Fulfilment does **not** release the commitment: a `FULFILLED` order keeps its `shipping_allowance_cents` inside the store's `shipping_allowance_committed_cents`, because the money really was spent.

Cancellation is available to the cashier and to the ordering patron, and requires `cancelled_reason`, either `PATRON_REQUEST` or `ASSORTMENT_RETIRED`. An order may be cancelled from `state` of `SUBMITTED`, `LOCAL_FILL_PENDING` or `OVERSEAS_SHIP_PENDING`; an order already `FULFILLED` or `CANCELLED` is terminal and the attempt is refused with `ERR_SPECIAL_ORDER_TERMINAL` (HTTP 409). Cancelling from `OVERSEAS_SHIP_PENDING → CANCELLED` subtracts exactly that order's `shipping_allowance_cents` from the store's `shipping_allowance_committed_cents`, returning the commitment total precisely to its pre-routing value, and increments both the store's `version` and the order's `version` by 1. Cancelling from `SUBMITTED → CANCELLED` — or from `LOCAL_FILL_PENDING`, which is the same fiscal situation — finds `shipping_allowance_cents` already at 0, so the store's committed total is unchanged and only the order's own `version` is incremented. In every case `cancelled_reason` is recorded from the request. The `ASSORTMENT_RETIRED` reason is also what the system writes on the orders it cancels itself, when a planner retires the allocation those orders depended on.

Special orders can be listed with optional filters on `store_id`, `patron_id`, `product_id`, `state` and `route`, and read individually — a read available to the cashier, to a compliance officer, and to the ordering patron.

### 3.9. Fund Governance: Capital Projects, MWR Programs and the Period-Close Checkpoint

The two funds are spent in two very different ways, and the split of authority between them is the segregation-of-duties backbone of this system. Surcharge money buys capital improvements to the stores, proposed by the fund controller but decided only by the board. Dividend money funds community programs registered by the board and distributed automatically at period close.

**Registering a programme.** An `MwrBoardOfficer` registers a morale, welfare and recreation programme against the `store_id` whose dividend will fund it, giving it a `name`, a `priority_rank` of at least 1 and a `funding_ceiling_cents` of at least 1. The `priority_rank` is a waterfall position — a *lower* rank is filled first — and ties on equal rank are broken by `created_at` ascending. A programme's `status` may be set at registration to `ACTIVE`, meaning it participates in the waterfall, or `SUSPENDED`, meaning it is skipped; it defaults to `ACTIVE`. Its `ytd_funded_cents` begins at 0 and is thereafter derived from the ledger: it is the sum of the negated `amount_cents` of every ledger entry whose `entry_type` is `DIVIDEND_TRANSFER` and whose `source_ref_id` names this programme, so that a transfer stored as a negative movement out of the fund reads as a positive figure funded into the programme. A store's programmes can be listed in waterfall order with an optional `status` filter, and any single programme can be read to obtain its `ytd_funded_cents`.

**Drafting a capital project.** A `SurchargeFundController` drafts a project against the `store_id` whose surcharge fund will pay for it, with a `title` of between 1 and 160 characters and a `requested_amount_cents` of at least 1 representing the construction or equipment request *excluding* contingency. The request amount is fixed at creation and never changes afterwards.

Contingency is added by tier, and the evaluation order is pinned: **the tier is selected from the contingency-free request amount, never from the obligation that already contains the contingency.** When `requested_amount_cents` is below 500000 cents (5,000.00 US dollars), `contingency_bp` is 1000 basis points — ten percent. When it is at least 500000 cents but below 2000000 cents (20,000.00 US dollars), `contingency_bp` is 700 basis points. When it is at or above 2000000 cents, `contingency_bp` is 500 basis points. Small projects carry the fattest contingency because small projects are the ones that surprise you. From that rate, `contingency_cents` is `requested_amount_cents` multiplied by `contingency_bp`, divided by ten thousand, and rounded to the nearest whole cent with an exact half rounding up. Finally `obligation_cents` is `requested_amount_cents` plus `contingency_cents`, and that obligation figure — not the request amount — is what gets reserved against the surcharge fund while the project is approved. A project is born at `state` of `DRAFT` with `revision_count` at 0 and `submitted_by_user_id`, `decided_by_user_id` and `outlay_cents` all null.

A project's `state` moves through seven values: `DRAFT`, `SUBMITTED`, `RETURNED_FOR_REVISION`, `AWAITING_FUNDS`, `APPROVED`, `REJECTED` and `CLOSED`, of which `REJECTED` and `CLOSED` are terminal.

**Submission.** The controller submits a project for board decision. Submission is legal from `state` of either `DRAFT` or `RETURNED_FOR_REVISION`; from anything else it is refused with `ERR_PROJECT_NOT_DRAFT` (HTTP 409). On success `submitted_by_user_id` is set to the submitting caller's `X-User-ID` and `version` is incremented by 1. The two source states differ in exactly one respect: `DRAFT → SUBMITTED` leaves `revision_count` alone, while `RETURNED_FOR_REVISION → SUBMITTED` increments `revision_count` by 1, because that counter tallies only re-submissions. This is the cycle in the project's lifecycle — `SUBMITTED → RETURNED_FOR_REVISION → SUBMITTED` may run as many times as the board insists.

**The board decision.** An `MwrBoardOfficer` — and only an `MwrBoardOfficer` — renders the decision, supplying a `decision` of `APPROVE`, `RETURN` or `REJECT` together with an optional `note`. The project must be at `state` of `SUBMITTED`; deciding a project in any other state is refused with `ERR_PROJECT_NOT_SUBMITTED` (HTTP 409). Every one of the three decisions writes `decided_by_user_id` from the deciding caller's `X-User-ID` and increments `version` by 1. Beyond that they diverge, and `APPROVE` itself forks in two:

- **`SUBMITTED → APPROVED`** is taken when the store's `fund_posture` is `UNRESTRICTED` **and** the project's `obligation_cents` is no greater than the store's available surcharge (its `surcharge_fund_balance_cents` less its `surcharge_obligated_cents`). The obligation is booked: `obligation_cents` is added to the store's `surcharge_obligated_cents`, the store's `fund_posture` is re-derived — which may itself drop the store to `CONSTRAINED` or `FROZEN` — and the store's `version` is incremented by 1 alongside the project's.
- **`SUBMITTED → AWAITING_FUNDS`** is taken on the very same `APPROVE` decision when either condition fails: the store's `fund_posture` is anything other than `UNRESTRICTED`, or the project's `obligation_cents` exceeds the store's available surcharge. This is not an error — an approval the fund cannot presently carry parks the project rather than refusing it. `decided_by_user_id` is written exactly as on the approved branch, but **no obligation is booked** and the store's `surcharge_obligated_cents` is left untouched.
- **`SUBMITTED → RETURNED_FOR_REVISION`** is taken on a `RETURN` decision. In addition to writing `decided_by_user_id`, it **clears `submitted_by_user_id` back to null**, because the next submission may come from a different controller and the segregation-of-duties check at close must reflect whoever submits last.
- **`SUBMITTED → REJECTED`** is taken on a `REJECT` decision and is terminal. No obligation is ever booked, and `submitted_by_user_id` is left as it stands.

A parked project is not forgotten. Whenever a store's `fund_posture` is recomputed — which happens after a visit is tendered and again during the period-close checkpoint — every project of that store at `state` of `AWAITING_FUNDS` is walked in `created_at` ascending order, and a project transitions `AWAITING_FUNDS → APPROVED` when the recomputed `fund_posture` is `UNRESTRICTED` and its `obligation_cents` is no greater than the store's available surcharge *at the moment that project is walked*. Each project so approved adds its `obligation_cents` to the store's `surcharge_obligated_cents` before the next is considered, the store's `fund_posture` is re-derived again afterwards, and both the store's `version` and each approved project's `version` are incremented by 1. A project too large for the remaining headroom simply stays parked while the walk moves on to the next one.

**Closing out.** When the work is done the controller closes the project with its actual `outlay_cents`. Three gates run in order. The project must be at `state` of `APPROVED`, or the attempt is refused with `ERR_PROJECT_NOT_APPROVED` (HTTP 409). The `outlay_cents` must be no greater than the project's `obligation_cents`, or the attempt is refused with `ERR_OUTLAY_EXCEEDS_OBLIGATION` (HTTP 409) — an outlay exactly equal to the obligation passes. And the closing caller's `X-User-ID` must differ from the project's stored `submitted_by_user_id`, or the attempt is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403): the officer who asked for the money may not be the officer who signs off that it was spent.

On success the project moves `APPROVED → CLOSED`, `outlay_cents` is recorded and `closed_by_user_id` is set from the closing caller's `X-User-ID`. A ledger entry is appended against the `SURCHARGE` fund with `entry_type` of `CAPITAL_OUTLAY`, `amount_cents` equal to the negative of `outlay_cents`, `source_ref_kind` of `CAPITAL_PROJECT` and `source_ref_id` naming the project. The store's `surcharge_obligated_cents` then has the **whole** `obligation_cents` subtracted from it — a full release including any contingency that went unspent, which is why closing a project under budget makes more surcharge available than the outlay alone would suggest. The store's `surcharge_fund_balance_cents` is recomputed from the ledger, its `fund_posture` is re-derived, and both the store's `version` and the project's `version` are incremented by 1. Capital projects can be listed with optional `store_id` and `state` filters and read individually, by fund controllers and board officers alike.

**The period-close checkpoint.** Once an accounting period ends, a `SurchargeFundController` runs the store's close-period checkpoint. It is the only operation in the system that sweeps records the caller did not name, and it performs six steps strictly in this order:

1. Every shopper delegation whose `status` is `ACTIVE` and whose `valid_to` is at or before the logical clock's current instant transitions `ACTIVE → EXPIRED`, with `version` incremented.
2. Every special order of this store whose `state` is `LOCAL_FILL_PENDING` or `OVERSEAS_SHIP_PENDING` transitions to `FULFILLED`, with `version` incremented, and the store's `shipping_allowance_committed_cents` is left unchanged.
3. The dividend waterfall runs, writing `DIVIDEND_TRANSFER` ledger entries and raising each funded programme's `ytd_funded_cents`.
4. The store's `dividend_fund_balance_cents` is recomputed from the ledger and its `fund_posture` is re-derived.
5. Every capital project of this store at `AWAITING_FUNDS` is walked in `created_at` ascending order and auto-approved while the available surcharge covers each obligation, exactly as described above.
6. The store's `period_close_index` is incremented by 1 and the store's `version` is incremented by 1.

**The dividend waterfall.** The amount to distribute is the store's `dividend_fund_balance_cents` **measured before any transfer in this run** — the waterfall does not re-read a shrinking balance from the ledger as it goes; it starts from one figure and draws that figure down. The candidates are the store's programmes whose `status` is `ACTIVE` and whose `ytd_funded_cents` is strictly below their `funding_ceiling_cents`; `SUSPENDED` programmes and programmes already at their ceiling are skipped entirely. Candidates are visited in `priority_rank` ascending order with `created_at` ascending as the tie-break.

For each candidate in turn, the system stops immediately if the remaining amount has reached zero or below. Otherwise it computes that programme's headroom as its `funding_ceiling_cents` less its `ytd_funded_cents`, and grants the smaller of the remaining amount and that headroom. When the grant is greater than 0, a ledger entry is appended against the `DIVIDEND` fund with `entry_type` of `DIVIDEND_TRANSFER`, `amount_cents` equal to the negative of the grant, `source_ref_kind` of `MWR_PROGRAM` and `source_ref_id` naming the programme; the programme's `ytd_funded_cents` rises by the grant and the remaining amount falls by it, before the next candidate is considered. No rounding can arise anywhere in this loop, because every grant is the smaller of two whole-cent integers.

If there are no candidates at all, or if money is still left after every candidate has reached its ceiling, the leftover simply stays in the dividend fund for the next period. That is not an error condition, and no ledger entry is written for it.

## 4. Endpoint Definitions

The API surface is flat: every path below is rooted at `/`, and there is no single owning top-level resource. Creating a new resource returns HTTP 201 with the created resource in `data`; every other successful operation — modifications, state transitions, sweeps and reads — returns HTTP 200 with the affected or requested resource in `data`. The table gives only the method, path, purpose and authorised roles; the request payload, the response payload and the side effects of each operation are specified in the narrative of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Set the server's logical clock; startup default is `2026-08-01T00:00:00Z` | `SystemOperator` |
| POST | `/stores` | Register a commissary or exchange store | `SurchargeFundController` |
| GET | `/stores` | List stores | `SurchargeFundController`, `AssortmentPlanner`, `ComplianceOfficer`, `MwrBoardOfficer` |
| GET | `/stores/{id}` | Read one store including all four derived fund figures and `fund_posture` | `SurchargeFundController`, `AssortmentPlanner`, `ComplianceOfficer`, `MwrBoardOfficer`, `StoreCashier` |
| POST | `/stores/{id}/close-period` | Ops-run checkpoint: expire lapsed delegations, fulfil pending special orders, run the dividend waterfall, re-derive posture, auto-approve parked projects, advance the period index | `SurchargeFundController` |
| GET | `/stores/{id}/fund-ledger` | Append-only fund ledger of the store, ordered `created_at` ascending | `SurchargeFundController`, `MwrBoardOfficer`, `ComplianceOfficer` |
| GET | `/stores/{id}/mwr-programs` | Programmes funded by this store's dividend, ordered `priority_rank` ascending then `created_at` ascending | `MwrBoardOfficer`, `SurchargeFundController` |
| POST | `/patrons` | Enrol a patron with an ID card class; a dependent requires a sponsor | `ComplianceOfficer` |
| GET | `/patrons` | List patrons; filter by sponsor to find a sponsor's dependents | `ComplianceOfficer`, `StoreCashier` |
| GET | `/patrons/{id}` | Read one patron with both risk scores and both status dimensions | `ComplianceOfficer`, `StoreCashier`, `Patron` |
| POST | `/patrons/{id}/card-status` | Suspend, reinstate or revoke an ID card; suspension and reinstatement cascade three hops | `ComplianceOfficer` |
| POST | `/patrons/{id}/compliance-review` | Record a resale strike or clear the watch; both recompute both risk scores | `ComplianceOfficer` |
| POST | `/shopper-delegations` | Grant authorized-shopper privileges; guarded by the delegate patron's version | `ComplianceOfficer` |
| GET | `/shopper-delegations` | List delegations by sponsor, delegate, status or supersession link | `ComplianceOfficer`, `StoreCashier` |
| GET | `/shopper-delegations/{id}` | Read one delegation | `ComplianceOfficer`, `StoreCashier` |
| POST | `/shopper-delegations/{id}/revoke` | Revoke a delegation; flags its open sales | `ComplianceOfficer` |
| POST | `/products` | Create a worldwide item record | `AssortmentPlanner` |
| GET | `/products` | List products | `AssortmentPlanner`, `StoreCashier` |
| GET | `/products/{id}` | Read one product | `AssortmentPlanner`, `StoreCashier`, `Patron` |
| POST | `/assortments` | Allocate an item to a store shelf block for a closed effective window; guarded by the store's version | `AssortmentPlanner` |
| GET | `/assortments` | List allocations by store, product, shelf block, status or supply mode | `AssortmentPlanner`, `StoreCashier` |
| GET | `/assortments/{id}` | Read one allocation | `AssortmentPlanner`, `StoreCashier` |
| POST | `/assortments/{id}/retire` | Retire an allocation; releases facings and cancels the store/product's pending overseas orders | `AssortmentPlanner` |
| POST | `/sales` | Open a sale (one visit); stamps the business date and runs the full eligibility gate | `StoreCashier` |
| POST | `/sales/{id}/lines` | Ring an item onto an open sale; prices it, rolls up the sale, refreshes the provisional allowance and rescores the patron | `StoreCashier` |
| POST | `/sales/{id}/tender` | Tender the sale: settle the vendor allowance, post the ledger entries, cascade into store posture and parked projects | `StoreCashier` |
| POST | `/sales/{id}/void` | Void a sale; a tendered sale is reversed in the ledger | `ComplianceOfficer` |
| GET | `/sales` | List sales by store, patron, acting delegation or either state dimension | `StoreCashier`, `ComplianceOfficer` |
| GET | `/sales/{id}` | Read one sale with every computed money field | `StoreCashier`, `ComplianceOfficer`, `Patron` |
| GET | `/sale-lines` | List sale lines by sale or by product | `StoreCashier`, `ComplianceOfficer` |
| GET | `/sale-lines/{id}` | Read one sale line with its priced fields | `StoreCashier`, `ComplianceOfficer` |
| POST | `/mwr-programs` | Register a morale, welfare and recreation programme as a dividend waterfall bucket | `MwrBoardOfficer` |
| GET | `/mwr-programs/{id}` | Read one programme including `ytd_funded_cents` | `MwrBoardOfficer`, `SurchargeFundController` |
| POST | `/capital-projects` | Draft a surcharge-funded capital project; contingency tier and obligation are computed at creation | `SurchargeFundController` |
| GET | `/capital-projects` | List capital projects by store or state | `SurchargeFundController`, `MwrBoardOfficer` |
| GET | `/capital-projects/{id}` | Read one capital project | `SurchargeFundController`, `MwrBoardOfficer` |
| POST | `/capital-projects/{id}/submit` | Submit a draft or returned project for board decision | `SurchargeFundController` |
| POST | `/capital-projects/{id}/decision` | Board decision: approve (obligating the fund or parking the project), return for revision, or reject | `MwrBoardOfficer` |
| POST | `/capital-projects/{id}/close` | Close an approved project with its actual outlay, releasing the whole obligation | `SurchargeFundController` |
| POST | `/special-orders` | Place a deployed or remote-site special order; runs the same eligibility gate as a sale | `StoreCashier`, `Patron` |
| GET | `/special-orders` | List special orders by store, patron, product, state or route | `StoreCashier`, `ComplianceOfficer` |
| GET | `/special-orders/{id}` | Read one special order with its shipping computation | `StoreCashier`, `ComplianceOfficer`, `Patron` |
| POST | `/special-orders/{id}/route` | Fork the order onto a fill route, committing the appropriated-fund shipping allowance on the overseas branch | `StoreCashier` |
| POST | `/special-orders/{id}/cancel` | Cancel a non-terminal special order, releasing exactly the committed shipping allowance | `StoreCashier`, `Patron` |

## 5. Error Code Catalogue

Every error response carries one of the identifiers below in `data.error_id`, together with the HTTP status shown. The conditions that trigger each identifier are specified in the narrative of §2 and §3, at the point in the workflow where the check belongs.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_ROLE_NOT_PERMITTED` | 403 |
| `ERR_PATRON_SCOPE_VIOLATION` | 403 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_STORE_NOT_FOUND` | 404 |
| `ERR_PATRON_NOT_FOUND` | 404 |
| `ERR_PRODUCT_NOT_FOUND` | 404 |
| `ERR_ASSORTMENT_NOT_FOUND` | 404 |
| `ERR_SALE_NOT_FOUND` | 404 |
| `ERR_SALE_LINE_NOT_FOUND` | 404 |
| `ERR_DELEGATION_NOT_FOUND` | 404 |
| `ERR_PROJECT_NOT_FOUND` | 404 |
| `ERR_SPECIAL_ORDER_NOT_FOUND` | 404 |
| `ERR_MWR_PROGRAM_NOT_FOUND` | 404 |
| `ERR_SPONSOR_REQUIRED` | 422 |
| `ERR_MARKUP_FORBIDDEN_IN_COMMISSARY` | 422 |
| `ERR_VENDOR_REQUIRED_FOR_DSD` | 422 |
| `ERR_DUPLICATE_SKU` | 409 |
| `ERR_STALE_STORE_VERSION` | 412 |
| `ERR_STALE_PATRON_VERSION` | 412 |
| `ERR_SALE_NOT_OPEN` | 409 |
| `ERR_SALE_ALREADY_VOIDED` | 409 |
| `ERR_PROJECT_NOT_DRAFT` | 409 |
| `ERR_PROJECT_NOT_SUBMITTED` | 409 |
| `ERR_PROJECT_NOT_APPROVED` | 409 |
| `ERR_DELEGATION_NOT_ACTIVE` | 409 |
| `ERR_ASSORTMENT_NOT_ACTIVE` | 409 |
| `ERR_SPECIAL_ORDER_NOT_ROUTABLE` | 409 |
| `ERR_SPECIAL_ORDER_TERMINAL` | 409 |
| `ERR_SALE_HAS_NO_LINES` | 409 |
| `ERR_SALE_COMPLIANCE_FLAGGED` | 409 |
| `ERR_PATRON_CARD_NOT_VALID` | 403 |
| `ERR_SPONSOR_CARD_NOT_VALID` | 403 |
| `ERR_PATRON_NOT_ELIGIBLE_FOR_CHANNEL` | 403 |
| `ERR_PATRON_NOT_ELIGIBLE_IN_REGION` | 403 |
| `ERR_QUANTITY_LIMIT_EXCEEDED` | 409 |
| `ERR_RESTRICTED_ITEM_BLOCKED_BY_WATCH` | 403 |
| `ERR_DELEGATION_WINDOW_NOT_COVERING` | 409 |
| `ERR_DELEGATION_WINDOW_OVERLAP` | 409 |
| `ERR_ITEM_NOT_IN_ASSORTMENT` | 409 |
| `ERR_ROUTE_NOT_AVAILABLE_IN_REGION` | 409 |
| `ERR_SHELF_CAPACITY_EXCEEDED` | 409 |
| `ERR_DELEGATION_SPEND_CAP_EXCEEDED` | 402 |
| `ERR_TAX_COLLECTION_FORBIDDEN` | 422 |
| `ERR_OUTLAY_EXCEEDS_OBLIGATION` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
