import os
from google import genai
from google.genai import types

class Orchestrator:
    def __init__(self):
        self.client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
        self.model = 'gemini-2.5-flash'

    def procesar_solicitud(self, mensaje_usuario: str) -> dict:
        """
        Analiza la petición y decide si requiere búsqueda web, respuesta general o síntesis de voz.
        """
        try:
            # Instrucción maestra de enrutamiento
            system_prompt = (
                "Eres el Orquestador Central de un sistema multiagente de IA. "
                "Analiza la petición del usuario y determina si requiere búsqueda en Internet (researcher) "
                "o si puede resolverse directamente con el secretario general (secretary). "
                "Devuelve una respuesta estructurada o procesa con la herramienta adecuada."
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
            
