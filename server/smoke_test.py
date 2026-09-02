import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI()

response = client.responses.create(
    model=os.environ.get("OPENAI_MODEL", "gpt-5.6"),
    input="Explain how AI works in a few words",
)

print(response.output_text)
