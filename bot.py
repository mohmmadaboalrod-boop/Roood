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
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import arabic_reshaper
from bidi.algorithm import get_display

# ==================== جلب المتغيرات من البيئة ====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "")

def parse_ids(env_var_name):
    """تحويل النص المفصول بفواصل في متغيرات البيئة إلى قائمة أرقام ID"""
    raw_val = os.getenv(env_var_name, "")
    return [int(x.strip()) for x in raw_val.replace(" ", "").split(",") if x.strip().isdigit()]

ALLOWED_USERS = parse_ids("ALLOWED_USERS")
ADMIN_IDS = parse_ids("ADMIN_IDS")

# حالات المحادثة
NAME, TIME, BROADCAST_MSG = range(3)

# ==================== حفظ البيانات في الذاكرة ====================
RECORDS = []

def save_record(user_id, action_type, full_name, action_time):
    RECORDS.append({
        "user_id": user_id,
        "action_type": action_type,
        "full_name": full_name,
        "action_time": action_time,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })

# ==================== إعداد الخط العربي للـ PDF ====================
FONT_PATH = "Amiri-Regular.ttf"

def setup_arabic_font():
    """تحميل تسجيل الخط العربي لمنع ظهور المربعات والرموز"""
    if not os.path.exists(FONT_PATH):
        try:
            url = "https://github.com/google/fonts/raw/main/ofl/amiri/Amiri-Regular.ttf"
            urllib.request.urlretrieve(url, FONT_PATH)
        except Exception as e:
            print(f"خطأ في تحميل الخط العربي: {e}")
    
    if os.path.exists(FONT_PATH):
        pdfmetrics.registerFont(TTFont("AmiriFont", FONT_PATH))
        return "AmiriFont"
    return "Helvetica"

def reshape_text(text):
    """إعادة تشكيل النص العربي للظهور بشكل صحيح من اليمين لليار"""
    reshaped = arabic_reshaper.reshape(text)
    return get_display(reshaped)

# ==================== بناء ملفات PDF ====================
def build_pdf_report(records, title_text, filename="report.pdf"):
    font_name = setup_arabic_font()
    doc = SimpleDocTemplate(filename, pagesize=letter)
    elements = []

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'ArabicTitle',
        parent=styles['Heading1'],
        fontName=font_name,
        fontSize=16,
        alignment=1, # محاذاة للوسط
        spaceAfter=15
    )

    elements.append(Paragraph(reshape_text(title_text), title_style))
    elements.append(Spacer(1, 10))

    data = [[
        reshape_text("التاريخ والوقت"),
        reshape_text("الساعة المحددة"),
        reshape_text("الاسم الثلاثي"),
        reshape_text("نوع الإجراء")
    ]]

    for r in reversed(records):
        data.append([
            reshape_text(r["created_at"]),
            reshape_text(r["action_time"]),
            reshape_text(r["full_name"]),
            reshape_text(r["action_type"])
        ])

    table = Table(data, colWidths=[130, 110, 180, 80])
    table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), font_name),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#102A43")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor("#F0F4F8")),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor("#BCCCDC")),
    ]))

    elements.append(table)
    doc.build(elements)
    return filename

# ==================== التحكم بالأوامر والشاشات ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # شاشة المدير (أزرار المشرفين فقط)
    if user_id in ADMIN_IDS:
        keyboard = [
            ["📄 استخراج pdf", "🔄 الخروج المتعدد"],
            ["📢 تعميم"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("أهلاً بك يا مدير! اختر الإجراء المطلوب من القائمة:", reply_markup=reply_markup)
        return ConversationHandler.END

    # شاشة المستخدمين (أزرار دخول وخروج فقط)
    elif user_id in ALLOWED_USERS:
        keyboard = [["دخول", "خروج"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("أهلاً بك! اختر الإجراء المطلوب:", reply_markup=reply_markup)
        return ConversationHandler.END

    else:
        await update.message.reply_text("❌ عذراً، ليس لديك صلاحية لاستخدام هذا البوت.")
        return ConversationHandler.END

async def handle_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    # معالجة أزرار المدير
    if user_id in ADMIN_IDS:
        if text == "📄 استخراج pdf":
            if not RECORDS:
                await update.message.reply_text("لا توجد سجلات حالية لإستخراج التقرير.")
                return ConversationHandler.END
            
            pdf_file = build_pdf_report(RECORDS, "تقرير حركة الدخول والخروج العامة", "all_records.pdf")
            with open(pdf_file, "rb") as f:
                await context.bot.send_document(chat_id=user_id, document=f, caption="📄 تقرير السجلات الشامل.")
            return ConversationHandler.END

        elif text == "🔄 الخروج المتعدد":
            # تصفية الأشخاص الذين تكرر تسجيلهم أكثر من مرة
            counts = Counter(r["full_name"] for r in RECORDS)
            multi_names = {name for name, cnt in counts.items() if cnt > 1}
            multi_records = [r for r in RECORDS if r["full_name"] in multi_names]

            if not multi_records:
                await update.message.reply_text("لا يوجد أشخاص قاموا بالدخول/الخروج أكثر من مرة.")
                return ConversationHandler.END

            pdf_file = build_pdf_report(multi_records, "تقرير الأشخاص المسجلين أكثر من مرة", "multiple_records.pdf")
            with open(pdf_file, "rb") as f:
                await context.bot.send_document(chat_id=user_id, document=f, caption="🔄 تقرير الأشخاص الذين تكرر تسجيلهم.")
            return ConversationHandler.END

        elif text == "📢 تعميم":
            await update.message.reply_text("يرجى كتابة نص التعميم المطلوب إرساله للجميع:")
            return BROADCAST_MSG

    # معالجة أزرار المستخدمين
    if user_id in ALLOWED_USERS and text in ["دخول", "خروج"]:
        context.user_data["action_type"] = text
        await update.message.reply_text(
            f"اخترت ({text}).\n\nالسؤال الأول: يرجى إدخال **الاسم الثلاثي**:",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="Markdown"
        )
        return NAME

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

    # حفظ السجل
    save_record(user_id, action_type, full_name, action_time)

    # تأكيد للمستخدم
    await update.message.reply_text(
        f"✅ تم تسجيل العملية بنجاح!\n\n"
        f"👤 الاسم: {full_name}\n"
        f"📌 نوع الإجراء: {action_type}\n"
        f"⏰ الوقت: {action_time}"
    )

    # إرسال إشعار فورى لجميع المدراء
    admin_notice = (
        f"🔔 **إشعار جديد:**\n\n"
        f"👤 **الاسم الثلاثي:** {full_name}\n"
        f"📌 **الإجراء:** {action_type}\n"
        f"⏰ **الوقت:** {action_time}\n"
        f"🆔 **معرف المستخدم:** `{user_id}`"
    )
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=admin_notice, parse_mode="Markdown")
        except Exception as e:
            print(f"فشل إرسال الإشعار للمدير {admin_id}: {e}")

    await start(update, context)
    return ConversationHandler.END

async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    broadcast_text = update.message.text
    all_recipients = set(ALLOWED_USERS + ADMIN_IDS)
    success_count = 0

    for uid in all_recipients:
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=f"📢 **تنبيه / تعميم من الإدارة:**\n\n{broadcast_text}",
                parse_mode="Markdown"
            )
            success_count += 1
        except Exception as e:
            print(f"فشل إرسال التعميم إلى {uid}: {e}")

    await update.message.reply_text(f"✅ تم إرسال التعميم بنجاح إلى ({success_count}) مستخدم.")
    await start(update, context)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("تم إلغاء العملية.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# ==================== خادم التشغيل الدائم 24/7 ====================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running 24/7!"

def keep_alive_ping():
    while True:
        time.sleep(600)
        if RENDER_URL:
            try:
                urllib.request.urlopen(RENDER_URL)
            except Exception as e:
                print(f"Ping failed: {e}")

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# ==================== التشغيل ====================
def main():
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=keep_alive_ping, daemon=True).start()

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^(دخول|خروج|📄 استخراج pdf|🔄 الخروج المتعدد|📢 تعميم)$"), handle_choice)
        ],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_time)],
            BROADCAST_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_broadcast)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)

    print("البوت يعمل بنجاح...")
    application.run_polling()

if __name__ == "__main__":
    main()
