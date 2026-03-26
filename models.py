"""
AI Receptionist — 数据库模型
SQLite持久化：预约、对话记录、统计
"""
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, Integer, String, Text, DateTime, Float, Boolean
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

Base = declarative_base()


class Appointment(Base):
    """预约记录"""
    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_name = Column(String(100), nullable=False)
    customer_phone = Column(String(20), nullable=False)
    service_type = Column(String(200), default="")
    vehicle_info = Column(String(200), default="")
    preferred_time = Column(String(50), default="")
    notes = Column(Text, default="")
    status = Column(String(20), default="pending")  # pending/confirmed/completed/cancelled
    source = Column(String(20), default="web")  # web/wecom/phone
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class Conversation(Base):
    """对话记录"""
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # user/assistant
    message = Column(Text, nullable=False)
    intent = Column(String(50), default="")
    source = Column(String(20), default="web")
    created_at = Column(DateTime, default=datetime.now)


class DailyStats(Base):
    """每日统计快照"""
    __tablename__ = "daily_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(String(10), nullable=False, unique=True, index=True)  # YYYY-MM-DD
    total_conversations = Column(Integer, default=0)
    total_appointments = Column(Integer, default=0)
    confirmed_appointments = Column(Integer, default=0)
    completed_appointments = Column(Integer, default=0)
    missed_intents = Column(Integer, default=0)  # unknown intent count
    avg_response_time_ms = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class ShopConfig(Base):
    """动态店铺配置（从JSON文件迁移到DB后使用）"""
    __tablename__ = "shop_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


# Database setup
def get_engine(db_url: str = "sqlite:///{}".format(os.path.join("/tmp" if os.getenv("VERCEL") else os.getcwd(), "ai_receptionist.db"))):
    """Create database engine."""
    return create_engine(db_url, echo=False)


def init_db(engine):
    """Create all tables."""
    Base.metadata.create_all(engine)


def get_session(engine):
    """Get a database session factory."""
    Session = sessionmaker(bind=engine)
    return Session()
