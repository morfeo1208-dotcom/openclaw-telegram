import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from google import genai
from google.genai import types

logging.basicConfig(level=logging.INFO)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# Inicializar cliente de Gemini
client = genai.Client(api_key=GEMINI_API_KEY)

async def responder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
        
    texto_usuario = update.message.text
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=texto_usuario,
            config=types.GenerateContentConfig(
                system_instruction=(
                    "Eres el secretario y asistente personal de tu usuario en Telegram. "
                    "Responde de forma natural, amigable, concisa y eficiente. "
                    "Nunca respondas como un bot corporativo ni digas 'Estimado usuario'. "
                    "Habla en primera persona como un verdadero secretario atento y servicial."
                )
            )
        )
        await update.message.reply_text(response.text)
    except Exception as e:
        logging.error(f"Error generando respuesta: {e}")
        await update.message.reply_text("Disculpa, tuve un inconveniente momentáneo al procesar tu mensaje.")

if __name__ == '__main__':
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, responder))
    print("Bot activo en Render...")
    app.run_polling()
        
