# -*- coding: utf-8 -*-
import asyncio
import logging
import pytz
from datetime import datetime

async def send_daily_reminders(bot, get_db):
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Выбираем только активных студентов
        cursor.execute("SELECT telegram_id, timezone, current_streak FROM students WHERE is_active = 1")
        students = cursor.fetchall()
        
        for student in students:
            user_id, tz_str, streak = student[0], student[1], student[2]
            if not tz_str:
                tz_str = "UTC"
                
            try:
                user_tz = pytz.timezone(tz_str)
                now_user = datetime.now(user_tz)
                current_time_str = now_user.strftime("%H:%M")
                
                # Утреннее напоминание (09:00)
                if current_time_str == "09:00":
                    msg = (
                        "☀️ <b>¡Buenos días!</b>\n\n"
                        "Es hora de tu práctica diaria de ruso. "
                        "¡Mantén tu racha activa! 💪"
                    )
                    await bot.send_message(user_id, msg, parse_mode="HTML")
                    logging.info(f">>> SCHEDULER: Sent morning reminder to {user_id}")

                # Вечернее напоминание (20:00)
                elif current_time_str == "20:00":
                    msg = (
                        "🌙 <b>¡Recordatorio de noche!</b>\n\n"
                        "Aún no has completado tu práctica de hoy. "
                        "¡No pierdas tu racha! ⚡"
                    )
                    await bot.send_message(user_id, msg, parse_mode="HTML")
                    logging.info(f">>> SCHEDULER: Sent evening reminder to {user_id}")

            except Exception as st_err:
                logging.error(f">>> SCHEDULER ERROR for user {user_id}: {st_err}")
                
        conn.close()
    except Exception as e:
        logging.error(f">>> SCHEDULER CYCLE ERROR: {e}")

async def run_scheduler(bot, get_db):
    logging.info(">>> SCHEDULER ENGINE STARTED SUCCESSFULLY")
    while True:
        try:
            await send_daily_reminders(bot, get_db)
        except Exception as e:
            logging.error(f">>> UNHANDLED SCHEDULER LOOP ERROR: {e}")
        # Проверка каждую минуту
        await asyncio.sleep(60)