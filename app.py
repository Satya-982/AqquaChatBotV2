from flask import Flask, request, jsonify, render_template_string, send_from_directory
import os, json, math, datetime, requests
from openai import OpenAI

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = Flask(__name__)

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

if not OPENROUTER_API_KEY or OPENROUTER_API_KEY == "your_openrouter_api_key_here":
    print("ERROR: OPENROUTER_API_KEY missing or placeholder!")
    print("Create/update .env file in this folder with:")
    print("OPENROUTER_API_KEY=sk-or-your-real-key-here")
    # Allow starting for static checks or render environments initializing later

client = OpenAI(
    api_key=OPENROUTER_API_KEY or "dummy_key",
    base_url="https://openrouter.ai/api/v1",
    default_headers={"HTTP-Referer": "https://aquabot.app", "X-Title": "AquaBot"}
)
MODEL = "openrouter/auto"
MAX_STEPS = 5

SYSTEM_EN = """You are AquaBot, expert AI advisor for shrimp and fish farmers in Andhra Pradesh.
You know: Vannamei/tiger shrimp, diseases (WSSV, EMS, Vibriosis, EHP), water quality (pH, DO, ammonia, salinity), feeding/FCR, pond prep, harvest timing, market prices, govt schemes.
Use web_search for live prices/news. Use calculate for FCR/feed/profit math. Use get_date_time for seasonal advice.
Reply in English. Be practical and concise."""

SYSTEM_TE = """మీరు AquaBot, ఆంధ్రప్రదేశ్ రొయ్యలు మరియు చేపల రైతులకు నిపుణ AI సలహాదారు.
మీకు తెలుసు: వన్నమీ/టైగర్ రొయ్యలు, వ్యాధులు (WSSV, EMS, విబ్రియోసిస్), నీటి నాణ్యత (pH, DO, అమ్మోనియా), మేత/FCR, చెరువు తయారీ, పంట సమయం, మార్కెట్ ధరలు.
లైవ్ ధరలకు web_search వాడండి. లెక్కలకు calculate వాడండి.
తెలుగులో జవాబు ఇవ్వండి. స్పష్టంగా మరియు ఆచరణాత్మకంగా ఉండండి."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search internet for live shrimp prices, disease alerts, weather, govt schemes.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "Calculate FCR, feed quantity, stocking density, profit, harvest weight.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string"},
                    "label": {"type": "string"}
                },
                "required": ["expression"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_date_time",
            "description": "Get current date and seasonal farming advice for AP.",
            "parameters": {"type": "object", "properties": {}}
        }
    }
]

def web_search(query):
    try:
        r = requests.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
            timeout=10, headers={"User-Agent": "AquaBot/1.0"}
        )
        d = r.json()
        results = []
        if d.get("Abstract"):
            results.append(f"[{d.get('AbstractSource','Web')}] {d['Abstract']}")
        if d.get("Answer"):
            results.append(f"[Answer] {d['Answer']}")
        for t in d.get("RelatedTopics", [])[:3]:
            if isinstance(t, dict) and t.get("Text"):
                results.append(f"[Info] {t['Text'][:200]}")
        if results:
            return "\n".join(results)
    except Exception:
        pass
    try:
        import re
        html = requests.get(
            "https://lite.duckduckgo.com/lite/",
            params={"q": query}, timeout=10,
            headers={"User-Agent": "Mozilla/5.0"}
        ).text
        s = re.findall(r'class="result-snippet"[^>]*>(.*?)</td>', html, re.DOTALL)
        s = [re.sub(r'<[^>]+>', '', x).strip() for x in s if x.strip()]
        if s:
            return "\n".join(f"[{i+1}] {x}" for i, x in enumerate(s[:3]))
    except Exception:
        pass
    return f"No results for '{query}'."

def calculate(expression, label=""):
    allowed = {"math","sqrt","pi","e","log","sin","cos","tan",
               "ceil","floor","abs","pow","factorial","log10"}
    for tok in expression.replace("(", " ").replace(")", " ").split():
        t = tok.strip("0123456789+-*/().%,")
        if t and t not in allowed:
            return f"Error: '{t}' not allowed."
    try:
        result = eval(expression.strip(), {"__builtins__": {}}, {"math": math, "abs": abs})
        return f"{label}: {round(result, 3)}" if label else f"Result: {round(result, 3)}"
    except Exception as e:
        return f"Error: {e}"

def get_date_time():
    now = datetime.datetime.now()
    m = now.month
    if m in [11, 12, 1, 2]:
        season = "Winter - Best stocking season. Low disease risk."
    elif m in [3, 4, 5]:
        season = "Summer - HIGH ALERT. Monitor DO closely."
    elif m in [6, 7, 8, 9]:
        season = "Monsoon - Flood risk. Check pond bunds."
    else:
        season = "Post-monsoon - Good harvest season."
    return f"Date: {now.strftime('%A, %d %B %Y')} | Season: {season}"

def run_tool(name, args):
    if name == "web_search":    return web_search(args.get("query", ""))
    if name == "calculate":     return calculate(args.get("expression", ""), args.get("label", ""))
    if name == "get_date_time": return get_date_time()
    return f"Unknown tool: {name}"

def run_agent(question, history, lang="en"):
    if not OPENROUTER_API_KEY or OPENROUTER_API_KEY == "your_openrouter_api_key_here":
        return "API Key missing! Please configure OPENROUTER_API_KEY in server environment."
    
    system = SYSTEM_TE if lang == "te" else SYSTEM_EN
    messages = history + [{"role": "user", "content": question}]
    for _ in range(MAX_STEPS):
        response = client.chat.completions.create(
            model=MODEL, max_tokens=1500,
            tools=TOOLS, tool_choice="auto",
            messages=[{"role": "system", "content": system}] + messages,
        )
        msg = response.choices[0].message
        if not msg.tool_calls:
            return msg.content
        messages.append({
            "role": "assistant", "content": msg.content or "",
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ]
        })
        for tc in msg.tool_calls:
            try:    args = json.loads(tc.function.arguments)
            except: args = {}
            result = run_tool(tc.function.name, args)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
    return "Max steps reached. Please try again."

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<title>AquaBot - Aquaculture AI Advisor</title>
<link rel="manifest" href="/manifest.json">
<meta name="theme-color" content="#0d9488">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="apple-mobile-web-app-title" content="AquaBot">
<link rel="apple-touch-icon" href="/static/icon-192.png">
<link rel="icon" type="image/png" sizes="192x192" href="/static/icon-192.png">
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+Telugu:wght@400;600&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{--teal:#0d9488;--teal-dark:#0f766e;--teal-light:#ccfbf1;--text:#1e293b;--muted:#64748b;--border:#e2e8f0}
body{font-family:'Inter',sans-serif;background:#f0fdfa;min-height:100vh;display:flex;flex-direction:column}
.header{background:linear-gradient(135deg,#0f766e,#0d9488);padding:14px 16px;display:flex;align-items:center;gap:12px;position:sticky;top:0;z-index:10;box-shadow:0 2px 8px rgba(0,0,0,0.15)}
.header-icon{width:44px;height:44px;background:rgba(255,255,255,0.2);border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:22px}
.header-text h1{color:#fff;font-size:17px;font-weight:600}
.header-text p{color:rgba(255,255,255,0.8);font-size:12px;margin-top:1px}
.lang-toggle{margin-left:auto;display:flex;background:rgba(255,255,255,0.15);border-radius:20px;padding:3px}
.lang-btn{border:none;background:transparent;color:rgba(255,255,255,0.7);font-size:12px;font-weight:500;padding:5px 12px;border-radius:16px;cursor:pointer;transition:all .2s;font-family:'Inter',sans-serif}
.lang-btn.active{background:#fff;color:var(--teal-dark)}
.chat-area{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:12px;padding-bottom:140px}
.msg{display:flex;gap:8px;animation:fadeUp .2s ease}
@keyframes fadeUp{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
.msg.user{flex-direction:row-reverse}
.avatar{width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:15px;flex-shrink:0;margin-top:2px}
.avatar.bot{background:var(--teal-light)}
.avatar.user{background:var(--teal)}
.bubble{padding:10px 14px;border-radius:16px;max-width:82%;font-size:14px;line-height:1.6;word-break:break-word}
.bubble.bot{background:#fff;color:var(--text);border-bottom-left-radius:4px;box-shadow:0 1px 3px rgba(0,0,0,0.08)}
.bubble.user{background:var(--teal);color:#fff;border-bottom-right-radius:4px}
.bubble.te{font-family:'Noto Sans Telugu','Inter',sans-serif;font-size:15px;line-height:1.9}
.thinking{display:flex;gap:4px;padding:12px 14px;background:#fff;border-radius:16px;border-bottom-left-radius:4px;width:fit-content;box-shadow:0 1px 3px rgba(0,0,0,0.08)}
.dot{width:7px;height:7px;background:var(--teal);border-radius:50%;animation:bounce .9s infinite}
.dot:nth-child(2){animation-delay:.15s}
.dot:nth-child(3){animation-delay:.3s}
@keyframes bounce{0%,60%,100%{transform:translateY(0)}30%{transform:translateY(-6px)}}
.suggestions{padding:0 16px 8px;display:flex;gap:8px;overflow-x:auto;scrollbar-width:none}
.suggestions::-webkit-scrollbar{display:none}
.chip{border:1.5px solid var(--teal);color:var(--teal);background:#fff;border-radius:20px;padding:6px 14px;font-size:12px;white-space:nowrap;cursor:pointer;font-family:'Inter',sans-serif;transition:all .15s}
.chip:hover{background:var(--teal);color:#fff}
.chip.te{font-family:'Noto Sans Telugu','Inter',sans-serif;font-size:13px}
.input-area{position:fixed;bottom:0;left:0;right:0;background:#fff;border-top:1px solid var(--border);padding:10px 12px;display:flex;gap:8px;align-items:flex-end}
#msg-input{flex:1;border:1.5px solid var(--border);border-radius:22px;padding:10px 16px;font-size:14px;outline:none;resize:none;max-height:100px;font-family:'Inter',sans-serif;line-height:1.5;transition:border-color .2s}
#msg-input.te{font-family:'Noto Sans Telugu','Inter',sans-serif;font-size:15px}
#msg-input:focus{border-color:var(--teal)}
#send-btn{width:44px;height:44px;background:var(--teal);border:none;border-radius:50%;color:#fff;font-size:20px;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:background .2s}
#send-btn:hover{background:var(--teal-dark)}
#send-btn:disabled{background:#94a3b8;cursor:not-allowed}
.welcome{background:#fff;border-radius:16px;padding:18px;margin-bottom:4px;box-shadow:0 1px 3px rgba(0,0,0,0.08);text-align:center}
.welcome h2{color:var(--teal-dark);font-size:16px;margin-bottom:6px}
.welcome p{color:var(--muted);font-size:13px;line-height:1.5}
.wave{font-size:28px;margin-bottom:8px}
</style>
</head>
<body>
<!-- PWA Install Bar -->
<div id="install-bar" style="display:none;background:#0f766e;padding:10px 16px;align-items:center;justify-content:space-between;gap:12px">
  <span style="color:#fff;font-size:13px">&#x1F4F1; Install AquaBot on your phone!</span>
  <button onclick="installApp()" style="background:#fff;color:#0f766e;border:none;border-radius:16px;padding:6px 16px;font-size:12px;font-weight:600;cursor:pointer">Install</button>
  <button onclick="document.getElementById("install-bar").style.display="none"" style="background:transparent;border:none;color:rgba(255,255,255,0.7);font-size:18px;cursor:pointer">&#x2715;</button>
</div>
<div class="header">
  <div class="header-icon">&#x1F990;</div>
  <div class="header-text">
    <h1>AquaBot</h1>
    <p>Shrimp &amp; Fish Farming Advisor</p>
  </div>
  <div class="lang-toggle">
    <button class="lang-btn active" id="btn-en" onclick="setLang('en')">EN</button>
    <button class="lang-btn" id="btn-te" onclick="setLang('te')">&#x0C24;&#x0C46;</button>
  </div>
</div>

<div class="chat-area" id="chat">
  <div class="welcome">
    <div class="wave">&#x1F30A;</div>
    <h2>Welcome to AquaBot!</h2>
    <p>Your AI advisor for shrimp and fish farming in Andhra Pradesh.<br>Ask me anything in Telugu or English.</p>
  </div>
</div>

<div class="suggestions" id="chips">
  <button class="chip" onclick="sendChip(this.innerText)">White spot disease?</button>
  <button class="chip" onclick="sendChip(this.innerText)">Vannamei price today?</button>
  <button class="chip" onclick="sendChip(this.innerText)">Ideal pH for shrimp?</button>
  <button class="chip" onclick="sendChip(this.innerText)">FCR calculation help</button>
  <button class="chip" onclick="sendChip(this.innerText)">Best harvest time?</button>
</div>

<div class="input-area">
  <textarea id="msg-input" placeholder="Ask about shrimp farming..." rows="1"></textarea>
  <button id="send-btn" onclick="sendMessage()">&#x27A4;</button>
</div>

<script>
let lang = 'en';
let history = [];
const chat = document.getElementById('chat');
const input = document.getElementById('msg-input');
const sendBtn = document.getElementById('send-btn');

const chips = {
  en: ['White spot disease?','Vannamei price today?','Ideal pH for shrimp?','FCR calculation help','Best harvest time?','Stocking density 1 acre?'],
  te: ['\u0C24\u0C46\u0C32\u0C4D\u0C32 \u0C2E\u0C1A\u0C4D\u0C1A \u0C35\u0C4D\u0C2F\u0C3E\u0C27\u0C3F?','\u0C28\u0C47\u0C21\u0C41 \u0C35\u0C28\u0C4D\u0C28\u0C2E\u0C40 \u0C27\u0C30?','\u0C30\u0C4A\u0C2F\u0C4D\u0C2F\u0C32\u0C15\u0C41 pH \u0C0E\u0C02\u0C24?','FCR \u0C32\u0C46\u0C15\u0C4D\u0C15 \u0C1A\u0C46\u0C2A\u0C4D\u0C2A\u0C02\u0C21\u0C3F','\u0C2A\u0C02\u0C1F \u0C38\u0C2E\u0C2F\u0C02 \u0C0E\u0C2A\u0C4D\u0C2A\u0C41\u0C21\u0C41?','1 \u0C0E\u0C15\u0C30\u0C3E\u0C15\u0C41 \u0C38\u0C4D\u0C1F\u0C3E\u0C15\u0C3F\u0C02\u0C17?']
};

function setLang(l) {
  lang = l;
  document.getElementById('btn-en').classList.toggle('active', l === 'en');
  document.getElementById('btn-te').classList.toggle('active', l === 'te');
  input.className = l === 'te' ? 'te' : '';
  input.placeholder = l === 'te' ? '\u0C30\u0C4A\u0C2F\u0C4D\u0C2F\u0C32 \u0C38\u0C3E\u0C17\u0C41 \u0C17\u0C41\u0C30\u0C3F\u0C02\u0C1A\u0C3F \u0C05\u0C21\u0C17\u0C02\u0C21\u0C3F...' : 'Ask about shrimp farming...';
  const chipsEl = document.getElementById('chips');
  chipsEl.innerHTML = chips[l].map(c => '<button class="chip' + (l==='te'?' te':'') + '" onclick="sendChip(this.innerText)">' + c + '</button>').join('');
}

function addMsg(text, role) {
  const isTE = lang === 'te';
  const div = document.createElement('div');
  div.className = 'msg ' + role;
  const formatted = text
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/\n/g,'<br>')
    .replace(/\*\*(.*?)\*\*/g,'<strong>$1</strong>')
    .replace(/\*(.*?)\*/g,'<em>$1</em>')
    .replace(/###\s*(.*)/g,'<strong>$1</strong>');
  div.innerHTML = '<div class="avatar ' + role + '">' + (role==='bot'?'&#x1F990;':'&#x1F464;') + '</div><div class="bubble ' + role + (isTE?' te':'') + '">' + formatted + '</div>';
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

function showThinking() {
  const div = document.createElement('div');
  div.className = 'msg bot'; div.id = 'thinking';
  div.innerHTML = '<div class="avatar bot">&#x1F990;</div><div class="thinking"><div class="dot"></div><div class="dot"></div><div class="dot"></div></div>';
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

function hideThinking() {
  const t = document.getElementById('thinking');
  if (t) t.remove();
}

async function sendMessage() {
  const text = input.value.trim();
  if (!text || sendBtn.disabled) return;
  input.value = '';
  input.style.height = 'auto';
  addMsg(text, 'user');
  sendBtn.disabled = true;
  showThinking();
  try {
    const res = await fetch('/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message: text, history: history, lang: lang})
    });
    const data = await res.json();
    hideThinking();
    if (data.reply) {
      addMsg(data.reply, 'bot');
      history.push({role:'user', content:text});
      history.push({role:'assistant', content:data.reply});
      if (history.length > 20) history = history.slice(-20);
    } else {
      addMsg('Error: ' + (data.error || 'Something went wrong'), 'bot');
    }
  } catch(e) {
    hideThinking();
    addMsg('Connection error. Please try again.', 'bot');
  }
  sendBtn.disabled = false;
  input.focus();
}

function sendChip(text) { input.value = text; sendMessage(); }

input.addEventListener('keydown', function(e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});

input.addEventListener('input', function() {
  this.style.height = 'auto';
  this.style.height = Math.min(this.scrollHeight, 100) + 'px';
});

// ── PWA Service Worker Registration ──────────────
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js')
      .then(reg => console.log('[AquaBot] SW registered:', reg.scope))
      .catch(err => console.log('[AquaBot] SW failed:', err));
  });
}

// ── PWA Install Prompt ────────────────────────────
let deferredPrompt;
window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  deferredPrompt = e;
  document.getElementById('install-bar').style.display = 'flex';
});

function installApp() {
  if (deferredPrompt) {
    deferredPrompt.prompt();
    deferredPrompt.userChoice.then(result => {
      document.getElementById('install-bar').style.display = 'none';
      deferredPrompt = null;
    });
  }
}
</script>
</body>
</html>"""

@app.route('/')
def index():
    return render_template_string(HTML)

@app.route('/chat', methods=['POST'])
def chat_endpoint():
    data = request.json
    message  = data.get('message', '')
    history  = data.get('history', [])
    lang     = data.get('lang', 'en')
    try:
        reply = run_agent(message, history, lang)
        return jsonify({"reply": reply})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/manifest.json')
def manifest():
    return send_from_directory('static', 'manifest.json', mimetype='application/manifest+json')

@app.route('/sw.js')
def service_worker():
    return send_from_directory('.', 'sw.js', mimetype='application/javascript')

@app.route('/offline')
def offline():
    return render_template_string("""<!DOCTYPE html>
<html><head><meta charset=UTF-8><meta name=viewport content='width=device-width,initial-scale=1'>
<title>AquaBot - Offline</title>
<style>body{font-family:Inter,sans-serif;background:#f0fdfa;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}
.box{text-align:center;padding:2rem;background:#fff;border-radius:16px;box-shadow:0 2px 12px rgba(0,0,0,.1);max-width:320px}
h2{color:#0f766e}p{color:#64748b;font-size:14px}
.btn{background:#0d9488;color:#fff;border:none;border-radius:8px;padding:10px 24px;cursor:pointer;font-size:14px;margin-top:1rem}</style>
</head><body><div class=box>
<div style=font-size:48px>🦐</div>
<h2>You're Offline</h2>
<p>Internet connection లేదు.<br>Connection వచ్చిన తర్వాత మళ్ళీ try చేయండి.</p>
<button class=btn onclick=location.reload()>Try Again</button>
</div></body></html>""")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"\n  AquaBot running at http://localhost:{port}\n  Open this in your browser!\n")
    app.run(debug=False, host='0.0.0.0', port=port)