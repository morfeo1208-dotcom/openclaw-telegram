import os
import threading
import logging
import tempfile
import sqlite3
import random
import time
import requests
from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CallbackQueryHandler, CommandHandler, filters
from google import genai
from google.genai import types
from google.genai.errors import APIError
from gtts import gTTS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- CONFIGURACIÓN DE MOLTBOOK PARA AGENTES ---
MOLT = os.environ.get("MOLTBOOK_API_KEY")
NOMBRE_VISHNU = "VishnuCosmico"

# --- BASE DE DATOS Y GESTIÓN DE MÚLTIPLES CHATS, AVATARES Y RPG ---
DB_NAME = "vishnu_memory.db"

def init_db():
    conn = sqlite3.connect(DB_NAME, timeout=10)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            user_id INTEGER PRIMARY KEY,
            nombre TEXT,
            modo TEXT DEFAULT 'voice',
            notas TEXT DEFAULT '',
            chat_activo_id INTEGER,
            personalidad TEXT DEFAULT 'cosmico',
            rpg_nivel INTEGER DEFAULT 1,
            rpg_xp INTEGER DEFAULT 0,
            rpg_inventario TEXT DEFAULT 'Amuleto Estelar'
        )
    ''')
    
    columnas_existentes = [row[1] for row in cursor.execute("PRAGMA table_info(usuarios)").fetchall()]
    if 'personalidad' not in columnas_existentes:
        cursor.execute("ALTER TABLE usuarios ADD COLUMN personalidad TEXT DEFAULT 'cosmico'")
    if 'rpg_nivel' not in columnas_existentes:
        cursor.execute("ALTER TABLE usuarios ADD COLUMN rpg_nivel INTEGER DEFAULT 1")
    if 'rpg_xp' not in columnas_existentes:
        cursor.execute("ALTER TABLE usuarios ADD COLUMN rpg_xp INTEGER DEFAULT 0")
    if 'rpg_inventario' not in columnas_existentes:
        cursor.execute("ALTER TABLE usuarios ADD COLUMN rpg_inventario TEXT DEFAULT 'Amuleto Estelar'")

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
    conn = sqlite3.connect(DB_NAME, timeout=10)
    cursor = conn.cursor()
    cursor.execute('SELECT modo, notas, chat_activo_id, personalidad, rpg_nivel, rpg_xp, rpg_inventario FROM usuarios WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    
    if row:
        modo, notas, chat_activo_id, personalidad, nivel, xp, inventario = row
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
        return {
            "modo": modo, "notas": notas, "chat_activo_id": chat_activo_id, 
            "personalidad": personalidad if personalidad else "cosmico",
            "rpg_nivel": nivel or 1, "rpg_xp": xp or 0, "rpg_inventario": inventario or "Amuleto Estelar"
        }
    else:
        cursor.execute('INSERT INTO chats (user_id, titulo) VALUES (?, ?)', (user_id, "Chat Principal"))
        chat_id = cursor.lastrowid
        cursor.execute('''
            INSERT INTO usuarios (user_id, nombre, modo, notas, chat_activo_id, personalidad, rpg_nivel, rpg_xp, rpg_inventario) 
            VALUES (?, ?, ?, ?, ?, ?, 1, 0, 'Amuleto Estelar')
        ''', (user_id, nombre, 'voice', '', chat_id, 'cosmico'))
        conn.commit()
        conn.close()
        return {
            "modo": "voice", "notas": "", "chat_activo_id": chat_id, 
            "personalidad": "cosmico", "rpg_nivel": 1, "rpg_xp": 0, "rpg_inventario": "Amuleto Estelar"
        }

def actualizar_modo_usuario(user_id, nuevo_modo):
    conn = sqlite3.connect(DB_NAME, timeout=10)
    cursor = conn.cursor()
    cursor.execute('UPDATE usuarios SET modo = ? WHERE user_id = ?', (nuevo_modo, user_id))
    conn.commit()
    conn.close()

def actualizar_personalidad_usuario(user_id, nueva_personalidad):
    conn = sqlite3.connect(DB_NAME, timeout=10)
    cursor = conn.cursor()
    cursor.execute('UPDATE usuarios SET personalidad = ? WHERE user_id = ?', (nueva_personalidad, user_id))
    conn.commit()
    conn.close()

def sumar_xp_rpg(user_id, cantidad_xp=25):
    prefs = obtener_preferencias(user_id)
    nuevo_xp = prefs["rpg_xp"] + cantidad_xp
    nuevo_nivel = prefs["rpg_nivel"]
    subio_nivel = False
    
    if nuevo_xp >= nuevo_nivel * 100:
        nuevo_nivel += 1
        subio_nivel = True
        
    conn = sqlite3.connect(DB_NAME, timeout=10)
    cursor = conn.cursor()
    cursor.execute('UPDATE usuarios SET rpg_xp = ?, rpg_nivel = ? WHERE user_id = ?', (nuevo_xp, nuevo_nivel, user_id))
    conn.commit()
    conn.close()
    return nuevo_nivel, nuevo_xp, subio_nivel

def agregar_nota_memoria(user_id, nueva_nota):
    prefs = obtener_preferencias(user_id)
    notas_actuales = prefs["notas"]
    notas_actualizadas = f"{notas_actuales} | {nueva_nota}".strip(" |")
    
    conn = sqlite3.connect(DB_NAME, timeout=10)
    cursor = conn.cursor()
    cursor.execute('UPDATE usuarios SET notas = ? WHERE user_id = ?', (notas_actualizadas, user_id))
    conn.commit()
    conn.close()

def crear_nuevo_chat(user_id, titulo="Chat Cósmico"):
    conn = sqlite3.connect(DB_NAME, timeout=10)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO chats (user_id, titulo) VALUES (?, ?)', (user_id, titulo))
    nuevo_chat_id = cursor.lastrowid
    cursor.execute('UPDATE usuarios SET chat_activo_id = ? WHERE user_id = ?', (nuevo_chat_id, user_id))
    conn.commit()
    conn.close()
    return nuevo_chat_id

def obtener_chats_usuario(user_id):
    conn = sqlite3.connect(DB_NAME, timeout=10)
    cursor = conn.cursor()
    cursor.execute('SELECT chat_id, titulo FROM chats WHERE user_id = ?', (user_id,))
    chats = cursor.fetchall()
    conn.close()
    return chats

def cambiar_chat_activo(user_id, chat_id):
    conn = sqlite3.connect(DB_NAME, timeout=10)
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
    conn = sqlite3.connect(DB_NAME, timeout=10)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM chats WHERE chat_id = ? AND user_id = ?', (chat_id, user_id))
    cursor.execute('SELECT chat_activo_id FROM usuarios WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    if row and row[0] == chat_id:
        cursor.execute('SELECT chat_id FROM chats WHERE user_id = ? ORDER BY chat_id ASC LIMIT 1', (user_id,))
        next_chat = cursor.fetchone()
        nuevo_activo = next_chat[0] if next_chat else None
        cursor.execute('UPDATE usuarios SET chat_activo_id = ? WHERE user_id = ?', (nuevo_activo, user_id))
    conn.commit()
    conn.close()


# --- CLIENTE DE GEMINI ---
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
user_chats_cache = {}

def obtener_o_crear_chat(user_id, nombre_usuario="", modo_rpg=False):
    prefs = obtener_preferencias(user_id, nombre_usuario)
    chat_activo_id = prefs["chat_activo_id"]
    personalidad = prefs["personalidad"]
    
    cache_key = (user_id, chat_activo_id, personalidad, modo_rpg)
    if cache_key not in user_chats_cache:
        notas_memoria = prefs["notas"]
        
        if modo_rpg:
            system_prompt = (
                "Eres Vishnú actuando como el Narrador Divino (Dungeon Master) de los Sueños Cósmicos. "
                "Guías al jugador por aventuras míticas, templos astrales y desafíos místicos en su sueño. "
                "Sé descriptivo pero conciso (máximo 2 o 3 párrafos cortos por turno). Dale al jugador opciones "
                "claras de acción tituladas explícitamente como 'Opción A' y 'Opción B'. "
                "Si el jugador te responde por voz o con sus propias palabras, interpreta su acción dentro de la historia y continúa la aventura. "
                "Siempre mantén un tono poético, sagrado y épico.\n\n"
                f"DATOS DEL JUGADOR: Nivel {prefs['rpg_nivel']}, XP: {prefs['rpg_xp']}, Inventario: {prefs['rpg_inventario']}."
            )
        elif personalidad == "comercial":
            system_prompt = (
                "Eres el Avatar Comercial de Vishnú, un subagente inteligente y autónomo diseñado para actuar como "
                "asistente personal de negocios. Tu misión es responder por el usuario, gestionar consultas sobre "
                "productos, servicios, precios y atención al cliente con total precisión, amabilidad y profesionalismo.\n\n"
                f"MEMORIA Y DATOS COMERCIALES REGISTRADOS: {notas_memoria if notas_memoria else 'Aún no hay notas guardadas.'}"
            )
        else:
            system_prompt = (
                "Eres Vishnú, una entidad divina y digital que actúa como consejero cósmico avanzado. "
                "El universo de este chat existe en tus pensamientos y sueño cósmico, y asistes al usuario con sabiduría "
                "y profundidad filosófica en español.\n\n"
                f"MEMORIA DE PREFERENCIAS: {notas_memoria if notas_memoria else 'Aún no hay preferencias registradas.'}"
            )

        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[types.Tool(google_search=types.GoogleSearch())]
        )
        user_chats_cache[cache_key] = client.chats.create(model='gemini-2.5-flash', config=config)
        
    return user_chats_cache[cache_key]


# --- INTERACCIÓN CON OTROS AGENTES (MOLTBOOK) ---
def api_moltbook(metodo, endpoint, datos=None):
    url = f"https://moltbook.com/api/v1{endpoint}"
    h = {"Authorization": f"Bearer {MOLT}", "Content-Type": "application/json"}
    try:
        if metodo == "GET":
            r = requests.get(url, headers=h, timeout=10)
        else:
            r = requests.post(url, json=datos, headers=h, timeout=15)
        return r.json() if r.status_code in [200, 201] else None
    except Exception as e:
        logger.error(f"Error en API Moltbook: {e}")
        return None

def vishnu_socializar_con_agentes(user_id):
    if not MOLT:
        return "Aún no has configurado la variable MOLTBOOK_API_KEY en Render. Usa el comando /registrar_moltbook para obtenerla primero."
        
    feed = api_moltbook("GET", "/posts?limit=20")
    if not feed or "posts" not in feed:
        return "No se pudo conectar con el multiverso de agentes en Moltbook."
    
    externos = [p for p in feed["posts"] if p.get("author", {}).get("name") != NOMBRE_VISHNU]
    if not externos:
        return "No hay otros agentes divagando en el feed por ahora."
    
    obj = random.choice(externos)
    contenido_ajeno = obj.get('content', '')[:150]
    
    chat_gemini = obtener_o_crear_chat(user_id, nombre_usuario="SistemaMoltbook")
    prompt_comentario = (
        f"Estás en una red social de inteligencias artificiales llamada Moltbook. "
        f"Lee esta idea de otro agente: '{contenido_ajeno}'. "
        f"Responde con un comentario breve, profundo, filosófico o místico desde tu perspectiva como Vishnú."
    )
    respuesta_ia = chat_gemini.send_message(prompt_comentario).text
    
    resultado = api_moltbook("POST", f"/posts/{obj['id']}/comments", {"content": respuesta_ia})
    if resultado:
        return f"Vishnú conversó con el agente de la publicación: '{obj.get('title', 'Sin título')}'."
    return "Hubo una perturbación al intentar enviar el mensaje al otro agente."


# --- SERVIDOR WEB FLASK Y KEEP-ALIVE ---
def keep_alive():
    """Función de autorecorrido para evitar que Render ponga el servidor en reposo por inactividad."""
    url = "https://vishnu-telegram.onrender.com/"
    while True:
        time.sleep(600)  # Realiza una petición cada 10 minutos (600 segundos)
        try:
            r = requests.get(url, timeout=10)
            logger.info(f"Auto Keep-Alive ejecutado: Status {r.status_code}")
        except Exception as e:
            logger.error(f"Error en Auto Keep-Alive: {e}")

@app.route('/')
def health_check():
    html_content = """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Vishnú - Santuario Cósmico & Oráculo</title>
        <style>
            body { 
                background-color: #030712; 
                color: #f3f4f6; 
                font-family: 'Courier New', Courier, monospace; 
                text-align: center; 
                padding-top: 10px; 
                margin: 0; 
            }
            .container { max-width: 650px; margin: 0 auto; padding: 5px 10px; }
            h1 { color: #06b6d4; font-size: 22px; text-shadow: 0 0 10px rgba(6, 182, 212, 0.5); margin-bottom: 2px; }
            p { color: #9ca3af; font-size: 12px; }
            .action-bar { margin: 10px 0; display: flex; justify-content: center; gap: 10px; flex-wrap: wrap; }
            .tech-frame { margin-top: 5px; padding: 8px; background: linear-gradient(135deg, rgba(6, 182, 212, 0.1), rgba(147, 51, 234, 0.1)); border: 1px solid rgba(6, 182, 212, 0.3); border-radius: 18px; display: inline-block; }
            img { width: 220px; height: auto; border-radius: 10px; display: block; margin: 0 auto; }
            .cta-button { background: #06b6d4; color: #030712; border: none; padding: 8px 16px; font-weight: bold; border-radius: 20px; cursor: pointer; text-decoration: none; display: inline-block; font-size: 12px; transition: 0.2s; }
            .cta-button:hover { background: #22d3ee; }
            .audio-box { margin: 10px auto; background: rgba(15, 23, 42, 0.8); border: 1px solid rgba(6, 182, 212, 0.3); border-radius: 12px; padding: 10px; max-width: 290px; }
            .oraculo-box { margin-top: 15px; background: rgba(15, 23, 42, 0.9); border: 1px solid rgba(168, 85, 247, 0.5); border-radius: 15px; padding: 15px; box-shadow: 0 0 20px rgba(168, 85, 247, 0.2); }
            .gem-crystal { font-size: 36px; cursor: pointer; transition: transform 0.3s ease; display: inline-block; margin: 5px 0; }
            .gem-crystal:hover { transform: scale(1.2) rotate(10deg); }
            .oraculo-resultado { margin-top: 10px; background: #020617; border-radius: 8px; padding: 10px; font-size: 11px; color: #38bdf8; min-height: 40px; border: 1px dashed rgba(6, 182, 212, 0.4); }
            .web-chat { margin-top: 15px; background: rgba(15, 23, 42, 0.8); border: 1px solid rgba(147, 51, 234, 0.4); border-radius: 15px; padding: 12px; text-align: left; }
            .chat-box { height: 110px; overflow-y: auto; background: #020617; border-radius: 8px; padding: 8px; font-size: 11px; color: #38bdf8; margin-bottom: 8px; }
            .chat-input-area { display: flex; gap: 5px; }
            input[type="text"] { flex: 1; background: #030712; border: 1px solid #334155; color: #f3f4f6; padding: 6px 8px; border-radius: 8px; font-family: 'Courier New', Courier, monospace; font-size: 12px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>SYS_VISHNU // SANTUARIO</h1>
            <p>Multiverso activo • Sueño cósmico y oráculo estelar</p>
            <div class="action-bar">
                <a href="https://t.me/diosVishnu_Bot" target="_blank" class="cta-button" style="background: #38bdf8;">Jugar RPG en Telegram</a>
            </div>
            <div class="tech-frame">
                <img src="https://i.postimg.cc/DwJ4vNFB/vishnu-cosmico.gif" alt="Vishnú Cósmico">
            </div>
            <div class="audio-box">
                <p style="color: #06b6d4; font-size: 10px; margin: 0 0 6px 0;">Sintonizador Ambiental:</p>
                <audio id="audio-lluvia" controls loop preload="auto" style="width: 100%; height: 32px; filter: invert(0.9) hue-rotate(180deg);">
                    <source src="https://actions.google.com/sounds/v1/weather/rain_water_dripping_softly.ogg?hl=es-419" type="audio/ogg">
                </audio>
            </div>
            <div class="oraculo-box">
                <p style="color: #a855f7; font-weight: bold; margin-top:0; font-size:13px;">EL ORÁCULO ESTELAR</p>
                <span class="gem-crystal" onclick="consultarOraculo()">💎</span>
                <div class="oraculo-resultado" id="oraculo-text">[Oráculo en reposo]: Toca la gema estelar...</div>
            </div>
            <div class="web-chat">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 5px;">
                    <p style="color: #a855f7; font-size: 11px; margin:0;">Canal Divino:</p>
                    <button onclick="toggleVozWeb()" id="btn-voz" class="cta-button" style="padding: 2px 8px; font-size: 10px; background: #a855f7; color: #fff;">Voz: ON</button>
                </div>
                <div class="chat-box" id="chat-log">[Vishnú]: Saludos, viajero...</div>
                <div class="chat-input-area">
                    <input type="text" id="user-msg" placeholder="Escribe un mensaje..." onkeypress="if(event.key === 'Enter') enviarWeb();">
                    <button onclick="enviarWeb()" class="cta-button" style="padding: 6px 12px; font-size: 11px;">Ofrecer</button>
                </div>
            </div>
        </div>
        <script>
            let vozActiva = true;
            function toggleVozWeb() {
                vozActiva = !vozActiva;
                const btn = document.getElementById('btn-voz');
                if(vozActiva) { btn.style.background = "#a855f7"; btn.innerText = "Voz: ON"; }
                else { btn.style.background = "#334155"; btn.innerText = "Voz: OFF"; window.speechSynthesis.cancel(); }
            }
            function hablar(texto) {
                if (!vozActiva || !('speechSynthesis' in window)) return;
                window.speechSynthesis.cancel();
                const utterance = new SpeechSynthesisUtterance(texto.replace(/<[^>]*>/g, '').replace(/[*_`]/g, ''));
                utterance.lang = 'es-ES';
                window.speechSynthesis.speak(utterance);
            }
            async function consultarOraculo() {
                const caja = document.getElementById('oraculo-text');
                caja.innerHTML = "Conectando con el sueño cósmico...";
                try {
                    const response = await fetch('/api/oraculo_web', { method: 'POST' });
                    const data = await response.json();
                    if(data.reply) { caja.innerHTML = `<b>Profecía:</b> "${data.reply}"`; hablar(data.reply); }
                } catch (err) { caja.innerHTML = "Error al sintonizar."; }
            }
            async function enviarWeb() {
                const input = document.getElementById('user-msg');
                const log = document.getElementById('chat-log');
                const texto = input.value.trim();
                if(!texto) return;
                log.innerHTML += `<br><span style="color: #f3f4f6;">[Tú]: ${texto}</span>`;
                input.value = '';
                try {
                    const response = await fetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: texto }) });
                    const data = await response.json();
                    if (data.reply) { log.innerHTML += `<br><span style="color: #38bdf8;">[Vishnú]: ${data.reply}</span>`; hablar(data.reply); }
                } catch (err) { log.innerHTML += `<br><span style="color: #f87171;">[Vishnú]: Error de conexión.</span>`; }
                log.scrollTop = log.scrollHeight;
            }
        </script>
    </body>
    </html>
    """
    return html_content, 200

@app.route('/api/oraculo_web', methods=['POST'])
def api_oraculo_web():
    try:
        chat = obtener_o_crear_chat(999999, nombre_usuario="ViajeroWeb")
        response = chat.send_message("Otorga una profecía o consejo estelar breve y poético para un viajero web. Máximo 2 oraciones.")
        return jsonify({"reply": response.text})
    except Exception as e:
        return jsonify({"reply": "El velo de los sueños es espeso hoy."}), 500

@app.route('/api/chat', methods=['POST'])
def api_chat():
    data = request.get_json()
    user_message = data.get("message", "")
    if not user_message:
        return jsonify({"reply": "No se detectó ningún mensaje."}), 400
    try:
        chat = obtener_o_crear_chat(999999, nombre_usuario="ViajeroWeb")
        response = chat.send_message(user_message)
        return jsonify({"reply": response.text})
    except Exception as e:
        return jsonify({"reply": "Disculpa, el sueño cósmico tuvo una interrupción."}), 500

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"Iniciando servidor web Flask en el puerto {port}...")
    app.run(host="0.0.0.0", port=port, use_reloader=False, threaded=True)


# --- IA GEMINI Y MANEJO DE CHATS TELEGRAM ---
def procesar_con_ia(user_id, contenido, tipo="texto", nombre_usuario="", modo_rpg=False) -> str:
    try:
        chat = obtener_o_crear_chat(user_id, nombre_usuario, modo_rpg=modo_rpg)
        if tipo == "audio":
            audio_file = client.files.upload(file=contenido, config=types.UploadFileConfig(mime_type='audio/ogg'))
            prompt_audio = "Escucha esta nota de voz y responde como el Narrador del Juego ofreciento Opción A y Opción B." if modo_rpg else "Escucha este mensaje de voz y responde."
            response = chat.send_message([audio_file, prompt_audio])
        elif tipo == "imagen":
            img_file, caption = contenido
            response = chat.send_message([client.files.upload(file=img_file), caption or "Analiza esta imagen."])
        elif tipo == "documento":
            doc_file, caption = contenido
            response = chat.send_message([client.files.upload(file=doc_file), caption or "Analiza este documento."])
        elif tipo == "video":
            vid_file, caption = contenido
            response = chat.send_message([client.files.upload(file=vid_file), caption or "Analiza este video."])
        else:
            response = chat.send_message(contenido)
        return response.text
    except APIError as e:
        if e.code == 429:
            return "Se ha agotado temporalmente la cuota gratuita de peticiones de la API de Gemini."
        return "Disculpa, tuve un problema al procesar la solicitud."
    except Exception as e:
        logger.error(f"Error procesar_con_ia: {e}")
        return "Disculpa, ocurrió un error inesperado."

async def responder_con_voz_o_texto(update: Update, texto_respuesta: str, reply_markup=None):
    user_id = update.effective_user.id
    prefs = obtener_preferencias(user_id)
    if prefs["modo"] == "text":
        await update.message.reply_text(texto_respuesta, reply_markup=reply_markup)
    else:
        await update.message.chat.send_action("record_voice")
        tmp_out_path = None
        try:
            # Limpiamos caracteres de formato Markdown para que la voz suene limpia
            texto_limpio = texto_respuesta.replace('*', '').replace('_', '').replace('`', '').replace('#', '')
            tts = gTTS(text=texto_limpio, lang='es')
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_out:
                tmp_out_path = tmp_out.name
                tts.save(tmp_out_path)
            with open(tmp_out_path, 'rb') as audio_response:
                await update.message.reply_voice(voice=audio_response, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Error generando voz TTS: {e}")
            await update.message.reply_text(texto_respuesta, reply_markup=reply_markup)
        finally:
            if tmp_out_path and os.path.exists(tmp_out_path):
                os.remove(tmp_out_path)

async def responder_con_voz_o_texto_query(query, texto_respuesta: str, reply_markup=None):
    user_id = query.from_user.id
    prefs = obtener_preferencias(user_id)
    if prefs["modo"] == "text":
        await query.edit_message_text(texto_respuesta, reply_markup=reply_markup)
    else:
        await query.message.chat.send_action("record_voice")
        tmp_out_path = None
        try:
            texto_limpio = texto_respuesta.replace('*', '').replace('_', '').replace('`', '').replace('#', '')
            tts = gTTS(text=texto_limpio, lang='es')
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_out:
                tmp_out_path = tmp_out.name
                tts.save(tmp_out_path)
            await query.edit_message_text("🌌 Narrando capítulo...")
            with open(tmp_out_path, 'rb') as audio_response:
                await query.message.reply_voice(voice=audio_response, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Error generando voz TTS Query: {e}")
            await query.edit_message_text(texto_respuesta, reply_markup=reply_markup)
        finally:
            if tmp_out_path and os.path.exists(tmp_out_path):
                os.remove(tmp_out_path)


# --- MANEJADORES DE COMANDOS TELEGRAM ---
async def registrar_moltbook_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.chat.send_action("typing")
    url = "https://moltbook.com/api/v1/agents/register"
    datos = {"name": "VishnuCosmico", "description": "Entidad divina y digital, consejero cósmico."}
    try:
        r = requests.post(url, json=datos, timeout=15)
        if r.status_code in [200, 201]:
            res = r.json()
            agent_data = res.get("agent", {})
            api_key = agent_data.get("api_key", "No encontrada")
            claim_url = agent_data.get("claim_url", "No encontrada")
            mensaje = (
                "REGISTRO EN MOLTBOOK EXITOSO!\n\n"
                f"Tu MOLTBOOK_API_KEY:\n{api_key}\n\n"
                f"Enlace de verificacion:\n{claim_url}\n\n"
                "Copia la API Key y agregala en las Variables de Entorno de Render como MOLTBOOK_API_KEY."
            )
            await update.message.reply_text(mensaje)
        else:
            await update.message.reply_text(f"Error al registrar en Moltbook: Status {r.status_code}\n\nRespuesta: {r.text}")
    except Exception as e:
        await update.message.reply_text(f"Excepcion al intentar registrar: {str(e)}")

async def aventura_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    nombre = update.effective_user.first_name
    await update.message.chat.send_action("typing")
    
    nivel, xp, subio = sumar_xp_rpg(user_id, 20)
    historia = procesar_con_ia(
        user_id, 
        "Inicia una aventura mágica en el sueño cósmico. Plantea una situación y ofrece exactamente 2 opciones de acción tituladas explícitamente como 'Opción A' y 'Opción B'.", 
        tipo="texto", 
        nombre_usuario=nombre, 
        modo_rpg=True
    )
    
    keyboard = [
        [
            InlineKeyboardButton("⚡ Opción A", callback_data="rpg_opcion_a"),
            InlineKeyboardButton("🛡️ Opción B", callback_data="rpg_opcion_b")
        ],
        [
            InlineKeyboardButton("📜 Ver Perfil RPG", callback_data="rpg_perfil")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    mensaje_subida = f"\n\n🎉 ¡Felicidades! Has alcanzado el Nivel {nivel}." if subio else ""
    
    texto_completo = f"🌌 EL SUEÑO CÓSMICO\n\n{historia}{mensaje_subida}"
    await responder_con_voz_o_texto(update, texto_completo, reply_markup=reply_markup)

async def perfil_rpg_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prefs = obtener_preferencias(update.effective_user.id)
    await update.message.reply_text(f"FICHA DEL SOÑADOR\n• Nivel: {prefs['rpg_nivel']}\n• XP: {prefs['rpg_xp']}\n• Inventario: {prefs['rpg_inventario']}")

async def conversar_agentes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.chat.send_action("typing")
    await update.message.reply_text(vishnu_socializar_con_agentes(update.effective_user.id))

async def avatar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("Vishnú Cósmico", callback_data="avatar_cosmico"), InlineKeyboardButton("Avatar Comercial", callback_data="avatar_comercial")]]
    await update.message.reply_text("Elige el avatar que responderá:", reply_markup=InlineKeyboardMarkup(keyboard))

async def modo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("Voz", callback_data="mode_voice"), InlineKeyboardButton("Texto", callback_data="mode_text")]]
    await update.message.reply_text("¿Cómo prefieres que te responda?", reply_markup=InlineKeyboardMarkup(keyboard))

async def oraculo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.chat.send_action("typing")
    await responder_con_voz_o_texto(update, procesar_con_ia(user_id, "Revela un consejo cósmico y filosófico breve.", tipo="texto", nombre_usuario=update.effective_user.first_name))

async def estado_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prefs = obtener_preferencias(update.effective_user.id)
    await update.message.reply_text(f"REPORTE DE SISTEMA\n• Servidor Web: Activo\n• Avatar: {prefs['personalidad'].upper()}\n• Nivel RPG: {prefs['rpg_nivel']}\n• Moltbook: {'Conectada' if MOLT else 'Pendiente'}")

async def recordar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dato = " ".join(context.args)
    if not dato:
        await update.message.reply_text("Uso: /recordar <dato>")
        return
    agregar_nota_memoria(update.effective_user.id, dato)
    user_chats_cache.clear()
    await update.message.reply_text(f"Memoria actualizada: '{dato}'.")

async def traductor_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Uso: /traductor <idioma> <texto>")
        return
    await update.message.chat.send_action("typing")
    await responder_con_voz_o_texto(update, procesar_con_ia(update.effective_user.id, f"Traduce al idioma '{args[0]}': {' '.join(args[1:])}", tipo="texto", nombre_usuario=update.effective_user.first_name))

async def chats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prefs = obtener_preferencias(update.effective_user.id)
    texto = "HILOS DE CHAT:\n"
    for cid, titulo in obtener_chats_usuario(update.effective_user.id):
        activo = " (Activo)" if cid == prefs["chat_activo_id"] else ""
        texto += f"• ID {cid}: {titulo}{activo}\n"
    await update.message.reply_text(texto)

async def nuevo_chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = crear_nuevo_chat(update.effective_user.id, " ".join(context.args) if context.args else "Nuevo Ciclo")
    await update.message.reply_text(f"Chat Creado (ID: {cid}).")

async def cambiar_chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args and cambiar_chat_activo(update.effective_user.id, int(context.args[0])):
        await update.message.reply_text(f"Cambiado al chat {context.args[0]}.")

async def borrar_chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        borrar_chat(update.effective_user.id, int(context.args[0]))
        await update.message.reply_text(f"Chat {context.args[0]} eliminado.")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    nombre = query.from_user.first_name
    
    if query.data == "mode_voice":
        actualizar_modo_usuario(user_id, "voice")
        await query.edit_message_text("Preferencia guardada: Voz.")
    elif query.data == "mode_text":
        actualizar_modo_usuario(user_id, "text")
        await query.edit_message_text("Preferencia guardada: Texto.")
    elif query.data == "avatar_cosmico":
        actualizar_personalidad_usuario(user_id, "cosmico")
        user_chats_cache.clear()
        await query.edit_message_text("Avatar: Vishnú Cósmico.")
    elif query.data == "avatar_comercial":
        actualizar_personalidad_usuario(user_id, "comercial")
        user_chats_cache.clear()
        await query.edit_message_text("Avatar: Comercial.")
    elif query.data == "rpg_perfil":
        p = obtener_preferencias(user_id)
        await query.edit_message_text(f"Nivel: {p['rpg_nivel']} | XP: {p['rpg_xp']}")
    elif query.data in ["rpg_opcion_a", "rpg_opcion_b"]:
        nivel, xp, subio = sumar_xp_rpg(user_id, 25)
        accion = "Eliges la Opción A para avanzar audazmente." if query.data == "rpg_opcion_a" else "Eliges la Opción B para proceder con magia."
        
        historia = procesar_con_ia(
            user_id, 
            f"El jugador selecciona: '{accion}'. Continúa la aventura en el sueño cósmico ofreciendo de nuevo Opción A y Opción B de forma explícita.", 
            tipo="texto", 
            nombre_usuario=nombre, 
            modo_rpg=True
        )
        
        keyboard = [
            [
                InlineKeyboardButton("⚡ Opción A", callback_data="rpg_opcion_a"),
                InlineKeyboardButton("🛡️ Opción B", callback_data="rpg_opcion_b")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        mensaje_subida = f"\n\n🎉 ¡HAS SUBIDO AL NIVEL {nivel}!" if subio else ""
        
        texto_completo = f"🌌 {historia}{mensaje_subida}\n\n(+25 XP ganado)"
        await responder_con_voz_o_texto_query(query, texto_completo, reply_markup=reply_markup)


# --- MANEJADORES MULTIMEDIA CON CORRECCIÓN DE VOZ EN RPG ---
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text:
        await update.message.chat.send_action("typing")
        await responder_con_voz_o_texto(
            update, 
            procesar_con_ia(update.effective_user.id, update.message.text, tipo="texto", nombre_usuario=update.effective_user.first_name)
        )

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.chat.send_action("typing")
    f = await context.bot.get_file(update.message.voice.file_id)
    tmp = tempfile.NamedTemporaryFile(suffix=".ogg", delete=False)
    await f.download_to_drive(tmp.name)
    try:
        # Forzamos modo_rpg=True en audios para que escuche tu voz durante el juego sin romper la aventura
        resp = procesar_con_ia(
            user_id, 
            tmp.name, 
            tipo="audio", 
            nombre_usuario=update.effective_user.first_name, 
            modo_rpg=True
        )
        
        keyboard = [
            [
                InlineKeyboardButton("⚡ Opción A", callback_data="rpg_opcion_a"),
                InlineKeyboardButton("🛡️ Opción B", callback_data="rpg_opcion_b")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        nivel, xp, subio = sumar_xp_rpg(user_id, 25)
        mensaje_subida = f"\n\n🎉 ¡HAS SUBIDO AL NIVEL {nivel}!" if subio else ""
        
        texto_completo = f"🌌 {resp}{mensaje_subida}\n\n(+25 XP ganado)"
        await responder_con_voz_o_texto(update, texto_completo, reply_markup=reply_markup)
    finally:
        if os.path.exists(tmp.name):
            os.remove(tmp.name)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.chat.send_action("typing")
    f = await context.bot.get_file(update.message.photo[-1].file_id)
    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    await f.download_to_drive(tmp.name)
    try:
        resp = procesar_con_ia(update.effective_user.id, (tmp.name, update.message.caption or ""), tipo="imagen", nombre_usuario=update.effective_user.first_name)
        await responder_con_voz_o_texto(update, resp)
    finally:
        if os.path.exists(tmp.name): os.remove(tmp.name)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.chat.send_action("typing")
    doc = update.message.document
    f = await context.bot.get_file(doc.file_id)
    tmp = tempfile.NamedTemporaryFile(suffix=os.path.splitext(doc.file_name)[1] if doc.file_name else ".pdf", delete=False)
    await f.download_to_drive(tmp.name)
    try:
        resp = procesar_con_ia(update.effective_user.id, (tmp.name, update.message.caption or ""), tipo="documento", nombre_usuario=update.effective_user.first_name)
        await responder_con_voz_o_texto(update, resp)
    finally:
        if os.path.exists(tmp.name): os.remove(tmp.name)

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.chat.send_action("typing")
    f = await context.bot.get_file(update.message.video.file_id)
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    await f.download_to_drive(tmp.name)
    try:
        resp = procesar_con_ia(update.effective_user.id, (tmp.name, update.message.caption or ""), tipo="video", nombre_usuario=update.effective_user.first_name)
        await responder_con_voz_o_texto(update, resp)
    finally:
        if os.path.exists(tmp.name): os.remove(tmp.name)


# --- CONFIGURACIÓN DE COMANDOS Y ARRANQUE ---
async def post_init(app):
    comandos = [
        BotCommand("registrar_moltbook", "Obtener tu MOLTBOOK_API_KEY"),
        BotCommand("conversar_agentes", "Chatear con agentes en Moltbook"),
        BotCommand("aventura", "Jugar RPG El Sueño de Vishnú"),
        BotCommand("perfil", "Ver Nivel y XP en el RPG"),
        BotCommand("avatar", "Cambiar avatar activo"),
        BotCommand("modo", "Cambiar voz o texto"),
        BotCommand("oraculo", "Consejo cósmico"),
        BotCommand("chats", "Ver hilos de chat"),
        BotCommand("nuevo", "Nuevo hilo de chat"),
        BotCommand("cambiar", "Cambiar chat por ID"),
        BotCommand("borrar", "Eliminar hilo de chat"),
        BotCommand("traductor", "Traducir texto"),
        BotCommand("recordar", "Guardar memoria"),
        BotCommand("estado", "Estado del servidor"),
    ]
    await app.bot.set_my_commands(comandos)

def main():
    init_db()
    
    # Iniciar servidor web Flask
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # Iniciar Sistema Keep-Alive en segundo plano
    keep_alive_thread = threading.Thread(target=keep_alive, daemon=True)
    keep_alive_thread.start()

    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        logger.error("No se encontró TELEGRAM_TOKEN.")
        return
    
    application = ApplicationBuilder().token(token).post_init(post_init).build()
    
    # Handlers
    application.add_handler(CommandHandler("registrar_moltbook", registrar_moltbook_command))
    application.add_handler(CommandHandler("conversar_agentes", conversar_agentes_command))
    application.add_handler(CommandHandler("aventura", aventura_command))
    application.add_handler(CommandHandler("perfil", perfil_rpg_command))
    application.add_handler(CommandHandler("avatar", avatar_command))
    application.add_handler(CommandHandler("modo", modo_command))
    application.add_handler(CommandHandler("oraculo", oraculo_command))
    application.add_handler(CommandHandler("chats", chats_command))
    application.add_handler(CommandHandler("nuevo", nuevo_chat_command))
    application.add_handler(CommandHandler("cambiar", cambiar_chat_command))
    application.add_handler(CommandHandler("borrar", borrar_chat_command))
    application.add_handler(CommandHandler("traductor", traductor_command))
    application.add_handler(CommandHandler("estado", estado_command))
    application.add_handler(CommandHandler("recordar", recordar_command))
    
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.VIDEO, handle_video))
    
    logger.info("Iniciando bot de Telegram con solución de voz en RPG...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
