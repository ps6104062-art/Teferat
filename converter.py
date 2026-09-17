import os
import shutil
import struct
import sqlite3


def _read_tdesktop_string(f):
    length = struct.unpack('>I', f.read(4))[0]
    if length == 0xffffffff:
        return None
    data = f.read(length)
    if length % 4:
        f.read(4 - length % 4)
    return data


def tdata_get_dc_auth(tdata_path):
    key_data_path = os.path.join(tdata_path, 'key_datas')
    if not os.path.exists(key_data_path):
        raise FileNotFoundError(f"key_datas not found in {tdata_path}")
    return True


async def session_to_tdata(session_path: str, output_dir: str, api_id: int, api_hash: str) -> str:
    from telethon import TelegramClient
    from telethon.sessions import SQLiteSession

    client = TelegramClient(session_path, api_id, api_hash)
    await client.connect()

    if not await client.is_user_authorized():
        await client.disconnect()
        raise Exception("Сессия не авторизована")

    session: SQLiteSession = client.session
    conn = sqlite3.connect(session.filename)
    cur = conn.cursor()

    cur.execute("SELECT dc_id, server_address, port, auth_key FROM sessions")
    row = cur.fetchone()
    conn.close()

    if not row:
        await client.disconnect()
        raise Exception("Не удалось прочитать данные сессии")

    dc_id, server, port, auth_key = row

    me = await client.get_me()
    user_id = me.id
    await client.disconnect()

    tdata_dir = os.path.join(output_dir, "tdata")
    os.makedirs(tdata_dir, exist_ok=True)

    _write_tdata_files(tdata_dir, dc_id, auth_key, user_id, api_id)

    zip_path = shutil.make_archive(os.path.join(output_dir, "tdata"), "zip", output_dir, "tdata")
    shutil.rmtree(tdata_dir, ignore_errors=True)
    return zip_path


def _write_tdata_files(tdata_dir, dc_id, auth_key, user_id, api_id):
    import hashlib

    def pack_data(data: bytes) -> bytes:
        length = len(data)
        pad = (4 - length % 4) % 4
        return struct.pack('>I', length) + data + b'\x00' * pad

    def create_map_file(path, dc_id, auth_key, user_id):
        with open(path, 'wb') as f:
            f.write(b'TDEF')
            f.write(struct.pack('>I', 1))
            f.write(struct.pack('>I', dc_id))
            f.write(pack_data(auth_key))
            f.write(struct.pack('>Q', user_id))

    os.makedirs(tdata_dir, exist_ok=True)
    map_path = os.path.join(tdata_dir, 'map0')
    create_map_file(map_path, dc_id, auth_key, user_id)
    shutil.copy(map_path, os.path.join(tdata_dir, 'map1'))

    key_data_path = os.path.join(tdata_dir, 'key_datas')
    with open(key_data_path, 'wb') as f:
        f.write(b'TDEF')
        f.write(struct.pack('>I', 1))
        f.write(struct.pack('>I', dc_id))
        f.write(pack_data(auth_key))


async def tdata_to_session(tdata_dir: str, output_path: str, api_id: int, api_hash: str) -> str:
    key_data_path = os.path.join(tdata_dir, 'key_datas')
    map_path = os.path.join(tdata_dir, 'map0')

    target = key_data_path if os.path.exists(key_data_path) else map_path
    if not os.path.exists(target):
        raise FileNotFoundError("Не найдены файлы key_datas или map0 в папке tdata")

    with open(target, 'rb') as f:
        magic = f.read(4)
        if magic != b'TDEF':
            raise Exception("Неверный формат tdata файла")
        f.read(4)
        dc_id = struct.unpack('>I', f.read(4))[0]
        auth_key_data = _read_tdesktop_string(f)

    from telethon import TelegramClient
    from telethon.sessions import SQLiteSession
    from telethon.crypto import AuthKey

    client = TelegramClient(output_path, api_id, api_hash)
    await client.connect()

    client.session.set_dc(dc_id, _dc_address(dc_id), 443)
    client.session.auth_key = AuthKey(auth_key_data)
    client.session.save()

    await client.disconnect()
    return output_path + ".session"


def _dc_address(dc_id: int) -> str:
    DCS = {
        1: "149.154.175.53",
        2: "149.154.167.51",
        3: "149.154.175.100",
        4: "149.154.167.91",
        5: "91.108.56.130",
    }
    return DCS.get(dc_id, "149.154.167.51")
