# Worklog — task_3259_messaging_campaign_registration_number_vetting_deliverability

## Step 1: Create task directory — 2026-09-30T14:58:00.000Z

Pre-allocated task directory `./tasks/task_3259_messaging_campaign_registration_number_vetting_deliverability/` verified to exist with `workspace/` inside. No new index computed; no other task_* directory created.

## Step 2: Generate scaffold — 2026-09-30T15:18:00.000Z

All three scaffold artifacts are written and the lint verdict is clean.

**Files written:**
- `SCAFFOLD.yaml`
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `SCAFFOLD_CORNER_DESIGN.yaml`

**Counts:**
- Endpoints: 76 (includes prefix-level alias GETs and reverse-reachability sub-resource GETs required by lint check (f); ~45 are distinct business operations)
- Entities: 10 (Account, Brand, Campaign, SenderNumber, ConsentRecord, Message, FeedbackEvent, Charge, DailySnapshot, OpsRun)
- State machines: 7 (Account, Brand, Campaign, SenderNumber, ConsentRecord, Message, FeedbackEvent) — Brand and Campaign both have revision cycles; cascades span three levels
- Calculations: 11; Errors: 26; Validations: 15 (priority-ordered); Roles: 8; OCC concurrency rules: 2 (both on `Campaign.version`, `expected_campaign_version`)
- §1.8 instances: 18 (exactly 2 per each of the 9 difficulty rules)
- §1.9 instances: 38 total = 31 active + 7 `excluded_because` stubs
- `scaffold_lint.py` final verdict: **clean lint** (509 calls scanned, 0 violations); no forbidden concurrency vocabulary

**Design decisions adjudicated:**
- **Archetype**: compliance/audit (primary) blended with quota/allocation (throughput MPS), layers: OCC, cascading side effects, rate/threshold triggers, derived-field reconciliation.
- **Identity-score arithmetic**: additive brand scoring terms (50 base; +10/+10/+5/−20/+10/+10/+5, clamp last) were verified reachable — scores used in fixtures are 50, 70, 75, 90, 95. A 100-score NON_PROFIT claim and a "74" boundary claim were both arithmetically impossible and were corrected (TEN_DLC inclusive boundary is tested 75→10 vs 70→3 instead).
- **Score model coherence**: postal-code validation applies to every brand including DRAFT, which forced the low-score (50) fixtures to use invalid postal formats.
- **Lint-driven §1.5 additions**: check (f) is purely textual, so all path placeholders were normalized to `{id}`, canonical collection segments were established via prefix-level single-GETs (`/messaging/brands/{id}` etc.), prefix-level filtered lists carry `account_id?`/`campaign_id?`/etc. filters, and reverse pointers (`vetting_fee_charge_id` etc.) were removed in favor of `Charge.reference_type/reference_id` lookups. A `Message.consent_record_id` FK was added to make consent reachability explicit.
- **Trust-score testability**: `trust_score` recompute on snapshot bumps `Campaign.version`, so no recipe reads the version before snapshot POSTs.
- **Spam-floor volume gate** (2000 attempted) is impractical to produce via individual sends; §1.8 asserts the volume-gate's non-suspension side and the rate arithmetic, keeping every test_recipe executable end-to-end from empty DB.

## Step 3: Copy shared files — 2026-09-30T15:19:30.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T15:52:00.000Z

(Note: first two subagent attempts died on transient model-API errors — Throttling.ResourceExhausted, then InvalidParameter — leaving a 6KB partial PRD which was deleted; third attempt with explicit incremental-write instructions succeeded.)

All coverage checks pass. The PRD is complete.

**PRD written:** `workspace/PRD.md` — 384 lines.

**Section list:**
- §1 Introduction (3 paragraphs: business context, system scope, design goals)
- §2 Global Specifications: 2.1 RBAC (8 roles, opaque identity prose per role), 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination (limit 10/1–100, offset 0, created_at ascending), 2.4 Resource Identity (common fields + the five append-style entities without `updated_at`/`version`), 2.5 Logical Clock (startup `2026-09-01T00:00:00Z`, `to_iso8601`/`current_utc`), 2.6 Precision & Rounding, 2.7 OCC (both `expected_campaign_version` rules → `ERR_STALE_VERSION` 412), 2.8 Validation Order (all 15 priorities explicit), 2.9 Cascades, 2.10 Nested Retrieval & prefix aliases, 2.11 Charge Ledger
- §3 Business Logic: 3.1 Account lifecycle & ops runs, 3.2 Brand identity & verification (full identity-scoring additive order + clamp-last, resubmission cap edge landing in REVOKED), 3.3 Campaign registration & review (ordered submit gates, rejection codes, deactivate rule), 3.4 Trust score & throughput (inclusive tiers, flat paths), 3.5 Sender numbers (provisioning-source derivation, porting gates, release-from-4-states, attach OCC + type-uniqueness, fiscal last-resort release rule), 3.6 Consent & message lifecycle (1460-day retention, POST_BRAND evidence timing, 7-step send gauntlet, retry codes E30034/E30007, cancel-no-refund), 3.7 Queue drain/segments/fees (60-second drain window, 3-run staleness, deterministic carrier filtering before charging, pinned segment-then-rate order, 50-cent long-message surcharge over 3 segments, all per-carrier cent rates, recurring fee trailing-window semantics), 3.8 Feedback/snapshots/spam floor (attempted-set exclusion, rate formulas with rounding modes, penalty-before-bonus trust recompute with clamp last, inclusive 2000/300 spam floor)
- §4 Endpoint table (75 rows, 4 columns)
- §5 Error catalogue (26 errors, 2 columns)

**Hard contract results:**
- Field coverage: 84 required names (entities + endpoint inputs/query params), 84 present, 0 missing — PASS
- §3 path purity: 513 backtick tokens scanned, 0 path/method violations — PASS
- Rule coverage: every state machine transition (Account, Brand incl. resubmission-cap note, Campaign incl. all three deactivate from-states, SenderNumber incl. system cascades, ConsentRecord, Message incl. retry/cancel, FeedbackEvent RECORDED→APPLIED), all 11 calculations with constants and boundary semantics, all 15 validations in priority order, both OCC rules, and all 26 errors rendered in prose — PASS

## Step 5: Generate unit tests — 2026-09-30T16:10:00.000Z

All done. Summary of the generation:

**Files written**

**test_helpers/** (all compile clean, importable):
- `__init__.py` — barrel re-export of framework validators
- `constants.py` — paths, roles, enums, fee/threshold constants from the PRD
- `types.py` — role/status enums and entity TypedDicts (ConsentRecord, FeedbackEvent, Charge, DailySnapshot, OpsRun carry only `id`+`created_at`, no `updated_at`/`version`, per PRD §2.4)
- `api_errors.py` — all 25 PRD §5 error IDs with HTTP statuses, registered via `set_error_http_status_map`
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (clock, accounts, brands, campaigns, numbers, consent, messages, feedback, snapshots, charges, ops runs)
- `test_users.py` — opaque per-role header constants + `MISSING_HEADERS`/`UNKNOWN_ROLE` auth-failure variants
- `factories.py` — payload factories incl. named brand profiles pinned to the §3.2 identity-score formula (`high95`, `charity90`, `high75`, `mid70`, `low50`)
- `fixtures.py` — `client`/`api` pytest fixtures plus composite builders: `create_verified_brand`, `create_approved_campaign`, `create_active_number`, OCC-aware `attach_number`, `approved_tendlc_stack`, `queued_message_stack`, `sent_message_stack`, `failed_message_stack`, `charges`

**test_suite/** (74 tests, all compile clean, all import clean):
- `conftest.py` — sys.path bridge + `api`/`client` fixtures
- `test_01_dual_variant_paths.py` (4), `test_02_combinatorial_formulas.py` (4), `test_03_revision_loops.py` (4), `test_04_transitive_cascades.py` (4), `test_05_priority_pairs.py` (4), `test_06_boundaries.py` (4), `test_07_cross_entity_gates.py` (4), `test_08_temporal_occupancy.py` (4), `test_09_compensating_actions.py` (4), `test_10_entity_corners.py` (7), `test_11_state_machine_corners.py` (6), `test_12_calculation_corners.py` (5), `test_13_validation_corners.py` (9), `test_14_endpoint_corners.py` (4), `test_15_rbac.py` (3), `test_16_cross_cutting_layers.py` (4)

**Coverage audit**
- §1.8 difficulty (queue A): 18/18 instances emitted, each with ≥2 tests — zero shortfalls.
- §1.9 corner (queue B): all 31 non-stub instances emitted (≥1 test each); the 7 `excluded_because:` stubs in the `errors` section were correctly not translated (their difficulty-design owners carry the assertions).
- Skipped instances: 0 — every instance passed the PRD-first two-condition filter. (The `spam_floor_suspends_campaign_and_numbers` corner instance self-adjusts in its recipe to assert rate arithmetic + trust penalty + non-suspension at sub-floor volume, which the PRD covers verbatim; its full-suspension claim would be a gap, but the instance's own assert list only contains the reachable claims.)

**Citation/quality sweeps**
- Every one of the 74 tests has exactly one `Design:` tag; all 49 distinct tags resolve to real instance names in the source YAMLs (verified programmatically).
- Verbatim sweep: every quoted PRD sentence in every docstring has a sliding 6-word window that literally matches PRD.md (after stripping markdown backticks/bold markers) — 0 misses.
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere.
- `py_compile` passes for all 9 helper files and all 17 suite files; all modules import successfully under `PYTHONPATH=<task root>`.

## Step 6: Generate implementation — 2026-09-30T16:16:00.000Z

Implementation complete and smoke-verified. Summary:

**Files written (all under `workspace/implementation/`)**

| File | Lines | Purpose |
|---|---|---|
| `start.sh` | 10 | Guarded pip install, `exec python3 app.py`, `0.0.0.0:$PORT` |
| `requirements.txt` | 1 | flask>=3.0 |
| `app.py` | 52 | App factory, ApiError/404/405/400 handlers, blueprint registration |
| `store.py` | 23 | In-memory dicts (10 collections) + logical clock (default `2026-09-01T00:00:00.000Z`) |
| `errors.py` | 57 | `ApiError` + all 26 error-id constants |
| `response.py` | 37 | `meta`/`response_type`/`data` envelope; pagination fields in meta |
| `util.py` | 133 | ISO parse/format (3-fractional-digit Z), auth, pagination (limit 1–100 default 10, offset≥0), left-to-right nested 404, version/timestamp touch |
| `constants.py` | 83 | All fee/score/threshold constants, GSM-7 set, error/rejection code sets |
| `serializers.py` | 106 | Per-entity field projections (internal fields like `verified_at`/`activated_at` excluded) |
| `services/calc.py` | 121 | Identity scoring (ordered additive terms, clamp last), segments (GSM-7 vs UCS-2), fees (long-message surcharge once, segments>3), throughput tiering (inclusive boundaries), trust recompute (penalties before bonus), snapshot rates (half-up 2dp pct, floor bps) |
| `services/shared.py` | 302 | Charge ledger, account/campaign cascades (created_at ASC, reason stamping), queue drain (capacity = mps×60, queued_at ASC), stale sweep (run_index−queued_run_index ≥3), recurring/number fee pass (30-day trailing windows), final number fee on release, spam floor (inclusive), throughput/consent/recipient-busy gates |
| `routes/accounts.py` | 190 | Account CRUD + suspend/reinstate/close + run_ops + ops_runs list |
| `routes/brands.py` | 260 | Brand CRUD + submit/verify/fail/revoke + campaigns/consent_records sub-lists + prefix alias/list |
| `routes/campaigns.py` | 509 | Campaign CRUD + submit (OCC on resubmit)/approve/reject/suspend/reactivate/deactivate + numbers/messages/feedback sub-lists + snapshot create/get/list (account-nested + prefix) |
| `routes/numbers.py` | 333 | Provision (PORT_IN/SHORT_CODE gates), activate/complete_port/fail_port/attach (OCC)/detach/reinstate/release + messages sub-list + prefix alias/list |
| `routes/consent.py` | 167 | Consent create (POST_BRAND temporal check, +1460d retention), revoke, messages sub-list, prefix alias/list |
| `routes/messages.py` | 262 | Send (full gate gauntlet: campaign→number→consent→shape→throughput→busy), delivery_outcome, retry (re-checks consent/throughput), cancel, feedback sub-list, prefix alias/list |
| `routes/feedback.py` | 134 | Feedback create (STOP revokes consent in-request, ends APPLIED), lists, prefix alias |
| `routes/charges.py` | 50 | Charge lists (account-nested + prefix) with kind/reference filters |
| `routes/misc.py` | 54 | `POST /_clock/set_current_utc`, ops_run alias + prefix list |

**Endpoint coverage**

All 76 endpoint entries from the PRD §4 table are implemented: 1 clock, 8 account-level, 8 prefix-level single-resource GETs, 9 prefix-level collection GETs, 10 brand, 12 campaign (incl. 3 snapshot routes), 12 number, 5 consent, 8 message, 2 feedback, 2 charge. (Campaign GET re-derives `allocated_mps` per the "re-derived on every read" rule.)

**py_compile status**

All 18 Python files pass `python3 -m py_compile`.

**Smoke boot result**

Started via `bash start.sh` on a test port; verified: clock set, account create (201), brand create → submit (identity_score 95) → verify, campaign create → submit (trust 95, allocated_mps 10) → approve, number provision → activate → attach (OCC `expected_campaign_version` enforced), consent create (retention `+1460d` = 2030-08-31), send (QUEUED, 1 segment), run_ops (1 dequeued → SENT, MESSAGE 75¢ + CARRIER_PASSTHROUGH 45¢ + CAMPAIGN_RECURRING 1000¢ charged), invalid `error_code` → 400 `ERR_VALIDATION`, retryable `E30034` failure → retry → re-QUEUED at run_index 1, `ERR_RECIPIENT_BUSY` on duplicate in-flight recipient, snapshot with attempted=0 → all rates 0 and trust unchanged, campaign suspend cascade (`CAMPAIGN_SUSPENDED` stamped, number SUSPENDED) → reactivate (number auto-restored to ACTIVE), 401/403/404 envelope shapes, and a second fresh boot showing empty store (`total_count: 0`). Both test PIDs killed individually; no broad kill patterns used.

## Step 7: Test-fix iteration loop — 2026-09-30T16:29:00.000Z

All 8 rounds pass 74/74. Clean sweep achieved. (Orchestrator verified: all 8 results.*.json show 74/74, and every results file mtime 16:29:10 is newer than the newest implementation edit 16:26:30 — no post-sweep writes.)

**Iterations run:** 2 (initial sweep: 53/74 in all 8 rounds, 21 distinct failures, non-flaky; second sweep after fixes: 74/74 in all 8 rounds).

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:**
- `test_helpers/api_client.py` — added a `get()` override on `ApiClient` that defaults bare reads (no `headers=` passed) to PlatformAdmin headers. PRD section 1 requires `X-User-ID`/`X-User-Role` on *every* request ("A request missing either header ... is rejected with ERR_UNAUTHENTICATED"), so the implementation's 401 on unauthenticated GETs was correct; ~35 read call sites across the suite omitted headers, causing `KeyError: 'status'` / `KeyError: 'trust_score'` when tests indexed into the error envelope. PlatformAdmin is the safe default since PRD section 2.1 says it "may read every resource."

**Fixes applied to `test_suite/`:** none.

**Fixes applied to `workspace/implementation/`:**
- `routes/brands.py` (`create_brand`, `_brand_submit`, `REQUIRED_BRAND_FIELDS`) — removed `website_url` from the non-empty field checks at both create and submit time. PRD section 3.2's identity-score formula grants "+10 if `website_url` is non-empty," which requires empty-website brands to be creatable, submittable, and scorable (score 50) so that the PRD-verbatim `ERR_BRAND_SCORE_TOO_LOW` verify path is reachable; enforcing non-empty `website_url` at submit made that path unreachable and contradicted the formula term.
- `routes/messages.py` (`send_message`) — reordered the compliance gate so the campaign-APPROVED check fires before the sender-number existence lookup, per PRD section 2.8 step 5 ("campaign must be APPROVED and the sender number must be ACTIVE and attached", in that order). Fixes `test_send_against_pending_review_campaign_is_rejected` (was returning `ERR_NOT_FOUND` instead of `ERR_CAMPAIGN_NOT_APPROVED`).
- `routes/messages.py` (`delivery_outcome`) — relaxed the FAILED-outcome `error_code` validation from membership in a hardcoded 5-code list to the carrier-code shape (`E` + digits). PRD section 3.6 requires the code be "drawn from the carrier error code set" but never enumerates that set (only names retryable codes `E30034`/`E30007`), so strict membership in an undeclared set is not uniquely derivable; the shape check keeps the PRD-required `ERR_VALIDATION` rejection for malformed codes while accepting legitimate carrier codes like `E21610` used by the non-retryable-retry test.

## Step 8: Finalize PRD — 2026-09-30T16:33:00.000Z

The diff is exactly the four edits (two for the send-ordering item, one each for the other two), all confined to lines traceable to the Step 7 diff. One final sanity check on the test_helpers item — confirmed it produces no PRD edit since PRD §1/§2.1 already mandates headers on every request and PlatformAdmin read access.

**Line counts:** PRD.md 383 lines, PRD_FINALIZED.md 383 lines (0% delta — edits are in-place sentence rewrites, no lines added or removed).

**Changes (one bullet per edit):**
- §3.2 (brand registration paragraph) — revise — marked `website_url` optional (omittable/empty at creation and submission, forgoing only its +10 scoring term) — `implementation/routes/brands.py:78` (create via `body.get("website_url", "")`), `brands.py:173-176` (`REQUIRED_BRAND_FIELDS` excludes `website_url`), `services/calc.py:36` (score term only when non-empty).
- §3.2 (submission preconditions) — revise — pinned the required non-empty field list (`legal_name`, `tax_id`, `business_type`, `address_line1`, `city`, `region_code`, `postal_code`, `country_code`, `opt_in_mechanism`) explicitly excluding `website_url` — `implementation/routes/brands.py:44-48`.
- §2.8 step 5 + §3.6 send gauntlet steps 2–3 — revise — pinned that the campaign-`APPROVED` check fires before any sender-number check including the number's existence lookup, so an unapproved campaign with an unresolvable `sender_number_id` yields `ERR_CAMPAIGN_NOT_APPROVED`, not `ERR_NOT_FOUND` — `implementation/routes/messages.py:71-88` (campaign existence → APPROVED → number existence → attached → ACTIVE).
- §3.6 (delivery outcomes) — revise — defined the carrier error code set by shape (`E` followed by one or more digits) rather than enumeration, with `ERR_VALIDATION` for malformed codes — `implementation/routes/messages.py:26-30` (`_is_carrier_error_code`), `messages.py:216-221`.

**No PRD edit for the `test_helpers/api_client.py` fix** — pure fixture bug; PRD §2.1 already requires `X-User-ID`/`X-User-Role` on every request and grants PlatformAdmin read access to every resource.

**Per-edit pre-edit search log:**

1. **website_url optionality (§3.2, two edits)**
   - (a) Subject: which brand fields are required/non-empty at create and submit.
   - (b) Enumerated paths: `grep website_url|REQUIRED_BRAND_FIELDS|require_nonempty` across `implementation/` → `routes/brands.py:44-48, 57-60, 78, 173-176`; `services/calc.py:36` (identity_score +10 term); downstream identity_score consumers `routes/brands.py:205` (verify ≥60), `routes/campaigns.py:197` (toll-free ≥75), `services/shared.py:98` (carrier filter), `services/calc.py:80` (TEN_DLC initial trust). Also confirmed no other `require_nonempty` call site (accounts, numbers, consent, feedback, campaigns, messages) touches brand fields.
   - (c) Adjustment: wording says website_url "may be omitted or empty at both creation and submission" and "simply forgoes its scoring term" — deliberately does not claim it is excluded from any other validation, and leaves the score formula verbatim, so all enumerated read paths remain accurately described.

2. **Send-gate ordering (§2.8 step 5, §3.6 steps 2–3)**
   - (a) Subject: ordering of campaign-approval vs sender-number existence/state/attachment checks on send.
   - (b) Enumerated paths: `routes/messages.py:64-107` (`send_message` full gauntlet, incl. `require_nonempty` on ids, campaign existence/nesting 404, APPROVED check at line 76-77, number existence/nesting 404 at 78-80, attach check, ACTIVE check); `routes/messages.py:227-257` (`retry_message` — re-checks `ERR_CAMPAIGN_NOT_APPROVED` after its own 404, consistent); `services/shared.py` (`check_throughput`, `check_recipient_not_busy`, `active_consent_for` — downstream of the gate, order unaffected); §2.8 steps 3/5 to keep the global ordering list and the §3.6 narrative from contradicting each other.
   - (c) Adjustment: both §2.8 step 5 and §3.6 were edited together so the global ordering list and the per-endpoint narrative agree; wording scopes the precedence strictly to the send compliance gate ("for sends") and explicitly notes campaign existence still precedes the APPROVED check, avoiding any false claim about step 3 path-id existence ordering generally.

3. **Carrier error code shape (§3.6 delivery outcomes)**
   - (a) Subject: what constitutes a valid `error_code` on a FAILED delivery outcome.
   - (b) Enumerated paths: `grep failed_error_code|RETRYABLE_ERROR_CODES|CARRIER_ERROR_CODES|DELIVERY_OUTCOMES` → `routes/messages.py:26-30` (`_is_carrier_error_code` shape: `E` + ≥1 digit), `messages.py:216-224` (FAILED validation + record), `messages.py:124, 253` (field init/clear), `messages.py:235-240` (retry membership in `E30034`/`E30007` — unchanged), `constants.py:72-73`, `serializers.py:45`.
   - (c) Adjustment: wording defines the set "by shape rather than by enumeration" and names `E30034`/`E30007`/`E21610` only as examples, so the retry path's fixed retryable list (still verbatim in the retry paragraph) is not contradicted and no finite set is asserted anywhere.

Output file: `workspace/PRD_FINALIZED.md`

## Step 9: Complete PRD scan — 2026-09-30T16:39:00.000Z

Done. PRD_COMPLETED.md is written at `workspace/PRD_COMPLETED.md`.

- Source: `PRD_FINALIZED.md` (383 lines, 56,420 chars) → `PRD_COMPLETED.md` (384 lines, 60,156 chars; +1 line, +3,736 chars).
- Counts: 14 ambiguity-pins, 3 mismatch-revisions (17 changes total).

Changes (section — insert/revise — kind — what — impl evidence):

- §2.1 role bullet — revise — mismatch — DeliverabilityAnalyst also reads accounts — routes/accounts.py:69 (`READ_ROLES + ["DeliverabilityAnalyst"]`).
- §2.2 success format — insert — ambiguity — `api_request_timestamp` is stamped from the logical clock, not wall-clock — response.py:12 (`now_iso()`).
- §2.5 logical clock — insert — ambiguity — `to_iso8601` accepts any parseable ISO 8601 (Z or offset) and is normalized to 3-fractional-digit UTC — routes/misc.py:28-32.
- §2.8 validation order — insert — ambiguity — numbered order is cross-category priority; per-endpoint interleaving of field-shape with gates is pinned (send pipeline, submit pipeline) — routes/messages.py:70-107, routes/campaigns.py:240-256.
- §3.1 ops run — insert — ambiguity — run_ops obeys the account gate (ERR_ACCOUNT_SUSPENDED/ERR_ACCOUNT_CLOSED) — routes/accounts.py:143.
- §3.2 brand submit — insert — ambiguity — from-state check (ERR_BRAND_REVOKED / ERR_INVALID_STATE) precedes field preconditions — routes/brands.py:168-178.
- §3.2 brand verify — insert — ambiguity — verification stamps a verification instant, refreshed on re-verification (used by POST_BRAND consent) — routes/brands.py:212.
- §3.3 campaign create — insert — ambiguity — `brand_id` must exist under the account (404); brand need not be verified at creation — routes/campaigns.py:86-89.
- §3.5 base_mps — insert — ambiguity — number-type base_mps table pinned: TEN_DLC 1, TOLL_FREE 3, SHORT_CODE 100 — routes/numbers.py:47.
- §3.6 consent create — insert — ambiguity — brand must exist and be non-REVOKED (ERR_NOT_FOUND / ERR_BRAND_REVOKED); `captured_at` must parse; never-verified brand cannot anchor POST_BRAND consent — routes/consent.py:50-64.
- §3.6 send gauntlet — revise — mismatch — field shape validated up front (ids) and after consent gate (body/carrier); old step "7. Field shape … last" removed; sender-number sub-order pinned as existence → attachment → ACTIVE; multiple matching ACTIVE consents resolve to most recently created; allocated_mps re-derived live at the throughput check — routes/messages.py:70-107, services/shared.py:276-286.
- §3.6 retry — insert — ambiguity — retry re-checks campaign APPROVED, re-resolves `consent_record_id`, applies recipient-busy gate, clears `failed_error_code` — routes/messages.py:241-256.
- §3.8 feedback — insert — ambiguity — STOP with no matching ACTIVE consent is still recorded+applied with no effect; BLOCK/SPAM accrue by the event's own creation day — routes/feedback.py:79-85.
- §3.8 spam floor — insert — ambiguity — already-SUSPENDED campaign is not re-touched by the floor check (no extra version bump) — services/shared.py:232-234.
- §4 table (accounts GET row) — revise — mismatch — added DeliverabilityAnalyst to authorized roles — routes/accounts.py:69.
- §4 table (campaigns/numbers/consent/messages/feedback list rows) — revise — ambiguity — filter lists updated to match implemented filter sets (added status, sender_number_id, consent_record_id, message_id where impl supports them) — routes/campaigns.py:488-494, numbers.py:148-155, consent.py:100-110, messages.py:147-160, feedback.py:102-112.

Note (informational, not a PRD change): `routes/campaigns.py` references an undefined `_filter_campaigns` (a stray block sits as dead code after the `return` in `list_snapshots`, campaigns.py:488-494), and `routes/numbers.py` similarly has dead code after `return` in `release_number` (numbers.py:323-333). All 8 recorded test runs pass 74/74, so these paths are unexercised by the suite; per instructions I did not modify implementation and instead described list filters generically in the PRD table.

## Post-Step-9 implementation repair + re-verification — 2026-09-30T16:43:30.000Z

Step 9's informational note flagged two real chunk-append defects on PRD §4-declared endpoints that the suite never exercised (so Step 7's clean sweep could not see them). Orchestrator investigated and repaired; the Step 9 PRD "described filters generically" workaround is superseded — the endpoints now genuinely work.

**Root cause:** truncated `Write`/misplaced `Edit` appends left code after a `return`, breaking two endpoints:

1. `routes/campaigns.py` — a stray campaign-filter body was pasted after `list_snapshots`'s `return` (old lines 488-494), so `def _filter_campaigns(items):` never existed while being **called** at `list_account_campaigns` (line 137) and `list_campaigns` (line 505) → `GET /messaging/accounts/<id>/campaigns` and `GET /messaging/campaigns` would raise `NameError` (500).
2. `routes/numbers.py` — the entire `GET /messaging/numbers` prefix-list handler body was pasted after `release_number`'s `return` (old lines 323-333) as dead code, and there was **no** `@bp.get("/messaging/numbers")` route at all → the prefix-level numbers list endpoint was missing entirely.

**Fixes (implementation only; no PRD/test change — both behaviors were already in PRD §4):**
- `routes/campaigns.py` — removed the stray post-`return` block and added a proper module-level `def _filter_campaigns(items)` (status + brand_id filters) between `list_snapshots` and `list_campaigns`.
- `routes/numbers.py` — removed the dead post-`return` block and added a real `@bp.get("/messaging/numbers")` `def list_numbers()` route applying account_id + `_filter_numbers` + sort + pagination.

**Verification:**
- `python3 -m py_compile` clean on both files; runtime `hasattr` confirms `_filter_campaigns`, `list_campaigns`, `list_numbers`, `_filter_numbers` all resolve; an AST scan found no remaining code after any `return` in either file.
- Smoke boot: `GET /messaging/campaigns` and `GET /messaging/numbers` both return 200 with a proper pagination envelope (previously NameError / 404).
- **Re-ran the full 8-round sweep after the fix** (implementation changed post-Step-7): all 8 rounds **74/74, 0 failed**; every results file mtime (16:43:24) is newer than the newest implementation edit (16:40:52) — no post-sweep writes, sweep valid.
