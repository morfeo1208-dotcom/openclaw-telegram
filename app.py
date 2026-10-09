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
from fpdf import FPDF

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

# Diccionarios para almacenar el modo de respuesta y el historial de chat de cada usuario
user_modes = {}
user_chats = {}

def obtener_o_crear_chat(user_id):
    if user_id not in user_chats:
        system_prompt = (
            "Eres un secretario personal de IA avanzado y multiagente. "
            "Responde de forma muy clara, concisa, directa y útil en español. "
            "Si el usuario te pide traducir un documento, proporciona la traducción completa y limpia."
        )
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[types.Tool(google_search=types.GoogleSearch())]
        )
        # Creamos una sesión de chat persistente por usuario
        user_chats[user_id] = client.chats.create(model='gemini-2.5-flash', config=config)
    return user_chats[user_id]

def procesar_con_ia(user_id, contenido, tipo="texto") -> str:
    try:
        chat = obtener_o_crear_chat(user_id)
        
        if tipo == "audio":
            audio_file = client.files.upload(
                file=contenido,
                config=types.UploadFileConfig(mime_type='audio/ogg')
            )
            response = chat.send_message([audio_file, "Escucha este mensaje de voz del usuario y responde a su solicitud."])
        elif tipo == "imagen":
            img_file, caption = contenido
            image_file_ref = client.files.upload(file=img_file)
            prompt_text = caption if caption else "Analiza esta imagen y describe qué ves o responde a lo que se pide en ella."
            response = chat.send_message([image_file_ref, prompt_text])
        elif tipo == "documento":
            doc_file, caption = contenido
            doc_file_ref = client.files.upload(file=doc_file)
            prompt_text = caption if caption else "Traduce este documento al español de forma completa y profesional."
            response = chat.send_message([doc_file_ref, prompt_text])
        elif tipo == "video":
            vid_file, caption = contenido
            vid_file_ref = client.files.upload(file=vid_file)
            prompt_text = caption if caption else "Analiza este video y responde o describe lo que ocurre en él."
            response = chat.send_message([vid_file_ref, prompt_text])
        else:
            response = chat.send_message(contenido)
            
        return response.text
    except Exception as e:
        logger.error(f"Error con Gemini API: {e}")
        return "Disculpa, tuve un pequeño problema al procesar la solicitud."

def crear_pdf_desde_texto(texto: str, output_path: str):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=11)
    safe_text = texto.encode('latin-1', 'replace').decode('latin-1')
    pdf.multi_cell(0, 10, safe_text)
    pdf.output(output_path)

async def responder_con_voz_o_texto(update: Update, texto_respuesta: str, es_documento_salida: bool = False):
    user_id = update.effective_user.id
    modo = user_modes.get(user_id, "voice")
    
    if es_documento_salida:
        tmp_pdf_path = None
        try:
            await update.message.chat.send_action("upload_document")
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_pdf:
                tmp_pdf_path = tmp_pdf.name
            
            crear_pdf_desde_texto(texto_respuesta, tmp_pdf_path)
            
            with open(tmp_pdf_path, 'rb') as pdf_file:
                await update.message.reply_document(
                    document=pdf_file, 
                    filename="documento_traducido.pdf",
                    caption="📄 Aquí tienes tu documento traducido/procesado en PDF."
                )
                return
        except Exception as e:
            logger.error(f"Error generando PDF de salida: {e}")
        finally:
            if tmp_pdf_path and os.path.exists(tmp_pdf_path):
                os.remove(tmp_pdf_path)

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

async def modo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("🎤 Responder con Voz", callback_data="mode_voice"),
            InlineKeyboardButton("✍️ Responder con Texto", callback_data="mode_text"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("¿Cómo prefieres que te responda a partir de ahora?", reply_markup=reply_markup)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if query.data == "mode_voice":
        user_modes[user_id] = "voice"
        await query.edit_message_text("✅ ¡Listo! Ahora te responderé con **Notas de Voz** (excepto al traducir documentos, que te enviaré el PDF).")
    elif query.data == "mode_text":
        user_modes[user_id] = "text"
        await query.edit_message_text("✅ ¡Listo! Ahora te responderé con **Texto**.")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    if not user_text:
        return
    user_id = update.effective_user.id
    logger.info(f"Texto recibido de {user_id}: {user_text}")
    await update.message.chat.send_action("typing")
    
    respuesta_texto = procesar_con_ia(user_id, user_text, tipo="texto")
    await responder_con_voz_o_texto(update, respuesta_texto, es_documento_salida=False)

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    logger.info(f"Nota de voz recibida de {user_id}")
    await update.message.chat.send_action("typing")
    
    voice = update.message.voice
    voice_file = await context.bot.get_file(voice.file_id)
    
    tmp_in_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp_in:
            tmp_in_path = tmp_in.name
            await voice_file.download_to_drive(tmp_in_path)
            
        respuesta_texto = procesar_con_ia(user_id, tmp_in_path, tipo="audio")
        await responder_con_voz_o_texto(update, respuesta_texto, es_documento_salida=False)
    finally:
        if tmp_in_path and os.path.exists(tmp_in_path):
            os.remove(tmp_in_path)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    logger.info(f"Imagen recibida de {user_id}")
    await update.message.chat.send_action("typing")
    
    photo = update.message.photo[-1]
    photo_file = await context.bot.get_file(photo.file_id)
    caption = update.message.caption or ""
    
    tmp_img_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp_img:
            tmp_img_path = tmp_img.name
            await photo_file.download_to_drive(tmp_img_path)
            
        respuesta_texto = procesar_con_ia(user_id, (tmp_img_path, caption), tipo="imagen")
        await responder_con_voz_o_texto(update, respuesta_texto, es_documento_salida=False)
    finally:
        if tmp_img_path and os.path.exists(tmp_img_path):
            os.remove(tmp_img_path)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    logger.info(f"Documento recibido de {user_id}")
    await update.message.chat.send_action("typing")
    
    doc = update.message.document
    doc_file = await context.bot.get_file(doc.file_id)
    caption = update.message.caption or ""
    file_extension = os.path.splitext(doc.file_name)[1] if doc.file_name else ".pdf"
    
    tmp_doc_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=file_extension, delete=False) as tmp_doc:
            tmp_doc_path = tmp_doc.name
            await doc_file.download_to_drive(tmp_doc_path)
            
        respuesta_texto = procesar_con_ia(user_id, (tmp_doc_path, caption), tipo="documento")
        await responder_con_voz_o_texto(update, respuesta_texto, es_documento_salida=True)
    finally:
        if tmp_doc_path and os.path.exists(tmp_doc_path):
            os.remove(tmp_doc_path)

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    logger.info(f"Video recibido de {user_id}")
    await update.message.chat.send_action("typing")
    
    video = update.message.video
    video_file = await context.bot.get_file(video.file_id)
    caption = update.message.caption or ""
    
    tmp_vid_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_vid:
            tmp_vid_path = tmp_vid.name
            await video_file.download_to_drive(tmp_vid_path)
            
        respuesta_texto = procesar_con_ia(user_id, (tmp_vid_path, caption), tipo="video")
        await responder_con_voz_o_texto(update, respuesta_texto, es_documento_salida=False)
    finally:
        if tmp_vid_path and os.path.exists(tmp_vid_path):
            os.remove(tmp_vid_path)

def main():
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        logger.error("No se encontró TELEGRAM_TOKEN en las variables de entorno.")
        return
    
    application = ApplicationBuilder().token(token).build()
    
    application.add_handler(CommandHandler("modo", modo_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.VIDEO, handle_video))
    
    logger.info("Iniciando bot de Telegram en el hilo principal...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
            
