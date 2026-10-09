import os
import threading
import logging
import tempfile
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from google import genai
from google.genai import types
from gtts import gTTS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Servidor Flask obligatorio para mantener el puerto de Render en verde
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot y Servidor Activos 🚀", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"Iniciando servidor web Flask en el puerto {port}...")
    app.run(host="0.0.0.0", port=port, use_reloader=False)

# Cliente de IA
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

def procesar_con_ia(contenido, es_audio=False) -> str:
    try:
        system_prompt = (
            "Eres un secretario personal de IA avanzado y multiagente. "
            "Responde de forma clara, directa, concisa y útil en español."
        )
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[types.Tool(google_search=types.GoogleSearch())]
        )
        
        if es_audio:
            logger.info("Subiendo archivo de audio a Gemini API...")
            # Especificar el mime_type para asegurar que Gemini entienda la nota de voz de Telegram (.ogg)
            audio_file = client.files.upload(
                file=contenido,
                config=types.UploadFileConfig(mime_type='audio/ogg')
            )
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[audio_file, "Escucha este mensaje de voz atentamente y responde a la petición del usuario de forma útil."],
                config=config
            )
        else:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=contenido,
                config=config
            )
            
        return response.text
    except Exception as e:
        logger.error(f"Error detallado en procesar_con_ia: {e}")
        raise e

# Manejador de texto (Responde con texto)
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    if not user_text:
        return
    logger.info(f"Texto recibido: {user_text}")
    await update.message.chat.send_action("typing")
    try:
        respuesta = procesar_con_ia(user_text, es_audio=False)
        await update.message.reply_text(respuesta)
    except Exception as e:
        await update.message.reply_text("Disculpa, tuve un fallo técnico procesando tu mensaje.")

# Manejador de notas de voz (Responde con NOTA DE VOZ)
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Nota de voz recibida")
    await update.message.chat.send_action("record_voice")
    
    voice = update.message.voice
    voice_file = await context.bot.get_file(voice.file_id)
    
    tmp_in_path = None
    tmp_out_path = None
    
    try:
        # 1. Guardar voz entrante
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp_in:
            tmp_in_path = tmp_in.name
            await voice_file.download_to_drive(tmp_in_path)
            
        # 2. Procesar con Gemini
        respuesta_texto = procesar_con_ia(tmp_in_path, es_audio=True)
        if not respuesta_texto:
            respuesta_texto = "No logré entender el audio con claridad. ¿Podrías repetirlo?"

        # 3. Convertir la respuesta de texto a audio con gTTS
        tts = gTTS(text=respuesta_texto, lang='es')
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_out:
            tmp_out_path = tmp_out.name
            tts.save(tmp_out_path)
            
        # 4. Enviar nota de voz a Telegram
        with open(tmp_out_path, 'rb') as audio_response:
            await update.message.reply_voice(voice=audio_response)
            
    except Exception as e:
        logger.error(f"Error procesando la nota de voz: {e}")
        await update.message.reply_text("Tuve un fallo técnico procesando la nota de voz. Inténtalo de nuevo.")
    finally:
        # Limpieza de archivos temporales
        if tmp_in_path and os.path.exists(tmp_in_path):
            os.remove(tmp_in_path)
        if tmp_out_path and os.path.exists(tmp_out_path):
            os.remove(tmp_out_path)

def main():
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        logger.error("No se encontró TELEGRAM_TOKEN en las variables de entorno.")
        return
    
    application = ApplicationBuilder().token(token).build()
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    
    logger.info("Iniciando bot de Telegram en el hilo principal...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
