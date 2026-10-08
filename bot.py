import os
import logging
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from google import genai
from google.genai import types

logging.basicConfig(level=logging.INFO)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY)

# ==========================================
# 1. DEFINICIÓN DE HABILIDADES (HERRAMIENTAS)
# ==========================================

def obtener_fecha_y_hora() -> str:
    """Devuelve la fecha y hora actual exacta."""
    ahora = datetime.now()
    return ahora.strftime("Hoy es %A, %d de %B de %Y y son las %H:%M horas.")

def guardar_recordatorio(tarea: str, hora: str) -> str:
    """Guarda una nota o recordatorio expresado por el usuario."""
    # Aquí podrías guardar los datos en una base de datos o archivo
    return f"Recordatorio registrado con éxito: '{tarea}' para las {hora}."

# Lista de funciones disponibles para el agente
mis_herramientas = [obtener_fecha_y_hora, guardar_recordatorio]

# ==========================================
# 2. LÓGICA DEL BOT
# ==========================================

async def responder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
        
    texto_usuario = update.message.text
    
    try:
        # Petición a Gemini enviándole las herramientas en la configuración
        response = client.models.generate_content(
            model='gemini-3.8-flash',
            contents=texto_usuario,
            config=types.GenerateContentConfig(
                system_instruction=(
                    "Eres el secretario personal de tu usuario en Telegram. "
                    "Tienes acceso a herramientas para consultar la hora actual y guardar recordatorios. "
                    "Utiliza tus herramientas cuando sea necesario para dar respuestas precisas y amables."
                ),
                tools=mis_herramientas
            )
        )
        
        await update.message.reply_text(response.text)
        
    except Exception as e:
        logging.error(f"Error procesando mensaje: {e}")
        await update.message.reply_text("Disculpa, tuve un inconveniente al procesar tu solicitud.")

if __name__ == '__main__':
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, responder))
    print("Bot con habilidades activo en Render...")
    app.run_polling()
    
