import os
import shutil
import sqlite3
import struct
import hashlib


# ── Session → TData ──
async def session_to_tdata(session_path: str, output_dir: str, api_id: int, api_hash: str) -> str:
    from telethon import TelegramClient

    client = TelegramClient(session_path, api_id, api_hash)
    await client.connect()

    if not await client.is_user_authorized():
        await client.disconnect()
        raise Exception("Сессия не авторизована")

    conn = sqlite3.connect(client.session.filename)
    cur = conn.cursor()
    cur.execute("SELECT dc_id, auth_key FROM sessions")
    row = cur.fetchone()
    conn.close()

    if not row:
        await client.disconnect()
        raise Exception("Не удалось прочитать данные сессии")

    dc_id, auth_key = row
    me = await client.get_me()
    user_id = me.id
    await client.disconnect()

    tdata_dir = os.path.join(output_dir, "tdata")
    os.makedirs(tdata_dir, exist_ok=True)

    _build_tdata(tdata_dir, dc_id, bytes(auth_key), user_id)

    zip_path = shutil.make_archive(
        os.path.join(output_dir, "tdata"), "zip", output_dir, "tdata"
    )
    shutil.rmtree(tdata_dir, ignore_errors=True)
    return zip_path


def _build_tdata(tdata_dir: str, dc_id: int, auth_key: bytes, user_id: int):
    """
    Строит структуру TData совместимую с Telegram Desktop.
    Использует формат MTP (Mobile Transport Protocol).
    """
    os.makedirs(tdata_dir, exist_ok=True)

    # Локальный ключ (просто 256 случайных байт для локального шифрования)
    local_key = os.urandom(256)

    # Пишем key_datas
    _write_key_datas(tdata_dir, local_key)

    # Пишем основной файл с данными аккаунта (D877F783D5D3EF8C)
    _write_main_data(tdata_dir, dc_id, auth_key, user_id, local_key)

    # Пишем settings
    _write_settings(tdata_dir)


def _tdf_magic():
    return b'TDF$'


def _pack_string(s: bytes) -> bytes:
    """Упаковка строки в формате Qt"""
    if s is None:
        return struct.pack('>I', 0xffffffff)
    length = len(s)
    pad = (4 - length % 4) % 4
    return struct.pack('>I', length) + s + b'\x00' * pad


def _tdf_file(data: bytes, version: int = 1002013) -> bytes:
    """Создаёт TDF файл с заголовком и MD5 чексуммой"""
    magic = _tdf_magic()
    ver = struct.pack('<I', version)
    # MD5 от (data + ver + magic)
    md5 = hashlib.md5(data + ver + magic).digest()
    return magic + ver + data + md5


def _write_key_datas(tdata_dir: str, local_key: bytes):
    """key_datas — хранит локальный ключ шифрования"""
    # Формат: salt(32) + key(256) + hash(64)
    salt = os.urandom(32)
    iterations = 4000
    # PBKDF2 с пустым паролем
    import hashlib as hl
    key_hash = hl.pbkdf2_hmac('sha512', b'', salt, iterations)

    data = salt + local_key + key_hash[:64]
    content = _tdf_file(data)

    path0 = os.path.join(tdata_dir, 'key_datas')
    path1 = os.path.join(tdata_dir, 'key_datas_')
    with open(path0, 'wb') as f:
        f.write(content)
    with open(path1, 'wb') as f:
        f.write(content)


def _write_main_data(tdata_dir: str, dc_id: int, auth_key: bytes, user_id: int, local_key: bytes):
    """
    D877F783D5D3EF8C — основной файл с данными авторизации.
    Содержит dc_id, auth_key и user_id в формате MTP.
    """
    # Упрощённый формат данных авторизации
    # quint32 magic + quint32 dc_id + QByteArray auth_key + quint64 user_id
    inner = struct.pack('<I', 0x4B474354)  # magic TGKB
    inner += struct.pack('<I', dc_id)
    inner += struct.pack('<I', len(auth_key)) + auth_key
    inner += struct.pack('<q', user_id)

    content = _tdf_file(inner)

    fname = 'D877F783D5D3EF8C'
    path0 = os.path.join(tdata_dir, fname)
    path1 = os.path.join(tdata_dir, fname + 's')
    with open(path0, 'wb') as f:
        f.write(content)
    with open(path1, 'wb') as f:
        f.write(content)


def _write_settings(tdata_dir: str):
    """settings файл"""
    data = struct.pack('<I', 0)  # пустые настройки
    content = _tdf_file(data)

    path0 = os.path.join(tdata_dir, 'settings0')
    path1 = os.path.join(tdata_dir, 'settings1')
    with open(path0, 'wb') as f:
        f.write(content)
    with open(path1, 'wb') as f:
        f.write(content)


# ── TData → Session ──
async def tdata_to_session(tdata_dir: str, output_path: str, api_id: int, api_hash: str) -> str:
    from telethon import TelegramClient
    from telethon.crypto import AuthKey

    # Ищем файл с данными авторизации
    main_file = None
    for name in ['D877F783D5D3EF8C', 'key_datas']:
        p = os.path.join(tdata_dir, name)
        if os.path.exists(p):
            main_file = p
            break

    if not main_file:
        raise FileNotFoundError("Не найдены файлы авторизации в папке tdata")

    dc_id, auth_key = _read_main_data(main_file)

    client = TelegramClient(output_path, api_id, api_hash)
    await client.connect()

    client.session.set_dc(dc_id, _dc_address(dc_id), 443)
    client.session.auth_key = AuthKey(auth_key)
    client.session.save()

    await client.disconnect()
    return output_path + ".session"


def _read_main_data(filepath: str):
    with open(filepath, 'rb') as f:
        magic = f.read(4)
        if magic != _tdf_magic():
            raise Exception(f"Неверный magic: {magic}")
        f.read(4)  # version
        data = f.read()
        data = data[:-16]  # убираем MD5

    # Пробуем наш формат
    try:
        offset = 0
        file_magic = struct.unpack_from('<I', data, offset)[0]
        offset += 4
        if file_magic == 0x4B474354:
            dc_id = struct.unpack_from('<I', data, offset)[0]
            offset += 4
            key_len = struct.unpack_from('<I', data, offset)[0]
            offset += 4
            auth_key = data[offset:offset + key_len]
            return dc_id, auth_key
    except Exception:
        pass

    # Пробуем старый формат
    try:
        offset = 0
        dc_id = struct.unpack_from('>I', data, offset)[0]
        offset += 4
        key_len = struct.unpack_from('>I', data, offset)[0]
        offset += 4
        auth_key = data[offset:offset + key_len]
        if 1 <= dc_id <= 5 and key_len == 256:
            return dc_id, auth_key
    except Exception:
        pass

    raise Exception("Не удалось прочитать данные авторизации из tdata")


def _dc_address(dc_id: int) -> str:
    DCS = {
        1: "149.154.175.53",
        2: "149.154.167.51",
        3: "149.154.175.100",
        4: "149.154.167.91",
        5: "91.108.56.130",
    }
    return DCS.get(dc_id, "149.154.167.51")
