from sqlalchemy import Column, Integer, String, JSON, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from .session import Base

class ValidationReportRecord(Base):
    __tablename__ = "validation_reports"

    id = Column(Integer, primary_key=True, index=True)
    endpoint = Column(String, index=True)
    method = Column(String)
    status_code = Column(Integer)
    validation_status = Column(String, index=True)
    severity = Column(String, nullable=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    expected_schema = Column(JSON, nullable=True)
    actual_schema = Column(JSON, nullable=True)

    differences = relationship("DifferenceRecord", back_populates="report", cascade="all, delete-orphan")

class DifferenceRecord(Base):
    __tablename__ = "differences"

    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(Integer, ForeignKey("validation_reports.id", ondelete="CASCADE"))
    issue_type = Column(String)
    severity = Column(String)
    location = Column(String)
    message = Column(String)
    expected = Column(String, nullable=True)
    actual = Column(String, nullable=True)

    report = relationship("ValidationReportRecord", back_populates="differences")


class AggregatedDriftRecord(Base):
    """
    Cumulative statistics tracking for recurring drift issues across time.
    Aggregates occurrences, first_seen, and last_seen timestamps per drift issue signature.
    """
    __tablename__ = "aggregated_drifts"

    id = Column(Integer, primary_key=True, index=True)
    endpoint = Column(String, index=True)
    method = Column(String)
    issue_type = Column(String, index=True)
    location = Column(String)
    message = Column(String)
    severity = Column(String)
    occurrence_count = Column(Integer, default=1)
    first_seen = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_seen = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    sample_expected = Column(String, nullable=True)
    sample_actual = Column(String, nullable=True)

