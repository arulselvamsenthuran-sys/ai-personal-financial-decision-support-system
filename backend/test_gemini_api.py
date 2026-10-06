import asyncio
from app.core.config import settings
from app.services.llm.provider import GeminiProvider

async def test_gemini():
    provider = GeminiProvider()
    print(f"Using model: {provider.model_name}")
    try:
        response = await provider.generate(
            prompt="Hello, this is a test.",
            system_prompt="You are a helpful assistant.",
            temperature=0,
            max_tokens=10,
        )
        print("Success!")
        print("Response:", response)
    except Exception as e:
        print(f"Error: {type(e).__name__}")
        print(str(e))

if __name__ == "__main__":
    asyncio.run(test_gemini())
