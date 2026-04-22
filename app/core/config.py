from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "GameVeredito"
    VERSION: str = "2.0.0"

    # Required — no default. Missing .env raises ValidationError at startup.
    GEMINI_API_KEY: str

    # Optional — get a free key at isthereanydeal.com/dev/app/
    # Without it, historical low price is silently skipped.
    ITAD_API_KEY: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
