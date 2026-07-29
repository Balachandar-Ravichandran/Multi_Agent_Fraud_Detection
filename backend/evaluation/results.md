# Golden Dataset Evaluation Results

Full sequential run over all 20 golden-set invoices, live (real `ANTHROPIC_API_KEY`, real SQLite, real Chroma retrieval, real PDF extraction). Produced by `eval/run_golden_set.py`; raw per-invoice data in `results.json`; full event trace in `logs/run_golden_set_eval.jsonl` (1,533 events).

## Headline

**20/20 invoices classified correctly.** Per Section 19, this single number is not the story — 7 of 20 are `CLEAN`, so it's not evaluated as a blended accuracy score. What matters is the breakdown below.

## Per-fraud-type precision / recall

| Fraud type | TP | FP | FN | Precision | Recall |
|---|---|---|---|---|---|
| CLEAN | 7 | 0 | 0 | 1.00 | 1.00 |
| PRICE_INFLATION | 2 | 0 | 0 | 1.00 | 1.00 |
| QUANTITY_MISMATCH | 2 | 0 | 0 | 1.00 | 1.00 |
| PHANTOM_VENDOR | 1 | 0 | 0 | 1.00 | 1.00 |
| NON_DELIVERY | 2 | 0 | 0 | 1.00 | 1.00 |
| ALTERED_BANK_DETAILS | 2 | 0 | 0 | 1.00 | 1.00 |
| DUPLICATE_BILLING | 1 | 0 | 0 | 1.00 | 1.00 |
| SPLIT_INVOICING | 2 | 0 | 0 | 1.00 | 1.00 |
| PO_EXCEEDS_CONTRACT_CEILING | 1 | 0 | 0 | 1.00 | 1.00 |

The 9x9 confusion matrix is diagonal (every off-diagonal cell is 0) — see `results.json`'s `confusion_matrix` for the raw table. Per Section 18, `PHANTOM_VENDOR`, `DUPLICATE_BILLING`, and `PO_EXCEEDS_CONTRACT_CEILING` each have exactly one example, so their recall is binary by construction (100% or 0%) — this run landed on 100% for all three, but that's one data point each, not a statistically robust estimate.

## Citation-validity rate: 100% (27/27)

Every citation across all 20 reports traces to a real record. This included verifying negative evidence correctly (e.g. `PHANTOM_VENDOR`'s "no vendor_master record found" citations were checked by confirming that absence, not by checking for existence) — see the note in `eval/run_golden_set.py::verify_citation()` for why a naive existence check would have wrongly flagged genuine evidence.

## Check 7 (RAG) context precision / recall: 1.00 / 1.00

Measured exactly, not estimated, per Section 19 — the corpus is 4 documents / 29 chunks, small enough to check the *correct* retrieval for every invoice by hand-verifiable rule (retrieved contract matches the invoice's own vendor, from the Pricing Schedule section). `INV-2024-4001` (the `PHANTOM_VENDOR` case) is excluded from this average, not scored as a miss — its vendor doesn't exist in the 3-vendor contract corpus, so there is no correct clause to retrieve in the first place.

## What this run does and doesn't prove

Confirms the system's *logic* handles all 9 label classes correctly on this dataset, including the two deliberately adversarial pairs (8001/8002 for split-invoicing vs. the general partial-shipment allowance; 9001 for the PRICE_INFLATION/PO_EXCEEDS_CONTRACT_CEILING boundary). It does **not** establish a real-world false-positive rate at Sterling's actual volume (500 invoices/month) — 20 invoices validate decision-boundary correctness, not production-scale statistics. Section 19 keeps these two claims separate; this writeup does too.

## Failure cases found

None in this run — all 20 invoices matched their expected label. No failure-case writeup is needed because there was nothing to trace back through the Event Catalogue this time.
