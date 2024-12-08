# payment.py

import requests
from variables import ADMIN_CHAT_ID,PREDEFINED_ADDRESSES
from database import (
    update_transaction,
    get_pending_transactions,
    add_subscription,
    users_collection,
    wallet_balances_collection,
    transactions_collection,
    crypto_prices_collection
)
from threading import Timer
from admin import notify_admin
from datetime import datetime
import time
from variables import CHANNEL_ID
from threading import Thread
import logging
from variables import ETHERSCAN_API_KEY, BSCSCAN_API_KEY,BACKUP_API_URL,CRYPTOCOMPARE_API_KEY,PRIMARY_API_URL
SUPPORTED_COINS = ["BTC", "ETH", "LTC", "BNB", "TRX", "USDT"]
COINGECKO_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "LTC": "litecoin",
    "BNB": "binancecoin",
    "TRX": "tron",
    "USDT": "tether",
}
logger = logging.getLogger(__name__)
def fetch_wallet_balance(coin, address):
    """Fetch the current balance of a wallet address for the specified coin."""
    try:
        if coin == "BTC":
            explorer_url = f"https://api.blockcypher.com/v1/btc/main/addrs/{address}/balance"
            response = requests.get(explorer_url)
            response.raise_for_status()
            data = response.json()
            balance = data.get("final_balance", 0) / 1e8  # Convert from satoshis to BTC
            return balance
    
        elif coin == "ETH":
            explorer_url = (
                f"https://api.etherscan.io/api?module=account&action=balance&address={address}"
                f"&tag=latest&apikey={ETHERSCAN_API_KEY}"
            )
            response = requests.get(explorer_url)
            response.raise_for_status()
            data = response.json()
            if data.get("status") != "1":
                logger.error(f"Etherscan API error: {data.get('message')}")
                return None
            balance = int(data.get("result", 0)) / 1e18  # Convert from Wei to ETH
            return balance

        elif coin == "LTC":
            explorer_url = f"https://api.blockcypher.com/v1/ltc/main/addrs/{address}/balance"
            response = requests.get(explorer_url)
            response.raise_for_status()
            data = response.json()
            balance = data.get("final_balance", 0) / 1e8  # Convert from litoshis to LTC
            return balance

        elif coin == "BNB":
            explorer_url = (
                f"https://api.bscscan.com/api?module=account&action=balance&address={address}"
                f"&tag=latest&apikey={BSCSCAN_API_KEY}"
            )
            response = requests.get(explorer_url)
            response.raise_for_status()
            data = response.json()
            if data.get("status") != "1":
                logger.error(f"BscScan API error: {data.get('message')}")
                return None
            balance = int(data.get("result", 0)) / 1e18  # Convert from Wei to BNB
            return balance

        elif coin == "TRX":
            explorer_url = f"https://api.trongrid.io/v1/accounts/{address}"
            response = requests.get(explorer_url)
            response.raise_for_status()
            data = response.json()
            balance = data.get("data", [{}])[0].get("balance", 0) / 1e6  # Convert from SUN to TRX
            return balance

        elif coin == "USDT_TRC20":
            explorer_url = f"https://apilist.tronscan.org/api/account?address={address}"
            response = requests.get(explorer_url)
            response.raise_for_status()
            if "application/json" in response.headers.get("Content-Type", ""):
                data = response.json()
                trc20_tokens = data.get("trc20token_balances", [])
                usdt_balance = 0
                for token in trc20_tokens:
                    if token.get("tokenid") == "Tether USD":
                        usdt_balance = int(token.get("balance", 0)) / 1e6  # Convert from SUN to USDT
                        break
                logger.info(f"USDT balance for {address}: {usdt_balance}")
                return usdt_balance
            else:
                logger.error(f"Invalid response received for USDT_TRC20: {response.text}")
                return None

        elif coin == "USDT_BEP20":
            # USDT on BEP20 (Binance Smart Chain)
            explorer_url = (
                f"https://api.bscscan.com/api?module=account&action=tokenbalance"
                f"&contractaddress=0x55d398326f99059ff775485246999027b3197955&address={address}"
                f"&tag=latest&apikey={BSCSCAN_API_KEY}"
            )
            response = requests.get(explorer_url)
            response.raise_for_status()
            data = response.json()
            if data.get("status") != "1":
                logger.error(f"BscScan API error: {data.get('message')}")
                return None
            balance = int(data.get("result", 0)) / 1e18  # Convert from Wei to USDT
            return balance
        else:
            logger.error(f"Unsupported coin type: {coin}")
            return None

    except requests.exceptions.RequestException as e:
        logger.error(f"HTTP error while fetching balance for {coin} at {address}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error while fetching balance for {coin} at {address}: {e}")
        return None
def update_wallet_balances():
        """Fetch and update the balances of all predefined wallet addresses."""
        while True:
            for coin, address in PREDEFINED_ADDRESSES.items():
                try:
                    current_balance = fetch_wallet_balance(coin, address)
                    if current_balance is not None:
                        wallet_balances_collection.update_one(
                            {"coin": coin, "address": address},
                            {
                                "$set": {
                                    "balance": current_balance,
                                    "last_updated": datetime.utcnow(),
                                }
                            },
                            upsert=True,
                        )
                        logger.info(f"Updated balance for {coin} ({address}): {current_balance}")
                except Exception as e:
                    logger.error(f"Error updating balance for {coin} ({address}): {e}")
            time.sleep(600)  # Update every 10 minutes

def monitor_payments(bot):
        """Continuously monitor pending transactions."""
        while True:
            pending_transactions = get_pending_transactions()
            logger.info(f"Checking {len(pending_transactions)} pending transactions.")
            for transaction in pending_transactions:
                try:
                    # Pass the bot (context) to check_payment
                    confirmed = check_payment(transaction, bot)
                    if confirmed:
                        user_id = transaction['user_id']
                        transaction_id = transaction['transaction_id']
                        logger.info(f"Transaction {transaction_id} confirmed for user {user_id}.")

                        # Notify the user about confirmation
                        try:
                            bot.send_message(
                                chat_id=user_id,
                                text=(
                                    f"✅ *Your payment for transaction {transaction_id} has been confirmed!*\n\n"
                                    f"Thank you for your purchase."
                                ),
                                parse_mode='Markdown'
                            )
                            # Delete the confirmed transaction from the database
                            update_transaction(transaction_id, "confirmed_tx_hash_placeholder")
                            # Optionally, you can implement a delete function if needed
                        except Exception as e:
                            logger.error(f"Failed to notify user {user_id}: {e}")
                except Exception as e:
                    logger.error(f"Error during payment check for transaction {transaction.get('_id')}: {e}")

            time.sleep(60)  # Check every minute
def initialize_wallet_balances():
    """Fetch and store initial balances for all predefined wallets on bot start."""
    for coin, address in PREDEFINED_ADDRESSES.items():
        try:
            current_balance = fetch_wallet_balance(coin, address)
            if current_balance is not None:
                # Update the wallet balance in the database
                wallet_balances_collection.update_one(
                    {"coin": coin, "address": address},
                    {"$set": {"balance": current_balance}},
                    upsert=True
                )
                logger.info(f"Initialized wallet balance for {coin} at {address}: {current_balance}")
            else:
                logger.error(f"Failed to initialize wallet balance for {coin} at {address}")
        except Exception as e:
            logger.error(f"Error initializing wallet balance for {coin} at {address}: {e}")

def check_payment(transaction, bot):
    """Check the payment status using blockchain explorer APIs."""
    coin = transaction['coin'].upper()
    address = PREDEFINED_ADDRESSES.get(coin)
    amount_usd = transaction['amount']  # Amount in USD
    transaction_id = transaction['_id']

    logger.info(
        f"Checking payment for Transaction ID: {transaction_id}, Coin: {coin}, Address: {address}, Amount (USD): {amount_usd}"
    )

    try:
        if not address:
            logger.warning(f"No predefined address found for coin: {coin}")
            return False

        # Fetch current price of the coin in USD
        crypto_prices = crypto_prices_collection.find_one({"type": "crypto_prices"})
        if not crypto_prices or "prices" not in crypto_prices:
            logger.error("Price data not available in the database.")
            return False

        prices = crypto_prices["prices"]
        if coin in ["USDT", "USDT_BEP20", "USDT_TRC20"]:
            crypto_price = 1.00  # USDT is always 1:1 with USD
        else:
            crypto_price = prices.get(coin)

        if crypto_price is None:
            logger.error(f"Price data for {coin} not available.")
            return False

        # Convert USD amount to equivalent cryptocurrency amount
        amount_crypto = amount_usd / crypto_price
        logger.info(f"Amount required in {coin}: {amount_crypto:.8f} (Price: {crypto_price:.2f} USD/{coin})")

        # Fetch current wallet balance
        current_balance = fetch_wallet_balance(coin, address)
        if current_balance is None:
            logger.error(f"Failed to fetch balance for {coin} at {address}.")
            return False

        # Fetch the old balance from the database
        wallet_balance = wallet_balances_collection.find_one({"coin": coin, "address": address})
        old_balance = wallet_balance.get("balance", 0) if wallet_balance else 0

        logger.info(f"Old balance: {old_balance:.8f}, Current balance: {current_balance:.8f}")

        # Calculate the expected new balance
        expected_new_balance = old_balance + amount_crypto

        # Validate the balance change
        if current_balance >= expected_new_balance:
            # Overpayment detected
            overpayment = current_balance - expected_new_balance
            if overpayment > 0:
                logger.info(
                    f"Transaction {transaction_id} includes an overpayment of {overpayment:.8f} {coin}."
                )

            # Update the wallet balance in the database
            wallet_balances_collection.update_one(
                {"coin": coin, "address": address},
                {"$set": {"balance": current_balance}},
                upsert=True
            )
            logger.info(f"Wallet balance updated for {coin} at {address}: {current_balance}")

            # Process the transaction
            return process_transaction(transaction, coin, address, bot)
        else:
            logger.warning(
                f"Balance change does not match transaction amount for {transaction_id}. "
                f"Expected new balance: {expected_new_balance:.8f}, Actual balance: {current_balance:.8f}."
            )
            return False

    except requests.exceptions.RequestException as e:
        logger.error(f"Error connecting to explorer API for {coin}: {e}")
    except ValueError as e:
        logger.error(f"Error parsing JSON response: {e}")
    except Exception as e:
        logger.error(f"Unexpected error while checking payment for transaction {transaction_id}: {e}")

    logger.warning(f"Payment not confirmed for transaction {transaction_id}.")
    return False


def process_transaction(transaction, coin, address, bot):
    """Process the transaction after confirmation."""
    transaction_id = transaction.get('_id')
    user_id = transaction.get('user_id')
    product_id = transaction.get('product_id')
    amount = transaction.get('amount')

    try:
        if not all([transaction_id, user_id, product_id, amount]):
            logger.error(f"Missing transaction details for Transaction ID: {transaction_id}. Aborting processing.")
            return False

        logger.info(f"Starting transaction processing for ID: {transaction_id}, User ID: {user_id}, Coin: {coin}.")

        # Fetch user information
        user_data = users_collection.find_one({"user_id": user_id})
        if not user_data:
            logger.error(f"User data not found for User ID: {user_id}. Aborting transaction processing.")
            return False
        username = user_data.get("username", "N/A")
        logger.info(f"User data fetched successfully for User ID: {user_id}, Username: {username}.")

        # Fetch transaction hash or other confirmation logic
        tx_hash = "ADD_YOUR_LOGIC_HERE_BRUH"  # Replace with actual logic to fetch the hash
        update_transaction(transaction_id, tx_hash)
        logger.info(f"Transaction hash updated for ID: {transaction_id}, TX Hash: {tx_hash}.")

        # Add subscription for the user
        duration = get_duration(product_id)
        if duration is None:
            logger.error(f"Invalid product ID: {product_id}. Cannot add subscription.")
            return False
        add_subscription(user_id, product_id, duration)
        logger.info(f"Subscription added for User ID: {user_id}, Product ID: {product_id}, Duration: {duration} days.")

        # Update wallet balance
        wallet_balance = wallet_balances_collection.find_one({"coin": coin, "address": address})
        if wallet_balance:
            updated_balance = wallet_balance['balance'] + amount
            wallet_balances_collection.update_one(
                {"coin": coin, "address": address},
                {"$set": {"balance": updated_balance}}
            )
            logger.info(f"Wallet balance updated for {coin} at {address}: {updated_balance}.")
        else:
            logger.warning(f"No wallet balance record found for {coin} at {address}. Creating new record.")
            wallet_balances_collection.insert_one(
                {"coin": coin, "address": address, "balance": amount}
            )

        # Notify admin
        admin_message = (
            f"✅ <b>Payment Automatically Confirmed</b>\n\n"
            f"👤 <b>User:</b> @{username} (ID: {user_id})\n"
            f"🛒 <b>Plan:</b> {product_id}\n"
            f"💰 <b>Amount:</b> {amount} {coin}\n"
            f"🏦 <b>Payment Address:</b> <code>{address}</code>\n"
            f"Payment has been successfully processed and subscription activated."
        )
        notify_admin(bot, admin_message, parse_mode="HTML")
        logger.info(f"Admin notified about transaction {transaction_id}.")

        # Notify channel about subscription sale
        sales_message = (
            f"🎉 <b>A subscription has been sold</b>\n\n"
            f"<b>Plan:</b> {product_id}\n"
            f"<b>Amount:</b> {amount}$ {coin}\n"
            f"📆 <b>Date:</b> {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )
        try:
            bot.send_message(chat_id=CHANNEL_ID, text=sales_message, parse_mode='HTML')
            logger.info(f"Subscription sale message sent to channel for transaction {transaction_id}.")
        except Exception as e:
            logger.error(f"Failed to send subscription sale message to channel: {e}")

        # Mark transaction as confirmed
        transactions_collection.update_one(
            {"_id": transaction_id},
            {"$set": {"status": "confirmed", "confirmed_at": datetime.utcnow()}}
        )
        logger.info(f"Transaction {transaction_id} marked as confirmed successfully.")

        return True

    except Exception as e:
        logger.error(f"Error processing transaction {transaction_id}: {e}")
        return False


def notify_admin(bot, message, parse_mode="HTML"):
        """Send a notification to the admin."""
        try:
            bot.send_message(
                chat_id=ADMIN_CHAT_ID,  # Admin's Telegram ID
                text=message,
                parse_mode=parse_mode
            )
            logger.info("Admin notified successfully.")
        except Exception as e:
            logger.error(f"Failed to notify admin: {e}")

def generate_wallet(coin):
        """Return a predefined wallet address for the specified coin."""
        try:
            address = PREDEFINED_ADDRESSES.get(coin)
            if address:
                logger.info(f"Using predefined address for {coin}: {address}")
                return address, None
            else:
                logger.warning(f"No predefined address found for {coin}.")
                return None, None
        except Exception as e:
            logger.error(f"Error fetching predefined address for {coin}: {e}")
            return None, None
def get_duration(product_id):
        """Return duration in days based on product ID."""
        if product_id == "coincraft_1w":
            return 7  # 1 week
        elif product_id == "coincraft_1m":
            return 30  # 1 month
        elif product_id == "coincraft_3m":
            return 90  # 3 months
        elif product_id == "coincraft_src":
            return None  # No duration for lifetime access
        else:
            logger.error(f"Invalid product ID: {product_id}. Cannot determine duration.")
            return None
def start_background_tasks(bot):
        """Start background threads for monitoring payments and updating balances."""
        # Start the wallet balance updater thread
        balance_updater_thread = Thread(target=update_wallet_balances, daemon=True)
        balance_updater_thread.start()
        logger.info("Started wallet balance updater thread.")

        # Start the payment monitor thread
        payment_monitor_thread = Thread(target=monitor_payments, args=(bot,), daemon=True)
        payment_monitor_thread.start()
        logger.info("Started payment monitor thread.")
def fetch_crypto_prices():
    """Fetch crypto prices from primary API with backup support."""
    prices = {}

    try:
        # Primary API
        logger.info("Fetching crypto prices from the primary API...")
        response = requests.get(
            PRIMARY_API_URL,
            params={
                "ids": ",".join([COINGECKO_IDS[coin] for coin in SUPPORTED_COINS if coin != "USDT"]),
                "vs_currencies": "usd"
            }
        )
        response.raise_for_status()
        data = response.json()

        for coin in SUPPORTED_COINS:
            if coin == "USDT":  # Set USDT price manually
                prices["USDT"] = 1.00
                prices["USDT_BEP20"] = 1.00
                prices["USDT_TRC20"] = 1.00
            else:
                coingecko_id = COINGECKO_IDS[coin]
                prices[coin] = data.get(coingecko_id, {}).get("usd", None)

        if not all(value is not None for key, value in prices.items() if "USDT" not in key):
            raise ValueError("Some prices are missing from the primary API response.")

        logger.info("Successfully fetched crypto prices from the primary API.")

    except (requests.exceptions.RequestException, ValueError) as e:
        logger.error(f"Primary API failed: {e}. Trying backup API...")

        try:
            # Backup API
            for coin in SUPPORTED_COINS:
                if "USDT" in coin:  # Handle USDT variants explicitly
                    prices["USDT"] = 1.00
                    prices["USDT_BEP20"] = 1.00
                    prices["USDT_TRC20"] = 1.00
                else:
                    response = requests.get(
                        BACKUP_API_URL,
                        params={
                            "fsym": coin,
                            "tsyms": "USD",
                            "api_key": CRYPTOCOMPARE_API_KEY
                        }
                    )
                    response.raise_for_status()
                    data = response.json()
                    prices[coin] = data.get("USD", None)

            if not all(value is not None for key, value in prices.items() if "USDT" not in key):
                raise ValueError("Some prices are missing from the backup API response.")

            logger.info("Successfully fetched crypto prices from the backup API.")

        except (requests.exceptions.RequestException, ValueError) as e:
            logger.error(f"Backup API also failed: {e}. Falling back to cached prices...")

            # Fetch last stored prices from the database as a fallback
            cached_prices = crypto_prices_collection.find_one({"type": "crypto_prices"})
            if cached_prices:
                prices = cached_prices.get("prices", {})
                logger.info("Using cached crypto prices as a fallback.")
            else:
                logger.error("No cached prices available. Unable to fetch crypto prices.")
                return None  # Fail gracefully

    # Save the fetched prices to the database
    crypto_prices_collection.update_one(
        {"type": "crypto_prices"},
        {"$set": {"prices": prices, "updated_at": datetime.utcnow()}},
        upsert=True
    )

    return prices

def schedule_price_updates():
    """Schedule the price fetching every 10 minutes."""
    fetch_crypto_prices()
    Timer(600, schedule_price_updates).start()  # 600 seconds = 10 minutes
