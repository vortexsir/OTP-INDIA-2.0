import os
from dotenv import load_dotenv

load_dotenv()

# Telegram Bot Token
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY")
BSCSCAN_API_KEY = os.getenv("BSCSCAN_API_KEY")
MONGODB_URI = os.getenv("MONGODB_URI")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))
BOTUSERNAME = os.getenv("BOTUSERNAME")
PRIMARY_API_URL = os.getenv("PRIMARY_API_URL")
BACKUP_API_URL = os.getenv("BACKUP_API_URL")
CRYPTOCOMPARE_API_KEY = os.getenv("CRYPTOCOMPARE_API_KEY")
CHANNEL_ID = os.getenv("CHANNEL_ID")
# Predefined Wallet Addresses for Each Supported Coin/Token
PREDEFINED_ADDRESSES = {
    "BTC": "YOUR_BTC_ADDRESS",
    "ETH": "YOUR_ETH_ADDRESS",
    "LTC": "YOUR_LTC_ADDRESS",
    "BNB": "YOUR_BNB_ADDRESS",
    "TRX": "YOUR_TRX_ADDRESS",
    "USDT_TRC20": "YOUR_USDT_TRC20_ADDRESS",
    "USDT_BEP20": "YOUR_USDT_BEP20_ADDRESS"
}
# Supported Coins/Tokens List
COIN_LIST = [
    "BTC",
    "ETH",
    "LTC",
    "BNB",
    "TRX",
    "USDT_TRC20",
    "USDT_BEP20"
]

# Product Prices in USD
PRODUCT_PRICES = {
    "coincraft_1w": 250,    # 1 Week Subscription
    "coincraft_1m": 400,    # 1 Months Subscription
    "coincraft_3m": 800,    # 3 Months Subscription
    "coincraft_src": 5000.0    # Lifetime Access (Coincraft SRC)
}
