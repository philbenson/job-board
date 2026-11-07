from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration from the environment, then from a .env file in the working directory.

    The database URL carries a password, so it is a secret: its repr, str and
    serialized forms are masked, and only ``get_secret_value()`` reveals it.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: SecretStr
