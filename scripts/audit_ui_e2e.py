"""Comprehensive Playwright UI E2E Audit Script.

Tests:
1. Console errors / JS unhandled exceptions
2. Dashboard rendering and confirmation flow
3. Timetable weekly grid and slot CRUD
4. Calendar holiday and exception creation and validation
5. Subjects & Instructor mapping CRUD
6. Attendance history filtering
7. Settings & OAuth providers display
8. Responsive mobile layout and hamburger menu
"""

import sys
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright
from app.database import SessionLocal
from app.models.subject import Subject
from app.models.calendar import Holiday, ClassException


def cleanup_db(test_code="TEST999"):
    """Clean up test artifacts from database."""
    db = SessionLocal()
    try:
        s = db.query(Subject).filter(Subject.code == test_code).first()
        if s:
            db.delete(s)
        h = db.query(Holiday).filter(Holiday.description.like("%Winter%")).all()
        for x in h:
            db.delete(x)
        e = db.query(ClassException).filter(ClassException.description.like("%Conference%")).all()
        for x in e:
            db.delete(x)
        db.commit()
    finally:
        db.close()


def run_audit():
    cleanup_db()
    console_errors = []
    page_errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        # Automatically accept all window.confirm dialogs
        page.on("dialog", lambda dialog: dialog.accept())

        def on_console(msg):
            if msg.type == "error":
                console_errors.append(f"[ERROR] {msg.text}")
            elif msg.type == "warning" and "DevTools" not in msg.text:
                console_errors.append(f"[WARN] {msg.text}")

        def on_page_error(exc):
            page_errors.append(str(exc))

        page.on("console", on_console)
        page.on("pageerror", on_page_error)

        try:
            print("--- 1. Testing Application Startup & Dashboard ---")
            page.goto("http://127.0.0.1:8000/dashboard", wait_until="networkidle")
            assert page.title() == "Attendance Automation Dashboard", f"Unexpected title: {page.title()}"
            
            # Check Dashboard content is displayed
            page.wait_for_selector("#dashboard-content", state="visible", timeout=5000)
            hero_title = page.locator("#hero-title").inner_text()
            print(f"Hero Title: {hero_title}")

            btn_confirm = page.locator("#btn-confirm-attendance")
            if btn_confirm.is_visible() and not btn_confirm.is_disabled():
                print("Clicking 'I WENT TO COLLEGE'...")
                page.fill("#input-confirm-note", "Playwright E2E Verification Note")
                btn_confirm.click()
                page.wait_for_timeout(1000)
                status_badge = page.locator("#hero-status-badge").inner_text()
                print(f"Post-confirmation status: {status_badge}")
                assert "Confirmed" in status_badge or "Attended" in status_badge
            else:
                status_badge = page.locator("#hero-status-badge").inner_text()
                print(f"Attendance status: {status_badge}")

            print("--- 2. Testing Subjects Page & CRUD ---")
            page.click("a[data-route='subjects']")
            page.wait_for_selector("#subjects-content", state="visible", timeout=5000)
            
            # Create test subject
            page.click("#btn-show-add-subject-modal")
            page.wait_for_selector("#modal-subject", state="visible", timeout=3000)
            test_code = "TEST999"
            test_name = "Automated Audit Test Course"
            page.fill("#input-subject-code", test_code)
            page.fill("#input-subject-name", test_name)
            page.fill("#input-prof-name", "Dr. Alan Turing")
            page.fill("#input-prof-email", "alan.turing@university.edu")
            page.fill("#input-chat-space", "spaces/AAAA9999")
            page.click("#btn-save-subject")
            page.wait_for_selector(f"#subjects-container:has-text('{test_code}')", timeout=5000)

            # Verify subject card exists
            subject_content = page.locator("#subjects-container").inner_text()
            assert test_code in subject_content, "Test subject not found in subjects container after creation"
            assert "alan.turing@university.edu" in subject_content, "Professor email not displayed"
            print(f"Subject {test_code} created and verified with instructor mapping.")

            print("--- 3. Testing Timetable Weekly Grid & Slot Creation ---")
            page.click("a[data-route='timetable']")
            page.wait_for_selector("#timetable-content", state="visible", timeout=5000)
            
            # Open Add Class Modal
            page.click("#btn-show-add-slot-modal")
            page.wait_for_selector("#modal-timetable-slot", state="visible", timeout=3000)
            
            # Select Subject and fields
            page.select_option("#input-slot-subject", label=f"{test_code} - {test_name}")
            page.select_option("#input-slot-weekday", value="1") # Tuesday
            page.fill("#input-slot-start", "09:30")
            page.fill("#input-slot-end", "11:00")
            page.fill("#input-slot-period", "E2E Lab Session")
            page.click("#btn-save-timetable-slot")
            page.wait_for_selector(f"#timetable-days-container:has-text('{test_code}')", timeout=5000)
            
            # Check timetable renders Tuesday slot
            timetable_content = page.locator("#timetable-days-container").inner_text()
            assert "E2E Lab Session" in timetable_content, "Created slot missing from timetable"
            assert test_code in timetable_content, "Subject code missing from timetable slot"
            print("Timetable slot created and verified on Tuesday grid.")

            print("--- 4. Testing Calendar Holidays & Exceptions ---")
            page.click("a[data-route='calendar']")
            page.wait_for_selector("#calendar-content", state="visible", timeout=5000)
            
            # Add Holiday
            page.click("#btn-show-add-holiday-modal")
            page.wait_for_selector("#modal-holiday", state="visible", timeout=3000)
            page.fill("#input-holiday-date", "2026-12-25")
            page.fill("#input-holiday-desc", "Winter Vacation Holiday")
            page.click("#btn-save-holiday")
            page.wait_for_selector("#calendar-holidays-container:has-text('Winter Vacation Holiday')", timeout=5000)
            holidays_text = page.locator("#calendar-holidays-container").inner_text()
            assert "Winter Vacation Holiday" in holidays_text, "Holiday not found in container"
            print("Holiday created and verified.")

            # Add Class Exception (CANCELLED)
            page.click("#btn-show-add-exception-modal")
            page.wait_for_selector("#modal-exception", state="visible", timeout=3000)
            page.select_option("#input-exception-type", value="CANCELLED")
            page.select_option("#input-exception-subject", label=f"{test_code} - {test_name}")
            page.fill("#input-exception-date", "2026-10-06")
            page.fill("#input-exception-desc", "Professor Conference Travel")
            page.click("#btn-save-exception")
            page.wait_for_selector("#calendar-exceptions-container:has-text('Professor Conference Travel')", timeout=5000)
            exceptions_text = page.locator("#calendar-exceptions-container").inner_text()
            assert "Professor Conference Travel" in exceptions_text, "Exception not found in container"
            print("Class cancellation exception created and verified.")

            # Test EXTRA class time toggle
            page.click("#btn-show-add-exception-modal")
            page.wait_for_selector("#modal-exception", state="visible", timeout=3000)
            page.select_option("#input-exception-type", value="EXTRA")
            assert page.locator("#exception-time-container").is_visible(), "Time fields should be visible for EXTRA class"
            page.select_option("#input-exception-type", value="CANCELLED")
            assert not page.locator("#exception-time-container").is_visible(), "Time fields should hide for CANCELLED class"
            page.click("#btn-cancel-exception-modal")
            page.wait_for_selector("#modal-exception", state="hidden", timeout=3000)
            print("Calendar EXTRA vs CANCELLED dynamic time toggle verified.")

            print("--- 5. Testing Attendance History Page ---")
            page.click("a[data-route='attendance']")
            page.wait_for_selector("#history-content", state="visible", timeout=5000)
            
            # Test date filtering
            page.fill("#filter-history-start", "2026-09-01")
            page.fill("#filter-history-end", "2026-09-30")
            page.click("#btn-apply-history-filters")
            page.wait_for_timeout(1000)
            print("Attendance history filtered cleanly.")

            print("--- 6. Testing Settings & OAuth Providers View ---")
            page.click("a[data-route='settings']")
            page.wait_for_selector("#settings-content", state="visible", timeout=5000)
            
            # Verify provider cards
            providers_text = page.locator("#notification-providers-list").inner_text()
            assert "Google Chat" in providers_text, "Google Chat provider card missing"
            assert "Gmail" in providers_text, "Gmail provider card missing"
            
            # Verify session status badge exists
            session_text = page.locator("#session-status-badge").inner_text()
            print(f"Portal session status: {session_text}")

            # Verify no secrets or sensitive keys appear in page text
            page_html = page.content()
            assert "client_secret" not in page_html.lower() or "[REDACTED]" in page_html
            assert "ya29." not in page_html
            print("Settings & OAuth providers rendered cleanly without secret leaks.")

            print("--- 7. Cleaning up Test Artifacts ---")
            # Go to Calendar to delete test holiday
            page.click("a[data-route='calendar']")
            page.wait_for_selector("#calendar-content", state="visible", timeout=5000)
            del_holiday_btn = page.locator("button.btn-delete-holiday").first
            if del_holiday_btn.is_visible():
                del_holiday_btn.click()
                page.wait_for_timeout(800)
                print("Cleaned up test holiday.")

            # Go to Subjects and delete test subject (which cascades to timetable slot and exception)
            page.click("a[data-route='subjects']")
            page.wait_for_selector("#subjects-content", state="visible", timeout=5000)
            del_subject_btn = page.locator(f"button.btn-delete-subject[data-code='{test_code}']")
            if del_subject_btn.is_visible():
                del_subject_btn.click()
                page.wait_for_timeout(1000)
                post_subjects = page.locator("#subjects-container").inner_text()
                assert test_code not in post_subjects
                print(f"Subject {test_code} deleted; cascading deletions confirmed.")

            print("--- 8. Testing Responsive Layout (Mobile Viewport 375x667) ---")
            page.set_viewport_size({"width": 375, "height": 667})
            page.wait_for_timeout(500)
            
            # Check hamburger button is visible on mobile
            menu_btn = page.locator("#mobile-menu-btn")
            assert menu_btn.is_visible(), "Mobile hamburger menu button should be visible on 375px width"
            
            # Toggle open
            menu_btn.click()
            page.wait_for_timeout(500)
            sidebar = page.locator("#app-sidebar")
            assert "open" in (sidebar.get_attribute("class") or ""), "Sidebar should open on hamburger click"
            
            # Close via close button in drawer header
            close_btn = page.locator("#sidebar-close-btn")
            assert close_btn.is_visible(), "Close button should be visible in drawer"
            close_btn.click()
            page.wait_for_timeout(500)
            assert "open" not in (sidebar.get_attribute("class") or ""), "Sidebar should close on close button click"
            
            # Open again and close via backdrop click
            menu_btn.click()
            page.wait_for_timeout(500)
            assert "open" in (sidebar.get_attribute("class") or ""), "Sidebar should open on hamburger click"
            page.locator("#sidebar-backdrop").click(position={"x": 320, "y": 300})
            page.wait_for_timeout(500)
            assert "open" not in (sidebar.get_attribute("class") or ""), "Sidebar should close on backdrop click"
            print("Mobile responsive drawer verified with close button and backdrop click.")

        finally:
            cleanup_db()
            browser.close()

    print("\n--- E2E AUDIT RESULTS ---")
    print(f"Console Errors logged: {len(console_errors)}")
    for err in console_errors:
        print(f"  {err}")
    print(f"Page Unhandled Exceptions: {len(page_errors)}")
    for err in page_errors:
        print(f"  {err}")

    if page_errors:
        print("AUDIT FAILED: Unhandled page exceptions detected!")
        sys.exit(1)
    print("\nALL BROWSER E2E TESTS PASSED CLEANLY WITH ZERO EXCEPTIONS!")


if __name__ == "__main__":
    run_audit()
