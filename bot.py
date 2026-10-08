import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from google import genai
from google.genai import types
from gtts import gTTS

# Configurar logging detallado para monitoreo
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# Inicializar cliente de Gemini
client = genai.Client(api_key=GEMINI_API_KEY)

async def responder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
        
    texto_usuario = update.message.text
    chat_id = update.message.chat_id
    
    try:
        # Enviar indicador de que el bot está procesando (escribiendo/grabando audio)
        await context.bot.send_chat_action(chat_id=chat_id, action="upload_voice")

        # Configuración del agente
        configuracion = types.GenerateContentConfig(
            system_instruction=(
                "Eres el secretario y asistente personal de tu usuario en Telegram. "
                "Responde de manera breve, natural y amigable, ya que tus respuestas "
                "serán convertidas a notas de voz."
            ),
            tools=[types.Tool(google_search=types.GoogleSearch())]
        )

        response = client.models.generate_content(
            model='gemini-3.8-flash',
            contents=texto_usuario,
            config=configuracion
        )
        
        texto_respuesta = response.text
        
        # Generar archivo de voz único usando el ID del mensaje para evitar conflictos
        audio_path = f"voz_{update.message.message_id}.mp3"
        
        tts = gTTS(text=texto_respuesta, lang='es', slow=False)
        tts.save(audio_path)
        
        # Enviar la nota de voz
        with open(audio_path, 'rb') as audio_file:
            await update.message.reply_voice(voice=audio_file)
            
        # Limpieza segura del archivo temporal
        if os.path.exists(audio_path):
            os.remove(audio_path)
        
    except Exception as e:
        logging.error(f"Error procesando la solicitud: {e}")
        try:
            await update.message.reply_text("Disculpa, tuve un pequeño fallo técnico. Inténtalo de nuevo.")
        except:
            pass

if __name__ == '__main__':
    if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
        logging.error("Faltan las variables de entorno TELEGRAM_TOKEN o GEMINI_API_KEY.")
    else:
        app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, responder))
        
        logging.info("Secretario con notas de voz optimizadas iniciado correctamente...")
        # run_polling maneja reconexiones automáticas ante pequeños cortes de red
        app.run_polling(drop_pending_updates=True)
        
