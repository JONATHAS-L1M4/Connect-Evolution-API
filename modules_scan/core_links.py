# core_links.py (versão focada em EasyPanel)
import os
import time
import json
import secrets
from typing import Tuple, Optional, Dict, Any

from dotenv import load_dotenv
import redis
from redis.exceptions import RedisError

load_dotenv()

BASE_URL = os.getenv("BASE_URL", "").rstrip("/")

# padrão para Docker/EasyPanel: serviço chama "redis"
PRIMARY_REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

# opcional: você pode pôr no painel: REDIS_FALLBACK_URLS=redis://localhost:6379/0
FALLBACK_URLS = os.getenv("REDIS_FALLBACK_URLS", "")

_REDIS: Optional[redis.Redis] = None


def _candidate_redis_urls() -> list[str]:
    urls = [PRIMARY_REDIS_URL]

    if FALLBACK_URLS:
        for u in FALLBACK_URLS.split(","):
            u = u.strip()
            if u:
                urls.append(u)

    # alguns comuns, caso o .env esteja errado
    commons = [
        "redis://redis:6379/0",
        "redis://localhost:6379/0",
    ]
    for c in commons:
        if c not in urls:
            urls.append(c)

    return urls


def _build_client(url: str) -> redis.Redis:
    return redis.Redis.from_url(
        url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=3,
        retry_on_timeout=True,
    )


def get_redis(retries: int = 3, delay: float = 1.5) -> redis.Redis:
    global _REDIS
    if _REDIS is not None:
        return _REDIS

    last_exc: Optional[Exception] = None
    urls = _candidate_redis_urls()
    print(f"[REDIS] tentando URLs: {urls}")

    for url in urls:
        for attempt in range(1, retries + 1):
            try:
                client = _build_client(url)
                client.ping()
                _REDIS = client
                print(f"[REDIS] conectado em {url} (tentativa {attempt}).")
                return _REDIS
            except Exception as exc:
                last_exc = exc
                print(f"[WARN] Falha ao conectar em {url} (tentativa {attempt}/{retries}): {exc}")
                time.sleep(delay)

    raise RuntimeError(f"Não foi possível conectar ao Redis: {last_exc}")


def safe_redis() -> Optional[redis.Redis]:
    try:
        return get_redis()
    except Exception as exc:
        print(f"[WARN] Redis indisponível: {exc}")
        return None


def _now() -> int:
    return int(time.time())


def _key_token(tok: str) -> str:
    return f"token:{tok}"


def _key_connect_active(instance: str) -> str:
    return f"connect_active:{instance}"


def init_db():
    r = safe_redis()
    if r is None:
        print("[WARN] Redis indisponível no init_db(); seguindo.")
    else:
        # <<< AQUI entra o que você pediu
        if os.getenv("REDIS_FLUSH_ON_START") == "1":
            try:
                r.flushall()
                print("[INFO] Redis limpo porque REDIS_FLUSH_ON_START=1.")
            except RedisError as exc:
                print(f"[WARN] Não consegui dar FLUSHALL no Redis: {exc}")
        print("[INFO] Conexão com Redis OK.")


def _row_to_payload_from_hash(h: Dict[str, str]) -> Dict[str, Any]:
    exp_str = h.get("expires_at")
    one_time_str = h.get("one_time", "0")
    used_at_str = h.get("used_at")

    raw_payload = h.get("payload") or "{}"
    try:
        payload_json = json.loads(raw_payload)
    except json.JSONDecodeError:
        payload_json = {}

    return {
        "expires_at": int(exp_str) if exp_str else 0,
        "payload": payload_json,
        "one_time": bool(int(one_time_str) if one_time_str else 0),
        "used_at": int(used_at_str) if (used_at_str and used_at_str.isdigit()) else None,
    }


def _get_active_token_for_instance(instance: str) -> Optional[str]:
    r = safe_redis()
    if r is None:
        return None

    try:
        tok = r.get(_key_connect_active(instance))
        if not tok:
            return None

        if not r.exists(_key_token(tok)):
            r.delete(_key_connect_active(instance))
            return None

        h = r.hgetall(_key_token(tok))
        if not h:
            r.delete(_key_connect_active(instance))
            return None

        data = _row_to_payload_from_hash(h)
        pl = data["payload"] or {}
        if pl.get("page") != "connect" or pl.get("instance") != instance:
            r.delete(_key_connect_active(instance))
            return None

        return tok
    except RedisError:
        return None


def create_token(ttl_seconds: int, payload: Dict[str, Any], one_time: bool = False) -> Optional[str]:
    r = safe_redis()
    if r is None:
        return None

    try:
        token = secrets.token_urlsafe(16)
        expires_at = _now() + int(ttl_seconds)
        key = _key_token(token)

        with r.pipeline(transaction=True) as p:
            p.hset(key, mapping={
                "expires_at": str(expires_at),
                "payload": json.dumps(payload or {}, ensure_ascii=False),
                "one_time": "1" if one_time else "0",
                "used_at": ""
            })
            p.expire(key, int(ttl_seconds))
            p.execute()

        return token
    except RedisError as exc:
        print(f"[ERROR] create_token: {exc}")
        return None


def build_link(token: str) -> str:
    """
    Monta o link que será enviado ao cliente.
    Ajuste: garantir que haja uma barra antes do querystring (?t=...),
    pois o domínio pode não ter path definido e alguns clientes reclamaram
    do formato sem "/?t=...".
    """
    if not BASE_URL:
        return f"/?t={token}"

    base = BASE_URL
    if not base.endswith("/"):
        base += "/"
    return f"{base}?t={token}"


def get_or_create_connect_link(instance: str, apikey: str, ttl_seconds: int = 8 * 60 * 60) -> Tuple[str, str, bool]:
    r = safe_redis()
    if r is None:
        return "", "", False

    existing = _get_active_token_for_instance(instance)
    if existing:
        return existing, build_link(existing), False

    payload = {"page": "connect", "instance": instance, "apikey": apikey}
    tok = create_token(ttl_seconds, payload, one_time=False)
    if not tok:
        return "", "", False

    key_active = _key_connect_active(instance)
    try:
        ok = r.set(key_active, tok, ex=int(ttl_seconds), nx=True)
    except RedisError as exc:
        print(f"[ERROR] get_or_create_connect_link.set: {exc}")
        return "", "", False

    if ok:
        return tok, build_link(tok), True

    existing = _get_active_token_for_instance(instance)
    if existing:
        r.delete(_key_token(tok))
        return existing, build_link(existing), False

    r.set(key_active, tok, ex=int(ttl_seconds))
    return tok, build_link(tok), True


def validate_token(token: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    r = safe_redis()
    if r is None:
        return False, "Redis indisponível.", None

    try:
        key = _key_token(token)
        if not r.exists(key):
            return False, "Token inválido ou não encontrado.", None

        h = r.hgetall(key)
        data = _row_to_payload_from_hash(h)
        return True, "OK", data["payload"]
    except RedisError as exc:
        print(f"[ERROR] validate_token: {exc}")
        return False, "Erro ao validar token.", None


def shorten_after_connected(token: str, seconds: int = 30):
    r = safe_redis()
    if r is None:
        return

    try:
        key = _key_token(token)
        if not r.exists(key):
            return

        new_ttl = max(5, int(seconds))
        r.expire(key, new_ttl)
        r.hset(key, "expires_at", str(_now() + new_ttl))

        h = r.hgetall(key)
        if h:
            data = _row_to_payload_from_hash(h)
            pl = data["payload"] or {}
            if pl.get("page") == "connect" and pl.get("instance"):
                r.expire(_key_connect_active(pl["instance"]), new_ttl)
    except RedisError:
        pass


def cleanup_orphan_links(valid_instances: list[str]):
    r = safe_redis()
    if r is None:
        print("[WARN] cleanup_orphan_links: Redis indisponível, nada a limpar.")
        return

    # connect_active:*
    try:
        for key in r.scan_iter("connect_active:*"):
            instance_name = key.split(":")[-1]
            if instance_name not in valid_instances:
                r.delete(key)
                print(f"[CLEANUP] Link órfão removido do Redis: {instance_name}")
    except RedisError as exc:
        print(f"[ERROR] cleanup_orphan_links (connect_active): {exc}")

    # token:*
    try:
        for key in r.scan_iter("token:*"):
            data = r.hgetall(key)
            if not data:
                r.delete(key)
                print(f"[CLEANUP] Token vazio removido: {key}")
                continue

            payload = data.get("payload")
            if payload:
                try:
                    payload_json = json.loads(payload)
                    instance_name = payload_json.get("instance")
                    if instance_name not in valid_instances:
                        r.delete(key)
                        print(f"[CLEANUP] Token de instância inválida removido: {key}")
                except json.JSONDecodeError:
                    r.delete(key)
                    print(f"[CLEANUP] Token inválido (payload corrompido) removido: {key}")
            else:
                r.delete(key)
                print(f"[CLEANUP] Token sem payload removido: {key}")
    except RedisError as exc:
        print(f"[ERROR] cleanup_orphan_links (token:*): {exc}")
