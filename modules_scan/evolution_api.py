from typing import Any, Dict, List, Tuple

import requests

from . import config
from .utils import build_url


def _pick_first(it: Dict[str, Any], keys: List[str]) -> Any:
    for k in keys:
        v = it.get(k)
        if v not in (None, ""):
            return v
    return None


def fetch_instances_from_api() -> List[Dict[str, Any]]:
    if not config.API_KEY:
        print("[ERRO] EVOLUTION_GLOBAL_KEY nao configurada.")
        return []

    try:
        url = build_url("/instance/fetchInstances")
        headers = {"apikey": config.API_KEY}
        resp = requests.get(url, headers=headers, verify=False, timeout=20)
        resp.raise_for_status()
        data = resp.json()

        if isinstance(data, dict):
            raw_list = data.get("instances")
            if isinstance(raw_list, list):
                instances = raw_list
            else:
                instances = next((v for v in data.values() if isinstance(v, list)), [])
        elif isinstance(data, list):
            instances = data
        else:
            instances = []

        out: List[Dict[str, Any]] = []
        for it in instances or []:
            item = it or {}
            name = _pick_first(item, ["name", "instanceName", "instance"])
            token = _pick_first(item, ["token", "apikey", "apiKey", "key"])
            number = _pick_first(item, ["number", "instance_number", "customer_number"])
            cstatus = _pick_first(item, ["connectionStatus", "connection_status", "status"]) or ""
            owner_jid = _pick_first(item, ["ownerJid", "owner_jid"]) or ""

            if not name or not token:
                continue

            out.append(
                {
                    "name": str(name),
                    "key": str(token),
                    "customer_number": str(number or ""),
                    "instance_number": str(number or ""),
                    "owner_jid": str(owner_jid or ""),
                    "connection_status": str(cstatus).lower(),
                }
            )

        return out

    except Exception as e:
        print(f"[ERRO] Falha ao buscar instancias na API: {e}")
        return []


def fetch_qr_code_status(instance_name: str, apikey: str) -> Dict[str, Any]:
    try:
        url = build_url(f"/instance/connect/{instance_name}")
        headers = {"apikey": apikey}
        rqs = requests.get(url, headers=headers, verify=False, timeout=10)
        rqs.raise_for_status()
        data = rqs.json()

        code = (
            data.get("code")
            or data.get("base64")
            or data.get("qrcode")
            or (data.get("qr") or {}).get("code")
            or (data.get("qrcode") or {}).get("code")
            or (data.get("qrcode") or {}).get("base64")
        )
        if code:
            return {"qrcode": code, "status": "qr_code"}

        state = str((data.get("instance") or {}).get("state", "")).lower()
        root_status = str(data.get("status", "")).lower()
        if state == "open" or root_status in ("open", "connected"):
            return {"qrcode": None, "status": "connected"}

        return {"qrcode": None, "status": "unknown", "raw": data}
    except Exception:
        return {
            "qrcode": None,
            "status": "error",
            "message": "Nao foi possivel obter o status do servidor.",
        }


def logout_instance(instance: str, apikey: str) -> Tuple[bool, Dict[str, Any]]:
    try:
        url = build_url(f"/instance/logout/{instance}")
        headers = {"apikey": apikey}
        r = requests.delete(url, headers=headers, verify=False, timeout=15)
        r.raise_for_status()
        try:
            return True, r.json()
        except Exception:
            return True, {"text": r.text}
    except Exception as e:
        return False, {"error": str(e)}
