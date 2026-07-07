import requests
requests.packages.urllib3.disable_warnings()   # ignore le warning TLS

KC     = "https://keycloak.mirecloud.com/auth/realms/mirecloud/protocol/openid-connect/token"
RAG    = "https://rag.mirecloud.com/query"
SECRET = "9PSxICBfVfMbjRhl1qAPM9QQhS9OUwdR"

def token(user, pwd):
    r = requests.post(KC, data={
        "grant_type": "password", "client_id": "openwebui", "client_secret": SECRET,
        "username": user, "password": pwd}, verify=False)
    r.raise_for_status()
    return r.json()["access_token"]

def ask(user, pwd, question):
    tok = token(user, pwd)
    r = requests.post(RAG, headers={"Authorization": f"Bearer {tok}"},
                      json={"question": question}, verify=False)   # json= gère les guillemets
    print(f"\n{'='*60}\n### {user}  (HTTP {r.status_code})")
    try:
        data = r.json()
        print("RÉPONSE :", data.get("answer"))
        print("GROUPES :", data.get("groups"))
        print("SOURCES :", [s.get("document_id") for s in data.get("sources", [])])
    except Exception:
        print(r.text)

if __name__ == "__main__":
    q = "Quel est le code d'autorisation des virements ?"
    ask("user-finance", "mirecloud", q)   # doit trouver FIN-9x7Q-2026
    ask("user-rh",      "mirecloud", q)   # ne doit RIEN trouver de finance