import os
import hmac
import hashlib
import json
import random
import string
from datetime import datetime
from urllib.parse import unquote, parse_qs

from dotenv import load_dotenv
from flask import Flask, abort, jsonify, render_template, request
from flask_cors import CORS
from telegram import Bot, Update, ReplyKeyboardMarkup, WebAppInfo
from telegram.ext import CallbackContext, CommandHandler, Dispatcher

from models import db, Order, Product, User

# --- App Initialization ---
load_dotenv()
app = Flask(__name__)

# --- Config ---
DEV_MODE = os.getenv("DEV_MODE", "False") == "True"
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
SALES_GROUP_ID = os.getenv("SALES_GROUP_ID")
COMMISSION_RATE = float(os.getenv("COMMISSION_RATE", 0.05))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

if DEV_MODE:
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///local.db')
    CORS(app) # Enable CORS for local development
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
    if not app.config['SQLALCHEMY_DATABASE_URI']:
        raise ValueError("No DATABASE_URL set for production environment")

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# --- Database & Bot Setup ---
db.init_app(app)
bot = Bot(token=TOKEN)
dispatcher = Dispatcher(bot, None, use_context=True)

# --- Helper Functions ---
def validate_telegram_data(init_data: str) -> dict:
    """Validates initData from Telegram Mini App."""
    try:
        encoded_data = parse_qs(init_data)
        data_check_string = unquote(init_data)

        # 1. Extract hash and sort data
        received_hash = encoded_data['hash'][0]
        data_check_string = '\n'.join(sorted([
            f"{k}={encoded_data[k][0]}" for k in encoded_data if k != 'hash'
        ]))

        # 2. Calculate secret key and HMAC
        secret_key = hmac.new("WebAppData".encode(), TOKEN.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

        # 3. Compare hashes
        if calculated_hash == received_hash:
            return json.loads(encoded_data['user'][0])
        else:
            return None
    except Exception:
        return None

def generate_promo_code(size=8, chars=string.ascii_uppercase + string.digits):
    """Generates a unique promo code."""
    while True:
        code = ''.join(random.choice(chars) for _ in range(size))
        if not User.query.filter_by(promo_code=code).first():
            return code

def notify_admin(message: str):
    """Sends a message to the admin."""
    try:
        bot.send_message(chat_id=ADMIN_ID, text=message)
    except Exception as e:
        print(f"Error notifying admin: {e}")

def notify_group(message: str):
    """Sends a message to the sales group."""
    if not SALES_GROUP_ID:
        print("SALES_GROUP_ID not set. Skipping group notification.")
        return
    try:
        bot.send_message(chat_id=SALES_GROUP_ID, text=message, parse_mode='HTML')
    except Exception as e:
        print(f"Error notifying sales group: {e}")

# --- Telegram Command Handlers ---
def start(update: Update, context: CallbackContext):
    """Handles the /start command."""
    telegram_user = update.effective_user
    user = User.query.get(telegram_user.id)

    if not user:
        new_user = User(
            id=telegram_user.id,
            first_name=telegram_user.first_name,
            username=telegram_user.username
        )
        db.session.add(new_user)
        db.session.commit()
        notify_admin(f"New user registered and is pending approval: {telegram_user.first_name} (@{telegram_user.username})")
    
    keyboard = [[{"text": "🚀 Launch Ahadu Market", "web_app": {"url": WEBHOOK_URL}}]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    update.message.reply_text("Welcome to Ahadu Market! Click the button below to open the app.", reply_markup=reply_markup)

# --- Web App Routes (Frontend) ---
@app.route('/')
def index():
    """Serves the main HTML file for the Mini App."""
    return render_template('index.html')

# --- API Routes (Backend for Mini App) ---
@app.route('/api/init', methods=['POST'])
def init_user():
    """Initial data endpoint for the Mini App."""
    init_data = request.json.get('initData')
    if not init_data:
        abort(400, 'Missing initData')

    tg_user_data = validate_telegram_data(init_data)
    if not tg_user_data:
        abort(403, 'Invalid initData')
        
    user_id = tg_user_data['id']
    user = User.query.get(user_id)
    if not user:
        abort(404, 'User not found in database')
        
    response_data = {'user': {
        'id': user.id,
        'first_name': user.first_name,
        'status': user.status,
        'phone_number': user.phone_number
    }}

    if user.status == 'APPROVED':
        response_data['products'] = [p.__dict__ for p in Product.query.order_by(Product.name).all()]
        for p in response_data['products']: p.pop('_sa_instance_state', None)
        
        response_data['my_orders'] = [o.__dict__ for o in Order.query.filter_by(salesperson_id=user.id).order_by(Order.created_at.desc()).all()]
        for o in response_data['my_orders']: o.pop('_sa_instance_state', None)

        leaderboard = db.session.query(
            User.first_name,
            db.func.sum(Order.product_price).label('total_sales')
        ).join(Order).filter(
            Order.status == 'COMPLETED',
            db.func.extract('month', Order.created_at) == datetime.utcnow().month,
            db.func.extract('year', Order.created_at) == datetime.utcnow().year
        ).group_by(User.id).order_by(db.desc('total_sales')).limit(10).all()
        response_data['leaderboard'] = [{'name': name, 'sales': sales} for name, sales in leaderboard]

    elif user.status == 'ADMIN':
        # Admins see everything
        response_data.update(get_admin_dashboard_data())

    return jsonify(response_data)

# --- (Continuation of app.py) ---
def get_admin_dashboard_data():
    """Helper to fetch all data for the admin dashboard."""
    # Approvals
    pending_users = User.query.filter_by(status='PENDING').all()
    # Orders
    pending_orders_q = Order.query.filter_by(status='PENDING').options(db.joinedload(Order.salesperson)).order_by(Order.created_at.desc()).all()
    pending_orders = []
    for o in pending_orders_q:
        order_dict = o.__dict__
        order_dict.pop('_sa_instance_state', None)
        order_dict['salesperson_name'] = o.salesperson.first_name
        pending_orders.append(order_dict)
    # Products
    products = [p.__dict__ for p in Product.query.order_by(Product.name).all()]
    for p in products: p.pop('_sa_instance_state', None)
    # Payouts
    salespeople = User.query.filter(User.status.in_(['APPROVED', 'ADMIN'])).all()
    payouts = []
    for s in salespeople:
        total_sales = db.session.query(db.func.sum(Order.product_price)).filter_by(salesperson_id=s.id, status='COMPLETED').scalar() or 0
        payouts.append({
            'id': s.id,
            'name': s.first_name,
            'total_sales': total_sales,
            'total_commission': total_sales * COMMISSION_RATE,
            'unpaid_commission': s.unpaid_commission
        })
    # Leaderboard
    leaderboard_q = db.session.query(
        User.first_name,
        db.func.sum(Order.product_price).label('total_sales')
    ).join(Order).filter(
        Order.status == 'COMPLETED',
        db.func.extract('month', Order.created_at) == datetime.utcnow().month,
        db.func.extract('year', Order.created_at) == datetime.utcnow().year
    ).group_by(User.id).order_by(db.desc('total_sales')).limit(10).all()
    leaderboard = [{'name': name, 'sales': sales} for name, sales in leaderboard_q]

    return {
        'pending_users': [{'id': u.id, 'first_name': u.first_name, 'username': u.username} for u in pending_users],
        'pending_orders': pending_orders,
        'products': products,
        'payouts': payouts,
        'leaderboard': leaderboard
    }

@app.route('/api/register', methods=['POST'])
def register_user():
    init_data = request.headers.get('X-Telegram-Init-Data')
    tg_user_data = validate_telegram_data(init_data)
    if not tg_user_data: abort(403)
    
    user = User.query.get(tg_user_data['id'])
    if not user or user.phone_number: abort(400) # Already registered or doesn't exist

    data = request.json
    user.phone_number = data.get('phone_number')
    user.first_name = data.get('first_name') # Allow updating name on registration
    db.session.commit()
    return jsonify({'status': 'ok', 'user_status': user.status})

@app.route('/api/sales', methods=['POST'])
def log_sale():
    init_data = request.headers.get('X-Telegram-Init-Data')
    tg_user_data = validate_telegram_data(init_data)
    if not tg_user_data: abort(403)
    
    user = User.query.get(tg_user_data['id'])
    if not user or user.status != 'APPROVED': abort(403)

    data = request.json
    product_id = data.get('productId')
    
    if product_id == 'other':
        product_name = data.get('other_product_name')
        product_price = float(data.get('other_product_price'))
    else:
        product = Product.query.get(int(product_id))
        if not product or product.quantity < 1:
            return jsonify({'error': 'Product out of stock or does not exist'}), 400
        product.quantity -= 1
        product_name = product.name
        product_price = product.price

    new_order = Order(
        salesperson_id=user.id,
        product_name=product_name,
        product_price=product_price,
        customer_name=data.get('customer_name'),
        customer_phone=data.get('customer_phone'),
        commission_earned=product_price * COMMISSION_RATE
    )
    db.session.add(new_order)
    db.session.commit()
    
    notify_admin(f"New Sale Pending Approval:\n\nSalesperson: {user.first_name}\nProduct: {product_name}\nPrice: ${product_price:,.2f}\nCustomer: {data.get('customer_name')}")
    
    return jsonify({'status': 'ok'}), 201


@app.route('/api/admin/approve_user/<int:user_id>', methods=['POST'])
def approve_user(user_id):
    # Auth check
    init_data = request.headers.get('X-Telegram-Init-Data')
    tg_user_data = validate_telegram_data(init_data)
    if not tg_user_data or tg_user_data['id'] != ADMIN_ID: abort(403)

    user_to_approve = User.query.get(user_id)
    if not user_to_approve or user_to_approve.status != 'PENDING': abort(404)

    user_to_approve.status = 'APPROVED'
    user_to_approve.promo_code = generate_promo_code()
    db.session.commit()

    # Notify the user
    welcome_message = (
        f"🎉 Congratulations, {user_to_approve.first_name}! You have been approved as a salesperson.\n\n"
        f"Your unique promo code is: <b>{user_to_approve.promo_code}</b>\n\n"
        "You can now access your portal to log sales and track your performance. Good luck!"
    )
    bot.send_message(chat_id=user_id, text=welcome_message, parse_mode='HTML')

    return jsonify(get_admin_dashboard_data())


@app.route('/api/admin/order/<int:order_id>', methods=['POST'])
def update_order(order_id):
    init_data = request.headers.get('X-Telegram-Init-Data')
    tg_user_data = validate_telegram_data(init_data)
    if not tg_user_data or tg_user_data['id'] != ADMIN_ID: abort(403)

    order = Order.query.get(order_id)
    if not order: abort(404)

    action = request.json.get('action') # 'approve' or 'reject'
    if action == 'approve':
        order.status = 'COMPLETED'
        # Add commission to salesperson's unpaid balance
        order.salesperson.unpaid_commission += order.commission_earned
        
        # Post celebration message to group chat
        group_message = (
            f"🎉 <b>New Sale!</b> 🎉\n\n"
            f"Sold by: {order.salesperson.first_name}\n"
            f"Item: {order.product_name}\n"
            f"Price: ${order.product_price:,.2f}\n\n"
            f"Great job, keep it up! 🚀"
        )
        notify_group(group_message)
        
    elif action == 'reject':
        order.status = 'CANCELLED'
        # If it was from inventory, restock it
        product = Product.query.filter_by(name=order.product_name).first()
        if product:
            product.quantity += 1
    else:
        abort(400, 'Invalid action')
        
    db.session.commit()
    return jsonify(get_admin_dashboard_data())


@app.route('/api/admin/product', methods=['POST', 'DELETE'])
def manage_product():
    init_data = request.headers.get('X-Telegram-Init-Data')
    tg_user_data = validate_telegram_data(init_data)
    if not tg_user_data or tg_user_data['id'] != ADMIN_ID: abort(403)

    if request.method == 'POST':
        data = request.json
        new_product = Product(
            name=data['name'],
            price=float(data['price']),
            quantity=int(data['quantity']),
            specs=data['specs']
        )
        db.session.add(new_product)
        db.session.commit()
    
    elif request.method == 'DELETE':
        product_id = request.args.get('id')
        product_to_delete = Product.query.get(product_id)
        if not product_to_delete: abort(404)
        db.session.delete(product_to_delete)
        db.session.commit()

    return jsonify(get_admin_dashboard_data())


@app.route('/api/admin/mark_paid/<int:user_id>', methods=['POST'])
def mark_paid(user_id):
    init_data = request.headers.get('X-Telegram-Init-Data')
    tg_user_data = validate_telegram_data(init_data)
    if not tg_user_data or tg_user_data['id'] != ADMIN_ID: abort(403)

    salesperson = User.query.get(user_id)
    if not salesperson: abort(404)
    
    salesperson.unpaid_commission = 0.0
    db.session.commit()

    return jsonify(get_admin_dashboard_data())


# --- Webhook Setup ---
# This part is for communication between Telegram servers and your Flask app
@app.route('/webhook', methods=['POST'])
def webhook():
    """Webhook endpoint to receive updates from Telegram."""
    update = Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return 'ok'

@app.route('/set_webhook', methods=['GET'])
def set_webhook():
    """A one-time route to set the webhook."""
    if not WEBHOOK_URL:
        return "WEBHOOK_URL not set in environment variables.", 500
    
    # We append '/webhook' to the base URL
    webhook_full_url = f"{WEBHOOK_URL.rstrip('/')}/webhook"
    
    success = bot.set_webhook(webhook_full_url)
    if success:
        return f"Webhook set to {webhook_full_url}"
    else:
        return "Webhook setup failed."

dispatcher.add_handler(CommandHandler('start', start))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        # Create admin user if it doesn't exist
        if not User.query.get(ADMIN_ID):
            admin_user = User(id=ADMIN_ID, first_name="Admin", status='ADMIN', promo_code='ADMIN')
            db.session.add(admin_user)
            db.session.commit()
            print(f"Admin user with ID {ADMIN_ID} created.")
            
    app.run(debug=DEV_MODE, host='0.0.0.0', port=int(os.getenv("PORT", 8000)))