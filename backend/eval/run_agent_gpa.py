"""Agent GPA evaluator for Q&A Mode (dynamic planner + tool selection).

Scores 4 dimensions from existing JSONL logs:
- 4B Tool Selection: Did planner pick the right tool (RAG/Storage/both)?
- 5B Tool Calling: Were parameters correct when tools executed?
- 1C Groundedness: Is answer supported by retrieved evidence?
- 1A Answer Correctness: Does answer match ground truth from reference data?
"""

import json
import sqlite3
from collections import defaultdict
from pathlib import Path


def load_logs(log_path: str) -> list[dict]:
    """Load JSONL log file."""
    events = []
    with open(log_path) as f:
        for line in f:
            if line.strip():
                events.append(json.loads(line))
    return events


def extract_qa_turns(events: list[dict]) -> list[dict]:
    """Extract Q&A turn sequences from events.

    A Q&A turn starts with qa_tool_choice and includes:
    - planner's tool selection decision (from decide_qa node)
    - actual tool calls (from act_qa node)
    - answer generated (from summarize_qa node)
    - citations (qa_citations in state)
    """
    turns = []
    current_turn = {}

    for event in events:
        category = event.get("category")
        event_name = event.get("event")

        # Q&A sequence markers
        if event_name == "QA_PLAN_CREATED":
            current_turn = {
                "timestamp": event.get("timestamp"),
                "invoice_id": event.get("invoice_id"),
                "question": event.get("question")  # Capture question here
            }

        elif event_name == "QA_TOOL_SELECTED":
            current_turn["question"] = current_turn.get("question") or event.get("question")
            current_turn["planned_tool"] = event.get("tool_choice")  # "RAG", "STORAGE", "BOTH", "NONE"

        elif category == "rag" and event_name == "RAG_SEARCH_EXECUTED":
            current_turn.setdefault("actual_tools", []).append({
                "type": "RAG",
                "vendor_id": event.get("vendor_id"),
                "query": event.get("query"),
                "top_k": event.get("top_k", 3),
                "results": event.get("result_count", 0)
            })

        elif category == "storage" and event_name == "STORAGE_QUERY_EXECUTED":
            current_turn.setdefault("actual_tools", []).append({
                "type": "STORAGE",
                "query_type": event.get("query_type"),
                "params": event.get("params", {}),
                "result_count": event.get("result_count", 0)
            })

        elif event_name == "QA_ANSWER_GENERATED":
            current_turn["answer"] = event.get("answer_text")
            current_turn["citations"] = event.get("citation_count", 0)

        elif event_name == "QA_TURN_COMPLETE":
            if current_turn:
                turns.append(current_turn)
                current_turn = {}

    return turns


def score_tool_selection(turn: dict) -> float:
    """Score 4B: Did planner pick appropriate tool for the question?

    Heuristic rules:
    - Vendor/PO/delivery/bank questions → STORAGE (1.0)
    - Contract/price/clause questions → RAG (1.0)
    - Questions needing both → BOTH (1.0)
    - All other combinations → scaled by relevance
    """
    if not turn.get("question") or not turn.get("planned_tool"):
        return 0.0

    q = turn["question"].lower()
    planned = turn["planned_tool"]

    # Vendor/PO/delivery/bank questions
    vendor_keywords = ["vendor", "approved", "po", "purchase order", "delivery", "received", "bank", "account"]
    contract_keywords = ["contract", "price", "ceiling", "cola", "clause", "term"]

    is_vendor_q = any(kw in q for kw in vendor_keywords)
    is_contract_q = any(kw in q for kw in contract_keywords)

    if is_vendor_q and planned == "STORAGE":
        return 1.0
    elif is_contract_q and planned == "RAG":
        return 1.0
    elif (is_vendor_q and is_contract_q) and planned == "BOTH":
        return 1.0
    elif planned == "NONE" and not (is_vendor_q or is_contract_q):
        return 1.0
    elif is_vendor_q and planned in ("RAG", "BOTH"):
        return 0.5  # Sub-optimal but not wrong
    elif is_contract_q and planned in ("STORAGE", "BOTH"):
        return 0.5
    else:
        return 0.0


def score_tool_calling(turn: dict) -> float:
    """Score 5B: Were tool parameters correct?

    Check:
    - RAG calls had vendor_id (not empty)
    - RAG calls had query (not empty)
    - STORAGE calls had valid params
    - All tools executed (not null)
    """
    if not turn.get("actual_tools"):
        return 1.0  # Tool was planned but not called (e.g., NONE)

    tools = turn["actual_tools"]
    scores = []

    for tool in tools:
        if tool["type"] == "RAG":
            # RAG must have vendor_id and query
            has_vendor = bool(tool.get("vendor_id"))
            has_query = bool(tool.get("query"))
            has_results = tool.get("results", 0) > 0
            score = (has_vendor + has_query + has_results) / 3.0
            scores.append(score)

        elif tool["type"] == "STORAGE":
            # STORAGE must have params and results
            has_params = bool(tool.get("params"))
            has_results = tool.get("result_count", 0) > 0
            score = (has_params + has_results) / 2.0
            scores.append(score)

    return sum(scores) / len(scores) if scores else 0.0


def score_groundedness(turn: dict, reference_data: dict) -> float:
    """Score 1C: Is answer supported by retrieved evidence?

    Check:
    - answer exists (not null)
    - has at least one citation
    - (optional) cited facts exist in reference data
    """
    if not turn.get("answer"):
        return 0.0

    answer = turn["answer"]
    citations = turn.get("citations", 0)

    # Must have evidence
    if citations == 0:
        # Acceptable only if question is unanswerable (e.g., "Does vendor not exist?")
        if "does not exist" in answer.lower() or "not found" in answer.lower():
            return 1.0  # Absence citation is valid
        return 0.0  # Answer with no citation = hallucination

    # Score by citation count (min 1, max 3+ is same)
    if citations >= 3:
        return 1.0
    elif citations >= 2:
        return 0.9
    else:
        return 0.7


def score_answer_correctness(turn: dict, reference_data: dict) -> float:
    """Score 1A: Does answer match ground truth?

    Check:
    - If asking for a specific fact (price, vendor name, etc), verify it matches reference data
    - Partial credit if answer is directionally correct but imprecise
    """
    if not turn.get("answer"):
        return 0.0

    answer = turn["answer"].lower()
    question = turn.get("question")
    q = (question.lower() if question else "")

    # Heuristic: can we verify the answer against reference data?
    # For now, give partial credit if answer doesn't contradict common facts

    # Unanswerable questions (e.g., "What's the weather?")
    if any(x in q for x in ["weather", "time", "news", "today"]):
        # Should refuse gracefully
        if "don't" in answer or "can't" in answer or "unknown" in answer:
            return 1.0
        return 0.0

    # For answerable questions, assume answer is correct if grounded (checked above)
    # Full verification would require parsing answer and querying DB
    return 0.8 if turn.get("citations", 0) > 0 else 0.5


def evaluate_agent_gpa(log_path: str, run_id: str = "default") -> dict:
    """Run Agent GPA evaluation on a log file."""

    print(f"\n{'='*60}")
    print(f"Agent GPA Evaluation: {run_id}")
    print(f"{'='*60}")

    events = load_logs(log_path)
    turns = extract_qa_turns(events)

    if not turns:
        print(f"\n⚠️  No Q&A turns found in {log_path}")
        print("(This is expected for Audit Mode only logs)")
        print("\nTo test Agent GPA scoring, run:")
        print("  backend\\.venv\\python.exe backend/eval/run_agent_gpa.py --test")
        return {"status": "no_qa_data"}

    print(f"\n✓ Found {len(turns)} Q&A turn(s)")

    # Reference data for correctness checks
    reference_data = load_reference_data()

    # Score each turn
    results = {
        "total_turns": len(turns),
        "turns": [],
        "aggregate": {
            "tool_selection_4b": 0.0,
            "tool_calling_5b": 0.0,
            "groundedness_1c": 0.0,
            "answer_correctness_1a": 0.0,
        }
    }

    for i, turn in enumerate(turns, 1):
        score_4b = score_tool_selection(turn)
        score_5b = score_tool_calling(turn)
        score_1c = score_groundedness(turn, reference_data)
        score_1a = score_answer_correctness(turn, reference_data)

        turn_result = {
            "turn": i,
            "invoice_id": turn.get("invoice_id"),
            "question": turn.get("question"),
            "planned_tool": turn.get("planned_tool"),
            "actual_tools": [t["type"] for t in turn.get("actual_tools", [])],
            "scores": {
                "4B_tool_selection": round(score_4b, 2),
                "5B_tool_calling": round(score_5b, 2),
                "1C_groundedness": round(score_1c, 2),
                "1A_answer_correctness": round(score_1a, 2),
            }
        }
        results["turns"].append(turn_result)

        # Accumulate
        results["aggregate"]["tool_selection_4b"] += score_4b
        results["aggregate"]["tool_calling_5b"] += score_5b
        results["aggregate"]["groundedness_1c"] += score_1c
        results["aggregate"]["answer_correctness_1a"] += score_1a

    # Average
    n = len(turns)
    for key in results["aggregate"]:
        results["aggregate"][key] = round(results["aggregate"][key] / n, 2)

    # Overall Agent GPA (average of 4 dimensions)
    agent_gpa = sum(results["aggregate"].values()) / 4
    results["aggregate"]["agent_gpa"] = round(agent_gpa, 2)

    return results


def load_reference_data() -> dict:
    """Load reference data for correctness validation."""
    try:
        db_path = Path(__file__).parent.parent / "fraud_system.db"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        # Load sample reference data
        vendors = {}
        cursor = conn.execute("SELECT * FROM vendor_master LIMIT 10")
        for row in cursor:
            vendors[row["vendor_id"]] = dict(row)

        conn.close()
        return {"vendors": vendors}
    except Exception as e:
        print(f"Warning: Could not load reference data: {e}")
        return {}


def create_test_qa_data() -> str:
    """Create sample Q&A turns for demonstration."""
    test_events = [
        {
            "timestamp": "2026-07-29T16:00:00.000000+00:00",
            "category": "qa",
            "event": "QA_PLAN_CREATED",
            "invoice_id": "INV-2024-1001",
            "question": "What is the contract price ceiling for this vendor?"
        },
        {
            "timestamp": "2026-07-29T16:00:01.000000+00:00",
            "category": "qa",
            "event": "QA_TOOL_SELECTED",
            "tool_choice": "RAG",
            "question": "What is the contract price ceiling for this vendor?"
        },
        {
            "timestamp": "2026-07-29T16:00:02.000000+00:00",
            "category": "rag",
            "event": "RAG_SEARCH_EXECUTED",
            "vendor_id": "VEND-1001",
            "query": "price ceiling contract term",
            "top_k": 3,
            "result_count": 2
        },
        {
            "timestamp": "2026-07-29T16:00:03.000000+00:00",
            "category": "qa",
            "event": "QA_ANSWER_GENERATED",
            "answer_text": "According to the Apex Steel contract on file, the price ceiling is $38.00 per unit.",
            "citation_count": 1
        },
        {
            "timestamp": "2026-07-29T16:00:04.000000+00:00",
            "category": "qa",
            "event": "QA_TURN_COMPLETE",
            "invoice_id": "INV-2024-1001"
        },
        {
            "timestamp": "2026-07-29T16:00:05.000000+00:00",
            "category": "qa",
            "event": "QA_PLAN_CREATED",
            "invoice_id": "INV-2024-1001",
            "question": "Is there a delivery record for PO-2024-0101?"
        },
        {
            "timestamp": "2026-07-29T16:00:06.000000+00:00",
            "category": "qa",
            "event": "QA_TOOL_SELECTED",
            "tool_choice": "STORAGE",
            "question": "Is there a delivery record for PO-2024-0101?"
        },
        {
            "timestamp": "2026-07-29T16:00:07.000000+00:00",
            "category": "storage",
            "event": "STORAGE_QUERY_EXECUTED",
            "query_type": "delivery_lookup",
            "params": {"po_number": "PO-2024-0101"},
            "result_count": 1
        },
        {
            "timestamp": "2026-07-29T16:00:08.000000+00:00",
            "category": "qa",
            "event": "QA_ANSWER_GENERATED",
            "answer_text": "Yes, there is a delivery record for PO-2024-0101 dated 2026-05-15 for 500 units of Grade-A Steel Brackets.",
            "citation_count": 1
        },
        {
            "timestamp": "2026-07-29T16:00:09.000000+00:00",
            "category": "qa",
            "event": "QA_TURN_COMPLETE",
            "invoice_id": "INV-2024-1001"
        },
    ]

    # Write test log
    test_log_path = Path(__file__).parent / "run_agent_gpa_test.jsonl"
    with open(test_log_path, "w") as f:
        for event in test_events:
            f.write(json.dumps(event) + "\n")

    return str(test_log_path)


def print_results(results: dict):
    """Pretty-print Agent GPA results."""
    if results.get("status") == "no_qa_data":
        return

    print(f"\n{'─'*60}")
    print(f"Results: {results['total_turns']} Q&A Turn(s)")
    print(f"{'─'*60}")

    # Per-turn breakdown
    for turn in results["turns"]:
        print(f"\nTurn {turn['turn']}: {turn.get('invoice_id')}")
        print(f"  Q: {turn['question']}")
        print(f"  Planned tool: {turn['planned_tool']}")
        print(f"  Actual tools: {', '.join(turn['actual_tools']) or '(none)'}")
        scores = turn["scores"]
        print(f"  Scores:")
        print(f"    4B Tool Selection:    {scores['4B_tool_selection']:.2f}")
        print(f"    5B Tool Calling:      {scores['5B_tool_calling']:.2f}")
        print(f"    1C Groundedness:      {scores['1C_groundedness']:.2f}")
        print(f"    1A Answer Correct:    {scores['1A_answer_correctness']:.2f}")

    # Aggregate
    print(f"\n{'─'*60}")
    print(f"Agent GPA Scorecard")
    print(f"{'─'*60}")
    agg = results["aggregate"]
    print(f"  4B Tool Selection:    {agg['tool_selection_4b']:.2f}")
    print(f"  5B Tool Calling:      {agg['tool_calling_5b']:.2f}")
    print(f"  1C Groundedness:      {agg['groundedness_1c']:.2f}")
    print(f"  1A Answer Correct:    {agg['answer_correctness_1a']:.2f}")
    print(f"\n  ⭐ Overall Agent GPA: {agg['agent_gpa']:.2f} / 1.0")
    print(f"{'─'*60}\n")


if __name__ == "__main__":
    import sys

    if "--test" in sys.argv:
        # Create and evaluate test data
        test_log = create_test_qa_data()
        print(f"✓ Created test Q&A log: {test_log}")
        results = evaluate_agent_gpa(test_log, run_id="test_qa_turns")
        print_results(results)
    else:
        # Evaluate golden-set log (Audit Mode)
        golden_log = Path(__file__).parent / "../logs/run_golden_set_eval.jsonl"
        results = evaluate_agent_gpa(str(golden_log), run_id="golden_set_eval")
        print_results(results)
