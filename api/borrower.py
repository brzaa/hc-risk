from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler
from pathlib import Path
import sqlite3
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[1]
PACKAGED_LOOKUP_DB = Path(__file__).resolve().with_name("web_lookup.db")
LOOKUP_DB = PACKAGED_LOOKUP_DB if PACKAGED_LOOKUP_DB.exists() else ROOT / "data" / "web_lookup.db"


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, object]) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _decode_record(raw: sqlite3.Row) -> dict[str, object]:
    return {
        "id": raw["id"],
        "split": raw["split"],
        "target": raw["target"],
        "profile": {
            "contract_type": raw["contract_type"],
            "income_type": raw["income_type"],
            "family_status": raw["family_status"],
            "housing_type": raw["housing_type"],
            "income_total": raw["income_total"],
            "credit_amount": raw["credit_amount"],
            "annuity_amount": raw["annuity_amount"],
            "ext_source_2": raw["ext_source_2"],
        },
        "activity": {
            "bureau_rows": raw["bureau_rows"],
            "active_loans": raw["active_loans"],
            "previous_rows": raw["previous_rows"],
            "previous_approved": raw["previous_approved"],
            "previous_refused": raw["previous_refused"],
            "installment_rows": raw["installment_rows"],
            "installment_late_rate": raw["installment_late_rate"],
            "installment_max_dpd": raw["installment_max_dpd"],
            "bureau_total_debt": raw["bureau_total_debt"],
            "bureau_total_overdue": raw["bureau_total_overdue"],
        },
        "scorecard": {
            "probability": raw["scorecard_probability"],
            "score": raw["scorecard_score"],
        },
        "leaderboard": {
            "blend": raw["leaderboard_blend"],
            "stack_logit": raw["stack_logit"],
        },
        "reasons": [
            {
                "feature": raw[f"reason{idx}_feature"],
                "contribution": raw[f"reason{idx}_contribution"],
                "raw_value": raw[f"reason{idx}_raw_value"],
                "matched_bin": raw[f"reason{idx}_matched_bin"],
                "points": raw[f"reason{idx}_points"],
                "bad_rate": raw[f"reason{idx}_bad_rate"],
            }
            for idx in (1, 2, 3)
            if raw[f"reason{idx}_feature"] is not None
        ],
    }


def lookup_borrower(borrower_id: int) -> dict[str, object] | None:
    if not LOOKUP_DB.exists():
        return None
    conn = sqlite3.connect(LOOKUP_DB)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM borrowers WHERE id = ?", (borrower_id,)).fetchone()
    conn.close()
    return None if row is None else _decode_record(row)


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        query = parse_qs(urlparse(self.path).query)
        raw_id = query.get("id", [None])[0]
        if raw_id is None:
            _json_response(self, 400, {"error": "Missing query parameter: id"})
            return
        try:
            borrower_id = int(raw_id)
        except ValueError:
            _json_response(self, 400, {"error": "Borrower id must be an integer"})
            return

        payload = lookup_borrower(borrower_id)
        if payload is None:
            _json_response(self, 404, {"error": f"Borrower {borrower_id} not found"})
            return
        _json_response(self, 200, payload)
