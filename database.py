# database.py
from pymongo import MongoClient
from variables import MONGODB_URI
import logging
from datetime import datetime, timedelta
import random
import string
logger = logging.getLogger(__name__)

# Initialize MongoDB client
client = MongoClient(MONGODB_URI)
db = client['coincraft_shop']

# Collections
users_collection = db['users']\

transactions_collection = db['transactions']
subscriptions_collection = db['subscriptions']
wallet_balances_collection = db["wallet_balances"]
crypto_prices_collection = db["crypto_prices"]
def generate_transaction_id(length=12):
    """Generate a unique random transaction ID."""
    while True:
        transaction_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))
        if not transactions_collection.find_one({"transaction_id": transaction_id}):
            logger.debug(f"Generated unique transaction ID: {transaction_id}")
            return transaction_id
        logger.warning(f"Collision detected for transaction ID: {transaction_id}. Regenerating...")

def add_user(user_id, username):
    """Add a new user to the database."""
    if not users_collection.find_one({"user_id": user_id}):
        users_collection.insert_one({
            "user_id": user_id,
            "username": username,
            "joined_at": datetime.utcnow()
        })
        logger.info(f"Added new user: {user_id} ({username})")
    else:
        logger.debug(f"User {user_id} already exists.")

def create_transaction(user_id, product_id, amount, coin, address):
    """Create a new transaction in the database."""
    transaction_id = generate_transaction_id()
    transaction = {
        "transaction_id": transaction_id,
        "user_id": user_id,
        "product_id": product_id,
        "amount": amount,
        "coin": coin,
        "address": address,
        "status": "pending",
        "created_at": datetime.utcnow()
    }
    transactions_collection.insert_one(transaction)
    logger.info(f"Created transaction {transaction_id} for user {user_id}.")
    return transaction_id

def update_transaction(transaction_id, tx_hash):
    """Update transaction with the latest transaction hash."""
    transactions_collection.update_one(
        {"transaction_id": transaction_id},
        {"$set": {"tx_hash": tx_hash, "updated_at": datetime.utcnow()}}
    )
    logger.info(f"Updated transaction {transaction_id} with tx_hash {tx_hash}.")

def get_pending_transactions():
    """Retrieve all pending transactions."""
    return list(transactions_collection.find({"status": "pending"}))
def add_subscription(user_id, product_id, duration_days):
    """Add a subscription for the user."""
    subscription = {
        "user_id": user_id,
        "product_id": product_id,
        "start_date": datetime.utcnow(),
    }

    if duration_days is not None:
        subscription["duration_days"] = duration_days
        subscription["end_date"] = datetime.utcnow() + timedelta(days=duration_days)
    else:
        subscription["duration_days"] = "Lifetime"
        subscription["end_date"] = None  # No end date for lifetime access

    subscriptions_collection.insert_one(subscription)
    logger.info(f"Added subscription for user {user_id} for product {product_id}.")
