FROM node:20-slim

# Instalar OpenClaw globalmente
RUN npm install -g openclaw

WORKDIR /app

# Copiar el archivo de configuración
COPY agent.json .

# Crear un enlace simbólico a los binarios globales y ejecutar
CMD ["sh", "-c", "openclaw start --config agent.json || node /usr/local/lib/node_modules/openclaw/index.js"]

