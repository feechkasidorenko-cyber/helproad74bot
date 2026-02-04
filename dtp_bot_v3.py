#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Телеграм-бот для обработки заявок по ДТП с AI-агентом
Версия 3.0 - с отправкой заявок администратору
"""

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

# ==================== НАСТРОЙКА ЛОГИРОВАНИЯ ====================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== КОНФИГУРАЦИЯ ====================
# ⚠️ ВАЖНО: Ваши токены
TELEGRAM_TOKEN = token_tg
OPENAI_API_KEY = token_api
# ==================== АДМИНИСТРАТОРЫ ====================
# 🔥 ВАЖНО: Укажите Telegram ID администраторов, которые будут получать заявки
# Можно указать несколько ID через запятую
ADMIN_IDS = [
    # 123456789,  # Пример: ID первого администратора
    # 987654321,  # Пример: ID второго администратора
]

# ⚡ КАК УЗНАТЬ СВОЙ TELEGRAM ID:
# 1. Напишите боту @userinfobot в Telegram
# 2. Он отправит вам ваш ID
# 3. Скопируйте число и вставьте выше в список ADMIN_IDS
# Например: ADMIN_IDS = [123456789, 987654321]

# Инициализация OpenAI
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

# ==================== ФУНКЦИИ РАБОТЫ С АДМИНИСТРАТОРАМИ ====================

def load_admins():
    """Загрузка списка администраторов из файла"""
    try:
        with open('admins.txt', 'r') as f:
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
        with open('admins.txt', 'w') as f:
            for admin_id in admins:
                f.write(f"{admin_id}\n")
        logger.info(f"💾 Сохранено {len(admins)} администраторов в файл")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения администраторов: {e}")
        return False


def is_admin(user_id):
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
                parse_mode='Markdown'
            )
            success_count += 1
            logger.info(f"✅ Заявка отправлена администратору {admin_id}")
        except Exception as e:
            logger.error(f"❌ Ошибка отправки администратору {admin_id}: {e}")
    
    logger.info(f"📨 Заявка отправлена {success_count} из {len(admins)} администраторов")


# ==================== ФУНКЦИИ РАБОТЫ С AI ====================

def get_ai_response(user_message: str, conversation_history: list, application_data: dict) -> str:
    """Получить ответ от AI-агента OpenAI"""
    
    if not openai_client:
        return ("Извините, AI-помощник временно недоступен. "
                "Пожалуйста, используйте режим с кнопками или попробуйте позже.")
    
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
            temperature=0.7
        )

        ai_message = response.choices[0].message.content
        logger.info(f"✅ Получен ответ от AI: {ai_message[:50]}...")
        return ai_message

    except Exception as e:
        logger.error(f"❌ Ошибка OpenAI API: {e}")
        return ("Извините, произошла ошибка при обработке сообщения. "
                "Попробуйте ещё раз или используйте режим с кнопками (/start).")


def extract_info_from_message(message: str, application: dict) -> dict:
    """Извлекает данные из сообщения пользователя"""
    message_lower = message.lower()
    updated = {}
    
    # Адрес
    if not application.get('location'):
        address_keywords = ['улица', 'ул.', 'проспект', 'пр.', 'переулок', 'пер.', 
                           'площадь', 'шоссе', 'дом', 'д.']
        if any(word in message_lower for word in address_keywords):
            application['location'] = message
            updated['location'] = True
    
    # Участники
    if not application.get('participants'):
        if 'два' in message_lower or '2' in message:
            application['participants'] = '2 автомобиля'
            updated['participants'] = True
        elif 'три' in message_lower or '3' in message:
            application['participants'] = '3 автомобиля'
            updated['participants'] = True
    
    # Повреждения
    if not application.get('damage'):
        damage_keywords = ['бампер', 'фара', 'крыло', 'дверь', 'капот', 
                          'повреждение', 'царапина', 'вмятина', 'разбит']
        if any(word in message_lower for word in damage_keywords):
            application['damage'] = message
            updated['damage'] = True
    
    # Пострадавшие
    if not application.get('injuries'):
        if 'нет пострадавших' in message_lower or 'никто не пострадал' in message_lower:
            application['injuries'] = 'Нет пострадавших'
            updated['injuries'] = True
        elif 'пострадал' in message_lower or 'ранен' in message_lower:
            application['injuries'] = 'Есть пострадавшие'
            updated['injuries'] = True
    
    # Телефон
    if not application.get('contact'):
        import re
        phone_patterns = [
            r'\+7[\s-]?\d{3}[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}',
            r'8[\s-]?\d{3}[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}',
            r'\d{11}'
        ]
        for pattern in phone_patterns:
            match = re.search(pattern, message)
            if match:
                application['contact'] = match.group()
                updated['contact'] = True
                break
    
    return updated


def format_application(app: dict, user_info: dict = None) -> str:
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


# ==================== ОБРАБОТЧИКИ КОМАНД ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало работы с ботом"""
    user = update.effective_user
    logger.info(f"👤 Пользователь {user.first_name} ({user.id}) начал работу")
    
    # Проверка на администратора
    if is_admin(user.id):
        # Показываем дополнительную кнопку для админов
        keyboard = [
            ['🤖 Общаться с AI-помощником'],
            ['📋 Заполнить по шагам'],
            ['⚙️ Управление администраторами']
        ]
    else:
        keyboard = [
            ['🤖 Общаться с AI-помощником'],
            ['📋 Заполнить по шагам']
        ]
    
    # Инициализация данных
    context.user_data['application'] = {
        'timestamp': datetime.now().isoformat(),
        'location': None,
        'participants': None,
        'damage': None,
        'injuries': None,
        'photos_count': 0,
        'contact': None,
    }
    context.user_data['ai_history'] = []
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    
    await update.message.reply_text(
        f"Здравствуйте, {user.first_name}! 👋\n\n"
        "Я помогу оформить заявку для аварийного комиссара после ДТП.\n\n"
        "Выберите удобный способ:",
        reply_markup=reply_markup
    )
    
    return CHOOSING_MODE


async def choose_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Выбор режима работы"""
    choice = update.message.text
    logger.info(f"📌 Выбран режим: {choice}")
    
    # Проверка на админ-панель
    if '⚙️' in choice and is_admin(update.effective_user.id):
        return await admin_menu(update, context)
    
    if '🤖' in choice or 'AI' in choice.upper():
        # AI режим
        await update.message.reply_text(
            "🤖 Отлично! Теперь общайтесь со мной свободно.\n\n"
            "Расскажите, что произошло и где?",
            reply_markup=ReplyKeyboardRemove()
        )
        return AI_CHAT
    else:
        # Режим с кнопками
        await update.message.reply_text(
            "📋 Буду задавать вопросы по порядку.\n\n"
            "📍 Шаг 1/5: Где произошло ДТП?\n"
            "Укажите адрес или ориентиры:",
            reply_markup=ReplyKeyboardRemove()
        )
        return LOCATION


# ==================== АДМИН-ПАНЕЛЬ ====================

async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Меню управления администраторами"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(
            "❌ У вас нет доступа к этой функции.",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END
    
    admins = load_admins()
    admin_list = "\n".join([f"• {admin_id}" for admin_id in admins]) if admins else "Нет администраторов"
    
    keyboard = [
        ['➕ Добавить администратора'],
        ['➖ Удалить администратора'],
        ['📋 Список администраторов'],
        ['◀️ Вернуться назад']
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    
    await update.message.reply_text(
        f"⚙️ *УПРАВЛЕНИЕ АДМИНИСТРАТОРАМИ*\n\n"
        f"Текущие администраторы ({len(admins)}):\n{admin_list}\n\n"
        f"Выберите действие:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    return ADMIN_MENU


async def admin_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбора в админ-меню"""
    choice = update.message.text
    
    if '➕' in choice:
        await update.message.reply_text(
            "➕ Отправьте Telegram ID нового администратора:\n\n"
            "💡 Как узнать ID:\n"
            "1. Напишите боту @userinfobot\n"
            "2. Он отправит вам ваш ID\n\n"
            "Для отмены отправьте /cancel",
            reply_markup=ReplyKeyboardRemove()
        )
        return ADMIN_ADD
    
    elif '➖' in choice:
        admins = load_admins()
        if not admins:
            await update.message.reply_text(
                "❌ Нет администраторов для удаления.",
                reply_markup=ReplyKeyboardRemove()
            )
            return ConversationHandler.END
        
        await update.message.reply_text(
            f"➖ Отправьте Telegram ID администратора для удаления:\n\n"
            f"Текущие администраторы:\n" + "\n".join([f"• {aid}" for aid in admins]) + "\n\n"
            f"Для отмены отправьте /cancel",
            reply_markup=ReplyKeyboardRemove()
        )
        return ADMIN_REMOVE
    
    elif '📋' in choice:
        admins = load_admins()
        admin_list = "\n".join([f"• `{admin_id}`" for admin_id in admins]) if admins else "Нет администраторов"
        
        await update.message.reply_text(
            f"📋 *СПИСОК АДМИНИСТРАТОРОВ* ({len(admins)}):\n\n{admin_list}",
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardRemove()
        )
        return await admin_menu(update, context)
    
    else:  # Вернуться назад
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
                await update.message.reply_text(
                    f"❌ Ошибка при сохранении администратора."
                )
        
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
                f"❌ Нельзя удалить последнего администратора (себя)!"
            )
        else:
            admins.remove(remove_admin_id)
            if save_admins(admins):
                await update.message.reply_text(
                    f"✅ Администратор {remove_admin_id} успешно удалён!"
                )
                logger.info(f"✅ Удалён администратор: {remove_admin_id}")
            else:
                await update.message.reply_text(
                    f"❌ Ошибка при сохранении изменений."
                )
        
        return await admin_menu(update, context)
    
    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат ID. Введите числовой ID.\n"
            "Для отмены отправьте /cancel"
        )
        return ADMIN_REMOVE


# ==================== РЕЖИМ С КНОПКАМИ ====================

async def get_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получение места ДТП"""
    context.user_data['application']['location'] = update.message.text
    logger.info(f"📍 Место ДТП: {update.message.text}")
    
    keyboard = [
        ['2 автомобиля', '3 автомобиля'],
        ['Более 3 автомобилей']
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    
    await update.message.reply_text(
        "✅ Место ДТП сохранено.\n\n"
        "👥 Шаг 2/5: Сколько автомобилей участвовало?",
        reply_markup=reply_markup
    )
    return PARTICIPANTS


async def get_participants(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получение количества участников"""
    context.user_data['application']['participants'] = update.message.text
    logger.info(f"👥 Участники: {update.message.text}")
    
    await update.message.reply_text(
        "✅ Количество участников сохранено.\n\n"
        "🚗 Шаг 3/5: Опишите повреждения вашего автомобиля:\n"
        "(например: разбита фара, помят бампер)",
        reply_markup=ReplyKeyboardRemove()
    )
    return DAMAGE


async def get_damage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получение описания повреждений"""
    context.user_data['application']['damage'] = update.message.text
    logger.info(f"🚗 Повреждения: {update.message.text}")
    
    keyboard = [
        ['Нет пострадавших'],
        ['Есть пострадавшие']
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    
    await update.message.reply_text(
        "✅ Повреждения зафиксированы.\n\n"
        "🚑 Шаг 4/5: Есть ли пострадавшие?",
        reply_markup=reply_markup
    )
    return INJURIES


async def get_injuries(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получение информации о пострадавших"""
    context.user_data['application']['injuries'] = update.message.text
    logger.info(f"🚑 Пострадавшие: {update.message.text}")
    
    await update.message.reply_text(
        "✅ Информация сохранена.\n\n"
        "📞 Шаг 5/5: Укажите ваш контактный телефон:\n"
        "(например: +79001234567)",
        reply_markup=ReplyKeyboardRemove()
    )
    return CONTACT


async def get_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получение контактных данных и показ итоговой заявки"""
    context.user_data['application']['contact'] = update.message.text
    logger.info(f"📞 Контакт: {update.message.text}")
    
    app = context.user_data['application']
    
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
        ['✅ Подтвердить и отправить'],
        ['❌ Отменить']
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    
    await update.message.reply_text(
        summary + "\n\nПроверьте данные:",
        reply_markup=reply_markup
    )
    return CONFIRM


# ==================== AI РЕЖИМ ====================

async def ai_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка сообщений в AI режиме"""
    user_message = update.message.text
    logger.info(f"💬 AI-чат: {user_message}")
    
    # Проверка команды завершения
    if user_message.lower() in ['/finish', 'завершить', 'закончить', 'готово']:
        return await finish_ai_application(update, context)
    
    # Извлекаем данные из сообщения
    app = context.user_data['application']
    updated_fields = extract_info_from_message(user_message, app)
    
    # Добавляем в историю
    context.user_data['ai_history'].append({
        "role": "user",
        "content": user_message
    })
    
    # Получаем ответ от AI
    ai_response = get_ai_response(
        user_message,
        context.user_data['ai_history'],
        app
    )
    
    # Добавляем ответ в историю
    context.user_data['ai_history'].append({
        "role": "assistant",
        "content": ai_response
    })
    
    # Показываем что было обновлено
    if updated_fields:
        fields_updated = ', '.join(updated_fields.keys())
        ai_response = f"✅ Сохранено: {fields_updated}\n\n" + ai_response
    
    await update.message.reply_text(
        ai_response + "\n\n💡 Когда закончите, напишите /finish"
    )
    
    return AI_CHAT


async def finish_ai_application(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Завершение AI-режима и показ заявки"""
    app = context.user_data['application']
    
    # Проверка обязательных полей
    missing = []
    if not app.get('location'):
        missing.append('место ДТП')
    if not app.get('contact'):
        missing.append('телефон')
    
    if missing:
        await update.message.reply_text(
            f"⚠️ Пожалуйста, укажите: {', '.join(missing)}"
        )
        return AI_CHAT
    
    # Формируем итоговую заявку
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
        ['✅ Подтвердить и отправить'],
        ['❌ Отменить']
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    
    await update.message.reply_text(
        summary + "\n\nПроверьте данные:",
        reply_markup=reply_markup
    )
    return CONFIRM


# ==================== ПОДТВЕРЖДЕНИЕ ====================

async def confirm_application(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Подтверждение и отправка заявки"""
    choice = update.message.text
    
    if '✅' in choice:
        app = context.user_data['application']
        user = update.effective_user
        
        # Формируем информацию о пользователе
        user_info = {
            'first_name': user.first_name,
            'username': user.username,
            'user_id': user.id
        }
        
        # Формируем заявку
        formatted_application = format_application(app, user_info)
        
        # Отправляем администраторам
        await send_to_admins(context, formatted_application)
        
        # Логирование
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
        
        admins = load_admins()
        await update.message.reply_text(
            f"✅ ЗАЯВКА УСПЕШНО ОТПРАВЛЕНА!\n\n"
            f"Ваша заявка отправлена аварийному комиссару ({len(admins)} получателей).\n"
            f"С вами свяжутся в ближайшее время.\n\n"
            f"Для новой заявки отправьте /start",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END
    else:
        await update.message.reply_text(
            "❌ Заявка отменена.\n\n"
            "Отправьте /start для создания новой заявки.",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END


# ==================== ДОПОЛНИТЕЛЬНЫЕ КОМАНДЫ ====================

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена операции"""
    logger.info("❌ Операция отменена пользователем")
    await update.message.reply_text(
        "❌ Операция отменена.\n\nОтправьте /start для начала новой заявки.",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Справка"""
    help_text = (
        "🤖 СПРАВКА ПО БОТУ\n\n"
        "Команды:\n"
        "/start - Начать новую заявку\n"
        "/help - Показать эту справку\n"
        "/cancel - Отменить текущую операцию\n"
        "/myid - Узнать свой Telegram ID\n\n"
        "Режимы работы:\n"
        "🤖 AI-помощник - свободное общение\n"
        "📋 По шагам - ответы на вопросы\n\n"
        "В AI-режиме используйте /finish для завершения."
    )
    
    if is_admin(update.effective_user.id):
        help_text += "\n\n⚙️ Админ-команды:\n/start → Управление администраторами"
    
    await update.message.reply_text(help_text)


async def myid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать свой Telegram ID"""
    user = update.effective_user
    is_admin_user = is_admin(user.id)
    
    await update.message.reply_text(
        f"ℹ️ Ваша информация:\n\n"
        f"Имя: {user.first_name}\n"
        f"Username: @{user.username if user.username else 'не установлен'}\n"
        f"Telegram ID: `{user.id}`\n"
        f"Статус: {'👑 Администратор' if is_admin_user else '👤 Пользователь'}",
        parse_mode='Markdown'
    )


# ==================== ГЛАВНАЯ ФУНКЦИЯ ====================

def main():
    """Запуск бота"""
    logger.info("🚀 Запуск бота...")
    
    # Проверка наличия администраторов
    admins = load_admins()
    if not admins:
        logger.warning("⚠️  ВНИМАНИЕ: Нет администраторов!")
        logger.warning("⚠️  Заявки не будут отправляться!")
        logger.warning("⚠️  Добавьте администраторов в файл admins.txt или в код")
    else:
        logger.info(f"✅ Загружено {len(admins)} администраторов")
    
    try:
        # Создание приложения
        application = Application.builder().token(TELEGRAM_TOKEN).build()
        
        # Обработчик разговора
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', start)],
            states={
                CHOOSING_MODE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, choose_mode)
                ],
                LOCATION: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, get_location)
                ],
                PARTICIPANTS: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, get_participants)
                ],
                DAMAGE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, get_damage)
                ],
                INJURIES: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, get_injuries)
                ],
                CONTACT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, get_contact)
                ],
                AI_CHAT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, ai_chat),
                    CommandHandler('finish', finish_ai_application)
                ],
                CONFIRM: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_application)
                ],
                ADMIN_MENU: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, admin_menu_handler)
                ],
                ADMIN_ADD: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_handler)
                ],
                ADMIN_REMOVE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, admin_remove_handler)
                ],
            },
            fallbacks=[CommandHandler('cancel', cancel)],
        )
        
        # Добавление обработчиков
        application.add_handler(conv_handler)
        application.add_handler(CommandHandler('help', help_command))
        application.add_handler(CommandHandler('myid', myid_command))
        
        logger.info("✅ Бот запущен и готов к работе!")
        logger.info("📱 Найдите бота в Telegram и отправьте /start")
        
        # Запуск polling
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка при запуске бота: {e}")
        raise


if __name__ == '__main__':
    main()
