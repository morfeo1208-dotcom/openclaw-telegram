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

# --- BASE DE DATOS Y GESTIÓN DE MÚLTIPLES CHATS (SQLite) ---
DB_NAME = "vishnu_memory.db"

def init_db():
    """Crea las tablas de base de datos para usuarios y múltiples chats."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            user_id INTEGER PRIMARY KEY,
            nombre TEXT,
            modo TEXT DEFAULT 'voice',
            notas TEXT DEFAULT '',
            chat_activo_id INTEGER
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chats (
            chat_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            titulo TEXT
        )
    ''')
    conn.commit()
    conn.close()

def obtener_preferencias(user_id, nombre=""):
    """Obtiene el modo, notas y chat activo del usuario."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT modo, notas, chat_activo_id FROM usuarios WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    
    if row:
        modo, notas, chat_activo_id = row
        # Si no tiene un chat activo asignado, le creamos uno por defecto
        if not chat_activo_id:
            cursor.execute('SELECT chat_id FROM chats WHERE user_id = ? ORDER BY chat_id ASC LIMIT 1', (user_id,))
            chat_row = cursor.fetchone()
            if chat_row:
                chat_activo_id = chat_row[0]
            else:
                cursor.execute('INSERT INTO chats (user_id, titulo) VALUES (?, ?)', (user_id, "Chat Principal"))
                chat_activo_id = cursor.lastrowid
            cursor.execute('UPDATE usuarios SET chat_activo_id = ? WHERE user_id = ?', (chat_activo_id, user_id))
            conn.commit()
        conn.close()
        return {"modo": modo, "notas": notas, "chat_activo_id": chat_activo_id}
    else:
        # Registrar usuario nuevo y crear su primer chat
        cursor.execute('INSERT INTO chats (user_id, titulo) VALUES (?, ?)', (user_id, "Chat Principal"))
        chat_id = cursor.lastrowid
        cursor.execute('INSERT INTO usuarios (user_id, nombre, modo, notas, chat_activo_id) VALUES (?, ?, ?, ?, ?)',
                       (user_id, nombre, 'voice', '', chat_id))
        conn.commit()
        conn.close()
        return {"modo": "voice", "notas": "", "chat_activo_id": chat_id}

def actualizar_modo_usuario(user_id, nuevo_modo):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE usuarios SET modo = ? WHERE user_id = ?', (nuevo_modo, user_id))
    conn.commit()
    conn.close()

def agregar_nota_memoria(user_id, nueva_nota):
    prefs = obtener_preferencias(user_id)
    notas_actuales = prefs["notas"]
    notas_actualizadas = f"{notas_actuales} | {nueva_nota}".strip(" |")
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE usuarios SET notas = ? WHERE user_id = ?', (notas_actualizadas, user_id))
    conn.commit()
    conn.close()

def crear_nuevo_chat(user_id, titulo="Chat Cósmico"):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO chats (user_id, titulo) VALUES (?, ?)', (user_id, titulo))
    nuevo_chat_id = cursor.lastrowid
    cursor.execute('UPDATE usuarios SET chat_activo_id = ? WHERE user_id = ?', (nuevo_chat_id, user_id))
    conn.commit()
    conn.close()
    return nuevo_chat_id

def obtener_chats_usuario(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT chat_id, titulo FROM chats WHERE user_id = ?', (user_id,))
    chats = cursor.fetchall()
    conn.close()
    return chats

def cambiar_chat_activo(user_id, chat_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT chat_id FROM chats WHERE chat_id = ? AND user_id = ?', (chat_id, user_id))
    if cursor.fetchone():
        cursor.execute('UPDATE usuarios SET chat_activo_id = ? WHERE user_id = ?', (chat_id, user_id))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False

def borrar_chat(user_id, chat_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM chats WHERE chat_id = ? AND user_id = ?', (chat_id, user_id))
    # Si borra el chat activo, reasignamos otro si existe
    cursor.execute('SELECT chat_activo_id FROM usuarios WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    if row and row[0] == chat_id:
        cursor.execute('SELECT chat_id FROM chats WHERE user_id = ? ORDER BY chat_id ASC LIMIT 1', (user_id,))
        next_chat = cursor.fetchone()
        nuevo_activo = next_chat[0] if next_chat else None
        cursor.execute('UPDATE usuarios SET chat_activo_id = ? WHERE user_id = ?', (nuevo_activo, user_id))
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


# --- IA GEMINI Y MANEJO DE CHATS MULTIPLES ---
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# Diccionario en RAM con clave (user_id, chat_id)
user_chats_cache = {}

def obtener_o_crear_chat(user_id, nombre_usuario=""):
    prefs = obtener_preferencias(user_id, nombre_usuario)
    chat_activo_id = prefs["chat_activo_id"]
    
    cache_key = (user_id, chat_activo_id)
    if cache_key not in user_chats_cache:
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
        user_chats_cache[cache_key] = client.chats.create(model='gemini-2.5-flash', config=config)
        
    return user_chats_cache[cache_key]

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
    await update.message.chat.send_action("typing")
    
    prompt_oraculo = (
        "Revela un consejo cósmico, filosófico y motivacional en 2 o 3 oraciones "
        "manteniendo tu personalidad divina como Vishnú. Sé misterioso pero inspirador."
    )
    respuesta = procesar_con_ia(user_id, prompt_oraculo, tipo="texto", nombre_usuario=nombre)
    await responder_con_voz_o_texto(update, respuesta)

async def estado_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    prefs = obtener_preferencias(user_id)
    mensaje_estado = (
        "🟢 *SYS_VISHNU // REPORTE DE SISTEMA*\n\n"
        "• *Servidor Web:* Activo en Render\n"
        "• *Conexión Neuronal:* Estable\n"
        f"• *Chat Activo ID:* `{prefs['chat_activo_id']}`\n"
        "• *Base de Datos:* SQLite Activa"
    )
    await update.message.reply_text(mensaje_estado, parse_mode="Markdown")

async def recordar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    dato = " ".join(context.args)
    if not dato:
        await update.message.reply_text("🧠 Uso: `/recordar <dato a guardar>`", parse_mode="Markdown")
        return
    agregar_nota_memoria(user_id, dato)
    user_chats_cache.clear()  # Limpiar caché para recargar notas en todos los chats
    await update.message.reply_text(f"👁️ **Memoria Divina Actualizada:** *'{dato}'*.", parse_mode="Markdown")

async def traductor_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    nombre = update.effective_user.first_name
    args = context.args
    if not args:
        await update.message.reply_text("🌐 Uso: `/traductor <idioma> <texto>`\nEjemplo: `/traductor en Hola mundo`", parse_mode="Markdown")
        return
    idioma = args[0].lower()
    if len(idioma) <= 3:
        texto = " ".join(args[1:])
        destino = idioma
    else:
        texto = " ".join(args)
        destino = "es"
    if not texto:
        await update.message.reply_text("⚠️ Escribe el texto a traducir.")
        return
    await update.message.chat.send_action("typing")
    prompt = f"Traduce de forma natural al idioma '{destino}':\n\n{texto}"
    respuesta = procesar_con_ia(user_id, prompt, tipo="texto", nombre_usuario=nombre)
    await responder_con_voz_o_texto(update, respuesta)

# Comandos de Gestión de Múltiples Chats
async def chats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    prefs = obtener_preferencias(user_id)
    chats = obtener_chats_usuario(user_id)
    
    texto = "📂 **TUS HILOS DE CHAT:**\n\n"
    for cid, titulo in chats:
        activo = " 🟢 *(Activo)*" if cid == prefs["chat_activo_id"] else ""
        texto += f"• **ID {cid}:** {titulo}{activo}\n"
        
    texto += "\n*Comandos útiles:*\n• `/nuevo <nombre>` (Crear chat)\n• `/cambiar <id>` (Cambiar chat)\n• `/borrar <id>` (Eliminar chat)"
    await update.message.reply_text(texto, parse_mode="Markdown")

async def nuevo_chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    titulo = " ".join(context.args) if context.args else "Nuevo Ciclo"
    chat_id = crear_nuevo_chat(user_id, titulo)
    await update.message.reply_text(f"✨ **Chat Creado y Activado (ID: {chat_id}):** *'{titulo}'*.", parse_mode="Markdown")

async def cambiar_chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("🔄 Uso: `/cambiar <id_del_chat>`\nConsulta tus chats con `/chats`.")
        return
    try:
        chat_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("⚠️ El ID debe ser un número.")
        return
        
    if cambiar_chat_activo(user_id, chat_id):
        await update.message.reply_text(f"✅ Has cambiado al chat con ID `{chat_id}`.", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ No se encontró un chat con ese ID.")

async def borrar_chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("🗑️ Uso: `/borrar <id_del_chat>`")
        return
    try:
        chat_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("⚠️ El ID debe ser un número.")
        return
        
    borrar_chat(user_id, chat_id)
    await update.message.reply_text(f"🗑️ El chat con ID `{chat_id}` ha sido eliminado.", parse_mode="Markdown")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if query.data == "mode_voice":
        actualizar_modo_usuario(user_id, "voice")
        await query.edit_message_text("✅ Preferencia guardada: **Notas de Voz**.")
    elif query.data == "mode_text":
        actualizar_modo_usuario(user_id, "text")
        await query.edit_message_text("✅ Preferencia guardada: **Texto**.")


# --- MANEJADORES DE MENSAJES MULTIMEDIA ---
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    if not user_text:
        return
    user_id = update.effective_user.id
    nombre = update.effective_user.first_name
    await update.message.chat.send_action("typing")
    respuesta = procesar_con_ia(user_id, user_text, tipo="texto", nombre_usuario=nombre)
    await responder_con_voz_o_texto(update, respuesta)

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    nombre = update.effective_user.first_name
    await update.message.chat.send_action("typing")
    voice = update.message.voice
    voice_file = await context.bot.get_file(voice.file_id)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp_path = tmp.name
            await voice_file.download_to_drive(tmp_path)
        respuesta = procesar_con_ia(user_id, tmp_path, tipo="audio", nombre_usuario=nombre)
        await responder_con_voz_o_texto(update, respuesta)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    nombre = update.effective_user.first_name
    await update.message.chat.send_action("typing")
    photo = update.message.photo[-1]
    photo_file = await context.bot.get_file(photo.file_id)
    caption = update.message.caption or ""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
          
