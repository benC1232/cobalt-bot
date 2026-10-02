FROM python:3.13-alpine
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY cobalt_bot ./cobalt_bot
USER nobody
CMD [ "python", "-m", "cobalt_bot.main" ]
