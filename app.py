import os
import threading
import logging
import tempfile
import sqlite3
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CallbackQueryHandler, CommandHandler, filters
from google import genai
from google.genai import types
from google.genai.errors import APIError
from gtts import gTTS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- BASE DE DATOS Y MEMORIA PERSISTENTE (SQLite) ---
DB_NAME = "vishnu_memory.db"

def init_db():
    """Crea la tabla de base de datos si no existe."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            user_id INTEGER PRIMARY KEY,
            nombre TEXT,
            modo TEXT DEFAULT 'voice',
            notas TEXT DEFAULT ''
        )
    ''')
    conn.commit()
    conn.close()

def obtener_preferencias(user_id, nombre=""):
    """Obtiene el modo y las notas guardadas del usuario."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT modo, notas FROM usuarios WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    
    if row:
        conn.close()
        return {"modo": row[0], "notas": row[1]}
    else:
        cursor.execute('INSERT INTO usuarios (user_id, nombre, modo, notas) VALUES (?, ?, ?, ?)',
                       (user_id, nombre, 'voice', ''))
        conn.commit()
        conn.close()
        return {"modo": "voice", "notas": ""}

def actualizar_modo_usuario(user_id, nuevo_modo):
    """Actualiza la preferencia de respuesta (voz o texto)."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE usuarios SET modo = ? WHERE user_id = ?', (nuevo_modo, user_id))
    conn.commit()
    conn.close()

def agregar_nota_memoria(user_id, nueva_nota):
    """Guarda un dato clave sobre las preferencias del usuario."""
    prefs = obtener_preferencias(user_id)
    notas_actuales = prefs["notas"]
    notas_actualizadas = f"{notas_actuales} | {nueva_nota}".strip(" |")
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE usuarios SET notas = ? WHERE user_id = ?', (notas_actualizadas, user_id))
    conn.commit()
    conn.close()


# --- SERVIDOR WEB FLASK ---
@app.route('/')
def health_check():
    html_content = """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Vishnú - Servidor Cósmico</title>
        <style>
            body {
                background-color: #030712;
                color: #f3f4f6;
                font-family: 'Courier New', Courier, monospace;
                text-align: center;
                padding-top: 50px;
                margin: 0;
            }
            .container {
                max-width: 600px;
                margin: 0 auto;
                padding: 20px;
            }
            h1 {
                color: #06b6d4;
                font-size: 26px;
                text-shadow: 0 0 10px rgba(6, 182, 212, 0.5);
                margin-bottom: 5px;
            }
            p {
                color: #9ca3af;
                font-size: 14px;
                letter-spacing: 1px;
            }
            .tech-frame {
                margin-top: 30px;
                padding: 12px;
                background: linear-gradient(135deg, rgba(6, 182, 212, 0.1), rgba(147, 51, 234, 0.1));
                border: 1px solid rgba(6, 182, 212, 0.3);
                border-radius: 20px;
                box-shadow: 0 0 30px rgba(6, 182, 212, 0.2);
                display: inline-block;
            }
            img {
                max-width: 100%;
                width: 300px;
                height: auto;
                border-radius: 12px;
                display: block;
            }
            .status-badge {
                margin-top: 20px;
                display: inline-block;
                padding: 6px 14px;
                background: rgba(16, 185, 129, 0.15);
                border: 1px solid #10b981;
                color: #34d399;
                border-radius: 20px;
                font-size: 12px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>SYS_VISHNU // ONLINE</h1>
            <p>Núcleo de procesamiento divino y multiverso activo</p>
            
            <div class="tech-frame">
                <img src="https://i.postimg.cc/DwJ4vNFB/vishnu-cosmico.gif" alt="Vishnú Cósmico-Tecnológico">
            </div>
            
            <div>
                <span class="status-badge">● CONEXIÓN NEURONAL ESTABLE</span>
            </div>
        </div>
    </body>
    </html>
    """
    return html_content, 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"Iniciando servidor web Flask en el puerto {port}...")
    app.run(host="0.0.0.0", port=port, use_reloader=False)


# --- IA GEMINI Y MANEJO DE CHAT ---
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

user_chats = {}

def obtener_o_crear_chat(user_id, nombre_usuario=""):
    if user_id not in user_chats:
        prefs = obtener_preferencias(user_id, nombre_usuario)
        notas_memoria = prefs["notas"]
        
        system_prompt = (
            "Eres Vishnú, una entidad divina y digital que actúa como secretario personal de IA avanzado y multiagente. "
            "El universo de este chat existe en tus pensamientos y sueño cósmico, y asistes al usuario con sabiduría, "
            "claridad y precisión absoluta en español.\n\n"
            f"MEMORIA DE PREFERENCIAS DEL USUARIO: {notas_memoria if notas_memoria else 'Aún no hay preferencias registradas.'}"
        )
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[types.Tool(google_search=types.GoogleSearch())]
        )
        user_chats[user_id] = client.chats.create(model='gemini-2.5-flash', config=config)
    return user_chats[user_id]

def procesar_con_ia(user_id, contenido, tipo="texto", nombre_usuario="") -> str:
    try:
        chat = obtener_o_crear_chat(user_id, nombre_usuario)
        
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
            prompt_text = caption if caption else "Analiza este documento y responde a lo que se solicita en él."
            response = chat.send_message([doc_file_ref, prompt_text])
        elif tipo == "video":
            vid_file, caption = contenido
            vid_file_ref = client.files.upload(file=vid_file)
            prompt_text = caption if caption else "Analiza este video y responde o describe lo que ocurre en él."
            response = chat.send_message([vid_file_ref, prompt_text])
        else:
            response = chat.send_message(contenido)
            
        return response.text
    except APIError as e:
        if e.code == 429:
            logger.error("Se ha alcanzado el límite de cuota de la API de Gemini.")
            return "⚠️ Se ha agotado temporalmente la cuota gratuita de peticiones de la API de Gemini. Por favor, intenta más tarde."
        logger.error(f"Error con Gemini API: {e}")
        return "Disculpa, tuve un pequeño problema al procesar la solicitud."
    except Exception as e:
        logger.error(f"Error inesperado: {e}")
        return "Disculpa, ocurrió un error inesperado al procesar tu solicitud."

async def responder_con_voz_o_texto(update: Update, texto_respuesta: str):
    user_id = update.effective_user.id
    prefs = obtener_preferencias(user_id)
    modo = prefs["modo"]

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


# --- MANEJADORES DE COMANDOS ---
async def modo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("🎤 Responder con Voz", callback_data="mode_voice"),
            InlineKeyboardButton("✍️ Responder con Texto", callback_data="mode_text"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("¿Cómo prefieres que te responda a partir de ahora?", reply_markup=reply_markup)

async def oraculo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    nombre = update.effective_user.first_name
    logger.info(f"Comando /oraculo ejecutado por {user_id}")
    await update.message.chat.send_action("typing")
    
    prompt_oraculo = (
        "Revela un consejo cósmico, filosófico y motivacional en 2 o 3 oraciones "
        "manteniendo tu personalidad divina como Vishnú. Sé misterioso pero inspirador."
    )
    
    respuesta_oraculo = procesar_con_ia(user_id, prompt_oraculo, tipo="texto", nombre_usuario=nombre)
    await responder_con_voz_o_texto(update, respuesta_oraculo)

async def estado_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    logger.info(f"Comando /estado ejecutado por {user_id}")
    
    mensaje_estado = (
        "🟢 *SYS_VISHNU // REPORTE DE SISTEMA*\n\n"
        "• *Servidor Web:* Activo en Render\n"
        "• *Conexión Neuronal:* Estable\n"
        "• *Base de Datos (SQLite):* Memoria Persistente Activa\n"
        "• *Monitoreo UptimeRobot:* En línea (Cada 5 min)"
    )
    await update.message.reply_text(mensaje_estado, parse_mode="Markdown")

async def recordar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    dato = " ".join(context.args)
    
    if not dato:
        await update.message.reply_text("🧠 Uso: `/recordar <dato a guardar>`\nEjemplo: `/recordar Me gusta el café sin azúcar`", parse_mode="Markdown")
        return
        
    agregar_nota_memoria(user_id, dato)
    
    # Reiniciar chat en RAM para actualizar prompt del sistema
    if user_id in user_chats:
        del user_chats[user_id]
        
    await update.message.reply_text(f"👁️ **Memoria Divina Actualizada:** He grabado en mi base de datos que: *'{dato}'*.", parse_mode="Markdown")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if query.data == "mode_voice":
        actualizar_modo_usuario(user_id, "voice")
        await query.edit_message_text("✅ ¡Listo! Preferencia guardada: Ahora te responderé con **Notas de Voz**.")
    elif query.data == "mode_text":
        actualizar_modo_usuario(user_id, "text")
        await query.edit_message_text("✅ ¡Listo! Preferencia guardada: Ahora te responderé con **Texto**.")


# --- MANEJADORES DE MENSAJES MULTIMEDIA ---
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    if not user_text:
        return
    user_id = update.effective_user.id
    nombre = update.effective_user.first_name
    logger.info(f"Texto recibido de {user_id}: {user_text}")
    await update.message.chat.send_action("typing")
    
    respuesta_texto = procesar_con_ia(user_id, user_text, tipo="texto", nombre_usuario=nombre)
    await responder_con_voz_o_texto(update, respuesta_texto)

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    nombre = update.effective_user.first_name
    logger.info(f"Nota de voz recibida de {user_id}")
    await update.message.chat.send_action("typing")
    
    voice = update.message.voice
    voice_file = await context.bot.get_file(voice.file_id)
    
    tmp_in_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp_in:
            tmp_in_path = tmp_in.name
            await voice_file.download_to_drive(tmp_in_path)
            
        respuesta_texto = procesar_con_ia(user_id, tmp_in_path, tipo="audio", nombre_usuario=nombre)
        await responder_con_voz_o_texto(update, respuesta_texto)
    finally:
        if tmp_in_path and os.path.exists(tmp_in_path):
            os.remove(tmp_in_path)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    nombre = update.effective_user.first_name
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
            
        respuesta_texto = procesar_con_ia(user_id, (tmp_img_path, caption), tipo="imagen", nombre_usuario=nombre)
        await responder_con_voz_o_texto(update, respuesta_texto)
    finally:
        if tmp_img_path and os.path.exists(tmp_img_path):
            os.remove(tmp_img_path)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    nombre = update.effective_user.first_name
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
            
        respuesta_texto = procesar_con_ia(user_id, (tmp_doc_path, caption), tipo="documento", nombre_usuario=nombre)
        await responder_con_voz_o_texto(update, respuesta_texto)
    finally:
        if tmp_doc_path and os.path.exists(tmp_doc_path):
            os.remove(tmp_doc_path)

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    nombre = update.effective_user.first_name
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
            
        respuesta_texto = procesar_con_ia(user_id, (tmp_vid_path, caption), tipo="video", nombre_usuario=nombre)
        await responder_con_voz_o_texto(update, respuesta_texto)
    finally:
        if tmp_vid_path and os.path.exists(tmp_vid_path):
            os.remove(tmp_vid_path)


# --- CONFIGURACIÓN DEL MENÚ Y ARRANQUE ---
async def post_init(app):
    comandos = [
        BotCommand("modo", "Cambiar respuesta entre Voz o Texto"),
        BotCommand("oraculo", "Recibir un consejo cósmico de Vishnú"),
        BotCommand("recordar", "Guardar un dato en la memoria persistente"),
        BotCommand("estado", "Verificar el estado del servidor"),
    ]
    await app.bot.set_my_commands(comandos)

def main():
    init_db()  # Inicializar Base de Datos SQLite
    
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        logger.error("No se encontró TELEGRAM_TOKEN en las variables de entorno.")
        return
    
    application = ApplicationBuilder().token(token).post_init(post_init).build()
    
    # Comandos
    application.add_handler(CommandHandler("modo", modo_command))
    application.add_handler(CommandHandler("oraculo", oraculo_command))
    application.add_handler(CommandHandler("estado", estado_command))
    application.add_handler(CommandHandler("recordar", recordar_command))
    
    # Callbacks y Mensajes
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
