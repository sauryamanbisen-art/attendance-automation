"""Unit tests for the isolated DecisionEngine."""

from datetime import date

import pytest
from sqlalchemy.orm import Session

from app.core.enums import AttendanceStatus, DecisionAction, DecisionReason
from app.models.attendance_confirmation import AttendanceConfirmation
from app.models.notification_event import NotificationEvent
from app.models.professor_mapping import ProfessorMapping
from app.models.subject import Subject
from app.services.decision_engine import DecisionEngine


def test_rule_unconfirmed_attendance_fails_closed() -> None:
    """If attendance is not confirmed, decision must be NO_ACTION regardless of portal status."""
    today = date(2026, 9, 25)

    # Even with ABSENT and valid professor, no confirmation -> NO_ACTION
    result = DecisionEngine.evaluate(
        is_confirmed=False,
        status=AttendanceStatus.ABSENT,
        is_reliable=True,
        has_professor_mapping=True,
        already_notified=False,
        subject_code="CS101",
        target_date=today,
        professor_email="prof@college.edu",
    )
    assert result.action == DecisionAction.NO_ACTION
    assert result.reason == DecisionReason.ATTENDANCE_NOT_CONFIRMED
    assert not result.is_eligible

    # Confirmed=False with PRESENT
    res_present = DecisionEngine.evaluate(
        is_confirmed=False,
        status=AttendanceStatus.PRESENT,
        is_reliable=True,
        has_professor_mapping=True,
        already_notified=False,
        subject_code="CS101",
        target_date=today,
    )
    assert res_present.action == DecisionAction.NO_ACTION
    assert res_present.reason == DecisionReason.ATTENDANCE_NOT_CONFIRMED


def test_rule_present_produces_no_action() -> None:
    """If student is PRESENT, decision must be NO_ACTION."""
    today = date(2026, 9, 25)
    result = DecisionEngine.evaluate(
        is_confirmed=True,
        status=AttendanceStatus.PRESENT,
        is_reliable=True,
        has_professor_mapping=True,
        already_notified=False,
        subject_code="CS101",
        target_date=today,
        professor_email="prof@college.edu",
    )
    assert result.action == DecisionAction.NO_ACTION
    assert result.reason == DecisionReason.STATUS_PRESENT
    assert not result.is_eligible


def test_rule_unknown_status_fails_closed() -> None:
    """If portal status is UNKNOWN, decision must be NO_ACTION."""
    today = date(2026, 9, 25)
    result = DecisionEngine.evaluate(
        is_confirmed=True,
        status=AttendanceStatus.UNKNOWN,
        is_reliable=True,
        has_professor_mapping=True,
        already_notified=False,
        subject_code="CS101",
        target_date=today,
        professor_email="prof@college.edu",
    )
    assert result.action == DecisionAction.NO_ACTION
    assert result.reason == DecisionReason.STATUS_UNKNOWN
    assert not result.is_eligible


def test_rule_absent_missing_professor_mapping() -> None:
    """If student is ABSENT and confirmed, but professor mapping is missing, decision must be NO_ACTION."""
    today = date(2026, 9, 25)

    # Case 1: has_professor_mapping is False
    res1 = DecisionEngine.evaluate(
        is_confirmed=True,
        status=AttendanceStatus.ABSENT,
        is_reliable=True,
        has_professor_mapping=False,
        already_notified=False,
        subject_code="CS101",
        target_date=today,
        professor_email=None,
    )
    assert res1.action == DecisionAction.NO_ACTION
    assert res1.reason == DecisionReason.MISSING_PROFESSOR_MAPPING
    assert not res1.is_eligible

    # Case 2: has_professor_mapping is True but email is empty/None
    res2 = DecisionEngine.evaluate(
        is_confirmed=True,
        status=AttendanceStatus.ABSENT,
        is_reliable=True,
        has_professor_mapping=True,
        already_notified=False,
        subject_code="CS101",
        target_date=today,
        professor_email="",
    )
    assert res2.action == DecisionAction.NO_ACTION
    assert res2.reason == DecisionReason.MISSING_PROFESSOR_MAPPING


def test_rule_absent_already_notified_deduplication() -> None:
    """If already notified today for this subject, decision must be NO_ACTION."""
    today = date(2026, 9, 25)
    result = DecisionEngine.evaluate(
        is_confirmed=True,
        status=AttendanceStatus.ABSENT,
        is_reliable=True,
        has_professor_mapping=True,
        already_notified=True,
        subject_code="CS101",
        target_date=today,
        professor_email="prof@college.edu",
    )
    assert result.action == DecisionAction.NO_ACTION
    assert result.reason == DecisionReason.ALREADY_NOTIFIED
    assert not result.is_eligible


def test_rule_absent_confirmed_with_mapping_is_eligible() -> None:
    """Confirmed day + Reliable portal absence + Valid professor mapping + Not notified = ELIGIBLE."""
    today = date(2026, 9, 25)
    result = DecisionEngine.evaluate(
        is_confirmed=True,
        status=AttendanceStatus.ABSENT,
        is_reliable=True,
        has_professor_mapping=True,
        already_notified=False,
        subject_code="CS101",
        target_date=today,
        professor_email="prof@college.edu",
    )
    assert result.action == DecisionAction.ELIGIBLE_FOR_NOTIFICATION
    assert result.reason == DecisionReason.ABSENT_AND_CONFIRMED
    assert result.is_eligible
    assert result.professor_email == "prof@college.edu"


def test_evaluate_subject_record_from_database(db_session: Session) -> None:
    """Test evaluation using active database entities."""
    engine = DecisionEngine()
    today = date(2026, 9, 25)

    # 1. Subject exists with professor mapping
    subject = Subject(code="CS101", name="Python Programming")
    db_session.add(subject)
    db_session.flush()

    mapping = ProfessorMapping(
        subject_id=subject.id,
        professor_name="Prof. Turing",
        professor_email="turing@university.edu",
    )
    db_session.add(mapping)
    db_session.commit()

    # Step A: Not confirmed yet -> NO_ACTION
    res_a = engine.evaluate_subject_record(
        db=db_session,
        target_date=today,
        subject_code="CS101",
        status=AttendanceStatus.ABSENT,
        is_reliable=True,
    )
    assert res_a.action == DecisionAction.NO_ACTION
    assert res_a.reason == DecisionReason.ATTENDANCE_NOT_CONFIRMED

    # Step B: Confirm attendance
    db_session.add(AttendanceConfirmation(date=today))
    db_session.commit()

    # Step C: Confirmed -> Now ELIGIBLE_FOR_NOTIFICATION
    res_b = engine.evaluate_subject_record(
        db=db_session,
        target_date=today,
        subject_code="CS101",
        status=AttendanceStatus.ABSENT,
        is_reliable=True,
    )
    assert res_b.action == DecisionAction.ELIGIBLE_FOR_NOTIFICATION
    assert res_b.reason == DecisionReason.ABSENT_AND_CONFIRMED
    assert res_b.professor_email == "turing@university.edu"

    # Step D: Notification recorded -> Next check dedupes to NO_ACTION
    db_session.add(
        NotificationEvent(
            date=today,
            subject_id=subject.id,
            subject_code="CS101",
            recipient_email="turing@university.edu",
        )
    )
    db_session.commit()

    res_c = engine.evaluate_subject_record(
        db=db_session,
        target_date=today,
        subject_code="CS101",
        status=AttendanceStatus.ABSENT,
        is_reliable=True,
    )
    assert res_c.action == DecisionAction.NO_ACTION
    assert res_c.reason == DecisionReason.ALREADY_NOTIFIED

    # Step E: Unreliable absent in database evaluation must produce NO_ACTION
    # Even if confirmed, has mapping, and for a new subject not yet notified
    subject2 = Subject(code="CS102", name="Data Structures")
    db_session.add(subject2)
    db_session.flush()
    mapping2 = ProfessorMapping(
        subject_id=subject2.id,
        professor_name="Prof. Knuth",
        professor_email="knuth@university.edu",
    )
    db_session.add(mapping2)
    db_session.commit()

    res_d = engine.evaluate_subject_record(
        db=db_session,
        target_date=today,
        subject_code="CS102",
        status=AttendanceStatus.ABSENT,
        is_reliable=False,
    )
    assert res_d.action == DecisionAction.NO_ACTION
    assert res_d.reason == DecisionReason.UNRELIABLE_ATTENDANCE_RESULT
    assert not res_d.is_eligible


# ==============================================================================
# Mandatory Safety Invariant Tests (10 Conditions)
# ==============================================================================


def test_safety_case_1_confirmed_absent_reliable_with_mapping_not_notified() -> None:
    """1. confirmed + ABSENT + reliable + professor mapping + not notified => ELIGIBLE_FOR_NOTIFICATION."""
    today = date(2026, 9, 26)
    result = DecisionEngine.evaluate(
        is_confirmed=True,
        status=AttendanceStatus.ABSENT,
        is_reliable=True,
        has_professor_mapping=True,
        already_notified=False,
        subject_code="MATH201",
        target_date=today,
        professor_email="gauss@math.edu",
    )
    assert result.action == DecisionAction.ELIGIBLE_FOR_NOTIFICATION
    assert result.reason == DecisionReason.ABSENT_AND_CONFIRMED
    assert result.is_eligible
    assert result.is_reliable is True


def test_safety_case_2_confirmed_absent_unreliable_with_mapping_not_notified() -> None:
    """2. confirmed + ABSENT + unreliable + professor mapping + not notified => NO_ACTION."""
    today = date(2026, 9, 26)
    result = DecisionEngine.evaluate(
        is_confirmed=True,
        status=AttendanceStatus.ABSENT,
        is_reliable=False,
        has_professor_mapping=True,
        already_notified=False,
        subject_code="MATH201",
        target_date=today,
        professor_email="gauss@math.edu",
    )
    assert result.action == DecisionAction.NO_ACTION
    assert result.reason == DecisionReason.UNRELIABLE_ATTENDANCE_RESULT
    assert not result.is_eligible
    assert result.is_reliable is False


def test_safety_case_3_confirmed_unknown_unreliable() -> None:
    """3. confirmed + UNKNOWN + unreliable => NO_ACTION."""
    today = date(2026, 9, 26)
    result = DecisionEngine.evaluate(
        is_confirmed=True,
        status=AttendanceStatus.UNKNOWN,
        is_reliable=False,
        has_professor_mapping=True,
        already_notified=False,
        subject_code="MATH201",
        target_date=today,
        professor_email="gauss@math.edu",
    )
    assert result.action == DecisionAction.NO_ACTION
    assert not result.is_eligible
    assert result.is_reliable is False


def test_safety_case_4_confirmed_absent_reliable_missing_mapping() -> None:
    """4. confirmed + ABSENT + reliable + missing mapping => NO_ACTION."""
    today = date(2026, 9, 26)
    result = DecisionEngine.evaluate(
        is_confirmed=True,
        status=AttendanceStatus.ABSENT,
        is_reliable=True,
        has_professor_mapping=False,
        already_notified=False,
        subject_code="MATH201",
        target_date=today,
        professor_email=None,
    )
    assert result.action == DecisionAction.NO_ACTION
    assert result.reason == DecisionReason.MISSING_PROFESSOR_MAPPING
    assert not result.is_eligible


def test_safety_case_5_confirmed_absent_reliable_already_notified() -> None:
    """5. confirmed + ABSENT + reliable + already notified => NO_ACTION."""
    today = date(2026, 9, 26)
    result = DecisionEngine.evaluate(
        is_confirmed=True,
        status=AttendanceStatus.ABSENT,
        is_reliable=True,
        has_professor_mapping=True,
        already_notified=True,
        subject_code="MATH201",
        target_date=today,
        professor_email="gauss@math.edu",
    )
    assert result.action == DecisionAction.NO_ACTION
    assert result.reason == DecisionReason.ALREADY_NOTIFIED
    assert not result.is_eligible


def test_safety_case_6_no_confirmation_absent_reliable() -> None:
    """6. no confirmation + ABSENT + reliable => NO_ACTION."""
    today = date(2026, 9, 26)
    result = DecisionEngine.evaluate(
        is_confirmed=False,
        status=AttendanceStatus.ABSENT,
        is_reliable=True,
        has_professor_mapping=True,
        already_notified=False,
        subject_code="MATH201",
        target_date=today,
        professor_email="gauss@math.edu",
    )
    assert result.action == DecisionAction.NO_ACTION
    assert result.reason == DecisionReason.ATTENDANCE_NOT_CONFIRMED
    assert not result.is_eligible


def test_safety_case_7_present_reliable() -> None:
    """7. PRESENT + reliable => NO_ACTION."""
    today = date(2026, 9, 26)
    result = DecisionEngine.evaluate(
        is_confirmed=True,
        status=AttendanceStatus.PRESENT,
        is_reliable=True,
        has_professor_mapping=True,
        already_notified=False,
        subject_code="MATH201",
        target_date=today,
        professor_email="gauss@math.edu",
    )
    assert result.action == DecisionAction.NO_ACTION
    assert result.reason == DecisionReason.STATUS_PRESENT
    assert not result.is_eligible


def test_safety_case_8_portal_unavailable_fails_closed() -> None:
    """8. portal unavailable => NO_ACTION."""
    from app.adapters.base.adapter import PortalUnavailableError
    from app.adapters.fake.adapter import FakePortalAdapter, FakeScenario

    adapter = FakePortalAdapter(scenario=FakeScenario.PORTAL_UNAVAILABLE)
    today = date(2026, 9, 26)
    with pytest.raises(PortalUnavailableError):
        adapter.get_attendance_for_date(today)


def test_safety_case_9_malformed_response_fails_closed() -> None:
    """9. malformed response => NO_ACTION."""
    from app.adapters.fake.adapter import FakePortalAdapter, FakeScenario

    adapter = FakePortalAdapter(scenario=FakeScenario.MALFORMED_RESPONSE)
    today = date(2026, 9, 26)
    records = adapter.get_attendance_for_date(today)
    assert len(records) == 1
    rec = records[0]
    assert rec.status == AttendanceStatus.UNKNOWN
    assert rec.is_reliable is False

    # When evaluated by decision engine:
    result = DecisionEngine.evaluate(
        is_confirmed=True,
        status=rec.status,
        is_reliable=rec.is_reliable,
        has_professor_mapping=True,
        already_notified=False,
        subject_code=rec.subject_code,
        target_date=today,
        professor_email="prof@college.edu",
    )
    assert result.action == DecisionAction.NO_ACTION
    assert not result.is_eligible


def test_safety_case_10_ambiguous_response_fails_closed() -> None:
    """10. ambiguous response => NO_ACTION."""
    from app.adapters.fake.adapter import FakePortalAdapter, FakeScenario

    adapter = FakePortalAdapter(scenario=FakeScenario.AMBIGUOUS_RESPONSE)
    today = date(2026, 9, 26)
    records = adapter.get_attendance_for_date(today)
    assert len(records) == 1
    rec = records[0]
    assert rec.status == AttendanceStatus.UNKNOWN
    assert rec.is_reliable is False

    # When evaluated by decision engine:
    result = DecisionEngine.evaluate(
        is_confirmed=True,
        status=rec.status,
        is_reliable=rec.is_reliable,
        has_professor_mapping=True,
        already_notified=False,
        subject_code=rec.subject_code,
        target_date=today,
        professor_email="prof@college.edu",
    )
    assert result.action == DecisionAction.NO_ACTION
    assert not result.is_eligible


# ==============================================================================
# Mandatory Explicit Reliability Invariant Tests (No Implicit Default to True)
# ==============================================================================


def test_evaluate_requires_explicit_is_reliable() -> None:
    """DecisionEngine.evaluate() MUST NOT have a default for is_reliable.

    Omitting is_reliable must raise a TypeError, preventing any caller
    from receiving an implicit trusted result by accident.
    """
    today = date(2026, 9, 26)
    with pytest.raises(TypeError, match="is_reliable"):
        # Intentionally omitting is_reliable
        DecisionEngine.evaluate(  # type: ignore[call-arg]
            is_confirmed=True,
            status=AttendanceStatus.ABSENT,
            has_professor_mapping=True,
            already_notified=False,
            subject_code="CS101",
            target_date=today,
            professor_email="prof@college.edu",
        )


def test_evaluate_subject_record_requires_explicit_is_reliable(db_session: Session) -> None:
    """DecisionEngine.evaluate_subject_record() MUST NOT have a default for is_reliable.

    Omitting is_reliable must raise a TypeError.
    """
    engine = DecisionEngine()
    today = date(2026, 9, 26)
    with pytest.raises(TypeError, match="is_reliable"):
        # Intentionally omitting is_reliable
        engine.evaluate_subject_record(  # type: ignore[call-arg]
            db=db_session,
            target_date=today,
            subject_code="CS101",
            status=AttendanceStatus.ABSENT,
        )


def test_decision_result_requires_explicit_is_reliable() -> None:
    """DecisionResult dataclass MUST NOT default is_reliable to True."""
    today = date(2026, 9, 26)
    with pytest.raises(TypeError):
        from app.services.decision_engine import DecisionResult

        DecisionResult(  # type: ignore[call-arg]
            action=DecisionAction.NO_ACTION,
            reason=DecisionReason.ATTENDANCE_NOT_CONFIRMED,
            subject_code="CS101",
            target_date=today,
            is_confirmed=False,
            status=AttendanceStatus.ABSENT,
        )


def test_none_or_falsy_reliability_fails_closed() -> None:
    """Passing None or False for is_reliable must fail closed to NO_ACTION."""
    today = date(2026, 9, 26)
    result_false = DecisionEngine.evaluate(
        is_confirmed=True,
        status=AttendanceStatus.ABSENT,
        is_reliable=False,
        has_professor_mapping=True,
        already_notified=False,
        subject_code="CS101",
        target_date=today,
        professor_email="prof@college.edu",
    )
    assert result_false.action == DecisionAction.NO_ACTION
    assert result_false.reason == DecisionReason.UNRELIABLE_ATTENDANCE_RESULT
    assert not result_false.is_eligible

    result_none = DecisionEngine.evaluate(
        is_confirmed=True,
        status=AttendanceStatus.ABSENT,
        is_reliable=None,  # type: ignore[arg-type]
        has_professor_mapping=True,
        already_notified=False,
        subject_code="CS101",
        target_date=today,
        professor_email="prof@college.edu",
    )
    assert result_none.action == DecisionAction.NO_ACTION
    assert result_none.reason == DecisionReason.UNRELIABLE_ATTENDANCE_RESULT
    assert not result_none.is_eligible


def test_rule_cancelled_class_fails_closed_to_no_action() -> None:
    """If a class was cancelled on target date, it must produce NO_ACTION even if portal returned ABSENT."""
    today = date(2026, 9, 26)
    result = DecisionEngine.evaluate(
        is_confirmed=True,
        status=AttendanceStatus.ABSENT,
        is_reliable=True,
        has_professor_mapping=True,
        already_notified=False,
        subject_code="CS101",
        target_date=today,
        professor_email="prof@college.edu",
        is_cancelled=True,
    )
    assert result.action == DecisionAction.NO_ACTION
    assert result.reason == DecisionReason.CLASS_CANCELLED
    assert not result.is_eligible


def test_rule_holiday_fails_closed_to_no_action() -> None:
    """If target date is a holiday and not an extra class, it must produce NO_ACTION even if portal returned ABSENT."""
    today = date(2026, 9, 26)
    result = DecisionEngine.evaluate(
        is_confirmed=True,
        status=AttendanceStatus.ABSENT,
        is_reliable=True,
        has_professor_mapping=True,
        already_notified=False,
        subject_code="CS101",
        target_date=today,
        professor_email="prof@college.edu",
        is_holiday=True,
        is_extra=False,
    )
    assert result.action == DecisionAction.NO_ACTION
    assert result.reason == DecisionReason.HOLIDAY
    assert not result.is_eligible


def test_rule_holiday_with_extra_class_is_eligible() -> None:
    """If target date is a holiday BUT subject was an extra scheduled class, it can be eligible for notification."""
    today = date(2026, 9, 26)
    result = DecisionEngine.evaluate(
        is_confirmed=True,
        status=AttendanceStatus.ABSENT,
        is_reliable=True,
        has_professor_mapping=True,
        already_notified=False,
        subject_code="CS101",
        target_date=today,
        professor_email="prof@college.edu",
        is_holiday=True,
        is_extra=True,
    )
    assert result.action == DecisionAction.ELIGIBLE_FOR_NOTIFICATION
    assert result.reason == DecisionReason.ABSENT_AND_CONFIRMED
    assert result.is_eligible


def test_database_evaluation_with_holiday_and_cancellation(db_session: Session) -> None:
    """Database evaluation must respect Holiday and ClassException records."""
    from app.models.calendar import ClassException, ExceptionType, Holiday

    engine = DecisionEngine()
    today = date(2026, 10, 2)

    # 1. Subject with professor mapping and student confirmation
    subject = Subject(code="CS201", name="Algorithms")
    db_session.add(subject)
    db_session.flush()

    mapping = ProfessorMapping(
        subject_id=subject.id,
        professor_name="Prof. Cormen",
        professor_email="cormen@algorithms.edu",
    )
    db_session.add(mapping)
    db_session.add(AttendanceConfirmation(date=today))
    db_session.commit()

    # Step A: Regular day, confirmed, reliable ABSENT -> ELIGIBLE
    res_normal = engine.evaluate_subject_record(
        db=db_session,
        target_date=today,
        subject_code="CS201",
        status=AttendanceStatus.ABSENT,
        is_reliable=True,
    )
    assert res_normal.action == DecisionAction.ELIGIBLE_FOR_NOTIFICATION

    # Step B: Declare today as Holiday -> NO_ACTION (reason: HOLIDAY)
    holiday = Holiday(date=today, description="Gandhi Jayanti")
    db_session.add(holiday)
    db_session.commit()

    res_holiday = engine.evaluate_subject_record(
        db=db_session,
        target_date=today,
        subject_code="CS201",
        status=AttendanceStatus.ABSENT,
        is_reliable=True,
    )
    assert res_holiday.action == DecisionAction.NO_ACTION
    assert res_holiday.reason == DecisionReason.HOLIDAY
    assert not res_holiday.is_eligible

    # Step C: Add EXTRA class exception on holiday -> ELIGIBLE
    extra_exc = ClassException(
        subject_id=subject.id,
        date=today,
        exception_type=ExceptionType.EXTRA,
    )
    db_session.add(extra_exc)
    db_session.commit()

    res_extra = engine.evaluate_subject_record(
        db=db_session,
        target_date=today,
        subject_code="CS201",
        status=AttendanceStatus.ABSENT,
        is_reliable=True,
    )
    assert res_extra.action == DecisionAction.ELIGIBLE_FOR_NOTIFICATION
    assert res_extra.is_eligible

    # Step D: Cancel the class exception -> NO_ACTION (reason: CLASS_CANCELLED)
    db_session.delete(extra_exc)
    cancel_exc = ClassException(
        subject_id=subject.id,
        date=today,
        exception_type=ExceptionType.CANCELLED,
    )
    db_session.add(cancel_exc)
    db_session.commit()

    res_cancel = engine.evaluate_subject_record(
        db=db_session,
        target_date=today,
        subject_code="CS201",
        status=AttendanceStatus.ABSENT,
        is_reliable=True,
    )
    assert res_cancel.action == DecisionAction.NO_ACTION
    assert res_cancel.reason == DecisionReason.CLASS_CANCELLED
    assert not res_cancel.is_eligible


