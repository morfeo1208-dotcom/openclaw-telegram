import os
import threading
import logging
import tempfile
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CallbackQueryHandler, CommandHandler, filters
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

# Diccionario para guardar la preferencia de cada usuario ('voice' o 'text')
user_modes = {}

def procesar_con_ia(contenido, es_audio=False) -> str:
    try:
        system_prompt = (
            "Eres un secretario personal de IA avanzado y multiagente. "
            "Responde de forma muy clara, concisa, directa y útil en español."
        )
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[types.Tool(google_search=types.GoogleSearch())]
        )
        
        if es_audio:
            audio_file = client.files.upload(
                file=contenido,
                config=types.UploadFileConfig(mime_type='audio/ogg')
            )
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[audio_file, "Escucha este mensaje de voz del usuario y responde a su solicitud."],
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

# Comando para abrir el selector de modo
async def modo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("🎤 Responder con Voz", callback_data="mode_voice"),
            InlineKeyboardButton("✍️ Responder con Texto", callback_data="mode_text"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("¿Cómo prefieres que te responda a partir de ahora?", reply_markup=reply_markup)

# Manejar los clics de los botones
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if query.data == "mode_voice":
        user_modes[user_id] = "voice"
        await query.edit_message_text("✅ ¡Listo! Ahora te responderé con **Notas de Voz**.")
    elif query.data == "mode_text":
        user_modes[user_id] = "text"
        await query.edit_message_text("✅ ¡Listo! Ahora te responderé con **Texto**.")

# Función inteligente para enviar la respuesta según el modo elegido por el usuario
async def enviar_respuesta(update: Update, texto_respuesta: str):
    user_id = update.effective_user.id
    modo = user_modes.get(user_id, "voice")  # Por defecto responde con voz si no ha elegido
    
    if modo == "text":
        await update.message.reply_text(texto_respuesta)
    else:
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
            await update.message.reply_text(texto_respuesta)
        finally:
            if tmp_out_path and os.path.exists(tmp_out_path):
                os.remove(tmp_out_path)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    if not user_text:
        return
    logger.info(f"Texto recibido: {user_text}")
    await update.message.chat.send_action("typing")
    
    respuesta_texto = procesar_con_ia(user_text, es_audio=False)
    await enviar_respuesta(update, respuesta_texto)

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
        await enviar_respuesta(update, respuesta_texto)
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
    
    # Comandos y Botones
    application.add_handler(CommandHandler("modo", modo_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Mensajes
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    
    logger.info("Iniciando bot de Telegram en el hilo principal...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
        
