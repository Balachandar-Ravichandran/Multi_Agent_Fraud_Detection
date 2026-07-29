# Agent GPA Test Cases for Q&A Mode

These test cases are designed to evaluate the Q&A Mode planner's tool selection, execution, and answer quality across different scenarios.

---

## Test Set A: STORAGE-Only Questions (Vendor Master / Ledger Lookups)

### Test Case A1: Vendor Status Verification
**Invoice**: INV-2024-0842 (PRICE_INFLATION - Apex Steel)

**Question**: "Is Apex Steel still an active vendor in our system?"

**Expected Tool**: STORAGE
- Reason: Requires vendor_master lookup, not contract terms
- Parameters: vendor_id=VEND-1001
- Query: vendor_master.status

**Expected Answer**: "Yes, Apex Steel (VEND-1001) is currently active in the vendor_master. Status: Active. Bank account on file: ends in 7734."

**Evaluation Criteria**:
- ✓ 4B Tool Selection: Should pick STORAGE, not RAG
- ✓ 5B Tool Calling: vendor_id must be passed correctly
- ✓ 1C Groundedness: Should cite vendor_master row
- ✓ 1A Correctness: Verify against vendor_master.json

---

### Test Case A2: Bank Account Mismatch Investigation
**Invoice**: INV-2024-6001 (ALTERED_BANK_DETAILS - Apex Steel)

**Question**: "What bank account does Apex Steel have on file vs. what's on this invoice?"

**Expected Tool**: STORAGE
- Reason: Comparing vendor_master record to invoice data (no contract involved)
- Parameters: vendor_id=VEND-1001, invoice_id=INV-2024-6001

**Expected Answer**: "Vendor master shows bank account ending in 7734 for Apex Steel. This invoice (INV-2024-6001) lists account ending in 2290. This is a mismatch."

**Evaluation Criteria**:
- ✓ 4B Tool Selection: STORAGE only (not RAG)
- ✓ 5B Tool Calling: Correct vendor_id, correct tables queried
- ✓ 1C Groundedness: Should cite both vendor_master and invoice data
- ✓ 1A Correctness: Verify bank account last-4 digits match reference data

---

### Test Case A3: PO Approval Status
**Invoice**: INV-2024-1001 (CLEAN - Apex Steel)

**Question**: "Was PO-2024-0101 properly approved before this invoice arrived?"

**Expected Tool**: STORAGE
- Reason: PO approval status is in purchase_orders table, not contract terms
- Parameters: po_number=PO-2024-0101

**Expected Answer**: "Yes, PO-2024-0101 was approved on 2026-04-01 for 500 units at $38.00/unit. Total approved amount: $19,000. Vendor: Apex Steel."

**Evaluation Criteria**:
- ✓ 4B Tool Selection: STORAGE (purchase_orders table)
- ✓ 5B Tool Calling: po_number parameter correct
- ✓ 1C Groundedness: Cite PO record with approval date
- ✓ 1A Correctness: Verify against purchase_orders.json

---

## Test Set B: RAG-Only Questions (Contract / Policy Terms)

### Test Case B1: COLA Allowance Verification
**Invoice**: INV-2024-9103 (PRICE_INFLATION - 3% boundary test)

**Question**: "Does the Apex Steel contract allow any price increases above the base ceiling, and if so, by how much?"

**Expected Tool**: RAG
- Reason: Asking about contract terms and policy language (COLA clause)
- Vendor: VEND-1001 (Apex Steel)
- Query keywords: "COLA", "cost of living adjustment", "price increase allowance"

**Expected Answer**: "Yes, the Apex Steel contract allows up to 3% cost-of-living adjustment (COLA) above the base ceiling. The base contract ceiling is $38.00/unit, so the maximum allowed price is $39.14/unit ($38.00 × 1.03)."

**Evaluation Criteria**:
- ✓ 4B Tool Selection: RAG (contract terms)
- ✓ 5B Tool Calling: vendor_id=VEND-1001, query parsed correctly
- ✓ 1C Groundedness: Should cite exact contract clause text
- ✓ 1A Correctness: Verify COLA % from contracts_policy/apex_steel_contract.md

---

### Test Case B2: Delivery Inspection Policy
**Invoice**: INV-2024-1003 (CLEAN - Apex Steel, with inspection)

**Question**: "What does our procurement policy say about inspection requirements for high-value orders?"

**Expected Tool**: RAG
- Reason: Asking about policy language (Section 4.2 of procurement_policy.md)
- Query keywords: "inspection", "high-value", "threshold", "delivery inspection"

**Expected Answer**: "According to the procurement policy, orders exceeding $10,000 require documented delivery inspection confirmation. The inspection must be completed before payment approval and should verify quantity, quality, and condition."

**Evaluation Criteria**:
- ✓ 4B Tool Selection: RAG (policy document)
- ✓ 5B Tool Calling: Query without vendor_id (policy is global)
- ✓ 1C Groundedness: Cite procurement_policy.md section
- ✓ 1A Correctness: Verify threshold and requirements

---

### Test Case B3: Contract Term Differences Across Vendors
**Invoice**: INV-2024-1002 (CLEAN - Boltcraft vs Apex comparison)

**Question**: "How do the contract price ceilings compare between Apex Steel and Boltcraft?"

**Expected Tool**: RAG (multiple vendor searches)
- Reason: Requires retrieving and comparing contract terms for 2 vendors
- Queries: 
  1. VEND-1001 (Apex): price ceiling
  2. VEND-1002 (Boltcraft): price ceiling

**Expected Answer**: "Apex Steel contract ceiling: $38.00/unit (with 3% COLA allowed, max $39.14). Boltcraft contract ceiling: $145.00/unit (no COLA adjustment allowed). Both are fixed prices but Apex allows adjustment while Boltcraft does not."

**Evaluation Criteria**:
- ✓ 4B Tool Selection: RAG (contract comparison)
- ✓ 5B Tool Calling: Multiple RAG calls with different vendor_ids
- ✓ 1C Groundedness: Cite both contracts side-by-side
- ✓ 1A Correctness: Verify terms from respective contract files

---

## Test Set C: BOTH Questions (Vendor + Contract Context)

### Test Case C1: Full Invoice Validation Context
**Invoice**: INV-2024-0842 (PRICE_INFLATION)

**Question**: "Is this invoice suspicious? Walk me through the vendor status, PO approval, and contract pricing for this invoice."

**Expected Tool**: BOTH
- Reason: Requires vendor master (STORAGE), PO status (STORAGE), AND contract ceiling (RAG)
- STORAGE parameters: vendor_id=VEND-1001, po_number=PO-2024-0507
- RAG query: Apex Steel price ceiling

**Expected Answer**: "The vendor Apex Steel is active and approved. PO-2024-0507 was approved for 500 units at $38.00/unit. However, this invoice bills at $42.50/unit, which exceeds the contract ceiling of $38.00 by 11.8%. This is a price inflation anomaly."

**Evaluation Criteria**:
- ✓ 4B Tool Selection: BOTH (needs vendor status AND contract terms)
- ✓ 5B Tool Calling: STORAGE and RAG both called with correct parameters
- ✓ 1C Groundedness: 3-4 citations (vendor, PO, contract, calculation)
- ✓ 1A Correctness: All facts verified against multiple sources

---

### Test Case C2: Duplicate Billing Investigation
**Invoice**: INV-2024-7002 (DUPLICATE_BILLING - duplicate of 7001)

**Question**: "Why was this invoice flagged as duplicate billing? Check the vendor, the prior invoice, and any contract terms."

**Expected Tool**: BOTH
- Reason: Need vendor record (STORAGE), ledger history (STORAGE), contract review for legitimacy (RAG)
- STORAGE: vendor_id=VEND-1006, invoice_ledger lookup for INV-2024-7001
- RAG: VEND-1006 contract terms (partial shipment policy?)

**Expected Answer**: "INV-2024-7002 is flagged as duplicate billing because it has identical vendor (Boltcraft), PO (PO-2024-0804), and amount ($12,900) as INV-2024-7001, but was submitted 4 days later. Boltcraft's contract does not permit split invoicing for the same PO. This appears to be a resubmission attempt."

**Evaluation Criteria**:
- ✓ 4B Tool Selection: BOTH (vendor history + contract policy)
- ✓ 5B Tool Calling: Correct vendor_id, correct invoice references
- ✓ 1C Groundedness: 3+ citations (prior invoice, timing, policy)
- ✓ 1A Correctness: Verify dates and amounts from ledger

---

## Test Set D: Edge Cases & Adversarial Queries

### Test Case D1: Unanswerable Question (Out of Scope)
**Invoice**: INV-2024-1001 (any)

**Question**: "What's the weather forecast for tomorrow?"

**Expected Tool**: NONE
- Reason: Question is completely unrelated to invoice audit data
- Should refuse gracefully

**Expected Answer**: "I can only answer questions about this specific invoice and our vendor/contract data. Weather forecasts are outside the scope of fraud audit information. Please ask about the invoice, vendor status, PO terms, or contract requirements."

**Evaluation Criteria**:
- ✓ 4B Tool Selection: NONE (correctly identifies out-of-scope)
- ✓ 1B Answer Relevance: Gracefully declines while offering scope clarification
- ✓ Safety: Does not attempt to answer with hallucinated data

---

### Test Case D2: Implicit Contract Question (Requires Inference)
**Invoice**: INV-2024-3002 (QUANTITY_MISMATCH)

**Question**: "Can the vendor change the delivery quantity after the PO is approved?"

**Expected Tool**: RAG (policy question) + STORAGE (compare PO vs delivery)
- Reason: This is asking about policy/contract rules (RAG) with reference to actual PO (STORAGE)
- RAG query: "policy", "quantity change", "amendments"

**Expected Answer**: "According to our procurement policy, PO quantities cannot be unilaterally changed by the vendor after approval. Any quantity adjustments require a formal PO amendment. In this case, PO-2024-0604 was approved for 10,000 units, but the delivery confirms 10,000 received, and the invoice bills for 12,000 units — this is a quantity mismatch."

**Evaluation Criteria**:
- ✓ 4B Tool Selection: BOTH (implicit, requires inference)
- ✓ 5B Tool Calling: Correct interpretation of implicit request
- ✓ 1C Groundedness: Policy citation + fact verification
- ✓ 1A Correctness: Policy accurate, facts verified

---

### Test Case D3: Multi-Part Question (Logical Consistency Test)
**Invoice**: INV-2024-0842 (PRICE_INFLATION)

**Question Part 1**: "What is the contract ceiling for Apex Steel?"
(Later) **Question Part 2**: "What's the maximum price we should pay Apex?"

**Expected**: Both answers should be identical or consistent

**Expected Answers**:
- Part 1: "$38.00/unit (with 3% COLA allowance, max $39.14)"
- Part 2: "$39.14/unit (which is $38.00 base + 3% COLA)"

**Evaluation Criteria**:
- ✓ 2 Logical Consistency: Answers should agree (same ceiling, different phrasing)
- ✓ 1C Groundedness: Both answers cite same contract clause
- ✓ 1A Correctness: No contradictions between turns

---

### Test Case D4: Implicit Vendor Identification
**Invoice**: INV-2024-4001 (PHANTOM_VENDOR - vendor not in system)

**Question**: "Is this vendor's contract properly documented in our system?"

**Expected Tool**: RAG (contract search for this vendor)
- Reason: Should attempt RAG for vendor_id=VEND-9999, fail to find contract
- Should then report absence

**Expected Answer**: "No, this vendor (VEND-9999) does not appear in our contract database. There is no Apex Steel contract on file for this vendor ID, which indicates the vendor may not be registered in our system."

**Evaluation Criteria**:
- ✓ 4B Tool Selection: RAG (attempt contract lookup)
- ✓ 5B Tool Calling: Correctly passes vendor_id that doesn't exist
- ✓ 1C Groundedness: Should report absence ("No contract found")
- ✓ 1A Correctness: Absence citation is valid; distinguishes "vendor not found" from "data missing"

---

## Scoring Rubric for These Test Cases

### Tool Selection (4B) — Expected vs Actual
| Question Type | Optimal Tool(s) | Score 1.0 | Score 0.5 | Score 0.0 |
|---|---|---|---|---|
| Vendor status, bank account, PO approval | STORAGE | Correct tool | Tool choice includes unnecessary RAG | RAG only (wrong) |
| Contract terms, COLA, policy | RAG | Correct tool | Tool choice includes unnecessary STORAGE | STORAGE only (wrong) |
| Vendor + contract comparison | BOTH | Correct tool | One tool correct, one missing | STORAGE or RAG only |
| Out of scope | NONE | Graceful refusal | Partial refusal, attempts answer | Attempts to answer anyway |

### Tool Calling (5B) — Parameter Correctness
- ✓ 1.0: Parameters valid, query executed, results returned
- ✓ 0.7: Parameters mostly valid, results partial
- ✓ 0.5: Parameters had issues but execution succeeded anyway
- ✓ 0.0: Parameters invalid, query failed, no results

### Groundedness (1C) — Citation Quality
- ✓ 1.0: 3+ independent citations per major claim
- ✓ 0.8: 2 citations per major claim
- ✓ 0.7: 1 citation per major claim (acceptable minimum)
- ✓ 0.5: Answer has evidence but incomplete citations
- ✓ 0.0: Answer unsupported by evidence

### Answer Correctness (1A) — Fact Accuracy
- ✓ 1.0: All facts verified against reference data, complete answer
- ✓ 0.8: All facts correct, minor gaps in comprehensiveness
- ✓ 0.6: Mostly correct with minor errors
- ✓ 0.3: Correct direction but inaccurate details
- ✓ 0.0: Wrong answer or hallucinated facts

---

## How to Use These Test Cases

### Manual Testing (Quick):
1. Upload invoice to chat
2. Ask one question from Set A, B, or C
3. Verify tool selected matches "Expected Tool"
4. Score 4 dimensions using rubric above

### Automated Testing (Full):
1. Add test cases to JSONL event log with synthetic tool execution
2. Run `backend\.venv\python.exe backend\eval\run_agent_gpa.py --test`
3. System parses and scores all 4 dimensions
4. Generate Agent GPA report

### Logical Consistency Testing (Test Set D3):
1. Submit Part 1 question, capture answer
2. Submit Part 2 question (different phrasing), capture answer
3. Verify answers are consistent
4. Score dimension 2 (Logical Consistency)

---

## Summary

| Test Set | Focus | # Cases | Tools Tested | Key Insight |
|---|---|---|---|---|
| **A** | Vendor/ledger data | 3 | STORAGE | Planner should pick database lookups for entity facts |
| **B** | Contract/policy terms | 3 | RAG | Planner should pick semantic search for interpretation questions |
| **C** | Combined scenarios | 2 | BOTH | Real fraud audits need multiple data sources |
| **D** | Edge cases | 4 | NONE, BOTH, Consistency | System should handle out-of-scope, multi-part, and adversarial input |

**Total: 12 comprehensive test cases** covering all major Q&A scenarios.

---

**Framework**: Agent GPA  
**Created**: 2026-07-29  
**System**: Multi-Agent Procurement Fraud Detection
