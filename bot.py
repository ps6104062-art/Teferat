import os
import asyncio
import shutil
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    FSInputFile
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError

from config import BOT_TOKEN, API_ID, API_HASH
from converter import session_to_tdata, tdata_to_session

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

TEMP_DIR = "temp"
os.makedirs(TEMP_DIR, exist_ok=True)

tg_clients: dict = {}


class CreateSession(StatesGroup):
    waiting_phone = State()
    waiting_code = State()
    waiting_password = State()

class ConvertSession(StatesGroup):
    waiting_session_file = State()

class ConvertTData(StatesGroup):
    waiting_tdata_file = State()


def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Session → TData", callback_data="session_to_tdata")],
        [InlineKeyboardButton(text="📂 TData → Session", callback_data="tdata_to_session")],
        [InlineKeyboardButton(text="✨ Создать сессию",  callback_data="create_session")],
    ])


@dp.message(F.text == "/start")
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🔐 <b>Session Manager</b>\n\n"
        "Работа с Telegram сессиями:\n\n"
        "<b>📋 Session → TData</b> — конвертация для Telegram Desktop\n"
        "<b>📂 TData → Session</b> — конвертация для Telethon/Pyrogram\n"
        "<b>✨ Создать сессию</b> — авторизация нового аккаунта\n\n"
        "Выберите действие 👇",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )


# ── Session → TData ──
@dp.callback_query(F.data == "session_to_tdata")
async def cb_session_to_tdata(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text(
        "📎 <b>Отправьте .session файл</b>\n\n"
        "<i>Файл будет сконвертирован в tdata.zip</i>",
        parse_mode="HTML"
    )
    await state.set_state(ConvertSession.waiting_session_file)
    await call.answer()


@dp.message(ConvertSession.waiting_session_file, F.document)
async def handle_session_file(message: Message, state: FSMContext):
    doc = message.document
    if not doc.file_name.endswith(".session"):
        await message.answer(
            "❌ <b>Неверный формат</b>\n\nНужен файл с расширением <code>.session</code>",
            parse_mode="HTML"
        )
        return

    user_dir = os.path.join(TEMP_DIR, str(message.from_user.id))
    os.makedirs(user_dir, exist_ok=True)
    session_path = os.path.join(user_dir, doc.file_name)
    await bot.download(doc, destination=session_path)

    msg = await message.answer("⏳ <b>Конвертирую...</b>\n\nSession → TData", parse_mode="HTML")
    try:
        zip_path = await session_to_tdata(
            session_path.replace(".session", ""),
            user_dir, API_ID, API_HASH
        )
        await bot.send_document(
            message.chat.id,
            FSInputFile(zip_path, filename="tdata.zip"),
            caption="✅ <b>Готово!</b>\n\n📂 Ваш <b>tdata.zip</b> готов к использованию",
            parse_mode="HTML"
        )
    except Exception as e:
        await message.answer(f"❌ <b>Ошибка конвертации</b>\n\n<code>{e}</code>", parse_mode="HTML")
    finally:
        shutil.rmtree(user_dir, ignore_errors=True)
        await msg.delete()

    await state.clear()
    await message.answer("Главное меню:", reply_markup=main_menu())


# ── TData → Session ──
@dp.callback_query(F.data == "tdata_to_session")
async def cb_tdata_to_session(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text(
        "📎 <b>Отправьте архив tdata.zip</b>\n\n"
        "<i>Внутри должна быть папка tdata/</i>",
        parse_mode="HTML"
    )
    await state.set_state(ConvertTData.waiting_tdata_file)
    await call.answer()


@dp.message(ConvertTData.waiting_tdata_file, F.document)
async def handle_tdata_file(message: Message, state: FSMContext):
    doc = message.document
    if not doc.file_name.endswith(".zip"):
        await message.answer(
            "❌ <b>Неверный формат</b>\n\nНужен <code>.zip</code> архив с папкой tdata внутри",
            parse_mode="HTML"
        )
        return

    user_dir = os.path.join(TEMP_DIR, str(message.from_user.id))
    os.makedirs(user_dir, exist_ok=True)
    zip_path = os.path.join(user_dir, "tdata.zip")
    await bot.download(doc, destination=zip_path)

    msg = await message.answer("⏳ <b>Конвертирую...</b>\n\nTData → Session", parse_mode="HTML")
    try:
        shutil.unpack_archive(zip_path, user_dir)
        tdata_dir = os.path.join(user_dir, "tdata")
        session_out = os.path.join(user_dir, "account.session")
        await tdata_to_session(tdata_dir, session_out, API_ID, API_HASH)
        await bot.send_document(
            message.chat.id,
            FSInputFile(session_out, filename="account.session"),
            caption="✅ <b>Готово!</b>\n\n📎 Ваш <b>.session</b> файл готов к использованию",
            parse_mode="HTML"
        )
    except Exception as e:
        await message.answer(f"❌ <b>Ошибка конвертации</b>\n\n<code>{e}</code>", parse_mode="HTML")
    finally:
        shutil.rmtree(user_dir, ignore_errors=True)
        await msg.delete()

    await state.clear()
    await message.answer("Главное меню:", reply_markup=main_menu())


# ── Создать сессию ──
@dp.callback_query(F.data == "create_session")
async def cb_create_session(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text(
        "📱 <b>Введите номер телефона</b>\n\n"
        "Формат: <code>+79991234567</code>",
        parse_mode="HTML"
    )
    await state.set_state(CreateSession.waiting_phone)
    await call.answer()


@dp.message(CreateSession.waiting_phone)
async def handle_phone(message: Message, state: FSMContext):
    phone = message.text.strip()
    if not phone.startswith("+") or not phone[1:].isdigit():
        await message.answer(
            "❌ <b>Неверный формат</b>\n\nПример: <code>+79991234567</code>",
            parse_mode="HTML"
        )
        return

    user_dir = os.path.join(TEMP_DIR, str(message.from_user.id))
    os.makedirs(user_dir, exist_ok=True)
    session_path = os.path.join(user_dir, "new_account")

    client = TelegramClient(session_path, API_ID, API_HASH)
    await client.connect()

    try:
        result = await client.send_code_request(phone)
        tg_clients[message.from_user.id] = {
            "client": client,
            "phone": phone,
            "phone_code_hash": result.phone_code_hash,
            "session_path": session_path + ".session",
            "user_dir": user_dir
        }
        await state.set_state(CreateSession.waiting_code)
        await message.answer(
            "✅ Код отправлен!\n\n"
            "💬 <b>Введите код</b> из SMS или Telegram\n"
            "<i>Можно с пробелами: 1 2 3 4 5</i>",
            parse_mode="HTML"
        )
    except Exception as e:
        await client.disconnect()
        await message.answer(f"❌ <b>Ошибка отправки кода</b>\n\n<code>{e}</code>", parse_mode="HTML")
        await state.clear()


@dp.message(CreateSession.waiting_code)
async def handle_code(message: Message, state: FSMContext):
    code = message.text.strip().replace(" ", "").replace("-", "")
    uid = message.from_user.id

    if uid not in tg_clients:
        await message.answer("❌ Сессия устарела. Начните заново /start")
        await state.clear()
        return

    data = tg_clients[uid]
    client: TelegramClient = data["client"]

    try:
        await client.sign_in(data["phone"], code, phone_code_hash=data["phone_code_hash"])
        await _finish_session(message, state, uid)
    except SessionPasswordNeededError:
        await state.set_state(CreateSession.waiting_password)
        await message.answer(
            "🔐 <b>Двухфакторная аутентификация</b>\n\n"
            "Введите пароль от аккаунта\n"
            "<i>Сообщение удалится автоматически</i>",
            parse_mode="HTML"
        )
    except PhoneCodeInvalidError:
        await message.answer("❌ <b>Неверный код</b>\n\nПопробуйте ещё раз:", parse_mode="HTML")
    except Exception as e:
        await message.answer(f"❌ <b>Ошибка</b>\n\n<code>{e}</code>", parse_mode="HTML")
        await _cleanup(uid, state)


@dp.message(CreateSession.waiting_password)
async def handle_password(message: Message, state: FSMContext):
    password = message.text.strip()
    uid = message.from_user.id
    try:
        await message.delete()
    except Exception:
        pass

    if uid not in tg_clients:
        await message.answer("❌ Сессия устарела. /start")
        await state.clear()
        return

    client: TelegramClient = tg_clients[uid]["client"]
    try:
        await client.sign_in(password=password)
        await _finish_session(message, state, uid)
    except Exception as e:
        await message.answer(f"❌ <b>Неверный пароль</b>\n\n<code>{e}</code>", parse_mode="HTML")
        await _cleanup(uid, state)


async def _finish_session(message: Message, state: FSMContext, uid: int):
    data = tg_clients[uid]
    client: TelegramClient = data["client"]
    user_dir = data["user_dir"]
    session_path = data["session_path"]

    await client.disconnect()

    await bot.send_document(
        message.chat.id,
        FSInputFile(session_path, filename="account.session"),
        caption="✅ <b>Авторизация успешна!</b>\n\nФайлы готовы — сохраните оба:",
        parse_mode="HTML"
    )

    try:
        zip_path = await session_to_tdata(
            session_path.replace(".session", ""),
            user_dir, API_ID, API_HASH
        )
        await bot.send_document(
            message.chat.id,
            FSInputFile(zip_path, filename="tdata.zip"),
            caption="📂 <b>tdata.zip</b> — для Telegram Desktop",
            parse_mode="HTML"
        )
    except Exception as e:
        await bot.send_message(
            message.chat.id,
            f"⚠️ <b>tdata не создана</b>\n\n<code>{e}</code>",
            parse_mode="HTML"
        )

    await _cleanup(uid, state)
    await bot.send_message(message.chat.id, "Главное меню:", reply_markup=main_menu())


async def _cleanup(uid: int, state: FSMContext):
    data = tg_clients.pop(uid, {})
    user_dir = data.get("user_dir")
    if user_dir:
        shutil.rmtree(user_dir, ignore_errors=True)
    await state.clear()


async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
