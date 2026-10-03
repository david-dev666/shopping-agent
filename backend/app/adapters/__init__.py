from app.adapters.base import PlatformAdapter
from app.adapters.jd import JDUnionAdapter
from app.adapters.pdd import PddAdapter
from app.adapters.registry import get_adapters, search_all
from app.adapters.taobao import TaobaoAdapter

__all__ = [
    "PlatformAdapter",
    "JDUnionAdapter",
    "PddAdapter",
    "TaobaoAdapter",
    "get_adapters",
    "search_all",
]
