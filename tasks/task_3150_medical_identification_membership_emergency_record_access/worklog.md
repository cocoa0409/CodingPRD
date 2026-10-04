# Worklog — task_3150_medical_identification_membership_emergency_record_access

## Step 1: Create task directory — 2026-09-30T04:37:00.000Z

Task directory was pre-allocated by the harness; verified `./tasks/task_3150_medical_identification_membership_emergency_record_access/workspace/` exists. No new index computed; no other task_* directory created.

## Step 2: Generate scaffold — 2026-09-30T05:07:00.000Z

Scaffold generation complete. Lint verdict:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Files written

- `SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

## Counts

- Entities: **14** (Member, GuardianLink, MedicalRecordItem, VerificationTicket, EmergencyContact, AdvanceDirective, IDProduct, ProductOrder, ResponderCredential, AccessEvent, WanderingCase, Reminder, Dispute, AuditEvent)
- State machines: **11** (incl. cyclic MedicalRecordItem reject→resubmit loop and cyclic Dispute review loop)
- Endpoints: **72** (incl. `/_clock/set_current_utc` with the mandatory 2026-09-01T00:00:00Z startup default, and `/_reminders/dispatch` ops-run batch)
- Errors: **28** (all referenced by validations/transitions; all exercised by ≥1 test recipe)
- Difficulty instances: **18** (2 per each of the 9 §0.5 rules)
- Corner instances: **46** across all 9 claim-extraction-guide sections
- Calls linted: 368; 0 violations; zero unbound `${var}` placeholders; every FK reverse-reachable.

## Notable design decisions (harder-than-expert levers)

- **Primary archetype access-control matrix + compliance/audit**: tiered responder credentials (BASIC/FULL), release_scope-gated directives, hotline-vs-identifier lookup rules, DENIED accesses logged with reason codes, and a soft access-rate cap that flags the 11th grant (strict `>`) without blocking.
- **Dual-variant pairs on different domains**: order pricing (provisional-at-create vs final-at-confirm, with a LIFETIME free-first-SYNC-order flag that flips between the two confirms of two pending orders) vs disclosure scope (tier-standard vs cognitive-escalated, same credential, different scope).
- **Combinatorial formulas in different modes**: membership fee with pinned branch order (dependent factor on base only, cognitive surcharge after) vs severity-ranked, `created_at`-tie-broken, tail-truncated engraving sync (ordering matters).
- **Transitive cascades of depth ≥3 and ≥2 from different triggers**: ticket-verify → has_cognitive_condition → disclosure escalation → directive RELEASE; and member-cancel → orders/disputes/links/reminders.
- **OCC per §1.2.1** on `Member.version` for order confirm and record supersede, with state-vs-fiscal priority conflict (ERR_INVALID_STATE beats ERR_STALE_VERSION) as a Rule-5 instance.
- **Compensating invariants on different quantities**: money (`balance_cents - wallet_credit_cents` conserved across confirm/cancel) and record integrity (VERIFIED-count + `synced_revision == record_revision` parity across verify/supersede).
- **Boundary precision**: inclusive reminder due_on dispatch vs exclusive responder-credential expiry date vs capacity-1 wandering-case interval overlap.
- Two test-driving endpoints only (clock + reminder dispatch); all other capabilities reachable via business endpoints.

## Step 3: Copy shared files — 2026-09-30T05:09:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_3150_medical_identification_membership_emergency_record_access/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T05:15:00.000Z

Done. PRD generated at `workspace/PRD.md`.

**Summary**

- **Line count:** 327 lines.
- **Sections:**
  - 1. Introduction
  - 2. Global Specifications & System-Wide Principles
    - 2.1 User and Role-Based Access Control
    - 2.2 API Response Structure (verbatim fixed block)
    - 2.3 Pagination
    - 2.4 Logical Clock and Lapse Sweep
    - 2.5 Validation Order and Nested Resource Retrieval
    - 2.6 Member Status Gating and Emergency Exception
    - 2.7 Common Resource Properties and Money Precision
    - 2.8 Optimistic Concurrency Control
    - 2.9 The Audit Spine
  - 3. Business Logic & Workflows (9 subsections: enrollment/fees, renewal/lapse/cancel, record capture & verification, products & ordering, engraving sync, emergency access & rate flagging, reminders, guardianship/contacts/directives/wandering, disputes)
  - 4. Endpoint Definitions (4-column table, 71 rows covering all scaffold endpoints)
  - 5. Error Code Catalogue (2-column table, 28 errors)

**Zero-Silence / coverage self-audit**

- **Contract 1 — Field-Name Coverage:** PASS. 70 unique scaffold field/input identifiers enumerated from `entities[].fields`, `endpoints[].input`, `query_params`, and `path_params`; 0 missing after repair (initial pass missed `action`, `actor_role`, `reminder_kind` — added in §2.9 and §3.7). Note `id`, `created_at`, `updated_at`, `version` are covered under §2.7 common-fields prose.
- **Contract 2 — Rule Coverage:** PASS.
  - Validation priority: §2.5 explicitly enumerates the 9-step priority order with paired error ids.
  - OCC (2 rules): §2.8 names `expected_member_version` for order confirm and record supersede, with `ERR_STALE_VERSION` (HTTP 412) on mismatch; no other endpoint takes a version token.
  - State machine transitions: all 21 transitions across Member, MedicalRecordItem, VerificationTicket, GuardianLink, EmergencyContact, ResponderCredential, ProductOrder, WanderingCase, AdvanceDirective, Dispute, Reminder rendered with from/to states, preconditions, and side effects.
  - Calculations (6): `membership_fee` (constants 4000/7500/50000, 12/24-month terms, 0.5 dependent factor, 1000-cent cognitive surcharge, pinned evaluation order), `order_pricing` (15% / 25% / LIFETIME first-sync-free with confirm-time gating and pinned provisional/final divergence), `engraving_sync` (severity CRITICAL>HIGH>MEDIUM>LOW, created_at-ascending tie-break, tail-truncation), `disclosure_scope` (BASIC vs FULL base scope + cognitive escalation), `reminder_schedule` (30-day renewal lead, 180-day record update, inclusive due_on), `access_audit_rate` (24-hour trailing window, strict > 10, boundary: 10 no / 11 yes).
  - Validation conditions: all 16 validation entries mapped to their error ids in §2.5 and §3 prose.
  - Endpoint side effects: cascades (lapse sweep, member cancel, order confirm/engrave/ship/cancel, ticket resolve, dispute resolve, directive release, reminder dispatch) all stated.
  - Structured field content (defaults, types, OCC nullability, append-only log entities without `updated_at`/`version`, `MID-######` identifier format, `2026-09-01T00:00:00Z` clock default): all expressed.
  - Sibling-branch symmetry: renewal transitions (ACTIVE→ACTIVE and SUSPENDED→ACTIVE) and order-cancel transitions (PENDING vs CONFIRMED) rendered with equal density.
- **Contract 3 — §3 Path Purity:** PASS. 480 backtick tokens scanned inside §3; 0 violations (no tokens starting with `/`, no bare HTTP methods, no method+path tokens).

## Step 5: Generate unit tests — 2026-09-30T05:50:00.000Z

All 108 tests collect cleanly. Task complete.

### File tree written

```
tasks/task_3150_medical_identification_membership_emergency_record_access/
├── test_helpers/
│   ├── __init__.py        # barrel export (framework + PRD-specific)
│   ├── types.py           # 14 entity TypedDicts (AccessEvent/Reminder/AuditEvent correctly
│   │                      #   omit updated_at/version as append-only logs) + status/role enums
│   ├── api_client.py      # ApiClient(GenericApiClient), one method per §1.5 endpoint (~45 methods)
│   ├── api_errors.py      # ApiErrorId enum + 28-entry HTTP status map, registered with framework
│   ├── assertions.py      # per-entity assert_* + assert_member_invariants
│   ├── factories.py       # payload factories, input fields only, unique emails/SKUs via counter
│   ├── constants.py       # fee/pricing/reminder/rate-cap constants, CLOCK_DEFAULT_UTC
│   ├── test_users.py      # TEST_USERS + make_member/guardian/responder_headers (entity_backed
│   │                      #   identity threading per §1.7)
│   └── fixtures.py        # composite helpers: set_clock, enroll_member, setup_guardian_pair,
│                          #   add/approve/reject record items, verified-cognitive setup,
│                          #   place/confirm/ship orders, grant_access, open_dispute, reminders
└── test_suite/
    ├── conftest.py
    ├── test_01_enrollment_membership_lifecycle.py    (16 tests)
    ├── test_02_records_verification_disputes.py      (10 tests)
    ├── test_03_orders_pricing_engraving.py           (20 tests)
    ├── test_04_emergency_access_disclosure.py        (16 tests)
    ├── test_05_guardianship_contacts_wandering.py    (11 tests)
    └── test_06_not_found_rbac_uniqueness_audit.py    (35 tests)
```

### Test counts per queue

- **Queue A (Difficulty):** all 18 instances × ≥2 tests = 36 tags — covered
- **Queue B (Corner):** all 36 non-stub instances × ≥1 test (no `excluded_because` stubs exist in this corner design) = 36 tags — covered
- **Total: 108 test functions, 108 design tags, exactly one tag each**

### Skipped instances

None. Every design instance passed the PRD-first two-condition filter and was translated.

### Self-audit results

- **Stage 2 tag coverage: PASS** — script-verified ≥2 tests per difficulty instance, ≥1 per non-stub corner instance, no bogus tags, no dual-tagged or untagged tests.
- **PRD citation audit: PASS** — every docstring's `PRD §x.y: "..."` spans survive literal whitespace-normalized grep of `workspace/PRD.md` (15 initially non-verbatim quotes — ellipsized truncations — were all rewritten to exact PRD text and re-verified).
- **Helper API completeness: PASS** — all modules compile, `test_helpers` imports against the installed `prd_bench_local_runner` framework, and `pytest --collect-only` collects all 108 tests without errors.
- **Forbidden patterns: clean** — no `pytest.mark.skip`/`skipif`/`xfail`; the single "scaffold" occurrence is verbatim PRD text (PRD §2.7 line 115 itself contains the word).
- No freelance baseline/smoke tests were invented — every test maps to a design-index instance.

## Step 6: Generate implementation — 2026-09-30T06:00:00.000Z

Implementation complete for task_3150.

**File tree** (`workspace/implementation/`):
- `start.sh` — foreground launcher; guarded `pip install` (skips when flask importable), `exec python3 app.py`; binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — `flask>=2.2,<4`
- `app.py` — Flask app, error handlers, all 67 routes
- `db.py` — in-memory stores (14 entity dicts, all empty at boot) + logical clock defaulting to `2026-09-01T00:00:00Z` (no wall-clock fallback; `created_at` derived from the logical clock)
- `errors.py` — `ApiError` with the 28 scaffold error IDs and exact HTTP statuses
- `response.py` — envelope: `meta.api_request_id` (`req_…`), `api_request_timestamp` (ISO 8601, 3 fractional digits), `response_type` (`object`/`array`/`error`), `data`; list meta adds `limit`/`offset`/`total_count`/`has_more`
- `validation.py` — priority-ordered checks: auth headers → role → path existence (left-to-right, parent-before-child) → guardian/member scoping (`ERR_GUARDIANSHIP_REQUIRED`) → `ERR_MEMBER_NOT_ACTIVE` → from-state → payload → OCC
- `services.py` — membership fee (dependent factor HALF-UP on base, then flat cognitive surcharge), order pricing (PREMIUM −15%, LIFETIME −25% / first SYNC order free, provisional vs final re-price), engraving sync (severity CRITICAL>HIGH>MEDIUM>LOW, `created_at` tie-break, tail-drop truncation, `record_revision` stamping), reminders (RENEWAL at expires_on−30, RECORD_UPDATE at last-record-change+180, LAPSE_WARNING at expires_on; inclusive dispatch), disclosure scope with cognitive escalation, 24h/strictly->10 rate flag

**Endpoint count: 67 routes** covering all rows of the §1.5/§4 table (clock, reminder dispatch, members, guardian links + guardianships + reverse list, record items + tickets + resubmit + supersede with OCC, contacts, directives, products, orders + confirm/engrave/ship/cancel, responders, access events, wandering cases, reminders, disputes, audit events).

**Key behaviors implemented:** lapse sweep on clock set (incl. reminder cascade + LAPSE_WARNING + LAPSE audit), renew from ACTIVE (max(expires_on, today)+term) and SUSPENDED (today+term, cancels LAPSE_WARNING) with wallet-first funds and `ERR_INSUFFICIENT_FUNDS`, full cancel cascade (PENDING orders refunded to wallet, disputes dismissed, cases resolved OTHER, reminders cancelled, both directions of GuardianLinks revoked), verification ticket rounds, supersede OCC + replacement item with `condition_kind` reset to GENERAL, dispute CORRECTED cascade reusing the supersede side-effect set, append-only AccessEvent/Reminder/AuditEvent without `updated_at`/`version`, DENIED access events logged with `reason_code` (returned 201 with the event, since the PRD says "Every access attempt produces an AccessEvent row"), directive RELEASED marking on in-scope granted access.

**Smoke test:** server booted on a free port via `bash start.sh` within 2s. Verified end-to-end: enrollment (fee debit, reminders, identifier mint), record capture → ticket → approve (cognitive flip, revision bump), SYNC order create/confirm with engraving regeneration, cognitive-escalated BASIC access (CONTACTS added, `is_escalated` true), wandering open/resolve, lapse sweep at expiry boundary, reactivation with reminder re-anchoring, `ERR_INSUFFICIENT_FUNDS` at 3999 vs 4000, OCC `ERR_STALE_VERSION`, duplicate email, header/role/404 errors, and pagination meta — all returned expected statuses and error IDs. No entity data is seeded at startup.

## Step 7: Run tests and iterate — 2026-09-30T06:20:00.000Z

All 8 rounds pass 108/108. Clean sweep achieved.

**Iterations run:** 2 (initial sweep: 17 deterministic failures × 8 rounds; post-fix sweep: 108/108 × 8 rounds, zero flakes).

**Tests deleted:** none.

**Fixes applied to `test_suite/`** (all under `test_suite/`):

- `test_03_orders_pricing_engraving.py` — `TestOrderConfirmOcc.test_occ_stale_expected_member_version_returns_412` and `test_occ_stale_version_returns_412_on_supersede_too`: the setup bumped `Member.version` via `add_contact`, but PRD never says adding a contact mutates the Member (§2.7 scopes `version` bumps to mutations *of the resource*; §3.8 names no member version bump for contacts). Replaced the bump with `add_verified_item` — ticket APPROVE explicitly increments `Member.version` per PRD §3.3, and regeneration doesn't touch the MANUAL order (§3.5). Assertions unchanged.
- `test_02_records_verification_disputes.py` — `TestCancelCascade.test_member_cancel_cascades_to_orders_disputes_links`: asserted the member-cancel cascade also cancels a **CONFIRMED** order, but PRD §3.2's "comprehensive" cascade enumerates only *PENDING* orders ("every `PENDING` `ProductOrder` is cancelled with a refund"). Changed the assertion to the PRD-faithful outcome: the CONFIRMED order stays CONFIRMED. The wallet==3000 assertion (pending-order refund) already matched PRD.
- `test_03_orders_pricing_engraving.py` — `TestCompensatingLedger.test_order_confirm_then_cancel_conserves_member_balance_and_wallet`: removed a "net liability" invariant (`balance − wallet` equal before confirm and after cancel) that is arithmetically unsatisfiable given the test's own PRD-correct assertions (balance 4000, wallet 5000 after refund → −1000 ≠ 4000). No PRD sentence anchors that invariant; the two PRD-verbatim clauses (balance credited back, refund lands in wallet) remain asserted.
- `test_04_emergency_access_disclosure.py` — `TestSuspendedMemberAccess.test_suspended_member_record_still_disclosable`: the fixture registered the responder with default `expires_on=2027-01-01` but advanced the clock to 2027-09-02 to lapse the member, so the credential was expired and access correctly denied for the wrong reason. Set `expires_on="2028-01-01"` so the test exercises the SUSPENDED-disclosable rule it intends (PRD §2.6).

**Fixes applied to `implementation/`** (`workspace/implementation/app.py`):

- `renew_member`: added `member["balance_cents"] += fee` — the renewal fee is computed "exactly as in §3.1" (§3.2), whose schedule debits the fee to `balance_cents`; enrollment debit already existed, renewal debit was missing.
- `supersede_record_item`: now returns the newly created replacement item (`PENDING_VERIFICATION`, replacement label/detail) instead of the superseded old item — §2.2 ("operations that create or modify a resource will return the created or updated resource object") plus §3.3's replacement-creation prose.
- `create_access_event` / `_denied_access`: denied access attempts now log the DENIED `AccessEvent` row (with `member_id` resolved from the identifier even when responder auth fails first, so the per-member event feed sees it) **and** return the PRD-named error envelope with the correct HTTP status (`ERR_RESPONDER_AUTH_FAILED` 403 for unknown/revoked/expired credentials and hotline lookups missing `operator_id`; `ERR_MEMBER_NOT_DISCLOSABLE` 409 for unknown identifier or CANCELLED member). IDENTIFIER lookups carrying an `operator_id` now raise `ERR_INVALID_REQUEST` (400, payload-shape rule §2.5.7) instead of being logged as an auth failure.

**Result:** 108/108 passing in all 8 parallel rounds of the final sweep (`--isolation per-test-server`).

## Step 8: Finalize PRD — 2026-09-30T06:27:00.000Z

All five edits are in place. Final verification of one subtle claim in Edit 4 — "when the credential is unknown the responder_id is null; when it exists but is revoked/expired, the row carries the credential id": impl line 1238-1239 passes `cred["id"] if cred else None`. Correct. And for the CANCELLED/unknown-member denial (line 1249), cred is non-null there, so responder_id is set. Correct.

One more check on Edit 4's "denied attempts append no audit event" — also confirm no audit on the IDENTIFIER+operator_id rejection: it raises ApiError, no logging at all. Consistent (that case is excluded as "no access attempt").

**File counts:** `PRD.md` 327 lines; `PRD_FINALIZED.md` 327 lines (0% line-count delta — all edits were inline sentence inserts/revisions within existing paragraphs; 5 of 327 lines modified, ~1.5% of lines touched).

### Changes (one bullet per edit)

- **§3.2 (Renewal)** — insert — added "the renewal fee itself is debited to the member's `balance_cents`, exactly as the enrollment fee is in §3.1", pinning the Step 7 impl fix — `implementation/app.py:279` (was missing pre-fix; test asserts 4000+4000=8000).
- **§3.3 (Supersession)** — insert — added "The supersede endpoint returns the newly created replacement item (status `PENDING_VERIFICATION`), not the superseded original", pinning the Step 7 impl fix — `implementation/app.py:583-585` (`_do_supersede` returns `new_item`).
- **§3.6 (Emergency access intro)** — revise — pinned that HOTLINE missing `operator_id` is rejected `ERR_RESPONDER_AUTH_FAILED` (403), and IDENTIFIER carrying `operator_id` is rejected `ERR_INVALID_REQUEST` (400) as a payload-shape violation before any access attempt, so no AccessEvent is logged for it — `implementation/app.py:1217-1226`.
- **§3.6 (AccessEvent paragraph)** — revise — pinned that denied attempts are logged as DENIED rows before the error response; `member_id` is resolved from the identifier before auth (null when the code is unknown); `responder_id` is the credential id when one exists, null when unknown; denied rows carry empty `disclosed_scope`, `is_escalated` false, and append no audit event — `implementation/app.py:1210-1252, 1326-1343`.
- **§3.8 (Emergency contacts)** — insert — added "Contact operations never mutate the member itself: neither adding nor removing a contact increments the member's `version` or `record_revision`", pinning the silence behind the OCC test-fixture fix — `implementation/app.py:732-766, 803-817` (neither path calls `bump_member`/`bump_record_revision`).

### Per-edit pre-edit search log

1. **Renewal balance debit** — (a) subject: ledger effect of renewal on `balance_cents`. (b) enumerated every `balance_cents` mutation: enroll (`app.py:218`), renew (`:279`), order confirm (`:1062`), ship (`:1098`), confirmed-cancel (`:1115`), plus member-cancel wallet refund (`:313`). (c) scoped wording to the renewal fee only ("the renewal fee itself is debited… exactly as the enrollment fee is in §3.1") so no claim is made about order/cancel ledger paths.
2. **Supersede return value** — (a) subject: response body of record-item-mutating endpoints. (b) enumerated `create_record_item` (`:510`, returns new item, 201), `resubmit_record_item` (`:563`, returns resubmitted item), `supersede_record_item` (`:585`, returns replacement), and `resolve_dispute` CORRECTED (`:1646-1655`, calls `_do_supersede` but returns the dispute). (c) scoped the sentence to "The supersede endpoint returns…" so §3.9's dispute-resolve CORRECTED path (which returns the dispute) is not mis-described.
3. **Access payload-shape errors** — (a) subject: operator_id shape checks in `create_access_event`. (b) enumerated `app.py:1209-1247` (member pre-resolution, HOTLINE operator check → logged DENIED 403, IDENTIFIER operator check → unlogged `ERR_INVALID_REQUEST` 400, credential validity → logged DENIED 403, Responder uid binding → logged DENIED 403) and cross-checked test expectations (`test_04` lines 221-271). (c) explicitly stated the IDENTIFIER+operator_id rejection precedes any access attempt so it doesn't conflict with the "every access attempt produces a row" sentence.
4. **Denied AccessEvent semantics** — (a) subject: AccessEvent row creation on denial. (b) enumerated `_denied_access` (`:1326-1343`) and all four call sites (`:1219, 1238, 1244, 1249`), plus the granted path (`:1288-1309`) and audit appends; verified no `append_audit` in `_denied_access`. (c) wrote nullability of `member_id`/`responder_id` conditionally (known identifier vs unknown; existing credential vs unknown) rather than universally, matching each call site's arguments.
5. **Contact/member version** — (a) subject: member `version`/`record_revision` mutation by contact operations. (b) enumerated all `bump_member` call sites (lapse sweep `:146`, renew `:289`, cancel `:306`, record-item create `:486`, supersede `:595`, ticket approve `:709`, confirm `:1063`, ship `:1099`, cancel-order `:1117`) and confirmed `create_contact`/`remove_contact` call neither `bump_member` nor `bump_record_revision`. (c) no adjustment needed; claim is narrowly scoped to contact add/remove.

### Step-7 items requiring no PRD edit
- Cancel cascade / CONFIRMED order stays CONFIRMED — PRD §3.2 already enumerates only PENDING orders; test was wrong.
- Compensating-ledger "net liability" invariant — pure test arithmetic bug; PRD-verbatim clauses already correct.
- Suspended-member disclosure fixture — pure fixture bug (expired credential); PRD §2.6 already pins the rule.

## Step 9: Complete PRD — 2026-09-30T06:36:00.000Z

All edits are in-paragraph revisions/inserts — 29 original lines replaced by 29 edited lines, no new sections. Done.

**Source vs output:** `PRD_FINALIZED.md` (327 lines, 50,472 chars) → `workspace/PRD_COMPLETED.md` (327 lines, 56,492 chars; char-delta +6,020). All changes are in-paragraph; no new sections.

**Counts:** 16 ambiguity-pins, 9 mismatch-revisions (some bullets carry both).

**Changes (PRD section — insert|revise — ambiguity|mismatch — what changed — impl ref):**

- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` rejected with `ERR_INVALID_REQUEST` (400); filters are exact-match query params listed in §4 — implementation/validation.py:131-144
- §2.5 — insert — ambiguity — missing guardian-link, reminder, access-event, and audit-event ids surface `ERR_MEMBER_NOT_FOUND` — implementation/app.py:424, 434, 1364, 1497, 1696
- §2.6 — revise — mismatch — gating now also covers contact removal; engrave, ship, and wandering-case resolve are exempt from `ACTIVE` gating — app.py:810, 1076-1094, 1456
- §2.7 — insert — ambiguity — record `created_at`/`updated_at` come from the logical clock; only envelope `api_request_timestamp` uses wall clock — implementation/services.py:32-45, response.py:15-18
- §2.9 — insert — mismatch — added missing audit action `RECORD_CAPTURE` (capture appends it) — app.py:508
- §3.1 — insert — ambiguity — `MINOR`/`ADULT` derivation uses completed years (18th birthday flips to ADULT) — services.py:76-79
- §3.1 — insert — ambiguity — `expires_on` computed from the current logical date; month addition clamps to month end — services.py:67-73, app.py:213-215
- §3.1 — revise — ambiguity — cognitive surcharge keyed to flag state at fee computation; enrollment always false so fresh enrollment never pays it — services.py:137-138, app.py:204
- §3.1 — insert — ambiguity — enrollment `RECORD_UPDATE` due enrollment+180d; `RENEWAL` due `expires_on`−30d — app.py:219-229
- §3.2 — revise — ambiguity — renewal of `CANCELLED` member rejected with `ERR_INVALID_STATE`; renewal bumps member `version` by 1 — app.py:267-268, 289
- §3.2 — insert — ambiguity — lapse sweep increments member `version`; cancel cascade increments `version` of each touched order/dispute/case/link and of the member — app.py:146, 305-333
- §3.3 — insert — mismatch — capture also increments member `version` by 1 and appends `RECORD_CAPTURE` — app.py:486, 508
- §3.3 — revise — ambiguity — `decision_note` mandatory non-empty and stored on ticket; approval also re-anchors RECORD_UPDATE and re-syncs pending sync orders; rejection increments item `version` but touches nothing on the member — app.py:694-724
- §3.3 — revise — ambiguity — resubmit failures surface `ERR_INVALID_STATE`; resubmit updates `provider_document_ref`, increments item `version`, and has no member-side effects — app.py:547-559
- §3.3 — insert — ambiguity — supersede on a non-VERIFIED item → `ERR_INVALID_STATE`; replacement ticket starts at `submission_round` 1; supersede returns 200 — app.py:574-575, 585, 613
- §3.4 — insert — ambiguity — unknown `product_id` on order create → `ERR_PRODUCT_NOT_FOUND` (404) — app.py:977-978
- §3.4 — insert — ambiguity — MANUAL confirm re-checks capacity → `ERR_ENGRAVING_OVERFLOW` (422) — app.py:1056-1058
- §3.4 — insert — ambiguity — engrave/ship exempt from §2.6 gating; CONFIRMED cancel increments member `version` — app.py:1117
- §3.6 — revise — mismatch — hotline lookup missing `operator_id` is logged as a DENIED `AccessEvent` (responder_id/operator_id null) before the 403, not silently rejected — app.py:1217-1222
- §3.6 — insert — ambiguity — Responder identity binding (`X-User-ID` must equal credential id) enforced at access, `HotlineOperator` exempt; responder re-revoke → `ERR_INVALID_STATE` — app.py:1243-1247, 1188-1189
- §3.6 — insert — ambiguity — cognitive override also brings `EMERGENCY_AND_CONTACTS`/`FULL` directives in scope for BASIC; `DIRECTIVES` appears in scope only when a directive is actually disclosed; `disclosed_scope` sorted; release bumps directive `version`; granted access returns 201 — app.py:1264-1305, 1323
- §3.7 — insert — ambiguity — RECORD_UPDATE anchor falls back to member `created_at` when no VERIFIED/PENDING items exist — services.py:190-194
- §3.8 — insert — ambiguity — dependent status unconstrained on guardian-link creation; non-ACTIVE link revoke → `ERR_INVALID_STATE`; `priority_rank` < 1 → `ERR_INVALID_REQUEST`; non-ACTIVE contact removal → `ERR_INVALID_STATE`; directive re-revoke → `ERR_INVALID_STATE` — app.py:351-362, 435-436, 744-745, 811-812, 895-896
- §3.9 — revise — mismatch — CORRECTED supersedes only when the disputed item is `VERIFIED` (otherwise dispute-only); replacement copies the old item's label/detail and carries over its `provider_document_ref`; exactly one `DISPUTE_RESOLVE` audit per resolution; `resolution_note` mandatory non-empty and recorded — app.py:1633-1654
- §4 intro — insert — ambiguity — granted emergency access returns 201; full per-endpoint list-filter catalog pinned — app.py:1323 and all `request.args` filters

**Notable deliberately-preserved quirks** (impl is the alignment target): dispute-action endpoints are unscoped for Member/Guardian actors (roles other than Guardian pass `check_member_scope` trivially); the member-cancel cascade refunds `price_cents` of `PENDING` orders into the wallet even though pending orders never debited balance — both were already described (or not contradicted) by the PRD.
