import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

ACCOUNTS_FILE = ROOT_DIR / "accounts.json"
SESSIONS_FILE = DATA_DIR / "sessions.json"
TARGET_COLLECTION_FILE = ROOT_DIR / "target_collection.json"
KNOWN_ACCOUNTS_FILE = ROOT_DIR / "known_accounts.json"
LAST_TRADE_FILE = ROOT_DIR / "last_trade.json"

BASE_URL = "https://www.wiki-masters.com"
LOGIN_URL = f"{BASE_URL}/login"
PULLS_URL = f"{BASE_URL}/pulls"
TRADES_URL = f"{BASE_URL}/trades"

API_MY_COLLECTION = f"{BASE_URL}/api/my-collection"
API_MY_STATS = f"{BASE_URL}/api/my-collection/stats"
API_PROFILE_COLLECTION = f"{BASE_URL}/api/profile"
API_PACKS_OPEN = f"{BASE_URL}/api/packs/open"
API_HUMAN_CHECK = f"{BASE_URL}/api/human-check"
API_PACKS_VERIFY_HUMAN = API_HUMAN_CHECK
TURNSTILE_SITEKEY = "0x4AAAAAAEW_2IAWonrk_N5i"
API_BULK_DISCARD = f"{BASE_URL}/api/user-cards/bulk-discard"
API_WIKIBIDOUS = f"{BASE_URL}/api/wikibidous"
API_FRIENDS = f"{BASE_URL}/api/friends"
API_FRIENDS_ACCEPT_ALL = f"{BASE_URL}/api/friends/accept-all"
API_FRIENDS_SEARCH = f"{BASE_URL}/api/friends/search"
API_TRADES = f"{BASE_URL}/api/trades"
API_ACHIEVEMENTS_CHECK = f"{BASE_URL}/api/achievements/check"
API_ACHIEVEMENTS_CLAIM = f"{BASE_URL}/api/achievements/claim"

SUPABASE_URL = "https://cyrxjeppjqsxxjayfrur.supabase.co"
SUPABASE_ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImN5cnhqZXBwanFzeHhqYXlmcnVyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzM4ODAzMzksImV4cCI6MjA4OTQ1NjMzOX0."
    "BZluyXygNxuQGDPxFX1zG5i-cqp10CVK-8GGtuak4Rg"
)

DEFAULT_TARGET_USERNAME = "\u200e\u200e\u200e\u200e"
DEFAULT_TARGET_EMAIL = "wikimasters@3d3n.dev"
DEFAULT_TARGET_ID = "90ac3faa-272a-4ef5-b343-a2f5efc46e1b"

PACK_OPEN_DELAY = 10.0
PACK_429_BACKOFF = 11.0

MAX_CARDS_PER_TRADE = 50
MAX_WB_PER_TRADE = 700
MAX_TRADES_PER_BOT = 1
MAX_DAILY_TARGET_TRADES = 48
MAX_CONCURRENT_CLIENTS = 3
DAILY_RESET_HOUR = 1
COUNTERPARTY_PAGES_TO_SCAN = 8
BULK_DISCARD_CHUNK_SIZE = 100

RARITY_RANKS = {
    "C": 0,
    "PC": 1,
    "R": 2,
    "SR": 3,
    "UR": 4,
    "L": 5,
}

VALUABLE_DUPLICATE_RARITIES = {"L", "UR", "SR", "R"}

DEFAULT_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:135.0) Gecko/20100101 Firefox/135.0"
REQUEST_TIMEOUT = 45.0
MAX_RETRIES = 3
HEADLESS = os.environ.get("HEADLESS", "true").lower() in ("true", "1", "yes")
