# main.py
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler
from telegram import Update
from telegram.ext import CallbackContext,MessageHandler, Filters
from variables import TELEGRAM_TOKEN, ADMIN_CHAT_ID
from payment import initialize_wallet_balances
from handlers import (
    confirm_payment_callback,
    start_handler,
    buy_subscription_handler,
    product_selection_handler,
    payment_selection_handler,
    coin_selection_handler,
    i_have_paid_handler,
    cancel_handler,
    confirm_transaction_handler,
    info_handler,
    user_info_handler,
    grant_subscription_handler,
    delete_subscription_handler,
    warn_handler,
    ban_handler,
    unban_handler,
    reset_warn_handler,
    view_referrals_handler,
    top_referrers_handler,
    referral_link_handler,
    list_subscribed_users_handler,
    cancel_payment_handler,
    auto_withdraw_handler,
    disable_auto_withdraw_handler,
    update_btc_address_handler,
    set_btc_address_handler,
    process_redeem_plan,
    redeem_rewards_handler
)
from payment import monitor_payments,schedule_price_updates
import threading
import logging
from telegram.utils.request import Request
# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def error_handler(update: object, context: CallbackContext) -> None:
    """Log the error and notify the admin."""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    
    # Attempt to send error message to admin
    try:
        admin_message = (
            f"🚨 *An error occurred:* 🚨\n\n"
            f"*Error:* `{context.error}`\n\n"
            f"*Update:* `{update}`"
        )
        context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_message, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Failed to notify admin about the error: {e}")

def main():
    # Initialize the Request object with timeouts
    request = Request(
        connect_timeout=10,
        read_timeout=10
    )

    # Initialize the Updater and Dispatcher
    updater = Updater(
        token=TELEGRAM_TOKEN,
        request_kwargs={'connect_timeout': 10, 'read_timeout': 10},
        use_context=True
    )
    dispatcher = updater.dispatcher

    # Register Command Handlers
    dispatcher.add_handler(CommandHandler("start", start_handler))
    # Ensure that only the admin can use the /confirm command
    dispatcher.add_handler(CommandHandler("confirm", confirm_transaction_handler)),
    dispatcher.add_handler(CommandHandler("info", info_handler)),
    dispatcher.add_handler(CommandHandler("user_info", user_info_handler)),
    dispatcher.add_handler(CommandHandler("grant_subscription", grant_subscription_handler)),
    dispatcher.add_handler(CommandHandler("delete_subscription", delete_subscription_handler)),
    dispatcher.add_handler(CommandHandler("warn", warn_handler)),
    dispatcher.add_handler(CommandHandler("ban", ban_handler)),
    dispatcher.add_handler(CommandHandler("unban", unban_handler)),
    dispatcher.add_handler(CommandHandler("reset_warn", reset_warn_handler)),
    dispatcher.add_handler(CommandHandler("view_referrals", view_referrals_handler))
    dispatcher.add_handler(CommandHandler("top_referrers", top_referrers_handler)),
    dispatcher.add_handler(CommandHandler("richies", list_subscribed_users_handler)),
    dispatcher.add_handler(CommandHandler("auto_withdraw", auto_withdraw_handler))
    dispatcher.add_handler(CommandHandler("disable_auto_withdraw", disable_auto_withdraw_handler))
    dispatcher.add_handler(CommandHandler("update_btc_address", update_btc_address_handler))
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, set_btc_address_handler))
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, process_redeem_plan))




    # Register Callback Query Handlers with specific patterns
    dispatcher.add_handler(CallbackQueryHandler(buy_subscription_handler, pattern="^buy_subscription$"))
    dispatcher.add_handler(CallbackQueryHandler(product_selection_handler, pattern="^(product_coincraft_bot|buy_coincraft_src)$"))
    dispatcher.add_handler(CallbackQueryHandler(payment_selection_handler, pattern="^pay_coincraft_"))
    dispatcher.add_handler(CallbackQueryHandler(coin_selection_handler, pattern="^coin_"))
    dispatcher.add_handler(CallbackQueryHandler(i_have_paid_handler, pattern="^i_have_paid$"))
    dispatcher.add_handler(CallbackQueryHandler(cancel_handler, pattern="^cancel$"))
    dispatcher.add_handler(CallbackQueryHandler(referral_link_handler, pattern="^get_referral_link$"))
    dispatcher.add_handler(CallbackQueryHandler(confirm_payment_callback, pattern="^confirm_payment$"))
    dispatcher.add_handler(CallbackQueryHandler(cancel_payment_handler, pattern="^cancel_payment$"))
    dispatcher.add_handler(CallbackQueryHandler(redeem_rewards_handler, pattern='^redeem_rewards$'))



    # Register the global error handler
   # dispatcher.add_error_handler(error_handler)

    # Start the Bot
    updater.start_polling()
    logger.info("Bot started polling.")

    # Start the Payment Monitoring Thread
    payment_thread = threading.Thread(target=monitor_payments, args=(updater.bot,), daemon=True)
    payment_thread.start()
    logger.info("Payment monitoring thread started.")

    # Run the bot until Ctrl-C is pressed
    updater.idle()

if __name__ == "__main__":
    schedule_price_updates()
    initialize_wallet_balances()
    main()
