import hashlib


def md5_sign(secret: str, params: dict[str, str]) -> str:
    """淘宝客 / 京东联盟 / 多多进宝通用的签名规则。

    md5(secret + 按 key 排序拼接的 k1v1k2v2... + secret) 转大写。
    注意：调用方需先把 sign 本身排除在 params 之外。
    """
    plain = secret + "".join(f"{k}{v}" for k, v in sorted(params.items())) + secret
    return hashlib.md5(plain.encode("utf-8")).hexdigest().upper()


def raise_on_error_response(body: dict, platform: str) -> None:
    """三大联盟 API 报错时都返回 error_response 字段，统一在这里抛错。"""
    if "error_response" in body:
        raise RuntimeError(f"{platform} API error: {body['error_response']}")
