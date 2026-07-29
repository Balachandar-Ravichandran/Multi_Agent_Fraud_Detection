# Sample `/api/v1/chat` requests

Ready-to-run examples against Section 14.1's contract once `app/main.py` implements
the endpoint. Multipart form fields: `message`, `file` (optional), `session_id`.
Paths assume the server runs from `backend/` on `localhost:8000`.

## 1. Audit Mode — a flagged case (PRICE_INFLATION)

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -F "message=Can you audit this invoice?" \
  -F "file=@data/golden_dataset/invoices/INV-2024-0842.pdf;type=application/pdf" \
  -F "session_id=demo-session-1"
```

Expected per `golden_dataset_labels.json`: `fraud_type=PRICE_INFLATION`, contract ceiling
$38.00/unit vs. billed $42.50/unit (+11.8%), `expected_flag=true`.

## 2. Audit Mode — a clean case

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -F "message=Please audit this invoice." \
  -F "file=@data/golden_dataset/invoices/INV-2024-1001.pdf;type=application/pdf" \
  -F "session_id=demo-session-2"
```

Expected: `fraud_type=CLEAN`, all seven checks pass.

## 3. Q&A Mode — follow-up on an already-audited case

Send after request 1 completes, reusing the same `session_id` so Preconditions
resolves `mode=follow_up` against the stored case (Section 5, step 2) rather than
starting a new audit.

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -F "message=Which contract clause did the price ceiling come from?" \
  -F "session_id=demo-session-1"
```

Expected: an answer citing the Apex Steel contract's `## 2. Pricing Schedule` clause
(`data/contracts_policy/apex_steel_contract.md`), grounding gate passed.

## 4. Precondition failure — no file on a fresh session

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -F "message=Can you audit this invoice?" \
  -F "session_id=demo-session-3"
```

Expected: `mode=needs_upload` (Section 5, step 3 — `audit` with no attached invoice).
