from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application Configuration.
    Loads variables from environment or uses default values.
    """

    # General Info
    PROJECT_NAME: str = "GameVeredito"
    VERSION: str = "1.3.0"

    # API Configuration
    # 'GEMINI_API_KEY' is required (no default value).
    # If missing in .env, the application will raise a validation error at startup.
    GEMINI_API_KEY: str = "CHAVE_DE_TESTE_NAO_FUNCIONA"
    CHEAPSHARK_API_URL: str = "https://www.cheapshark.com/api/1.0"

    # Pydantic Configuration to read .env file
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
