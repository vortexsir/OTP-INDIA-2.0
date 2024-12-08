# handlers.py
from datetime import datetime
import os
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, InputFile
from telegram.ext import CallbackContext
from database import add_subscription, create_transaction, transactions_collection, subscriptions_collection,users_collection
from variables import ADMIN_CHAT_ID, PRODUCT_PRICES
from payment import  fetch_crypto_prices, generate_wallet, get_duration
from admin import notify_admin
from bson.errors import InvalidId
from variables import BOTUSERNAME
import requests
from threading import Timer

from datetime import datetime, timedelta
logger = logging.getLogger(__name__)

def start_handler(update: Update, context: CallbackContext):
    """Handle the /start command with referral tracking."""
    user = update.effective_user
    args = context.args

    # Check if the user is banned
    if is_banned(user.id):
        update.message.reply_text("❌ You are banned from using this bot.")
        return

    # Handle referral link
    referrer_id = None
    if args and args[0].startswith("ref_"):
        try:
            referrer_id = int(args[0][4:])  # Extract referrer ID
            logger.info(f"User {user.id} joined with referral from {referrer_id}.")
        except ValueError:
            logger.warning(f"Invalid referral argument: {args[0]}.")

    # Add or update the user in the database
    user_data = users_collection.find_one({"user_id": user.id})
    if not user_data:
        # New user
        users_collection.insert_one({
            "user_id": user.id,
            "username": user.username,
            "referrals": 0,
            "referral_earnings": 0.0,
            "referred_by": referrer_id,
            "date_joined": datetime.utcnow(),
        })
        if referrer_id:
            # Increment the referrer's referral count
            users_collection.update_one(
                {"user_id": referrer_id},
                {"$inc": {"referrals": 1}}
            )
            logger.info(f"User {referrer_id} now has an additional referral.")
    else:
        # Existing user
        users_collection.update_one(
            {"user_id": user.id},
            {"$set": {"username": user.username}}  # Update username if changed
        )
        logger.info(f"Updated user info for {user.id}.")

    # Prepare the main menu
    keyboard = [
        [InlineKeyboardButton("💳 Buy Subscription", callback_data="buy_subscription")],
        [InlineKeyboardButton("📦 Buy Coincraft SRC", callback_data="buy_coincraft_src")],
        [InlineKeyboardButton("🔗 Get Referral Link", callback_data="get_referral_link")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Welcome message
    welcome_message = (
        f"🎉 <b>Welcome to Coincraft Shop!</b> 🎉\n\n"
        f"👤 <b>Your Username:</b> @{user.username or 'N/A'}\n"
        f"🆔 <b>Your User ID:</b> {user.id}\n\n"
        f"💡 <i>Choose a product to get started:</i>"
    )

    # Path to welcome image
    script_dir = os.path.dirname(os.path.abspath(__file__))
    image_path = os.path.join(script_dir, 'templates', 'welcome_image.jpg')

    try:
        if os.path.exists(image_path):
            with open(image_path, 'rb') as photo:
                update.message.reply_photo(
                    photo=photo,
                    caption=welcome_message,
                    reply_markup=reply_markup,
                    parse_mode='HTML'
                )
                logger.info(f"Sent welcome image to user {user.id}.")
        else:
            update.message.reply_text(welcome_message, reply_markup=reply_markup, parse_mode='HTML')
            logger.warning(f"Image {image_path} not found. Sent text message instead.")
    except Exception as e:
        logger.error(f"Error sending welcome message to user {user.id}: {e}")
        update.message.reply_text(
            "❌ An error occurred while processing your request. Please try again later.",
            parse_mode='HTML'
        )

def buy_subscription_handler(update: Update, context: CallbackContext):
    """Handle buying Coincraft Bot subscriptions."""
    user = update.effective_user

    # Check if the user is banned
    if is_banned(user.id):
        update.message.reply_text("❌ You are banned from using this bot.")
        return
    query = update.callback_query
    query.answer()
    keyboard = [
        [InlineKeyboardButton("🛠 Coincraft Bot", callback_data="product_coincraft_bot")],
        [InlineKeyboardButton("📦 Buy Coincraft SRC", callback_data="buy_coincraft_src")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_caption(
        caption="🛒 *Select the product you want to buy:*",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    logger.info(f"User {query.from_user.id} is selecting a product.")

def product_selection_handler(update: Update, context: CallbackContext):
    """Handle product selection and show payment options."""
    query = update.callback_query
    query.answer()

    if query.data.startswith("product_coincraft_bot"):
        keyboard = [
            [InlineKeyboardButton(f"1 Week - ${PRODUCT_PRICES['coincraft_1w']}", callback_data="pay_coincraft_1w")],
            [InlineKeyboardButton(f"1 Months - ${PRODUCT_PRICES['coincraft_1m']}", callback_data="pay_coincraft_1m")],
            [InlineKeyboardButton(f"3 Months - ${PRODUCT_PRICES['coincraft_3m']}", callback_data="pay_coincraft_3m")],
            [InlineKeyboardButton("🔙 Back", callback_data="buy_subscription")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_caption(
            caption="🛠 *Coincraft Bot Subscription*\n\n*Choose a duration:*",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        logger.info(f"User {query.from_user.id} selected Coincraft Bot subscription.")
    elif query.data == "buy_coincraft_src":
        keyboard = [
            [InlineKeyboardButton(f"💵 Buy Now - ${PRODUCT_PRICES['coincraft_src']}", callback_data="pay_coincraft_src")],
            [InlineKeyboardButton("🔙 Back", callback_data="buy_subscription")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_caption(
            caption=f"📦 *Coincraft SRC Selected*\n\n*Price: ${PRODUCT_PRICES['coincraft_src']}*\n\nPlease proceed to payment:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        logger.info(f"User {query.from_user.id} selected Coincraft SRC.")
    elif query.data == "cancel":
        query.edit_message_caption("❌ *Operation Cancelled.*", parse_mode='Markdown')
        logger.info(f"User {query.from_user.id} cancelled the operation.")

def payment_selection_handler(update: Update, context: CallbackContext):
    """Handle payment method selection and create invoice."""
    user = update.effective_user

    query = update.callback_query
    query.answer()
    data = query.data.split("_")

    # Check if the user is banned
    if is_banned(user.id):
        query.edit_message_text("❌ You are banned from using this bot.")
        logger.warning(f"Banned user {user.id} attempted to access the bot.")
        return

    # Validate callback data
    if len(data) < 3:
        query.edit_message_caption("❌ Invalid product selected.", parse_mode='HTML')
        logger.warning(f"Invalid callback data received: {data}")
        return

    product_id = f"{data[1]}_{data[2]}"
    amount = PRODUCT_PRICES.get(product_id)

    if not amount:
        query.edit_message_caption("❌ Invalid product selected.", parse_mode='HTML')
        logger.warning(f"Product ID '{product_id}' not found in PRODUCT_PRICES.")
        return

    # Store selected product in user data
    context.user_data['product_id'] = product_id
    logger.info(f"User {query.from_user.id} selected product {product_id}.")

    # Fetch user referral rewards
    user_rewards = get_user_rewards(user.id)
    redeem_available = user_rewards >= amount

    # Define inline buttons for payment options
    keyboard_buttons = [
        InlineKeyboardButton("BTC 🪙", callback_data="coin_BTC"),
        InlineKeyboardButton("ETH 🪙", callback_data="coin_ETH"),
        InlineKeyboardButton("LTC 🪙", callback_data="coin_LTC"),
        InlineKeyboardButton("BNB 🪙", callback_data="coin_BNB"),
        InlineKeyboardButton("TRX 🪙", callback_data="coin_TRX"),
        InlineKeyboardButton("USDT (TRC20) 🪙", callback_data="coin_USDT_TRC20"),
        InlineKeyboardButton("USDT (BEP20) 🪙", callback_data="coin_USDT_BEP20"),
    ]

    # Add "Redeem Rewards" option if the user has enough rewards
    if redeem_available:
        keyboard_buttons.append(InlineKeyboardButton("🎁 Redeem Rewards", callback_data="redeem_rewards"))

    # Add back button
    keyboard_buttons.append(InlineKeyboardButton("🔙 Back", callback_data="buy_subscription"))

    # Arrange buttons in a grid layout
    reply_markup = InlineKeyboardMarkup([
        [keyboard_buttons[0], keyboard_buttons[1], keyboard_buttons[2]],
        [keyboard_buttons[3], keyboard_buttons[4], keyboard_buttons[5]],
        [keyboard_buttons[6], keyboard_buttons[7], keyboard_buttons[8]] if redeem_available else [keyboard_buttons[6], keyboard_buttons[7]],
    ])

    query.edit_message_caption(
        caption=(
            "💰 <b>Select your payment method:</b>\n\n"
            f"💸 <b>Product:</b> {product_id}\n"
            f"💵 <b>Price:</b> ${amount}\n"
            f"🎁 <b>Available Rewards:</b> ${user_rewards:.2f}"
        ),
        reply_markup=reply_markup,
        parse_mode='HTML'
    )
    logger.info(f"Displayed payment selection menu to user {query.from_user.id}.")

def get_user_rewards(user_id):
    user_data = users_collection.find_one({"user_id": user_id})
    if user_data and "referral_earnings" in user_data:
        return float(user_data["referral_earnings"])
    return 0.0

def coin_selection_handler(update: Update, context: CallbackContext):
    """Handle cryptocurrency selection and ask for confirmation before creating an invoice or redeeming rewards."""
    user = update.effective_user

    # Check if the user is banned
    if is_banned(user.id):
        update.callback_query.edit_message_text("❌ You are banned from using this bot.")
        logger.warning(f"Banned user {user.id} attempted to use the bot.")
        return

    query = update.callback_query
    query.answer()
    data = query.data.split("_")
    logger.info(f"Coin selection callback data: {data}")

    # Validate callback data
    if len(data) < 2:
        query.edit_message_caption("❌ Invalid selection. Please try again.", parse_mode="HTML", reply_markup=None)
        logger.warning("Coin selection callback data is incomplete.")
        return

    option = data[1].upper()

    if option == "REDEEM":
        # Handle redeem rewards option
        referral_rewards = get_user_rewards(user.id)  # Function to fetch referral rewards from the database
        if referral_rewards <= 0:
            query.edit_message_text(
                "❌ You don't have enough referral rewards to redeem.",
                parse_mode="HTML"
            )
            logger.info(f"User {user.id} tried to redeem rewards with insufficient balance.")
            return

        # Display redeemable plans
        redeemable_plans = {
            f"coincraft_1w: ${PRODUCT_PRICES['coincraft_1w']}", 
            f"coincraft_1m: ${PRODUCT_PRICES['coincraft_1m']}",
            f"coincraft_3m: ${PRODUCT_PRICES['coincraft_3m']}",
        }

        redeem_message = (
            f"🎉 <b>You have ${referral_rewards:.2f} in referral rewards!</b>\n\n"
            "You can use your rewards to redeem the following subscription plans:\n\n"
            + "\n".join([f"• <b>{plan}</b>: ${price}" for plan, price in redeemable_plans.items()]) +
            "\n\nReply with the plan you'd like to redeem (e.g., <code>coincraft_1m</code>)."
        )
        context.user_data.update({
            "redeemable_rewards": referral_rewards,
            "available_plans": redeemable_plans
        })

        query.edit_message_text(redeem_message, parse_mode="HTML")
        logger.info(f"Displayed redeemable plans to user {user.id}.")
        return

    # Process selected coin for payment
    coin = option
    variant = data[2].upper() if len(data) > 2 else None
    selected_coin = f"{coin}_{variant}" if variant else coin

    product_id = context.user_data.get("product_id")
    amount = PRODUCT_PRICES.get(product_id)
    user_id = query.from_user.id

    # Validate product and amount
    if not product_id or not amount:
        query.edit_message_caption("❌ Invalid payment process. Please try again.", parse_mode="HTML")
        logger.warning(f"Product ID '{product_id}' not found or invalid in PRODUCT_PRICES.")
        return

    # Save user selection in context
    context.user_data.update({
        'selected_coin': selected_coin,
        'selected_amount': amount,
        'selected_product_id': product_id
    })

    # Ask for confirmation
    confirmation_message = (
        f"💰 <b>Confirm Payment</b>\n\n"
        f"🛒 <b>Product:</b> {product_id}\n"
        f"💸 <b>Amount:</b> ${amount}\n"
        f"💱 <b>Payment Method:</b> {selected_coin}\n\n"
        "🔍 <b>Do you want to proceed with the payment?</b>"
    )
    keyboard = [
        [InlineKeyboardButton("✅ Confirm", callback_data="confirm_payment")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_payment")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        query.edit_message_caption(
            caption=confirmation_message,
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
        logger.info(f"Requested payment confirmation from user {user_id} for {product_id} using {selected_coin}.")
    except Exception as e:
        logger.error(f"Failed to send payment confirmation message to user {user_id}: {e}")
        query.edit_message_text("❌ An error occurred. Please try again later.")

def i_have_paid_handler(update: Update, context: CallbackContext):
    """Handle the 'I have paid' button click."""
    user = update.effective_user

    # Check if the user is banned
    if is_banned(user.id):
        update.message.reply_text("❌ You are banned from using this bot.")
        return
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    transaction_id = context.user_data.get('transaction_id')

    logger.info(f"User {user_id} clicked 'I have paid' for transaction {transaction_id}.")

    if not transaction_id:
        query.edit_message_caption("❌ *No pending transaction found.*", parse_mode='Markdown')
        logger.warning(f"No transaction ID found in user data for user {user_id}.")
        return

    try:
        transaction = transactions_collection.find_one({"transaction_id": transaction_id, "user_id": user_id})
    except InvalidId:
        transaction = None

    if not transaction:
        query.edit_message_caption("❌ *Transaction not found. Please contact support.*", parse_mode='Markdown')
        logger.warning(f"Transaction {transaction_id} not found for user {user_id}.")
        return

    if transaction['status'] == 'confirmed':
        query.edit_message_caption("✅ *Payment already confirmed. Thank you!*", parse_mode='Markdown')
        logger.info(f"Payment already confirmed for transaction {transaction_id}.")
        return

    # Notify admin about the payment confirmation request
    admin_message = (
        f"🔔 *Payment Action Detected* 🔔\n\n"
        f"👤 *User ID:* {user_id}\n"
        f"🆔 *Transaction ID:* `{transaction_id}`\n"
        f"💰 *Amount:* ${transaction['amount']} {transaction['coin']}\n"
        f"🏦 *Wallet Address:* `{transaction['address']}`\n\n"
        "🔍 *User has clicked 'I have paid'. Please verify the payment.*"
    )
    notify_admin(context.bot, admin_message, parse_mode='Markdown')
    logger.info(f"Admin notified about payment confirmation request for transaction {transaction_id} by user {user_id}.")

    # Confirm to the user
    query.edit_message_caption(
        "✅ *Payment is being verified. Our team will review it shortly. Thank you!*",
        parse_mode='Markdown'
    )


def cancel_handler(update: Update, context: CallbackContext):
    """Handle cancellation."""
        # Check if the user is banned
    user = update.effective_user
    if is_banned(user.id):
        update.message.reply_text("❌ You are banned from using this bot.")
        return
    query = update.callback_query
    query.answer()

    query.edit_message_caption("❌ *Operation Cancelled.*", parse_mode='Markdown')
    logger.info(f"User {query.from_user.id} cancelled the operation.")

    # Clear context data for clean-up
    context.user_data.clear()

    logger.info(f"User {query.from_user.id} cancelled the operation.")
def confirm_payment_callback(update: Update, context: CallbackContext):
    """Handle the inline callback to confirm the payment."""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id

    # Fetch necessary data from user context
    selected_coin = context.user_data.get('selected_coin')
    selected_amount_usd = context.user_data.get('selected_amount')  # Amount in USD
    product_id = context.user_data.get('selected_product_id')

    if not selected_coin or not selected_amount_usd or not product_id:
        query.edit_message_caption("❌ Payment details are missing. Please start again.", parse_mode="HTML")
        logger.warning(f"User {user_id} attempted to confirm payment with incomplete details.")
        return

    # Update market exchange rate for the selected coin
    logger.info(f"Fetching market price for {selected_coin}...")
    crypto_prices = fetch_crypto_prices()  # Ensure `fetch_crypto_prices` is properly defined
    if not crypto_prices:
        query.edit_message_caption(
            "❌ Unable to fetch market prices. Please try again later.",
            parse_mode="HTML"
        )
        logger.error("Market prices are unavailable.")
        return

    if selected_coin not in crypto_prices:
        query.edit_message_caption(
            f"❌ Market price for <b>{selected_coin}</b> is unavailable. Please try again later.",
            parse_mode="HTML"
        )
        logger.error(f"Market price for {selected_coin} not found in fetched prices.")
        return

    # Calculate the equivalent cryptocurrency amount
    crypto_price = crypto_prices[selected_coin]  # Price in USD
    try:
        amount_crypto = selected_amount_usd / crypto_price
    except ZeroDivisionError:
        query.edit_message_caption(
            "❌ Market price for the selected cryptocurrency is zero. Please try again later.",
            parse_mode="HTML"
        )
        logger.error(f"Market price for {selected_coin} is zero. Cannot calculate equivalent amount.")
        return

    logger.info(f"User {user_id} needs to pay {amount_crypto:.8f} {selected_coin} for {selected_amount_usd:.2f} USD.")

    # Generate the predefined wallet address
    wallet_address, _ = generate_wallet(selected_coin)
    if not wallet_address:
        query.edit_message_caption(
            f"❌ Payment method <b>{selected_coin}</b> not supported.",
            parse_mode="HTML"
        )
        logger.warning(f"No wallet address found for coin {selected_coin}.")
        return

    # Create a transaction record
    transaction_id = create_transaction(user_id, product_id, selected_amount_usd, selected_coin, wallet_address)
    context.user_data['transaction_id'] = transaction_id

    # Notify admin about the new invoice
    admin_message = (
        "📄 <b>New Invoice Created</b>\n\n"
        f"👤 <b>User ID:</b> {user_id}\n"
        f"🛒 <b>Product:</b> {product_id}\n"
        f"💰 <b>Amount:</b> {selected_amount_usd:.2f} USD ({amount_crypto:.8f} {selected_coin})\n"
        f"🏦 <b>Wallet Address:</b> <code>{wallet_address}</code>\n"
        f"🆔 <b>Transaction ID:</b> <code>{transaction_id}</code>"
    )
    notify_admin(context.bot, admin_message, parse_mode="HTML")
    logger.info(f"Admin notified about new invoice {transaction_id} for user {user_id}.")

    # Display payment instructions to the user
    payment_message = (
        "💰 <b>Invoice Generated</b>\n\n"
        f"🔗 <b>Wallet Address:</b> <code>{wallet_address}</code>\n"
        f"💸 <b>Amount:</b> {amount_crypto:.8f} {selected_coin}\n\n"
        "📥 <b>Please send the specified amount to the above address.</b>\n"
        "Once the payment is complete, click the <b>'I have paid'</b> button below."
    )
    keyboard = [
        [InlineKeyboardButton("✅ I have paid", callback_data="i_have_paid")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    query.edit_message_caption(
        caption=payment_message,
        parse_mode="HTML",
        reply_markup=reply_markup
    )
    logger.info(f"Payment instructions sent to user {user_id} for transaction {transaction_id}.")

def cancel_payment_handler(update: Update, context: CallbackContext):
    """Handle the cancellation of a payment process."""
    user = update.effective_user

    # Check if the user initiated the payment process
    if 'selected_product_id' not in context.user_data:
        update.callback_query.answer("❌ No active payment process to cancel.", show_alert=True)
        logger.warning(f"User {user.id} attempted to cancel a non-existent payment process.")
        return

    query = update.callback_query
    query.answer()

    # Clear context data related to the payment
    context.user_data.pop('selected_product_id', None)
    context.user_data.pop('selected_coin', None)
    context.user_data.pop('selected_amount', None)

    # Inform the user that the payment process has been canceled
    try:
        query.edit_message_caption(
            caption="❌ Payment process has been canceled. You can start again if needed.",
            parse_mode="HTML"
        )
        logger.info(f"User {user.id} canceled the payment process.")
    except Exception as e:
        logger.error(f"Failed to update cancellation message for user {user.id}: {e}")
        query.edit_message_text("❌ An error occurred while canceling. Please try again later.")

def confirm_transaction_handler(update: Update, context: CallbackContext):
    """Admin command to confirm a transaction."""
    user = update.effective_user

    # Check if the user is banned
    if is_banned(user.id):
        update.message.reply_text("❌ You are banned from using this bot.")
        return

    # Check if the user is authorized (Admin only)
    if user.id != ADMIN_CHAT_ID:
        update.message.reply_text("❌ You are not authorized to use this command.")
        return

    # Parse the command arguments
    message = update.message.text
    args = message.split()

    if len(args) != 2:
        update.message.reply_text("❌ Usage: /confirm <transaction_id>", parse_mode='Markdown')
        logger.warning(f"Admin provided invalid usage for /confirm: {message}")
        return

    transaction_id = args[1]

    # Fetch the transaction from the database
    transaction = transactions_collection.find_one({"transaction_id": transaction_id})

    if not transaction:
        update.message.reply_text("⚠️ Transaction not found.", parse_mode='Markdown')
        logger.warning(f"Admin attempted to confirm non-existent transaction {transaction_id}.")
        return

    if transaction.get('status') == 'confirmed':
        update.message.reply_text("✅ Transaction already confirmed.", parse_mode='Markdown')
        logger.info(f"Admin attempted to reconfirm already confirmed transaction {transaction_id}.")
        return

    # Update the transaction status to confirmed
    try:
        transactions_collection.update_one(
            {"transaction_id": transaction_id},
            {"$set": {"status": "confirmed", "confirmed_at": datetime.utcnow()}}
        )
        logger.info(f"Transaction {transaction_id} status updated to confirmed.")
    except Exception as e:
        update.message.reply_text("❌ Failed to update transaction status.", parse_mode='Markdown')
        logger.error(f"Error updating transaction status for {transaction_id}: {e}")
        return

    # Handle subscription creation or file delivery
    product_id = transaction['product_id']
    user_id = transaction['user_id']
    amount = transaction.get('amount', 0)
    try:
        if product_id == "coincraft_src":
            # Send the Coincraft SRC file to the user
            file_path = "templates/coincraft_src.rar"  # Path to the file
            if os.path.exists(file_path):
                with open(file_path, "rb") as file:
                    context.bot.send_document(
                        chat_id=user_id,
                        document=InputFile(file),
                        caption="✅ *Thank you for purchasing Coincraft SRC!*\n\nHere is your file.",
                        parse_mode='Markdown'
                    )
                logger.info(f"Sent Coincraft SRC file to user {user_id}.")
            else:
                update.message.reply_text("❌ The file for Coincraft SRC could not be found. Please contact support.", parse_mode='Markdown')
                logger.error(f"File not found at {file_path}. Failed to send Coincraft SRC to user {user_id}.")
        else:
            # Add subscription for other products
            duration_days = get_duration(product_id)
            add_subscription(user_id, product_id, duration_days)
            logger.info(f"Subscription added for user {user_id} for product {product_id}.")
    except Exception as e:
        update.message.reply_text("⚠️ Failed to process transaction.", parse_mode='Markdown')
        logger.error(f"Error processing transaction {transaction_id}: {e}")
        return

    # Handle referral rewards
    referred_user = users_collection.find_one({"user_id": user_id})
    referrer_id = referred_user.get("referred_by")
    if referrer_id:
        referral_earning = amount * 0.2  # 20% of the sale price
        users_collection.update_one(
            {"user_id": referrer_id},
            {"$inc": {"referral_earnings": referral_earning}}
        )

        # Notify the referrer
        try:
            referrer = users_collection.find_one({"user_id": referrer_id})
            referrer_username = referrer.get('username', 'Unknown')
            context.bot.send_message(
                chat_id=referrer_id,
                text=(
                    f"🎉 <b>Referral Reward Earned!</b>\n\n"
                    f"👤 Referred User: @{referred_user.get('username', 'Unknown')}\n"
                    f"💰 Reward: ${referral_earning:.2f}\n\n"
                    f"Thank you for referring users!"
                ),
                parse_mode='HTML'
            )
            logger.info(f"Referral reward of ${referral_earning:.2f} sent to user {referrer_id}.")
        except Exception as e:
            logger.error(f"Failed to notify referrer {referrer_id}: {e}")

        # Notify the admin about the referral
        try:
            context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=(
                    f"📢 <b>Referral Purchase Notification</b>\n\n"
                    f"👤 Referrer: @{referrer_username} (ID: {referrer_id})\n"
                    f"👤 Referred User: @{referred_user.get('username', 'Unknown')} (ID: {user_id})\n"
                    f"💰 Referral Reward: ${referral_earning:.2f}\n"
                    f"🛒 Product Purchased: {product_id}\n"
                    f"💵 Amount Paid: ${amount:.2f}"
                ),
                parse_mode='HTML'
            )
            logger.info(f"Admin notified about referral reward for {referrer_id}.")
        except Exception as e:
            logger.error(f"Failed to notify admin about referral reward for {referrer_id}: {e}")

    # Notify admin about successful confirmation
    update.message.reply_text(f"✅ Transaction {transaction_id} confirmed successfully.", parse_mode='Markdown')
    logger.info(f"Admin confirmed transaction {transaction_id} for user {user_id}.")

    # Notify the user about the confirmation
    try:
        context.bot.send_message(
            chat_id=user_id,
            text=(
                f"✅ Your payment for transaction `{transaction_id}` has been confirmed!\n\n"
                "Thank you for your purchase!"
            ),
            parse_mode='Markdown'
        )
        logger.info(f"Notified user {user_id} about confirmation of transaction {transaction_id}.")
    except Exception as e:
        update.message.reply_text(f"⚠️ Failed to notify user: {e}", parse_mode='Markdown')
        logger.error(f"Failed to notify user {user_id} about transaction confirmation: {e}")


def send_file_to_user(context, user_id, file_path, caption):
    """Send a file to the user or notify admin if missing."""
    if os.path.exists(file_path):
        try:
            with open(file_path, 'rb') as doc:
                context.bot.send_document(chat_id=user_id, document=doc, caption=caption, parse_mode='Markdown')
            logger.info(f"Sent file {file_path} to user {user_id}.")
        except Exception as e:
            notify_admin(context.bot, f"Failed to send file to user {user_id}: {e}")
            logger.error(f"Failed to send file {file_path} to user {user_id}: {e}")
    else:
        error_message = f"File {file_path} not found."
        context.bot.send_message(chat_id=user_id, text="⚠️ *Sorry, the requested file is not available.*", parse_mode='Markdown')
        notify_admin(context.bot, error_message)
        logger.error(error_message)
def info_handler(update: Update, context: CallbackContext):
    """Handle the /info command to display user information."""
    user = update.effective_user

    # Check if the user is banned
    if is_banned(user.id):
        update.message.reply_text("❌ You are banned from using this bot.")
        return

    # Fetch user data from the database
    user_data = users_collection.find_one({"user_id": user.id})
    if not user_data:
        update.message.reply_text("❌ <b>User not found in the database.</b>", parse_mode='HTML')
        logger.warning(f"User {user.id} not found in database for /info command.")
        return

    # Fetch subscriptions and transactions
    subscriptions = list(subscriptions_collection.find({"user_id": user.id}))
    transactions = list(transactions_collection.find({"user_id": user.id}))

    # Calculate total money spent and earned
    total_spent = sum(txn.get("amount", 0) for txn in transactions if txn.get("status") == "confirmed")
    total_earned = user_data.get("total_earned", 0)  # Use `total_earned` from user document

    # Format subscription data
    subscription_info = ""
    if subscriptions:
        for sub in subscriptions:
            product_id = sub.get("product_id", "Unknown Product")
            start_date = sub.get("start_date", None)
            end_date = sub.get("end_date", "Lifetime" if sub.get("duration_days") == "Lifetime" else None)
            subscription_info += (
                f"📦 <b>Product:</b> {product_id}\n"
                f"📅 <b>Start Date:</b> {start_date.strftime('%Y-%m-%d') if start_date else 'N/A'}\n"
                f"📆 <b>End Date:</b> {end_date.strftime('%Y-%m-%d') if isinstance(end_date, datetime) else end_date}\n\n"
            )
    else:
        subscription_info = "🚫 <b>No subscriptions found.</b>\n"

    # Format response message
    joined_at = user_data.get("joined_at", None)
    response_message = (
        f"👤 <b>User Information</b>\n\n"
        f"🆔 <b>User ID:</b> <code>{user.id}</code>\n"
        f"💼 <b>Username:</b> @{user.username if user.username else 'N/A'}\n"
        f"📅 <b>Date Joined:</b> {joined_at.strftime('%Y-%m-%d') if joined_at else 'Unknown'}\n\n"
        f"💰 <b>Total Money Spent:</b> ${total_spent:.2f}\n"
        f"🤑 <b>Total Money Earned:</b> ${total_earned:.2f}\n\n"
        f"📜 <b>Subscriptions:</b>\n{subscription_info}"
    )

    # Send the information to the user
    update.message.reply_text(response_message, parse_mode='HTML')
    logger.info(f"Displayed info for user {user.id}.")
def user_info_handler(update: Update, context: CallbackContext):
    """Admin command to fetch user information by username or user ID."""
    if update.effective_user.id != ADMIN_CHAT_ID:
        update.message.reply_text("❌ You are not authorized to use this command.")
        return

    # Parse the command arguments
    message = update.message.text
    args = message.split(maxsplit=1)

    if len(args) != 2:
        update.message.reply_text("❌ <b>Usage:</b> /user_info <username|user_id>", parse_mode='HTML')
        return

    query = args[1]

    # Check if the query is a username or user ID
    if query.startswith("@"):
        user_data = users_collection.find_one({"username": query.lstrip("@")})
    else:
        try:
            user_id = int(query)
            user_data = users_collection.find_one({"user_id": user_id})
        except ValueError:
            update.message.reply_text("❌ <b>Invalid user ID format.</b>", parse_mode='HTML')
            return

    if not user_data:
        update.message.reply_text(f"⚠️ <b>User not found:</b> {query}", parse_mode='HTML')
        return

    # Fetch subscriptions and transactions
    user_id = user_data["user_id"]
    subscriptions = list(subscriptions_collection.find({"user_id": user_id}))
    transactions = list(transactions_collection.find({"user_id": user_id}))

    # Calculate total money spent and earned
    total_spent = sum(txn.get("amount", 0) for txn in transactions if txn.get("status") == "confirmed")
    total_earned = user_data.get("total_earned", 0)

    # Format subscription data
    subscription_info = ""
    if subscriptions:
        for sub in subscriptions:
            product_id = sub.get("product_id", "Unknown Product")
            start_date = sub.get("start_date", None)
            end_date = sub.get("end_date", "Lifetime" if sub.get("duration_days") == "Lifetime" else None)
            subscription_info += (
                f"📦 <b>Product:</b> {product_id}\n"
                f"📅 <b>Start Date:</b> {start_date.strftime('%Y-%m-%d') if start_date else 'N/A'}\n"
                f"📆 <b>End Date:</b> {end_date.strftime('%Y-%m-%d') if isinstance(end_date, datetime) else end_date}\n\n"
            )
    else:
        subscription_info = "🚫 <b>No subscriptions found.</b>\n"

    # Format response message
    joined_at = user_data.get("joined_at", None)
    response_message = (
        f"👤 <b>User Information</b>\n\n"
        f"🆔 <b>User ID:</b> <code>{user_id}</code>\n"
        f"💼 <b>Username:</b> @{user_data.get('username', 'N/A')}\n"
        f"📅 <b>Date Joined:</b> {joined_at.strftime('%Y-%m-%d') if joined_at else 'Unknown'}\n\n"
        f"💰 <b>Total Money Spent:</b> ${total_spent:.2f}\n"
        f"🤑 <b>Total Money Earned:</b> ${total_earned:.2f}\n\n"
        f"📜 <b>Subscriptions:</b>\n{subscription_info}"
    )

    # Send the information to the admin
    update.message.reply_text(response_message, parse_mode='HTML')
    logger.info(f"Admin fetched info for user {user_id}.")


def grant_subscription_handler(update: Update, context: CallbackContext):
    """Admin command to grant a subscription or SRC access to a user."""
    if update.effective_user.id != ADMIN_CHAT_ID:
        update.message.reply_text("❌ You are not authorized to use this command.")
        return

    # Parse the command arguments
    message = update.message.text
    args = message.split(maxsplit=3)

    if len(args) != 4:
        update.message.reply_text("❌ <b>Usage:</b> /grant_subscription <username|user_id> <product_id> <duration_days>", parse_mode='HTML')
        return

    query = args[1]
    product_id = args[2]
    try:
        duration_days = int(args[3]) if args[3].lower() != "lifetime" else None
    except ValueError:
        update.message.reply_text("❌ <b>Invalid duration format.</b>", parse_mode='HTML')
        return

    # Fetch user data by username or user ID
    if query.startswith("@"):
        user_data = users_collection.find_one({"username": query.lstrip("@")})
    else:
        try:
            user_id = int(query)
            user_data = users_collection.find_one({"user_id": user_id})
        except ValueError:
            update.message.reply_text("❌ <b>Invalid user ID format.</b>", parse_mode='HTML')
            return

    if not user_data:
        update.message.reply_text(f"⚠️ <b>User not found:</b> {query}", parse_mode='HTML')
        return

    user_id = user_data["user_id"]

    # Grant subscription or SRC access
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
        subscription["end_date"] = None

    # Insert the subscription into the database
    try:
        subscriptions_collection.insert_one(subscription)
        update.message.reply_text(
            f"✅ <b>Successfully granted {product_id} to user:</b> <code>{user_id}</code>",
            parse_mode='HTML'
        )

        # Notify the user
        context.bot.send_message(
            chat_id=user_id,
            text=f"🎉 <b>Congratulations!</b>\n\nYou have been granted access to:\n"
                 f"📦 <b>Product:</b> {product_id}\n"
                 f"📅 <b>Start Date:</b> {subscription['start_date'].strftime('%Y-%m-%d')}\n"
                 f"📆 <b>End Date:</b> {subscription['end_date'].strftime('%Y-%m-%d') if subscription['end_date'] else 'Lifetime'}\n\n"
                 f"Enjoy!",
            parse_mode='HTML'
        )
        logger.info(f"Admin granted {product_id} to user {user_id}.")
    except Exception as e:
        update.message.reply_text(f"❌ <b>Failed to grant subscription:</b> {e}", parse_mode='HTML')
        logger.error(f"Error granting subscription to user {user_id}: {e}")
def delete_subscription_handler(update: Update, context: CallbackContext):
    """Admin command to delete a user's subscription."""
    if update.effective_user.id != ADMIN_CHAT_ID:
        update.message.reply_text("❌ You are not authorized to use this command.")
        return

    # Parse the command arguments
    message = update.message.text
    args = message.split(maxsplit=2)

    if len(args) != 3:
        update.message.reply_text("❌ <b>Usage:</b> /delete_subscription <username|user_id> <product_id>", parse_mode='HTML')
        return

    query = args[1]
    product_id = args[2]

    # Fetch user data by username or user ID
    if query.startswith("@"):
        user_data = users_collection.find_one({"username": query.lstrip("@")})
    else:
        try:
            user_id = int(query)
            user_data = users_collection.find_one({"user_id": user_id})
        except ValueError:
            update.message.reply_text("❌ <b>Invalid user ID format.</b>", parse_mode='HTML')
            return

    if not user_data:
        update.message.reply_text(f"⚠️ <b>User not found:</b> {query}", parse_mode='HTML')
        return

    user_id = user_data["user_id"]

    # Delete the subscription
    result = subscriptions_collection.delete_one({"user_id": user_id, "product_id": product_id})

    if result.deleted_count > 0:
        update.message.reply_text(
            f"✅ <b>Successfully deleted subscription:</b> {product_id} for user <code>{user_id}</code>",
            parse_mode='HTML'
        )
        logger.info(f"Admin deleted subscription {product_id} for user {user_id}.")
    else:
        update.message.reply_text(
            f"⚠️ <b>Subscription not found:</b> {product_id} for user <code>{user_id}</code>",
            parse_mode='HTML'
        )
        logger.warning(f"Attempted to delete non-existent subscription {product_id} for user {user_id}.")
# Warn thresholds (e.g., ban after 3 warnings)
WARN_THRESHOLD = 3

def warn_handler(update: Update, context: CallbackContext):
    """Admin command to warn a user."""
    if update.effective_user.id != ADMIN_CHAT_ID:
        update.message.reply_text("❌ You are not authorized to use this command.")
        return

    # Parse the command arguments
    message = update.message.text
    args = message.split(maxsplit=2)

    if len(args) != 2:
        update.message.reply_text("❌ <b>Usage:</b> /warn <user_id>", parse_mode='HTML')
        return

    try:
        user_id = int(args[1])
    except ValueError:
        update.message.reply_text("❌ <b>Invalid user ID format.</b>", parse_mode='HTML')
        return

    # Fetch user data from the database
    user_data = users_collection.find_one({"user_id": user_id})
    if not user_data:
        update.message.reply_text(f"⚠️ <b>User not found:</b> {user_id}", parse_mode='HTML')
        return

    # Increment warnings
    warnings = user_data.get("warnings", 0) + 1
    users_collection.update_one({"user_id": user_id}, {"$set": {"warnings": warnings}})

    # Warn user
    try:
        context.bot.send_message(
            chat_id=user_id,
            text=f"⚠️ <b>You have been warned by the admin.</b>\n"
                 f"Current Warnings: {warnings}\n\n"
                 f"Please adhere to the rules to avoid further actions.",
            parse_mode='HTML'
        )
    except Exception as e:
        update.message.reply_text(f"❌ <b>Failed to notify user:</b> {e}", parse_mode='HTML')

    # Check if the user has reached the warn threshold
    if warnings >= WARN_THRESHOLD:
        update.message.reply_text(f"🚨 <b>User {user_id} has been warned {WARN_THRESHOLD} times and will be banned.</b>", parse_mode='HTML')
        ban_user(user_id, context)
    else:
        update.message.reply_text(
            f"⚠️ <b>User {user_id} has been warned.</b>\nCurrent Warnings: {warnings}/{WARN_THRESHOLD}",
            parse_mode='HTML'
        )
def ban_handler(update: Update, context: CallbackContext):
    """Admin command to ban a user."""
    if update.effective_user.id != ADMIN_CHAT_ID:
        update.message.reply_text("❌ You are not authorized to use this command.")
        return

    # Parse the command arguments
    message = update.message.text
    args = message.split(maxsplit=2)

    if len(args) != 2:
        update.message.reply_text("❌ <b>Usage:</b> /ban <user_id>", parse_mode='HTML')
        return

    try:
        user_id = int(args[1])
    except ValueError:
        update.message.reply_text("❌ <b>Invalid user ID format.</b>", parse_mode='HTML')
        return

    # Fetch user data from the database
    user_data = users_collection.find_one({"user_id": user_id})
    if not user_data:
        update.message.reply_text(f"⚠️ <b>User not found:</b> {user_id}", parse_mode='HTML')
        return

    # Ban the user
    ban_user(user_id, context)

    update.message.reply_text(
        f"✅ <b>User {user_id} has been banned.</b>",
        parse_mode='HTML'
    )


def ban_user(user_id: int, context: CallbackContext):
    """Helper function to ban a user."""
    # Add the user to a banned users list/collection
    try:
        users_collection.update_one({"user_id": user_id}, {"$set": {"banned": True}})
        # Optionally, notify the user
        context.bot.send_message(
            chat_id=user_id,
            text="🚨 <b>You have been banned by the admin.</b>\nContact support if you believe this is a mistake.",
            parse_mode='HTML'
        )
        logger.info(f"User {user_id} has been banned.")
    except Exception as e:
        logger.error(f"Failed to ban user {user_id}: {e}")
def reset_warn_handler(update: Update, context: CallbackContext):
    """Admin command to reset a user's warnings."""
    if update.effective_user.id != ADMIN_CHAT_ID:
        update.message.reply_text("❌ You are not authorized to use this command.")
        return

    # Parse the command arguments
    message = update.message.text
    args = message.split(maxsplit=2)

    if len(args) != 2:
        update.message.reply_text("❌ <b>Usage:</b> /reset_warn <user_id>", parse_mode='HTML')
        return

    try:
        user_id = int(args[1])
    except ValueError:
        update.message.reply_text("❌ <b>Invalid user ID format.</b>", parse_mode='HTML')
        return

    # Fetch user data from the database
    user_data = users_collection.find_one({"user_id": user_id})
    if not user_data:
        update.message.reply_text(f"⚠️ <b>User not found:</b> {user_id}", parse_mode='HTML')
        return

    # Reset the warnings
    users_collection.update_one({"user_id": user_id}, {"$set": {"warnings": 0}})
    update.message.reply_text(
        f"✅ <b>Warnings for user {user_id} have been reset.</b>",
        parse_mode='HTML'
    )
def unban_handler(update: Update, context: CallbackContext):
    """Admin command to unban a user."""
    if update.effective_user.id != ADMIN_CHAT_ID:
        update.message.reply_text("❌ You are not authorized to use this command.")
        return

    # Parse the command arguments
    message = update.message.text
    args = message.split(maxsplit=2)

    if len(args) != 2:
        update.message.reply_text("❌ <b>Usage:</b> /unban <user_id>", parse_mode='HTML')
        return

    try:
        user_id = int(args[1])
    except ValueError:
        update.message.reply_text("❌ <b>Invalid user ID format.</b>", parse_mode='HTML')
        return

    # Fetch user data from the database
    user_data = users_collection.find_one({"user_id": user_id})
    if not user_data:
        update.message.reply_text(f"⚠️ <b>User not found:</b> {user_id}", parse_mode='HTML')
        return

    # Remove the banned status
    users_collection.update_one({"user_id": user_id}, {"$unset": {"banned": ""}})
    update.message.reply_text(
        f"✅ <b>User {user_id} has been unbanned.</b>",
        parse_mode='HTML'
    )

    # Notify the user
    try:
        context.bot.send_message(
            chat_id=user_id,
            text="🎉 <b>You have been unbanned by the admin.</b>\nWelcome back!",
            parse_mode='HTML'
        )
    except Exception as e:
        logger.error(f"Failed to notify user {user_id} about unbanning: {e}")
def is_banned(user_id):
    """Check if a user is banned."""
    user_data = users_collection.find_one({"user_id": user_id})
    return user_data.get("banned", False) if user_data else False
def has_coincraft_subscription(user_id):
    """Check if a user has an active Coincraft subscription."""
    subscriptions = subscriptions_collection.find({"user_id": user_id})
    for sub in subscriptions:
        if "coincraft" in sub["product_id"] and (sub["end_date"] is None or sub["end_date"] > datetime.utcnow()):
            return True
    return False
def get_referral_link(user_id):
    """Generate a referral link for a user."""
    return f"https://t.me/{BOTUSERNAME}?start=ref_{user_id}"
def referral_link_handler(update: Update, context: CallbackContext):
    """Handle the 'Get Referral Link' button."""
    user = update.effective_user

    # Generate referral link
    referral_link = get_referral_link(user.id)

    # Send the referral link to the user
    message = (
        f"🔗 <b>Your Referral Link</b>\n\n"
        f"Invite your friends using the link below. When they join and make a purchase, "
        f"you'll earn rewards!\n\n"
        f"<a href='{referral_link}'>{referral_link}</a>"
    )
    update.callback_query.answer()
    update.callback_query.message.reply_text(message, parse_mode="HTML")
    logger.info(f"Sent referral link to user {user.id}.")

def notify_admin_referral(context, referrer_id, referred_user_id, product_id, amount):
    """Notify admin about a referral purchase."""
    referrer = users_collection.find_one({"user_id": referrer_id})
    referred_user = users_collection.find_one({"user_id": referred_user_id})

    referral_earning = amount * 0.2  # 20% of the sale price

    # Notify the admin
    admin_message = (
        f"📢 <b>Referral Purchase Notification</b>\n\n"
        f"👤 <b>Referrer:</b> {referrer.get('username', referrer_id)} (ID: {referrer_id})\n"
        f"👤 <b>Referred User:</b> {referred_user.get('username', referred_user_id)} (ID: {referred_user_id})\n"
        f"🛒 <b>Plan:</b> {product_id}\n"
        f"💰 <b>Price:</b> ${amount:.2f}\n"
        f"🏆 <b>Referrer Earnings:</b> ${referral_earning:.2f}"
    )
    context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_message, parse_mode="HTML")

    # Update referrer stats
    users_collection.update_one(
        {"user_id": referrer_id},
        {
            "$inc": {"referrals": 1, "referral_earnings": referral_earning}
        }
    )
def view_referrals_handler(update: Update, context: CallbackContext):
    """Admin command to view referrals for a specific user."""
    if update.effective_user.id != ADMIN_CHAT_ID:
        update.message.reply_text("❌ You are not authorized to use this command.")
        return

    if len(context.args) != 1:
        update.message.reply_text("❌ Usage: /view_referrals <user_id>")
        return

    try:
        user_id = int(context.args[0])
    except ValueError:
        update.message.reply_text("❌ Invalid user ID.")
        return

    user = users_collection.find_one({"user_id": user_id})
    if not user:
        update.message.reply_text("❌ User not found.")
        return

    referred_users = list(users_collection.find({"referred_by": user_id}))
    referrals_count = user.get("referrals", 0)
    referral_earnings = user.get("referral_earnings", 0.0)

    referred_details = "\n".join(
        [f"👤 {u.get('username', 'Unknown')} (ID: {u['user_id']})" for u in referred_users]
    )

    message = (
        f"📋 <b>User Referrals</b>\n\n"
        f"👤 <b>User:</b> @{user.get('username', 'N/A')} (ID: {user_id})\n"
        f"👥 <b>Total Referrals:</b> {referrals_count}\n"
        f"💰 <b>Total Earnings:</b> ${referral_earnings:.2f}\n\n"
        f"📜 <b>Referred Users:</b>\n{referred_details or 'None'}"
    )
    update.message.reply_text(message, parse_mode="HTML")
def top_referrers_handler(update: Update, context: CallbackContext):
    """Admin command to view top referrers."""
    if update.effective_user.id != ADMIN_CHAT_ID:
        update.message.reply_text("❌ You are not authorized to use this command.")
        return

    try:
        top_referrers = list(
            users_collection.find({"referrals": {"$gt": 0}})
            .sort("referrals", -1)
            .limit(10)
        )

        if not top_referrers:
            update.message.reply_text("❌ No referrers found.")
            return

        message = "<b>🏆 Top Referrers</b>\n\n"
        for idx, user in enumerate(top_referrers, start=1):
            message += (
                f"#{idx} 👤 @{user.get('username', 'Unknown')} "
                f"(ID: {user['user_id']})\n"
                f"   👥 Referrals: {user['referrals']}\n"
                f"   💰 Earnings: ${user.get('referral_earnings', 0.0):.2f}\n\n"
            )

        update.message.reply_text(message, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error fetching top referrers: {e}")
        update.message.reply_text("❌ Failed to fetch top referrers.")
def list_subscribed_users_handler(update: Update, context: CallbackContext):
    """Admin command to list all users with active subscriptions."""
    # Ensure only admin can execute this command
    if update.effective_user.id != ADMIN_CHAT_ID:
        update.message.reply_text("❌ You are not authorized to use this command.")
        return

    # Fetch all active subscriptions
    subscriptions = list(subscriptions_collection.find({"end_date": {"$gte": datetime.utcnow()}}))

    if not subscriptions:
        update.message.reply_text("❌ No active subscriptions found.")
        return

    # Create a dictionary to organize subscriptions by user
    user_subscriptions = {}
    for sub in subscriptions:
        user_id = sub["user_id"]
        product_id = sub["product_id"]
        end_date = sub.get("end_date", "Lifetime")
        if isinstance(end_date, datetime):
            end_date = end_date.strftime('%Y-%m-%d')

        if user_id not in user_subscriptions:
            user = users_collection.find_one({"user_id": user_id})
            username = user.get("username", "Unknown") if user else "Unknown"
            user_subscriptions[user_id] = {
                "username": username,
                "subscriptions": []
            }

        user_subscriptions[user_id]["subscriptions"].append(f"{product_id} (Ends: {end_date})")

    # Build the message
    message = "<b>📋 List of Subscribed Users</b>\n\n"
    for user_id, info in user_subscriptions.items():
        message += (
            f"👤 <b>User:</b> @{info['username']} (ID: {user_id})\n"
            f"📦 <b>Subscriptions:</b>\n  - " + "\n  - ".join(info["subscriptions"]) + "\n\n"
        )

    # Send the response
    update.message.reply_text(message, parse_mode="HTML")
    logger.info("Admin fetched the list of subscribed users.")
def delete_unpaid_invoices():
    """Delete unpaid invoices older than 30 minutes."""
    try:
        # Calculate the cutoff time (30 minutes ago)
        cutoff_time = datetime.utcnow() - timedelta(minutes=30)
        
        # Find and delete unpaid invoices
        result = transactions_collection.delete_many({
            "status": "pending",  # Only unpaid invoices
            "created_at": {"$lte": cutoff_time}  # Older than 30 minutes
        })
        
        if result.deleted_count > 0:
            logger.info(f"Deleted {result.deleted_count} unpaid invoices older than 30 minutes.")
        else:
            logger.info("No unpaid invoices found to delete.")
    except Exception as e:
        logger.error(f"Error deleting unpaid invoices: {e}")

    # Schedule the function to run again after a fixed interval (e.g., 5 minutes)
    Timer(300, delete_unpaid_invoices).start()

# Start the periodic job
delete_unpaid_invoices()
def auto_withdraw_handler(update: Update, context: CallbackContext):
    """Handle auto-withdrawal setup for Coincraft Bot users."""
    user = update.effective_user
    user_data = users_collection.find_one({"user_id": user.id})

    # Check if the user has a valid subscription
    if not has_coincraft_subscription(user.id):
        update.message.reply_text(
            "❌ <b>You need an active Coincraft Bot subscription to enable auto-withdrawal.</b>",
            parse_mode="HTML"
        )
        return

    # Check if the user already has a BTC address set
    btc_address = user_data.get("btc_address")
    if btc_address:
        update.message.reply_text(
            f"💰 <b>Auto-withdrawal is currently enabled to:</b> <code>{btc_address}</code>\n\n"
            "🔄 <b>Use /update_btc_address to change your BTC address.</b>\n"
            "❌ <b>Use /disable_auto_withdraw to disable auto-withdrawal.</b>",
            parse_mode="HTML"
        )
    else:
        update.message.reply_text(
            "💳 <b>No BTC address set for auto-withdrawal.</b>\n\n"
            "Please send your BTC address to enable auto-withdrawal.",
            parse_mode="HTML"
        )
        context.user_data["awaiting_btc_address"] = True

def set_btc_address_handler(update: Update, context: CallbackContext):
    """Handle BTC address input and validate it."""
    user = update.effective_user

    # Check if awaiting BTC address
    if not context.user_data.get("awaiting_btc_address"):
        return

    # Get the BTC address from the user
    btc_address = update.message.text.strip()

    # Validate the BTC address using blockchain API
    blockchain_api_url = f"https://blockchain.info/rawaddr/{btc_address}"
    try:
        response = requests.get(blockchain_api_url)
        response_data = response.json()

        # Check if the address is valid
        if response.status_code == 200:
            address_type = response_data.get("type", "Unknown")
            balance = response_data.get("final_balance", 0) / 1e8  # Convert satoshis to BTC

            # Save the BTC address and details to the database
            users_collection.update_one(
                {"user_id": user.id},
                {"$set": {"btc_address": btc_address, "btc_address_type": address_type, "btc_balance": balance}}
            )

            update.message.reply_text(
                f"✅ <b>BTC Address Verified</b>\n\n"
                f"💳 <b>Address:</b> <code>{btc_address}</code>\n"
                f"📜 <b>Type:</b> {address_type}\n"
                f"💰 <b>Balance:</b> {balance} BTC\n\n"
                f"Auto-withdrawal has been enabled to this address.",
                parse_mode="HTML"
            )
            context.user_data.pop("awaiting_btc_address", None)  # Clear context flag
        else:
            update.message.reply_text("❌ <b>Invalid BTC address. Please try again.</b>", parse_mode="HTML")

    except Exception as e:
        logger.error(f"Error validating BTC address for user {user.id}: {e}")
        update.message.reply_text("❌ <b>Failed to verify BTC address. Please try again later.</b>", parse_mode="HTML")
def disable_auto_withdraw_handler(update: Update, context: CallbackContext):
    """Handle disabling auto-withdrawal."""
    user = update.effective_user

    # Fetch user data
    user_data = users_collection.find_one({"user_id": user.id})

    if not user_data.get("btc_address"):
        update.message.reply_text("❌ <b>Auto-withdrawal is not enabled.</b>", parse_mode="HTML")
        return

    # Remove BTC address
    users_collection.update_one({"user_id": user.id}, {"$unset": {"btc_address": "", "btc_address_type": "", "btc_balance": ""}})
    update.message.reply_text("✅ <b>Auto-withdrawal has been disabled.</b>", parse_mode="HTML")
def update_btc_address_handler(update: Update, context: CallbackContext):
    """Handle updating the BTC address."""
    user = update.effective_user

    # Fetch user data
    user_data = users_collection.find_one({"user_id": user.id})

    if not user_data.get("btc_address"):
        update.message.reply_text(
            "❌ <b>No BTC address is currently set. Use /auto_withdraw to set a new address.</b>",
            parse_mode="HTML"
        )
        return

    update.message.reply_text(
        "🔄 <b>Please send your new BTC address.</b>",
        parse_mode="HTML"
    )
    context.user_data["awaiting_btc_address"] = True
import re

def is_potential_btc_address(text):
    """Check if the given text looks like a BTC address."""
    btc_address_pattern = r"^[13][a-km-zA-HJ-NP-Z1-9]{25,34}$"  # Matches legacy (P2PKH, P2SH) and SegWit addresses
    bech32_pattern = r"^(bc1)[a-zA-HJ-NP-Z0-9]{39,59}$"  # Matches Bech32 addresses
    return re.match(btc_address_pattern, text) or re.match(bech32_pattern, text)
def update_user_rewards(user_id, amount):
    try:
        # Fetch the user's current referral earnings
        user_data = users_collection.find_one({"user_id": user_id})
        if not user_data:
            # If the user does not exist in the database, initialize with zero referral earnings
            new_balance = max(0, amount)  # Ensure no negative balance
            users_collection.insert_one({"user_id": user_id, "referral_earnings": new_balance})
            logger.info(f"Initialized referral earnings for user {user_id} with balance: {new_balance}.")
        else:
            # Update the existing referral earnings balance
            current_earnings = user_data.get("referral_earnings", 0)
            new_balance = max(0, current_earnings + amount)  # Ensure no negative balance
            users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"referral_earnings": new_balance}}
            )
            logger.info(f"Updated referral earnings for user {user_id}: {current_earnings} -> {new_balance}.")

    except Exception as e:
        logger.error(f"Error updating referral earnings for user {user_id}: {e}")


def redeem_rewards_handler(update: Update, context: CallbackContext):
    """Handle the redeem rewards button click."""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id

    # Get product details from user data
    product_id = context.user_data.get('product_id')
    if not product_id:
        query.edit_message_caption(
            "❌ No product selected. Please start again.",
            parse_mode="HTML"
        )
        logger.warning(f"User {user_id} tried to redeem rewards without a selected product.")
        return

    # Fetch product price and user rewards
    product_price = PRODUCT_PRICES.get(product_id)
    user_rewards = get_user_rewards(user_id)

    # Check if the user has enough rewards
    if user_rewards < product_price:
        query.edit_message_caption(
            f"❌ Insufficient rewards. You need ${product_price - user_rewards:.2f} more to redeem this product.",
            parse_mode="HTML"
        )
        logger.warning(f"User {user_id} has insufficient rewards for product {product_id}.")
        return

    # Deduct the rewards from the user's balance
    update_user_rewards(user_id, -product_price)

    # Activate the subscription
    add_subscription(user_id, product_id, get_duration(product_id))

    # Notify the user
    query.edit_message_caption(
        f"🎉 <b>Subscription Activated!</b>\n\n"
        f"✅ <b>Product:</b> {product_id}\n"
        f"💵 <b>Paid with:</b> Rewards (${product_price})\n\n"
        "Thank you for using your rewards!",
        parse_mode="HTML"
    )
    logger.info(f"User {user_id} redeemed rewards for product {product_id}.")

    # Notify the admin
    admin_message = (
        f"🎁 <b>Rewards Redeemed</b>\n\n"
        f"👤 <b>User ID:</b> {user_id}\n"
        f"🛒 <b>Product:</b> {product_id}\n"
        f"💵 <b>Paid with Rewards:</b> ${product_price}\n"
        f"📆 <b>Duration:</b> {get_duration(product_id)} days"
    )
    notify_admin(context.bot, admin_message, parse_mode="HTML")
def process_redeem_plan(update: Update, context: CallbackContext):
    """Process the user's plan selection for redeeming rewards."""
    user = update.effective_user
    user_response = update.message.text.strip().lower()
    referral_rewards = context.user_data.get("redeemable_rewards", 0)
    available_plans = context.user_data.get("available_plans", {})

    if user_response not in available_plans:
        update.message.reply_text("❌ Invalid plan. Please reply with a valid plan name.")
        return

    plan_price = available_plans[user_response]
    if referral_rewards < plan_price:
        update.message.reply_text("❌ You don't have enough referral rewards to redeem this plan.")
        return

    # Deduct the plan price from the user's referral rewards
    remaining_rewards = referral_rewards - plan_price
    users_collection.update_one(
        {"user_id": user.id},
        {"$set": {"referral_rewards": remaining_rewards}}
    )

    # Activate the subscription for the user
    add_subscription(user.id, user_response, get_duration(user_response))

    update.message.reply_text(
        f"✅ Successfully redeemed <b>{user_response}</b> using referral rewards!\n"
        f"Remaining rewards: ${remaining_rewards:.2f}",
        parse_mode="HTML"
    )
    logger.info(f"User {user.id} redeemed plan {user_response} using referral rewards.")
