import os
import threading
import logging
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from google import genai
from google.genai import types

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Servidor Flask obligatorio para satisfacer el puerto web gratuito de Render
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Secretario IA & Bot de Telegram Activos 🚀", 200

# Inicializar cliente de Gemini
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

def procesar_con_ia(texto: str) -> str:
    try:
        system_prompt = (
            "Eres un secretario personal de IA avanzado y multiagente. "
            "Responde de forma clara, directa y útil en español."
        )
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[types.Tool(google_search=types.GoogleSearch())]
        )
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=texto,
            config=config
        )
        return response.text
    except Exception as e:
        logger.error(f"Error con la IA: {e}")
        return "Disculpa, tuve un pequeño fallo técnico consultando a la IA. Inténtalo de nuevo."

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    if not user_text:
        return
    
    logger.info(f"Mensaje recibido: {user_text}")
    await update.message.chat.send_action("typing")
    
    respuesta = procesar_con_ia(user_text)
    await update.message.reply_text(respuesta)

def run_telegram_bot():
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        logger.error("No se encontró TELEGRAM_TOKEN en las variables de entorno.")
        return
    
    application = ApplicationBuilder().token(token).build()
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    logger.info("Iniciando bucle de Telegram...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    # Ejecutar el bot de Telegram en segundo plano
    t = threading.Thread(target=run_telegram_bot, daemon=True)
    t.start()
    
    # Render asigna dinámicamente un puerto a través de la variable PORT
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"Iniciando servidor web Flask en el puerto {port}...")
    app.run(host="0.0.0.0", port=port)
