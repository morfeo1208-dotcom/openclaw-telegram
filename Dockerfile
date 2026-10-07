FROM node:20-slim

# Instalar OpenClaw de forma global
RUN npm install -g openclaw

WORKDIR /app

# Copiar el archivo de configuración del agente
COPY agent.json .

# Comando para iniciar el agente de OpenClaw
CMD ["openclaw", "start", "--config", "agent.json"]
