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

app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot y Servidor Activos 🚀", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"Iniciando servidor web Flask en el puerto {port}...")
    app.run(host="0.0.0.0", port=port, use_reloader=False)

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

def procesar_con_ia(contenido, es_audio=False) -> str:
    try:
        system_prompt = (
            "Eres un secretario personal de IA avanzado y multiagente. "
            "Responde de forma muy clara, concisa, directa y útil en español. "
            "Tus respuestas serán convertidas a audio, así que evita usar caracteres especiales, listas complejas o emojis excesivos."
        )
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[types.Tool(google_search=types.GoogleSearch())]
        )
        
        if es_audio:
            # Subir nota de voz especificando mime_type para evitar rechazo de la API
            audio_file = client.files.upload(
                file=contenido,
                config=types.UploadFileConfig(mime_type='audio/ogg')
            )
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[audio_file, "Escucha este mensaje de voz del usuario y responde a su solicitud de forma directa."],
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
        logger.error(f"Error con Gemini API: {e}")
        return "Disculpa, tuve un pequeño problema al procesar la solicitud."

# Función auxiliar para convertir cualquier texto de respuesta en una NOTA DE VOZ de Telegram
async def responder_con_voz(update: Update, texto_respuesta: str):
    await update.message.chat.send_action("record_voice")
    tmp_out_path = None
    try:
        tts = gTTS(text=texto_respuesta, lang='es')
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_out:
            tmp_out_path = tmp_out.name
            tts.save(tmp_out_path)
            
        with open(tmp_out_path, 'rb') as audio_response:
            await update.message.reply_voice(voice=audio_response)
    except Exception as e:
        logger.error(f"Error generando audio gTTS: {e}")
        # Si falla el audio por algún motivo, envía el texto como respaldo
        await update.message.reply_text(texto_respuesta)
    finally:
        if tmp_out_path and os.path.exists(tmp_out_path):
            os.remove(tmp_out_path)

# Manejador si le escribes TEXTO -> Responde con NOTA DE VOZ
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    if not user_text:
        return
    logger.info(f"Texto recibido: {user_text}")
    
    respuesta_texto = procesar_con_ia(user_text, es_audio=False)
    await responder_con_voz(update, respuesta_texto)

# Manejador si le envías NOTA DE VOZ -> Responde con NOTA DE VOZ
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Nota de voz recibida")
    await update.message.chat.send_action("typing")
    
    voice = update.message.voice
    voice_file = await context.bot.get_file(voice.file_id)
    
    tmp_in_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp_in:
            tmp_in_path = tmp_in.name
            await voice_file.download_to_drive(tmp_in_path)
            
        respuesta_texto = procesar_con_ia(tmp_in_path, es_audio=True)
        await responder_con_voz(update, respuesta_texto)
    finally:
        if tmp_in_path and os.path.exists(tmp_in_path):
            os.remove(tmp_in_path)

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
                
