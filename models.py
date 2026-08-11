from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

# Initialize db in app.py

db = SQLAlchemy()

class EmergencyContact(db.Model):
    __tablename__ = 'emergency_contacts'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(120))
    role = db.Column(db.String(50))
    priority = db.Column(db.Integer, default=1)
    camera_zone = db.Column(db.String(50))

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'phone': self.phone,
            'email': self.email,
            'role': self.role,
            'priority': self.priority,
            'camera_zone': self.camera_zone,
        }

class AlertSetting(db.Model):
    __tablename__ = 'alert_settings'
    id = db.Column(db.Integer, primary_key=True)
    threshold = db.Column(db.Integer, nullable=False, default=50)  # default threshold
    notify_sms = db.Column(db.Boolean, default=False)
    notify_email = db.Column(db.Boolean, default=True)
    notify_whatsapp = db.Column(db.Boolean, default=False)
    cooldown_minutes = db.Column(db.Integer, default=5)  # cooldown between alerts

    def to_dict(self):
        return {
            'threshold': self.threshold,
            'notify_sms': self.notify_sms,
            'notify_email': self.notify_email,
            'notify_whatsapp': self.notify_whatsapp,
            'cooldown_minutes': self.cooldown_minutes,
        }

class AlertHistory(db.Model):
    __tablename__ = 'alert_history'
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    location = db.Column(db.String(100))
    camera_name = db.Column(db.String(100))
    crowd_count = db.Column(db.Integer)
    threshold = db.Column(db.Integer)
    severity = db.Column(db.String(20))
    contacts_json = db.Column(db.Text)  # JSON string of contacts involved

    def to_dict(self):
        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat(),
            'location': self.location,
            'camera_name': self.camera_name,
            'crowd_count': self.crowd_count,
            'threshold': self.threshold,
            'severity': self.severity,
            'contacts_json': self.contacts_json,
        }
class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)

    full_name = db.Column(db.String(100), nullable=False)

    username = db.Column(db.String(50), unique=True, nullable=False)

    email = db.Column(db.String(120), unique=True, nullable=False)

    phone = db.Column(db.String(20))

    password_hash = db.Column(db.String(255), nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # ---------- Forgot Password ----------

    otp = db.Column(db.String(6))

    otp_expiry = db.Column(db.DateTime)

    # -------------------------------------

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def generate_otp(self, otp):
        self.otp = otp
        self.otp_expiry = datetime.utcnow() + timedelta(minutes=5)

    def verify_otp(self, otp):

        if self.otp != otp:
            return False

        if self.otp_expiry is None:
            return False

        return datetime.utcnow() < self.otp_expiry

    def clear_otp(self):
        self.otp = None
        self.otp_expiry = None
