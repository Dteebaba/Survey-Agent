from dotenv import load_dotenv
import os

load_dotenv()

print("Key:", os.getenv("GEMINI_API_KEY"))