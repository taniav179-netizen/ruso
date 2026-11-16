# -*- coding: utf-8 -*-
import os
import random
import sqlite3
import asyncio
import logging
from datetime import date, datetime
import pytz
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import FSInputFile, InputMediaPhoto
from config import BOT_TOKEN, ADMIN_ID

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

DB_PATH = "/root/bots/lms_bot/lms_database.db"

POPULAR_TIMEZONES = [
    ("Argentina (UTC-3)", "America/Argentina/Buenos_Aires"),
    ("España / Madrid (UTC+1/+2)", "Europe/Madrid"),
    ("México (UTC-6)", "America/Mexico_City"),
    ("Colombia / Perú (UTC-5)", "America/Bogota"),
    ("Chile (UTC-3)", "America/Santiago"),
    ("Moscú (UTC+3)", "Europe/Moscow"),
]

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db_full():
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS students (
            telegram_id INTEGER PRIMARY KEY,
            full_name TEXT,
            username TEXT,
            timezone TEXT DEFAULT 'America/Argentina/Buenos_Aires',
            current_streak INTEGER DEFAULT 0,
            last_activity DATE,
            is_active BOOLEAN DEFAULT 1,
            daily_questions_count INTEGER DEFAULT 2
        )
    ''')
    try:
        c.execute("ALTER TABLE students ADD COLUMN timezone TEXT DEFAULT 'America/Argentina/Buenos_Aires'")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE students ADD COLUMN daily_questions_count INTEGER DEFAULT 2")
    except sqlite3.OperationalError:
        pass

    c.execute('''
        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            tag TEXT UNIQUE NOT NULL,
            image_url TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS student_topics (
            student_id INTEGER,
            topic_id INTEGER,
            is_enabled BOOLEAN DEFAULT 0,
            PRIMARY KEY (student_id, topic_id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_tag TEXT,
            task_type TEXT,
            question_text TEXT,
            options TEXT,
            correct_answer TEXT,
            explanation TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS error_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            question_text TEXT,
            wrong_answer TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    c.execute("INSERT OR IGNORE INTO topics (id, name, tag, image_url) VALUES (1, 'Verbos. Conjugaci\u00f3n I', 'verb_group_1', '/root/bots/lms_bot/card1.jpg')")
    c.execute("INSERT OR IGNORE INTO topics (id, name, tag, image_url) VALUES (2, 'Verbos. Conjugaci\u00f3n II', 'verb_group_2', '/root/bots/lms_bot/card2.jpg')")
    c.execute("INSERT OR IGNORE INTO topics (id, name, tag, image_url) VALUES (3, 'Verbos. Conjugaci\u00f3n I y II', 'verb_group_mixed', '/root/bots/lms_bot/card1.jpg|/root/bots/lms_bot/card2.jpg')")
    conn.commit()
    conn.close()

user_last_msgs = {}

def track_msg(uid, msg_id):
    if uid not in user_last_msgs:
        user_last_msgs[uid] = []
    user_last_msgs[uid].append(msg_id)

def log_error(uid, question, wrong_ans):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("INSERT INTO error_logs (student_id, question_text, wrong_answer) VALUES (?, ?, ?)",
                  (uid, question, wrong_ans))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Error logging: {e}")

def get_active_topic(uid):
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute('''
            SELECT t.tag, t.name, t.image_url 
            FROM student_topics st
            JOIN topics t ON st.topic_id = t.id
            WHERE st.student_id = ? AND st.is_enabled = 1
            LIMIT 1
        ''', (uid,))
        row = c.fetchone()
        conn.close()
        if row:
            return (row[0], row[1], row[2])
    except Exception:
        conn.close()
    return ("verb_group_1", "Verbos. Conjugaci\u00f3n I", "/root/bots/lms_bot/card1.jpg")

def get_random_tasks_for_student(student_id: int, topic_tag: str):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT daily_questions_count FROM students WHERE telegram_id = ?", (student_id,))
    row = c.fetchone()
    count = row[0] if row and row[0] else 2

    c.execute("SELECT id, question_text, options, correct_answer, explanation FROM tasks WHERE topic_tag = ? AND task_type = 'test'", (topic_tag,))
    tasks = c.fetchall()
    if not tasks:
        c.execute("SELECT id, question_text, options, correct_answer, explanation FROM tasks WHERE task_type = 'test'")
        tasks = c.fetchall()
    conn.close()

    if not tasks:
        return []
    sample_size = min(count, len(tasks))
    return random.sample(tasks, sample_size)

# ================= 1. /start И ИНСТРУКЦИИ =================
@dp.message(Command("start"))
async def start_handler(message: types.Message):
    uid = message.from_user.id
    name = message.from_user.first_name or "estudiante"

    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('''
            INSERT OR IGNORE INTO students (telegram_id, full_name, username)
            VALUES (?, ?, ?)
        ''', (uid, message.from_user.full_name, message.from_user.username))
        c.execute('''
            INSERT OR IGNORE INTO student_topics (student_id, topic_id, is_enabled)
            VALUES (?, 1, 1)
        ''', (uid,))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Error saving student: {e}")

    builder = InlineKeyboardBuilder()
    builder.button(text="Empezar el d\u00eda \u2600\ufe0f", callback_data="start_daily_flow")
    builder.button(text="\u2699\ufe0f Configuraci\u00f3n (/settings)", callback_data="open_settings_from_start")
    builder.button(text="\u2753 \u00bfC\u00f3mo usar el bot?", callback_data="show_instructions")
    builder.adjust(1)

    text = (
        f"\u00a1Hola, {name}! \U0001f44b\n\n"
        "Bienvenido/a al bot de pr\u00e1ctica de ruso.\n\n"
        "\U0001f4cc <b>\u00bfC\u00f3mo funciona?</b>\n"
        "\u2022 Todos los d\u00edas a las 09:00 recibir\u00e1s tu pr\u00e1ctica diaria.\n"
        "\u2022 Puedes configurar tu zona horaria y cantidad de preguntas con /settings.\n"
        "\u2022 Mant\u00e9n tu racha respondiendo todos los d\u00edas."
    )
    msg = await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    track_msg(uid, msg.message_id)

@dp.callback_query(F.data == "show_instructions")
async def show_instructions_handler(callback: types.CallbackQuery):
    instructions = (
        "\u2139\ufe0f <b>Instrucciones de uso:</b>\n\n"
        "1. Usa /settings para cambiar tu zona horaria y cu\u00e1ntas preguntas diarias responder (2 a 10).\n"
        "2. A las 09:00 de tu hora local recibir\u00e1s un aviso con el bot\u00f3n de inicio.\n"
        "3. Si a las 20:00 a\u00fan no has practicado, recibir\u00e1s un recordatorio.\n"
        "4. Primero repasa la tarjeta y luego presiona <b>\u00a1Estoy listo/a!</b> para resolver el quiz."
    )
    await callback.answer()
    await callback.message.answer(instructions, parse_mode="HTML")

# ================= 2. НАСТРОЙКИ (/settings): ВОПРОСЫ И ЧАСОВОЙ ПОЯС =================
async def send_settings_menu(user_id: int, message_or_call):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT daily_questions_count, timezone FROM students WHERE telegram_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()

    count = row[0] if row and row[0] else 2
    tz_val = row[1] if row and row[1] else "America/Argentina/Buenos_Aires"

    builder = InlineKeyboardBuilder()
    builder.button(text=f"\U0001f522 Preguntas diarias: {count}", callback_data="cfg_change_qcount")
    builder.button(text="\U0001f30d Cambiar zona horaria", callback_data="cfg_change_tz")
    builder.adjust(1)

    txt = (
        "\u2699\ufe0f <b>Configuraci\u00f3n personal:</b>\n\n"
        f"\u2022 Preguntas por d\u00eda: <b>{count}</b>\n"
        f"\u2022 Zona horaria actual: <code>{tz_val}</code>\n\n"
        "\u00bfQu\u00e9 deseas modificar?"
    )
    if isinstance(message_or_call, types.CallbackQuery):
        await message_or_call.answer()
        await message_or_call.message.answer(txt, reply_markup=builder.as_markup(), parse_mode="HTML")
    else:
        await message_or_call.answer(txt, reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.message(Command("settings"))
async def cmd_settings(message: types.Message):
    await send_settings_menu(message.from_user.id, message)

@dp.callback_query(F.data == "open_settings_from_start")
async def open_settings_callback(callback: types.CallbackQuery):
    await send_settings_menu(callback.from_user.id, callback)

@dp.callback_query(F.data == "cfg_back")
async def back_to_settings(callback: types.CallbackQuery):
    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        pass
    await send_settings_menu(callback.from_user.id, callback)

@dp.callback_query(F.data == "cfg_change_qcount")
async def show_qcount_picker(callback: types.CallbackQuery):
    uid = callback.from_user.id
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT daily_questions_count FROM students WHERE telegram_id = ?", (uid,))
    row = c.fetchone()
    conn.close()
    current_count = row[0] if row and row[0] else 2

    builder = InlineKeyboardBuilder()
    for num in range(2, 11):
        icon = "\U0001f518" if num == current_count else "\u26aa"
        builder.button(text=f"{icon} {num}", callback_data=f"set_qcount_{num}")
    builder.button(text="\U0001f519 Volver a ajustes", callback_data="cfg_back")
    builder.adjust(3, 3, 3, 1)

    await callback.message.edit_text(
        "\U0001f522 <b>Elige la cantidad de preguntas diarias (de 2 a 10):</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("set_qcount_"))
async def save_qcount_setting(callback: types.CallbackQuery):
    new_count = int(callback.data.split("_")[2])
    uid = callback.from_user.id

    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE students SET daily_questions_count = ? WHERE telegram_id = ?", (new_count, uid))
    conn.commit()
    conn.close()

    await callback.answer(f"\u00a1Guardado! Ahora recibir\u00e1s {new_count} preguntas al d\u00eda.", show_alert=True)
    await send_settings_menu(uid, callback)

@dp.callback_query(F.data == "cfg_change_tz")
async def show_tz_picker(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    for label, tz_name in POPULAR_TIMEZONES:
        builder.button(text=label, callback_data=f"settz_{tz_name}")
    builder.button(text="\U0001f519 Volver a ajustes", callback_data="cfg_back")
    builder.adjust(1)

    await callback.message.edit_text(
        "\U0001f30d <b>Selecciona tu pa\u00eds o zona horaria:</b>\n\n"
        "Los recordatorios de las 09:00 y 20:00 se enviar\u00e1n seg\u00fan tu selecci\u00f3n.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("settz_"))
async def save_tz_setting(callback: types.CallbackQuery):
    tz_name = callback.data.replace("settz_", "")
    uid = callback.from_user.id

    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE students SET timezone = ? WHERE telegram_id = ?", (tz_name, uid))
    conn.commit()
    conn.close()

    await callback.answer("\u00a1Zona horaria guardada!", show_alert=True)
    await send_settings_menu(uid, callback)

# ================= 3. КАРТОЧКИ И ВОПРОСЫ =================
@dp.callback_query(F.data == "start_daily_flow")
async def show_miro_card(callback: types.CallbackQuery):
    uid = callback.from_user.id
    topic_info = get_active_topic(uid)
    tag, name, img_field = topic_info[0], topic_info[1], topic_info[2]

    builder = InlineKeyboardBuilder()
    builder.button(text="\u00a1Estoy listo/a! \u27a1\ufe0f", callback_data=f"show_q1_{tag}")

    caption = (
        f"\U0001f4d8 <b>Tema: {name}</b>\n\n"
        "Revisa el material en la imagen para recordar la regla.\n"
        "Cuando est\u00e9s listo/a, presiona el bot\u00f3n para comenzar las preguntas."
    )

    try:
        await callback.message.delete()
    except Exception:
        pass

    img_paths = [p.strip() for p in img_field.split("|")]
    valid_paths = [p for p in img_paths if os.path.exists(p)]

    if len(valid_paths) == 2:
        media = [
            InputMediaPhoto(media=FSInputFile(valid_paths[0])),
            InputMediaPhoto(media=FSInputFile(valid_paths[1]), caption=caption, parse_mode="HTML")
        ]
        album_msgs = await bot.send_media_group(chat_id=uid, media=media)
        for m in album_msgs:
            track_msg(uid, m.message_id)
        btn_msg = await bot.send_message(
            chat_id=uid,
            text="\U0001f447 Presiona el bot\u00f3n когда termines de repasar:",
            reply_markup=builder.as_markup()
        )
        track_msg(uid, btn_msg.message_id)
    elif len(valid_paths) == 1:
        msg = await bot.send_photo(
            chat_id=uid,
            photo=FSInputFile(valid_paths[0]),
            caption=caption,
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        track_msg(uid, msg.message_id)
    else:
        msg = await bot.send_message(
            chat_id=uid,
            text=caption,
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        track_msg(uid, msg.message_id)

    await callback.answer()

@dp.callback_query(F.data.startswith("show_q1_"))
async def start_quiz_session(callback: types.CallbackQuery):
    uid = callback.from_user.id
    topic_tag = callback.data.replace("show_q1_", "")

    tasks = get_random_tasks_for_student(uid, topic_tag)
    if not tasks:
        await callback.answer("No hay preguntas disponibles en la base de datos.", show_alert=True)
        return

    try:
        await callback.message.delete()
    except Exception:
        pass

    task_ids = ",".join(str(t[0]) for t in tasks)
    await send_quiz_step(uid, task_ids_str=task_ids, current_index=0)
    await callback.answer()

async def send_quiz_step(user_id: int, task_ids_str: str, current_index: int):
    task_ids = task_ids_str.split(",")
    total_tasks = len(task_ids)
    current_task_id = int(task_ids[current_index])

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT question_text, options, correct_answer FROM tasks WHERE id = ?", (current_task_id,))
    q_data = c.fetchone()
    conn.close()

    if not q_data:
        return

    q_text = q_data[0]
    options_raw = q_data[1] or ""
    correct_ans = q_data[2] or ""

    builder = InlineKeyboardBuilder()
    if options_raw:
        for opt in options_raw.split("|"):
            opt_clean = opt.strip()
            is_corr = "1" if opt_clean == correct_ans.strip() else "0"
            builder.button(text=opt_clean, callback_data=f"ansstep_{is_corr}_{task_ids_str}_{current_index}")
    builder.adjust(2)

    msg = await bot.send_message(
        user_id,
        f"\u2753 <b>Pregunta {current_index + 1}/{total_tasks}:</b>\n\n{q_text}",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    track_msg(user_id, msg.message_id)

@dp.callback_query(F.data.startswith("ansstep_"))
async def process_quiz_answer(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    is_corr = parts[1]
    task_ids_str = parts[2]
    current_index = int(parts[3])
    task_ids = task_ids_str.split(",")
    total_tasks = len(task_ids)
    uid = callback.from_user.id

    current_task_id = int(task_ids[current_index])

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT question_text, correct_answer, explanation FROM tasks WHERE id = ?", (current_task_id,))
    q_data = c.fetchone()

    if is_corr == "1":
        text_res = callback.message.text + "\n\n\u2705 \u00a1Correcto! \u00a1Muy bien!"
    else:
        explanation = q_data[2] or q_data[1]
        log_error(uid, q_data[0], f"Respuesta: {q_data[1]} | Regla: {explanation}")
        text_res = callback.message.text + f"\n\n\U0001f4a1 Revisa la regla e int\u00e9ntalo de nuevo:\n<i>{explanation}</i>"
        c.execute("UPDATE students SET current_streak = 0 WHERE telegram_id = ?", (uid,))

    c.execute("UPDATE students SET last_activity = ? WHERE telegram_id = ?", (date.today().isoformat(), uid))
    conn.commit()
    conn.close()

    if current_index + 1 >= total_tasks:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT current_streak FROM students WHERE telegram_id = ?", (uid,))
        s_row = c.fetchone()
        streak = (s_row[0] or 0) + 1 if is_corr == "1" else 0
        c.execute("UPDATE students SET current_streak = ? WHERE telegram_id = ?", (streak, uid))
        conn.commit()
        conn.close()

        if streak >= 5:
            try:
                await bot.send_message(
                    ADMIN_ID,
                    f"\U0001f389 <b>\u0423\u0447\u0435\u043d\u0438\u043a {callback.from_user.full_name} (\u0441\u0442\u0440\u0438\u043a 5 \u0434\u043d\u0435\u0439 \u0431\u0435\u0437 \u043e\u0448\u0438\u0431\u043e\u043a)!</b>\n"
                    f"\u0422\u0435\u043c\u0430 \u0443\u0441\u0432\u043e\u0435\u043d\u0430. \u041f\u0435\u0440\u0435\u043a\u043b\u044e\u0447\u0438\u0442\u0435 \u0435\u0433\u043e \u0447\u0435\u0440\u0435\u0437 /admin.",
                    parse_mode="HTML"
                )
            except Exception as e:
                logging.error(f"Error alerting admin: {e}")

        text_res += "\n\n\u00a1Hasta ma\u00f1ana! \U0001f44b"
        await callback.message.edit_text(text_res, parse_mode="HTML")
    else:
        await callback.message.edit_text(text_res, parse_mode="HTML")
        await asyncio.sleep(1)
        await send_quiz_step(uid, task_ids_str, current_index + 1)

    await callback.answer()

# ================= 4. АДМИНКА (/admin) =================
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if str(message.from_user.id) != str(ADMIN_ID):
        await message.answer("Acceso denegado.")
        return

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT telegram_id, full_name, username, current_streak FROM students")
    students = c.fetchall()
    conn.close()

    if not students:
        await message.answer("No hay alumnos registrados.")
        return

    builder = InlineKeyboardBuilder()
    for s in students:
        s_id, s_name, s_user, s_streak = s[0], s[1] or "Sin nombre", f"@{s[2]}" if s[2] else "", s[3] or 0
        builder.button(text=f"\U0001f464 {s_name} (\U0001f525 {s_streak})", callback_data=f"adm_stud_{s_id}")
    builder.adjust(1)

    await message.answer("\U0001f6e0 <b>Panel de Administrador</b>\n\nSelecciona un alumno:", reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("adm_stud_"))
async def manage_student_topics(callback: types.CallbackQuery):
    if str(callback.from_user.id) != str(ADMIN_ID):
        await callback.answer("Sin acceso", show_alert=True)
        return

    stud_id = int(callback.data.split("_")[2])
    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT full_name, current_streak, timezone, daily_questions_count FROM students WHERE telegram_id = ?", (stud_id,))
    st_row = c.fetchone()
    st_name = st_row[0] if st_row else f"ID {stud_id}"
    streak = st_row[1] if st_row else 0
    tz_val = st_row[2] if st_row and st_row[2] else "N/A"
    cnt_val = st_row[3] if st_row and st_row[3] else 2

    c.execute('''
        SELECT t.id, t.name, COALESCE(st.is_enabled, 0)
        FROM topics t
        LEFT JOIN student_topics st ON t.id = st.topic_id AND st.student_id = ?
    ''', (stud_id,))
    topics = c.fetchall()
    conn.close()

    builder = InlineKeyboardBuilder()
    for tid, tname, enabled in topics:
        icon = "\u2705" if enabled else "\u274c"
        builder.button(text=f"{icon} {tname}", callback_data=f"adm_tog_{stud_id}_{tid}")
    builder.button(text="\U0001f4cb Errores del alumno", callback_data=f"adm_err_{stud_id}")
    builder.button(text="\U0001f519 Volver a la lista", callback_data="adm_back_list")
    builder.adjust(1)

    card_text = (
        f"\U0001f464 Alumno: <b>{st_name}</b>\n"
        f"\U0001f525 Racha actual: <b>{streak} d\u00edas</b>\n"
        f"\U0001f522 Preguntas/d\u00eda: <b>{cnt_val}</b>\n"
        f"\U0001f30d Zona horaria: <code>{tz_val}</code>\n\n"
        f"Temas disponibles (toca para activar/desactivar):"
    )

    await callback.message.edit_text(
        card_text,
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("adm_tog_"))
async def toggle_topic_status(callback: types.CallbackQuery):
    if str(callback.from_user.id) != str(ADMIN_ID):
        await callback.answer("Sin acceso", show_alert=True)
        return

    parts = callback.data.split("_")
    stud_id = int(parts[2])
    topic_id = int(parts[3])

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT is_enabled FROM student_topics WHERE student_id = ? AND topic_id = ?", (stud_id, topic_id))
    row = c.fetchone()

    if row is None:
        c.execute("INSERT INTO student_topics (student_id, topic_id, is_enabled) VALUES (?, ?, 1)", (stud_id, topic_id))
    else:
        new_val = 0 if row[0] == 1 else 1
        c.execute("UPDATE student_topics SET is_enabled = ? WHERE student_id = ? AND topic_id = ?", (new_val, stud_id, topic_id))
    conn.commit()
    conn.close()

    await manage_student_topics(callback)

@dp.callback_query(F.data.startswith("adm_err_"))
async def show_student_errors(callback: types.CallbackQuery):
    if str(callback.from_user.id) != str(ADMIN_ID):
        await callback.answer("Sin acceso", show_alert=True)
        return

    stud_id = int(callback.data.split("_")[2])
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT question_text, wrong_answer, timestamp FROM error_logs WHERE student_id = ? ORDER BY id DESC LIMIT 10", (stud_id,))
    errs = c.fetchall()
    conn.close()

    builder = InlineKeyboardBuilder()
    builder.button(text="\U0001f519 Volver", callback_data=f"adm_stud_{stud_id}")

    if not errs:
        txt = "<b>El alumno a\u00fan no ha cometido errores.</b>"
    else:
        txt = "<b>\u00daltimos errores del alumno:</b>\n\n"
        for q, w, ts in errs:
            date_str = ts[:10] if ts else ""
            txt += f"\u2022 <b>Pregunta:</b> {q}\n  <b>Detalle:</b> {w} ({date_str})\n\n"

    try:
        await callback.message.edit_text(txt, reply_markup=builder.as_markup(), parse_mode="HTML")
    except Exception:
        await callback.message.answer(txt, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "adm_back_list")
async def back_to_admin_list(callback: types.CallbackQuery):
    try:
        await callback.message.delete()
    except Exception:
        pass
    await admin_panel(callback.message)
    await callback.answer()

# ================= 5. ТОЧКА ВХОДА =================
async def main():
    try:
        init_db_full()
    except Exception as e:
        logging.warning(f"DB init warning: {e}")
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info(">>> BOT_POLLING_STARTED <<<")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())