import os
import threading
import logging
import tempfile
import sqlite3
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

# --- BASE DE DATOS Y GESTIÓN DE MÚLTIPLES CHATS, AVATARES Y RPG ---
DB_NAME = "vishnu_memory.db"

def init_db():
    """Crea las tablas de base de datos para usuarios, múltiples chats, avatares y progreso de RPG."""
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
                "Sé descriptivo pero conciso (máximo 3 párrafos cortos por turno). Dale al jugador opciones "
                "claras de acción. Siempre mantén un tono poético, sagrado y épico.\n\n"
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


# --- SERVIDOR WEB FLASK CON ORÁCULO Y MÚSICA AMBIENTAL ---
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
            
            /* REPRODUCTOR AMBIENTAL */
            .audio-box {
                margin: 10px auto;
                background: rgba(15, 23, 42, 0.8);
                border: 1px solid rgba(6, 182, 212, 0.3);
                border-radius: 12px;
                padding: 8px;
                max-width: 280px;
            }

            /* ORÁCULO ESTELAR / RULETA DE BENDICIONES */
            .oraculo-box {
                margin-top: 15px;
                background: rgba(15, 23, 42, 0.9);
                border: 1px solid rgba(168, 85, 247, 0.5);
                border-radius: 15px;
                padding: 15px;
                box-shadow: 0 0 20px rgba(168, 85, 247, 0.2);
            }
            .gem-crystal {
                font-size: 36px;
                cursor: pointer;
                transition: transform 0.3s ease;
                display: inline-block;
                margin: 5px 0;
                animation: pulseGlow 2s infinite;
            }
            .gem-crystal:hover {
                transform: scale(1.2) rotate(10deg);
            }
            @keyframes pulseGlow {
                0% { filter: drop-shadow(0 0 5px #a855f7); }
                50% { filter: drop-shadow(0 0 20px #06b6d4); }
                100% { filter: drop-shadow(0 0 5px #a855f7); }
            }
            .oraculo-resultado {
                margin-top: 10px;
                background: #020617;
                border-radius: 8px;
                padding: 10px;
                font-size: 11px;
                color: #38bdf8;
                min-height: 40px;
                border: 1px dashed rgba(6, 182, 212, 0.4);
            }

            /* CHAT WEB */
            .web-chat {
                margin-top: 15px;
                background: rgba(15, 23, 42, 0.8);
                border: 1px solid rgba(147, 51, 234, 0.4);
                border-radius: 15px;
                padding: 12px;
                text-align: left;
            }
            .chat-box {
                height: 100px;
                overflow-y: auto;
                background: #020617;
                border-radius: 8px;
                padding: 8px;
                font-size: 11px;
                color: #38bdf8;
                margin-bottom: 8px;
            }
            .chat-input-area { display: flex; gap: 5px; }
            input[type="text"] {
                flex: 1; background: #030712; border: 1px solid #334155; color: #f3f4f6; padding: 6px 8px; border-radius: 8px; font-family: 'Courier New', Courier, monospace; font-size: 12px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>SYS_VISHNU // SANTUARIO</h1>
            <p>Multiverso activo • Sueño cósmico y oráculo estelar</p>
            
            <div class="action-bar">
                <a href="https://t.me/diosVishnu_Bot" target="_blank" class="cta-button" style="background: #38bdf8;">✈️ Jugar RPG en Telegram</a>
            </div>
            
            <div class="tech-frame">
                <img src="https://i.postimg.cc/DwJ4vNFB/vishnu-cosmico.gif" alt="Vishnú Cósmico">
            </div>

            <!-- REPRODUCTOR DE MÚSICA AMBIENTAL -->
            <div class="audio-box">
                <p style="color: #06b6d4; font-size: 10px; margin: 0 0 4px 0;">Sintonizador Ambiental (Sueño Cósmico):</p>
                <audio controls loop preload="auto" style="width: 100%; height: 28px; filter: invert(0.9) hue-rotate(180deg);">
                    <source src="https://actions.google.com/sounds/v1/weather/rain_water_dripping_softly.ogg?hl=es-419" type="audio/ogg">
                    Tu navegador no soporta audio.
                </audio>
            </div>

            <!-- ORÁCULO ESTELAR / RULETA DE BENDICIONES -->
            <div class="oraculo-box">
                <p style="color: #a855f7; font-weight: bold; margin-top:0; font-size:13px;">🔮 EL ORÁCULO ESTELAR (RULETA DE BENDICIONES)</p>
                <p style="font-size: 11px; margin-bottom: 5px;">Toca la gema sagrada para recibir una profecía de los sueños de Vishnú:</p>
                <span class="gem-crystal" onclick="consultarOraculo()" title="Toca para invocar profecía">💎</span>
                <div class="oraculo-resultado" id="oraculo-text">
                    [Oráculo en reposo]: Toca la gema estelar para revelar tu destino de hoy...
                </div>
            </div>

            <!-- CHAT WEB -->
            <div class="web-chat">
                <p style="color: #a855f7; font-size: 11px; margin-top:0;">Canal Divino con Vishnú:</p>
                <div class="chat-box" id="chat-log">
                    [Vishnú]: Saludos, viajero. Escribe tu consulta al santuario...
                </div>
                <div class="chat-input-area">
                    <input type="text" id="user-msg" placeholder="Escribe un mensaje..." onkeypress="if(event.key === 'Enter') enviarWeb();">
                    <button onclick="enviarWeb()" class="cta-button" style="padding: 6px 12px; font-size: 11px;">Ofrecer</button>
                </div>
            </div>
        </div>

        <script>
            async function consultarOraculo() {
                const caja = document.getElementById('oraculo-text');
                caja.innerHTML = "✨ Conectando con el sueño cósmico de Vishnú y revelando profecía...";
                try {
                    const response = await fetch('/api/oraculo_web', { method: 'POST' });
                    const data = await response.json();
                    if(data.reply) {
                        caja.innerHTML = `🌟 <b>Profecía Estelar:</b> "${data.reply}"`;
                    } else {
                        caja.innerHTML = "⚠️ El oráculo parpadeó en las estrellas. Intenta de nuevo.";
                    }
                } catch (err) {
                    caja.innerHTML = "❌ Error al sintonizar con el multiverso.";
                }
            }

            async function enviarWeb() {
                const input = document.getElementById('user-msg');
                const log = document.getElementById('chat-log');
                const texto = input.value.trim();
                if(!texto) return;

                log.innerHTML += `<br><span style="color: #f3f4f6;">[Tú]: ${texto}</span>`;
                input.value = '';
                log.scrollTop = log.scrollHeight;

                try {
                    const response = await fetch('/api/chat', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ message: texto })
                    });
                    const data = await response.json();
                    if (data.reply) {
                        log.innerHTML += `<br><span style="color: #38bdf8;">[Vishnú]: ${data.reply}</span>`;
                    } else {
                        log.innerHTML += `<br><span style="color: #f87171;">[Vishnú]: Ocurrió un error en el multiverso.</span>`;
                    }
                } catch (err) {
                    log.innerHTML += `<br><span style="color: #f87171;">[Vishnú]: Error de conexión neuronal.</span>`;
                }
                log.scrollTop = log.scrollHeight;
            }
        </script>
    </body>
    </html>
    """
    return html_content, 200

@app.route('/api/oraculo_web', methods=['POST'])
def api_oraculo_web():
    web_user_id = 999999
    try:
        chat = obtener_o_crear_chat(web_user_id, nombre_usuario="ViajeroWeb")
        prompt = "Imagina que eres Vishnú desde tu sueño cósmico. Otorga una profecía mística, bendición o consejo estelar breve, poético y único para un viajero que acaba de tocar la gema del oráculo en la web. Máximo 2 oraciones."
        response = chat.send_message(prompt)
        return jsonify({"reply": response.text})
    except Exception as e:
        logger.error(f"Error en oráculo web: {e}")
        return jsonify({"reply": "El velo de los sueños cósmicos es espeso hoy. Vuelve a intentarlo."}), 500

@app.route('/api/chat', methods=['POST'])
def api_chat():
    data = request.get_json()
    user_message = data.get("message", "")
    if not user_message:
        return jsonify({"reply": "No se detectó ningún mensaje."}), 400
    
    web_user_id = 999999
    try:
        chat = obtener_o_crear_chat(web_user_id, nombre_usuario="ViajeroWeb")
        response = chat.send_message(user_message)
        return jsonify({"reply": response.text})
    except Exception as e:
        logger.error(f"Error en chat web API: {e}")
        return jsonify({"reply": "Disculpa, el sueño cósmico tuvo una pequeña interrupción."}), 500

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"Iniciando servidor web Flask en el puerto {port}...")
    app.run(host="0.0.0.0", port=port, use_reloader=False, threaded=True)


# --- IA GEMINI Y MANEJO DE CHATS TELEGRAM ---
def procesar_con_ia(user_id, contenido, tipo="texto", nombre_usuario="", modo_rpg=False) -> str:
    try:
        chat = obtener_o_crear_chat(user_id, nombre_usuario, modo_rpg=modo_rpg)
        
        if tipo == "audio":
            audio_file = client.files.upload(
                file=contenido,
                config=types.UploadFileConfig(mime_type='audio/ogg')
            )
            response = chat.send_message([audio_file, "Escucha este mensaje de voz del usuario y responde a su solicitud."])
        elif tipo == "imagen":
            img_file, caption = contenido
            image_file_ref = client.files.upload(file=img_file)
            prompt_text = caption if caption else "Analiza esta imagen y describe qué ves o responde al contenido de ella."
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
            return "⚠️ Se ha agotado temporalmente la cuota gratuita de peticiones de la API. Intenta en un momento."
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


# --- MANEJADORES DE COMANDOS TELEGRAM Y MODO RPG ---
async def aventura_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    nombre = update.effective_user.first_name
    await update.message.chat.send_action("typing")
    
    nivel, xp, subio = sumar_xp_rpg(user_id, 20)
    prompt_inicio = (
        "Inicia o continúa una aventura mágica en uno de tus sueños cósmicos. "
        "Plantea una situación intrigante, una criatura o un portal místico, "
        "y ofrece 2 acciones posibles que el jugador puede tomar."
    )
    historia = procesar_con_ia(user_id, prompt_inicio, tipo="texto", nombre_usuario=nombre, modo_rpg=True)
    
    keyboard = [
        [
            InlineKeyboardButton("⚡ Opción A: Explorar lo desconocido", callback_data="rpg_opcion_a"),
            InlineKeyboardButton("🛡️ Opción B: Usar canalización mágica", callback_data="rpg_opcion_b")
        ],
        [
            InlineKeyboardButton("📜 Ver mi Perfil RPG", callback_data="rpg_perfil")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    mensaje_subida = f"\n\n🎉 ¡Felicidades! Has alcanzado el **Nivel {nivel}** de Conciencia Cósmica." if subio else ""
    await update.message.reply_text(f"🌌 **EL SUEÑO CÓSMICO DE VISHNÚ**\n\n{historia}{mensaje_subida}", reply_markup=reply_markup)

async def perfil_rpg_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    prefs = obtener_preferencias(user_id)
    texto_perfil = (
        "🛡️ **FICHA DEL SOÑADOR CÓSMICO**\n\n"
        f"• **Viajero:** {update.effective_user.first_name}\n"
        f"• **Nivel:** `{prefs['rpg_nivel']}`\n"
        f"• **Experiencia (XP):** `{prefs['rpg_xp']}` pts\n"
        f"• **Inventario:** `{prefs['rpg_inventario']}`\n\n"
        "💡 *Escribe `/aventura` para adentrarte de nuevo en el sueño.*"
    )
    await update.message.reply_text(texto_perfil, parse_mode="Markdown")

async def avatar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("🌌 Vishnú (Modo Cósmico)", callback_data="avatar_cosmico"),
            InlineKeyboardButton("💼 Avatar Comercial (Negocios)", callback_data="avatar_comercial"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🔀 **SISTEMA DE PROYECCIÓN DE AVATARES:**\n\n"
        "Elige quién responderá a partir de ahora en tus interacciones de Telegram:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

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
    prompt_oraculo = "Revela un consejo cósmico, filosófico y motivacional en 2 o 3 oraciones manteniendo tu personalidad divina."
    respuesta = procesar_con_ia(user_id, prompt_oraculo, tipo="texto", nombre_usuario=nombre)
    await responder_con_voz_o_texto(update, respuesta)

async def estado_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    prefs = obtener_preferencias(user_id)
    mensaje_estado = (
        "🟢 *SYS_VISHNU // REPORTE DE SISTEMA*\n\n"
        "• *Servidor Web:* Activo en Render (Con Oráculo y Música)\n"
        f"• *Avatar Activo:* `{prefs['personalidad'].upper()}`\n"
        f"• *Nivel RPG:* `{prefs['rpg_nivel']}` ({prefs['rpg_xp']} XP)\n"
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
    user_chats_cache.clear()
    await update.message.reply_text(f"👁️ **Memoria Actualizada:** *'{dato}'*.", parse_mode="Markdown")

async def traductor_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    nombre = update.effective_user.first_name
    args = context.args
    if not args:
        await update.message.reply_text("🌐 Uso: `/traductor <idioma> <texto>`", parse_mode="Markdown")
        return
    idioma = args[0].lower()
    texto = " ".join(args[1:]) if len(idioma) <= 3 else " ".join(args)
    destino = idioma if len(idioma) <= 3 else "es"
    await update.message.chat.send_action("typing")
    prompt = f"Traduce de forma natural al idioma '{destino}':\n\n{texto}"
    respuesta = procesar_con_ia(user_id, prompt, tipo="texto", nombre_usuario=nombre)
    await responder_con_voz_o_texto(update, respuesta)

async def chats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    prefs = obtener_preferencias(user_id)
    chats = obtener_chats_usuario(user_id)
    texto = "📂 **TUS HILOS DE CHAT:**\n\n"
    for cid, titulo in chats:
        activo = " 🟢 *(Activo)*" if cid == prefs["chat_activo_id"] else ""
        texto += f"• **ID {cid}:** {titulo}{activo}\n"
    await update.message.reply_text(texto, parse_mode="Markdown")

async def nuevo_chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    titulo = " ".join(context.args) if context.args else "Nuevo Ciclo"
    chat_id = crear_nuevo_chat(user_id, titulo)
    await update.message.reply_text(f"✨ **Chat Creado (ID: {chat_id}):** *'{titulo}'*.", parse_mode="Markdown")

async def cambiar_chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        return
    try:
        chat_id = int(context.args[0])
        if cambiar_chat_activo(user_id, chat_id):
            await update.message.reply_text(f"✅ Cambiado al chat `{chat_id}`.", parse_mode="Markdown")
    except ValueError:
        pass

async def borrar_chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        return
    try:
        chat_id = int(context.args[0])
        borrar_chat(user_id, chat_id)
        await update.message.reply_text(f"🗑️ Chat `{chat_id}` eliminado.", parse_mode="Markdown")
    except ValueError:
        pass

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    nombre = query.from_user.first_name
    
    if query.data == "mode_voice":
        actualizar_modo_usuario(user_id, "voice")
        await query.edit_message_text("✅ Preferencia guardada: **Notas de Voz**.")
    elif query.data == "mode_text":
        actualizar_modo_usuario(user_id, "text")
        await query.edit_message_text("✅ Preferencia guardada: **Texto**.")
    elif query.data == "avatar_cosmico":
        actualizar_personalidad_usuario(user_id, "cosmico")
        user_chats_cache.clear()
        await query.edit_message_text("🌌 **Avatar Actualizado:** Has sintonizado con **Vishnú (Modo Cósmico)**.")
    elif query.data == "avatar_comercial":
        actualizar_personalidad_usuario(user_id, "comercial")
        user_chats_cache.clear()
        await query.edit_message_text("💼 **Avatar Actualizado:** Has proyectado el **Avatar Comercial** 🤖.")
    elif query.data == "rpg_perfil":
        prefs = obtener_preferencias(user_id)
        await query.edit_message_text(f"🛡️ **Nivel:** {prefs['rpg_nivel']} | **XP:** {prefs['rpg_xp']} | **Objetos:** {prefs['rpg_inventario']}")
    elif query.data in ["rpg_opcion_a", "rpg_opcion_b"]:
        nivel, xp, subio = sumar_xp_rpg(user_id, 25)
        accion = "Eliges aventurarte decididamente por el camino frontal." if query.data == "rpg_opcion_a" else "Eliges invocar un encantamiento y proceder con cautela."
        
        historia = procesar_con_ia(user_id, f"El jugador responde: '{accion}'. Narra el resultado y continúa la aventura en el sueño.", tipo="texto", nombre_usuario=nombre, modo_rpg=True)
        
        keyboard = [
            [
                InlineKeyboardButton("⚡ Continuar Aventura", callback_data="rpg_opcion_a"),
                InlineKeyboardButton("🔮 Usar magia ancestral", callback_data="rpg_opcion_b")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        mensaje_subida = f"\n\n🎉 **¡HAS SUBIDO AL NIVEL {nivel}!**" if subio else ""
        await query.edit_message_text(f"🌌 {historia}{mensaje_subida}\n\n*(+25 XP ganado)*", reply_markup=reply_markup)


# --- MANEJADORES DE MENSAJES MULTIMEDIA TELEGRAM ---
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
            tmp_path = tmp.name
            await photo_file.download_to_drive(tmp_path)
        respuesta = procesar_con_ia(user_id, (tmp_path, caption), tipo="imagen", nombre_usuario=nombre)
        await responder_con_voz_o_texto(update, respuesta)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    nombre = update.effective_user.first_name
    await update.message.chat.send_action("typing")
    doc = update.message.document
    doc_file = await context.bot.get_file(doc.file_id)
    caption = update.message.caption or ""
    ext = os.path.splitext(doc.file_name)[1] if doc.file_name else ".pdf"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp_path = tmp.name
            await doc_file.download_to_drive(tmp_path)
        respuesta = procesar_con_ia(user_id, (tmp_path, caption), tipo="documento", nombre_usuario=nombre)
        await responder_con_voz_o_texto(update, respuesta)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    nombre = update.effective_user.first_name
    await update.message.chat.send_action("typing")
    video = update.message.video
    video_file = await context.bot.get_file(video.file_id)
    caption = update.message.caption or ""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name
            await video_file.download_to_drive(tmp_path)
        respuesta = procesar_con_ia(user_id, (tmp_path, caption), tipo="video", nombre_usuario=nombre)
        await responder_con_voz_o_texto(update, respuesta)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


# --- CONFIGURACIÓN DE COMANDOS Y ARRANQUE ---
async def post_init(app):
    comandos = [
        BotCommand("aventura", "Jugar al RPG El Sueño de Vishnú"),
        BotCommand("perfil", "Ver tu Nivel y XP en el RPG"),
        BotCommand("avatar", "Cambiar entre Vishnú Cósmico y Comercial"),
        BotCommand("modo", "Cambiar respuesta entre Voz o Texto"),
        BotCommand("oraculo", "Recibir un consejo cósmico"),
        BotCommand("chats", "Ver lista de hilos de chat"),
        BotCommand("nuevo", "Crear un nuevo hilo de chat"),
        BotCommand("cambiar", "Cambiar al chat activo por ID"),
        BotCommand("borrar", "Eliminar un hilo de chat"),
        BotCommand("traductor", "Traducir texto a otro idioma"),
        BotCommand("recordar", "Guardar memoria persistente"),
        BotCommand("estado", "Ver estado del servidor"),
    ]
    await app.bot.set_my_commands(comandos)

def main():
    init_db()
    
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        logger.error("No se encontró TELEGRAM_TOKEN en las variables de entorno.")
        return
    
    application = ApplicationBuilder().token(token).post_init(post_init).build()
    
    # Handlers de Comandos
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
    
    # Callbacks y Multimedia
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.VIDEO, handle_video))
    
    logger.info("Iniciando servidor web y bot de Telegram con todas las capacidades activas...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
