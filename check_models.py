from pathlib import Path
from dotenv import load_dotenv
import os

# Force-load .env from project root
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

print("DEBUG: ENV PATH =", env_path)
print("DEBUG: GEMINI KEY (first 5 chars) =", str(os.getenv("GEMINI_API_KEY"))[:5])

import google.generativeai as genai
import os

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

print("Available models:")
for m in genai.list_models():
    print(m.name)