"""
Kodo AI — MVP Lead Response Server v2
Production-ready: SQLite + logging + rapport + CORS
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json, datetime, sqlite3, os, re, threading

DB_PATH = os.environ.get('KODO_DB', 'kodo_leads.db')

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''CREATE TABLE IF NOT EXISTS leads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT, nom TEXT, email TEXT, telephone TEXT,
        message TEXT, source TEXT, score INTEGER, type_bien TEXT,
        urgence TEXT, is_hot INTEGER, email_sent INTEGER DEFAULT 0
    )''')
    conn.commit()
    return conn

def qualify(lead):
    msg = lead.get('message', '').lower()
    score = 0
    if lead.get('telephone'): score += 2
    if len(lead.get('message', '')) > 50: score += 2
    if any(w in msg for w in ['acheter','cherch','vendre','budget','vente']): score += 2
    if any(w in msg for w in ['visiter','disponible','urgence','semaine']): score += 2
    if any(w in msg for w in ['chambres','jardin','parking','m2','etage']): score += 1
    score = min(score, 10)
    
    t = 'inconnu'
    if any(w in msg for w in ['appartement','t3','t2','t4','studio']): t = 'appartement'
    elif any(w in msg for w in ['maison','villa']): t = 'maison'
    elif 'terrain' in msg: t = 'terrain'
    
    return {
        'score': score, 'type_bien': t,
        'urgence': 'haute' if score >= 8 else ('moyenne' if score >= 5 else 'basse'),
        'is_hot': score >= 7
    }

def generate_email(lead, qual):
    nom = lead.get('nom', 'Client').split()[0]
    if qual['is_hot']:
        t = qual['type_bien']
        type_str = "d'une " + t if t != 'inconnu' else 'immobiliere'
        return (f"Bonjour {nom},\n\nMerci pour votre message ! "
                f"Votre recherche {type_str} est un projet que nous accompagnons regulierement.\n\n"
                f"Seriez-vous disponible pour un appel de 15 minutes cette semaine ?\n\n"
                f"Cordialement,\nL'equipe [Agence]\nAssiste par Kodo AI")
    else:
        return (f"Bonjour {nom},\n\nMerci de votre interet ! "
                f"Pourriez-vous me preciser :\n"
                f"1. Le type de bien recherche ?\n"
                f"2. Votre budget approximatif ?\n"
                f"3. Le secteur geographique souhaite ?\n\n"
                f"Cordialement,\nL'equipe [Agence]\nAssiste par Kodo AI")

def get_daily_report(conn):
    today = datetime.date.today().isoformat()
    week_ago = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    
    cur = conn.execute("SELECT * FROM leads WHERE timestamp >= ?", (week_ago,))
    leads = [dict(zip([d[0] for d in cur.description], row)) for row in cur.fetchall()]
    
    total = len(leads)
    if total == 0:
        return {"message": "Aucun lead cette semaine", "leads": 0}
    
    hot = sum(1 for l in leads if l['is_hot'])
    sources = {}
    types = {}
    for l in leads:
        sources[l['source']] = sources.get(l['source'], 0) + 1
        types[l['type_bien']] = types.get(l['type_bien'], 0) + 1
    
    return {
        "periode": f"{week_ago} a {today}",
        "total_leads": total,
        "leads_chauds": hot,
        "leads_tiedes": total - hot,
        "taux_chauds": f"{hot/total*100:.0f}%",
        "sources": sources,
        "types_biens": types,
        "top_leads": sorted(
            [{"nom": l['nom'], "score": l['score'], "type": l['type_bien']} for l in leads],
            key=lambda x: -x['score']
        )[:5]
    }

class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
    
    def _json_response(self, code, data):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self._cors()
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8'))
    
    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()
    
    def do_POST(self):
        if self.path == '/webhook/lead-intake':
            try:
                n = int(self.headers.get('Content-Length', 0))
                lead = json.loads(self.rfile.read(n))
                qual = qualify(lead)
                email = generate_email(lead, qual)
                
                conn = sqlite3.connect(DB_PATH)
                conn.execute(
                    "INSERT INTO leads (timestamp,nom,email,telephone,message,source,score,type_bien,urgence,is_hot) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (datetime.datetime.now().isoformat(), lead.get('nom',''), lead.get('email',''),
                     lead.get('telephone',''), lead.get('message',''), lead.get('source',''),
                     qual['score'], qual['type_bien'], qual['urgence'], int(qual['is_hot']))
                )
                conn.commit()
                lead_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                conn.close()
                
                self._json_response(200, {
                    'status': 'ok', 'lead_id': lead_id,
                    'qualification': qual,
                    'email_preview': email[:200],
                    'notification': f"Nouveau lead: {lead.get('nom','')} - Score {qual['score']}/10"
                })
            except Exception as e:
                self._json_response(500, {'status': 'error', 'message': str(e)})
            return
        self._json_response(404, {'error': 'not found'})
    
    def do_GET(self):
        if self.path == '/healthz':
            self._json_response(200, {'status': 'ok', 'service': 'kodo-ai-mvp-v2'})
        elif self.path == '/api/leads':
            conn = sqlite3.connect(DB_PATH)
            cur = conn.execute("SELECT * FROM leads ORDER BY id DESC LIMIT 50")
            leads = [dict(zip([d[0] for d in cur.description], row)) for row in cur.fetchall()]
            conn.close()
            self._json_response(200, leads)
        elif self.path == '/api/report':
            conn = sqlite3.connect(DB_PATH)
            report = get_daily_report(conn)
            conn.close()
            self._json_response(200, report)
        else:
            self._json_response(404, {'error': 'not found'})
    
    def log_message(self, fmt, *args):
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {args[0] if args else ''}")

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 8899))
    srv = HTTPServer(('0.0.0.0', port), Handler)
    print(f"Kodo AI MVP v2 on http://0.0.0.0:{port}")
    srv.serve_forever()
