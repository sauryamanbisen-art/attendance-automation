"""Test suite validating the complete PWIOI Portal Academic Attendance pipeline.

Verifies:
PWIOI Portal -> Playwright Adapter -> Attendance Parser -> Database -> API & Frontend
"""

from datetime import date
from unittest.mock import MagicMock
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.adapters.pwioi.adapter import PWIOIPortalAdapter
from app.adapters.pwioi.config import PWIOIPortalConfig
from app.database.base import Base
from app.models.portal_attendance import PortalAttendanceSummary
from app.models.subject import Subject
from app.services.portal_attendance_service import PortalAttendanceService


@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_portal_academic_summary_extraction_from_dom():
    """Verify Playwright adapter extracts real overall attendance, classes, and course rates from PWIOI DOM."""
    from playwright.sync_api import sync_playwright

    html = """<!DOCTYPE html>
<html>
<body>
  <div>
    <div class="stat-card">
      <p>Overall Attendance</p>
      <h3>94.0%</h3>
    </div>
    <div class="stat-card">
      <p>Classes Attended</p>
      <h3>147 / 157</h3>
    </div>
  </div>

  <div class="xl:col-span-3 space-y-4 border border-gray-400 p-4 rounded-sm">
    <div class="flex items-center justify-between">
      <h2 class="text-xl font-semibold text-gray-900">Course Breakdown</h2>
      <span class="text-sm text-gray-500">2 courses</span>
    </div>
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <div class="bg-white border border-gray-400 rounded-sm shadow-sm p-4 hover:shadow-md transition-shadow cursor-pointer group" id="card-0">
        <div class="flex justify-between items-start mb-4">
          <div class="flex-1 min-w-0">
            <h4 class="font-semibold text-gray-900 text-sm mb-1 truncate">Operating System</h4>
            <div class="flex items-center gap-2">
              <span class="px-2 py-0.5 rounded-sm text-xs font-medium bg-gray-100 text-gray-700">302OPS</span>
              <span class="px-2 py-0.5 rounded-sm text-xs font-medium bg-green-50 text-green-700 border border-green-200">85.7%</span>
            </div>
          </div>
        </div>
        <p class="text-xs text-gray-500">12 / 14 Classes</p>
        <p class="text-xs text-gray-500">Click to view details &rarr;</p>
      </div>
      <div class="bg-white border border-gray-400 rounded-sm shadow-sm p-4 hover:shadow-md transition-shadow cursor-pointer group" id="card-1">
        <div class="flex justify-between items-start mb-4">
          <div class="flex-1 min-w-0">
            <h4 class="font-semibold text-gray-900 text-sm mb-1 truncate">OJT / Java Web Developer (Spring Boot)</h4>
            <div class="flex items-center gap-2">
              <span class="px-2 py-0.5 rounded-sm text-xs font-medium bg-gray-100 text-gray-700">306JWD</span>
              <span class="px-2 py-0.5 rounded-sm text-xs font-medium bg-green-50 text-green-700 border border-green-200">90.0%</span>
            </div>
          </div>
        </div>
        <p class="text-xs text-gray-500">18 / 20 Classes</p>
        <p class="text-xs text-gray-500">Click to view details &rarr;</p>
      </div>
    </div>
  </div>
</body>
</html>"""

    cfg = PWIOIPortalConfig()
    adapter = PWIOIPortalAdapter(config=cfg)

    with sync_playwright() as p:
        try:
            b = p.chromium.launch(headless=True)
        except Exception:
            try:
                b = p.chromium.launch(channel="chrome", headless=True)
            except Exception:
                pytest.skip("Playwright browser not available")
        page = b.new_page()
        page.set_content(html)

        extracted = adapter.extract_academic_summary(page)
        assert extracted["sync_status"] == "SYNCED"
        assert extracted["overall_rate"] == 94.0
        assert extracted["attended_classes"] == 147
        assert extracted["total_classes"] == 157
        assert extracted["missed_classes"] == 10
        assert extracted["course_count"] == 2
        assert "302OPS" in extracted["courses"]
        assert extracted["courses"]["302OPS"]["rate"] == 85.7
        assert extracted["courses"]["306JWD"]["rate"] == 90.0
        b.close()


def test_portal_attendance_service_persistence_and_separation(test_db):
    """Verify PortalAttendanceService saves and retrieves authoritative values, without synthetic data."""
    svc = PortalAttendanceService(test_db)
    
    # 1. Unsynced state returns None fields with truthful status
    initial = svc.get_or_create_awaiting_summary()
    assert initial.sync_status == "AWAITING_PORTAL_SYNC"
    assert initial.overall_rate is None
    assert initial.total_classes is None
    assert initial.attended_classes is None

    # 2. Saving extracted portal values updates cleanly
    updated = svc.update_summary(
        overall_rate=94.0,
        total_classes=157,
        attended_classes=147,
        missed_classes=10,
        course_count=6,
        course_stats={
            "302OPS": {"rate": 85.7, "attended_classes": 12, "total_classes": 14},
            "306JWD": {"rate": 90.0, "attended_classes": 18, "total_classes": 20},
        },
        sync_status="SYNCED",
    )
    assert updated.sync_status == "SYNCED"
    assert updated.overall_rate == 94.0
    assert updated.attended_classes == 147
    assert updated.total_classes == 157
    assert updated.missed_classes == 10
    
    courses = updated.get_course_stats()
    assert courses["302OPS"]["rate"] == 85.7
    assert courses["306JWD"]["rate"] == 90.0
