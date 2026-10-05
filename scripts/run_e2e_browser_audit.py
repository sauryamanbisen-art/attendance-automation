import asyncio
import os
from playwright.async_api import async_playwright

ARTIFACT_DIR = "/Users/sauryamanbisen/.gemini/antigravity-ide/brain/caa47dc0-b234-4cc2-a9d2-212ae7a0dffe"

async def audit():
    os.makedirs(ARTIFACT_DIR, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        context = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await context.new_page()

        console_errors = []
        network_errors = []

        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("requestfailed", lambda req: network_errors.append(f"{req.method} {req.url}: {req.failure}"))
        page.on("response", lambda res: network_errors.append(f"{res.status} {res.url}") if res.status >= 400 and not res.url.endswith("favicon.ico") else None)

        # 1. Desktop Dashboard
        await page.goto("http://127.0.0.1:8000/dashboard")
        await page.wait_for_timeout(2000)
        await page.screenshot(path=os.path.join(ARTIFACT_DIR, "audit_dashboard_desktop.png"))

        # 2. Timetable
        timetable_btn = page.locator("a[href='#timetable'], button#tab-timetable, nav a:has-text('Timetable')").first
        if await timetable_btn.is_visible():
            await timetable_btn.click()
            await page.wait_for_timeout(1500)
            await page.screenshot(path=os.path.join(ARTIFACT_DIR, "audit_timetable_desktop.png"))

        # 3. Calendar & Exceptions
        cal_btn = page.locator("a[href='#calendar'], button#tab-calendar, nav a:has-text('Calendar')").first
        if await cal_btn.is_visible():
            await cal_btn.click()
            await page.wait_for_timeout(1500)
            await page.screenshot(path=os.path.join(ARTIFACT_DIR, "audit_calendar_desktop.png"))

        # 4. Attendance History
        history_btn = page.locator("a[href='#attendance'], button#tab-attendance, nav a:has-text('Attendance')").first
        if await history_btn.is_visible():
            await history_btn.click()
            await page.wait_for_timeout(1500)
            await page.screenshot(path=os.path.join(ARTIFACT_DIR, "audit_history_page1_desktop.png"))

            # Check row count
            rows = await page.locator("tbody tr").count()
            print(f"Attendance rows count on page 1: {rows}")

            # Click next
            next_btn = page.locator("#next-page, button:has-text('Next')").first
            if await next_btn.is_visible() and await next_btn.is_enabled():
                await next_btn.click()
                await page.wait_for_timeout(1000)
                await page.screenshot(path=os.path.join(ARTIFACT_DIR, "audit_history_page2_desktop.png"))
                rows_p2 = await page.locator("tbody tr").count()
                print(f"Attendance rows count on page 2: {rows_p2}")

        # 5. Subjects
        subjects_btn = page.locator("a[href='#subjects'], button#tab-subjects, nav a:has-text('Subjects')").first
        if await subjects_btn.is_visible():
            await subjects_btn.click()
            await page.wait_for_timeout(1500)
            await page.screenshot(path=os.path.join(ARTIFACT_DIR, "audit_subjects_desktop.png"))

        # 6. Settings
        settings_btn = page.locator("a[href='#settings'], button#tab-settings, nav a:has-text('Settings')").first
        if await settings_btn.is_visible():
            await settings_btn.click()
            await page.wait_for_timeout(1500)
            await page.screenshot(path=os.path.join(ARTIFACT_DIR, "audit_settings_desktop.png"))

        # 7. Tablet Responsive Dashboard & History (iPad 768x1024)
        await page.set_viewport_size({"width": 768, "height": 1024})
        await page.goto("http://127.0.0.1:8000/dashboard")
        await page.wait_for_timeout(1500)
        await page.screenshot(path=os.path.join(ARTIFACT_DIR, "audit_dashboard_tablet.png"))

        # 8. Mobile Responsive Dashboard & Navigation (iPhone 390x844)
        await page.set_viewport_size({"width": 390, "height": 844})
        await page.goto("http://127.0.0.1:8000/dashboard")
        await page.wait_for_timeout(1500)
        await page.screenshot(path=os.path.join(ARTIFACT_DIR, "audit_dashboard_mobile.png"))

        await browser.close()

        print(f"Console errors detected: {len(console_errors)}")
        for err in console_errors:
            print("  [CONSOLE ERROR]:", err)

        print(f"Network errors detected: {len(network_errors)}")
        for err in network_errors:
            print("  [NETWORK ERROR]:", err)

        assert len(console_errors) == 0, f"Found {len(console_errors)} console errors"
        assert len(network_errors) == 0, f"Found {len(network_errors)} network errors"
        print("Audit screenshots, responsive layouts, and DOM checks completed successfully with 0 errors.")

if __name__ == "__main__":
    asyncio.run(audit())
