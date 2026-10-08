import os
from google import genai
from google.genai import types

class Orchestrator:
    def __init__(self):
        self.client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
        self.model = 'gemini-3.8-flash'  # Actualizado aquí

    def procesar_solicitud(self, mensaje_usuario: str) -> dict:
        try:
            system_prompt = (
                "Eres el Orquestador Central de un sistema multiagente de IA. "
                "Analiza la petición del usuario y determina si requiere búsqueda en Internet (researcher) "
                "o si puede resolverse directamente con el secretario general (secretary)."
            )

            config = types.GenerateContentConfig(
                system_instruction=system_prompt,
                tools=[types.Tool(google_search=types.GoogleSearch())]
            )

            response = self.client.models.generate_content(
                model=self.model,
                contents=mensaje_usuario,
                config=config
            )

            return {
                "status": "success",
                "texto": response.text
            }
        except Exception as e:
            return {
                "status": "error",
                "texto": f"Error en el orquestador: {str(e)}"
            }
            
