# cobalt discord bot

Watches chat for links, checks locally whether cobalt supports them, downloads the media through the
cobalt api from this repo into a temp folder, and replies in the same channel with the file attached.

- `cobalt_bot/services.py`: Python port of cobalt's url matching (`api/src/processing/url.js` +
  `service-config.js`). Unsupported links are dropped before any request reaches cobalt.
- `cobalt_bot/cobalt.py`: cobalt api client and size-capped downloader.
- `cobalt_bot/main.py`: the Discord client.
- `../docker-compose.yml`: runs cobalt + the bot.

## setup

1. Create an application at https://discord.com/developers/applications. Under **Bot**, copy the token and
   enable **Message Content Intent**. Invite it with the `bot` scope and the *Send Messages*,
   *Attach Files*, and *Read Message History* permissions.
2. `cp bot/.env.example bot/.env` and set `DISCORD_TOKEN`.
3. From the repo root: `docker compose up -d --build`
4. Logs: `docker compose logs -f bot`

Containers restart on crash and on boot (`sudo systemctl enable docker` so the daemon starts on boot).
Logs are capped at 3 x 10 MB per container.

## development

```sh
cd bot
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
docker build -t cobalt-api .. && docker run -d --rm --name cobalt -p 9000:9000 -e API_URL=http://localhost:9000/ cobalt-api
set -a; . ./.env; set +a; .venv/bin/python -m cobalt_bot.main
.venv/bin/python -m unittest      # replays cobalt's own test urls through the filter
```

## updating cobalt

```sh
git fetch upstream && git merge upstream/main
cd bot && .venv/bin/python -m unittest
```
Then check `git diff ORIG_HEAD -- api/src/processing/url.js api/src/processing/service-config.js`
for new services or patterns and mirror them in `cobalt_bot/services.py`.
