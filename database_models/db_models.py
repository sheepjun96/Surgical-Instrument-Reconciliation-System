from sqlalchemy import Column, Integer, String, DateTime, JSON, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime, timezone
from database import Base

class SurgicalSession(Base):
    __tablename__ = "surgical_sessions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    status = Column(String(50), default="WAITING_BEFORE")
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    # 수술 전 데이터
    before_original_url = Column(String(255), nullable=True)
    before_drawn_url = Column(String(255), nullable=True)
    before_captured_at = Column(String(100), nullable=True)
    before_counts = Column(JSON, default=dict)

    # 수술 후 데이터
    after_original_url = Column(String(255), nullable=True)
    after_drawn_url = Column(String(255), nullable=True)
    after_captured_at = Column(String(100), nullable=True)
    after_counts = Column(JSON, default=dict)