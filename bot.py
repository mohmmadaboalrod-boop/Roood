import os
import threading
import time
import urllib.request
from datetime import datetime
from collections import Counter
from flask import Flask

# مكتبة Telegram Bot
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)

# مكتبات إنشاء PDF ودعم العربية
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
from reportlab.lib import colors
import arabic_reshaper
from bidi.algorithm import get_display

# ==================== الإعدادات العامة ====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "ضع_توكن_البوت_هنا")
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "")  # رابط تطبيقك على Render

# معرفات المستخدمين المسموح لهم (6 مستخدمين)
ALLOWED_USERS = [123456789, 987654321, 112233445, 556677889, 990011223, 443322110]

# معرفات المشرفين / المدراء
ADMIN_IDS = [123456789, 999888777]

# حالات المحادثة
NAME, TIME = range(2)

# ==================== حفظ البيانات في الذاكرة (بدون DB) ====================
# قائمة في الذاكرة لتخزين السجلات مؤقتاً
RECORDS = []

def save_record(user_id, action_type, full_name, action_time):
    RECORDS.append({
        "user_id": user_id,
        "action_type": action_type,
        "full_name": full_name,
        "action_time": action_time,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })

def get_multiple_actions():
    # حساب عدد مرات تسجيل كل اسم
    counts = Counter(r["full_name"] for r in RECORDS)
    return [(name, count) for name, count in counts.items() if count > 1]

def reshape_text(text):
    reshaped = arabic_reshaper.reshape(text)
    return get_display(reshaped)

# ==================== معالجات الأوامر والمحادثة ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in ALLOWED_USERS and user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ عذراً، ليس لديك صلاحية لاستخدام هذا البوت.")
        return ConversationHandler.END

    keyboard = [["دخول", "خروج"]]
    
    if user_id in ADMIN_IDS:
        keyboard.append(["📄 استخراج ملف PDF", "🔄 الخروج المتعدد"])

    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("أهلاً بك! يرجى اختيار الإجراء المطلوب:", reply_markup=reply_markup)

async def handle_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    if user_id in ADMIN_IDS:
        if text == "📄 استخراج ملف PDF":
            await generate_and_send_pdf(update, context)
            return ConversationHandler.END
        elif text == "🔄 الخروج المتعدد":
            await show_multiple_exits(update, context)
            return ConversationHandler.END

    if text in ["دخول", "خروج"]:
        context.user_data["action_type"] = text
        await update.message.reply_text(
            f"اخترت ({text}).\n\nالسؤال الأول: يرجى إدخال **الاسم الثلاثي**:",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="Markdown"
        )
        return NAME
    else:
        await update.message.reply_text("يرجى اختيار أحد الأزرار المتاحة.")
        return ConversationHandler.END

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["full_name"] = update.message.text
    action = context.user_data["action_type"]
    
    await update.message.reply_text(
        f"السؤال الثاني: يرجى إدخال **ساعة {action}** (مثال: 08:30 صباحاً):",
        parse_mode="Markdown"
    )
    return TIME

async def get_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    action_time = update.message.text
    user_id = update.effective_user.id
    full_name = context.user_data["full_name"]
    action_type = context.user_data["action_type"]

    save_record(user_id, action_type, full_name, action_time)

    await update.message.reply_text(
        f"✅ تم تسجيل العملية بنجاح!\n\n"
        f"👤 الاسم: {full_name}\n"
        f"📌 نوع الإجراء: {action_type}\n"
        f"⏰ الوقت: {action_time}"
    )

    await start(update, context)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("تم إلغاء العملية.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# ==================== تقارير المشرف ====================
async def generate_and_send_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not RECORDS:
        await update.message.reply_text("لا توجد سجلات مسجلة في الذاكرة حتى الآن.")
        return

    pdf_filename = "attendance_report.pdf"
    doc = SimpleDocTemplate(pdf_filename, pagesize=letter)
    elements = []

    data = [[
        reshape_text("التاريخ والوقت"), 
        reshape_text("الساعة المحددة"), 
        reshape_text("الاسم الثلاثي"), 
        reshape_text("نوع الإجراء")
    ]]
    
    for r in reversed(RECORDS):
        data.append([
            reshape_text(r["created_at"]),
            reshape_text(r["action_time"]),
            reshape_text(r["full_name"]),
            reshape_text(r["action_type"])
        ])

    table = Table(data, colWidths=[130, 110, 180, 80])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#102A43")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor("#F0F4F8")),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor("#BCCCDC")),
    ]))

    elements.append(table)
    doc.build(elements)

    with open(pdf_filename, "rb") as file:
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=file,
            caption="📄 تقرير حركة الدخول والخروج المسجلة."
        )

async def show_multiple_exits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    multiple_records = get_multiple_actions()
    if not multiple_records:
        await update.message.reply_text("لا يوجد أشخاص تكرر تسجيلهم أكثر من مرة.")
        return

    message = "🔄 **قائمة الأشخاص الذين تكرر تسجيلهم أكثر من مرة:**\n\n"
    for name, count in multiple_records:
        message += f"• **{name}**: تم التسجيل {count} مرات\n"

    await update.message.reply_text(message, parse_mode="Markdown")

# ==================== خادم Flask + إبقاء البوت نشطاً 24/7 ====================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive and running!"

def keep_alive_ping():
    """حلقة تفحص رابط الموقع كل 10 دقائق لمنعه من الخمول"""
    while True:
        time.sleep(600)  # كل 10 دقائق
        if RENDER_URL:
            try:
                urllib.request.urlopen(RENDER_URL)
                print("Keep-alive ping sent successfully.")
            except Exception as e:
                print(f"Ping failed: {e}")

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# ==================== تشغيل التطبيق ====================
def main():
    # تشغيل خادم Flask
    threading.Thread(target=run_flask, daemon=True).start()
    
    # تشغيل التنبيه الذاتي لمنع السكون
    threading.Thread(target=keep_alive_ping, daemon=True).start()

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^(دخول|خروج|📄 استخراج ملف PDF|🔄 الخروج المتعدد)$"), handle_choice)
        ],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_time)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)

    print("البوت يعمل الآن...")
    application.run_polling()

if __name__ == "__main__":
    main()
