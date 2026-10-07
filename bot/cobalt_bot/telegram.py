"""Telegram bot: re-uploads media from any cobalt-supported link posted in chat."""

import asyncio
import logging
import os
import tempfile
from pathlib import Path

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramAPIError
from aiogram.types import (
    FSInputFile,
    InputMediaAudio,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
    LinkPreviewOptions,
    Message,
)
from aiogram.utils.chat_action import ChatActionSender

from . import cobalt
from .services import match_service

log = logging.getLogger("cobalt-bot.telegram")

MAX_MEDIA_PER_GROUP = 10
UPLOAD_LIMIT = 50 * 1024 * 1024  # bot api cap for any upload
PHOTO_LIMIT = 10 * 1024 * 1024  # bigger photos have to go as documents
UPLOAD_TIMEOUT = 300  # seconds; aiogram's default of 60 is too short for 50 MB on a slow uplink
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)

PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTS = {".mp4", ".mov"}
AUDIO_EXTS = {".mp3", ".m4a"}
ANIMATION_EXTS = {".gif"}

dp = Dispatcher()


@dp.message(F.text | F.caption)
async def on_message(message: Message, bot: Bot, http: aiohttp.ClientSession):
    if message.from_user and message.from_user.is_bot:
        return

    urls = dict.fromkeys(extract_urls(message))  # dedupe, keep order
    for url in urls:
        service = match_service(url)
        if not service:
            continue
        try:
            await handle_url(message, bot, http, url, service)
        except Exception:
            log.exception("unhandled error for %s", url)


def extract_urls(message: Message) -> list[str]:
    """Links as telegram parsed them, including hidden text links."""
    text = message.text or message.caption or ""
    urls = []
    for entity in message.entities or message.caption_entities or []:
        if entity.type == "url":
            url = entity.extract_from(text)
            urls.append(url if "://" in url else f"https://{url}")
        elif entity.type == "text_link":
            urls.append(entity.url)
    return [u for u in urls if u.startswith(("http://", "https://"))]


async def handle_url(message: Message, bot: Bot, http: aiohttp.ClientSession, url: str, service: str):
    user = message.from_user.username or message.from_user.id if message.from_user else "?"
    log.info("%s link from %s: %s", service, user, url)
    max_bytes = int(os.environ["TELEGRAM_MAX_UPLOAD_MB"]) * 1024 * 1024 \
        if os.environ.get("TELEGRAM_MAX_UPLOAD_MB") else UPLOAD_LIMIT
    limit_mb = max_bytes // (1024 * 1024)

    async with ChatActionSender.upload_document(bot=bot, chat_id=message.chat.id,
                                                message_thread_id=message.message_thread_id):
        try:
            items = await cobalt.resolve(http, url)
        except (cobalt.CobaltError, aiohttp.ClientError, ValueError) as e:
            log.warning("cobalt failed for %s: %r", url, e)
            await reply(message, f"couldn't download {url}: {getattr(e, 'code', 'cobalt unreachable')}")
            return

        with tempfile.TemporaryDirectory(prefix="cobalt-bot-") as tmp:
            files: list[Path] = []
            skipped = 0
            try:
                for item in items:
                    try:
                        files.append(await cobalt.download(http, item, Path(tmp), max_bytes))
                    except cobalt.TooLargeError:
                        skipped += 1
            except (cobalt.CobaltError, aiohttp.ClientError) as e:
                log.warning("download failed for %s: %r", url, e)
                await reply(message, f"couldn't download {url}: {getattr(e, 'code', 'download failed')}")
                return

            if not files:
                await reply(message, f"the file from {url} is larger than the {limit_mb} MB upload limit.")
                return

            try:
                await send_files(message, files)
            except TelegramAPIError as e:
                log.warning("upload failed for %s: %r", url, e)
                await reply(message, f"couldn't upload the file from {url}: {e.message}")
                return
            total_mb = sum(p.stat().st_size for p in files) / (1024 * 1024)
            log.info("sent %d file(s) (%.1f MB) for %s in chat %s", len(files), total_mb, url, message.chat.id)
            if skipped:
                log.info("skipped %d file(s) over %d MB for %s", skipped, limit_mb, url)
                await reply(message, f"skipped {skipped} file(s) over the {limit_mb} MB upload limit.")


def kind(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in PHOTO_EXTS and path.stat().st_size <= PHOTO_LIMIT:
        return "photo"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in ANIMATION_EXTS:
        return "animation"
    return "document"


async def send_files(message: Message, files: list[Path]):
    """Sends files as native telegram media, batching them into albums where telegram allows it.

    Albums can mix photos and videos, but audio and documents only group with their own kind,
    and gifs can't be in albums at all.
    """
    groups: dict[str, list[Path]] = {}
    for path in files:
        k = kind(path)
        group = "visual" if k in ("photo", "video") else path.name if k == "animation" else k
        groups.setdefault(group, []).append(path)

    for paths in groups.values():
        for i in range(0, len(paths), MAX_MEDIA_PER_GROUP):
            chunk = paths[i:i + MAX_MEDIA_PER_GROUP]
            if len(chunk) == 1:
                await send_single(message, chunk[0])
            else:
                await message.reply_media_group([input_media(p) for p in chunk])


async def send_single(message: Message, path: Path):
    file = FSInputFile(path)
    match kind(path):
        case "photo":
            await message.reply_photo(file)
        case "video":
            await message.reply_video(file, supports_streaming=True)
        case "audio":
            await message.reply_audio(file)
        case "animation":
            await message.reply_animation(file)
        case _:
            await message.reply_document(file)


def input_media(path: Path):
    file = FSInputFile(path)
    match kind(path):
        case "photo":
            return InputMediaPhoto(media=file)
        case "video":
            return InputMediaVideo(media=file, supports_streaming=True)
        case "audio":
            return InputMediaAudio(media=file)
        case _:
            return InputMediaDocument(media=file)


async def reply(message: Message, content: str):
    await message.reply(content, link_preview_options=NO_PREVIEW)


async def run():
    bot = Bot(os.environ["TELEGRAM_TOKEN"], session=AiohttpSession(timeout=UPLOAD_TIMEOUT))
    async with aiohttp.ClientSession() as http:
        me = await bot.get_me()
        log.info("logged in as @%s", me.username)
        await dp.start_polling(bot, http=http)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(name)s %(message)s")
    asyncio.run(run())


if __name__ == "__main__":
    main()
