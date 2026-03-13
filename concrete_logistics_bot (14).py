import os
import sqlite3
import logging
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_PATH = "logistics.db"

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

ASK_JOB, ASK_PLATE, ASK_PLATE_MANUAL, ASK_GRADE, ASK_VOLUME = range(5)

STATUS_EMOJI = {
    "active": "🟢",
    "completed": "✅",
    "cancelled": "❌"
}

# ─────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────

def init_db():
    with sqlite3.connect(DB_PATH) as conn:

        conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            location TEXT,
            status TEXT,
            created_at TEXT
        )
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS trucks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plate TEXT UNIQUE,
            added_at TEXT
        )
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS trips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            job_name TEXT,
            truck_plate TEXT,
            grade TEXT,
            volume REAL
        )
        """)

        conn.commit()


def add_job(name, location):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO jobs (name,location,status,created_at) VALUES (?,?,?,?)",
            (name, location, "active", datetime.now().isoformat())
        )
        conn.commit()


def add_truck(plate):
    plate = plate.upper().replace(" ", "")
    with sqlite3.connect(DB_PATH) as conn:
        try:
            conn.execute(
                "INSERT INTO trucks (plate,added_at) VALUES (?,?)",
                (plate, datetime.now().isoformat())
            )
            conn.commit()
        except:
            pass


def get_jobs(status=None):

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row

        if status:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status=?",
                (status,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM jobs").fetchall()

    return [dict(r) for r in rows]


def get_job_by_id(job_id):

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM jobs WHERE id=?",
            (job_id,)
        ).fetchone()

    return dict(row) if row else None


def get_trucks():

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM trucks").fetchall()

    return [dict(r) for r in rows]


def save_trip(job_name, truck_plate, grade, volume):

    with sqlite3.connect(DB_PATH) as conn:

        conn.execute(
            """
            INSERT INTO trips
            (timestamp,job_name,truck_plate,grade,volume)
            VALUES (?,?,?,?,?)
            """,
            (
                datetime.now().isoformat(),
                job_name,
                truck_plate,
                grade,
                volume
            )
        )

        conn.commit()


def get_job_grade_breakdown(job):

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row

        rows = conn.execute(
            """
            SELECT grade,
            SUM(volume) as total,
            COUNT(*) as trips
            FROM trips
            WHERE job_name=?
            GROUP BY grade
            """,
            (job,)
        ).fetchall()

    return rows


# ─────────────────────────────────────────────
# MENU
# ─────────────────────────────────────────────

def main_menu():

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton("➕ Log Trip", callback_data="log_trip")
        ],

        [
            InlineKeyboardButton("🏗 Job Status", callback_data="job_status")
        ]
    ])


# ─────────────────────────────────────────────
# START
# ─────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "Concrete Dispatch Bot",
        reply_markup=main_menu()
    )


# ─────────────────────────────────────────────
# JOB STATUS
# ─────────────────────────────────────────────

async def job_status(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    jobs = get_jobs()

    if not jobs:

        await query.edit_message_text(
            "No jobs available",
            reply_markup=main_menu()
        )
        return

    lines = []

    for j in jobs:

        emoji = STATUS_EMOJI.get(j["status"], "⬜")

        grades = get_job_grade_breakdown(j["name"])

        grade_lines = ""

        for g in grades:

            grade_lines += f"\n   └ {g['grade']} → {g['total']} m³ ({g['trips']} trips)"

        if not grade_lines:
            grade_lines = "\n   _No concrete yet_"

        lines.append(
            f"{emoji} {j['name']}\n"
            f"📍 {j['location']}{grade_lines}"
        )

    text = "🏗 Job Status\n\n" + "\n\n".join(lines)

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅ Back", callback_data="back")]
        ])
    )


# ─────────────────────────────────────────────
# LOG TRIP FLOW
# ─────────────────────────────────────────────

async def log_trip_start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    jobs = get_jobs("active")

    buttons = [
        [InlineKeyboardButton(j["name"], callback_data=f"job_{j['id']}")]
        for j in jobs
    ]

    await query.message.reply_text(
        "Select job:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

    return ASK_JOB


async def job_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    job_id = int(query.data.split("_")[1])
    job = get_job_by_id(job_id)

    context.user_data["job"] = job["name"]

    trucks = get_trucks()

    buttons = [
        [InlineKeyboardButton(t["plate"], callback_data=f"truck_{t['plate']}")]
        for t in trucks
    ]

    buttons.append(
        [InlineKeyboardButton("Manual Plate", callback_data="manual")]
    )

    await query.message.reply_text(
        f"Job: {job['name']}\nSelect truck:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

    return ASK_PLATE


async def truck_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    if query.data == "manual":

        await query.message.reply_text(
            "Enter truck plate:"
        )

        return ASK_PLATE_MANUAL

    plate = query.data.split("_")[1]

    context.user_data["truck"] = plate

    grades = ["C25", "C30", "C35", "C40"]

    buttons = [
        [InlineKeyboardButton(g, callback_data=f"grade_{g}")]
        for g in grades
    ]

    await query.message.reply_text(
        "Select grade:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

    return ASK_GRADE


async def manual_plate(update: Update, context: ContextTypes.DEFAULT_TYPE):

    plate = update.message.text.upper().replace(" ", "")

    context.user_data["truck"] = plate

    grades = ["C25", "C30", "C35", "C40"]

    buttons = [
        [InlineKeyboardButton(g, callback_data=f"grade_{g}")]
        for g in grades
    ]

    await update.message.reply_text(
        "Select grade:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

    return ASK_GRADE


async def grade_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    grade = query.data.split("_")[1]

    context.user_data["grade"] = grade

    await query.message.reply_text(
        f"Enter volume for {grade} (m³):"
    )

    return ASK_VOLUME


async def volume_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):

    try:

        volume = float(update.message.text)

        save_trip(
            context.user_data["job"],
            context.user_data["truck"],
            context.user_data["grade"],
            volume
        )

        await update.message.reply_text(
            "Trip saved",
            reply_markup=main_menu()
        )

        context.user_data.clear()

        return ConversationHandler.END

    except:

        await update.message.reply_text(
            "Enter a valid number"
        )

        return ASK_VOLUME


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():

    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(

        entry_points=[
            CallbackQueryHandler(log_trip_start, pattern="log_trip")
        ],

        states={

            ASK_JOB: [
                CallbackQueryHandler(job_selected, pattern="job_")
            ],

            ASK_PLATE: [
                CallbackQueryHandler(truck_selected, pattern="truck_|manual")
            ],

            ASK_PLATE_MANUAL: [
                MessageHandler(filters.TEXT, manual_plate)
            ],

            ASK_GRADE: [
                CallbackQueryHandler(grade_selected, pattern="grade_")
            ],

            ASK_VOLUME: [
                MessageHandler(filters.TEXT, volume_entered)
            ],
        },

        fallbacks=[]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(job_status, pattern="job_status"))
    app.add_handler(CallbackQueryHandler(lambda u,c: u.callback_query.edit_message_text("Menu",reply_markup=main_menu()), pattern="back"))

    logger.info("Bot running")

    app.run_polling()


if __name__ == "__main__":
    main()

