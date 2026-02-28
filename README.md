# Kōdō AI — MVP Backend

Serveur de qualification automatique de leads pour agences immobilières.

## Endpoints
- `POST /webhook/lead-intake` — Recevoir et qualifier un lead
- `GET /api/leads` — Lister les leads traités
- `GET /api/report` — Rapport quotidien
- `GET /healthz` — Health check

## Déploiement
```bash
docker build -t kodo-ai .
docker run -p 8080:8080 kodo-ai
```
