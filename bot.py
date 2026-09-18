import os
import asyncio
import shutil
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Updater, CommandHandler, CallbackQueryHandler,
    MessageHandler, Filters, ConversationHandler, CallbackContext
)
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError
from telethon.sync import TelegramClient as SyncClient

from config import BOT_TOKEN, API_ID, API_HASH
from converter import session_to_tdata, tdata_to_session

logging.basicConfig(level=logging.INFO)

TEMP_DIR = "temp"
os.makedirs(TEMP_DIR, exist_ok=True)

PHONE, CODE, PASSWORD = range(3)
WAIT_SESSION_FILE, WAIT_TDATA_FILE = range(3, 5)

tg_clients = {}


def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Session → TData", callback_data="session_to_tdata")],
        [InlineKeyboardButton("📂 TData → Session", callback_data="tdata_to_session")],
        [InlineKeyboardButton("✨ Создать сессию",  callback_data="create_session")],
    ])


def cmd_start(update: Update, ctx: CallbackContext):
    update.message.reply_text(
        "🔐 <b>Session Manager</b>\n\n"
        "Работа с Telegram сессиями:\n\n"
        "<b>📋 Session → TData</b> — конвертация для Telegram Desktop\n"
        "<b>📂 TData → Session</b> — конвертация для Telethon/Pyrogram\n"
        "<b>✨ Создать сессию</b> — авторизация нового аккаунта\n\n"
        "Выберите действие 👇",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )
    return ConversationHandler.END


# ── Session → TData ──
def cb_session_to_tdata(update: Update, ctx: CallbackContext):
    update.callback_query.answer()
    update.callback_query.edit_message_text(
        "📎 <b>Отправьте .session файл</b>\n\n"
        "<i>Файл будет сконвертирован в tdata.zip</i>",
        parse_mode="HTML"
    )
    return WAIT_SESSION_FILE


def handle_session_file(update: Update, ctx: CallbackContext):
    doc = update.message.document
    if not doc or not doc.file_name.endswith(".session"):
        update.message.reply_text(
            "❌ <b>Неверный формат</b>\n\nНужен файл с расширением <code>.session</code>",
            parse_mode="HTML"
        )
        return WAIT_SESSION_FILE

    uid = update.effective_user.id
    user_dir = os.path.join(TEMP_DIR, str(uid))
    os.makedirs(user_dir, exist_ok=True)
    session_path = os.path.join(user_dir, doc.file_name)
    doc.get_file().download(custom_path=session_path)

    msg = update.message.reply_text("⏳ <b>Конвертирую...</b>\n\nSession → TData", parse_mode="HTML")
    try:
        loop = asyncio.new_event_loop()
        zip_path = loop.run_until_complete(
            session_to_tdata(session_path.replace(".session", ""), user_dir, API_ID, API_HASH)
        )
        loop.close()
        update.message.reply_document(
            open(zip_path, "rb"),
            filename="tdata.zip",
            caption="✅ <b>Готово!</b>\n\n📂 Ваш <b>tdata.zip</b> готов к использованию",
            parse_mode="HTML"
        )
    except Exception as e:
        update.message.reply_text(f"❌ <b>Ошибка конвертации</b>\n\n<code>{e}</code>", parse_mode="HTML")
    finally:
        shutil.rmtree(user_dir, ignore_errors=True)
        msg.delete()

    update.message.reply_text("Главное меню:", reply_markup=main_menu())
    return ConversationHandler.END


# ── TData → Session ──
def cb_tdata_to_session(update: Update, ctx: CallbackContext):
    update.callback_query.answer()
    update.callback_query.edit_message_text(
        "📎 <b>Отправьте архив tdata.zip</b>\n\n"
        "<i>Внутри должна быть папка tdata/</i>",
        parse_mode="HTML"
    )
    return WAIT_TDATA_FILE


def handle_tdata_file(update: Update, ctx: CallbackContext):
    doc = update.message.document
    if not doc or not doc.file_name.endswith(".zip"):
        update.message.reply_text(
            "❌ <b>Неверный формат</b>\n\nНужен <code>.zip</code> архив с папкой tdata внутри",
            parse_mode="HTML"
        )
        return WAIT_TDATA_FILE

    uid = update.effective_user.id
    user_dir = os.path.join(TEMP_DIR, str(uid))
    os.makedirs(user_dir, exist_ok=True)
    zip_path = os.path.join(user_dir, "tdata.zip")
    doc.get_file().download(custom_path=zip_path)

    msg = update.message.reply_text("⏳ <b>Конвертирую...</b>\n\nTData → Session", parse_mode="HTML")
    try:
        shutil.unpack_archive(zip_path, user_dir)
        tdata_dir = os.path.join(user_dir, "tdata")
        session_out = os.path.join(user_dir, "account")
        loop = asyncio.new_event_loop()
        result_path = loop.run_until_complete(
            tdata_to_session(tdata_dir, session_out, API_ID, API_HASH)
        )
        loop.close()
        update.message.reply_document(
            open(result_path, "rb"),
            filename="account.session",
            caption="✅ <b>Готово!</b>\n\n📎 Ваш <b>.session</b> файл готов к использованию",
            parse_mode="HTML"
        )
    except Exception as e:
        update.message.reply_text(f"❌ <b>Ошибка конвертации</b>\n\n<code>{e}</code>", parse_mode="HTML")
    finally:
        shutil.rmtree(user_dir, ignore_errors=True)
        msg.delete()

    update.message.reply_text("Главное меню:", reply_markup=main_menu())
    return ConversationHandler.END


# ── Создать сессию ──
def cb_create_session(update: Update, ctx: CallbackContext):
    update.callback_query.answer()
    update.callback_query.edit_message_text(
        "📱 <b>Введите номер телефона</b>\n\n"
        "Формат: <code>+79991234567</code>",
        parse_mode="HTML"
    )
    return PHONE


def handle_phone(update: Update, ctx: CallbackContext):
    phone = update.message.text.strip()
    if not phone.startswith("+") or not phone[1:].isdigit():
        update.message.reply_text(
            "❌ <b>Неверный формат</b>\n\nПример: <code>+79991234567</code>",
            parse_mode="HTML"
        )
        return PHONE

    uid = update.effective_user.id
    user_dir = os.path.join(TEMP_DIR, str(uid))
    os.makedirs(user_dir, exist_ok=True)
    session_path = os.path.join(user_dir, "new_account")

    loop = asyncio.new_event_loop()

    async def send_code():
        client = SyncClient(session_path, API_ID, API_HASH, loop=loop)
        await client.connect()
        result = await client.send_code_request(phone)
        return client, result

    try:
        client, result = loop.run_until_complete(send_code())
        tg_clients[uid] = {
            "client": client,
            "loop": loop,
            "phone": phone,
            "phone_code_hash": result.phone_code_hash,
            "session_path": session_path + ".session",
            "user_dir": user_dir
        }
        update.message.reply_text(
            "✅ Код отправлен!\n\n"
            "💬 <b>Введите код</b> из SMS или Telegram\n"
            "<i>Можно с пробелами: 1 2 3 4 5</i>",
            parse_mode="HTML"
        )
        return CODE
    except Exception as e:
        loop.close()
        update.message.reply_text(f"❌ <b>Ошибка отправки кода</b>\n\n<code>{e}</code>", parse_mode="HTML")
        shutil.rmtree(user_dir, ignore_errors=True)
        return ConversationHandler.END


def handle_code(update: Update, ctx: CallbackContext):
    code = update.message.text.strip().replace(" ", "").replace("-", "")
    uid = update.effective_user.id

    if uid not in tg_clients:
        update.message.reply_text("❌ Сессия устарела. /start")
        return ConversationHandler.END

    data = tg_clients[uid]
    client = data["client"]
    loop = data["loop"]

    async def sign_in():
        return await client.sign_in(data["phone"], code, phone_code_hash=data["phone_code_hash"])

    try:
        loop.run_until_complete(sign_in())
        return finish_session(update, ctx, uid)
    except SessionPasswordNeededError:
        update.message.reply_text(
            "🔐 <b>Двухфакторная аутентификация</b>\n\n"
            "Введите пароль от аккаунта\n"
            "<i>Сообщение удалится автоматически</i>",
            parse_mode="HTML"
        )
        return PASSWORD
    except PhoneCodeInvalidError:
        update.message.reply_text("❌ <b>Неверный код</b>\n\nПопробуйте ещё раз:", parse_mode="HTML")
        return CODE
    except Exception as e:
        update.message.reply_text(f"❌ <b>Ошибка</b>\n\n<code>{e}</code>", parse_mode="HTML")
        cleanup(uid)
        return ConversationHandler.END


def handle_password(update: Update, ctx: CallbackContext):
    password = update.message.text.strip()
    uid = update.effective_user.id
    try:
        update.message.delete()
    except Exception:
        pass

    if uid not in tg_clients:
        update.message.reply_text("❌ Сессия устарела. /start")
        return ConversationHandler.END

    data = tg_clients[uid]
    client = data["client"]
    loop = data["loop"]

    async def sign_in_2fa():
        return await client.sign_in(password=password)

    try:
        loop.run_until_complete(sign_in_2fa())
        return finish_session(update, ctx, uid)
    except Exception as e:
        update.message.reply_text(f"❌ <b>Неверный пароль</b>\n\n<code>{e}</code>", parse_mode="HTML")
        cleanup(uid)
        return ConversationHandler.END


def finish_session(update: Update, ctx: CallbackContext, uid: int):
    data = tg_clients[uid]
    client = data["client"]
    loop = data["loop"]
    user_dir = data["user_dir"]
    session_path = data["session_path"]

    loop.run_until_complete(client.disconnect())
    loop.close()

    update.message.reply_document(
        open(session_path, "rb"),
        filename="account.session",
        caption="✅ <b>Авторизация успешна!</b>\n\nФайлы готовы — сохраните оба:",
        parse_mode="HTML"
    )

    try:
        new_loop = asyncio.new_event_loop()
        zip_path = new_loop.run_until_complete(
            session_to_tdata(session_path.replace(".session", ""), user_dir, API_ID, API_HASH)
        )
        new_loop.close()
        update.message.reply_document(
            open(zip_path, "rb"),
            filename="tdata.zip",
            caption="📂 <b>tdata.zip</b> — для Telegram Desktop",
            parse_mode="HTML"
        )
    except Exception as e:
        update.message.reply_text(f"⚠️ <b>tdata не создана</b>\n\n<code>{e}</code>", parse_mode="HTML")

    cleanup(uid)
    update.message.reply_text("Главное меню:", reply_markup=main_menu())
    return ConversationHandler.END


def cleanup(uid: int):
    data = tg_clients.pop(uid, {})
    loop = data.get("loop")
    if loop and not loop.is_closed():
        loop.close()
    user_dir = data.get("user_dir")
    if user_dir:
        shutil.rmtree(user_dir, ignore_errors=True)


def cancel(update: Update, ctx: CallbackContext):
    cleanup(update.effective_user.id)
    update.message.reply_text("Отменено.", reply_markup=main_menu())
    return ConversationHandler.END


def main():
    updater = Updater(BOT_TOKEN)
    dp = updater.dispatcher

    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(cb_session_to_tdata, pattern="^session_to_tdata$"),
            CallbackQueryHandler(cb_tdata_to_session, pattern="^tdata_to_session$"),
            CallbackQueryHandler(cb_create_session,   pattern="^create_session$"),
        ],
        states={
            WAIT_SESSION_FILE: [MessageHandler(Filters.document, handle_session_file)],
            WAIT_TDATA_FILE:   [MessageHandler(Filters.document, handle_tdata_file)],
            PHONE:    [MessageHandler(Filters.text & ~Filters.command, handle_phone)],
            CODE:     [MessageHandler(Filters.text & ~Filters.command, handle_code)],
            PASSWORD: [MessageHandler(Filters.text & ~Filters.command, handle_password)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("start", cmd_start),
        ],
    )

    dp.add_handler(CommandHandler("start", cmd_start))
    dp.add_handler(conv)

    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
