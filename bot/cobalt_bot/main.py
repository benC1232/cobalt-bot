"""Discord bot: re-uploads media from any cobalt-supported link posted in chat."""

import logging
import os
import re
import tempfile
from pathlib import Path

import aiohttp
import discord

from . import cobalt
from .services import match_service

log = logging.getLogger("cobalt-bot")

MAX_ATTACHMENTS_PER_MESSAGE = 10
DEFAULT_UPLOAD_LIMIT = 10 * 1024 * 1024  # DMs, unboosted servers
NO_PING = discord.AllowedMentions(replied_user=False)

# http(s) links, including ones wrapped in <> to suppress embeds
URL_REGEX = re.compile(r"""https?://[^\s<>]+[^\s<>.,:;"')\]!?]""")


class CobaltBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.http_session: aiohttp.ClientSession | None = None

    async def setup_hook(self):
        self.http_session = aiohttp.ClientSession()

    async def close(self):
        if self.http_session:
            await self.http_session.close()
        await super().close()

    async def on_ready(self):
        log.info("logged in as %s", self.user)

    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        urls = dict.fromkeys(URL_REGEX.findall(message.content))  # dedupe, keep order
        for url in urls:
            service = match_service(url)
            if not service:
                continue
            try:
                await self.handle_url(message, url, service)
            except Exception:
                log.exception("unhandled error for %s", url)

    async def handle_url(self, message: discord.Message, url: str, service: str):
        log.info("%s link from %s: %s", service, message.author, url)
        max_bytes = int(os.environ["MAX_UPLOAD_MB"]) * 1024 * 1024 if os.environ.get("MAX_UPLOAD_MB") \
            else message.guild.filesize_limit if message.guild else DEFAULT_UPLOAD_LIMIT
        limit_mb = max_bytes // (1024 * 1024)

        async with message.channel.typing():
            try:
                items = await cobalt.resolve(self.http_session, url)
            except (cobalt.CobaltError, aiohttp.ClientError, ValueError) as e:
                log.warning("cobalt failed for %s: %r", url, e)
                await reply(message, f"couldn't download <{url}>: `{getattr(e, 'code', 'cobalt unreachable')}`")
                return

            with tempfile.TemporaryDirectory(prefix="cobalt-bot-") as tmp:
                files: list[Path] = []
                skipped = 0
                try:
                    for item in items:
                        try:
                            files.append(await cobalt.download(self.http_session, item, Path(tmp), max_bytes))
                        except cobalt.TooLargeError:
                            skipped += 1
                except (cobalt.CobaltError, aiohttp.ClientError) as e:
                    log.warning("download failed for %s: %r", url, e)
                    await reply(message, f"couldn't download <{url}>: `{getattr(e, 'code', 'download failed')}`")
                    return

                if not files:
                    await reply(message, f"the file from <{url}> is larger than the {limit_mb} MB upload limit here.")
                    return

                for i in range(0, len(files), MAX_ATTACHMENTS_PER_MESSAGE):
                    chunk = files[i:i + MAX_ATTACHMENTS_PER_MESSAGE]
                    await message.reply(files=[discord.File(p) for p in chunk], allowed_mentions=NO_PING)
                total_mb = sum(p.stat().st_size for p in files) / (1024 * 1024)
                log.info("sent %d file(s) (%.1f MB) for %s in #%s", len(files), total_mb, url, message.channel)
                if skipped:
                    log.info("skipped %d file(s) over %d MB for %s", skipped, limit_mb, url)
                    await reply(message, f"skipped {skipped} file(s) over the {limit_mb} MB upload limit.")


async def reply(message: discord.Message, content: str):
    await message.reply(content, allowed_mentions=NO_PING, suppress_embeds=True)


def main():
    CobaltBot().run(os.environ["DISCORD_TOKEN"], root_logger=True)


if __name__ == "__main__":
    main()
