#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Телеграм-бот для обработки заявок по ДТП с AI-агентом
Адаптирован под Python 3.13 и python-telegram-bot 20+
"""

import os
import logging
from datetime import datetime

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
from openai import OpenAI

# ==================== ЛОГИРОВАНИЕ ====================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ==================== КОНФИГ ====================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

ADMIN_IDS = [
    # 123456789,
    # 987654321,
]

# ==================== OpenAI ====================
try:
    openai_client = OpenAI(api_key=OPENAI_API_KEY)
    logger.info("✅ OpenAI клиент инициализирован")
except Exception as e:
    logger.error(f"❌ Ошибка инициализации OpenAI: {e}")
    openai_client = None

# ==================== СОСТОЯНИЯ ====================
(
    CHOOSING_MODE,
    LOCATION,
    PARTICIPANTS,
    DAMAGE,
    INJURIES,
    PHOTOS,
    CONTACT,
    AI_CHAT,
    CONFIRM,
    ADMIN_MENU,
    ADMIN_ADD,
    ADMIN_REMOVE,
) = range(12)

# ==================== АДМИНЫ ====================


def load_admins():
    """Загрузка списка администраторов из файла"""
    try:
        with open("admins.txt", "r") as f:
            admins = [int(line.strip()) for line in f if line.strip()]
            logger.info(f"📋 Загружено {len(admins)} администраторов из файла")
            return admins
    except FileNotFoundError:
        logger.info("📋 Файл admins.txt не найден, используются администраторы из кода")
        return ADMIN_IDS.copy()
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки администраторов: {e}")
        return ADMIN_IDS.copy()


def save_admins(admins):
    """Сохранение списка администраторов в файл"""
    try:
        with open("admins.txt", "w") as f:
            for admin_id in admins:
                f.write(f"{admin_id}\n")
        logger.info(f"💾 Сохранено {len(admins)} администраторов в файл")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения администраторов: {e}")
        return False


def is_admin(user_id: int) -> bool:
    """Проверка является ли пользователь администратором"""
    admins = load_admins()
    return user_id in admins


async def send_to_admins(context: ContextTypes.DEFAULT_TYPE, message: str):
    """Отправка сообщения всем администраторам"""
    admins = load_admins()

    if not admins:
        logger.warning("⚠️ Нет администраторов для отправки заявки!")
        return

    success_count = 0
    for admin_id in admins:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=message,
                parse_mode="Markdown",
            )
            success_count += 1
            logger.info(f"✅ Заявка отправлена администратору {admin_id}")
        except Exception as e:
            logger.error(f"❌ Ошибка отправки администратору {admin_id}: {e}")

    logger.info(
        f"📨 Заявка отправлена {success_count} из {len(admins)} администраторов"
    )


# ==================== AI ====================


def get_ai_response(
    user_message: str, conversation_history: list, application_data: dict
) -> str:
    """Получить ответ от AI-агента OpenAI"""

    if not openai_client:
        return (
            "Извините, AI-помощник временно недоступен. "
            "Пожалуйста, используйте режим с кнопками или попробуйте позже."
        )

    try:
        system_prompt = f"""Ты - помощник аварийного комиссара. Помогаешь оформить заявку после ДТП.

Твоя задача:
1. Собрать информацию: место ДТП, участники, повреждения, пострадавшие, контакт
2. Быть вежливым и кратким
3. Задавать по одному вопросу за раз

Текущие данные заявки:
- Место: {application_data.get('location', 'не указано')}
- Участники: {application_data.get('participants', 'не указано')}
- Повреждения: {application_data.get('damage', 'не указано')}
- Пострадавшие: {application_data.get('injuries', 'не указано')}
- Контакт: {application_data.get('contact', 'не указано')}

Если поле не заполнено, спроси о нём. Отвечай кратко на русском языке."""

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(conversation_history[-10:])
        messages.append({"role": "user", "content": user_message})

        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages,
            max_tokens=300,
            temperature=0.7,
        )

        ai_message = response.choices[0].message.content
        logger.info(f"✅ Получен ответ от AI: {ai_message[:50]}...")
        return ai_message

    except Exception as e:
        logger.error(f"❌ Ошибка OpenAI API: {e}")
        return (
            "Извините, произошла ошибка при обработке сообщения. "
            "Попробуйте ещё раз или используйте режим с кнопками (/start)."
        )


def extract_info_from_message(message: str, application: dict) -> dict:
    """Извлекает данные из сообщения пользователя"""
    message_lower = message.lower()
    updated = {}

    # Адрес
    if not application.get("location"):
        address_keywords = [
            "улица",
            "ул.",
            "проспект",
            "пр.",
            "переулок",
            "пер.",
            "площадь",
            "шоссе",
            "дом",
            "д.",
        ]
        if any(word in message_lower for word in address_keywords):
            application["location"] = message
            updated["location"] = True

    # Участники
    if not application.get("participants"):
        if "два" in message_lower or "2" in message:
            application["participants"] = "2 автомобиля"
            updated["participants"] = True
        elif "три" in message_lower or "3" in message:
            application["participants"] = "3 автомобиля"
            updated["participants"] = True

    # Повреждения
    if not application.get("damage"):
        damage_keywords = [
            "бампер",
            "фара",
            "крыло",
            "дверь",
            "капот",
            "повреждение",
            "царапина",
            "вмятина",
            "разбит",
        ]
        if any(word in message_lower for word in damage_keywords):
            application["damage"] = message
            updated["damage"] = True

    # Пострадавшие
    if not application.get("injuries"):
        if (
            "нет пострадавших" in message_lower
            or "никто не пострадал" in message_lower
        ):
            application["injuries"] = "Нет пострадавших"
            updated["injuries"] = True
        elif "пострадал" in message_lower or "ранен" in message_lower:
            application["injuries"] = "Есть пострадавшие"
            updated["injuries"] = True

    # Телефон
    if not application.get("contact"):
        import re

        phone_patterns = [
            r"\+7[\s-]?\d{3}[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}",
            r"8[\s-]?\d{3}[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}",
            r"\d{11}",
        ]
        for pattern in phone_patterns:
            match = re.search(pattern, message)
            if match:
                application["contact"] = match.group()
                updated["contact"] = True
                break

    return updated


def format_application(app: dict, user_info: dict | None = None) -> str:
    """Форматирование заявки для отправки"""

    user_section = ""
    if user_info:
        user_section = f"""
👤 *ИНФОРМАЦИЯ О ПОЛЬЗОВАТЕЛЕ:*
Имя: {user_info.get('first_name', 'Не указано')}
Username: @{user_info.get('username', 'нет')}
Telegram ID: `{user_info.get('user_id', 'н/д')}`

"""

    return f"""
🚨 *НОВАЯ ЗАЯВКА НА АВАРИЙНОГО КОМИССАРА*
━━━━━━━━━━━━━━━━━━━━━
{user_section}
🕐 *Дата и время:*
{datetime.fromisoformat(app['timestamp']).strftime('%d.%m.%Y %H:%M:%S')}

📍 *Место ДТП:*
{app.get('location', 'не указано')}

👥 *Участники:*
{app.get('participants', 'не указано')}

🚗 *Повреждения:*
{app.get('damage', 'не указано')}

🚑 *Пострадавшие:*
{app.get('injuries', 'не указано')}

📞 *Контакт:*
{app.get('contact', 'не указано')}

━━━━━━━━━━━━━━━━━━━━━
⏰ Время получения: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
"""


# ==================== ОБРАБОТЧИКИ ====================


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало работы с ботом"""
    user = update.effective_user
    logger.info(f"👤 Пользователь {user.first_name} ({user.id}) начал работу")

    if is_admin(user.id):
        keyboard = [
            ["🤖 Общаться с AI-помощником"],
            ["📋 Заполнить по шагам"],
            ["⚙️ Управление администраторами"],
        ]
    else:
        keyboard = [
            ["🤖 Общаться с AI-помощником"],
            ["📋 Заполнить по шагам"],
        ]

    context.user_data["application"] = {
        "timestamp": datetime.now().isoformat(),
        "location": None,
        "participants": None,
        "damage": None,
        "injuries": None,
        "photos_count": 0,
        "contact": None,
    }
    context.user_data["ai_history"] = []

    reply_markup = ReplyKeyboardMarkup(
        keyboard, resize_keyboard=True, one_time_keyboard=True
    )

    await update.message.reply_text(
        f"Здравствуйте, {user.first_name}! 👋\n\n"
        "Я помогу оформить заявку для аварийного комиссара после ДТП.\n\n"
        "Выберите удобный способ:",
        reply_markup=reply_markup,
    )

    return CHOOSING_MODE


async def choose_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Выбор режима работы"""
    choice = update.message.text
    logger.info(f"📌 Выбран режим: {choice}")

    if "⚙️" in choice and is_admin(update.effective_user.id):
        return await admin_menu(update, context)

    if "🤖" in choice or "AI" in choice.upper():
        await update.message.reply_text(
            "🤖 Отлично! Теперь общайтесь со мной свободно.\n\n"
            "Расскажите, что произошло и где?",
            reply_markup=ReplyKeyboardRemove(),
        )
        return AI_CHAT
    else:
        await update.message.reply_text(
            "📋 Буду задавать вопросы по порядку.\n\n"
            "📍 Шаг 1/5: Где произошло ДТП?\n"
            "Укажите адрес или ориентиры:",
            reply_markup=ReplyKeyboardRemove(),
        )
        return LOCATION


# ==================== АДМИН-ПАНЕЛЬ ====================


async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Меню управления администраторами"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(
            "❌ У вас нет доступа к этой функции.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ConversationHandler.END

    admins = load_admins()
    admin_list = (
        "\n".join([f"• {admin_id}" for admin_id in admins])
        if admins
        else "Нет администраторов"
    )

    keyboard = [
        ["➕ Добавить администратора"],
        ["➖ Удалить администратора"],
        ["📋 Список администраторов"],
        ["◀️ Вернуться назад"],
    ]
    reply_markup = ReplyKeyboardMarkup(
        keyboard, resize_keyboard=True, one_time_keyboard=True
    )

    await update.message.reply_text(
        f"⚙️ *УПРАВЛЕНИЕ АДМИНИСТРАТОРАМИ*\n\n"
        f"Текущие администраторы ({len(admins)}):\n{admin_list}\n\n"
        f"Выберите действие:",
        reply_markup=reply_markup,
        parse_mode="Markdown",
    )

    return ADMIN_MENU


async def admin_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбора в админ-меню"""
    choice = update.message.text

    if "➕" in choice:
        await update.message.reply_text(
            "➕ Отправьте Telegram ID нового администратора:\n\n"
            "💡 Как узнать ID:\n"
            "1. Напишите боту @userinfobot\n"
            "2. Он отправит вам ваш ID\n\n"
            "Для отмены отправьте /cancel",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ADMIN_ADD

    elif "➖" in choice:
        admins = load_admins()
        if not admins:
            await update.message.reply_text(
                "❌ Нет администраторов для удаления.",
                reply_markup=ReplyKeyboardRemove(),
            )
            return ConversationHandler.END

        await update.message.reply_text(
            "➖ Отправьте Telegram ID администратора для удаления:\n\n"
            "Текущие администраторы:\n"
            + "\n".join([f"• {aid}" for aid in admins])
            + "\n\n"
            "Для отмены отправьте /cancel",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ADMIN_REMOVE

    elif "📋" in choice:
        admins = load_admins()
        admin_list = (
            "\n".join([f"• `{admin_id}`" for admin_id in admins])
            if admins
            else "Нет администраторов"
        )

        await update.message.reply_text(
            f"📋 *СПИСОК АДМИНИСТРАТОРОВ* ({len(admins)}):\n\n{admin_list}",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(),
        )
        return await admin_menu(update, context)

    else:
        return await start(update, context)


async def admin_add_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Добавление администратора"""
    try:
        new_admin_id = int(update.message.text.strip())
        admins = load_admins()

        if new_admin_id in admins:
            await update.message.reply_text(
                f"⚠️ Администратор {new_admin_id} уже есть в списке!"
            )
        else:
            admins.append(new_admin_id)
            if save_admins(admins):
                await update.message.reply_text(
                    f"✅ Администратор {new_admin_id} успешно добавлен!"
                )
                logger.info(f"✅ Добавлен новый администратор: {new_admin_id}")
            else:
                await update.message.reply_text("❌ Ошибка при сохранении администратора.")

        return await admin_menu(update, context)

    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат ID. Введите числовой ID.\n"
            "Для отмены отправьте /cancel"
        )
        return ADMIN_ADD


async def admin_remove_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Удаление администратора"""
    try:
        remove_admin_id = int(update.message.text.strip())
        admins = load_admins()

        if remove_admin_id not in admins:
            await update.message.reply_text(
                f"⚠️ Администратор {remove_admin_id} не найден в списке!"
            )
        elif remove_admin_id == update.effective_user.id and len(admins) == 1:
            await update.message.reply_text(
                "❌ Нельзя удалить последнего администратора (себя)!"
            )
        else:
            admins.remove(remove_admin_id)
            if save_admins(admins):
                await update.message.reply_text(
                    f"✅ Администратор {remove_admin_id} успешно удалён!"
                )
                logger.info(f"✅ Удалён администратор: {remove_admin_id}")
            else:
                await update.message.reply_text("❌ Ошибка при сохранении изменений.")

        return await admin_menu(update, context)

    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат ID. Введите числовой ID.\n"
            "Для отмены отправьте /cancel"
        )
        return ADMIN_REMOVE


# ==================== РЕЖИМ С КНОПКАМИ ====================


async def get_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["application"]["location"] = update.message.text
    logger.info(f"📍 Место ДТП: {update.message.text}")

    keyboard = [
        ["2 автомобиля", "3 автомобиля"],
        ["Более 3 автомобилей"],
    ]
    reply_markup = ReplyKeyboardMarkup(
        keyboard, resize_keyboard=True, one_time_keyboard=True
    )

    await update.message.reply_text(
        "✅ Место ДТП сохранено.\n\n"
        "👥 Шаг 2/5: Сколько автомобилей участвовало?",
        reply_markup=reply_markup,
    )
    return PARTICIPANTS


async def get_participants(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["application"]["participants"] = update.message.text
    logger.info(f"👥 Участники: {update.message.text}")

    await update.message.reply_text(
        "✅ Количество участников сохранено.\n\n"
        "🚗 Шаг 3/5: Опишите повреждения вашего автомобиля:\n"
        "(например: разбита фара, помят бампер)",
        reply_markup=ReplyKeyboardRemove(),
    )
    return DAMAGE


async def get_damage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["application"]["damage"] = update.message.text
    logger.info(f"🚗 Повреждения: {update.message.text}")

    keyboard = [
        ["Нет пострадавших"],
        ["Есть пострадавшие"],
    ]
    reply_markup = ReplyKeyboardMarkup(
        keyboard, resize_keyboard=True, one_time_keyboard=True
    )

    await update.message.reply_text(
        "✅ Повреждения зафиксированы.\n\n"
        "🚑 Шаг 4/5: Есть ли пострадавшие?",
        reply_markup=reply_markup,
    )
    return INJURIES


async def get_injuries(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["application"]["injuries"] = update.message.text
    logger.info(f"🚑 Пострадавшие: {update.message.text}")

    await update.message.reply_text(
        "✅ Информация сохранена.\n\n"
        "📞 Шаг 5/5: Укажите ваш контактный телефон:\n"
        "(например: +79001234567)",
        reply_markup=ReplyKeyboardRemove(),
    )
    return CONTACT


async def get_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["application"]["contact"] = update.message.text
    logger.info(f"📞 Контакт: {update.message.text}")

    app = context.user_data["application"]

    summary = f"""
━━━━━━━━━━━━━━━━━━━━━
📋 ЗАЯВКА НА АВАРИЙНОГО КОМИССАРА
━━━━━━━━━━━━━━━━━━━━━

🕐 Время: {datetime.fromisoformat(app['timestamp']).strftime('%d.%m.%Y %H:%M')}

📍 Место ДТП:
{app['location']}

👥 Участники:
{app['participants']}

🚗 Повреждения:
{app['damage']}

🚑 Пострадавшие:
{app['injuries']}

📞 Контакт:
{app['contact']}

━━━━━━━━━━━━━━━━━━━━━
"""

    keyboard = [
        ["✅ Подтвердить и отправить"],
        ["❌ Отменить"],
    ]
    reply_markup = ReplyKeyboardMarkup(
        keyboard, resize_keyboard=True, one_time_keyboard=True
    )

    await update.message.reply_text(
        summary + "\n\nПроверьте данные:", reply_markup=reply_markup
    )
    return CONFIRM


# ==================== AI РЕЖИМ ====================


async def ai_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_message = update.message.text
    logger.info(f"💬 AI-чат: {user_message}")

    if user_message.lower() in ["/finish", "завершить", "закончить", "готово"]:
        return await finish_ai_application(update, context)

    app = context.user_data["application"]
    updated_fields = extract_info_from_message(user_message, app)

    context.user_data["ai_history"].append(
        {
            "role": "user",
            "content": user_message,
        }
    )

    ai_response = get_ai_response(
        user_message,
        context.user_data["ai_history"],
        app,
    )

    context.user_data["ai_history"].append(
        {
            "role": "assistant",
            "content": ai_response,
        }
    )

    if updated_fields:
        fields_updated = ", ".join(updated_fields.keys())
        ai_response = f"✅ Сохранено: {fields_updated}\n\n" + ai_response

    await update.message.reply_text(
        ai_response + "\n\n💡 Когда закончите, напишите /finish"
    )

    return AI_CHAT


async def finish_ai_application(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    app = context.user_data["application"]

    missing = []
    if not app.get("location"):
        missing.append("место ДТП")
    if not app.get("contact"):
        missing.append("телефон")

    if missing:
        await update.message.reply_text(
            f"⚠️ Пожалуйста, укажите: {', '.join(missing)}"
        )
        return AI_CHAT

    summary = f"""
━━━━━━━━━━━━━━━━━━━━━
📋 ЗАЯВКА НА АВАРИЙНОГО КОМИССАРА
━━━━━━━━━━━━━━━━━━━━━

🕐 Время: {datetime.fromisoformat(app['timestamp']).strftime('%d.%m.%Y %H:%M')}

📍 Место ДТП:
{app.get('location', 'не указано')}

👥 Участники:
{app.get('participants', 'не указано')}

🚗 Повреждения:
{app.get('damage', 'не указано')}

🚑 Пострадавшие:
{app.get('injuries', 'не указано')}

📞 Контакт:
{app.get('contact', 'не указано')}

━━━━━━━━━━━━━━━━━━━━━
"""

    keyboard = [
        ["✅ Подтвердить и отправить"],
        ["❌ Отменить"],
    ]
    reply_markup = ReplyKeyboardMarkup(
        keyboard, resize_keyboard=True, one_time_keyboard=True
    )

    await update.message.reply_text(
        summary + "\n\nПроверьте данные:", reply_markup=reply_markup
    )
    return CONFIRM


# ==================== ПОДТВЕРЖДЕНИЕ ====================


async def confirm_application(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    choice = update.message.text

    if "✅" in choice:
        app = context.user_data["application"]
        user = update.effective_user

        user_info = {
            "first_name": user.first_name,
            "username": user.username,
            "user_id": user.id,
        }

        formatted_application = format_application(app, user_info)

        await send_to_admins(context, formatted_application)

        logger.info("=" * 50)
        logger.info("📨 НОВАЯ ЗАЯВКА ОТПРАВЛЕНА:")
        logger.info(f"От: {user.first_name} (@{user.username}, ID: {user.id})")
        logger.info(f"Время: {app['timestamp']}")
        logger.info(f"Место: {app['location']}")
        logger.info(f"Участники: {app['participants']}")
        logger.info(f"Повреждения: {app['damage']}")
        logger.info(f"Пострадавшие: {app['injuries']}")
        logger.info(f"Контакт: {app['contact']}")
        logger.info("=" * 50)

        await update.message.reply_text(
            "✅ ЗАЯВКА УСПЕШНО ОТПРАВЛЕНА!\n\n"
            "Наш специалист свяжется с вами в ближайшее время.",
            reply_markup=ReplyKeyboardRemove(),
        )

        return ConversationHandler.END

    else:
        await update.message.reply_text(
            "❌ Заявка отменена. Если хотите начать заново — отправьте /start",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ConversationHandler.END


# ==================== СЛУЖЕБНОЕ ====================


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "❌ Диалог отменён. Если хотите начать заново — отправьте /start",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("❌ Ошибка в обработчике:", exc_info=context.error)


# ==================== MAIN ====================
# ==================== MAIN ====================

def main() -> None:
    """Запуск бота"""
    # Проверка токена
    if not TELEGRAM_TOKEN:
        logger.error("❌ TELEGRAM_TOKEN не установлен! Проверьте переменные окружения.")
        return
    
    logger.info(f"✅ Токен бота: {'установлен' if TELEGRAM_TOKEN else 'отсутствует'}")
    logger.info(f"✅ OpenAI: {'доступен' if openai_client else 'недоступен'}")
    
    try:
        # Используем ApplicationBuilder вместо Application.builder()
        from telegram.ext import ApplicationBuilder
        
        # Создаем Application через Builder
        application = (
            ApplicationBuilder()
            .token(TELEGRAM_TOKEN)
            .build()
        )
        
        # Обработчик диалога
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", start)],
            states={
                CHOOSING_MODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_mode)],
                LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_location)],
                PARTICIPANTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_participants)],
                DAMAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_damage)],
                INJURIES: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_injuries)],
                CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_contact)],
                AI_CHAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ai_chat)],
                CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_application)],
                ADMIN_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_menu_handler)],
                ADMIN_ADD: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_handler)],
                ADMIN_REMOVE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_remove_handler)],
            },
            fallbacks=[CommandHandler("cancel", cancel)],
        )

        application.add_handler(conv_handler)
        application.add_error_handler(error_handler)

        # Запуск бота
        logger.info("🚀 Бот запущен. Ожидаю сообщения...")
        application.run_polling()
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка при запуске: {e}")
        raise


if __name__ == "__main__":
    main()
