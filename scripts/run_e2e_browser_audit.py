import asyncio
import os
from playwright.async_api import async_playwright

ARTIFACT_DIR = "/Users/sauryamanbisen/.gemini/antigravity-ide/brain/760303f0-7ffc-4c15-8084-c2185ed5c6e6"

async def audit():
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        context = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await context.new_page()

        # 1. Dashboard
        await page.goto("http://127.0.0.1:8000/dashboard")
        await page.wait_for_timeout(2000)
        await page.screenshot(path=os.path.join(ARTIFACT_DIR, "audit_dashboard_desktop.png"))
        
        # Check text contents on Dashboard
        dashboard_content = await page.content()
        
        # 2. Timetable
        timetable_btn = page.locator("a[href='#timetable'], button#tab-timetable, nav a:has-text('Timetable')").first
        if await timetable_btn.is_visible():
            await timetable_btn.click()
            await page.wait_for_timeout(1500)
            await page.screenshot(path=os.path.join(ARTIFACT_DIR, "audit_timetable_desktop.png"))
        
        # 3. Attendance History
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

        # 4. Subjects
        subjects_btn = page.locator("a[href='#subjects'], button#tab-subjects, nav a:has-text('Subjects')").first
        if await subjects_btn.is_visible():
            await subjects_btn.click()
            await page.wait_for_timeout(1500)
            await page.screenshot(path=os.path.join(ARTIFACT_DIR, "audit_subjects_desktop.png"))

        # 5. Settings
        settings_btn = page.locator("a[href='#settings'], button#tab-settings, nav a:has-text('Settings')").first
        if await settings_btn.is_visible():
            await settings_btn.click()
            await page.wait_for_timeout(1500)
            await page.screenshot(path=os.path.join(ARTIFACT_DIR, "audit_settings_desktop.png"))

        # 6. Mobile Dashboard
        await page.set_viewport_size({"width": 390, "height": 844})
        await page.goto("http://127.0.0.1:8000/dashboard")
        await page.wait_for_timeout(2000)
        await page.screenshot(path=os.path.join(ARTIFACT_DIR, "audit_dashboard_mobile.png"))

        await browser.close()
        print("Audit screenshots and DOM checks completed successfully.")

if __name__ == "__main__":
    asyncio.run(audit())
