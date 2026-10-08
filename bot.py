import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from google import genai
from google.genai import types
from gtts import gTTS

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
        # Configuración del agente con búsqueda web y personalidad
        configuracion = types.GenerateContentConfig(
            system_instruction=(
                "Eres el secretario y asistente personal de tu usuario en Telegram. "
                "Responde de manera concisa, natural y amigable, ya que tus respuestas "
                "serán convertidas a notas de voz para el usuario."
            ),
            tools=[types.Tool(google_search=types.GoogleSearch())]
        )

        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=texto_usuario,
            config=configuracion
        )
        
        texto_respuesta = response.text
        
        # 1. Convertir la respuesta de texto a voz (gTTS utiliza voz femenina en español)
        tts = gTTS(text=texto_respuesta, lang='es', slow=False)
        audio_path = "respuesta.mp3"
        tts.save(audio_path)
        
        # 2. Enviar el archivo de audio a Telegram
        with open(audio_path, 'rb') as audio_file:
            await update.message.reply_audio(
                audio=audio_file, 
                title="Nota de voz del secretario",
                performer="Asistente IA"
            )
            
        # 3. Eliminar el archivo temporal del servidor para ahorrar espacio
        if os.path.exists(audio_path):
            os.remove(audio_path)
        
    except Exception as e:
        logging.error(f"Error procesando voz o respuesta: {e}")
        await update.message.reply_text("Disculpa, tuve un inconveniente generando tu nota de voz.")

if __name__ == '__main__':
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, responder))
    print("Bot de voz activo en Render...")
    app.run_polling()
    
