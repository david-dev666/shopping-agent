from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""

    database_url: str = "sqlite:///./shopping_agent.db"

    # DEMO_MODE：无数据源时返回内置样例（显式标注，仅用于开箱预览）
    demo_mode: bool = False

    # Kimi 浏览器扩展 daemon（用户真实浏览器登录态采集）
    webbridge_enabled: bool = True
    webbridge_base_url: str = "http://127.0.0.1:10086"

    tavily_api_key: str = ""

    jd_union_app_key: str = ""
    jd_union_app_secret: str = ""

    tbk_app_key: str = ""
    tbk_app_secret: str = ""
    tbk_adzone_id: str = ""

    pdd_client_id: str = ""
    pdd_client_secret: str = ""
    pdd_pid: str = ""
    pdd_custom_parameters: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
