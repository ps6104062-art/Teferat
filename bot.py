import os
import asyncio
import shutil
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, ConversationHandler, filters
)
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError

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


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    # Чистим старое состояние если есть
    await cleanup(uid)
    await update.message.reply_text(
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


async def cb_session_to_tdata(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "📎 <b>Отправьте .session файл</b>\n\n"
        "<i>Файл будет сконвертирован в tdata.zip</i>",
        parse_mode="HTML"
    )
    return WAIT_SESSION_FILE


async def handle_session_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc or not doc.file_name.endswith(".session"):
        await update.message.reply_text(
            "❌ <b>Неверный формат</b>\n\nНужен файл <code>.session</code>",
            parse_mode="HTML"
        )
        return WAIT_SESSION_FILE

    uid = update.effective_user.id
    user_dir = os.path.join(TEMP_DIR, str(uid))
    os.makedirs(user_dir, exist_ok=True)
    session_path = os.path.join(user_dir, doc.file_name)

    tg_file = await doc.get_file()
    await tg_file.download_to_drive(session_path)

    msg = await update.message.reply_text("⏳ <b>Конвертирую Session → TData...</b>", parse_mode="HTML")
    try:
        zip_path = await session_to_tdata(
            session_path.replace(".session", ""), user_dir, API_ID, API_HASH
        )
        with open(zip_path, "rb") as f:
            await update.message.reply_document(
                f, filename="tdata.zip",
                caption="✅ <b>Готово!</b>\n\n📂 <b>tdata.zip</b> готов к использованию",
                parse_mode="HTML"
            )
    except Exception as e:
        await update.message.reply_text(
            f"❌ <b>Ошибка конвертации</b>\n\n<code>{e}</code>", parse_mode="HTML"
        )
    finally:
        shutil.rmtree(user_dir, ignore_errors=True)
        try:
            await msg.delete()
        except Exception:
            pass

    await update.message.reply_text("Главное меню:", reply_markup=main_menu())
    return ConversationHandler.END


async def cb_tdata_to_session(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "📎 <b>Отправьте архив tdata.zip</b>\n\n"
        "<i>Внутри должна быть папка tdata/</i>",
        parse_mode="HTML"
    )
    return WAIT_TDATA_FILE


async def handle_tdata_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc or not doc.file_name.endswith(".zip"):
        await update.message.reply_text(
            "❌ <b>Неверный формат</b>\n\nНужен <code>.zip</code> с папкой tdata внутри",
            parse_mode="HTML"
        )
        return WAIT_TDATA_FILE

    uid = update.effective_user.id
    user_dir = os.path.join(TEMP_DIR, str(uid))
    os.makedirs(user_dir, exist_ok=True)
    zip_path = os.path.join(user_dir, "tdata.zip")

    tg_file = await doc.get_file()
    await tg_file.download_to_drive(zip_path)

    msg = await update.message.reply_text("⏳ <b>Конвертирую TData → Session...</b>", parse_mode="HTML")
    try:
        shutil.unpack_archive(zip_path, user_dir)
        tdata_dir = os.path.join(user_dir, "tdata")
        session_out = os.path.join(user_dir, "account")
        result_path = await tdata_to_session(tdata_dir, session_out, API_ID, API_HASH)
        with open(result_path, "rb") as f:
            await update.message.reply_document(
                f, filename="account.session",
                caption="✅ <b>Готово!</b>\n\n📎 <b>account.session</b> готов к использованию",
                parse_mode="HTML"
            )
    except Exception as e:
        await update.message.reply_text(
            f"❌ <b>Ошибка конвертации</b>\n\n<code>{e}</code>", parse_mode="HTML"
        )
    finally:
        shutil.rmtree(user_dir, ignore_errors=True)
        try:
            await msg.delete()
        except Exception:
            pass

    await update.message.reply_text("Главное меню:", reply_markup=main_menu())
    return ConversationHandler.END


async def cb_create_session(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "📱 <b>Введите номер телефона</b>\n\n"
        "Формат: <code>+79991234567</code>",
        parse_mode="HTML"
    )
    return PHONE


async def handle_phone(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    if not phone.startswith("+") or not phone[1:].isdigit():
        await update.message.reply_text(
            "❌ <b>Неверный формат</b>\n\nПример: <code>+79991234567</code>",
            parse_mode="HTML"
        )
        return PHONE

    uid = update.effective_user.id
    await cleanup(uid)

    user_dir = os.path.join(TEMP_DIR, str(uid))
    os.makedirs(user_dir, exist_ok=True)
    session_path = os.path.join(user_dir, "new_account")

    client = TelegramClient(session_path, API_ID, API_HASH)
    await client.connect()

    try:
        result = await client.send_code_request(phone)
        tg_clients[uid] = {
            "client": client,
            "phone": phone,
            "phone_code_hash": result.phone_code_hash,
            "session_path": session_path + ".session",
            "user_dir": user_dir
        }
        await update.message.reply_text(
            "✅ Код отправлен!\n\n"
            "💬 <b>Введите код</b> из SMS или Telegram\n"
            "<i>Можно с пробелами: 1 2 3 4 5</i>",
            parse_mode="HTML"
        )
        return CODE
    except Exception as e:
        await client.disconnect()
        await update.message.reply_text(
            f"❌ <b>Ошибка отправки кода</b>\n\n<code>{e}</code>", parse_mode="HTML"
        )
        shutil.rmtree(user_dir, ignore_errors=True)
        return ConversationHandler.END


async def handle_code(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip().replace(" ", "").replace("-", "")
    uid = update.effective_user.id

    if uid not in tg_clients:
        await update.message.reply_text("❌ Сессия устарела. Нажми /start")
        return ConversationHandler.END

    data = tg_clients[uid]
    client: TelegramClient = data["client"]

    try:
        await client.sign_in(data["phone"], code, phone_code_hash=data["phone_code_hash"])
        return await finish_session(update, uid)
    except SessionPasswordNeededError:
        await update.message.reply_text(
            "🔐 <b>Двухфакторная аутентификация</b>\n\n"
            "Введите пароль от аккаунта\n"
            "<i>Сообщение удалится автоматически</i>",
            parse_mode="HTML"
        )
        return PASSWORD
    except PhoneCodeInvalidError:
        await update.message.reply_text(
            "❌ <b>Неверный код</b>\n\nПопробуйте ещё раз:", parse_mode="HTML"
        )
        return CODE
    except Exception as e:
        await update.message.reply_text(
            f"❌ <b>Ошибка</b>\n\n<code>{e}</code>", parse_mode="HTML"
        )
        await cleanup(uid)
        return ConversationHandler.END


async def handle_password(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    password = update.message.text.strip()
    uid = update.effective_user.id
    try:
        await update.message.delete()
    except Exception:
        pass

    if uid not in tg_clients:
        await update.message.reply_text("❌ Сессия устарела. Нажми /start")
        return ConversationHandler.END

    client: TelegramClient = tg_clients[uid]["client"]
    try:
        await client.sign_in(password=password)
        return await finish_session(update, uid)
    except Exception as e:
        await update.message.reply_text(
            f"❌ <b>Неверный пароль</b>\n\n<code>{e}</code>", parse_mode="HTML"
        )
        await cleanup(uid)
        return ConversationHandler.END


async def finish_session(update: Update, uid: int):
    data = tg_clients[uid]
    client: TelegramClient = data["client"]
    user_dir = data["user_dir"]
    session_path = data["session_path"]

    await client.disconnect()

    with open(session_path, "rb") as f:
        await update.message.reply_document(
            f, filename="account.session",
            caption="✅ <b>Авторизация успешна!</b>\n\nСохраните оба файла:",
            parse_mode="HTML"
        )

    try:
        zip_path = await session_to_tdata(
            session_path.replace(".session", ""), user_dir, API_ID, API_HASH
        )
        with open(zip_path, "rb") as f:
            await update.message.reply_document(
                f, filename="tdata.zip",
                caption="📂 <b>tdata.zip</b> — для Telegram Desktop",
                parse_mode="HTML"
            )
    except Exception as e:
        await update.message.reply_text(
            f"⚠️ <b>tdata не создана</b>\n\n<code>{e}</code>", parse_mode="HTML"
        )

    tg_clients.pop(uid, None)
    shutil.rmtree(user_dir, ignore_errors=True)
    await update.message.reply_text("Главное меню:", reply_markup=main_menu())
    return ConversationHandler.END


async def cleanup(uid: int):
    data = tg_clients.pop(uid, {})
    client = data.get("client")
    if client:
        try:
            await client.disconnect()
        except Exception:
            pass
    user_dir = data.get("user_dir")
    if user_dir:
        shutil.rmtree(user_dir, ignore_errors=True)


async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await cleanup(update.effective_user.id)
    await update.message.reply_text("Отменено.", reply_markup=main_menu())
    return ConversationHandler.END


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(cb_session_to_tdata, pattern="^session_to_tdata$"),
            CallbackQueryHandler(cb_tdata_to_session, pattern="^tdata_to_session$"),
            CallbackQueryHandler(cb_create_session,   pattern="^create_session$"),
        ],
        states={
            WAIT_SESSION_FILE: [MessageHandler(filters.Document.ALL, handle_session_file)],
            WAIT_TDATA_FILE:   [MessageHandler(filters.Document.ALL, handle_tdata_file)],
            PHONE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_phone)],
            CODE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code)],
            PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_password)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("start", cmd_start),
        ],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(conv)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
