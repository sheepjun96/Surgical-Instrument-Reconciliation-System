from sqlalchemy import Column, Integer, String, DateTime, JSON, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from database import Base

class SurgicalSession(Base):
    __tablename__ = "surgical_sessions"

    id = Column(Integer, primary_key=True, index=True)
    status = Column(String(50), default="WAITING_BEFORE") # WAITING_BEFORE, WAITING_AFTER, COMPLETED
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime, nullable=True)
    
    final_comparison = Column(JSON, nullable=True) 

    captures = relationship("Capture", back_populates="session", cascade="all, delete-orphan")


class Capture(Base):
    __tablename__ = "captures"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("surgical_sessions.id"))
    phase = Column(String(20)) # 'BEFORE' 또는 'AFTER'
    
    original_image_path = Column(String(255), nullable=False)
    drawn_image_path = Column(String(255), nullable=True)
    
    rf_detr_raw = Column(JSON, nullable=True)
    point_raw = Column(JSON, nullable=True)
    
    merged_counts = Column(JSON, nullable=True)
    
    captured_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    session = relationship("SurgicalSession", back_populates="captures")