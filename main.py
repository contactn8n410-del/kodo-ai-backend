"""
Kōdō AI — MVP Lead Response Server v3
VRAIE IA : appel LLM pour qualification + réponse personnalisée
Supporte : Ollama (local), Groq (cloud free), Anthropic (cloud paid)
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json, datetime, sqlite3, os, re, threading, urllib.request, time

DB_PATH = os.environ.get('KODO_DB', 'kodo_leads.db')
LLM_BACKEND = os.environ.get('LLM_BACKEND', 'ollama')  # ollama | groq | anthropic
LLM_MODEL = os.environ.get('LLM_MODEL', 'qwen2.5:7b')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
OLLAMA_URL = os.environ.get('OLLAMA_URL', 'http://localhost:11434')

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''CREATE TABLE IF NOT EXISTS leads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT, nom TEXT, email TEXT, telephone TEXT,
        message TEXT, source TEXT, 
        score INTEGER, type_bien TEXT, urgence TEXT, is_hot INTEGER,
        ai_analysis TEXT, ai_response TEXT, ai_model TEXT, ai_latency_ms INTEGER,
        email_sent INTEGER DEFAULT 0
    )''')
    conn.commit()
    return conn

QUALIFICATION_TEMPLATE = """Tu es un assistant de qualification de leads pour une agence immobilière à La Réunion.

Analyse ce message d'un prospect et retourne un JSON strict (pas de texte avant/après) :

{{"score": <0-10>, "type_bien": "<appartement|maison|terrain|local_commercial|autre|inconnu>", "budget": "<montant ou inconnu>", "zone": "<ville/quartier ou inconnu>", "urgence": "<haute|moyenne|basse>", "intention": "<achat|vente|location|estimation|autre>", "points_cles": ["point1", "point2"], "is_hot": <true|false>}}

Critères de scoring :
- Téléphone fourni : +2
- Message détaillé (>50 mots) : +2  
- Mentionne budget : +2
- Mentionne zone précise : +1
- Mentionne délai/urgence : +2
- Mentionne critères précis (chambres, surface, etc.) : +1

Message du prospect :
Nom: {nom}
Email: {email}
Téléphone: {telephone}
Message: {message}
Source: {source}
"""

RESPONSE_PROMPT = """Tu es l'assistant commercial de l'agence. Rédige une réponse email courte (max 5 phrases), chaleureuse et professionnelle, à ce prospect.

Contexte qualification :
- Score: {score}/10
- Type de bien: {type_bien}
- Zone: {zone}
- Intention: {intention}
- Points clés: {points_cles}

Prospect : {nom}
Message original : {message}

Règles :
- Tutoiement interdit, vouvoyer
- Mentionner ce que le prospect cherche spécifiquement
- Proposer un appel de 15 minutes
- Si score >= 7 : ton enthousiaste, proposer RDV cette semaine
- Si score 4-6 : ton professionnel, demander plus d'infos
- Si score < 4 : ton poli, accusé de réception
- Signer "L'équipe [NOM_AGENCE]"
"""

def call_llm(prompt, backend=None, model=None):
    """Appelle le LLM configuré. Retourne (response_text, latency_ms, model_used)"""
    backend = backend or LLM_BACKEND
    model = model or LLM_MODEL
    start = time.time()
    
    if backend == 'ollama':
        return _call_ollama(prompt, model, start)
    elif backend == 'groq':
        return _call_groq(prompt, model, start)
    elif backend == 'anthropic':
        return _call_anthropic(prompt, model, start)
    else:
        raise ValueError(f"Unknown backend: {backend}")

def _call_ollama(prompt, model, start):
    data = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.3, "num_predict": 500}
    }).encode()
    req = urllib.request.Request(f"{OLLAMA_URL}/api/generate", data=data,
                                 headers={"Content-Type": "application/json"})
    resp = urllib.request.urlopen(req, timeout=30)
    result = json.loads(resp.read())
    latency = int((time.time() - start) * 1000)
    return result.get('response', ''), latency, model

def _call_groq(prompt, model, start):
    import subprocess
    model = model or 'llama-3.1-8b-instant'
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 500
    })
    proc = subprocess.run([
        'curl', '-s', 'https://api.groq.com/openai/v1/chat/completions',
        '-H', 'Content-Type: application/json',
        '-H', f'Authorization: Bearer {GROQ_API_KEY}',
        '-d', payload
    ], capture_output=True, text=True, timeout=15)
    result = json.loads(proc.stdout)
    latency = int((time.time() - start) * 1000)
    text = result['choices'][0]['message']['content']
    return text, latency, model

def _call_anthropic(prompt, model, start):
    model = model or 'claude-3-haiku-20240307'
    data = json.dumps({
        "model": model,
        "max_tokens": 500,
        "messages": [{"role": "user", "content": prompt}]
    }).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages",
                                 data=data,
                                 headers={"Content-Type": "application/json",
                                          "x-api-key": ANTHROPIC_API_KEY,
                                          "anthropic-version": "2023-06-01"})
    resp = urllib.request.urlopen(req, timeout=15)
    result = json.loads(resp.read())
    latency = int((time.time() - start) * 1000)
    text = result['content'][0]['text']
    return text, latency, model

def qualify_with_ai(lead):
    """Qualification par IA réelle"""
    prompt = QUALIFICATION_TEMPLATE.format(**lead)
    try:
        raw, latency, model = call_llm(prompt)
        # Extraire le JSON de la réponse
        json_match = re.search(r'\{[^{}]*\}', raw, re.DOTALL)
        if json_match:
            analysis = json.loads(json_match.group())
            return analysis, raw, latency, model
        else:
            return None, raw, latency, model
    except Exception as e:
        return None, str(e), 0, "error"

def generate_response(lead, qualification):
    """Génère une réponse personnalisée par IA"""
    prompt = RESPONSE_PROMPT.format(
        score=qualification.get('score', 0),
        type_bien=qualification.get('type_bien', 'inconnu'),
        zone=qualification.get('zone', 'inconnu'),
        intention=qualification.get('intention', 'inconnu'),
        points_cles=', '.join(qualification.get('points_cles', [])),
        nom=lead.get('nom', ''),
        message=lead.get('message', '')
    )
    try:
        text, latency, model = call_llm(prompt)
        return text.strip(), latency
    except Exception as e:
        return f"[Erreur génération: {e}]", 0

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass
    
    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
    
    def _json_response(self, code, data):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self._cors()
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False, indent=2).encode())
    
    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()
    
    def do_POST(self):
        if self.path == '/webhook/lead-intake':
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length))
            lead = {
                'nom': body.get('nom', ''),
                'email': body.get('email', ''),
                'telephone': body.get('telephone', ''),
                'message': body.get('message', ''),
                'source': body.get('source', 'direct')
            }
            
            # 1. Qualification par IA
            analysis, raw_ai, qual_latency, model = qualify_with_ai(lead)
            
            if analysis:
                score = min(max(int(analysis.get('score', 0)), 0), 10)
                type_bien = analysis.get('type_bien', 'inconnu')
                urgence = analysis.get('urgence', 'basse')
                is_hot = 1 if analysis.get('is_hot', False) else 0
            else:
                # Fallback si IA échoue
                score = 0
                type_bien = 'inconnu'
                urgence = 'basse'
                is_hot = 0
                analysis = {"error": "AI qualification failed", "raw": raw_ai[:200]}
            
            # 2. Génération réponse personnalisée
            ai_response, resp_latency = generate_response(lead, analysis or {})
            total_latency = qual_latency + resp_latency
            
            # 3. Stockage SQLite
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute('''INSERT INTO leads 
                (timestamp, nom, email, telephone, message, source, 
                 score, type_bien, urgence, is_hot, ai_analysis, ai_response, ai_model, ai_latency_ms)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (datetime.datetime.now().isoformat(), lead['nom'], lead['email'],
                 lead['telephone'], lead['message'], lead['source'],
                 score, type_bien, urgence, is_hot,
                 json.dumps(analysis, ensure_ascii=False), ai_response, model, total_latency))
            lead_id = cur.lastrowid
            conn.commit()
            conn.close()
            
            self._json_response(200, {
                "status": "ok",
                "lead_id": lead_id,
                "qualification": {
                    "score": score,
                    "type_bien": type_bien,
                    "urgence": urgence,
                    "is_hot": bool(is_hot),
                    "analysis": analysis
                },
                "ai_response": ai_response,
                "ai_model": model,
                "latency_ms": total_latency,
                "notification": f"{'🔥' if is_hot else '📩'} Lead: {lead['nom']} - Score {score}/10"
            })
        else:
            self._json_response(404, {"error": "not found"})
    
    def do_GET(self):
        if self.path == '/healthz':
            self._json_response(200, {
                "status": "ok",
                "service": "kodo-ai-mvp-v3",
                "llm_backend": LLM_BACKEND,
                "llm_model": LLM_MODEL
            })
        elif self.path == '/api/leads':
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            rows = conn.execute('SELECT * FROM leads ORDER BY id DESC LIMIT 50').fetchall()
            conn.close()
            self._json_response(200, [dict(r) for r in rows])
        elif self.path == '/api/report':
            conn = sqlite3.connect(DB_PATH)
            today = datetime.date.today().isoformat()
            total = conn.execute('SELECT COUNT(*) FROM leads WHERE timestamp LIKE ?', (today+'%',)).fetchone()[0]
            hot = conn.execute('SELECT COUNT(*) FROM leads WHERE timestamp LIKE ? AND is_hot=1', (today+'%',)).fetchone()[0]
            avg_score = conn.execute('SELECT AVG(score) FROM leads WHERE timestamp LIKE ?', (today+'%',)).fetchone()[0]
            avg_latency = conn.execute('SELECT AVG(ai_latency_ms) FROM leads WHERE timestamp LIKE ?', (today+'%',)).fetchone()[0]
            conn.close()
            self._json_response(200, {
                "date": today,
                "total_leads": total,
                "hot_leads": hot,
                "avg_score": round(avg_score, 1) if avg_score else 0,
                "avg_ai_latency_ms": round(avg_latency) if avg_latency else 0,
                "llm_backend": LLM_BACKEND
            })
        else:
            self._json_response(404, {"error": "not found"})

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 8899))
    srv = HTTPServer(('0.0.0.0', port), Handler)
    print(f"Kōdō AI MVP v3 ({LLM_BACKEND}/{LLM_MODEL}) on http://0.0.0.0:{port}")
    srv.serve_forever()
