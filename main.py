# main.py
import asyncio
import logging
import random
import sqlite3
from aiogram.types import FSInputFile
from datetime import datetime, date
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BOT_TOKEN, ADMIN_ID, DB_NAME, DEFAULT_TIMEZONE
from database import init_db

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone=DEFAULT_TIMEZONE)

# Инициализируем БД
init_db()

# Глобальное хранилище ID отправленных сообщений для их очистки в 00:00
# { user_id: [msg_id1, msg_id2, ...] }
user_messages = {}

def track_msg(user_id: int, msg_id: int):
    if user_id not in user_messages:
        user_messages[user_id] = []
    user_messages[user_id].append(msg_id)

def get_db():
    return sqlite3.connect(DB_NAME)

# --- БАЗА ДАННЫХ И ЛОГИКА ---

def register_student(user_id: int, full_name: str, username: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO students (telegram_id, full_name, username)
        VALUES (?, ?, ?)
        ON CONFLICT(telegram_id) DO UPDATE SET full_name=?, username=?
    ''', (user_id, full_name, username, full_name, username))
    
    # Привязываем первую тему по умолчанию
    cursor.execute("SELECT id FROM topics WHERE tag = 'verb_group_1'")
    topic = cursor.fetchone()
    if topic:
        cursor.execute('''
            INSERT OR IGNORE INTO student_topics (student_id, topic_id, is_enabled)
            VALUES (?, ?, 1)
        ''', (user_id, topic[0]))

    # Создаем таблицу логов ошибок, если нет
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS error_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            question_text TEXT,
            wrong_answer TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def log_error(student_id: int, question: str, wrong_ans: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO error_logs (student_id, question_text, wrong_answer) VALUES (?, ?, ?)",
                   (student_id, question, wrong_ans))
    conn.commit()
    conn.close()

def get_active_topic(student_id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT t.tag, t.name, t.image_url 
        FROM topics t
        JOIN student_topics st ON t.id = st.topic_id
        WHERE st.student_id = ? AND st.is_enabled = 1
        LIMIT 1
    ''', (student_id,))
    row = cursor.fetchone()
    conn.close()
    return row if row else ("verb_group_1", "Verbos. Conjugación I", "https://miro.com/app/board/uXjVJURPg-w=/?moveToWidget=3458764640579743742&cot=14")

def get_random_tasks_for_student(student_id: int, topic_tag: str):
    """ Достает количество вопросов из настроек конкретного ученика """
    conn = get_db()
    cursor = conn.cursor()
    
    # Узнаем лимит пользователя
    cursor.execute("SELECT daily_questions_count FROM students WHERE telegram_id = ?", (student_id,))
    row = cursor.fetchone()
    count = row[0] if row and row[0] else 2

    # Берем вопросы
    cursor.execute("SELECT id, question_text, options, correct_answer, explanation FROM tasks WHERE topic_tag = ?", (topic_tag,))
    tasks = cursor.fetchall()
    conn.close()
    
    return random.sample(tasks, k=min(count, len(tasks))) if tasks else []

# --- РАССЫЛКА И ТАЙМЕРЫ ---

async def send_morning_reminder():
    """ 09:00 - Утреннее приглашение (на испанском) """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT telegram_id FROM students WHERE is_active = 1")
    students = cursor.fetchall()
    conn.close()

    for (uid,) in students:
        builder = InlineKeyboardBuilder()
        builder.button(text="¡Empezar la tarea! 🚀", callback_data="start_daily_flow")
        msg = await bot.send_message(
            uid,
            "¡Hola! 👋 Es hora de practicar un poco de ruso. ¿Estás listo para la tarea de hoy?",
            reply_markup=builder.as_markup()
        )
        track_msg(uid, msg.message_id)

async def send_evening_reminder():
    """ 20:00 - Вечернее напоминание """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT telegram_id FROM students WHERE is_active = 1")
    students = cursor.fetchall()
    conn.close()

    for (uid,) in students:
        builder = InlineKeyboardBuilder()
        builder.button(text="¡Hacer el test ahora! ⏳", callback_data="start_daily_flow")
        msg = await bot.send_message(
            uid,
            "¡Recordatorio! ⚠️ Aún no has completado la tarea de hoy. ¡Solo te llevará 2 minutos!",
            reply_markup=builder.as_markup()
        )
        track_msg(uid, msg.message_id)

async def midnight_cleanup():
    """ 00:00 - Очистка чатов и кнопка 'Empezar el día' """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT telegram_id FROM students")
    students = cursor.fetchall()
    conn.close()

    for (uid,) in students:
        # Удаляем все дневные сообщения
        if uid in user_messages:
            for msg_id in user_messages[uid]:
                try:
                    await bot.delete_message(uid, msg_id)
                except Exception:
                    pass
            user_messages[uid] = []

        # Оставляем только кнопку Начать день
        builder = InlineKeyboardBuilder()
        builder.button(text="Empezar el día ☀️", callback_data="start_daily_flow")
        msg = await bot.send_message(
            uid,
            "¡Nuevo día, nueva oportunidad! Oprime el botón para comenzar tu tarea diaria.",
            reply_markup=builder.as_markup()
        )
        track_msg(uid, msg.message_id)

# --- ОБРАБОТЧИКИ ХОДА ТЕСТА ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    register_student(message.from_user.id, message.from_user.full_name, message.from_user.username)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="Empezar el día ☀️", callback_data="start_daily_flow")
    builder.button(text="⚙️ Ajustar cantidad de preguntas", callback_data="open_settings_from_start")
    builder.button(text="❓ ¿Cómo usar el bot?", callback_data="show_instructions")
    builder.adjust(1)

    welcome_text = (
        f"¡Hola, {message.from_user.first_name}! 👋\n\n"
        f"Bienvenido/a al bot de práctica de ruso.\n\n"
        f"📌 **¿Cómo funciona?**\n"
        f"• Todos los días recibirás ejercicios para practicar.\n"
        f"• Por defecto, la cantidad es de **2 preguntas por día**.\n"
        f"• Si deseas cambiar el ritmo de estudio (de **2 a 10 preguntas**), "
        f"puedes usar el comando /settings en cualquier momento o presionar el botón de abajo."
    )

    msg = await message.answer(welcome_text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    track_msg(message.from_user.id, msg.message_id)


@dp.callback_query(F.data == "show_instructions")
async def show_instructions_handler(callback: types.CallbackQuery):
    instructions = (
        "ℹ️ **Instrucciones de uso:**\n\n"
        "1. Usa el comando /settings para elegir cuántas preguntas diarias quieres responder (mínimo 2, máximo 10).\n"
        "2. Todos los días a las 09:00 recibirás un recordatorio para comenzar.\n"
        "3. Primero verás una tarjeta con la regla gramatical. Léela con atención y presiona *¡Estoy listo/a!*.\n"
        "4. Responderás las preguntas una por una. Al finalizar, verás tu racha de días sin errores."
    )
    await callback.answer()
    await callback.message.answer(instructions, parse_mode="Markdown")
# --- CONFIGURACIÓN DE CANTIDAD DE PREGUNTAS ---

@dp.message(Command("settings"))
async def cmd_settings(message: types.Message):
    """ Menú para configurar la cantidad de preguntas diarias """
    uid = message.from_user.id
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT daily_questions_count FROM students WHERE telegram_id = ?", (uid,))
    row = cursor.fetchone()
    conn.close()
    
    current_count = row[0] if row and row[0] else 2

    builder = InlineKeyboardBuilder()
    for num in range(2, 11):
        icon = "🔘" if num == current_count else "⚪️"
        builder.button(text=f"{icon} {num}", callback_data=f"set_qcount_{num}")
    
    builder.adjust(3)

    settings_text = (
        f"⚙️ **Configuración de carga diaria**\n\n"
        f"Cantidad actual de preguntas por día: **{current_count}**\n\n"
        f"Elige cuántas preguntas deseas responder diariamente (de 2 a 10):"
    )

    await message.answer(settings_text, reply_markup=builder.as_markup(), parse_mode="Markdown")


@dp.callback_query(F.data == "open_settings_from_start")
async def open_settings_callback(callback: types.CallbackQuery):
    """ Permite abrir la configuración directamente desde el botón del mensaje /start """
    await callback.answer()
    await cmd_settings(callback.message)


@dp.callback_query(F.data.startswith("set_qcount_"))
async def save_qcount_setting(callback: types.CallbackQuery):
    """ Guardar la nueva cantidad en la base de datos """
    new_count = int(callback.data.split("_")[2])
    uid = callback.from_user.id

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE students SET daily_questions_count = ? WHERE telegram_id = ?", (new_count, uid))
    conn.commit()
    conn.close()

    await callback.answer(
        f"¡Guardado! Ahora recibirás {new_count} preguntas al día.", 
        show_alert=True
    )
    await callback.message.delete()

# Клик 'Empezar' -> Настоящая картинка темы с компьютера
@dp.callback_query(F.data == "start_daily_flow")
async def show_miro_card(callback: types.CallbackQuery):
    uid = callback.from_user.id
    tag, name, img_path = get_active_topic(uid)

    builder = InlineKeyboardBuilder()
    builder.button(text="¡Estoy listo/a! ➡️", callback_data=f"show_q1_{tag}")

    caption = (
        f"📘 **Tema: {name}**\n\n"
        f"Revisa el material en la imagen para recordar la regla.\n"
        f"Cuando estés listo/a, presiona el botón para comenzar las preguntas."
    )
    
    try:
        await callback.message.delete()
    except Exception:
        pass

    # Отправляем файл-картинку с компьютера
    photo_file = FSInputFile(img_path)
    msg = await bot.send_photo(
        chat_id=uid,
        photo=photo_file,
        caption=caption,
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    track_msg(uid, msg.message_id)
    await callback.answer()

# Нажал 'Готов' -> Картинка пропадает, появляется Вопрос №1
# Показ следующего вопроса из пула
@dp.callback_query(F.data.startswith("show_q1_"))
async def start_quiz_session(callback: types.CallbackQuery):
    uid = callback.from_user.id
    topic_tag = callback.data.split("show_q1_")[1]
    
    tasks = get_random_tasks_for_student(uid, topic_tag)
    if not tasks:
        await callback.answer("Задания не найдены.", show_alert=True)
        return

    await callback.message.delete() # Картинка исчезает!
    
    # Собираем ID всех выбранных вопросов через запятую
    task_ids = ",".join(str(t[0]) for t in tasks)
    
    # Запускаем первый вопрос (индекс 0)
    await send_quiz_step(uid, task_ids_str=task_ids, current_index=0)
    await callback.answer()

async def send_quiz_step(user_id: int, task_ids_str: str, current_index: int):
    """ Вспомогательная функция для отправки очередного вопроса """
    task_ids = task_ids_str.split(",")
    total_tasks = len(task_ids)
    
    current_task_id = int(task_ids[current_index])
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT question_text, options, correct_answer FROM tasks WHERE id = ?", (current_task_id,))
    q_data = cursor.fetchone()
    conn.close()

    builder = InlineKeyboardBuilder()
    for opt in q_data[1].split("|"):
        is_corr = "1" if opt == q_data[2] else "0"
        # Передаем строку всех ID, текущий шаг и признак верного ответа
        builder.button(text=opt, callback_data=f"ansstep_{is_corr}_{task_ids_str}_{current_index}")
    builder.adjust(1)

    msg = await bot.send_message(
        user_id, 
        f"❓ **Вопрос {current_index + 1}/{total_tasks}:**\n{q_data[0]}", 
        reply_markup=builder.as_markup(), 
        parse_mode="Markdown"
    )
    track_msg(user_id, msg.message_id)

@dp.callback_query(F.data.startswith("ansstep_"))
async def process_quiz_answer(callback: types.CallbackQuery):
    _, is_corr, task_ids_str, current_index_str = callback.data.split("_")
    current_index = int(current_index_str)
    task_ids = task_ids_str.split(",")
    total_tasks = len(task_ids)
    uid = callback.from_user.id

    current_task_id = int(task_ids[current_index])

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT question_text, correct_answer, explanation FROM tasks WHERE id = ?", (current_task_id,))
    q_data = cursor.fetchone()

    # Результат текущего ответа
    if is_corr == "1":
        text_res = callback.message.text + "\n\n✅ Молодец!"
    else:
        log_error(uid, q_data[0], f"Ошибка на шаге {current_index + 1}")
        text_res = callback.message.text + f"\n\nПовтори еще раз 💡\nПравило: {q_data[2]}"

    # Стрик и завершение дня (проверяем, был ли это последний вопрос)
    if current_index + 1 >= total_tasks:
        no_errors_today = (is_corr == "1")
        if no_errors_today:
            cursor.execute("UPDATE students SET current_streak = current_streak + 1 WHERE telegram_id = ?", (uid,))
        else:
            cursor.execute("UPDATE students SET current_streak = 0 WHERE telegram_id = ?", (uid,))
        
        cursor.execute("UPDATE students SET last_activity = ? WHERE telegram_id = ?", (date.today(), uid))
        conn.commit()
        conn.close()

        text_res += "\n\nДо завтра!👋"
        await callback.message.edit_text(text_res)
    else:
        cursor.execute("UPDATE students SET last_activity = ? WHERE telegram_id = ?", (date.today(), uid))
        conn.commit()
        conn.close()

        await callback.message.edit_text(text_res)
        await asyncio.sleep(1)
        await send_quiz_step(uid, task_ids_str, current_index + 1)

    await callback.answer()

    # Если текущий ответ правильный (is_corr == "1")
    no_errors_today = (is_corr == "1")    
    # Стрик
    if no_errors_today:
        cursor.execute("UPDATE students SET current_streak = current_streak + 1 WHERE telegram_id = ?", (uid,))
    else:
        cursor.execute("UPDATE students SET current_streak = 0 WHERE telegram_id = ?", (uid,))

    # Проверяем 5 дней идеальных ответов подряд!
    cursor.execute("SELECT current_streak, full_name FROM students WHERE telegram_id = ?", (uid,))
    streak, name = cursor.fetchone()

    if streak >= 5:
        await bot.send_message(
            ADMIN_ID,
            f"🎉 **Ученик освоил тему!**\n\nСтудент **{name}** уже 5 дней занимается без единой ошибки!\n"
            f"Рекомендуется сменить его тему на **«Verbos. Conjugación II»** в панели /admin."
        )

    conn.commit()
    conn.close()

    await callback.message.edit_text(text_res)

# --- ПАНЕЛЬ АДМИНИСТРАТОРА И ЛОГИ ОШИБОК ---

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT telegram_id, full_name, current_streak FROM students")
    students = cursor.fetchall()
    conn.close()

    builder = InlineKeyboardBuilder()
    for sid, name, streak in students:
        builder.button(text=f"🎓 {name} (Стрик: {streak}🔥)", callback_data=f"adm_menu_{sid}")
    builder.adjust(1)

    await message.answer("Панель преподавателя. Выберите ученика:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("adm_menu_"))
async def admin_student_menu(callback: types.CallbackQuery):
    sid = int(callback.data.split("_")[2])
    
    builder = InlineKeyboardBuilder()
    builder.button(text="📚 Сменить тему", callback_data=f"adm_topics_{sid}")
    builder.button(text="⚠️ Посмотреть ошибки", callback_data=f"adm_errors_{sid}")
    builder.button(text="◀️ Назад", callback_data="back_admin")
    builder.adjust(1)

    await callback.message.edit_text(f"Управление учеником ID: {sid}", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("adm_topics_"))
async def admin_topics(callback: types.CallbackQuery):
    sid = int(callback.data.split("_")[2])

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM topics")
    topics = cursor.fetchall()

    cursor.execute("SELECT topic_id FROM student_topics WHERE student_id = ? AND is_enabled = 1", (sid,))
    active = cursor.fetchone()
    active_id = active[0] if active else None
    conn.close()

    builder = InlineKeyboardBuilder()
    for tid, name in topics:
        icon = "✅" if tid == active_id else "❌"
        builder.button(text=f"[{icon}] {name}", callback_data=f"set_topic_{sid}_{tid}")
    builder.button(text="◀️ Назад", callback_data=f"adm_menu_{sid}")
    builder.adjust(1)

    await callback.message.edit_text("Выберите активную тему для ученика:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("set_topic_"))
async def set_student_topic(callback: types.CallbackQuery):
    _, _, sid, tid = callback.data.split("_")
    sid, tid = int(sid), int(tid)

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE student_topics SET is_enabled = 0 WHERE student_id = ?", (sid,))
    cursor.execute('''
        INSERT INTO student_topics (student_id, topic_id, is_enabled) VALUES (?, ?, 1)
        ON CONFLICT(student_id, topic_id) DO UPDATE SET is_enabled = 1
    ''', (sid, tid))
    conn.commit()
    conn.close()

    await callback.answer("Тема изменена!", show_alert=True)
    await admin_topics(callback)

@dp.callback_query(F.data.startswith("adm_errors_"))
async def show_student_errors(callback: types.CallbackQuery):
    sid = int(callback.data.split("_")[2])

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT question_text, wrong_answer, timestamp FROM error_logs WHERE student_id = ? ORDER BY id DESC LIMIT 10", (sid,))
    errors = cursor.fetchall()
    conn.close()

    if not errors:
        msg_text = "🎉 У этого ученика нет зафиксированных ошибок!"
    else:
        msg_text = "⚠️ **Последние ошибки ученика:**\n\n"
        for q, w, t in errors:
            msg_text += f"• Вопрос: *{q}*\n  Лог: {w} ({t})\n\n"

    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад", callback_data=f"adm_menu_{sid}")

    await callback.message.edit_text(msg_text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data == "back_admin")
async def back_to_adm(callback: types.CallbackQuery):
    await callback.message.delete()
    await cmd_admin(callback.message)

# main.py — Настройки пользователя

@dp.message(Command("settings"))
async def cmd_settings(message: types.Message):
    """ Меню выбора количества вопросов в день """
    uid = message.from_user.id
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT daily_questions_count FROM students WHERE telegram_id = ?", (uid,))
    row = cursor.fetchone()
    conn.close()
    
    current_count = row[0] if row else 2

    builder = InlineKeyboardBuilder()
    # Создаем кнопки от 2 до 10
    for num in range(2, 11):
        icon = "🔘" if num == current_count else "⚪️"
        builder.button(text=f"{icon} {num}", callback_data=f"set_qcount_{num}")
    
    builder.adjust(3) # Кнопки сеткой по 3 в ряд

    await message.answer(
        f"⚙️ **Настройки нагрузки**\n\n"
        f"Текущее количество вопросов в день: **{current_count}**\n"
        f"Выберите новое количество вопросов (от 2 до 10):",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data.startswith("set_qcount_"))
async def save_qcount_setting(callback: types.CallbackQuery):
    """ Сохранение выбранного количества в БД """
    new_count = int(callback.data.split("_")[2])
    uid = callback.from_user.id

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE students SET daily_questions_count = ? WHERE telegram_id = ?", (new_count, uid))
    conn.commit()
    conn.close()

    await callback.answer(f"Сохранено! Теперь вы будете получать {new_count} вопросов в день.", show_alert=True)
    await callback.message.delete()

# --- ЗАПУСК И ПЛАНИРОВЩИК ---

async def main():
    # Настраиваем отправку в 9:00, 20:00 и сброс в 00:00 по времени Буэнос-Айреса
    scheduler.add_job(send_morning_reminder, "cron", hour=9, minute=0)
    scheduler.add_job(send_evening_reminder, "cron", hour=20, minute=0)
    scheduler.add_job(midnight_cleanup, "cron", hour=0, minute=0)
    
    scheduler.start()
    print("Бот и планировщик (Аргентина) запущены!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())