import os
import sqlite3
import logging
from datetime import datetime
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)

# Constants
ADMIN_IDS = [5816482345, 7335094257, 5858459838, 8095253829]
ADMIN_APPROVAL_GROUP_CHAT_ID = -4766309126
ADMIN_REPORT_GROUP_CHAT_ID = -1002451897474
AUCTION_CHANNEL_ID = "@Acz_Hexa_Auction"

# States for ConversationHandler
POKE_CATEGORY, POKE_NAME, POKE_INFO, POKE_IV_EV, POKE_MOVESET, POKE_BOOSTED, POKE_PRICE = range(7)
TM_INFO, TM_PRICE = range(8, 10)

# Initialize logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Database setup
def init_db():
    conn = sqlite3.connect("acz_auction.db")
    cursor = conn.cursor()
    
    # Items table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS items (
        item_id TEXT PRIMARY KEY,
        user_id INTEGER,
        username TEXT,
        first_name TEXT,
        item_type TEXT,
        category TEXT,
        name TEXT,
        info_text TEXT,
        info_photo_id TEXT,
        iv_ev_text TEXT,
        iv_ev_photo_id TEXT,
        moveset_text TEXT,
        moveset_photo_id TEXT,
        is_boosted INTEGER,
        tm_number INTEGER,
        tm_name TEXT,
        tm_type TEXT,
        tm_power TEXT,
        tm_accuracy TEXT,
        tm_category TEXT,
        base_price INTEGER,
        status TEXT,
        submission_time TEXT,
        approval_time TEXT,
        admin_message_id INTEGER,
        channel_message_id1 INTEGER,
        channel_message_id2 INTEGER,
        highest_bid INTEGER,
        highest_bidder_id INTEGER,
        highest_bidder_name TEXT
    )
    """)
    
    # Users table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        last_seen TEXT,
        is_banned INTEGER DEFAULT 0,
        ban_reason TEXT,
        submissions_count INTEGER DEFAULT 0,
        approved_count INTEGER DEFAULT 0,
        rejected_count INTEGER DEFAULT 0,
        bids_count INTEGER DEFAULT 0,
        wins_count INTEGER DEFAULT 0
    )
    """)
    
    # Bids table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS bids (
        bid_id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id TEXT,
        user_id INTEGER,
        username TEXT,
        first_name TEXT,
        amount INTEGER,
        bid_time TEXT,
        FOREIGN KEY(item_id) REFERENCES items(item_id)
    """)
    
    # Reports table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reports (
        report_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        first_name TEXT,
        message TEXT,
        report_time TEXT,
        status TEXT DEFAULT 'open'
    )
    """)
    
    # Auction state table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS auction_state (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        submissions_open INTEGER DEFAULT 0,
        bidding_open INTEGER DEFAULT 0
    )
    """)
    
    # Initialize auction state if not exists
    cursor.execute("SELECT COUNT(*) FROM auction_state")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO auction_state (submissions_open, bidding_open) VALUES (0, 0)")
    
    conn.commit()
    conn.close()

# Helper functions
def get_db_connection():
    conn = sqlite3.connect("acz_auction.db")
    conn.row_factory = sqlite3.Row
    return conn

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def escape_markdown_v2(text: str) -> str:
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return ''.join(f'\\{char}' if char in escape_chars else char for char in text)

def generate_item_id() -> str:
    import random
    import string
    prefix = random.choice(string.ascii_uppercase)
    suffix = ''.join(random.choices(string.digits, k=4))
    return f"{prefix}{suffix}"

def get_auction_state():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT submissions_open, bidding_open FROM auction_state LIMIT 1")
    state = cursor.fetchone()
    conn.close()
    return state["submissions_open"], state["bidding_open"]

def format_pokemon_channel_message(item: sqlite3.Row) -> str:
    poke_name = escape_markdown_v2(item['name'])
    seller_name = escape_markdown_v2(item['first_name'])
    seller_username = escape_markdown_v2(item['username']) if item['username'] else "N/A"
    
    info_lines = item['info_text'].split('\n')
    level = "?"
    nature = "?"
    types = "?"
    
    for line in info_lines:
        if "Lv." in line and "Nature:" in line:
            level_part = line.split("Lv.")[1].split("|")[0].strip()
            level = level_part if level_part else "?"
            nature_part = line.split("Nature:")[1].strip()
            nature = nature_part if nature_part else "?"
        elif "Types:" in line:
            types_part = line.split("Types:")[1].strip()
            types = types_part if types_part else "?"
    
    boosted = "Yes" if item['is_boosted'] else "No"
    
    message = (
        f"Item ID: `{item['item_id']}`\n"
        f"👾 *Pokémon:* {poke_name} \\(*{escape_markdown_v2(nature)}*\\)\n"
        f"✨ *Category:* {escape_markdown_v2(item['category'])} \\| 🚀 *Boosted:* {boosted}\n\n"
        f"🧬 *Types:* {escape_markdown_v2(types)}\n\n"
        f"📊 *IVs \\| EVs:*\n"
        f"```\n{escape_markdown_v2(item['iv_ev_text'])}\n```\n\n"
        f"⚔️ *Moveset:*\n"
        f"```\n{escape_markdown_v2(item['moveset_text'])}\n```\n\n"
        f"💰 *Base Price:* {item['base_price']:,}\n"
        f"👤 *Seller:* {seller_name} \\(@{seller_username}\\) \\(`{item['user_id']}`\\)\n"
        "\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\n"
        "_\\(Bidding details below 👇\\)_"
    )
    return message

def format_tm_channel_message(item: sqlite3.Row) -> str:
    seller_name = escape_markdown_v2(item['first_name'])
    seller_username = escape_markdown_v2(item['username']) if item['username'] else "N/A"
    
    message = (
        f"Item ID: `{item['item_id']}`\n"
        f"💿 *TM:* TM{item['tm_number']} \\- {escape_markdown_v2(item['tm_name'])}\n"
        f"✨ *Type:* \\[{escape_markdown_v2(item['tm_type'])}\\]\n"
        f"💥 *Power:* {escape_markdown_v2(item['tm_power'])} \\| "
        f"*Accuracy:* {escape_markdown_v2(item['tm_accuracy'])} "
        f"\\({escape_markdown_v2(item['tm_category'])}\\)\n\n"
        f"💰 *Base Price:* {item['base_price']:,}\n"
        f"👤 *Seller:* {seller_name} \\(@{seller_username}\\) \\(`{item['user_id']}`\\)\n"
        "\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\n"
        "_\\(Bidding details below 👇\\)_"
    )
    return message

def format_preview_message(item_id: str, item_data: dict, user: object) -> str:
    escaped_name = escape_markdown_v2(user.first_name)
    escaped_username = escape_markdown_v2(user.username) if user.username else "N/A"
    
    if item_data['item_type'] == 'pokemon':
        poke_name = escape_markdown_v2(item_data['name'])
        category = escape_markdown_v2(item_data['category'])
        boosted = "Yes" if item_data.get('is_boosted', False) else "No"
        
        info_lines = item_data['info_text'].split('\n')
        level = "?"
        nature = "?"
        types = "?"
        
        for line in info_lines:
            if "Lv." in line and "Nature:" in line:
                level_part = line.split("Lv.")[1].split("|")[0].strip()
                level = level_part if level_part else "?"
                nature_part = line.split("Nature:")[1].strip()
                nature = nature_part if nature_part else "?"
            elif "Types:" in line:
                types_part = line.split("Types:")[1].strip()
                types = types_part if types_part else "?"
        
        message = (
            f"Item ID: `{item_id}`\n"
            f"👾 *Pokémon:* {poke_name} \\(*{escape_markdown_v2(nature)}*\\)\n"
            f"✨ *Category:* {category} \\| 🚀 *Boosted:* {boosted}\n\n"
            f"🧬 *Types:* {escape_markdown_v2(types)}\n\n"
            f"📊 *IVs \\| EVs:*\n"
            f"```\n{escape_markdown_v2(item_data['iv_ev_text'])}\n```\n\n"
            f"⚔️ *Moveset:*\n"
            f"```\n{escape_markdown_v2(item_data['moveset_text'])}\n```\n\n"
            f"💰 *Base Price:* {item_data['base_price']:,}\n"
            f"👤 *Seller:* {escaped_name} \\(@{escaped_username}\\) \\(`{user.id}`\\)\n"
            "\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\n"
            "_Pending admin approval_"
        )
    else:
        message = (
            f"Item ID: `{item_id}`\n"
            f"💿 *TM:* TM{item_data['tm_number']} \\- {escape_markdown_v2(item_data['tm_name'])}\n"
            f"✨ *Type:* \\[{escape_markdown_v2(item_data['tm_type'])}\\]\n"
            f"💥 *Power:* {escape_markdown_v2(item_data['tm_power'])} \\| "
            f"*Accuracy:* {escape_markdown_v2(item_data['tm_accuracy'])} "
            f"\\({escape_markdown_v2(item_data['tm_category'])}\\)\n\n"
            f"💰 *Base Price:* {item_data['base_price']:,}\n"
            f"👤 *Seller:* {escaped_name} \\(@{escaped_username}\\) \\(`{user.id}`\\)\n"
            "\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\n"
            "_Pending admin approval_"
        )
    
    return message

# Command handlers
async def add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    submissions_open, _ = get_auction_state()
    
    if not submissions_open:
        await update.message.reply_text("⚠️ Submissions are currently closed. Please wait for the next auction.")
        return ConversationHandler.END
    
    if context.user_data.get('item_type'):
        await update.message.reply_text("⚠️ You already have an item submission in progress. Please finish or cancel it first.")
        return ConversationHandler.END
    
    keyboard = [
        [InlineKeyboardButton("0l (Pokémon)", callback_data="poke_0l")],
        [InlineKeyboardButton("6l (Pokémon)", callback_data="poke_6l")],
        [InlineKeyboardButton("shiny✨️ (Pokémon)", callback_data="poke_shiny")],
        [InlineKeyboardButton("TM (Item)", callback_data="item_tm")],
        [InlineKeyboardButton("Cancel", callback_data="cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🎮 Please select the type of item you want to add:",
        reply_markup=reply_markup
    )
    
    return POKE_CATEGORY

async def poke_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel":
        await query.edit_message_text("❌ Item submission cancelled.")
        return ConversationHandler.END
    
    context.user_data['item_type'] = 'pokemon'
    context.user_data['category'] = query.data.split('_')[1]
    
    await query.edit_message_text("🔤 Please send the Pokémon's name (e.g., 'Charizard'):")
    return POKE_NAME

async def poke_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['name'] = update.message.text
    
    await update.message.reply_text(
        "📝 Please send the Pokémon Info message (Photo + Caption) with this format:\n\n"
        "Lv. <num> | Nature: <word>\n"
        "Types: [...]"
    )
    return POKE_INFO

async def poke_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message.photo or not update.message.caption:
        await update.message.reply_text("⚠️ Please send a photo with caption. Try again:")
        return POKE_INFO
    
    caption = update.message.caption
    if not ("Lv." in caption and "Nature:" in caption and "Types:" in caption):
        await update.message.reply_text("⚠️ Invalid format. Please include Level, Nature, and Types. Try again:")
        return POKE_INFO
    
    context.user_data['info_text'] = caption
    context.user_data['info_photo_id'] = update.message.photo[-1].file_id
    
    await update.message.reply_text(
        "📊 Please send the IV/EV message (Photo + Caption) with this format:\n\n"
        "HP IV | EV\n"
        "Atk IV | EV\n"
        "... (all 6 stats)"
    )
    return POKE_IV_EV

async def poke_iv_ev(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message.photo or not update.message.caption:
        await update.message.reply_text("⚠️ Please send a photo with caption. Try again:")
        return POKE_IV_EV
    
    lines = update.message.caption.split('\n')
    if len(lines) < 6 or not all("|" in line for line in lines[:6]):
        await update.message.reply_text("⚠️ Invalid format. Need all 6 stats with IV | EV format. Try again:")
        return POKE_IV_EV
    
    context.user_data['iv_ev_text'] = update.message.caption
    context.user_data['iv_ev_photo_id'] = update.message.photo[-1].file_id
    
    await update.message.reply_text(
        "⚔️ Please send the Moveset message (Photo + Caption) with this format:\n\n"
        "• Move Name [Type]\n"
        "Power: X, Accuracy: Y (Category)"
    )
    return POKE_MOVESET

async def poke_moveset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message.photo or not update.message.caption:
        await update.message.reply_text("⚠️ Please send a photo with caption. Try again:")
        return POKE_MOVESET
    
    if "•" not in update.message.caption or "Power:" not in update.message.caption:
        await update.message.reply_text("⚠️ Invalid format. Need bullet points and Power/Accuracy. Try again:")
        return POKE_MOVESET
    
    context.user_data['moveset_text'] = update.message.caption
    context.user_data['moveset_photo_id'] = update.message.photo[-1].file_id
    
    keyboard = [
        [InlineKeyboardButton("Yes", callback_data="boosted_yes")],
        [InlineKeyboardButton("No", callback_data="boosted_no")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🚀 Is this Pokémon boosted?",
        reply_markup=reply_markup
    )
    return POKE_BOOSTED

async def poke_boosted(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    context.user_data['is_boosted'] = query.data == "boosted_yes"
    await query.edit_message_text("💰 Please send the base price (number only):")
    return POKE_PRICE

async def poke_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        price = int(update.message.text)
        if price <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ Invalid price. Please send a positive number:")
        return POKE_PRICE
    
    context.user_data['base_price'] = price
    return await complete_submission(update, context)

async def item_tm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    context.user_data['item_type'] = 'tm'
    
    await query.edit_message_text(
        "📝 Please send the TM Info message (text only) with this format:\n\n"
        "TM<num>\n"
        "Move Name [Type]\n"
        "Power: X, Accuracy: Y (Category)"
    )
    return TM_INFO

async def tm_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message.text:
        await update.message.reply_text("⚠️ Please send text only. Try again:")
        return TM_INFO
    
    text = update.message.text
    lines = text.split('\n')
    
    if len(lines) < 3 or not lines[0].startswith("TM") or "[" not in lines[1] or "Power:" not in lines[2]:
        await update.message.reply_text("⚠️ Invalid format. Need TM number, Move with Type, and Power/Accuracy. Try again:")
        return TM_INFO
    
    try:
        tm_num = int(lines[0][2:])
    except ValueError:
        await update.message.reply_text("⚠️ Invalid TM number. Try again:")
        return TM_INFO
    
    move_line = lines[1]
    start = move_line.find("[")
    end = move_line.find("]")
    if start == -1 or end == -1:
        await update.message.reply_text("⚠️ Couldn't find move type in brackets. Try again:")
        return TM_INFO
    
    move_name = move_line[:start].strip()
    move_type = move_line[start+1:end]
    
    details = lines[2]
    power = details.split("Power:")[1].split(",")[0].strip() if "Power:" in details else "?"
    accuracy = details.split("Accuracy:")[1].split(",")[0].strip() if "Accuracy:" in details else "?"
    category = details.split("(")[1].split(")")[0] if "(" in details and ")" in details else "?"
    
    context.user_data['tm_number'] = tm_num
    context.user_data['tm_name'] = move_name
    context.user_data['tm_type'] = move_type
    context.user_data['tm_power'] = power
    context.user_data['tm_accuracy'] = accuracy
    context.user_data['tm_category'] = category
    context.user_data['info_text'] = text
    
    await update.message.reply_text("💰 Please send the base price (number only):")
    return TM_PRICE

async def tm_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        price = int(update.message.text)
        if price <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ Invalid price. Please send a positive number:")
        return TM_PRICE
    
    context.user_data['base_price'] = price
    return await complete_submission(update, context)

async def complete_submission(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    user_data = context.user_data
    
    item_id = generate_item_id()
    item_type = user_data['item_type']
    base_price = user_data['base_price']
    submission_time = datetime.now().isoformat()
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        "INSERT OR IGNORE INTO users (user_id, username, first_name, last_seen) VALUES (?, ?, ?, ?)",
        (user.id, user.username, user.first_name, submission_time)
    )
    cursor.execute(
        "UPDATE users SET username = ?, first_name = ?, last_seen = ?, submissions_count = submissions_count + 1 WHERE user_id = ?",
        (user.username, user.first_name, submission_time, user.id)
    )
    
    if item_type == 'pokemon':
        cursor.execute(
            """INSERT INTO items (
                item_id, user_id, username, first_name, item_type, category, name, 
                info_text, info_photo_id, iv_ev_text, iv_ev_photo_id, moveset_text, 
                moveset_photo_id, is_boosted, base_price, status, submission_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item_id, user.id, user.username, user.first_name, item_type, 
                user_data['category'], user_data['name'], user_data['info_text'], 
                user_data['info_photo_id'], user_data['iv_ev_text'], 
                user_data['iv_ev_photo_id'], user_data['moveset_text'], 
                user_data['moveset_photo_id'], user_data.get('is_boosted', 0), 
                base_price, 'pending', submission_time
            )
        )
    else:
        cursor.execute(
            """INSERT INTO items (
                item_id, user_id, username, first_name, item_type, tm_number, tm_name, 
                tm_type, tm_power, tm_accuracy, tm_category, info_text, base_price, 
                status, submission_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item_id, user.id, user.username, user.first_name, item_type, 
                user_data['tm_number'], user_data['tm_name'], user_data['tm_type'], 
                user_data['tm_power'], user_data['tm_accuracy'], 
                user_data['tm_category'], user_data['info_text'], base_price, 
                'pending', submission_time
            )
        )
    
    conn.commit()
    
    preview_message = format_preview_message(item_id, user_data, user)
    
    keyboard = [
        [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{item_id}")],
        [InlineKeyboardButton("❌ Reject", callback_data=f"reject_{item_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if item_type == 'pokemon':
        sent_message = await context.bot.send_photo(
            chat_id=ADMIN_APPROVAL_GROUP_CHAT_ID,
            photo=user_data['info_photo_id'],
            caption=preview_message,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=reply_markup
        )
    else:
        sent_message = await context.bot.send_message(
            chat_id=ADMIN_APPROVAL_GROUP_CHAT_ID,
            text=preview_message,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=reply_markup
        )
    
    cursor.execute(
        "UPDATE items SET admin_message_id = ? WHERE item_id = ?",
        (sent_message.message_id, item_id)
    )
    
    conn.commit()
    conn.close()
    
    await context.bot.send_message(
        chat_id=user.id,
        text=f"✅ Your item has been submitted for approval!\n\nItem ID: `{item_id}`",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    context.user_data.clear()
    
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("❌ Item submission cancelled.")
    else:
        await update.message.reply_text("❌ Item submission cancelled.")
    
    return ConversationHandler.END

async def admin_approval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    if not is_admin(query.from_user.id):
        await query.edit_message_text("⚠️ Only admins can approve/reject items.")
        return
    
    action, item_id = query.data.split('_')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM items WHERE item_id = ?", (item_id,))
    item = cursor.fetchone()
    
    if not item:
        await query.edit_message_text("⚠️ Item not found in database.")
        conn.close()
        return
    
    if item['status'] != 'pending':
        await query.edit_message_text(f"⚠️ Item already {item['status']}.")
        conn.close()
        return
    
    approval_time = datetime.now().isoformat()
    
    if action == "approve":
        cursor.execute(
            "UPDATE items SET status = 'approved', approval_time = ? WHERE item_id = ?",
            (approval_time, item_id))
        
        cursor.execute(
            "UPDATE users SET approved_count = approved_count + 1 WHERE user_id = ?",
            (item['user_id'],))
        
        conn.commit()
        
        channel_message1 = await post_to_auction_channel(item, context)
        
        if channel_message1:
            cursor.execute(
                "UPDATE items SET channel_message_id1 = ?, channel_message_id2 = ? WHERE item_id = ?",
                (channel_message1.message_id, channel_message1.message_id + 1, item_id)
            )
            conn.commit()
        
        await query.edit_message_text(
            query.message.text + "\n\n✅ APPROVED by admin",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        
        await context.bot.send_message(
            chat_id=item['user_id'],
            text=f"🎉 Your item has been approved!\n\nItem ID: `{item_id}`",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        
    else:
        cursor.execute(
            "UPDATE items SET status = 'rejected' WHERE item_id = ?",
            (item_id,))
        
        cursor.execute(
            "UPDATE users SET rejected_count = rejected_count + 1 WHERE user_id = ?",
            (item['user_id'],))
        
        conn.commit()
        
        await query.edit_message_text(
            query.message.text + "\n\n❌ REJECTED by admin",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        
        await context.bot.send_message(
            chat_id=item['user_id'],
            text=f"😞 Your item was not approved.\n\nItem ID: `{item_id}`",
            parse_mode=ParseMode.MARKDOWN_V2
        )
    
    conn.close()

async def post_to_auction_channel(item: sqlite3.Row, context: ContextTypes.DEFAULT_TYPE):
    if item['item_type'] == 'pokemon':
        message_text = format_pokemon_channel_message(item)
        
        try:
            sent_message = await context.bot.send_photo(
                chat_id=AUCTION_CHANNEL_ID,
                photo=item['info_photo_id'],
                caption=message_text,
                parse_mode=ParseMode.MARKDOWN_V2
            )
        except Exception as e:
            logger.error(f"Error posting Pokémon to channel: {e}")
            return None
        
    else:
        message_text = format_tm_channel_message(item)
        
        try:
            sent_message = await context.bot.send_message(
                chat_id=AUCTION_CHANNEL_ID,
                text=message_text,
                parse_mode=ParseMode.MARKDOWN_V2
            )
        except Exception as e:
            logger.error(f"Error posting TM to channel: {e}")
            return None
    
    bidding_text = (
        f"🔥 *Status ID:* `{item['item_id']}`\n"
        "\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\n"
        f"*Current Bid:* No bids yet\\.\n"
        f"*Starting Price:* {item['base_price']:,}\n"
        "\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-"
    )
    
    keyboard = [
        [InlineKeyboardButton("Place Bid ⬆️", callback_data=f"bid_prompt_{item['item_id']}")],
        [InlineKeyboardButton("Refresh 🔄", callback_data=f"refresh_{item['item_id']}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await context.bot.send_message(
            chat_id=AUCTION_CHANNEL_ID,
            text=bidding_text,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=reply_markup,
            reply_to_message_id=sent_message.message_id
        )
    except Exception as e:
        logger.error(f"Error posting bidding info to channel: {e}")
        return None
    
    return sent_message

# Bidding system
async def bid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /bid <item_id> <amount>")
        return
    
    item_id = context.args[0].upper()
    try:
        amount = int(context.args[1])
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ Invalid amount. Please provide a positive number.")
        return
    
    user = update.effective_user
    _, bidding_open = get_auction_state()
    
    if not bidding_open:
        await update.message.reply_text("⚠️ Bidding is currently closed.")
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Check if user is banned
    cursor.execute("SELECT is_banned FROM users WHERE user_id = ?", (user.id,))
    user_record = cursor.fetchone()
    if user_record and user_record['is_banned']:
        await update.message.reply_text("⚠️ You are banned from bidding.")
        conn.close()
        return
    
    # Get item details
    cursor.execute(
        "SELECT * FROM items WHERE item_id = ? AND status = 'approved'",
        (item_id,)
    )
    item = cursor.fetchone()
    
    if not item:
        await update.message.reply_text("⚠️ Item not found or not approved for bidding.")
        conn.close()
        return
    
    if user.id == item['user_id']:
        await update.message.reply_text("⚠️ You cannot bid on your own item.")
        conn.close()
        return
    
    # Calculate minimum bid
    current_bid = item['highest_bid'] if item['highest_bid'] else item['base_price']
    
    if amount <= current_bid:
        await update.message.reply_text(
            f"⚠️ Your bid must be higher than the current bid of {current_bid:,}."
        )
        conn.close()
        return
    
    # Check bid increments
    increment = 1000
    if current_bid >= 50000:
        increment = 5000
    elif current_bid >= 20000:
        increment = 2000
    
    if amount < current_bid + increment:
        await update.message.reply_text(
            f"⚠️ Minimum bid increment is {increment:,}. "
            f"Your bid must be at least {current_bid + increment:,}."
        )
        conn.close()
        return
    
    # Process the bid
    bid_time = datetime.now().isoformat()
    
    try:
        # Start transaction
        cursor.execute("BEGIN TRANSACTION")
        
        # Update item with new bid
        cursor.execute(
            """UPDATE items 
            SET highest_bid = ?, highest_bidder_id = ?, highest_bidder_name = ?
            WHERE item_id = ?""",
            (amount, user.id, user.first_name, item_id)
        )
        
        # Add bid to history
        cursor.execute(
            """INSERT INTO bids (
                item_id, user_id, username, first_name, amount, bid_time
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            (item_id, user.id, user.username, user.first_name, amount, bid_time)
        )
        
        # Update user stats
        cursor.execute(
            "UPDATE users SET bids_count = bids_count + 1 WHERE user_id = ?",
            (user.id,)
        )
        
        conn.commit()
        
        # Edit channel message
        bidding_text = (
            f"🔥 *Status ID:* `{item_id}`\n"
            "\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\n"
            f"*Highest Bid:* {amount:,}\n"
            f"*By:* {escape_markdown_v2(user.first_name)} "
            f"(\@{escape_markdown_v2(user.username) if user.username else 'N/A'})\n"
            "\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-"
        )
        
        keyboard = [
            [InlineKeyboardButton("Place Bid ⬆️", callback_data=f"bid_prompt_{item_id}")],
            [InlineKeyboardButton("Refresh 🔄", callback_data=f"refresh_{item_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.edit_message_text(
            chat_id=AUCTION_CHANNEL_ID,
            message_id=item['channel_message_id2'],
            text=bidding_text,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=reply_markup
        )
        
        # Notify previous bidder if exists
        if item['highest_bidder_id'] and item['highest_bidder_id'] != user.id:
            try:
                await context.bot.send_message(
                    chat_id=item['highest_bidder_id'],
                    text=f"⚠️ You've been outbid on item `{item_id}`. New highest bid: {amount:,}",
                    parse_mode=ParseMode.MARKDOWN_V2
                )
            except Exception as e:
                logger.error(f"Error notifying previous bidder: {e}")
        
        # Notify seller
        try:
            await context.bot.send_message(
                chat_id=item['user_id'],
                text=f"🎉 New bid on your item `{item_id}`: {amount:,}",
                parse_mode=ParseMode.MARKDOWN_V2
            )
        except Exception as e:
            logger.error(f"Error notifying seller: {e}")
        
        await update.message.reply_text(
            f"✅ Your bid of {amount:,} on item `{item_id}` has been placed!",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Error processing bid: {e}")
        await update.message.reply_text("⚠️ An error occurred while processing your bid. Please try again.")
    
    finally:
        conn.close()

async def bid_prompt_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    item_id = query.data.split('_')[2]
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT base_price, highest_bid FROM items WHERE item_id = ? AND status = 'approved'",
        (item_id,)
    )
    item = cursor.fetchone()
    conn.close()
    
    if not item:
        await query.edit_message_text("⚠️ Item not found or not approved for bidding.")
        return
    
    current_bid = item['highest_bid'] if item['highest_bid'] else item['base_price']
    increment = 1000
    if current_bid >= 50000:
        increment = 5000
    elif current_bid >= 20000:
        increment = 2000
    
    min_bid = current_bid + increment
    
    await context.bot.send_message(
        chat_id=query.from_user.id,
        text=(
            f"💸 To bid on item `{item_id}`, use:\n\n"
            f"`/bid {item_id} {min_bid}`\n\n"
            f"*Current bid:* {current_bid:,}\n"
            f"*Minimum bid:* {min_bid:,}"
        ),
        parse_mode=ParseMode.MARKDOWN_V2
    )

async def refresh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    item_id = query.data.split('_')[1]
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT highest_bid, highest_bidder_name, highest_bidder_id, base_price, channel_message_id2 "
        "FROM items WHERE item_id = ? AND status = 'approved'",
        (item_id,)
    )
    item = cursor.fetchone()
    conn.close()
    
    if not item:
        await query.edit_message_text("⚠️ Item not found or not approved for bidding.")
        return
    
    if item['highest_bid']:
        bidding_text = (
            f"🔥 *Status ID:* `{item_id}`\n"
            "\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\n"
            f"*Highest Bid:* {item['highest_bid']:,}\n"
            f"*By:* {escape_markdown_v2(item['highest_bidder_name'])}\n"
            "\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-"
        )
    else:
        bidding_text = (
            f"🔥 *Status ID:* `{item_id}`\n"
            "\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\n"
            f"*Current Bid:* No bids yet\\.\n"
            f"*Starting Price:* {item['base_price']:,}\n"
            "\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-"
        )
    
    keyboard = [
        [InlineKeyboardButton("Place Bid ⬆️", callback_data=f"bid_prompt_{item_id}")],
        [InlineKeyboardButton("Refresh 🔄", callback_data=f"refresh_{item_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text=bidding_text,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=reply_markup
    )

# User commands
async def mybids(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        """SELECT item_id, name, tm_name, highest_bid, base_price 
        FROM items 
        WHERE highest_bidder_id = ? AND status = 'approved'""",
        (user.id,)
    )
    items = cursor.fetchall()
    conn.close()
    
    if not items:
        await update.message.reply_text("You're not currently winning any bids.")
        return
    
    message = "🏆 Items you're currently winning:\n\n"
    for item in items:
        name = item['name'] if item['name'] else f"TM{item['tm_number']} {item['tm_name']}"
        message += (
            f"• `{item['item_id']}` - {name}\n"
            f"  Your bid: {item['highest_bid']:,} (Starting: {item['base_price']:,})\n\n"
        )
    
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN_V2)

async def myitems(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        """SELECT item_id, name, tm_name, status, base_price, highest_bid 
        FROM items 
        WHERE user_id = ? AND status IN ('pending', 'approved')""",
        (user.id,)
    )
    items = cursor.fetchall()
    conn.close()
    
    if not items:
        await update.message.reply_text("You don't have any items submitted or approved.")
        return
    
    message = "📦 Your items:\n\n"
    for item in items:
        name = item['name'] if item['name'] else f"TM{item['tm_number']} {item['tm_name']}"
        status = "✅ Approved" if item['status'] == 'approved' else "⏳ Pending"
        bid_info = f" - Current bid: {item['highest_bid']:,}" if item['highest_bid'] else ""
        message += (
            f"• `{item['item_id']}` - {name}\n"
            f"  {status} - Base: {item['base_price']:,}{bid_info}\n\n"
        )
    
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN_V2)

async def all_items(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        f"📢 All auction items are posted in our channel: {AUCTION_CHANNEL_ID}"
    )

async def me_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        """SELECT submissions_count, approved_count, rejected_count, bids_count, wins_count 
        FROM users WHERE user_id = ?""",
        (user.id,)
    )
    user_stats = cursor.fetchone()
    
    if not user_stats:
        await update.message.reply_text("No stats available yet. Submit an item to get started!")
        conn.close()
        return
    
    # Get category breakdown
    cursor.execute(
        """SELECT category, COUNT(*) as count 
        FROM items 
        WHERE user_id = ? AND item_type = 'pokemon' 
        GROUP BY category""",
        (user.id,)
    )
    category_stats = cursor.fetchall()
    
    conn.close()
    
    submission_rate = (
        (user_stats['approved_count'] / user_stats['submissions_count'] * 100) 
        if user_stats['submissions_count'] > 0 else 0
    )
    
    message = (
        f"📊 *Your Stats*\n\n"
        f"• Submissions: {user_stats['submissions_count']}\n"
        f"  - Approved: {user_stats['approved_count']}\n"
        f"  - Rejected: {user_stats['rejected_count']}\n"
        f"  - Approval Rate: {submission_rate:.1f}%\n\n"
        f"• Bids Placed: {user_stats['bids_count']}\n"
        f"• Items Won: {user_stats['wins_count']}\n\n"
        f"🎮 *Pokémon Categories Submitted:*\n"
    )
    
    for stat in category_stats:
        message += f"  - {stat['category']}: {stat['count']}\n"
    
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN_V2)

async def arules(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    rules_text = (
        "📜 *Auction Rules*\n\n"
        "1. All items must be legitimately obtained\n"
        "2. Bidding increments:\n"
        "   - <20k: +1,000\n"
        "   - 20k-50k: +2,000\n"
        "   - ≥50k: +5,000\n"
        "3. Winning bidders must complete trades within 24 hours\n"
        "4. False bids will result in a ban\n"
        "5. Admins reserve the right to remove any item\n\n"
        "By participating, you agree to these rules."
    )
    await update.message.reply_text(rules_text, parse_mode=ParseMode.MARKDOWN_V2)

async def report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /report <message>")
        return
    
    user = update.effective_user
    report_text = ' '.join(context.args)
    report_time = datetime.now().isoformat()
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        """INSERT INTO reports (
            user_id, username, first_name, message, report_time
        ) VALUES (?, ?, ?, ?, ?)""",
        (user.id, user.username, user.first_name, report_text, report_time)
    )
    
    conn.commit()
    conn.close()
    
    # Notify admin group
    report_message = (
        f"⚠️ *New Report*\n\n"
        f"From: {escape_markdown_v2(user.first_name)} "
        f"(\@{escape_markdown_v2(user.username) if user.username else 'N/A'})\n"
        f"User ID: `{user.id}`\n\n"
        f"*Message:*\n{escape_markdown_v2(report_text)}"
    )
    
    await context.bot.send_message(
        chat_id=ADMIN_REPORT_GROUP_CHAT_ID,
        text=report_message,
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    await update.message.reply_text(
        "✅ Your report has been submitted to the admins. Thank you!"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    submissions_open, bidding_open = get_auction_state()
    
    help_text = (
        "🛠 *Bot Commands*\n\n"
        "ℹ️ *Info*\n"
        "/me_info - Your stats\n"
        "/myitems - Your submitted items\n"
        "/mybids - Items you're winning\n"
        "/all_items - View all auction items\n"
        "/arules - Auction rules\n"
        "/report <message> - Report an issue\n\n"
    )
    
    if submissions_open:
        help_text += "🎮 *Submission*\n/add - Submit an item\n\n"
    
    if bidding_open:
        help_text += "💸 *Bidding*\n/bid <item_id> <amount> - Place a bid\n\n"
    
    if is_admin(update.effective_user.id):
        help_text += (
            "👑 *Admin Commands*\n"
            "/starto - Open submissions\n"
            "/submito - Close submissions\n"
            "/bido - Close bidding\n"
            "/endo - End auction\n"
            "/alist - List all items\n"
            "/bidders <item_id> - Bid history\n"
            "/aban <user_id> [reason] - Ban user\n"
            "/unban <user_id> - Unban user\n"
            "/post <message> - Broadcast\n"
            "/clear_reports - Close all reports"
        )
    
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN_V2)

# Admin commands
async def admin_command_wrapper(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_admin(update.effective_user.id):
            await update.message.reply_text("⚠️ This command is for admins only.")
            return
        return await func(update, context)
    return wrapper

@admin_command_wrapper
async def starto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        "UPDATE auction_state SET submissions_open = 1, bidding_open = 1"
    )
    conn.commit()
    conn.close()
    
    await context.bot.send_message(
        chat_id=AUCTION_CHANNEL_ID,
        text="🎉 *AUCTION STARTED* 🎉\n\nSubmissions and bidding are now OPEN!",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    await update.message.reply_text("✅ Auction started. Submissions and bidding are open.")

@admin_command_wrapper
async def submito(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        "UPDATE auction_state SET submissions_open = 0"
    )
    conn.commit()
    conn.close()
    
    await context.bot.send_message(
        chat_id=AUCTION_CHANNEL_ID,
        text="⏳ *SUBMISSIONS CLOSED*\n\nNo new items can be submitted. Bidding remains OPEN!",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    await update.message.reply_text("✅ Submissions closed. Bidding remains open.")

@admin_command_wrapper
async def bido(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        "UPDATE auction_state SET bidding_open = 0"
    )
    
    # Get all approved items with bids
    cursor.execute(
        """SELECT item_id, user_id, highest_bidder_id, highest_bid, name, tm_name 
        FROM items 
        WHERE status = 'approved' AND highest_bidder_id IS NOT NULL"""
    )
    items = cursor.fetchall()
    
    conn.commit()
    conn.close()
    
    # Notify winners and sellers
    for item in items:
        name = item['name'] if item['name'] else f"TM{item['tm_number']} {item['tm_name']}"
        
        # Notify winner
        try:
            await context.bot.send_message(
                chat_id=item['highest_bidder_id'],
                text=(
                    f"🎉 You won the auction for `{item['item_id']}` - {name}!\n\n"
                    f"Winning bid: {item['highest_bid']:,}\n\n"
                    f"Please contact the seller @{item['username']} to arrange the trade."
                ),
                parse_mode=ParseMode.MARKDOWN_V2
            )
        except Exception as e:
            logger.error(f"Error notifying winner: {e}")
        
        # Notify seller
        try:
            await context.bot.send_message(
                chat_id=item['user_id'],
                text=(
                    f"🎉 Your item `{item['item_id']}` - {name} has been sold!\n\n"
                    f"Winning bid: {item['highest_bid']:,}\n\n"
                    f"Please contact the buyer to arrange the trade."
                ),
                parse_mode=ParseMode.MARKDOWN_V2
            )
        except Exception as e:
            logger.error(f"Error notifying seller: {e}")
        
        # Update item status
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE items SET status = 'sold' WHERE item_id = ?",
            (item['item_id'],)
        conn.commit()
        conn.close()
    
    await context.bot.send_message(
        chat_id=AUCTION_CHANNEL_ID,
        text="🏁 *BIDDING CLOSED*\n\nAll winning bidders and sellers have been notified to arrange trades.",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    await update.message.reply_text("✅ Bidding closed. Winners and sellers notified.")

@admin_command_wrapper
async def endo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [InlineKeyboardButton("✅ Confirm", callback_data="confirm_endo")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_endo")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "⚠️ This will clean up all sold, ended, rejected, and cancelled items. Continue?",
        reply_markup=reply_markup
    )

async def endo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    if query.data == "confirm_endo":
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Delete sold/ended/rejected/cancelled items
        cursor.execute(
            """DELETE FROM items 
            WHERE status IN ('sold', 'ended', 'rejected', 'cancelled')"""
        )
        
        # Delete associated bids
        cursor.execute(
            """DELETE FROM bids 
            WHERE item_id NOT IN (SELECT item_id FROM items)"""
        )
        
        conn.commit()
        conn.close()
        
        await query.edit_message_text("✅ Auction cleanup complete. Pending and approved items retained.")
    else:
        await query.edit_message_text("❌ Auction cleanup cancelled.")

@admin_command_wrapper
async def alist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        """SELECT item_id, name, tm_name, user_id, base_price, highest_bid 
        FROM items 
        WHERE status = 'approved'
        ORDER BY submission_time"""
    )
    items = cursor.fetchall()
    conn.close()
    
    if not items:
        await update.message.reply_text("No approved items currently in auction.")
        return
    
    messages = []
    current_message = "📋 *Approved Items*\n\n"
    
    for item in items:
        name = item['name'] if item['name'] else f"TM{item['tm_number']} {item['tm_name']}"
        bid_info = f" (Bid: {item['highest_bid']:,})" if item['highest_bid'] else ""
        line = (
            f"• `{item['item_id']}` - {name}\n"
            f"  Seller: `{item['user_id']}` - "
            f"Base: {item['base_price']:,}{bid_info}\n\n"
        )
        
        if len(current_message) + len(line) > 4000:
            messages.append(current_message)
            current_message = line
        else:
            current_message += line
    
    if current_message:
        messages.append(current_message)
    
    for msg in messages:
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2)

@admin_command_wrapper
async def bidders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /bidders <item_id>")
        return
    
    item_id = context.args[0].upper()
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get item info
    cursor.execute(
        """SELECT name, tm_name, base_price, highest_bid, highest_bidder_id 
        FROM items 
        WHERE item_id = ?""",
        (item_id,)
    )
    item = cursor.fetchone()
    
    if not item:
        await update.message.reply_text("Item not found.")
        conn.close()
        return
    
    # Get bid history
    cursor.execute(
        """SELECT user_id, username, first_name, amount, bid_time 
        FROM bids 
        WHERE item_id = ? 
        ORDER BY amount DESC""",
        (item_id,)
    )
    bids = cursor.fetchall()
    conn.close()
    
    name = item['name'] if item['name'] else f"TM{item['tm_number']} {item['tm_name']}"
    
    message = (
        f"📊 *Bid History for {name}* (`{item_id}`)\n\n"
        f"Base Price: {item['base_price']:,}\n"
        f"Highest Bid: {item['highest_bid']:,}\n\n"
        "🛒 *Bids:*\n"
    )
    
    if not bids:
        message += "No bids yet."
    else:
        for bid in bids:
            message += (
                f"• {bid['first_name']} (\@{bid['username']}) - "
                f"{bid['amount']:,} at {bid['bid_time'][:16]}\n"
            )
    
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN_V2)

@admin_command_wrapper
async def aban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /aban <user_id or @username> [reason]")
        return
    
    target = context.args[0]
    reason = ' '.join(context.args[1:]) if len(context.args) > 1 else "No reason provided"
    
    try:
        if target.startswith('@'):
            # Lookup by username
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT user_id FROM users WHERE username = ?",
                (target[1:],)
            user = cursor.fetchone()
            conn.close()
            
            if not user:
                await update.message.reply_text("User not found in database.")
                return
            
            user_id = user['user_id']
        else:
            user_id = int(target)
    except ValueError:
        await update.message.reply_text("Invalid user ID. Must be numeric or @username.")
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        "UPDATE users SET is_banned = 1, ban_reason = ? WHERE user_id = ?",
        (reason, user_id)
    
    # Get username for message
    cursor.execute(
        "SELECT username, first_name FROM users WHERE user_id = ?",
        (user_id,)
    )
    user = cursor.fetchone()
    conn.commit()
    conn.close()
    
    username = user['username'] if user and user['username'] else "N/A"
    first_name = user['first_name'] if user else "Unknown"
    
    # Notify user
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                f"⚠️ *You have been banned from the auction*\n\n"
                f"*Reason:* {escape_markdown_v2(reason)}\n\n"
                f"Contact an admin if you believe this is a mistake."
            ),
            parse_mode=ParseMode.MARKDOWN_V2
        )
    except Exception as e:
        logger.error(f"Error notifying banned user: {e}")
    
    await update.message.reply_text(
        f"✅ User {first_name} (@{username}) (`{user_id}`) has been banned.\n"
        f"Reason: {reason}"
    )

@admin_command_wrapper
async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /unban <user_id or @username>")
        return
    
    target = context.args[0]
    
    try:
        if target.startswith('@'):
            # Lookup by username
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT user_id FROM users WHERE username = ?",
                (target[1:],)
            user = cursor.fetchone()
            conn.close()
            
            if not user:
                await update.message.reply_text("User not found in database.")
                return
            
            user_id = user['user_id']
        else:
            user_id = int(target)
    except ValueError:
        await update.message.reply_text("Invalid user ID. Must be numeric or @username.")
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        "UPDATE users SET is_banned = 0, ban_reason = NULL WHERE user_id = ?",
        (user_id,))
    
    # Get username for message
    cursor.execute(
        "SELECT username, first_name FROM users WHERE user_id = ?",
        (user_id,)
    )
    user = cursor.fetchone()
    conn.commit()
    conn.close()
    
    username = user['username'] if user and user['username'] else "N/A"
    first_name = user['first_name'] if user else "Unknown"
    
    # Notify user
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text="🎉 Your auction ban has been lifted! You can now participate again."
        )
    except Exception as e:
        logger.error(f"Error notifying unbanned user: {e}")
    
    await update.message.reply_text(
        f"✅ User {first_name} (@{username}) (`{user_id}`) has been unbanned."
    )

@admin_command_wrapper
async def warn(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /warn <user_id> <reason>")
        return
    
    try:
        user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid user ID. Must be numeric.")
        return
    
    reason = ' '.join(context.args[1:])
    
    # Notify user
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                f"⚠️ *You have received a warning from the auction admin*\n\n"
                f"*Reason:* {escape_markdown_v2(reason)}\n\n"
                f"Please review the auction rules to avoid further action."
            ),
            parse_mode=ParseMode.MARKDOWN_V2
        )
    except Exception as e:
        logger.error(f"Error warning user: {e}")
        await update.message.reply_text("Failed to send warning to user. They may have blocked the bot.")
        return
    
    await update.message.reply_text("✅ Warning sent to user.")

@admin_command_wrapper
async def post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /post <message>")
        return
    
    message_text = ' '.join(context.args)
    
    # Split message if too long
    max_length = 4000
    message_chunks = [message_text[i:i+max_length] for i in range(0, len(message_text), max_length)]
    
    # Send to channel
    try:
        for chunk in message_chunks:
            await context.bot.send_message(
                chat_id=AUCTION_CHANNEL_ID,
                text=chunk
            )
    except Exception as e:
        logger.error(f"Error posting to channel: {e}")
        await update.message.reply_text("Failed to post to channel.")
        return
    
    # Send to all users
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT user_id FROM users WHERE is_banned = 0"
    )
    users = cursor.fetchall()
    conn.close()
    
    success = 0
    failed = 0
    
    for user in users:
        try:
            for chunk in message_chunks:
                await context.bot.send_message(
                    chat_id=user['user_id'],
                    text=chunk
                )
            success += 1
        except Exception as e:
            logger.error(f"Error sending to user {user['user_id']}: {e}")
            failed += 1
    
    await update.message.reply_text(
        f"✅ Broadcast complete.\n\n"
        f"• Channel: {len(message_chunks)} message(s)\n"
        f"• Users: {success} successful, {failed} failed"
    )

@admin_command_wrapper
async def clear_reports(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        "UPDATE reports SET status = 'closed' WHERE status = 'open'"
    )
    count = cursor.rowcount
    conn.commit()
    conn.close()
    
    await update.message.reply_text(f"✅ Closed {count} open reports.")

@admin_command_wrapper
async def reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /reply <user_id> <message>")
        return
    
    try:
        user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid user ID. Must be numeric.")
        return
    
    message_text = ' '.join(context.args[1:])
    
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=message_text
        )
        await update.message.reply_text("✅ Message sent to user.")
    except Exception as e:
        logger.error(f"Error replying to user: {e}")
        await update.message.reply_text("Failed to send message. User may have blocked the bot.")

# Error handler
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)
    
    if update and hasattr(update, 'effective_user'):
        try:
            await context.bot.send_message(
                chat_id=update.effective_user.id,
                text="⚠️ An error occurred while processing your request. Please try again."
            )
        except Exception:
            pass

# Main function
def main() -> None:
    # Initialize database
    init_db()
    
    # Create the Application
    application = Application.builder().token(os.getenv("BOT_TOKEN")).build()
    
    # Add conversation handler for item submission
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("add", add)],
        states={
            POKE_CATEGORY: [CallbackQueryHandler(poke_category), CallbackQueryHandler(item_tm)],
            POKE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, poke_name)],
            POKE_INFO: [MessageHandler(filters.PHOTO & filters.CAPTION, poke_info)],
            POKE_IV_EV: [MessageHandler(filters.PHOTO & filters.CAPTION, poke_iv_ev)],
            POKE_MOVESET: [MessageHandler(filters.PHOTO & filters.CAPTION, poke_moveset)],
            POKE_BOOSTED: [CallbackQueryHandler(poke_boosted)],
            POKE_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, poke_price)],
            TM_INFO: [MessageHandler(filters.TEXT & ~filters.COMMAND, tm_info)],
            TM_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, tm_price)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(conv_handler)
    
    # Add command handlers
    application.add_handler(CommandHandler("bid", bid))
    application.add_handler(CommandHandler("mybids", mybids))
    application.add_handler(CommandHandler("myitems", myitems))
    application.add_handler(CommandHandler("all_items", all_items))
    application.add_handler(CommandHandler("me_info", me_info))
    application.add_handler(CommandHandler("arules", arules))
    application.add_handler(CommandHandler("report", report))
    application.add_handler(CommandHandler("help", help_command))
    
    # Add admin command handlers
    application.add_handler(CommandHandler("starto", starto))
    application.add_handler(CommandHandler("submito", submito))
    application.add_handler(CommandHandler("bido", bido))
    application.add_handler(CommandHandler("endo", endo))
    application.add_handler(CommandHandler("alist", alist))
    application.add_handler(CommandHandler("bidders", bidders))
    application.add_handler(CommandHandler("aban", aban))
    application.add_handler(CommandHandler("unban", unban))
    application.add_handler(CommandHandler("warn", warn))
    application.add_handler(CommandHandler("post", post))
    application.add_handler(CommandHandler("clear_reports", clear_reports))
    application.add_handler(CommandHandler("reply", reply))
    
    # Add callback handlers
    application.add_handler(CallbackQueryHandler(admin_approval_callback, pattern=r"^(approve|reject)_"))
    application.add_handler(CallbackQueryHandler(bid_prompt_callback, pattern=r"^bid_prompt_"))
    application.add_handler(CallbackQueryHandler(refresh_callback, pattern=r"^refresh_"))
    application.add_handler(CallbackQueryHandler(endo_callback, pattern=r"^(confirm|cancel)_endo"))
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Run the bot
    application.run_polling()

if __name__ == "__main__":
    main()