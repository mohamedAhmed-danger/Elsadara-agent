from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone
from flask_login import UserMixin
from sqlalchemy import ForeignKeyConstraint, PrimaryKeyConstraint
from enum import Enum

db = SQLAlchemy()


class Status(Enum):
    PENDING = "Pending"
    REVIEWED = "Reviewed"
    ATTENDED = "Attended"
    NO_SHOW = "No Show"


class User(db.Model, UserMixin):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    password = db.Column(db.String(100), nullable=False)


class Laboratory(db.Model):
    __tablename__ = 'laboratories'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    location = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(200), nullable=True)

    # relationships
    subscription = db.relationship('Subscription', backref='laboratory', uselist=False, lazy=True)
    lab_services = db.relationship('LabService', backref='laboratory', lazy=True)
    pages = db.relationship('Page', backref='laboratory', lazy=True)
    lab_inquiries = db.relationship('Inquiry', backref='laboratory', lazy=True)


class LabService(db.Model):
    __tablename__ = 'lab_services'
    id = db.Column(db.Integer, primary_key=True)
    laboratory_id = db.Column(db.Integer, db.ForeignKey('laboratories.id'), nullable=False)#fk
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)
    duration = db.Column(db.Integer, nullable=False)
    patient_instructions = db.Column(db.TEXT, nullable=True)
    description = db.Column(db.TEXT, nullable=True)
    alias_name = db.Column(db.JSON, nullable=True)
    keywords = db.Column(db.JSON, nullable=True)


class Platform(db.Model):
    __tablename__ = 'platforms'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)

    # relationships
    pages = db.relationship('Page', backref='platform', lazy=True, cascade="all, delete-orphan")


# composite primary key for page_id and platform_id
class Page(db.Model):
    __tablename__ = 'pages'
    __table_args__ = (
        PrimaryKeyConstraint('page_id', 'platform_id'),
    )
    page_id = db.Column(db.String(100), nullable=False)
    token = db.Column(db.String(200), nullable=False)
    platform_id = db.Column(db.Integer, db.ForeignKey('platforms.id'), nullable=False)
    laboratory_id = db.Column(db.Integer, db.ForeignKey('laboratories.id'), nullable=False)

    # relationships
    clients = db.relationship('Client', backref='page', lazy=True, cascade="all, delete-orphan")


# composite primary key for sender_id, page_id, and platform_id
class Client(db.Model):
    __tablename__ = 'clients'
    __table_args__ = (
        PrimaryKeyConstraint('sender_id', 'page_id', 'platform_id'),
        ForeignKeyConstraint(
            ['page_id', 'platform_id'],
            ['pages.page_id', 'pages.platform_id']
        ),
    )
    sender_id = db.Column(db.String(100), nullable=False)
    page_id = db.Column(db.String(100), nullable=False)
    platform_id = db.Column(db.Integer, nullable=False)
    summary = db.Column(db.String(200), nullable=True)
    last_bot_reply = db.Column(db.String(200), nullable=True)
    chat_history = db.Column(db.JSON, nullable=False, default=list)  


class Booking(db.Model):
    __tablename__ = 'bookings'
    id = db.Column(db.Integer, primary_key=True)
    reference_id = db.Column(db.String(20), unique=True, nullable=True, index=True)
    name = db.Column(db.String(120), nullable=False)
    details = db.Column(db.Text)
    date = db.Column(db.String(100))
    phone_number = db.Column(db.String(50))
    status = db.Column(db.Enum(Status), default=Status.PENDING)
    booking_time = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    time = db.Column(db.String(20), nullable=True)
    comes_from = db.Column(db.String(100))
    address = db.Column(db.String(255), nullable=False)


class Inquiry(db.Model):
    __tablename__ = 'inquiries'
    id = db.Column(db.Integer, primary_key=True)
    laboratory_id = db.Column(db.Integer, db.ForeignKey('laboratories.id'), nullable=False)#fk
    prescription_img = db.Column(db.String(255), nullable=True)
    status = db.Column(db.Enum(Status), default=Status.PENDING)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    comes_from = db.Column(db.String(100))
    phone_number = db.Column(db.String(20))
    ocr_extracted_text = db.Column(db.Text)
    confidence_score = db.Column(db.Float)
    services_mentioned = db.Column(db.String(500))
    deleted_at = db.Column(db.DateTime, nullable=True)
    deletion_reason = db.Column(db.String(50), nullable=True)


class Complaint(db.Model):
    __tablename__ = 'complaints'
    id = db.Column(db.Integer, primary_key=True)
    phone_number = db.Column(db.String(20), nullable=False)
    complaint_text = db.Column(db.Text, nullable=False)
    status = db.Column(db.Enum(Status), default=Status.PENDING)  
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    comes_from = db.Column(db.String(100))


class Subscription(db.Model):
    __tablename__ = "subscriptions"
    id = db.Column(db.Integer, primary_key=True)
    laboratory_id = db.Column(db.Integer, db.ForeignKey('laboratories.id'), nullable=False, unique=True)#fk
    plan_name = db.Column(db.String(100), default="Standard", nullable=False)
    message_limit = db.Column(db.Integer, default=5000, nullable=False)
    message_used = db.Column(db.Integer, default=0, nullable=False)
    grace_limit = db.Column(db.Integer, default=50, nullable=False)
    estimated_cost = db.Column(db.Float, default=0.0, nullable=False)
    start_date = db.Column(db.DateTime)
    end_date = db.Column(db.DateTime)
    renew_count = db.Column(db.Integer, default=0, nullable=False)
    last_renewed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    is_active = db.Column(db.Boolean, default=True, nullable=False)


class Feedback(db.Model):
    __tablename__ = "feedbacks"
    id = db.Column(db.Integer, primary_key=True)
    reference_id = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(50), nullable=False)
    phone_number = db.Column(db.String(50), nullable=False)
    overall_rating = db.Column(db.Integer, nullable=False)
    ease_of_use = db.Column(db.Integer, nullable=False)
    feedback_text = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))