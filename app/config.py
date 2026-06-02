import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"

load_dotenv(ENV_FILE)

TOKEN = os.getenv("TOKEN")
ADMINS_IDS = [int(x) for x in os.getenv("ADMINS_IDS", "").split(",") if x]
COMMISSION_STARS = [int(os.getenv("COMMISSION_STARS", 30))]
COMMISSION_NFT = [int(os.getenv("COMMISSION_NFT", 30))]
COMMISSION_PREMIUM = [int(os.getenv("COMMISSION_PREMIUM", 30))]
COMMISSION_TON = [int(os.getenv("COMMISSION_TON", 30))]
COMMISSION_NUMBERS = [int(os.getenv("COMMISSION_NUMBERS", 30))]
REFERRAL_PERCENT = int(os.getenv("REFERRAL_PERCENT", 30))
API_KEY = os.getenv("API_KEY")
MNEMONIC = os.getenv("MNEMONIC")
COOKIES = os.getenv("COOKIES")
FRAGMENT_HASH = os.getenv("FRAGMENT_HASH")
PLATEGA_MERCHANT_ID = os.getenv("PLATEGA_MERCHANT_ID")
PLATEGA_SECRET = os.getenv("PLATEGA_SECRET")
CRYPTOBOT_TOKEN = os.getenv("CRYPTOBOT_TOKEN")
MARKETAPI_TOKEN = os.getenv("MARKETAPI_TOKEN")
INSTRUCTION_URL = os.getenv("INSTRUCTION_URL", "https://telegra.ph/Kak-vzyat-ssylku-na-avtorizaciyu-12-10")
SUPPORT_URL = os.getenv("SUPPORT_URL", "https://t.me/kalipsom")
PRIVACY_URL = os.getenv("PRIVACY_URL", "https://telegra.ph/Politika-Konfidencialnosti-12-01-51")
AVAILABLE_URL = os.getenv("AVAILABLE_URL", "https://telegra.ph/Dostupno-k-pokupke-12-03")
