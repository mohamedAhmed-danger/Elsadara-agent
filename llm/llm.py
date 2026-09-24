from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from config import Config


def get_gemini():
    api_key = Config.GEMINI_API_KEY

    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY or GOOGLE_API_KEY must be set."
        )

    return ChatGoogleGenerativeAI(
        model=Config.GEMINI_MODEL,
        google_api_key=api_key,
        temperature=0.0,
    )


def get_gemini_embeddings():
    api_key = Config.GEMINI_API_KEY

    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY or GOOGLE_API_KEY must be set."
        )

    return GoogleGenerativeAIEmbeddings(
        model=Config.EMBEDDING_MODEL,
        google_api_key=api_key,
        output_dimensionality=768,
    )