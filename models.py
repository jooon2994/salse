from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import DateTime
from datetime import datetime

db = SQLAlchemy()

class User(db.Model):
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=False) # Telegram User ID
    first_name = db.Column(db.String(80), nullable=False)
    username = db.Column(db.String(80), nullable=True)
    phone_number = db.Column(db.String(20), nullable=True)
    status = db.Column(db.String(20), default='PENDING', nullable=False) # PENDING, APPROVED, ADMIN
    promo_code = db.Column(db.String(20), unique=True, nullable=True)
    unpaid_commission = db.Column(db.Float, default=0.0, nullable=False)
    created_at = db.Column(DateTime, default=datetime.utcnow)
    orders = db.relationship('Order', backref='salesperson', lazy=True)

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    price = db.Column(db.Float, nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    specs = db.Column(db.String(500), nullable=True)

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    salesperson_id = db.Column(db.BigInteger, db.ForeignKey('user.id'), nullable=False)
    product_name = db.Column(db.String(120), nullable=False)
    product_price = db.Column(db.Float, nullable=False)
    customer_name = db.Column(db.String(120), nullable=False)
    customer_phone = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), default='PENDING', nullable=False) # PENDING, COMPLETED, CANCELLED
    commission_earned = db.Column(db.Float, nullable=False)
    created_at = db.Column(DateTime, default=datetime.utcnow)