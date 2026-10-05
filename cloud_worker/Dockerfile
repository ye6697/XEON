FROM node:22-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-pip python3-venv git ca-certificates curl && rm -rf /var/lib/apt/lists/*
RUN npm install -g @openai/codex@latest

WORKDIR /opt/xeon-work
COPY requirements.txt /opt/xeon-work/requirements.txt
RUN python3 -m pip install --break-system-packages --no-cache-dir -r requirements.txt
COPY . /opt/xeon-work

RUN mkdir -p /var/lib/xeon-work && chmod 700 /var/lib/xeon-work
EXPOSE 8787
CMD ["python3","-m","uvicorn","app:app","--host","0.0.0.0","--port","8787"]
