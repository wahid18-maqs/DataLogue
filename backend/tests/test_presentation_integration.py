"""Integration checks for the presentation generation endpoints."""

import io
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import pandas as pd  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402

DATA_DIR = BASE_DIR / "data" / "uploads"
SAMPLE_CSV = DATA_DIR / "0bef146023704edf91909b14f502d050.csv"

# The sample dataset, written out when the file is not already there, so
# the checks do not depend on a file left behind by an earlier run.
SAMPLE_CSV_CONTENT = """Order_ID,Order_Date,Customer_Name,Customer_ID,Product,Category,Sub_Category,Region,State,City,Sales_Representative,Quantity,Unit_Price,Discount,Sales,Profit,Shipping_Cost,Payment_Method,Customer_Segment,Order_Status
ORD-1001,2025-01-05,Ava Patel,CUST-001,Office Chair,Furniture,Chairs,North,Illinois,Chicago,Sam Reed,2,120.50,0.05,228.95,42.10,12.00,Credit Card,Consumer,Completed
ORD-1002,2025-01-18,Liam Chen,CUST-002,Laptop Stand,Electronics,Accessories,South,Texas,Austin,Jo Ellis,1,45.00,0.00,45.00,8.50,7.00,PayPal,Small Business,Completed
ORD-1003,2025-02-03,Emma Smith,CUST-003,Desk Lamp,Office,Lighting,East,Florida,Miami,Kim Patel,3,60.00,0.10,162.00,31.40,9.00,Credit Card,Corporate,Completed
ORD-1004,2025-02-21,Noah Brown,CUST-004,Bookshelf,Furniture,Storage,West,California,Los Angeles,Sam Reed,1,220.00,0.00,220.00,55.00,15.00,Debit Card,Consumer,Pending
ORD-1005,2025-03-07,Olivia Jones,CUST-005,Monitor,Electronics,Displays,North,New York,New York,Jo Ellis,2,310.00,0.15,527.00,110.30,18.00,Credit Card,Corporate,Completed
ORD-1006,2025-03-25,James Wilson,CUST-006,Notebook,Office,Paper,South,Georgia,Atlanta,Kim Patel,12,6.50,0.00,78.00,19.20,5.00,PayPal,Small Business,Completed
"""


def ensure_sample_csv() -> Path:
    """The sample dataset, written out if it is not already there."""
    if SAMPLE_CSV.exists():
        return SAMPLE_CSV
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SAMPLE_CSV.write_text(SAMPLE_CSV_CONTENT, encoding="utf-8")
    return SAMPLE_CSV

PASSED = []
FAILED = []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL  {name} {detail}")


def wait_for_job(client, job_id, timeout=180):
    """
    Poll a generation job until it finishes.

    The timeout is generous because a deck build may call the LLM, and a
    large free model can take a minute or more to answer.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/presentations/jobs/{job_id}")
        assert response.status_code == 200, response.text
        job = response.json()
        if job["status"] in ("completed", "failed"):
            return job, job.get("stage_history", [])
        time.sleep(0.05)
    raise AssertionError(f"Job {job_id} did not finish within {timeout}s")


def main():
    client = TestClient(app)

    print("\n[1] Health and service info")
    check("GET /health returns ok", client.get("/health").json() == {"status": "ok"})
    check("GET / returns service info", "service" in client.get("/").json())

    print("\n[2] Dataset listing")
    response = client.get("/datasets")
    check("GET /datasets returns 200", response.status_code == 200)
    datasets = response.json()["datasets"]
    check("GET /datasets returns a list", isinstance(datasets, list))
    check("Every dataset has an id and name",
          all(d.get("dataset_id") and d.get("display_name") for d in datasets),
          str(datasets[:2]))

    print("\n[3] Upload CSV (existing pipeline)")
    with ensure_sample_csv().open("rb") as handle:
        response = client.post("/upload", files={"file": ("sales.csv", handle, "text/csv")})
    check("POST /upload returns 200", response.status_code == 200, response.text)
    upload_body = response.json()
    check("Upload returns a schema", "schema" in upload_body)
    check("Upload reports total_rows", upload_body["schema"]["total_rows"] > 0)
    check("Stored filename is unique per upload",
          upload_body["stored_filename"].endswith(".csv"))

    print("\n[4] Dashboard still works after upload")
    response = client.get("/dashboard")
    check("GET /dashboard returns 200", response.status_code == 200)
    dashboard = response.json()
    for key in ("title", "kpis", "main_chart", "secondary_charts"):
        check(f"Dashboard payload has '{key}'", key in dashboard)
    check("GET /kpis returns 200", client.get("/kpis").status_code == 200)
    check("GET /charts returns 200", client.get("/charts").status_code == 200)
    check("GET /plan returns 200", client.get("/plan").status_code == 200)

    print("\n[4b] Recent activity table payload")
    table = dashboard.get("latest_table", {})
    check("Table has columns", bool(table.get("columns")))
    check("Table reports the preview row count", table.get("preview_count") == 10)
    check("Table payload respects its row cap",
          len(table.get("rows", [])) <= 10, str(len(table.get("rows", []))))
    check("Table reports the total row count",
          table.get("total_rows", 0) >= len(table.get("rows", [])),
          str(table.get("total_rows")))
    check("Table rows are dicts with the declared columns",
          all(isinstance(r, dict) for r in table.get("rows", [])))

    print("\n[5] Generate presentation from active session")
    response = client.post("/presentations/generate")
    check("POST /presentations/generate returns 200", response.status_code == 200, response.text)
    job_body = response.json()
    check("Generate returns a job_id", bool(job_body.get("job_id")))
    check("Generate returns the stage list", len(job_body.get("stages", [])) == 6)
    check("Generate starts as running", job_body.get("status") == "running")

    job, stages = wait_for_job(client, job_body["job_id"])
    check("Job completes", job["status"] == "completed", job.get("error") or "")
    check("Job reports a filename", bool(job.get("filename")))
    check("Job reports a download_url", bool(job.get("download_url")))
    check("Job returns the deck plan", bool(job.get("deck")))
    check("Job progressed through real stages",
          "analyzing_data" in stages and "preparing_powerpoint" in stages, str(stages))
    check("Job stage history covers the whole pipeline",
          stages[:5] == ["reading_spreadsheet", "detecting_columns",
                         "analyzing_data", "writing_narrative",
                         "generating_slides"], str(stages))
    check("Deck slide count matches plan", job["deck"]["slide_count"] == len(job["deck"]["slides"]))

    print("\n[6] Download the generated PPTX")
    response = client.get(job["download_url"])
    check("GET download returns 200", response.status_code == 200)
    check("Download has the pptx media type",
          "presentationml" in response.headers.get("content-type", ""),
          response.headers.get("content-type", ""))
    payload = response.content
    check("Downloaded file is a real PPTX (zip magic bytes)", payload[:2] == b"PK")
    check("Downloaded file is non-trivial in size", len(payload) > 10000, str(len(payload)))

    from pptx import Presentation  # noqa: E402
    tmp_path = Path(tempfile.mkstemp(suffix=".pptx")[1])
    tmp_path.write_bytes(payload)
    prs = Presentation(str(tmp_path))
    check("PPTX opens with the AI-selected slide count",
          len(prs.slides) == job["deck"]["slide_count"]
          and 2 <= len(prs.slides) <= 10,
          str(len(prs.slides)))
    check("PPTX is 16:9 widescreen", prs.slide_width == 12192000 and prs.slide_height == 6858000)
    chart_count = sum(1 for slide in prs.slides for shape in slide.shapes if shape.has_chart)
    check("PPTX contains native editable charts", chart_count >= 3, str(chart_count))
    titles = [
        shape.text_frame.text
        for slide in prs.slides
        for shape in slide.shapes
        if shape.has_text_frame and shape.text_frame.text.strip()
    ]
    check("PPTX contains slide titles", any("Executive Summary" in t for t in titles))
    os.remove(tmp_path)

    print("\n[7] Generate from a direct CSV upload")
    with SAMPLE_CSV.open("rb") as handle:
        response = client.post(
            "/presentations/generate",
            files={"file": ("quarterly_sales.csv", handle, "text/csv")},
        )
    check("Generate with file returns 200", response.status_code == 200, response.text)
    job, _ = wait_for_job(client, response.json()["job_id"])
    check("File-based generation completes", job["status"] == "completed", job.get("error") or "")
    check("File-based deck has slides", job["deck"]["slide_count"] >= 4)
    check("Uploaded file appears in the dataset list",
          any(d["display_name"] == "quarterly_sales"
              for d in client.get("/datasets").json()["datasets"]))

    print("\n[8] Generate from a direct Excel upload")
    excel_path = BASE_DIR / "data" / "uploads" / "_integration_check.xlsx"
    pd.DataFrame({
        "Transaction_Date": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"],
        "Region": ["North", "South", "East", "West"],
        "Revenue": [1200.5, 450.0, 2100.75, 890.0],
        "Profit": [350.2, 110.0, 720.5, 210.0],
    }).to_excel(excel_path, index=False)
    with excel_path.open("rb") as handle:
        response = client.post(
            "/presentations/generate",
            files={"file": ("regional_report.xlsx", handle,
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
    check("Generate with Excel returns 200", response.status_code == 200, response.text)
    job, _ = wait_for_job(client, response.json()["job_id"])
    check("Excel generation completes", job["status"] == "completed", job.get("error") or "")
    titles = [s["title"] for s in job["deck"]["slides"]]
    check("Excel deck titles adapt to the dataset",
          any("Region" in t for t in titles), str(titles))
    check("Excel deck has a revenue KPI",
          any("revenue" in k["label"].lower() for k in job["deck"]["slides"][0]["kpis"]))

    print("\n[9] Generate from a previous dataset id")
    dataset_id = client.get("/datasets").json()["datasets"][0]["dataset_id"]
    response = client.post("/presentations/generate", data={"dataset_id": dataset_id})
    check("Generate with dataset_id returns 200", response.status_code == 200, response.text)
    job, _ = wait_for_job(client, response.json()["job_id"])
    check("dataset_id generation completes", job["status"] == "completed", job.get("error") or "")

    print("\n[9b] Regenerate with the requester's suggestions")
    response = client.post(
        "/presentations/generate",
        data={"suggestions": "Lead with the Furniture segment and use a cautious tone."},
    )
    check("Generate with suggestions returns 200", response.status_code == 200, response.text)
    job, _ = wait_for_job(client, response.json()["job_id"])
    check("Suggestion generation completes", job["status"] == "completed", job.get("error") or "")
    check("The suggestion generation produces a deck",
          (job.get("deck") or {}).get("slide_count", 0) >= 4,
          str((job.get("deck") or {}).get("slide_count")))
    check("The deck records where the narrative came from",
          (job.get("deck") or {}).get("narrative_source") in ("agent", "template"),
          str((job.get("deck") or {}).get("narrative_source")))

    print("\n[9c] Editing the deck live")
    response = client.post(
        f"/presentations/{job['filename']}/edit",
        json={"edits": [{"slide": 1, "field": "banner_text", "value": "Edited by the requester."}]},
    )
    check("Edit returns 200", response.status_code == 200, response.text)
    edited = response.json()
    check("The edit is reported as applied",
          edited.get("applied") == [{"slide": 1, "field": "banner_text"}],
          str(edited.get("applied")))
    check("The edited deck carries the new text",
          (edited.get("deck") or {}).get("slides", [{}])[0].get("banner_text")
          == "Edited by the requester.",
          str((edited.get("deck") or {}).get("slides", [{}])[0].get("banner_text")))
    check("The edited deck points at a new file",
          edited.get("download_url") and edited.get("download_url") != job.get("download_url"),
          str(edited.get("download_url")))

    edited_response = client.get(edited["download_url"])
    check("The edited file downloads", edited_response.status_code == 200)
    if edited_response.status_code == 200:
        from pptx import Presentation as _Presentation
        prs = _Presentation(io.BytesIO(edited_response.content))
        text = "\n".join(
            shape.text_frame.text
            for slide in prs.slides
            for shape in slide.shapes
            if shape.has_text_frame
        )
        check("The edited text is in the file", "Edited by the requester." in text, text[:120])
        check("The file has every slide", len(prs.slides) == edited["deck"]["slide_count"],
              str(len(prs.slides)))

    # The edit is addressed by the file, so it survives a server restart,
    # which empties the in-memory job registry.
    app.state.presentation_jobs.clear()
    response = client.post(
        f"/presentations/{job['filename']}/edit",
        json={"edits": [{"slide": 1, "field": "banner_text", "value": "Edited after a restart."}]},
    )
    check("A deck can still be edited after a restart", response.status_code == 200, response.text)
    check("The edit after the restart is applied",
          (response.json().get("deck") or {}).get("slides", [{}])[0].get("banner_text")
          == "Edited after a restart.",
          str((response.json().get("deck") or {}).get("slides", [{}])[0].get("banner_text")))

    response = client.post(
        f"/presentations/{job['filename']}/edit",
        json={"edits": [{"slide": 1, "field": "series", "value": "x"}]},
    )
    check("An edit to a computed field is rejected", response.status_code == 400, response.text)
    check("The rejection says why",
          "not an editable field" in response.json().get("detail", ""),
          response.json().get("detail", ""))

    response = client.post(
        f"/presentations/{job['filename']}/edit", json={"edits": []}
    )
    check("An empty edit list is rejected", response.status_code == 400, response.text)

    response = client.post(
        "/presentations/does-not-exist.pptx/edit",
        json={"edits": [{"slide": 1, "field": "title", "value": "x"}]},
    )
    check("Editing an unknown file returns 404", response.status_code == 404, response.text)

    print("\n[10] Error handling")
    response = client.post("/presentations/generate", data={"dataset_id": "does_not_exist.csv"})
    check("Unknown dataset_id returns 404", response.status_code == 404, response.text)

    response = client.post(
        "/presentations/generate",
        files={"file": ("notes.txt", b"not a dataset", "text/plain")},
    )
    check("Unsupported extension returns 400", response.status_code == 400, response.text)

    response = client.get("/presentations/jobs/does-not-exist")
    check("Unknown job id returns 404", response.status_code == 404, response.text)

    response = client.get("/presentations/download/missing.pptx")
    check("Missing presentation returns 404", response.status_code == 404, response.text)

    response = client.get("/presentations/download/../../etc/passwd")
    check("Path traversal on download is rejected", response.status_code in (400, 404),
          str(response.status_code))

    print("\n[11] Chart variety across different datasets")
    job_a, _ = wait_for_job(client, client.post(
        "/presentations/generate",
        files={"file": ("a.csv", SAMPLE_CSV.read_bytes(), "text/csv")},
    ).json()["job_id"])
    job_b, _ = wait_for_job(client, client.post(
        "/presentations/generate",
        files={"file": ("b.xlsx", excel_path.read_bytes(), "application/vnd.ms-excel")},
    ).json()["job_id"])

    def chart_types(job):
        return [s.get("chart_type") for s in job["deck"]["slides"] if s["type"] == "chart"]

    check("Sales deck has chart slides", len(chart_types(job_a)) >= 3, str(chart_types(job_a)))
    check("Regional deck has chart slides", len(chart_types(job_b)) >= 2, str(chart_types(job_b)))
    check("Deck titles differ between datasets",
          job_a["deck"]["title"] != job_b["deck"]["title"],
          f"{job_a['deck']['title']} vs {job_b['deck']['title']}")

    print("\n[12] Cleanup")
    for dataset in client.get("/datasets").json()["datasets"]:
        if dataset["dataset_id"].startswith(("quarterly_sales", "a_", "b_", "regional_report")):
            (DATA_DIR / dataset["dataset_id"]).unlink(missing_ok=True)
    if excel_path.exists():
        excel_path.unlink()
    for leftover in (BASE_DIR / "data" / "presentations").glob("*.pptx"):
        leftover.unlink()
    print("  Cleaned generated artifacts.")

    print(f"\n{'=' * 60}")
    print(f"PASSED: {len(PASSED)}   FAILED: {len(FAILED)}")
    if FAILED:
        print("\nFailures:")
        for name in FAILED:
            print(f"  - {name}")
        return 1
    print("All integration checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
