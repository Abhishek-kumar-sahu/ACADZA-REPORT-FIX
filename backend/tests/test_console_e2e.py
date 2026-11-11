"""Browser-level tests of the faculty console (Phase 6): real uvicorn + real DB + Microsoft Edge (headless)
via Playwright. Skipped (with the reason shown) if Playwright or Edge is unavailable.

Mutating tests each use a different question, so they do not depend on order.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import pytest

pw = pytest.importorskip("playwright.sync_api", reason="playwright not installed")
from playwright.sync_api import Error as PWError, expect, sync_playwright  # noqa: E402

from backend.app.config import ROOT  # noqa: E402
from backend.app.db import init_db, make_engine, session_factory  # noqa: E402
from backend.app.importer import import_all  # noqa: E402
from backend.app.models import Report, utcnow  # noqa: E402
from backend.app.services.triage_store import run_and_store  # noqa: E402

pytestmark = pytest.mark.e2e
KEY = "e2e-faculty-key-0123456789abcdef"
LCR = "60f744b3f1b9bc7cc7b4a949"          # answer_key C→A (faculty review)
PLEXUS = "61ee6c9d90a1a968a168686b"       # spelling plexux→plexus (faculty review, has edit)
DUP_OPTIONS = "6956d79788d7701e5617bc29"  # identical_options (no writable fields)
FRAC = "63765a28f1d8416ae0408d89"         # markup_leak (auto-eligible, proposed)
CHAPTER = "68ecbacb2ec87a18deba1ad7"      # wrong_chapter
MISSING_D = "622f08d7b70e4b50e4500a1b"    # R009/R010
XSS = '<img src=x onerror="window.__xss=1"><script>window.__xss=2</script> option C is wrong'


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server():
    tmp = Path(tempfile.mkdtemp())
    url = f"sqlite:///{(tmp / 'e2e.db').as_posix()}"
    eng = make_engine(url)
    init_db(eng)
    with session_factory(eng)() as s:
        import_all(s, ROOT / "data")
        run_and_store(s)
        s.add(Report(report_id="R901", question_id=LCR, student_id="stu_e2e", source="web", reported_at=utcnow(), comment=XSS))
        s.commit()
    eng.dispose()
    port = _free_port()
    env = {**os.environ, "DATABASE_URL": url, "FACULTY_ACCESS_KEY": KEY, "PYTHONUTF8": "1", "LOG_LEVEL": "WARNING"}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.app.main:app", "--port", str(port)], cwd=ROOT,
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    for _ in range(150):
        try:
            if httpx.get(base + "/api/v1/health", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.2)
    else:
        proc.terminate()
        pytest.fail("server did not start")
    yield base
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        try:
            b = p.chromium.launch(channel="msedge", headless=True)
        except PWError as e:
            pytest.skip(f"Microsoft Edge not available for Playwright: {e}")
        yield b
        b.close()


@pytest.fixture
def page(browser):
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    pg = ctx.new_page()
    pg.set_default_timeout(10_000)
    pg.problems = []
    pg.on("pageerror", lambda e: pg.problems.append(f"pageerror: {e}"))
    pg.on("console", lambda m: pg.problems.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
    pg.on("dialog", lambda d: (pg.problems.append(f"native dialog: {d.message}"), d.dismiss()))
    yield pg
    ctx.close()


def api(base, path, method="GET", body=None, key=None):
    headers = {"X-Faculty-Key": key} if key else {}
    r = httpx.request(method, base + "/api/v1" + path, json=body, headers=headers, timeout=10)
    return r


def repair_of(base, qid, status=None):
    reps = api(base, f"/cases/{qid}").json()["repairs"]
    return next(r for r in reps if r["status"] != "superseded" and (status is None or r["status"] == status))


def answer_of(base, qid):
    return api(base, f"/questions/{qid}").json()["answer"]


def go(page, base, hash_):
    page.goto(f"{base}/#{hash_}")
    page.wait_for_load_state("networkidle")


def login(page, base, name="Meera Iyer", key=KEY):
    go(page, base, "/settings")
    page.get_by_label("Your name (recorded on every action)").fill(name)
    page.get_by_label("Faculty key").fill(key)
    page.get_by_role("button", name="Verify and use key").click()


# ------------------------------------------------------------------ screens & data

SCREENS = [("/", "Overview"), ("/queue", "Report Queue"), ("/review", "Faculty Review"), (f"/case/{LCR}", "In a LCR circuit"),
           ("/quality", "Quality Audit"), ("/revisions", "Revision History"), ("/audit", "Audit Logs"), ("/settings", "Settings")]


@pytest.mark.parametrize("hash_,heading", SCREENS)
def test_every_screen_renders_without_errors(page, server, hash_, heading):
    bad = []
    page.on("response", lambda r: bad.append(f"{r.status} {r.url}") if r.status >= 400 else None)
    go(page, server, hash_)
    expect(page.locator("h1")).to_contain_text(heading)
    assert page.problems == [] and bad == []
    assert page.locator('nav a[aria-current="page"]').count() == 1


def test_overview_numbers_are_the_api_numbers(page, server):
    d = api(server, "/dashboard").json()
    go(page, server, "/")
    strip = page.get_by_label("Key metrics")
    for label, key in [("Total reports", "total_reports"), ("Unique questions", "unique_questions"),
                       ("Confirmed defects", "confirmed_defects"), ("Faculty review", "needs_review")]:
        expect(strip.locator(".metric", has_text=label).locator(".metric-value")).to_have_text(str(d["metrics"][key]))
    already = next((v["count"] for v in d["verdicts"] if v["verdict"] == "already_fixed"), 0)
    expect(strip.locator(".metric", has_text="Already fixed").locator(".metric-value")).to_have_text(str(already))
    expect(page.locator("section", has_text="Most urgent").locator("tbody tr")).to_have_count(len(d["urgent"]))


def test_queue_filters_search_sort_and_pagination(page, server):
    go(page, server, "/queue")
    total = api(server, "/cases").json()["total"]
    expect(page.locator(".pager").first).to_contain_text(f"of {total}")
    page.get_by_role("button", name="Needs review").click()
    page.wait_for_load_state("networkidle")
    assert "status=needs_review" in page.url
    n = api(server, "/cases", body=None).json()  # sanity: API reachable
    want = api(server, "/cases?status=needs_review").json()["total"]
    expect(page.locator(".pager").first).to_contain_text(f"of {want}")
    page.get_by_role("button", name="Clear filters").click()
    page.get_by_label("Search").fill("R019")
    expect(page.locator("tbody tr")).to_have_count(1)
    expect(page.locator("tbody tr").first).to_contain_text("de-Broglie")
    page.get_by_label("Search").fill("")
    page.wait_for_timeout(500)
    page.get_by_label("Subject").select_option("Botany")
    page.wait_for_load_state("networkidle")
    expect(page.locator("tbody tr")).to_have_count(api(server, "/cases?subject=Botany").json()["total"])
    page.get_by_role("button", name="Reports").click()
    page.wait_for_load_state("networkidle")
    assert "sort=reports" in page.url
    assert n["total"] == total


def test_keyboard_navigation_opens_a_case(page, server):
    go(page, server, "/queue")
    page.keyboard.press("j")
    page.keyboard.press("Enter")
    page.wait_for_url("**/#/case/*")
    expect(page.locator("h1")).to_be_visible()


def test_mathml_preserved(page, server):
    go(page, server, f"/case/{LCR}")
    assert page.locator(".content math").count() >= 1
    ns = page.evaluate("document.querySelector('.content math').namespaceURI")
    assert ns == "http://www.w3.org/1998/Math/MathML"
    expect(page.locator(".content math").first).to_be_visible()


def test_malicious_student_comment_is_inert_text(page, server):
    go(page, server, f"/case/{LCR}")
    comment = page.locator(".comment", has_text="option C is wrong")
    expect(comment).to_contain_text('<script>window.__xss=2</script>')     # shown literally
    assert page.evaluate("window.__xss") is None
    assert page.locator("main img[onerror], main script").count() == 0
    assert not any("native dialog" in p for p in page.problems)


def test_injection_report_is_flagged(page, server):
    go(page, server, "/case/6062ec84518e9535e120c422")
    expect(page.get_by_text("instruction-like text · not followed")).to_be_visible()


# ------------------------------------------------------------------ authentication

def test_read_only_without_key(page, server):
    go(page, server, f"/case/{LCR}")
    btn = page.get_by_role("button", name="Approve…")
    expect(btn).to_be_disabled()
    expect(btn).to_have_attribute("title", "Enter the faculty key in Settings to make changes.")
    expect(page.locator("#key-pill")).to_contain_text("Read-only")


def test_invalid_key_is_rejected_and_cleared(page, server):
    login(page, server, key="definitely-the-wrong-key-123")
    expect(page.get_by_text("The key was rejected")).to_be_visible()
    expect(page.locator("#key-pill")).to_contain_text("Key rejected")
    go(page, server, f"/case/{LCR}")
    expect(page.get_by_role("button", name="Approve…")).to_be_disabled()


def test_valid_key_lives_only_in_memory(page, server):
    login(page, server)
    expect(page.get_by_text("Write access verified", exact=True)).to_be_visible()
    expect(page.locator("#key-pill")).to_contain_text("Faculty · Meera Iyer")
    stored = page.evaluate("JSON.stringify({...localStorage}) + JSON.stringify({...sessionStorage})")
    assert KEY not in stored and KEY not in page.url and KEY not in page.content()
    assert page.get_by_label("Faculty key").input_value() == ""
    page.reload()
    page.wait_for_load_state("networkidle")
    expect(page.locator("#key-pill")).to_contain_text("Read-only")      # reload forgets the key


def test_frontend_source_contains_no_key():
    for f in (ROOT / "frontend").rglob("*"):
        if f.suffix in (".js", ".html", ".css"):
            text = f.read_text(encoding="utf-8")
            assert "FACULTY_ACCESS_KEY" not in text and KEY not in text, f


# ------------------------------------------------------------------ faculty workflows

def test_answer_key_approve_execute_rollback_are_separate(page, server):
    login(page, server)
    rep = repair_of(server, LCR, "proposed")
    go(page, server, f"/case/{LCR}")
    expect(page.get_by_text("Answer-key change: independent verification is unavailable")).to_be_visible()
    page.get_by_role("button", name="Approve…").click()
    dlg = page.locator("dialog[open]")
    approve = dlg.get_by_role("button", name="Approve repair")
    expect(approve).to_be_disabled()                                    # explicit teacher confirmation required
    dlg.get_by_label("I have independently verified the correct answer.").check()
    approve.click()
    expect(page.locator(".toast", has_text=f"Repair #{rep['id']} approved. Not executed yet.").last).to_be_visible()
    assert answer_of(server, LCR) == "C"                                # approval changed nothing
    expect(page.get_by_text("Approved but not executed")).to_be_visible()

    page.get_by_role("button", name="Execute…").click()
    dlg = page.locator("dialog[open]")
    expect(dlg).to_contain_text("This writes to the live question")
    dlg.get_by_role("button", name=f"Execute repair #{rep['id']}").click()
    expect(page.locator(".toast", has_text="Executed: revision #").last).to_be_visible()
    assert answer_of(server, LCR) == "A"

    rev = api(server, f"/questions/{LCR}/revisions").json()["items"][-1]
    page.get_by_role("button", name=f"Roll back revision #{rev['id']}…").click()
    page.locator("dialog[open]").get_by_role("button", name=f"Roll back revision #{rev['id']}").click()
    expect(page.locator(".toast", has_text=f"revision #{rev['id']} reverted by").last).to_be_visible()
    assert answer_of(server, LCR) == "C"
    expect(page.get_by_text(f"rolled back by #")).to_be_visible()
    assert api(server, "/audit/verify").json()["ok"] is True


def test_reject_requires_a_reason(page, server):
    login(page, server)
    rep = repair_of(server, DUP_OPTIONS, "proposed")
    go(page, server, f"/case/{DUP_OPTIONS}")
    page.get_by_role("button", name="Reject…").click()
    dlg = page.locator("dialog[open]")
    go_btn = dlg.get_by_role("button", name="Reject repair")
    expect(go_btn).to_be_disabled()
    dlg.get_by_label("Reason (required)").fill("Options will be rewritten in the CMS")
    go_btn.click()
    expect(page.locator(".toast", has_text=f"Repair #{rep['id']} rejected.").last).to_be_visible()
    assert repair_of(server, DUP_OPTIONS)["status"] == "rejected"


def test_edit_proposal_must_validate_before_approval(page, server):
    login(page, server)
    go(page, server, f"/case/{PLEXUS}")
    page.get_by_role("button", name="Edit proposal…").click()
    dlg = page.locator("dialog[open]")
    approve = dlg.get_by_role("button", name="Approve with this edit")
    expect(approve).to_be_disabled()
    dlg.get_by_label("Replace").fill("pl3xus")                          # digit change: violates R-31
    dlg.get_by_role("button", name="Validate").click()
    expect(dlg.get_by_text("Not valid")).to_be_visible()
    expect(approve).to_be_disabled()
    dlg.get_by_label("Replace").fill("plexus")
    expect(dlg.get_by_text("Validate the edit before approving it.")).to_be_visible()   # stale validation cleared
    dlg.get_by_role("button", name="Validate").click()
    expect(dlg.get_by_text("Valid", exact=True)).to_be_visible()
    approve.click()
    page.locator("dialog[open]").get_by_role("button", name="Approve repair").click()
    expect(page.locator(".toast", has_text="approved").last).to_be_visible()
    r = repair_of(server, PLEXUS)
    assert r["status"] == "approved_applied" and r["edit"]["replace"] == "plexus"
    assert "plexux" in api(server, f"/questions/{PLEXUS}").json()["question_html_safe"]   # not executed


def test_conflict_shows_server_message_and_refreshes(page, server):
    login(page, server)
    rep = repair_of(server, FRAC, "proposed")
    go(page, server, f"/case/{FRAC}")
    assert api(server, f"/repairs/{rep['id']}/approve", "POST", {"actor": "Someone Else"}, KEY).status_code == 200
    page.get_by_role("button", name="Approve…").click()
    page.locator("dialog[open]").get_by_role("button", name="Approve repair").click()
    expect(page.locator(".toast.danger")).to_contain_text("This changed since you loaded it")
    expect(page.locator("dialog[open]")).to_have_count(0)
    expect(page.get_by_role("button", name="Execute…")).to_be_visible()  # view refreshed to the true state


def test_investigate_and_reopen(page, server):
    login(page, server)
    go(page, server, f"/case/{CHAPTER}")
    before = api(server, f"/cases/{CHAPTER}").json()["status"]
    page.get_by_role("button", name="Request investigation…").click()
    dlg = page.locator("dialog[open]")
    dlg.get_by_label("What needs checking? (required)").fill("Confirm the correct chapter with Biology")
    dlg.get_by_role("button", name="Put on hold").click()
    expect(page.locator(".toast", has_text="under investigation").last).to_be_visible()
    assert api(server, f"/cases/{CHAPTER}").json()["status"] == "investigating"
    page.get_by_role("button", name="Reopen case…").click()
    page.locator("dialog[open]").get_by_role("button", name="Reopen case").click()
    expect(page.locator(".toast", has_text="Case reopened").last).to_be_visible()
    assert api(server, f"/cases/{CHAPTER}").json()["status"] == before


def test_reply_edit_enforces_truthfulness_and_duplicate_marking(page, server):
    login(page, server)
    go(page, server, f"/case/{MISSING_D}")
    card = page.get_by_role("article", name="Report R010")
    card.get_by_role("button", name="Edit reply…").click()
    dlg = page.locator("dialog[open]")
    dlg.get_by_label("Reply the student will see").fill("Thanks! We have fixed it.")
    dlg.get_by_role("button", name="Save reply").click()
    expect(dlg.get_by_role("alert")).to_contain_text("R-71")            # server refuses a false 'fixed'
    dlg.get_by_label("Reply the student will see").fill("Thanks for flagging this. A teacher is adding the missing option.")
    dlg.get_by_role("button", name="Save reply").click()
    expect(page.locator(".toast", has_text="Reply to R010 saved").last).to_be_visible()
    expect(page.get_by_role("article", name="Report R010")).to_contain_text("edited by faculty")

    page.get_by_role("article", name="Report R010").get_by_role("button", name="Mark duplicate…").click()
    dlg = page.locator("dialog[open]")
    dlg.get_by_label("Duplicate of").select_option("R009")
    dlg.get_by_role("button", name="Mark duplicate").click()
    expect(page.locator(".toast", has_text="R010 marked as a duplicate of R009").last).to_be_visible()
    expect(page.get_by_role("article", name="Report R010")).to_contain_text("duplicate of R009")


def test_audit_and_revision_history_screens(page, server):
    go(page, server, "/audit")
    expect(page.get_by_text("Audit chain verified")).to_be_visible()
    page.get_by_label("Actor").select_option("faculty")
    page.wait_for_load_state("networkidle")
    assert "actor_type=faculty" in page.url
    want = api(server, "/audit?actor_type=faculty").json()["total"]
    expect(page.locator(".pager")).to_contain_text(f"of {want}")
    go(page, server, "/revisions")
    total = api(server, "/revisions").json()["total"]
    expect(page.locator(".pager")).to_contain_text(f"of {total}")


# ------------------------------------------------------------------ error states (single responses intercepted)

def _fulfil(page, pattern, status, code, message):
    page.route(pattern, lambda route: route.fulfill(status=status, content_type="application/json",
               body=json.dumps({"error": {"code": code, "message": message, "details": None, "request_id": "e2eREQ12345"}})))


@pytest.mark.parametrize("status,code,shown", [
    (401, "auth_required", "Enter the faculty key in Settings"),
    (413, "payload_too_large", "too long to send"),
    (503, "writes_disabled", "Changes are disabled on this server"),
])
def test_write_error_states(page, server, status, code, shown):
    login(page, server)
    go(page, server, f"/case/{MISSING_D}")
    _fulfil(page, "**/api/v1/reports/*/reply", status, code, "x")
    page.get_by_role("article", name="Report R009").get_by_role("button", name="Edit reply…").click()
    dlg = page.locator("dialog[open]")
    dlg.get_by_label("Reply the student will see").fill("Thanks, a teacher is checking this.")
    dlg.get_by_role("button", name="Save reply").click()
    expect(dlg.get_by_role("alert")).to_contain_text(shown)
    expect(dlg.get_by_role("alert")).to_contain_text("e2eREQ12345")     # request id surfaced


def test_server_with_writes_disabled_disables_buttons(page, server):
    page.route("**/api/v1/auth/status", lambda r: r.fulfill(status=200, content_type="application/json", body='{"writes_enabled": false}'))
    go(page, server, f"/case/{LCR}")
    page.wait_for_timeout(300)
    go(page, server, f"/case/{LCR}")
    expect(page.locator("#key-pill")).to_contain_text("Writes disabled on server")
    expect(page.get_by_role("button", name="Request investigation…")).to_be_disabled()


def test_read_error_has_retry(page, server):
    _fulfil(page, "**/api/v1/revisions*", 500, "internal_error", "Something went wrong on our side.")
    go(page, server, "/revisions")
    alert = page.get_by_role("alert")
    expect(alert).to_contain_text("Something went wrong")
    page.unroute("**/api/v1/revisions*")
    alert.get_by_role("button", name="Retry").click()
    expect(page.locator("h1")).to_have_text("Revision History")


# ------------------------------------------------------------------ responsive

@pytest.mark.parametrize("w,h", [(1440, 900), (1280, 800), (1024, 768), (768, 1024), (390, 844)])
@pytest.mark.parametrize("hash_", ["/", "/queue", f"/case/{LCR}", "/audit", "/settings"])
def test_no_horizontal_overflow(browser, server, w, h, hash_):
    ctx = browser.new_context(viewport={"width": w, "height": h})
    pg = ctx.new_page()
    pg.goto(f"{server}/#{hash_}")
    pg.wait_for_load_state("networkidle")
    overflow = pg.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    ctx.close()
    assert overflow <= 1, f"{w}x{h} {hash_}: {overflow}px horizontal overflow"


def test_mobile_navigation(browser, server):
    ctx = browser.new_context(viewport={"width": 390, "height": 844})
    pg = ctx.new_page()
    pg.goto(f"{server}/#/")
    pg.wait_for_load_state("networkidle")
    nav = pg.locator("#sidebar")
    assert pg.evaluate("document.getElementById('sidebar').getBoundingClientRect().right") <= 0
    pg.get_by_role("button", name="Menu").click()
    expect(pg.get_by_role("button", name="Menu")).to_have_attribute("aria-expanded", "true")
    pg.wait_for_timeout(250)
    assert pg.evaluate("document.getElementById('sidebar').getBoundingClientRect().left") >= 0
    nav.get_by_role("link", name="Audit Logs").click()
    expect(pg.locator("h1")).to_have_text("Audit Logs")
    ctx.close()
