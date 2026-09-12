"""ORM mapping for the row-level writes.

Only the tables the application inserts into and updates are mapped. The
analytical reads (views, window functions, percentiles) stay as SQL in the
module that owns them -- an ORM adds nothing there.
"""
from sqlalchemy import (BigInteger, Boolean, DateTime, Float, ForeignKey, Integer,
                        Numeric, SmallInteger, String, func)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, mapped_column


class Base(DeclarativeBase):
    pass


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = {"schema": "pe"}

    id = mapped_column(BigInteger, primary_key=True)
    lead_id = mapped_column(String, nullable=False)
    created_at = mapped_column(DateTime(timezone=True), nullable=False)

    product_type = mapped_column(String)
    channel = mapped_column(String)
    device = mapped_column(String)
    partner = mapped_column(String)
    city = mapped_column(String)
    insurance_company = mapped_column(String)
    payment_type = mapped_column(String)

    price = mapped_column(Numeric(14, 2))
    discount_percent = mapped_column(Numeric(6, 2))
    expected_margin = mapped_column(Numeric(14, 2))
    days_to_policy_expiry = mapped_column(Integer)

    minutes_since_abandonment = mapped_column(Integer)
    sessions_last_7d = mapped_column(Integer)
    offer_views_last_7d = mapped_column(Integer)
    price_comparisons_last_7d = mapped_column(Integer)
    days_since_last_visit = mapped_column(Numeric(8, 2))
    has_previous_purchase = mapped_column(SmallInteger)
    visited_offer_page = mapped_column(SmallInteger)
    incoming_call_last_24h = mapped_column(SmallInteger)

    completed_purchase = mapped_column(SmallInteger)
    ingested_at = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModelVersion(Base):
    __tablename__ = "model_versions"
    __table_args__ = {"schema": "pe"}

    id = mapped_column(BigInteger, primary_key=True)
    version = mapped_column(String, nullable=False, unique=True)
    algorithm = mapped_column(String, nullable=False)
    is_active = mapped_column(Boolean, nullable=False, default=False)
    trained_at = mapped_column(DateTime(timezone=True), server_default=func.now())

    train_rows = mapped_column(Integer, nullable=False)
    valid_rows = mapped_column(Integer)
    test_rows = mapped_column(Integer, nullable=False)
    train_period_start = mapped_column(DateTime(timezone=True))
    train_period_end = mapped_column(DateTime(timezone=True))
    valid_period_start = mapped_column(DateTime(timezone=True))
    valid_period_end = mapped_column(DateTime(timezone=True))
    test_period_start = mapped_column(DateTime(timezone=True))
    test_period_end = mapped_column(DateTime(timezone=True))

    base_rate_train = mapped_column(Float)
    base_rate_valid = mapped_column(Float)
    base_rate_test = mapped_column(Float)

    hyperparams = mapped_column(JSONB, default=dict)
    feature_spec = mapped_column(JSONB, default=dict)
    metrics = mapped_column(JSONB, default=dict)
    selection_metrics = mapped_column(JSONB, default=dict)
    candidate_results = mapped_column(JSONB, default=list)
    feature_importance = mapped_column(JSONB, default=list)

    artifact_path = mapped_column(String, nullable=False)
    notes = mapped_column(String)


class Prediction(Base):
    __tablename__ = "predictions"
    __table_args__ = {"schema": "pe"}

    id = mapped_column(BigInteger, primary_key=True)
    lead_id = mapped_column(String, nullable=False)
    model_version = mapped_column(String, ForeignKey("pe.model_versions.version"),
                                  nullable=False)
    probability = mapped_column(Float, nullable=False)
    score = mapped_column(Integer, nullable=False)
    scored_at_age_minutes = mapped_column(Float, nullable=False)
    lead_created_at = mapped_column(DateTime(timezone=True))
    predicted_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    batch_id = mapped_column(String, nullable=False)


class JobRun(Base):
    __tablename__ = "job_runs"
    __table_args__ = {"schema": "pe"}

    id = mapped_column(BigInteger, primary_key=True)
    job_name = mapped_column(String, nullable=False)
    status = mapped_column(String, nullable=False)
    trigger = mapped_column(String, nullable=False)
    started_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at = mapped_column(DateTime(timezone=True))
    duration_ms = mapped_column(Integer)
    rows_processed = mapped_column(Integer)
    detail = mapped_column(JSONB, default=dict)
    error = mapped_column(String)


class MonitoringSnapshot(Base):
    __tablename__ = "monitoring_snapshots"
    __table_args__ = {"schema": "pe"}

    id = mapped_column(BigInteger, primary_key=True)
    captured_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    model_version = mapped_column(String)
    scored_leads = mapped_column(Integer)
    mean_probability = mapped_column(Float)
    p10_probability = mapped_column(Float)
    p90_probability = mapped_column(Float)
    observed_base_rate = mapped_column(Float)
    expected_base_rate = mapped_column(Float)
    detail = mapped_column(JSONB, default=dict)


class Segment(Base):
    __tablename__ = "segments"
    __table_args__ = {"schema": "pe"}

    model_version = mapped_column(String, ForeignKey("pe.model_versions.version",
                                                     ondelete="CASCADE"),
                                  primary_key=True)
    segment = mapped_column(Integer, primary_key=True)
    label = mapped_column(String, nullable=False)
    size = mapped_column(Integer, nullable=False)
    centroid = mapped_column(JSONB, default=dict)
    traits = mapped_column(JSONB, default=list)


class LeadSegment(Base):
    __tablename__ = "lead_segments"
    __table_args__ = {"schema": "pe"}

    lead_id = mapped_column(String, primary_key=True)
    model_version = mapped_column(String, ForeignKey("pe.model_versions.version",
                                                     ondelete="CASCADE"),
                                  primary_key=True)
    segment = mapped_column(Integer, nullable=False)
    x = mapped_column(Float)
    y = mapped_column(Float)
