"""SQLAlchemy models — all tables include tenant_id for future multi-tenancy."""

from datetime import datetime, timezone
from typing import Optional

import bcrypt
from flask_login import UserMixin

from ..extensions import db

DEFAULT_TENANT = "default"


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# User (admin authentication)
# ---------------------------------------------------------------------------

class User(db.Model, UserMixin):
    __tablename__ = "users"

    id: int = db.Column(db.Integer, primary_key=True)
    username: str = db.Column(db.String(64), unique=True, nullable=False, index=True)
    password_hash: str = db.Column(db.String(256), nullable=False)
    role: str = db.Column(db.String(32), nullable=False, default="admin")
    created_at: datetime = db.Column(db.DateTime(timezone=True), default=_now)

    def set_password(self, password: str) -> None:
        self.password_hash = bcrypt.hashpw(
            password.encode(), bcrypt.gensalt(rounds=12)
        ).decode()

    def check_password(self, password: str) -> bool:
        return bcrypt.checkpw(password.encode(), self.password_hash.encode())

    def __repr__(self) -> str:
        return f"<User {self.username}>"


# ---------------------------------------------------------------------------
# BagQueue — uploaded bag photos (FIFO work queue)
# ---------------------------------------------------------------------------

class BagQueue(db.Model):
    __tablename__ = "bag_queue"

    id: int = db.Column(db.Integer, primary_key=True)
    tenant_id: str = db.Column(db.String(64), nullable=False, default=DEFAULT_TENANT, index=True)
    bag_name: str = db.Column(db.String(256), nullable=False)
    image_path: str = db.Column(db.String(512), nullable=False)  # Cloudinary URL after upload
    custom_prompt: Optional[str] = db.Column(db.Text, nullable=True)
    reference_url: Optional[str] = db.Column(db.String(1024), nullable=True)  # manual Pinterest URL
    status: str = db.Column(
        db.String(32), nullable=False, default="pending", index=True
    )
    # status values: pending | processing | done | rejected
    sort_order: int = db.Column(db.Integer, nullable=False, default=0)
    created_at: datetime = db.Column(db.DateTime(timezone=True), default=_now, index=True)
    processed_at: Optional[datetime] = db.Column(db.DateTime(timezone=True), nullable=True)

    approvals = db.relationship("PendingApproval", back_populates="bag", lazy="dynamic")

    def __repr__(self) -> str:
        return f"<BagQueue {self.bag_name} [{self.status}]>"


# ---------------------------------------------------------------------------
# PendingApproval — generated images awaiting Telegram review
# ---------------------------------------------------------------------------

class PendingApproval(db.Model):
    __tablename__ = "pending_approvals"

    id: int = db.Column(db.Integer, primary_key=True)
    tenant_id: str = db.Column(db.String(64), nullable=False, default=DEFAULT_TENANT, index=True)
    bag_queue_id: int = db.Column(db.Integer, db.ForeignKey("bag_queue.id"), nullable=False)

    reference_pin_id: Optional[str] = db.Column(db.String(256), nullable=True)
    reference_url: Optional[str] = db.Column(db.Text, nullable=True)
    generated_image_url: Optional[str] = db.Column(db.Text, nullable=True)
    prompt_used: Optional[str] = db.Column(db.Text, nullable=True)
    caption: Optional[str] = db.Column(db.Text, nullable=True)  # legacy free-form

    # AI-generated, admin-editable per-platform captions (Stage 6 extension)
    fb_caption: Optional[str] = db.Column(db.Text, nullable=True)
    ig_caption: Optional[str] = db.Column(db.Text, nullable=True)

    telegram_message_id: Optional[str] = db.Column(db.String(64), nullable=True, index=True)
    status: str = db.Column(
        db.String(32), nullable=False, default="pending", index=True
    )
    # status values: pending | approved | rejected | awaiting | posted

    regeneration_count: int = db.Column(db.Integer, nullable=False, default=0)
    scheduled_post_date: Optional[datetime] = db.Column(db.DateTime(timezone=True), nullable=True)

    created_at: datetime = db.Column(db.DateTime(timezone=True), default=_now, index=True)
    responded_at: Optional[datetime] = db.Column(db.DateTime(timezone=True), nullable=True)

    bag = db.relationship("BagQueue", back_populates="approvals")
    post_log = db.relationship("PostLog", back_populates="approval", uselist=False)

    def __repr__(self) -> str:
        return f"<PendingApproval id={self.id} status={self.status}>"


# ---------------------------------------------------------------------------
# PostLog — history of social media posts
# ---------------------------------------------------------------------------

class PostLog(db.Model):
    __tablename__ = "post_log"

    id: int = db.Column(db.Integer, primary_key=True)
    tenant_id: str = db.Column(db.String(64), nullable=False, default=DEFAULT_TENANT, index=True)
    approval_id: int = db.Column(
        db.Integer, db.ForeignKey("pending_approvals.id"), nullable=False
    )

    # Facebook
    fb_status: str = db.Column(db.String(16), nullable=False, default="skipped")
    fb_post_id: Optional[str] = db.Column(db.String(256), nullable=True)
    fb_error: Optional[str] = db.Column(db.Text, nullable=True)
    # status values: success | failed | skipped

    # Instagram
    ig_status: str = db.Column(db.String(16), nullable=False, default="skipped")
    ig_post_id: Optional[str] = db.Column(db.String(256), nullable=True)
    ig_error: Optional[str] = db.Column(db.Text, nullable=True)

    caption: Optional[str] = db.Column(db.Text, nullable=True)
    posted_at: datetime = db.Column(db.DateTime(timezone=True), default=_now, index=True)

    approval = db.relationship("PendingApproval", back_populates="post_log")

    def __repr__(self) -> str:
        return f"<PostLog id={self.id} posted_at={self.posted_at}>"


# ---------------------------------------------------------------------------
# RecentPinCache — prevents reusing recent Pinterest reference photos
# ---------------------------------------------------------------------------

class RecentPinCache(db.Model):
    __tablename__ = "recent_pin_cache"

    id: int = db.Column(db.Integer, primary_key=True)
    pin_id: str = db.Column(db.String(256), nullable=False)
    tenant_id: str = db.Column(db.String(64), nullable=False, default=DEFAULT_TENANT)
    used_at: datetime = db.Column(db.DateTime(timezone=True), default=_now, index=True)

    __table_args__ = (
        db.UniqueConstraint("pin_id", "tenant_id", name="uq_pin_tenant"),
    )

    def __repr__(self) -> str:
        return f"<RecentPinCache pin={self.pin_id}>"


# ---------------------------------------------------------------------------
# Settings — configurable key/value store per tenant
# ---------------------------------------------------------------------------

class Setting(db.Model):
    __tablename__ = "settings"

    id: int = db.Column(db.Integer, primary_key=True)
    key: str = db.Column(db.String(128), nullable=False)
    tenant_id: str = db.Column(db.String(64), nullable=False, default=DEFAULT_TENANT)
    value: Optional[str] = db.Column(db.Text, nullable=True)
    updated_at: datetime = db.Column(
        db.DateTime(timezone=True), default=_now, onupdate=_now
    )

    __table_args__ = (
        db.UniqueConstraint("key", "tenant_id", name="uq_setting_key_tenant"),
    )

    @classmethod
    def get(cls, key: str, tenant_id: str = DEFAULT_TENANT, default: str = "") -> str:
        row = cls.query.filter_by(key=key, tenant_id=tenant_id).first()
        return row.value if row and row.value is not None else default

    @classmethod
    def set(cls, key: str, value: str, tenant_id: str = DEFAULT_TENANT) -> None:
        row = cls.query.filter_by(key=key, tenant_id=tenant_id).first()
        if row:
            row.value = value
        else:
            db.session.add(cls(key=key, tenant_id=tenant_id, value=value))
        db.session.commit()

    def __repr__(self) -> str:
        return f"<Setting {self.key}={self.value!r}>"
