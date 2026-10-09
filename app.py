import os
import threading
import logging
import tempfile
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from google import genai
from google.genai import types

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Servidor Flask en segundo plano solo para mantener activo el puerto de Render
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot y Servidor Activos 🚀", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"Iniciando servidor web Flask en el puerto {port}...")
    app.run(host="0.0.0.0", port=port, use_reloader=False)

# Cliente de IA con Gemini
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

def procesar_con_ia(contenido, es_audio=False) -> str:
    try:
        system_prompt = (
            "Eres un secretario personal de IA avanzado y multiagente. "
            "Responde de forma clara, directa y útil en español."
        )
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[types.Tool(google_search=types.GoogleSearch())]
        )
        
        if es_audio:
            # Subir archivo de audio a la API de Gemini
            audio_file = client.files.upload(file=contenido)
            response = client.models.generate_content(
                model='gemini-3.8-flash',
                contents=[audio_file, "Escucha este mensaje de voz y responde a lo que solicita el usuario."],
                config=config
            )
        else:
            response = client.models.generate_content(
                model='gemini-3.8-flash',
                contents=contenido,
                config=config
            )
            
        return response.text
    except Exception as e:
        logger.error(f"Error con la IA: {e}")
        return "Disculpa, tuve un fallo técnico consultando a la IA. Inténtalo de nuevo."

# Manejador de texto
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    if not user_text:
        return
    logger.info(f"Texto recibido: {user_text}")
    await update.message.chat.send_action("typing")
    respuesta = procesar_con_ia(user_text, es_audio=False)
    await update.message.reply_text(respuesta)

# Manejador de notas de voz
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Nota de voz recibida")
    await update.message.chat.send_action("typing")
    
    voice = update.message.voice
    voice_file = await context.bot.get_file(voice.file_id)
    
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp_file:
        tmp_path = tmp_file.name
        await voice_file.download_to_drive(tmp_path)
    
    try:
        respuesta = procesar_con_ia(tmp_path, es_audio=True)
        await update.message.reply_text(respuesta)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

def main():
    # Iniciar Flask en hilo secundario
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # Ejecutar Telegram en hilo principal
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        logger.error("No se encontró TELEGRAM_TOKEN en las variables de entorno.")
        return
    
    application = ApplicationBuilder().token(token).build()
    
    # Escuchar texto y notas de voz
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    
    logger.info("Iniciando bot de Telegram en el hilo principal...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
    
