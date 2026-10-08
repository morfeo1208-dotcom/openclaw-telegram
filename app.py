import os
import logging
from flask import Flask, render_template_string, request, jsonify
from google import genai
from google.genai import types

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY)

# Interfaz HTML sencilla y moderna integrada directamente
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Secretario Personal IA</title>
    <style>
        body { font-family: Arial, sans-serif; background: #0f172a; color: #f8fafc; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
        .chat-container { width: 100%; max-width: 500px; background: #1e293b; padding: 20px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.5); display: flex; flex-direction: column; height: 80vh; }
        .chat-box { flex: 1; overflow-y: auto; padding: 10px; border-bottom: 1px solid #334155; margin-bottom: 10px; display: flex; flex-direction: column; gap: 10px; }
        .message { padding: 10px 14px; border-radius: 8px; max-width: 80%; line-height: 1.4; }
        .user { background: #3b82f6; align-self: flex-end; }
        .assistant { background: #334155; align-self: flex-start; }
        .input-area { display: flex; gap: 10px; }
        input { flex: 1; padding: 10px; border-radius: 6px; border: 1px solid #475569; background: #0f172a; color: white; }
        button { padding: 10px 20px; background: #10b981; border: none; border-radius: 6px; color: white; font-weight: bold; cursor: pointer; }
        button:hover { background: #059669; }
    </style>
</head>
<body>
    <div class="chat-container">
        <h2>Secretario IA </h2>
        <div class="chat-box" id="chatBox"></div>
        <div class="input-area">
            <input type="text" id="userInput" placeholder="Escribe tu solicitud..." onkeypress="if(event.key === 'Enter') sendMessage()">
            <button onclick="sendMessage()">Enviar</button>
        </div>
    </div>

    <script>
        async function sendMessage() {
            const input = document.getElementById('userInput');
            const chatBox = document.getElementById('chatBox');
            const text = input.value.trim();
            if (!text) return;

            chatBox.innerHTML += `<div class="message user">${text}</div>`;
            input.value = '';
            chatBox.scrollTop = chatBox.scrollHeight;

            const response = await fetch('/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: text })
            });
            const data = await response.json();

            chatBox.innerHTML += `<div class="message assistant">${data.reply}</div>`;
            chatBox.scrollTop = chatBox.scrollHeight;
        }
    </script>
</body>
</html>
"""

@app.route('/')
index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/chat', methods=['POST'])
def chat():
    user_message = request.json.get('message', '')
    try:
        configuracion = types.GenerateContentConfig(
            system_instruction="Eres el secretario y asistente personal. Responde de forma concisa y eficiente.",
            tools=[types.Tool(google_search=types.GoogleSearch())]
        )
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=user_message,
            config=configuracion
        )
        return jsonify({'reply': response.text})
    except Exception as e:
        return jsonify({'reply': 'Disculpa, ocurrió un error procesando tu solicitud.'})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
