import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from google import genai
from google.genai import types

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

def main():
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        logger.error("No se encontró TELEGRAM_TOKEN en las variables de entorno.")
        return
    
    application = ApplicationBuilder().token(token).build()
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    logger.info("Iniciando bot de Telegram en el hilo principal...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
    
