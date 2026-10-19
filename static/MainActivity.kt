package com.vishnu.flotante

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.view.Gravity
import android.view.ViewGroup
import android.widget.*
import android.graphics.Color
import android.graphics.Typeface
import android.text.InputType
import androidx.core.app.ActivityCompat
import java.net.HttpURLConnection
import java.net.URL
import java.io.OutputStreamWriter
import org.json.JSONObject
import kotlin.concurrent.thread

class MainActivity : Activity() {
    private lateinit var status: TextView
    private lateinit var endpoint: EditText
    private lateinit var token: EditText
    private lateinit var message: EditText
    private lateinit var transcript: TextView
    private lateinit var tts: android.speech.tts.TextToSpeech
    private val prefs by lazy { getSharedPreferences("vishnu", MODE_PRIVATE) }
    private val reqMic = 202

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        tts = android.speech.tts.TextToSpeech(this) { tts.setLanguage(java.util.Locale("es", "CO")) }

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(24, 28, 24, 24)
            setBackgroundColor(Color.rgb(4, 8, 24))
        }
        fun label(text: String, size: Float = 16f) = TextView(this).apply {
            this.text = text; textSize = size; setTextColor(Color.rgb(226, 232, 255))
            setPadding(0, 8, 0, 8)
        }
        root.addView(label("VISHNÚ • ESFERA HOLOGRÁFICA", 22f).apply { setTypeface(null, Typeface.BOLD) })
        root.addView(label("Servidor HTTPS de Flask"))
        endpoint = EditText(this).apply {
            hint = "https://tu-servicio.onrender.com"
            setSingleLine(true); setTextColor(Color.WHITE); setHintTextColor(Color.GRAY)
            setText(prefs.getString("endpoint", "https://vishnu-telegram.onrender.com"))
        }
        root.addView(endpoint, LinearLayout.LayoutParams(-1, ViewGroup.LayoutParams.WRAP_CONTENT))
        root.addView(label("Token de acceso del endpoint"))
        token = EditText(this).apply {
            hint = "Token VISHNU_MOBILE_TOKEN"; inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
            setSingleLine(true); setTextColor(Color.WHITE); setHintTextColor(Color.GRAY)
            setText(prefs.getString("token", ""))
        }
        root.addView(token, LinearLayout.LayoutParams(-1, ViewGroup.LayoutParams.WRAP_CONTENT))
        val save = Button(this).apply { text = "Guardar conexión" }
        root.addView(save)
        status = label("Estado: configura el servidor y el token.")
        root.addView(status)
        val activate = Button(this).apply { text = "Activar esfera flotante" }
        root.addView(activate)
        val openChat = Button(this).apply { text = "Abrir chat de Vishnú" }
        root.addView(openChat)
        root.addView(label("Conversación de prueba"))
        transcript = label("Vishnú: Saludos, viajero.")
        root.addView(ScrollView(this).apply { addView(transcript) }, LinearLayout.LayoutParams(-1, 0, 1f))
        message = EditText(this).apply {
            hint = "Escribe a Vishnú…"; setTextColor(Color.WHITE); setHintTextColor(Color.GRAY)
        }
        root.addView(message)
        val actions = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        actions.addView(Button(this).apply {
            text = "Enviar"
            setOnClickListener { sendMessage(message.text.toString()) }
        }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        actions.addView(Button(this).apply {
            text = "🎙 Dictar"
            setOnClickListener { startDictation() }
        }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        root.addView(actions)
        setContentView(root)

        save.setOnClickListener {
            val base = endpoint.text.toString().trim().trimEnd('/')
            if (!base.startsWith("https://")) {
                status.text = "Usa una URL HTTPS válida."
                return@setOnClickListener
            }
            prefs.edit().putString("endpoint", base).putString("token", token.text.toString().trim()).apply()
            status.text = "Conexión guardada en este teléfono."
        }
        activate.setOnClickListener {
            if (!Settings.canDrawOverlays(this)) {
                startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName")))
                status.text = "Autoriza “Mostrar sobre otras aplicaciones” y vuelve aquí."
            } else {
                startService(Intent(this, BubbleService::class.java))
                status.text = "Esfera activada. Puedes cambiar de aplicación."
            }
        }
        openChat.setOnClickListener { showChat() }
        if (intent.getBooleanExtra("open_chat", false)) showChat()
    }

    private fun showChat() {
        // La actividad ya contiene el panel de conversación.
        runOnUiThread { if (!isFinishing) window.decorView.requestFocus() }
    }

    private fun startDictation() {
        if (ActivityCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.RECORD_AUDIO), reqMic)
            return
        }
        if (!SpeechRecognizer.isRecognitionAvailable(this)) {
            status.text = "No hay servicio de reconocimiento de voz disponible."
            return
        }
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, "es-CO")
            putExtra(RecognizerIntent.EXTRA_PROMPT, "Habla con Vishnú")
        }
        try { startActivityForResult(intent, reqMic) }
        catch (_: Exception) { status.text = "No se pudo iniciar el reconocimiento de voz." }
    }

    @Deprecated("Compatibilidad con el selector de voz del sistema")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == reqMic && resultCode == RESULT_OK) {
            val spoken = data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull()
            if (!spoken.isNullOrBlank()) { message.setText(spoken); sendMessage(spoken) }
        }
    }

    private fun sendMessage(text: String) {
        val msg = text.trim()
        if (msg.isEmpty()) return
        val base = endpoint.text.toString().trim().trimEnd('/')
        val secret = token.text.toString().trim()
        if (!base.startsWith("https://") || secret.isEmpty()) {
            status.text = "Guarda una URL HTTPS y el token del servidor."
            return
        }
        transcript.append("\n\nTú: $msg\nVishnú: pensando…")
        message.setText("")
        status.text = "Conectando con el santuario…"
        thread {
            var conn: HttpURLConnection? = null
            try {
                conn = (URL("$base/api/mobile/chat").openConnection() as HttpURLConnection).apply {
                    requestMethod = "POST"
                    connectTimeout = 15000
                    readTimeout = 60000
                    doOutput = true
                    setRequestProperty("Content-Type", "application/json; charset=utf-8")
                    setRequestProperty("Authorization", "Bearer $secret")
                }
                val body = JSONObject().put("message", msg).toString()
                OutputStreamWriter(conn.outputStream, Charsets.UTF_8).use { it.write(body) }
                val code = conn.responseCode
                val stream = if (code in 200..299) conn.inputStream else conn.errorStream
                val result = stream.bufferedReader(Charsets.UTF_8).use { it.readText() }
                val json = JSONObject(result)
                if (code !in 200..299) throw Exception(json.optString("error", "HTTP $code"))
                val reply = json.optString("reply", "No llegó respuesta.")
                runOnUiThread {
                    transcript.append("\n$reply")
                    status.text = "Conectado."
                    tts.speak(reply, android.speech.tts.TextToSpeech.QUEUE_FLUSH, null, "vishnu-reply")
                }
            } catch (e: Exception) {
                runOnUiThread { status.text = "Error de conexión: ${e.message ?: "sin detalle"}" }
            } finally { conn?.disconnect() }
        }
    }

    override fun onDestroy() {
        if (::tts.isInitialized) { tts.stop(); tts.shutdown() }
        super.onDestroy()
    }
}
