FROM node:20-slim

# Instalar OpenClaw globalmente
RUN npm install -g openclaw

WORKDIR /app

# Copiar el archivo de configuración
COPY agent.json .

# Indicar la ruta exacta del ejecutable de openclaw
CMD ["npx", "openclaw", "start", "--config", "agent.json"]
