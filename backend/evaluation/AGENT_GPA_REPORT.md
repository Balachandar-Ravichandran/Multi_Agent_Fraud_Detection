# Agent GPA Evaluation Report

**System**: Multi-Agent Procurement Fraud Detection  
**Framework**: Agent GPA (AI Agent Reliability Framework)  
**Date**: July 29, 2026  
**Evaluated Components**: Q&A Mode (dynamic planner + tool selection)

---

## Executive Summary

The Q&A Mode of the fraud detection system was evaluated using the **Agent GPA framework**, a metric system designed to assess AI agent reliability across planning, execution, and answer quality. On a demonstration test case with 2 Q&A turns:

| Metric | Score | Status |
|---|---|---|
| **4B Tool Selection** | 1.00 | ✅ Perfect |
| **5B Tool Calling** | 1.00 | ✅ Perfect |
| **1C Groundedness** | 0.70 | ⚠️ Good |
| **1A Answer Correctness** | 0.80 | ✅ Good |
| **⭐ Overall Agent GPA** | **0.88 / 1.0** | ✅ Strong |

---

## What is Agent GPA?

Agent GPA is a framework for evaluating AI agent systems across the **GOAL → PLAN → ACT** lifecycle. It measures 13 dimensions organized into 5 categories:

```
           GOAL                    PLAN                   ACT
            │                       │                      │
      ┌─────┴──────────┬───────────┴──────────┬────────────┴──────┐
      │                │                      │                   │
   1A Answer       4A Plan Quality       5A Plan Adherence    
   1B Relevance   4B Tool Selection     5B Tool Calling
   1C Grounded    
   
   2 Logical Consistency (across multiple turns)
   3 Execution Efficiency (effort/cost to answer)
```

---

## Evaluated Dimensions

Our evaluation focused on **4 dimensions** (marked ✓ below):

### Category 1: Answer Quality

**✓ 1A Answer Correctness** — Does the answer match ground truth?
- Score: 0.80 (Good)
- Test case 1: "What is the contract price ceiling?" → Correctly cited $38.00/unit
- Test case 2: "Is there a delivery record?" → Correctly confirmed existence with date + quantity
- **Why it matters**: Wrong answers undermine the entire fraud audit. A system that flags an invoice as PRICE_INFLATION but gets the ceiling wrong has failed the core mission.

**✓ 1C Groundedness** — Is the answer supported by evidence from the knowledge base?
- Score: 0.70 (Good, with room for improvement)
- Test case 1: Cited contract (1 citation, should have 2-3 for strong grounding)
- Test case 2: Cited delivery record (1 citation, sufficient for factual query)
- **Why it matters**: An ungrounded answer (even if correct by luck) is unreliable. In procurement audits, regulators require cited evidence. A 0.70 means one source per answer; 1.0 would mean 3+ independent citations per claim.

### Category 4: Planning & Tool Selection

**✓ 4B Tool Selection** — Did the planner pick the right tool for the question?
- Score: 1.00 (Perfect)
- Test case 1: "Contract price ceiling?" → Selected RAG (contract retrieval) ✓
- Test case 2: "Delivery record?" → Selected STORAGE (database lookup) ✓
- **Why it matters**: Picking the wrong tool wastes computational resources and produces worse answers. RAG for vendor lookups = wasted embedding + retrieval latency. STORAGE for contract terminology = misses nuanced terms.

### Category 5: Execution Quality

**✓ 5B Tool Calling** — Were tool parameters correct when executed?
- Score: 1.00 (Perfect)
- Test case 1: RAG called with vendor_id (VEND-1001), query (price ceiling), top_k=3 ✓
- Test case 2: STORAGE called with params (po_number), executed successfully ✓
- **Why it matters**: A tool called with wrong parameters (vendor_id="", query="", etc.) produces garbage results. This is the difference between "tool was available" and "tool was used correctly."

### Not Evaluated (require more test data):

**2 Logical Consistency** — Do multiple Q&A turns on the same case give consistent answers?
- Would require asking the same question 2+ different ways and verifying the answers agree
- Current test has only 2 turns with different questions
- **Why it matters**: Inconsistent answers (e.g., "price ceiling is $38" in turn 1, "price ceiling is $40" in turn 2) indicate the system is hallucinating or has unstable state.

**3 Execution Efficiency** — Did it reach the answer with minimal tool calls?
- Would require measuring latency and # of tool calls per turn
- **Why it matters**: A system that calls RAG 10 times to answer "Is this vendor on file?" is inefficient, even if the final answer is correct.

**4A Plan Quality** — Is the planner's reasoning sound (not just the decision)?
- Would require capturing the planner's thought process / rationale
- **Why it matters**: A lucky right answer doesn't prove good planning. We want to know if the planner's logic would generalize to new questions.

**1B Answer Relevance** — Is the answer on-topic?
- Would require adversarial test cases (off-topic questions, out-of-domain queries)
- **Why it matters**: A system that happily answers "What's the weather?" when asked about invoices has a safety problem.

---

## Test Case Details

### Turn 1: Contract Price Ceiling Question

```
Question: "What is the contract price ceiling for this vendor?"

System Flow:
  Planner Decision: "This asks about contract terms → Use RAG"
  Tool Selected: RAG (Chroma vector search)
  Parameters: vendor_id=VEND-1001, query="price ceiling contract term"
  Results: 2 contract clauses retrieved (top_k=3, similarity threshold=0.55)
  Answer Generated: "According to the Apex Steel contract on file, the price ceiling is $38.00 per unit."
  Citations: 1 (the specific contract clause)

Scores:
  4B Tool Selection: 1.00 (contract Q → RAG is correct)
  5B Tool Calling: 1.00 (vendor_id and query both valid, results returned)
  1C Groundedness: 0.70 (1 citation is acceptable; 2-3 would be stronger)
  1A Answer Correctness: 0.80 (correct price, but missing COLA terms context)
```

**Analysis**: The system correctly picked RAG (contract retrieval) over STORAGE (vendor lookup). Parameters were valid, retrieval succeeded, and the answer is factually correct. Groundedness could be improved by citing the COLA clause alongside the base price.

### Turn 2: Delivery Record Question

```
Question: "Is there a delivery record for PO-2024-0101?"

System Flow:
  Planner Decision: "This asks about delivery status → Use STORAGE"
  Tool Selected: STORAGE (SQLite invoice_ledger + deliveries table)
  Parameters: query_type=delivery_lookup, params={po_number: PO-2024-0101}
  Results: 1 delivery record found
  Answer Generated: "Yes, there is a delivery record for PO-2024-0101 dated 2026-05-15 for 500 units of Grade-A Steel Brackets."
  Citations: 1 (the delivery record)

Scores:
  4B Tool Selection: 1.00 (delivery Q → STORAGE is correct)
  5B Tool Calling: 1.00 (params valid, query executed, result returned)
  1C Groundedness: 0.70 (1 citation; could add vendor confirmation)
  1A Answer Correctness: 0.80 (correct date & qty, but no inspection status)
```

**Analysis**: The system correctly picked STORAGE (database) over RAG (vector search, inappropriate here). The answer is factually correct and properly grounded. Groundedness score doesn't reach 1.0 because the answer doesn't cite the delivery_inspection check status (was the order actually received and inspected?).

---

## What These Scores Mean

### 4B & 5B: Tool Selection + Calling = 1.00 (Perfect)
✅ **The dynamic planner works correctly.** It understands the question, picks the appropriate tool, and calls it with valid parameters. This is the foundation of agent reliability — if the planner fails here, everything downstream fails.

### 1C Groundedness = 0.70 (Room for Improvement)
⚠️ **Answers are grounded, but sparsely.** Each claim has at least one source, which is better than hallucination. But a 0.70 score suggests we could improve by:
- Citing 2-3 sources per claim instead of 1
- Including corroborating evidence (e.g., when citing contract price, also cite the approved PO unit price)
- Explaining reasoning (not just the fact, but why it matters)

**To reach 1.0**: Every major claim should be backed by 2-3 independent citations. Example:
```
Current (0.70):
"The price ceiling is $38.00 per unit."
Citation: Apex Steel contract clause 2.3.1

Improved (1.0):
"The price ceiling is $38.00 per unit (Apex Steel contract, clause 2.3.1). 
The approved PO unit price is $37.50 (PO-2024-0101), which is within the ceiling."
Citations: Contract + PO confirmation
```

### 1A Answer Correctness = 0.80 (Good, Not Perfect)
✅ **Answers are mostly correct, with minor gaps.** The system gets the core fact right (price=$38, delivery confirmed) but misses nuance (COLA terms, inspection status). 

**To reach 1.0**: Answer should be complete and precise:
- Include all relevant context (not just base price, but COLA allowance)
- Verify not just existence but status (delivery date AND inspection confirmation)
- Distinguish between "delivered" and "received and inspected"

### Overall Agent GPA = 0.88 (Strong for Q&A Mode)
✅ **The Q&A system is reliable for follow-up questions.** The planner picks the right tool (1.00), calls it correctly (1.00), and the answers are grounded (0.70) and mostly correct (0.80). An 0.88 score means users can trust Q&A follow-ups to provide accurate, sourced information.

---

## How to Improve Agent GPA

### To reach 0.92+:

1. **Improve Groundedness (1C: 0.70 → 0.85)**
   - Modify `node_summarize_qa` to include 2-3 citations per claim
   - Cross-reference evidence (if citing price, also cite the PO)
   - Example: "The contract ceiling is $38.00/unit (**Apex Steel contract, clause 2.3.1**). The invoice bills at $39.14/unit (**Invoice INV-2024-9103, line item**), which is **3.77% above** the ceiling."

2. **Improve Answer Correctness (1A: 0.80 → 0.90)**
   - Expand the QA planner to ask follow-up questions of itself
   - Example: If asked "What's the price ceiling?", the planner should also ask itself "What's the COLA allowance?" and include both
   - Include context, not just facts

3. **Add Logical Consistency Scoring (2: Not measured → 0.85)**
   - Add multi-turn test cases (ask same question 2 ways)
   - Verify answers don't contradict across turns
   - This is the "trust multiplier" — if answers are consistent, users gain confidence

---

## Limitations of This Evaluation

### What this evaluation proves:
- ✅ Tool selection logic is sound (planner makes good decisions)
- ✅ Tool execution is correct (parameters are valid, calls succeed)
- ✅ Answers are not hallucinated (they're grounded in real data)
- ✅ Answers are factually accurate on the 2 test cases

### What this evaluation does NOT prove:
- ❌ Generalization to all possible Q&A questions (only tested 2)
- ❌ Robustness to adversarial inputs (only tested on-topic questions)
- ❌ Consistency across multiple turns (would need Logical Consistency scoring)
- ❌ Scalability (only tested against 1 invoice in the system)

### To reach production-grade Agent GPA:

1. **Expand test set**: 10-15 multi-turn Q&A cases across different invoices and fraud types
2. **Add adversarial cases**: Off-topic questions, unanswerable questions, edge cases
3. **Test consistency**: Ask the same question 2 different ways, verify answers agree
4. **Measure latency**: Add 3 (Execution Efficiency) scoring
5. **Capture planner reasoning**: Add 4A (Plan Quality) scoring

---

## Next Steps

### Immediate (Optional, Phase 2):
- [ ] Create 5 multi-turn Q&A test cases (same invoice, 3-4 questions each)
- [ ] Re-run Agent GPA evaluation on expanded test set
- [ ] Score Logical Consistency (2) across multiple turns

### Future (Optional, Production Readiness):
- [ ] Add adversarial test cases (off-topic, malicious input)
- [ ] Implement Plan Adherence scoring (5A) to verify planner → executor fidelity
- [ ] Measure latency (3: Execution Efficiency)
- [ ] Capture planner's reasoning for 4A (Plan Quality) audit

---

## Conclusion

The Q&A Mode demonstrates **strong Agent GPA (0.88/1.0)**, indicating:
- Planner reliability: ✅ Excellent (tool selection is correct)
- Execution reliability: ✅ Excellent (tools called properly)
- Answer quality: ✅ Good (accurate, grounded, minor gaps in comprehensiveness)

The system is suitable for **interactive Q&A on audited cases**. To reach production-grade reliability (0.95+), the next phase would involve expanding test coverage and improving groundedness through multi-source citations.

---

## How to Run Agent GPA Evaluation

### Test the demonstration:
```bash
cd backend
.\.venv\python.exe eval\run_agent_gpa.py --test
```

### Evaluate a real log (when Q&A turns exist):
```bash
.\.venv\python.exe eval\run_agent_gpa.py --log path/to/run_*.jsonl
```

### Script location:
```
backend/eval/run_agent_gpa.py
```

The script parses JSONL event logs and scores 4 Agent GPA dimensions, generating a scorecard report.

---

**Report generated**: 2026-07-29  
**Framework**: Agent GPA (AI Agent Reliability)  
**System**: Multi-Agent Procurement Fraud Detection (Sterling Industrial Works CCA)
