import os
import threading
import logging
from flask import Flask, render_template_string, request, jsonify
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from core.orchestrator import Orchestrator

app = Flask(__name__)
orquestador = Orchestrator()
logging.basicConfig(level=logging.INFO)

# --- CONFIGURACIÓN DE LA INTERFAZ WEB ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OpenClaw Multiagente IA</title>
    <style>
        body { font-family: Arial, sans-serif; background: #0b0f19; color: #f8fafc; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
        .chat-container { width: 100%; max-width: 600px; background: #1e293b; padding: 20px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.6); display: flex; flex-direction: column; height: 85vh; }
        .header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #334155; padding-bottom: 10px; margin-bottom: 10px; }
        .chat-box { flex: 1; overflow-y: auto; padding: 10px; display: flex; flex-direction: column; gap: 12px; }
        .message { padding: 12px 16px; border-radius: 10px; max-width: 85%; line-height: 1.5; font-size: 14px; }
        .user { background: #2563eb; align-self: flex-end; }
        .assistant { background: #334155; align-self: flex-start; border-left: 4px solid #10b981; }
        .input-area { display: flex; gap: 10px; margin-top: 10px; }
        input { flex: 1; padding: 12px; border-radius: 8px; border: 1px solid #475569; background: #0f172a; color: white; font-size: 14px; }
        button { padding: 12px 24px; background: #10b981; border: none; border-radius: 8px; color: white; font-weight: bold; cursor: pointer; }
        button:hover { background: #059669; }
    </style>
</head>
<body>
    <div class="chat-container">
        <div class="header">
            <h3>🤖 OpenClaw Multiagente</h3>
            <span style="font-size: 12px; color: #10b981;">● En línea (Web & Telegram)</span>
        </div>
        <div class="chat-box" id="chatBox"></div>
        <div class="input-area">
            <input type="text" id="userInput" placeholder="Escribe una tarea o consulta..." onkeypress="if(event.key === 'Enter') sendMessage()">
            <button onclick="sendMessage()">Enviar</button>
        </div>
    </div>

    <script>
        async function sendMessage() {
            const input = document.getElementById('userInput');
            const chatBox = document.getElementById('chatBox');
            const text = input.value.trim();
            if (!text) return;

            chatBox.innerHTML += `<div class="message user">${text}</div>`;
            input.value = '';
            chatBox.scrollTop = chatBox.scrollHeight;

            const response = await fetch('/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: text })
            });
            const data = await response.json();

            chatBox.innerHTML += `<div class="message assistant">${data.reply}</div>`;
            chatBox.scrollTop = chatBox.scrollHeight;
        }
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/chat', methods=['POST'])
def chat():
    user_message = request.json.get('message', '')
    resultado = orquestador.procesar_solicitud(user_message)
    return jsonify({'reply': resultado['texto']})


# --- CONFIGURACIÓN DEL BOT DE TELEGRAM ---
async def handle_telegram_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    if not user_message:
        return
    
    # Procesar con el mismo orquestador central
    resultado = orquestador.procesar_solicitud(user_message)
    await update.message.reply_text(resultado['texto'])

def run_telegram_bot():
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        logging.warning("TELEGRAM_TOKEN no configurado. El bot de Telegram no se iniciará.")
        return
    
    # Limpiar webhooks pendientes e iniciar polling
    application = ApplicationBuilder().token(token).build()
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_telegram_message))
    
    logging.info("Iniciando bot de Telegram en segundo plano...")
    application.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    # Arrancar Telegram en un hilo independiente para que no bloquee a Flask
    telegram_thread = threading.Thread(target=run_telegram_bot, daemon=True)
    telegram_thread.start()

    # Arrancar Flask para Render
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
    
