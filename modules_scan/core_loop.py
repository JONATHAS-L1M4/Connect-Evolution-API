from time import sleep
from typing import Any, Dict

from .core_links import cleanup_orphan_links, get_or_create_connect_link, init_db
from .evolution_api import fetch_instances_from_api, fetch_qr_code_status, logout_instance
from .messaging import send_text_admin_to_client
from .utils import normalize_number, number_from_owner_jid


def main_loop():
    init_db()
    print("[SCANNER] Scanner iniciado com sucesso.")

    while True:
        print("[SCANNER] Efetuando varredura das instancias...")
        instances = fetch_instances_from_api()
        instance_names = [item.get("name") for item in instances if item.get("name")]

        if not instances:
            print("[INFO] Nenhuma instancia retornada pela API. Aguardando...")

        cleanup_orphan_links(instance_names)
        next_sleep = 60

        for item in instances:
            instance = item.get("name")
            apikey = item.get("key")

            instance_number = normalize_number(item.get("instance_number") or item.get("customer_number"))
            owner_jid_number = normalize_number(number_from_owner_jid(item.get("owner_jid") or ""))
            conn_status_hint = str(item.get("connection_status") or "").lower()

            if not instance or not apikey:
                print(f"[WARN] Registro invalido vindo da API: instance='{instance}', key presente? {bool(apikey)}")
                continue

            status: Dict[str, Any] = fetch_qr_code_status(instance, apikey)
            s = status.get("status")

            if s == "qr_code":
                client_number = instance_number
                token, link, created = get_or_create_connect_link(instance, apikey, ttl_seconds=4 * 60 * 60)

                # Important: failure to create token/link is not "already exists".
                if not token or not link:
                    print(f"[ERRO] instance={instance}: falha ao criar/recuperar link (verifique REDIS_URL).")
                    continue

                if created:
                    if not client_number:
                        print(f"[WARN] instance={instance}: numero ausente; nao e possivel enviar o link.")
                    else:
                        ok, resp = send_text_admin_to_client(client_number, link)
                        if ok:
                            print(f"[OK] Link enviado p/ {client_number} (instance={instance})")
                        else:
                            print(f"[ERRO] Envio p/ {client_number} (instance={instance}) -> {resp}")
                else:
                    print(f"[INFO] instance={instance}: link ja existe/recente; nada a enviar agora.")
                continue

            if s == "connected" or conn_status_hint in ("open", "connected"):
                if owner_jid_number and instance_number and owner_jid_number != instance_number:
                    print(
                        f"[WARN] instance={instance}: divergencia "
                        f"(ownerJid={owner_jid_number} != cadastro={instance_number}). Efetuando logout..."
                    )
                    ok, resp = logout_instance(instance, apikey)
                    if ok:
                        print(f"[OK] instance={instance}: logout realizado. Detalhe: {resp}")
                        get_or_create_connect_link(instance, apikey, ttl_seconds=4 * 60 * 60)
                    else:
                        print(f"[ERRO] instance={instance}: falha no logout -> {resp}")
                else:
                    print(f"[OK] instance={instance}: conectada e sem divergencia.")
                continue

            if s == "unknown":
                print(f"[INFO] instance={instance}: status desconhecido -> {status.get('raw')}")
            elif s == "error":
                print(f"[ERRO] instance={instance}: {status.get('message')}")
            else:
                if conn_status_hint == "connecting":
                    print(f"[INFO] instance={instance}: connecting, aguardando QR...")
                    next_sleep = min(next_sleep, 15)
                else:
                    print(f"[INFO] instance={instance}: nao conectada (hint='{conn_status_hint}').")

        sleep(next_sleep)
