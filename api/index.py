from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import parse_qs
import mimetypes

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from api.borrower import lookup_borrower

STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/analysis": ("analysis.html", "text/html; charset=utf-8"),
    "/analysis.html": ("analysis.html", "text/html; charset=utf-8"),
    "/credit-risk-review": ("analysis.html", "text/html; charset=utf-8"),
    "/credit-risk-review.html": ("analysis.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
    "/data/summary.json": ("data/summary.json", "application/json; charset=utf-8"),
}

def _serve_file(start_response, file_path: Path, content_type: str | None = None):
    body = file_path.read_bytes()
    if content_type is None:
        guessed = mimetypes.guess_type(str(file_path))[0]
        content_type = guessed or "application/octet-stream"
    start_response(
        "200 OK",
        [
            ("Content-Type", content_type),
            ("Content-Length", str(len(body))),
        ],
    )
    return [body]


def _json_response(start_response, status: str, payload: dict[str, object]):
    body = json.dumps(payload).encode("utf-8")
    start_response(
        status,
        [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(body))),
        ],
    )
    return [body]

def _borrower_html(payload: dict[str, object], borrower_id: int) -> bytes:
    reasons_html = "".join(
        f"""
        <div class="reason-item">
          <span>{reason['feature']}</span>
          <strong>{reason['contribution'] if reason['contribution'] is not None else '—'}</strong>
          <span>Raw: {reason['raw_value'] if reason['raw_value'] is not None else '—'}</span>
          <span>Bin: {reason['matched_bin'] if reason['matched_bin'] is not None else '—'}</span>
          <span>Points: {reason['points'] if reason['points'] is not None else '—'}</span>
          <span>Bad Rate: {reason['bad_rate'] if reason['bad_rate'] is not None else '—'}</span>
        </div>
        """
        for reason in payload["reasons"]
    )
    detail_rows = [
        ("Contract Type", payload["profile"]["contract_type"]),
        ("Income Type", payload["profile"]["income_type"]),
        ("Family Status", payload["profile"]["family_status"]),
        ("Housing", payload["profile"]["housing_type"]),
        ("Income", payload["profile"]["income_total"]),
        ("Credit", payload["profile"]["credit_amount"]),
        ("Annuity", payload["profile"]["annuity_amount"]),
        ("Bureau Rows", payload["activity"]["bureau_rows"]),
        ("Previous Applications", payload["activity"]["previous_rows"]),
        ("Late Rate", payload["activity"]["installment_late_rate"]),
        ("Scorecard Probability", payload["scorecard"]["probability"]),
        ("Leaderboard Blend", payload["leaderboard"]["blend"]),
    ]
    details_html = "".join(
        f"<div class='detail-item'><span>{label}</span><strong>{value if value is not None else '—'}</strong></div>"
        for label, value in detail_rows
    )
    html = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Borrower {borrower_id}</title>
    <link rel="stylesheet" href="/styles.css" />
  </head>
  <body>
    <main class="site-main" style="padding-top:32px;">
      <section class="borrower-shell">
        <div class="borrower-hero">
          <div class="borrower-hero-copy">
            <span class="panel-tag">{payload['split'].title()} Borrower</span>
            <span class="owner-line">Portfolio by Bramastya Zaki</span>
            <h3>SK_ID_CURR {borrower_id}</h3>
            <p>A borrower-level trace connecting application context, credit history, explainable score contributions, and final model outputs.</p>
            <div class="hero-actions">
              <a class="ghost-button" href="/analysis">Back to analysis</a>
            </div>
          </div>
          <div class="borrower-scoreboard">
            <div class="score-chip"><span>Observed Target</span><strong>{payload['target'] if payload['target'] is not None else 'Test'}</strong></div>
            <div class="score-chip"><span>Scorecard Probability</span><strong>{payload['scorecard']['probability'] if payload['scorecard']['probability'] is not None else '—'}</strong></div>
            <div class="score-chip"><span>Leaderboard Blend</span><strong>{payload['leaderboard']['blend'] if payload['leaderboard']['blend'] is not None else '—'}</strong></div>
          </div>
        </div>
        <div class="borrower-grid">
          <article class="panel panel-span">
            <span class="panel-tag">Profile and Activity</span>
            <div class="detail-grid">{details_html}</div>
          </article>
          <article class="panel panel-span">
            <span class="panel-tag">Reason Codes</span>
            <div class="reason-list">{reasons_html}</div>
          </article>
        </div>
      </section>
    </main>
  </body>
</html>"""
    return html.encode("utf-8")


def _borrower_message_page(title: str, message: str, status: str = "400 Bad Request") -> tuple[str, bytes]:
    body = f"""<!doctype html><html lang="en"><head><meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1.0" /><title>{title}</title><link rel="stylesheet" href="/styles.css" /></head><body><main class="site-main" style="padding-top:32px;"><div class="empty-state"><p>{message}</p><p><a class="ghost-button" href="/">Back to project</a></p></div></main></body></html>""".encode("utf-8")
    return status, body


def app(environ, start_response):
    path = environ.get("PATH_INFO", "")
    method = environ.get("REQUEST_METHOD", "GET").upper()
    if path in STATIC_FILES:
        relative_path, content_type = STATIC_FILES[path]
        return _serve_file(start_response, ROOT / relative_path, content_type)

    if path.startswith("/data/plots/"):
        file_path = ROOT / path.lstrip("/")
        if file_path.exists() and file_path.is_file():
            return _serve_file(start_response, file_path)

    if path.startswith("/borrowers/"):
        slug = path.removeprefix("/borrowers/").strip("/")
        if slug:
            file_path = ROOT / "borrowers" / f"{slug.removesuffix('.html')}.html"
            if file_path.exists() and file_path.is_file():
                return _serve_file(start_response, file_path, "text/html; charset=utf-8")
            try:
                borrower_id = int(slug.removesuffix(".html"))
            except ValueError:
                borrower_id = None
            if borrower_id is not None:
                payload = lookup_borrower(borrower_id)
                if payload is not None:
                    body = _borrower_html(payload, borrower_id)
                    start_response(
                        "200 OK",
                        [
                            ("Content-Type", "text/html; charset=utf-8"),
                            ("Content-Length", str(len(body))),
                        ],
                    )
                    return [body]
                body = f"""<!doctype html><html lang="en"><head><meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1.0" /><title>Borrower not found</title><link rel="stylesheet" href="/styles.css" /></head><body><main class="site-main" style="padding-top:32px;"><div class="empty-state"><p>Borrower {borrower_id} was not found in the prepared walkthrough bundle.</p><p><a class="ghost-button" href="/">Back to project</a></p></div></main></body></html>""".encode("utf-8")
                start_response(
                    "404 Not Found",
                    [
                        ("Content-Type", "text/html; charset=utf-8"),
                        ("Content-Length", str(len(body))),
                    ],
                )
                return [body]

    if path not in {"/api/borrower", "/borrower"}:
        return _json_response(start_response, "404 Not Found", {"error": "Not found"})

    query = parse_qs(environ.get("QUERY_STRING", ""))
    raw_id = query.get("id", [None])[0]
    if raw_id is None:
        if path == "/borrower":
            status, body = _borrower_message_page("Borrower Trace", "Enter a borrower ID to open a trace page. Try 182619 or 100002.")
            start_response(
                status,
                [
                    ("Content-Type", "text/html; charset=utf-8"),
                    ("Content-Length", str(len(body))),
                ],
            )
            return [body]
        body = json.dumps({"error": "Missing query parameter: id"}).encode("utf-8")
        start_response(
            "400 Bad Request",
            [
                ("Content-Type", "application/json; charset=utf-8"),
                ("Content-Length", str(len(body))),
            ],
        )
        return [body]

    try:
        borrower_id = int(raw_id)
    except ValueError:
        if path == "/borrower":
            status, body = _borrower_message_page("Borrower Trace", "Borrower IDs must be numeric. Try 182619 or 100002.")
            start_response(
                status,
                [
                    ("Content-Type", "text/html; charset=utf-8"),
                    ("Content-Length", str(len(body))),
                ],
            )
            return [body]
        body = json.dumps({"error": "Borrower id must be an integer"}).encode("utf-8")
        start_response(
            "400 Bad Request",
            [
                ("Content-Type", "application/json; charset=utf-8"),
                ("Content-Length", str(len(body))),
            ],
        )
        return [body]

    payload = lookup_borrower(borrower_id)
    if path == "/borrower":
        if payload is None:
            body = f"""<!doctype html><html lang="en"><head><meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1.0" /><title>Borrower not found</title><link rel="stylesheet" href="/styles.css" /></head><body><main class="site-main" style="padding-top:32px;"><div class="empty-state"><p>Borrower {borrower_id} was not found in the prepared walkthrough bundle.</p><p><a class="ghost-button" href="/">Back to project</a></p></div></main></body></html>""".encode("utf-8")
            start_response(
                "404 Not Found",
                [
                    ("Content-Type", "text/html; charset=utf-8"),
                    ("Content-Length", str(len(body))),
                ],
            )
            return [body]
        body = _borrower_html(payload, borrower_id)
        start_response(
            "200 OK",
            [
                ("Content-Type", "text/html; charset=utf-8"),
                ("Content-Length", str(len(body))),
            ],
        )
        return [body]

    status = "200 OK" if payload is not None else "404 Not Found"
    body = json.dumps(payload if payload is not None else {"error": f"Borrower {borrower_id} not found"}).encode("utf-8")
    start_response(
        status,
        [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(body))),
        ],
    )
    return [body]
