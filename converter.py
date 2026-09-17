import os
import shutil
from opentele.tl import TelegramClient as OpenClient
from opentele.td import TDesktop
from opentele.api import UseCurrentSession


async def session_to_tdata(session_path: str, output_dir: str, api_id: int, api_hash: str) -> str:
    client = OpenClient(session_path, api_id=api_id, api_hash=api_hash)
    await client.connect()

    tdata_path = os.path.join(output_dir, "tdata")
    await client.ToTData(tdata_path)
    await client.disconnect()

    zip_path = shutil.make_archive(os.path.join(output_dir, "tdata"), "zip", output_dir, "tdata")
    shutil.rmtree(tdata_path, ignore_errors=True)
    return zip_path


async def tdata_to_session(tdata_dir: str, output_path: str, api_id: int, api_hash: str) -> str:
    tdesk = TDesktop(tdata_dir)
    client = await tdesk.ToTelethon(output_path, UseCurrentSession, api_id=api_id, api_hash=api_hash)
    await client.connect()
    await client.disconnect()
    return output_path
