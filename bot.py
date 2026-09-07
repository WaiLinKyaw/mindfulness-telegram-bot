import asyncio
from aiohttp import web
import logging
import sqlite3
import os
import datetime
import pytz
from google import genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ----------------- CONFIGURATION -----------------
#TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN1")
#GEMINI_API_KEY = os.getenv("GEMINI_API_KEY1")
# ----------------- CONFIGURATION -----------------
# Environment Variables မှတစ်ဆင့် Key များကို ဆွဲထုတ်ယူခြင်း
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# API Keys များ ထည့်မထားပါက Program ကို ချက်ချင်း ရပ်တန့်ပြီး သတိပေးရန်
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("Error: TELEGRAM_BOT_TOKEN ကို Environment Variable ထဲတွင် သတ်မှတ်ပေးရန် လိုအပ်ပါသည်။")

if not GEMINI_API_KEY:
    raise ValueError("Error: GEMINI_API_KEY ကို Environment Variable ထဲတွင် သတ်မှတ်ပေးရန် လိုအပ်ပါသည်။")

client = genai.Client(api_key=GEMINI_API_KEY)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# ----------------- DATABASE HELPERS -----------------
def get_db_connection():
    return sqlite3.connect("mindfulness_bot.db")

def register_user(chat_id: int, first_name: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR IGNORE INTO bot_users (chat_id, first_name, subscribed)
        VALUES (?, ?, 1)
    """, (chat_id, first_name))
    conn.commit()
    conn.close()

def get_subscribed_users():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT chat_id FROM bot_users WHERE subscribed = 1")
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    return users

def get_random_daily_quote():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT quote FROM daily_quotes ORDER BY RANDOM() LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else "ယနေ့တစ်နေ့တာလုံး သတိပဋ္ဌာန်စိတ်ဖြင့် အေးချမ်းပါစေ။"

def get_resources_by_category(category: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT title, type, source FROM dhamma_resources WHERE category = ?", (category,))
    results = cursor.fetchall()
    conn.close()
    return results

# ----------------- GEMINI CHAT WITH HISTORY -----------------
async def get_dhamma_guidance_with_history(user_mood: str, user_message: str, history: list) -> str:
    system_instruction = (
        "သင်သည် မြန်မာနိုင်ငံမှ နာမည်ကျော် ဆရာဝန်ကြီး ဒေါက်တာစိုးလွင်၏ ဓမ္မအတွေးအမြင်များ၊ "
        "သတိပဋ္ဌာန်တရားနှင့် စိတ်ခွန်အားဖြည့် ဒေသနာများကို အခြေခံထားသော စာနာနားလည်မှုရှိသည့် Mindfulness Assistant ဖြစ်သည်။ "
        "User ၏ စိတ်ခံစားချက်နှင့် ရင်ဖွင့်စကားများကို နွေးထွေးစွာ နားထောင်ပေးပါ။ အရင်ပြောခဲ့သော စကားများကို အခြေခံ၍ ဆက်စပ်ဆွေးနွေးပါ။ "
        "လောကဓံတရား၊ ပစ္စုပ္ပန်စိတ်ကို ထားနည်း၊ အသက်ရှူသတိပြုနည်းနှင့် 'လက်ရှိဖြစ်နေသော စိတ်ကို အသိအမှတ်ပြု လက်ခံခြင်း' "
        "စသည့် ဆရာကြီးဒေါက်တာစိုးလွင် ဟောကြားလေ့ရှိသော စိတ်ငြိမ်းချမ်းရေး လမ်းညွှန်ချက်များကို အခြေခံ၍ "
        "မြန်မာလို ယဉ်ကျေးသိမ်မွေ့စွာ၊ တိုတိုနှင့် ထိရောက်စွာ နှစ်သိမ့် အကြံပြုဆွေးနွေးပေးပါ။"
    )

    # Gemini API သို့ ပေးပို့ရန် Contents Format တည်ဆောက်ခြင်း
    formatted_contents = []

    # Chat History ထည့်သွင်းခြင်း (နောက်ဆုံး အပြန်အလှန် ၅ ခုထိ မှတ်သားထားမည်)
    for entry in history[-10:]:
        role = "user" if entry["role"] == "user" else "model"
        formatted_contents.append({"role": role, "parts": [{"text": entry["text"]}]})

    # လက်ရှိ User ပို့လိုက်သော မက်ဆေ့ခ်ျကို Mood အခြေအနေနှင့် ပေါင်းစပ်ထည့်သွင်းခြင်း
    current_prompt = f"[User Mood: {user_mood}]\n{user_message}"
    formatted_contents.append({"role": "user", "parts": [{"text": current_prompt}]})

    try:
        response = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=formatted_contents,
            config={"system_instruction": system_instruction}
        )
        return response.text
    except Exception as e:
        logging.error(f"Gemini API Error: {e}")
        return "လက်ရှိ စနစ်အနည်းငယ် အလုပ်များနေသဖြင့် ခေတ္တခဏ အသက်ကို ဖြည်းဖြည်းရှူသွင်း ရှူထုတ်ရင်း စိတ်ကို ငြိမ်းချမ်းအောင် ထားပေးပါခင်ဗျာ။"

# ----------------- DAILY REMINDER JOB -----------------
async def send_daily_dhamma(context: ContextTypes.DEFAULT_TYPE):
    """နေ့စဉ် မနက်တိုင်း User များထံ ပို့ပေးမည့် Function"""
    users = get_subscribed_users()
    quote = get_random_daily_quote()
    message = f"🌅 **မင်္ဂလာနံနက်ခင်းပါခင်ဗျာ**\n\nဒီနေ့အတွက် ဆရာကြီးဒေါက်တာစိုးလွင်၏ ဓမ္မလက်ဆောင်:\n\n{quote}"

    for chat_id in users:
        try:
            await context.bot.send_message(chat_id=chat_id, text=message, parse_mode="Markdown")
        except Exception as e:
            logging.warning(f"User {chat_id} ထံသို့ စာပို့မရပါ: {e}")

# ----------------- BOT HANDLERS -----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.first_name)

    # User တစ်ဦးစီ၏ Chat History ကို Reset ပြုလုပ်ခြင်း
    context.user_data["chat_history"] = []

    keyboard = [
        [
            InlineKeyboardButton("စိတ်ဖိစီးနေတယ် 😣", callback_data="mood_stress"),
            InlineKeyboardButton("ဝမ်းနည်းနေတယ် 😔", callback_data="mood_sadness")
        ],
        [
            InlineKeyboardButton("ဒေါသထွက်နေတယ် 😡", callback_data="mood_anger"),
            InlineKeyboardButton("စိတ်ငြိမ်သက်ချင်တယ် 🧘", callback_data="mood_mindfulness")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"မင်္ဂလာပါ {user.first_name}။ စိတ်၏ ငြိမ်းချမ်းမှု ရရှိစေရန် ကြိုဆိုပါတယ်။\n\n"
        "နေ့စဉ် မနက်ခင်းတိုင်း သတိပဋ္ဌာန်စာတိုလေးများ ပို့ပေးပါမည်။\n"
        "လောလောဆယ် သင့်ရဲ့ စိတ်ခံစားချက် အခြေအနေလေးကို ရွေးချယ်ပေးပါခင်ဗျာ-",
        reply_markup=reply_markup
    )

async def mood_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    mood_map = {
        "mood_stress": ("စိတ်ဖိစီးမှု", "stress"),
        "mood_sadness": ("ဝမ်းနည်းမှု", "sadness"),
        "mood_anger": ("ဒေါသဖြစ်ခြင်း", "anger"),
        "mood_mindfulness": ("စိတ်အေးချမ်းမှုရှာဖွေခြင်း", "mindfulness")
    }

    mood_label, category = mood_map.get(query.data, ("အခြား", "mindfulness"))
    context.user_data["current_mood"] = mood_label
    context.user_data["current_category"] = category

    await query.edit_message_text(
        f"သင် '{mood_label}' ဖြစ်နေတာကို နားလည်ပေးပါတယ်။\n"
        "ဒီခံစားချက်နဲ့ ပတ်သက်ပြီး ဘာတွေကြုံတွေ့နေရလဲဆိုတာ စာတိုလေး ပို့ပြီး ရင်ဖွင့်ဆွေးနွေးနိုင်ပါတယ်ခင်ဗျာ။\n\n"
        "သင့်အတွက် ဆရာကြီးဒေါက်တာစိုးလွင်၏ တရားစာအုပ်များနှင့် ဗီဒီယိုများကို အောက်တွင် ပို့ပေးထားပါသည် 👇"
    )

    resources = get_resources_by_category(category)
    for title, r_type, source in resources:
        if r_type == "video":
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"🎬 **{title}**\n🔗 ကြည့်ရှုရန်: {source}",
                parse_mode="Markdown"
            )
        elif r_type == "book":
            if os.path.exists(source):
                with open(source, "rb") as pdf_file:
                    await context.bot.send_document(
                        chat_id=query.message.chat_id,
                        document=pdf_file,
                        caption=f"📖 ဆရာကြီးဒေါက်တာစိုးလွင်၏ စာအုပ်: **{title}**",
                        parse_mode="Markdown"
                    )

async def chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    user_mood = context.user_data.get("current_mood", "မသိရှိသေးပါ")

    # User History ကို ဆွဲယူခြင်း
    if "chat_history" not in context.user_data:
        context.user_data["chat_history"] = []

    history = context.user_data["chat_history"]

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    # History ပါဝင်သော Gemini Call
    bot_reply = await get_dhamma_guidance_with_history(user_mood, user_message, history)

    # History ထဲသို့ လက်ရှိ အမေးအဖြေ အသစ်ကို ထည့်သွင်းခြင်း
    history.append({"role": "user", "text": user_message})
    history.append({"role": "model", "text": bot_reply})

    # Memory မပြည့်စေရန် အမေးအဖြေ နောက်ဆုံး ၁၀ ခုသာ ထိန်းသိမ်းခြင်း
    if len(history) > 10:
        context.user_data["chat_history"] = history[-10:]

    await update.message.reply_text(bot_reply)

# ----------------- MAIN FUNCTION -----------------
def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Scheduler JobQueue စတင်ခြင်း (မြန်မာစံတော်ချိန် မနက် ၈:၀၀ နာရီတွင် နေ့စဉ် ပို့ပေးမည်)
    job_queue = app.job_queue
    if job_queue:
        mm_tz = pytz.timezone("Asia/Yangon")
        reminder_time = datetime.time(hour=8, minute=0, second=0, tzinfo=mm_tz)
        job_queue.run_daily(send_daily_dhamma, time=reminder_time)
        print("Daily Reminder Scheduler စတင် အသက်ဝင်နေပါပြီ...")

    # Handlers စာရင်း
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(mood_button_handler, pattern="^mood_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_handler))

    print("Bot is running...")

# Dummy web server ကို background task အနေနဲ့ run ရန်
    app.post_init = lambda application: start_dummy_server()

    print("Bot is running...")
  
    app.run_polling()

# Render ကျေနပ်စေရန် dummy web server အသေးစား
async def handle_ping(request):
    return web.Response(text="Bot is running alive!")

async def start_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    app_web = web.Application()
    app_web.router.add_get("/", handle_ping)
    runner = web.AppRunner(app_web)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

if __name__ == "__main__":
    main()