import os
import logging
from dotenv import load_dotenv
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import (
    Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, Filters,
    ConversationHandler, CallbackContext, CallbackQueryHandler
)

# Логирование
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.DEBUG)
logger = logging.getLogger()

# Загрузка переменных окружения
load_dotenv()
TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
METHODIST_CHAT_ID = int(os.getenv("METHODIST_CHAT_ID"))
CAMP_CHAT_ID = int(os.getenv("CAMP_CHAT_ID"))

if not TOKEN or not ADMIN_ID:
    logger.error("Token or Admin ID is not set. Exiting...")
    exit(1)

# Словари
user_waiting_state = {}
user_id_by_username = {}
approved_users = set()  # Список одобренных user_id
approved_users = {ADMIN_ID}
pending_applications = {}

# Подключение к Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("telegram-bot-for-magistr-b1c60d226ade.json", scope)
client = gspread.authorize(creds)
sheet = client.open("Магистр: Регистрация")

# Состояния анкеты
ASK_FULL_NAME, ASK_BIRTHDAY, ASK_PHONE, ASK_GENDER, ASK_ROLE = range(5)
WAITING_TEXT = 100

#Состояние для организации мероприятий
CHOOSE_EVENT_TYPE, ASK_EVENT_NAME, ASK_EVENT_DATE, ASK_EVENT_PLACE, ASK_EVENT_DESCRIPTION, ASK_EVENT_EXTRA_INFO, ASK_EVENT_CONFIRMATION, SHOW_EVENT_DETAIL = range(8)

def handle_organize_event(update: Update, context: CallbackContext):
    # Проверяем, что это сообщение (а не callback query)
    if update.message:
        # Создаем инлайн клавиатуру
        keyboard = [
            [
                InlineKeyboardButton("Официальное мероприятие", callback_data='event_type_official'),
                InlineKeyboardButton("Неофициальное мероприятие", callback_data='event_type_unofficial')
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Отправляем сообщение с инлайн кнопками
        update.message.reply_text(
            "Выберите тип мероприятия:", 
            reply_markup=reply_markup
        )
    return CHOOSE_EVENT_TYPE  # Здесь возвращаем правильное состояние

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ КНОПОК ---
def get_cancel_or_skip_button():
    keyboard = [
        [InlineKeyboardButton("↩️ Вернуться в главное меню", callback_data="cancel_to_menu")],
        [InlineKeyboardButton("⏭ Пропустить", callback_data="skip_step")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_cancel_button():
    keyboard = [[InlineKeyboardButton("❌ Вернуться в главное меню", callback_data='cancel_to_menu')]]
    return InlineKeyboardMarkup(keyboard)
    
def cancel_to_menu(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    query.edit_message_text("Вы вернулись в главное меню.")
    return start(update, context)

# --- ХЕЛПЕР ДЛЯ СОХРАНЕНИЯ ТЕКУЩЕГО СОСТОЯНИЯ ---
def set_current_state(state):
    def wrapper(func):
        def wrapped(update, context):
            context.user_data["current_state"] = state
            return func(update, context)
        return wrapped
    return wrapper
    
# Функция для обработки кнопки "📅 Организовать мероприятие"
def handle_event_type_choice(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    if query.data == "event_type_official":
        context.user_data["event_type"] = "official"
    elif query.data == "event_type_unofficial":
        context.user_data["event_type"] = "unofficial"
    else:
        query.edit_message_text("Неверный выбор.")
        return ConversationHandler.END

    query.edit_message_text("Введите название мероприятия:")
    return ASK_EVENT_NAME

# Запрос имени мероприятия
@set_current_state(ASK_EVENT_NAME)
def ask_event_name(update: Update, context: CallbackContext):
    context.user_data["event_name"] = update.message.text
    update.message.reply_text("Введите дату и время мероприятия:", reply_markup=get_cancel_button())
    return ASK_EVENT_DATE

# Запрос даты и времени
@set_current_state(ASK_EVENT_DATE)
def ask_event_date(update: Update, context: CallbackContext):
    context.user_data["event_date"] = update.message.text
    update.message.reply_text("Введите место проведения мероприятия:", reply_markup=get_cancel_button())
    return ASK_EVENT_PLACE

# Запрос места проведения
@set_current_state(ASK_EVENT_PLACE)
def ask_event_place(update: Update, context: CallbackContext):
    context.user_data["event_place"] = update.message.text
    update.message.reply_text("Введите краткое описание мероприятия:", reply_markup=get_cancel_button())
    return ASK_EVENT_DESCRIPTION

# Запрос описания мероприятия
@set_current_state(ASK_EVENT_DESCRIPTION)
def ask_event_description(update: Update, context: CallbackContext):
    context.user_data["event_description"] = update.message.text
    update.message.reply_text("Введите дополнительную информацию о мероприятии (по желанию):", reply_markup=get_cancel_or_skip_button())
    return ASK_EVENT_EXTRA_INFO

# Запрос дополнительной информации
@set_current_state(ASK_EVENT_EXTRA_INFO)
def ask_event_extra_info(update: Update, context: CallbackContext):
    context.user_data["event_extra_info"] = update.message.text
    return ask_event_confirmation(update, context)


def skip_event_extra_info(update: Update, context: CallbackContext):
    query = update.callback_query
    context.user_data["event_extra_info"] = ""
    query.edit_message_text("Дополнительная информация пропущена.")
    return ask_event_confirmation(update, context)

def ask_event_confirmation(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    event_data = context.user_data
    message = (
        f"🔹 Название: {event_data.get('event_name')}\n"
        f"📅 Дата и время: {event_data.get('event_date')}\n"
        f"📍 Место: {event_data.get('event_place')}\n"
        f"📝 Описание: {event_data.get('event_description')}\n"
        f"ℹ️ Доп. информация: {event_data.get('event_extra_info') or '—'}\n\n"
        f"Подтвердить мероприятие?"
    )

    keyboard = [
        [InlineKeyboardButton("✅ Да", callback_data="confirm_yes")],
        [InlineKeyboardButton("❌ Нет", callback_data="confirm_no")]
    ]
    query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard))
    return ASK_EVENT_CONFIRMATION

def confirm_event(update: Update, context: CallbackContext):
    global sheet  
    query = update.callback_query
    query.answer()
    choice = query.data

    username = query.from_user.username or "без username"
    context.user_data["organizer_username"] = username

    if choice == "confirm_yes":
        sheet_name = "Мероприятия официальные" if context.user_data.get("event_type") == "official" else "Мероприятия неофициальные"
        worksheet = sheet.worksheet(sheet_name)

        new_row = [
            context.user_data.get("event_name"),
            context.user_data.get("event_date"),
            context.user_data.get("event_place"),
            context.user_data.get("event_description"),
            context.user_data.get("event_extra_info", ""),
            context.user_data.get("organizer_username")
        ]
        worksheet.append_row(new_row, table_range="A2")

        query.edit_message_text("✅ Мероприятие успешно зарегистрировано!")
        return ConversationHandler.END

    else:
        query.edit_message_text("❌ Регистрация мероприятия отменена.")
        # Переход в главное меню после отмены
        return start(update, context)
        
def save_event_to_sheet(context: CallbackContext):
    spreadsheet_id = "1GcQQjuSMA3ytaGlJ8WPh8hHupLhTy9b7EQnwgh23-Ag"
    service = context.bot_data["sheets_service"]

    values = [[
        context.user_data["event_name"],
        context.user_data["event_date"],
        context.user_data["event_place"],
        context.user_data["event_description"],
        context.user_data.get("event_extra_info", ""),
        f"@{context.user_data['organizer_username']}"
    ]]

    if context.user_data.get("event_type") == "official":
        range_name = "Мероприятия официальные!A2:F"
    else:
        range_name = "Мероприятия неофициальные!A2:F"

    body = {"values": values}
    service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=range_name,
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body=body
    ).execute()

# Команды и анкета
def start(update: Update, context: CallbackContext):
    user = update.effective_user
    user_id = user.id
    logger.info("User started the bot.")

    if user_id in approved_users:
        if user_id == ADMIN_ID:
            keyboard = ReplyKeyboardMarkup(
                [
                    ["📅 Организовать мероприятие", "📋 Узнать мероприятия"],
                    ["🎯 Смена"],
                    ["📢 Написать методистам", "📢 Написать всему центру"],
                    ["🛑 Распрощаться с человеком"]
                ],
                resize_keyboard=True
            )
        else:
            keyboard = ReplyKeyboardMarkup(
                [
                    ["📅 Организовать мероприятие", "📋 Узнать мероприятия"],
                    ["🎯 Смена"]
                ],
                resize_keyboard=True
            )
    else:
        keyboard = ReplyKeyboardMarkup(
            [
                ["📝 Подать заявку", "👨‍💼 Руководитель"],
                ["ℹ️ Полезная информация"]
            ],
            resize_keyboard=True
        )

    text = "Привет! Выберите действие ниже:"

    # Отправка в зависимости от типа апдейта
    if update.message:
        update.message.reply_text(text, reply_markup=keyboard)
    elif update.callback_query:
        update.callback_query.message.reply_text(text, reply_markup=keyboard)

    return ConversationHandler.END

def handle_menu(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    text = update.message.text
    logger.info(f"User {user_id} selected menu option or sent message. Text: {text}. State: {context.user_data.get('state', 'No state')}")

    if text == "📝 Подать заявку":
        return begin_application(update, context)  # Переход к началу регистрации
    else:
        update.message.reply_text("Пожалуйста, выберите одну из доступных команд.")
        return WAITING_TEXT  # Ожидание следующего действия пользователя

def begin_application(update: Update, context: CallbackContext):
    logger.info(f"User {update.message.from_user.id} started the registration process.")
    update.message.reply_text("Начнем регистрацию. Введите ваше <b>ФИО</b>:", parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
    context.user_data['state'] = ASK_FULL_NAME  # Установить состояние
    return ASK_FULL_NAME

def ask_birthday(update: Update, context: CallbackContext):
    context.user_data["full_name"] = update.message.text
    logger.info(f"User {update.message.from_user.id} provided full name: {update.message.text}")
    update.message.reply_text("Введите дату рождения (например, 01.01.2000):")
    return ASK_BIRTHDAY

def ask_phone(update: Update, context: CallbackContext):
    context.user_data["birthday"] = update.message.text
    logger.info(f"User {update.message.from_user.id} provided birthday: {update.message.text}")
    update.message.reply_text("Введите номер телефона:")
    return ASK_PHONE

def ask_gender(update: Update, context: CallbackContext):
    context.user_data["phone"] = update.message.text
    logger.info(f"User {update.message.from_user.id} provided phone: {update.message.text}")
    keyboard = [[
        InlineKeyboardButton("Мужской", callback_data="male"),
        InlineKeyboardButton("Женский", callback_data="female")
    ]]
    update.message.reply_text("Выберите пол:", reply_markup=InlineKeyboardMarkup(keyboard))
    return ASK_GENDER

def ask_role(update: Update, context: CallbackContext):
    context.user_data["gender"] = update.callback_query.data
    logger.info(f"User {update.callback_query.from_user.id} selected gender: {update.callback_query.data}")
    keyboard = [[
        InlineKeyboardButton("Методист", callback_data="methodist"),
        InlineKeyboardButton("Магистр", callback_data="magistr")
    ]]
    update.callback_query.message.reply_text("Выберите должность:", reply_markup=InlineKeyboardMarkup(keyboard))
    return ASK_ROLE

def submit_application(update: Update, context: CallbackContext):
    user_data = context.user_data

    if update.callback_query:
        user = update.callback_query.from_user
        user_data["role"] = update.callback_query.data
    elif update.message:
        user = update.message.from_user
        user_data["role"] = update.message.text
    else:
        return ConversationHandler.END

    user_data["user_id"] = user.id
    user_data["username"] = user.username if user.username else "нет username"
    if user.username:
        user_id_by_username[user.username] = user.id

    pending_applications[user.id] = user_data

    text = (
        f"📋 Новая заявка:\n"
        f"👤 ФИО: {user_data['full_name']}\n"
        f"🎂 Дата рождения: {user_data['birthday']}\n"
        f"📞 Телефон: {user_data['phone']}\n"
        f"🚻 Пол: {user_data['gender']}\n"
        f"💼 Должность: {user_data['role']}\n"
        f"🆔 Telegram: @{user_data['username']}"
    )

    buttons = [[
        InlineKeyboardButton("✅ Одобрить", callback_data=f"approve:{user_data['user_id']}"),
        InlineKeyboardButton("❌ Отклонить", callback_data=f"reject:{user_data['user_id']}")
    ]]

    logger.info(f"Sending new application from {user_data['username']} to admin.")
    context.bot.send_message(chat_id=ADMIN_ID, text=text, reply_markup=InlineKeyboardMarkup(buttons))

    if update.callback_query:
        update.callback_query.message.reply_text("Ваша заявка отправлена на рассмотрение.", reply_markup=ReplyKeyboardRemove())
    elif update.message:
        update.message.reply_text("Ваша заявка отправлена на рассмотрение.", reply_markup=ReplyKeyboardRemove())

    return ConversationHandler.END

def handle_approval_rejection(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    action, user_id_str = query.data.split(":")
    user_id = int(user_id_str)
    user_data = pending_applications.get(user_id)

    if not user_data:
        logger.warning(f"Данные заявки для user_id {user_id} не найдены.")
        query.message.reply_text("Ошибка: заявка не найдена.")
        return ConversationHandler.END

    # Общие данные
    role = user_data["role"].strip().lower()
    username = user_data["username"]
    full_name = user_data["full_name"]
    birthday = user_data["birthday"]
    phone = user_data["phone"]
    gender = user_data["gender"]

    if action == "approve":
        sheet_name = "Методисты" if role == "methodist" else "Магистры"
        worksheet = sheet.worksheet(sheet_name)
        worksheet.append_row([full_name, birthday, phone, gender, f"@{username}"])
        approved_users.add(user_id)

        # Сообщение + клавиатура
        links = [
            "https://t.me/+_nrCKWdshN8wNzRi",
            "https://t.me/+P1S3QOP5LP40NjE6"
        ]
        if role == "methodist":
            links = [
                "https://t.me/+TEBK6X4Zvos1YzEy",
                "https://t.me/+bTsWQjpu3JoxMmZi",
                *links
            ]

        message = "Ваша заявка одобрена! 🎉\nПрисоединяйтесь к чатам:\n" + "\n".join(links)
        context.bot.send_message(chat_id=user_id, text=message)

        keyboard = ReplyKeyboardMarkup(
            [
                ["📅 Организовать мероприятие", "📋 Узнать мероприятия"],
                ["🎯 Смена"]
            ],
            resize_keyboard=True
        )
        context.bot.send_message(chat_id=user_id, text="Вы теперь участник! Вот ваше меню:", reply_markup=keyboard)
        query.message.reply_text("Заявка одобрена ✅")

    elif action == "reject":
        context.bot.send_message(chat_id=user_id, text="Ваша заявка отклонена.")
        query.message.reply_text("Заявка отклонена ❌")

    query.edit_message_reply_markup(reply_markup=None)
    return ConversationHandler.END

def handle_menu_text(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    state = user_waiting_state.get(user_id)
    text = update.message.text
    logger.info(f"User {user_id} selected menu option or sent message. Text: {text}. State: {state}")

    if state in ["writing_to_methodists", "writing_to_camp"]:
        return handle_message_for_sending(update, context)

    # Расширенные опции для руководителя
    if user_id == ADMIN_ID:
        cancel_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Отменить", callback_data="cancel_action")]
        ])

        if text == "📢 Написать методистам":
            user_waiting_state[user_id] = "writing_to_methodists"
            return update.message.reply_text("Введите сообщение для методистов:", reply_markup=cancel_markup)
        elif text == "📢 Написать всему центру":
            user_waiting_state[user_id] = "writing_to_camp"
            return update.message.reply_text("Введите сообщение для всего центра:", reply_markup=cancel_markup)
        elif text == "🛑 Распрощаться с человеком":
            return update.message.reply_text("Эта функция в разработке 👷")

    # Общие команды
    if text == "👨‍💼 Руководитель":
        return show_admin_menu(update, context)
    elif text == "ℹ️ Полезная информация":
        return help_command(update, context)
    else:
        update.message.reply_text("Пожалуйста, выберите одну из доступных команд.")

def help_command(update: Update, context: CallbackContext):
    update.message.reply_text(
        "ℹ️ <b>Полезная информация:</b>\n\n"
        "— Подать заявку: нажмите «Подать заявку» в меню или введите /start\n"
        "— Руководитель: доступно только администратору\n"
        "— Отменить действия: /cancel\n\n"
        "Если что-то не работает — напишите нам!",
        parse_mode="HTML"
    )
def show_admin_menu(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        logger.warning(f"Unauthorized access attempt by user {update.effective_user.id}")
        return

    logger.info(f"User {update.message.from_user.id} is admin. Showing main keyboard again.")
    update.message.reply_text("Режим руководителя активен. Используйте команды с клавиатуры ниже.")
    return start(update, context)  # просто переотправляем клавиатуру

def handle_events_menu(update: Update, context: CallbackContext):
    update.callback_query.answer()
    update.callback_query.message.reply_text("Вы выбрали 'Написать методистам'. Введите сообщение.")
    user_waiting_state[update.effective_user.id] = "writing_to_methodists"
    logger.info(f"User {update.callback_query.from_user.id} selected 'Написать методистам'.")


def handle_camp_menu(update: Update, context: CallbackContext):
    update.callback_query.answer()
    update.callback_query.message.reply_text("Вы выбрали 'Написать всему центру'. Введите сообщение.")
    user_waiting_state[update.effective_user.id] = "writing_to_camp"
    logger.info(f"User {update.callback_query.from_user.id} selected 'Написать всему центру'.")

def handle_cancel_action(update: Update, context: CallbackContext):
    user_id = update.callback_query.from_user.id
    user_waiting_state[user_id] = None  # Сброс состояния ожидания
    logger.info(f"User {user_id} cancelled action.")

    # Подтверждаем callback запрос
    update.callback_query.answer()

    # Отправляем сообщение о том, что действие отменено
    update.callback_query.message.reply_text("Ожидание сообщения отменено.")

    # Возвращаем в главное меню
    update.callback_query.message.reply_text("Возвращаюсь в главное меню.", reply_markup=main_menu_keyboard())

    return ConversationHandler.END  # Завершаем текущую беседу

def handle_message_for_sending(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    state = user_waiting_state.get(user_id)
    logger.info(f"Обработано сообщение от пользователя {user_id}. Текущее состояние: {state}")

    # Логирование всех данных сообщения
    logger.info(f"Содержимое сообщения: {update.message}")
    logger.info(f"Тип сообщения: {type(update.message)}")

    # Если пользователь в режиме написания методистам или центру
    if state == "writing_to_methodists":
        target_chat_id = METHODIST_CHAT_ID
        logger.info(f"Отправка в методисты. chat_id: {target_chat_id}")
    elif state == "writing_to_camp":
        target_chat_id = CAMP_CHAT_ID
        logger.info(f"Отправка в лагерь. chat_id: {target_chat_id}")
    else:
        logger.warning(f"Неизвестное состояние для пользователя {user_id}, состояние: {state}")
        update.message.reply_text("Ошибка состояния. Пожалуйста, выберите одну из доступных команд.")
        return handle_menu_text(update, context)

    try:
        # Логирование медиа, если оно есть
        if update.message.photo:
            logger.info(f"Фото получено: {update.message.photo}")
            largest_photo = update.message.photo[-1]
            logger.info(f"Самое большое фото: {largest_photo.file_id}")
            caption = update.message.caption if update.message.caption else ""
            context.bot.send_photo(
                chat_id=target_chat_id,
                photo=largest_photo.file_id,
                caption=caption
            )

        elif update.message.video:
            logger.info(f"Видео получено: {update.message.video.file_id}")
            context.bot.send_video(
                chat_id=target_chat_id,
                video=update.message.video.file_id,
                caption=update.message.caption
            )
        elif update.message.document:
            logger.info(f"Документ получен: {update.message.document.file_id}")
            context.bot.send_document(
                chat_id=target_chat_id,
                document=update.message.document.file_id,
                caption=update.message.caption
            )
        elif update.message.text:
            logger.info(f"Текстовое сообщение: {update.message.text}")
            context.bot.send_message(
                chat_id=target_chat_id,
                text=update.message.text
            )
        else:
            logger.warning(f"Неизвестный тип сообщения от пользователя {user_id}, Тип: {type(update.message)}")
            update.message.reply_text("Не удалось обработать это сообщение.")

        update.message.reply_text("Сообщение отправлено.")
        logger.info(f"Сообщение успешно отправлено в чат {target_chat_id}")

    except Exception as e:
        logger.error(f"Ошибка при пересылке сообщения: {e}")
        update.message.reply_text("Не удалось отправить сообщение. Пожалуйста, попробуйте снова.")

#Календарь мероприятий
def show_event_type_menu(update: Update, context: CallbackContext):
    logger.debug("show_event_type_menu called")  # Проверь, что функция вызывается
    keyboard = [
        [InlineKeyboardButton("Узнать про официальные мероприятия", callback_data="view_official_events")],
        [InlineKeyboardButton("Узнать про неофициальные мероприятия", callback_data="view_unofficial_events")],
        [InlineKeyboardButton("Назад", callback_data="cancel_to_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        update.message.reply_text("Выберите тип мероприятий:", reply_markup=reply_markup)
    elif update.callback_query:
        update.callback_query.edit_message_text("Выберите тип мероприятий:", reply_markup=reply_markup)

# Обработчик календаря мероприятий с логированием
def handle_view_events(update: Update, context: CallbackContext):
    # Логируем начало обработки
    logger.debug("handle_view_events called with update: %s", update)
    query = update.callback_query
    query.answer()  # Отвечаем на запрос пользователя

    # Логируем полученные данные callback
    logger.debug("Callback data: %s", query.data)

    try:
        # Проверяем, что пришлел запрос на официальные мероприятия
        if query.data == "view_official_events":
            logger.debug("Fetching official events")
            events = get_events_from_sheet("Мероприятия официальные")
            send_event_summaries(events, query)
        # Если неофициальные
        elif query.data == "view_unofficial_events":
            logger.debug("Fetching unofficial events")
            events = get_events_from_sheet("Мероприятия неофициальные")
            send_event_summaries(events, query)
        else:
            logger.warning("Unknown callback data: %s", query.data)

    except Exception as e:
        # Логируем ошибку, если что-то пошло не так
        logger.error("Error occurred in handle_view_events: %s", e)

# Получение мероприятий из Google Sheets с логированием
def get_events_from_sheet(sheet_name):
    try:
        logger.debug("Fetching events from sheet: %s", sheet_name)

        # Получаем данные из листа
        sheet = sheet.worksheet(sheet_name)
        data = worksheet.get_all_values()[1:]  # Пропускаем заголовки

        logger.debug("Fetched %d rows of data from sheet '%s'", len(data), sheet_name)

        events = []
        for i, row in enumerate(data):
            if len(row) < 6:
                logger.warning("Skipping row %d due to insufficient data", i)
                continue
            event = {
                'name': row[0],
                'datetime': row[1],
                'place': row[2],
                'description': row[3],
                'extra_info': row[4],
                'organizer': row[5]
            }
            events.append(event)

        logger.debug("Successfully fetched %d events from sheet '%s'", len(events), sheet_name)

        if not events:
            logger.warning("No events found in sheet '%s'", sheet_name)  # Если список пустой, добавим предупреждение

        return events
    except Exception as e:
        logger.error("Error fetching events from sheet '%s': %s", sheet_name, e)
        return []

# Отправка кратких описаний мероприятий с логированием и обработкой ошибок
def send_event_summaries(events, query):
    try:
        # Логируем начало обработки
        logger.debug("send_event_summaries called with %d events", len(events) if events else 0)

        if not events:
            logger.info("No events found.")
            query.edit_message_text("Пока нет мероприятий.")
            return

        # Логируем, что мероприятия есть и начинаем их отправку
        logger.debug("Sending event summaries...")

        for i, event in enumerate(events):
            # Формируем текст с кратким описанием мероприятия
            text = f"<b>{event['name']}</b>\n🕒 {event['datetime']}\n📍 {event['place']}\n📝 {event['description']}"
            # Логируем информацию о каждом мероприятии
            logger.debug("Event %d: %s", i, text)

            # Формируем кнопки для отображения подробной информации
            keyboard = [[InlineKeyboardButton("Подробнее", callback_data=f"event_detail_{i}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            # Отправляем сообщение с кратким описанием
            query.message.bot.send_message(chat_id=query.message.chat.id, text=text, parse_mode="HTML", reply_markup=reply_markup)
            logger.debug("Event %d summary sent", i)

        # Логируем завершение отправки всех мероприятий
        query.edit_message_text("Вот список мероприятий 👇")
        logger.debug("All event summaries sent.")

        # Сохраняем список мероприятий для кнопок «Подробнее»
        context = query.message.bot_data
        context['current_events'] = events
        logger.debug("Event list saved for 'Подробнее' button.")
    except Exception as e:
        logger.error("Error in send_event_summaries: %s", e)
        query.edit_message_text("Произошла ошибка при отправке мероприятий. Пожалуйста, попробуйте снова.")

# Показать подробную информацию о мероприятии с логированием
def show_event_detail(update: Update, context: CallbackContext):
    # Логируем начало обработки
    logger.debug("show_event_detail called with update: %s", update)

    query = update.callback_query
    query.answer()  # Отвечаем на запрос пользователя

    # Логируем данные callback
    logger.debug("Callback data: %s", query.data)

    try:
        # Извлекаем индекс мероприятия из данных callback
        event_index = int(query.data.split("_")[-1])
        logger.debug("Extracted event index: %d", event_index)

        # Получаем список мероприятий из context
        events = context.bot_data.get('current_events', [])
        if event_index >= len(events):
            query.message.reply_text("Ошибка: мероприятие не найдено.")
            logger.warning("Event index out of range: %d", event_index)
            return

        # Логируем, что мероприятие найдено
        event = events[event_index]
        logger.debug("Fetched event: %s", event)

        # Формируем текст с деталями мероприятия
        text = (
            f"<b>{event['name']}</b>\n\n"
            f"<b>Дата и время:</b> {event['datetime']}\n"
            f"<b>Место:</b> {event['place']}\n"
            f"<b>Описание:</b> {event['description']}\n"
            f"<b>Доп. информация:</b> {event['extra_info']}\n"
            f"<b>Организатор:</b> @{event['organizer']}"
        )

        # Отправляем сообщение с деталями
        query.edit_message_text(text, parse_mode="HTML")
        logger.debug("Event details sent: %s", text)

    except Exception as e:
        # Логируем ошибку, если что-то пошло не так
        logger.error("Error occurred in show_event_detail: %s", e)

# Запуск бота
def main():
    updater = Updater(TOKEN, use_context=True)
    dispatcher = updater.dispatcher
    bot: Bot = updater.bot
    bot.set_my_commands([
        ("start", "📝 Подать заявку"),
        ("admin", "👨‍💼 Руководитель"),
        ("help", "ℹ️ Полезная информация")
    ])

    # ConversationHandler для подачи заявки (регистрация пользователя)
    registration_handler = ConversationHandler(
        entry_points=[MessageHandler(Filters.regex("^📝 Подать заявку$"), handle_menu)],
        states={
            ASK_FULL_NAME: [MessageHandler(Filters.text, ask_birthday)],
            ASK_BIRTHDAY: [MessageHandler(Filters.text, ask_phone)],
            ASK_PHONE: [MessageHandler(Filters.text, ask_gender)],
            ASK_GENDER: [CallbackQueryHandler(ask_role)],
            ASK_ROLE: [CallbackQueryHandler(submit_application)],
        },
        fallbacks=[CallbackQueryHandler(cancel_to_menu, pattern="cancel_to_menu")],
        allow_reentry=True
    )
    dispatcher.add_handler(registration_handler)

    event_calendar_handler = ConversationHandler(
        entry_points=[MessageHandler(Filters.regex("^📖 Узнать мероприятия$"), show_event_type_menu)],
        states={
            CHOOSE_EVENT_TYPE: [CallbackQueryHandler(handle_view_events, pattern="^view_")],
            SHOW_EVENT_DETAIL: [CallbackQueryHandler(show_event_detail, pattern="^event_detail_")],
        },
        fallbacks=[CallbackQueryHandler(cancel_to_menu, pattern="cancel_to_menu")],
        allow_reentry=True
    )
    dispatcher.add_handler(event_calendar_handler)

    # ConversationHandler для организации мероприятия
    conv_handler_event = ConversationHandler(
        entry_points=[MessageHandler(Filters.regex("^📅 Организовать мероприятие$"), handle_organize_event)],
        states={
            CHOOSE_EVENT_TYPE: [CallbackQueryHandler(handle_event_type_choice, pattern="^event_type_")],
            ASK_EVENT_NAME: [MessageHandler(Filters.text & ~Filters.command, ask_event_name), CallbackQueryHandler(cancel_to_menu, pattern="cancel_to_menu")],
            ASK_EVENT_DATE: [MessageHandler(Filters.text & ~Filters.command, ask_event_date), CallbackQueryHandler(cancel_to_menu, pattern="cancel_to_menu")],
            ASK_EVENT_PLACE: [MessageHandler(Filters.text & ~Filters.command, ask_event_place), CallbackQueryHandler(cancel_to_menu, pattern="cancel_to_menu")],
            ASK_EVENT_DESCRIPTION: [MessageHandler(Filters.text & ~Filters.command, ask_event_description), CallbackQueryHandler(cancel_to_menu, pattern="cancel_to_menu")],
            ASK_EVENT_EXTRA_INFO: [MessageHandler(Filters.text & ~Filters.command, ask_event_extra_info), CallbackQueryHandler(cancel_to_menu, pattern="cancel_to_menu"), CallbackQueryHandler(skip_event_extra_info, pattern="skip_step")],
            ASK_EVENT_CONFIRMATION: [CallbackQueryHandler(confirm_event, pattern="^confirm_yes$|^confirm_no$"), CallbackQueryHandler(cancel_to_menu, pattern="cancel_to_menu")],
        },
        fallbacks=[CallbackQueryHandler(show_event_type_menu, pattern="^📖 Узнать мероприятия$"), CallbackQueryHandler(cancel_to_menu, pattern="cancel_to_menu")],
        allow_reentry=True
    )
    dispatcher.add_handler(conv_handler_event)

    # Обработчики для календаря мероприятий
    dispatcher.add_handler(MessageHandler(Filters.regex("^📋 Узнать мероприятия$"), show_event_type_menu))
    dispatcher.add_handler(CallbackQueryHandler(handle_view_events, pattern="^view_"))
    dispatcher.add_handler(CallbackQueryHandler(show_event_detail, pattern="^event_detail_"))

    # Обработчики для меню руководителя
    dispatcher.add_handler(CallbackQueryHandler(handle_events_menu, pattern="events_menu"))
    dispatcher.add_handler(CallbackQueryHandler(handle_camp_menu, pattern="camp_menu"))
    dispatcher.add_handler(CallbackQueryHandler(handle_approval_rejection, pattern="^(approve|reject):"))
    dispatcher.add_handler(MessageHandler(Filters.regex("^📅 Организовать мероприятие$"), handle_organize_event))
    dispatcher.add_handler(CallbackQueryHandler(cancel_to_menu, pattern="cancel_to_menu"))
    dispatcher.add_handler(CommandHandler("admin", show_admin_menu))

    # ➕ Добавляем обработчик для кнопки "Отменить" (cancel_action)
    dispatcher.add_handler(CallbackQueryHandler(handle_cancel_action, pattern="cancel_action"))

    # Текстовые сообщения (не команды)
    dispatcher.add_handler(MessageHandler(Filters.text & (~Filters.command), handle_menu_text))

    # Медиа и документы
    dispatcher.add_handler(MessageHandler(Filters.photo | Filters.video | Filters.document, handle_message_for_sending))

    updater.start_polling(timeout=30, drop_pending_updates=True)
    updater.idle()

if __name__ == '__main__':
    main()
