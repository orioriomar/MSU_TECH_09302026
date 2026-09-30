"""This file is the heart of the app. It runs the web server, stores everything in the
database, runs the weekly AI checks, creates issue tickets, and feeds the dashboard.

No endpoint edits a real website or contacts anyone; people approve every public change.
"""
from __future__ import annotations
import csv, io, json, os, re, sqlite3, threading, uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
import requests
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / '.env')

from ai import (generate_questions, extract_claims, AIError, OLLAMA_MODEL, OLLAMA_URL, AI_PROVIDER, GEMINI_MODEL,
                friendly_error, is_quota_error)
from models import (AnswerSubmission, ExtractedClaim, ClaimBatch, QuestionGenerateRequest,
                    NewQuestion, TicketDecision)
from verifier import verify, suggested_action

BASE=Path(__file__).resolve().parent
DB=Path(os.getenv('PROOF_FLOWER_DB', str(BASE/'proof_flower.sqlite3')))
LOCK=threading.RLock()
app=FastAPI(title='Proof Flower — AI Mystery Shopper',version='0.2.0')
from fastapi.staticfiles import StaticFiles
app.mount('/static', StaticFiles(directory=str(BASE/'static')), name='static')  # logo, icons, pages


def timestamp():
    """This returns the current date and time (UTC) so every record is time-stamped."""
    return datetime.now(timezone.utc).isoformat(timespec='seconds')
@contextmanager
def conn():
    """This opens the SQLite database, saves changes if the work succeeds, and undoes them if it fails."""
    DB.parent.mkdir(parents=True, exist_ok=True)
    c=sqlite3.connect(DB,timeout=15,check_same_thread=False)
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally: c.close()

def rows(c,query,args=()):
    """This runs a database query and returns the results as a list of dictionaries."""
    return [dict(r) for r in c.execute(query,args).fetchall()]

def init_db():
    """This creates the database tables the first time the app starts (facts, questions, answers,
    claims, tickets, audit log, weekly checks) and loads the original bakery starter data.
    """
    with LOCK,conn() as c:
        c.executescript('''
            CREATE TABLE IF NOT EXISTS facts (
                fact_id TEXT PRIMARY KEY, business_id TEXT NOT NULL, business_name TEXT NOT NULL,
                product_id TEXT NOT NULL, product_name TEXT NOT NULL, field TEXT NOT NULL,
                value TEXT NOT NULL, context TEXT NOT NULL DEFAULT '', source_url TEXT NOT NULL DEFAULT '',
                checked_at TEXT NOT NULL DEFAULT '', approved INTEGER NOT NULL DEFAULT 0,
                is_demo INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS questions (
                id TEXT PRIMARY KEY, business_id TEXT NOT NULL, type TEXT NOT NULL,
                text TEXT NOT NULL, product_id TEXT NOT NULL DEFAULT '',
                target_field TEXT NOT NULL DEFAULT '', context TEXT NOT NULL DEFAULT '',
                origin TEXT NOT NULL DEFAULT 'manual');
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, question_id TEXT NOT NULL,
                business_id TEXT NOT NULL, answer TEXT NOT NULL, citations TEXT NOT NULL,
                mode TEXT NOT NULL, extraction TEXT NOT NULL, extraction_status TEXT NOT NULL,
                extraction_note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS claims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,run_id INTEGER NOT NULL,product_id TEXT NOT NULL,
                field TEXT NOT NULL,value TEXT NOT NULL,context TEXT NOT NULL,quote TEXT NOT NULL,
                verdict TEXT NOT NULL, reason TEXT NOT NULL, expected TEXT NOT NULL DEFAULT '',
                fact_id TEXT NOT NULL DEFAULT '', FOREIGN KEY(run_id) REFERENCES runs(id));
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,business_id TEXT NOT NULL,product_id TEXT NOT NULL,
                product_name TEXT NOT NULL,field TEXT NOT NULL,context TEXT NOT NULL,ai_value TEXT NOT NULL,
                verified_value TEXT NOT NULL, fact_id TEXT NOT NULL,source_url TEXT NOT NULL,
                title TEXT NOT NULL,proposal TEXT NOT NULL,priority TEXT NOT NULL DEFAULT 'review',
                status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                first_run_id INTEGER NOT NULL,last_run_id INTEGER NOT NULL,occurrences INTEGER NOT NULL DEFAULT 1,
                reviewer_note TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS eval_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, business_id TEXT NOT NULL, label TEXT NOT NULL,
                mode TEXT NOT NULL, eval_version TEXT NOT NULL, synthetic INTEGER NOT NULL DEFAULT 0,
                scores TEXT NOT NULL, results TEXT NOT NULL, created_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'done');
            CREATE TABLE IF NOT EXISTS businesses (
                business_id TEXT PRIMARY KEY, business_name TEXT NOT NULL, location TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '', website TEXT NOT NULL DEFAULT '', signals TEXT NOT NULL DEFAULT '{}',
                eval_version TEXT NOT NULL DEFAULT '', synthetic INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,ticket_id INTEGER NOT NULL,
                action TEXT NOT NULL,note TEXT NOT NULL,created_at TEXT NOT NULL);
        ''')
        try:  # older databases: add the status column if it's missing
            c.execute("ALTER TABLE eval_runs ADD COLUMN status TEXT NOT NULL DEFAULT 'done'")
        except sqlite3.OperationalError:
            pass
        if c.execute('SELECT COUNT(*) FROM facts').fetchone()[0]==0:
            with (BASE/'data/demo_catalog.csv').open(newline='',encoding='utf-8-sig') as f:
                insert_csv_rows(c,list(csv.DictReader(f)),seed=True)
        if c.execute('SELECT COUNT(*) FROM questions').fetchone()[0]==0:
            for q in json.loads((BASE/'data/demo_questions.json').read_text()):
                c.execute('INSERT INTO questions VALUES (?,?,?,?,?,?,?,?)',
                    (q['id'],'juniper_bakery',q['type'],q['text'],q['product_id'],q['target_field'],q['context'],'starter'))

EXPECTED_CSV=('fact_id','business_id','business_name','product_id','product_name','field','value',
              'context','source_url','checked_at','approved','is_demo')
VALID_FIELDS={'price_usd','availability','address','hours','policy'}
SAFE_ID=re.compile(r'^[a-z0-9_]{1,40}$')

def insert_csv_rows(c,items,seed=False,allow_demo=False):
    """This reads rows from a business's fact spreadsheet (CSV), checks every row is valid, and saves
    them. A real fact can only be marked approved if it has an official https link and a checked date.
    """
    if not items: raise ValueError('CSV contains no data rows.')
    clean=[]
    for i,row in enumerate(items,2):
        missing=[k for k in EXPECTED_CSV if k not in row]
        if missing:raise ValueError('Missing CSV columns: '+', '.join(missing))
        entry={k:(row.get(k) or '').strip() for k in EXPECTED_CSV}
        for k in ('fact_id','business_id','business_name','product_id','product_name','field','value'):
            if not entry[k]:raise ValueError(f'Row {i}: {k} is required.')
        if entry['field'] not in VALID_FIELDS:raise ValueError(f'Row {i}: unknown field {entry["field"]}')
        if not SAFE_ID.match(entry['business_id']):
            raise ValueError(f'Row {i}: business_id must use only lowercase letters, numbers and underscores (e.g. my_cafe).')
        approved=entry['approved'].lower() in ('yes','true','1')
        is_demo=entry['is_demo'].lower() in ('yes','true','1')
        if not seed and not allow_demo and is_demo:
            raise ValueError('Do not import a real business with is_demo=yes.')
        if approved and not is_demo:
            u=urlparse(entry['source_url'])
            if u.scheme!='https' or not u.hostname or not entry['checked_at']:
                raise ValueError(f'Row {i}: approved real facts need an HTTPS source URL and checked_at date.')
        clean.append((entry['fact_id'], entry['business_id'],entry['business_name'],entry['product_id'],
            entry['product_name'],entry['field'],entry['value'],entry['context'],entry['source_url'],
            entry['checked_at'],int(approved),int(is_demo)))
    for x in clean:
        c.execute('''INSERT INTO facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(fact_id) DO UPDATE SET business_id=excluded.business_id,
            business_name=excluded.business_name, product_id=excluded.product_id,
            product_name=excluded.product_name,field=excluded.field,value=excluded.value,
            context=excluded.context,source_url=excluded.source_url,checked_at=excluded.checked_at,
            approved=excluded.approved,is_demo=excluded.is_demo''',x)
    return len(clean)

init_db()

@app.get('/')
def home():
    """This serves the owner dashboard (the home page)."""
    return FileResponse(BASE/'static/audit.html')

@app.get('/console')
def console():
    """This serves the older analyst console at /console for technical users and judges."""
    return FileResponse(BASE/'static/index.html')

@app.get('/api/status')
def status():
    """This reports which AI provider is set up (shown in the analyst console sidebar)."""
    try:
        resp=requests.get(f'{OLLAMA_URL.rstrip("/")}/api/tags',timeout=1.5)
        ollama=resp.ok
        installed=[m.get('name','') for m in resp.json().get('models',[])] if resp.ok else []
    except Exception: ollama=False;installed=[]
    return {'ai_provider':AI_PROVIDER,'gemini_configured':bool(os.getenv('GEMINI_API_KEY')),
            'gemini_model':GEMINI_MODEL,'ollama_available':ollama,
            'ollama_model':OLLAMA_MODEL,'installed_models':installed,
            'openai_available':bool(os.getenv('OPENAI_API_KEY')),
            'note':'Configured means a key is present; live Gemini API access must still be tested.'}

@app.get('/api/facts')
def facts():
    """This returns every business fact in the database, plus the list of businesses."""
    with conn() as c:
        items=rows(c,'SELECT * FROM facts ORDER BY business_name,product_name,field,context')
    return {'facts':items,'businesses':list({f['business_id']:f['business_name'] for f in items}.items())}

class CatalogCSV(BaseModel):
    """This is the shape of an uploaded fact spreadsheet: the raw CSV text."""
    csv_text:str=Field(min_length=20,max_length=250000)
@app.post('/api/catalog/import')
def import_catalog(payload: CatalogCSV):
    """This imports a business's fact spreadsheet uploaded from the analyst console."""
    try:
        table=list(csv.DictReader(io.StringIO(payload.csv_text)))
        with LOCK,conn() as c:
            n=insert_csv_rows(c,table)
        return {'imported':n,'note':'Rows with approved=no remain draft; the app never treats them as verified.'}
    except (ValueError,csv.Error) as exc: raise HTTPException(422,str(exc)) from exc

@app.get('/api/questions')
def questions():
    """This returns every question stored in the database."""
    with conn() as c:return rows(c,'SELECT * FROM questions ORDER BY id')

@app.post('/api/questions')
def add_question(payload: NewQuestion):
    """This adds one question written by hand in the analyst console."""
    with LOCK,conn() as c:
        if not c.execute('SELECT 1 FROM facts WHERE business_id=? LIMIT 1',(payload.business_id,)).fetchone():
            raise HTTPException(404,'Business not found; import its catalog first.')
        qid='M'+uuid.uuid4().hex[:9].upper()
        c.execute('INSERT INTO questions VALUES(?,?,?,?,?,?,?,?)',
            (qid,payload.business_id,payload.type,payload.text,payload.product_id,payload.target_field,payload.context,'manual'))
    return {'id':qid}

@app.post('/api/questions/generate')
def generated_questions(payload: QuestionGenerateRequest):
    """This asks Gemini to suggest new shopper questions from a business's approved facts,
    and skips any question that duplicates one we already have.
    """
    counts={'visibility':payload.visibility,'accuracy':payload.accuracy,'stress':payload.stress}
    if not sum(counts.values()):raise HTTPException(422,'Ask for at least one question.')
    with conn() as c:
        ff=rows(c,'SELECT * FROM facts WHERE business_id=?',(payload.business_id,))
    if not ff:raise HTTPException(404,'Import business facts before generating questions.')
    brand=ff[0]['business_name']
    try: batch=generate_questions(brand,ff,counts)
    except AIError as exc: raise HTTPException(503,str(exc)) from exc
    created=[]; skipped=0
    norm=lambda t: re.sub(r'[^a-z0-9 ]','',t.lower()).strip()
    with LOCK,conn() as c:
        existing={norm(r['text']) for r in rows(c,'SELECT text FROM questions WHERE business_id=?',(payload.business_id,))}
        for item in batch.questions:
            if norm(item.text) in existing:
                skipped+=1; continue
            existing.add(norm(item.text))
            qid='G'+uuid.uuid4().hex[:9].upper()
            c.execute('INSERT INTO questions VALUES (?,?,?,?,?,?,?,?)',
                      (qid,payload.business_id,item.type,item.text,item.product_id,item.target_field,item.context,AI_PROVIDER))
            created.append({'id':qid,**item.model_dump()})
    return {'questions':created,'requested':counts,'actual':len(created),'duplicates_skipped':skipped,
            'note':f'{AI_PROVIDER} draft questions; review them before collecting answers.'}

@app.put('/api/questions/{question_id}')
def update_question(question_id:str,payload:NewQuestion):
    """This edits an existing question."""
    with LOCK,conn() as c:
        existing=c.execute('SELECT * FROM questions WHERE id=?',(question_id,)).fetchone()
        if not existing:raise HTTPException(404,'Question not found.')
        if c.execute('SELECT 1 FROM runs WHERE question_id=? LIMIT 1',(question_id,)).fetchone():
            raise HTTPException(409,'This question already has answers and must remain unchanged for an honest audit trail.')
        if not c.execute('SELECT 1 FROM facts WHERE business_id=? LIMIT 1',(payload.business_id,)).fetchone():
            raise HTTPException(404,'Business not found; import its catalog first.')
        c.execute('''UPDATE questions SET business_id=?,type=?,text=?,product_id=?,
                 target_field=?,context=?,origin=? WHERE id=?''',
                 (payload.business_id,payload.type,payload.text,payload.product_id,
                  payload.target_field,payload.context,'reviewed_question',question_id))
    return {'updated':question_id}

@app.delete('/api/questions/{question_id}')
def delete_question(question_id:str):
    """This deletes a question, unless saved answers already depend on it."""
    with LOCK,conn() as c:
        exists=c.execute('SELECT 1 FROM runs WHERE question_id=? LIMIT 1',(question_id,)).fetchone()
        if exists:raise HTTPException(409,'Question already has answers; preserve the audit trail.')
        c.execute('DELETE FROM questions WHERE id=?',(question_id,))
    return {'deleted':question_id}


def severity_for(product_id:str, field:str)->str:
    """This decides how serious a wrong fact is: Critical if AI says the business is closed,
    High for a wrong price, hours, address or policy, Medium for an item's availability.
    """
    if product_id=='business' and field=='availability': return 'critical'   # e.g. "permanently closed"
    if field in ('price_usd','policy','hours','address'): return 'high'
    if field=='availability': return 'medium'
    return 'low'

def get_question(c,qid):
    """This looks up one question by its ID, or returns a 'not found' error."""
    q=c.execute('SELECT * FROM questions WHERE id=?',(qid,)).fetchone()
    if not q:raise HTTPException(404,'Question ID not found.')
    return dict(q)

def process_answer(qid:str,answer:str,citations:list[str],mode:str,
                   extraction:str, manual_claims:list[dict]|None=None):
    """This is the core pipeline for ONE AI answer. It saves the answer, pulls out its factual claims
    (with Gemini, or from hand-written labels), checks each claim against the approved facts,
    opens or updates a ticket for every wrong claim, and marks an approved ticket as fixed
    when a later answer gets that fact right.
    """
    with conn() as c:
        q=get_question(c,qid)
        allfacts=rows(c,'SELECT * FROM facts WHERE business_id=?',(q['business_id'],))
    brand=allfacts[0]['business_name'] if allfacts else q['business_id']
    try:
        if extraction in ('ai','ollama'):
            batch=extract_claims(answer,q,brand,allfacts)
            extracted=[p.model_dump() for p in batch.claims]
        else:
            extracted=[ExtractedClaim.model_validate(cl).model_dump() for cl in (manual_claims or [])]
            for cl in extracted:
                if re.sub(r'\s+',' ',cl['quote']).strip() not in re.sub(r'\s+',' ',answer).strip():
                    raise ValueError('The claim quote must be an exact substring of the answer.')
                if (cl['product_id'],cl['field']) not in {(f['product_id'],f['field']) for f in allfacts}:
                    raise ValueError('The claim must match a known catalog product and field.')
        extraction_status='complete';extract_note=''
    except Exception as exc:
        # Save the raw real answer, but never make tickets when extraction fails.
        extracted=[];extraction_status='failed'
        extract_note=(str(exc) if isinstance(exc,ValueError) else friendly_error(exc))[:300]
    tickets_created=[]; tickets_updated=[]; verdicts=[]; verified_retests=[]
    with LOCK,conn() as c:
        cursor=c.execute('''INSERT INTO runs(question_id,business_id,answer,citations,mode,extraction,extraction_status,extraction_note,created_at)
                        VALUES (?,?,?,?,?,?,?,?,?)''',
                 (qid,q['business_id'],answer,json.dumps(citations),mode,extraction,extraction_status,extract_note,timestamp()))
        run_id=cursor.lastrowid
        for cl in extracted:
            # Use the original question's declared context when the answer does not
            # explicitly provide one; never override a context stated by the answer.
            cl['context'] = (cl.get('context') or q['context'] or '').strip().lower()
            result=verify(cl,allfacts)
            fact=result.get('fact')
            verdicts.append({'product_id':cl['product_id'],'field':cl['field'],
                             'observed':cl['value'],'verdict':result['verdict'],'reason':result['reason']})
            c.execute('''INSERT INTO claims(run_id,product_id,field,value,context,quote,verdict,reason,expected,fact_id)
                            VALUES (?,?,?,?,?,?,?,?,?,?)''',
                 (run_id,cl['product_id'],cl['field'],cl['value'],cl['context'],cl['quote'],
                  result['verdict'],result['reason'],str(result.get('expected','')),
                  fact['fact_id'] if fact else ''))
            if result['verdict']=='INCORRECT':
                # One ticket per wrong FACT (product + field + context), however the AI words it.
                # A dismissed ticket is not reopened by the same fact; an approved one records that
                # the fix has NOT worked yet (the AI still repeats the error on a later check).
                active=c.execute('''SELECT * FROM tickets WHERE business_id=? AND product_id=? AND field=?
                        AND context=? AND status IN ('pending','investigating','approved','rejected')
                        ORDER BY id DESC LIMIT 1''',
                    (q['business_id'],cl['product_id'],cl['field'],cl['context'])).fetchone()
                if active:
                    action={'approved':'retest_still_wrong','rejected':'repeat_after_dismissal'}.get(active['status'],'repeat_detected')
                    c.execute('UPDATE tickets SET last_run_id=?,occurrences=occurrences+1,updated_at=? WHERE id=?',
                              (run_id,timestamp(),active['id']))
                    c.execute('INSERT INTO audit(ticket_id,action,note,created_at) VALUES (?,?,?,?)',
                              (active['id'],action,f'Answer #{run_id} said: {result["observed"]}',timestamp()))
                    tickets_updated.append(active['id'])
                else:
                    product_name=fact['product_name']
                    label={'price_usd':'price'}.get(cl['field'],cl['field'])
                    title=f'{product_name}: {label}'+(f' ({cl["context"]})' if cl['context'] else '')+' discrepancy'
                    cur=c.execute('''INSERT INTO tickets(business_id,product_id,product_name,field,context,ai_value,
                        verified_value,fact_id,source_url,title,proposal,priority,status,created_at,updated_at,
                        first_run_id,last_run_id,occurrences,reviewer_note)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                        (q['business_id'],cl['product_id'],product_name,cl['field'],cl['context'],
                         result['observed'],result['expected'],fact['fact_id'],fact['source_url'],title,
                         suggested_action(cl['field']),severity_for(cl['product_id'],cl['field']),
                         'pending',timestamp(),timestamp(),run_id,run_id,1,''))
                    tickets_created.append(cur.lastrowid)
            elif result['verdict']=='CORRECT' and mode!='demo':
                # A fresh answer after approval is evidence for retest, not proof of causality.
                prev=rows(c,'''SELECT * FROM tickets WHERE business_id=? AND product_id=? AND field=?
                  AND context=? AND status='approved' AND first_run_id!=?''',
                  (q['business_id'],cl['product_id'],cl['field'],cl['context'],run_id))
                for t in prev:
                    c.execute('UPDATE tickets SET status=?,last_run_id=?,updated_at=? WHERE id=?',
                              ('verified',run_id,timestamp(),t['id']))
                    c.execute('INSERT INTO audit(ticket_id,action,note,created_at) VALUES (?,?,?,?)',
                              (t['id'],'retest_observed',f'Follow-up answer #{run_id} matches approved fact. No causal claim.',timestamp()))
                    verified_retests.append(t['id'])
    return {'run_id':run_id,'mode':mode,'extraction_status':extraction_status,'extraction_note':extract_note,
            'claims':verdicts,'tickets_created':tickets_created,'tickets_updated':tickets_updated,
            'tickets_verified_on_retest':verified_retests}

@app.post('/api/answers')
def submit_answer(payload:AnswerSubmission):
    """This lets an analyst paste in an AI answer by hand and send it through the pipeline."""
    return process_answer(payload.question_id,payload.answer,payload.citations,'pasted',
        payload.extraction,[c.model_dump() for c in payload.manual_claims])

@app.post('/api/demo')
def run_demo():
    """This loads the original bakery demo answers (analyst console only)."""
    with conn() as c:
        if c.execute("SELECT COUNT(*) FROM runs WHERE mode='demo'").fetchone()[0]:
            raise HTTPException(409,'Demo already loaded. Reset the demo or inspect its existing tickets.')
    result=[]
    for d in json.loads((BASE/'data/demo_answers.json').read_text()):
        result.append(process_answer(d['question_id'],d['answer'],['demo://old-menu'],
                                     'demo','manual',d['claims']))
    return {'processed':len(result),'runs':result,'notice':'All four answers are authored synthetic fixtures.'}

@app.post('/api/reset-demo')
def reset_demo():
    """This removes the bakery demo answers and the tickets they created."""
    with LOCK,conn() as c:
        ids=[r[0] for r in c.execute("SELECT id FROM runs WHERE mode='demo'")]
        if not ids:return {'deleted_demo_runs':0}
        binds=','.join('?' for _ in ids)
        # Only delete tickets that originate from demo answers; prevent demo reset
        # from erasing a separate, real-business investigation.
        tickets=rows(c,f'SELECT id FROM tickets WHERE first_run_id IN ({binds})',ids)
        tids=[t['id'] for t in tickets]
        if tids:
            marks=','.join('?' for _ in tids)
            c.execute(f'DELETE FROM audit WHERE ticket_id IN ({marks})',tids)
            c.execute(f'DELETE FROM tickets WHERE id IN ({marks})',tids)
        c.execute(f'DELETE FROM claims WHERE run_id IN ({binds})',ids)
        c.execute(f'DELETE FROM runs WHERE id IN ({binds})',ids)
    return {'deleted_demo_runs':len(ids)}

@app.post('/api/runs/{run_id}/extract')
def retry_extraction(run_id:int):
    """This retries pulling claims out of an answer whose first attempt failed."""
    with conn() as c:
        r=c.execute('SELECT * FROM runs WHERE id=?',(run_id,)).fetchone()
        if not r:raise HTTPException(404,'Answer not found.')
        if r['extraction_status']=='complete':raise HTTPException(409,'Answer already extracted.')
    # Rerun against original question; use new run for clean audit trail.
    return process_answer(r['question_id'],r['answer'],json.loads(r['citations']),
                          r['mode'],'ai')

class LiveRequest(BaseModel):
    """This is the shape of a request to ask one question live."""
    question_id:str

@app.post('/api/run-live-gemini')
def run_live_gemini(payload: LiveRequest):
    """This asks Gemini ONE question live and sends the answer through the pipeline."""
    if not os.getenv('GEMINI_API_KEY'):
        raise HTTPException(400,'Set GEMINI_API_KEY in .env and restart the application.')
    with conn() as c:
        q=get_question(c,payload.question_id)
    try:
        answer,citations=ask_gemini_shopper(q['text'])
    except Exception as exc:
        raise HTTPException(502,'Live Gemini call failed. Check key, model access, Google Search grounding, network and quota.') from exc
    return process_answer(payload.question_id,answer,citations,'live_gemini','ai')

def ask_gemini_shopper(question_text:str)->tuple[str,list[str]]:
    """This is the AI Mystery Shopper. It asks Gemini a question with Google Search turned on,
    the way a real customer would, and returns the answer plus the web pages it cited.
    """
    from google import genai
    from google.genai import types
    client=genai.Client(api_key=os.environ['GEMINI_API_KEY'])
    from ai import with_quota_retry
    response=with_quota_retry(lambda: client.models.generate_content(
        model=os.getenv('GEMINI_SHOPPER_MODEL') or os.getenv('GEMINI_MODEL','gemini-3.5-flash-lite'),
        contents=question_text,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.5,
        ),
    ))
    answer=response.text or ''
    if not answer.strip():
        raise ValueError('Gemini returned an empty answer.')
    citations=[]
    for cand in response.candidates or []:
        grounding=getattr(cand,'grounding_metadata',None)
        for chunk in (getattr(grounding,'grounding_chunks',None) or []):
            url=getattr(getattr(chunk,'web',None),'uri',None)
            if url and url.startswith('https://') and url not in citations:
                citations.append(url)
    return answer,citations
@app.post('/api/run-live')
def run_live(payload:LiveRequest):
    """This asks ChatGPT (OpenAI) one question live, if an OpenAI key is set,
    and sends the answer through the pipeline.
    """
    if not os.getenv('OPENAI_API_KEY'):raise HTTPException(400,'Set OPENAI_API_KEY before making paid live calls.')
    with conn() as c:q=get_question(c,payload.question_id)
    try:
        from openai import OpenAI
        resp=OpenAI(timeout=60).responses.create(
            model=os.getenv('OPENAI_MODEL','gpt-4.1-mini'),
            tools=[{'type':'web_search'}],input=q['text'])
        answer=resp.output_text or ''
        citations=[]
        for out in resp.output or []:
            for content in getattr(out,'content',[]) or []:
                for a in getattr(content,'annotations',[]) or []:
                    if getattr(a,'type',None)=='url_citation':
                        u=getattr(a,'url','')
                        if u and u not in citations:citations.append(u)
    except Exception as exc:
        raise HTTPException(502,'Live OpenAI call failed. Check API key, billing, model and web-search access.') from exc
    return process_answer(payload.question_id,answer,citations,'live_openai','ai')

@app.get('/api/dashboard')
def dashboard():
    """This returns the data for the older analyst console: counts, answers and tickets."""
    with conn() as c:
        runs=rows(c,'''SELECT r.*,q.text AS question_text,q.type AS question_type
                       FROM runs r JOIN questions q ON q.id=r.question_id ORDER BY r.id DESC LIMIT 250''')
        claims=rows(c,'''SELECT cl.*,r.mode,r.question_id FROM claims cl JOIN runs r ON r.id=cl.run_id
                          ORDER BY cl.id DESC LIMIT 500''')
        tickets=rows(c,'''SELECT t.*,r.answer,r.citations,r.question_id,r.mode,cl.quote
              FROM tickets t JOIN runs r ON r.id=t.first_run_id
              JOIN claims cl ON cl.run_id=t.first_run_id AND cl.product_id=t.product_id
               AND cl.field=t.field AND cl.context=t.context AND cl.verdict='INCORRECT'
              ORDER BY t.id DESC''')
        audit=rows(c,'SELECT * FROM audit ORDER BY id DESC LIMIT 100')
    for r in runs:r['citations']=json.loads(r['citations'])
    for t in tickets:t['citations']=json.loads(t['citations'])
    real=[r for r in runs if r['mode']!='demo']
    v=[r for r in real if r['question_type']=='visibility']
    included=0
    for r in v:
        with conn() as c:
            name=c.execute('SELECT business_name FROM facts WHERE business_id=? LIMIT 1',(r['business_id'],)).fetchone()
        if name and name['business_name'].lower() in r['answer'].lower():included+=1
    verified=[cl for cl in claims if cl['verdict'] in ('CORRECT','INCORRECT') and cl['mode']!='demo']
    return {'metrics':{'real_answers':len(real),'synthetic_answers':len(runs)-len(real),
             'visibility_pct':round(100*included/len(v),1) if v else None,
             'visibility_n':len(v),'visibility_mentions':included,
             'accuracy_pct':round(100*sum(x['verdict']=='CORRECT' for x in verified)/len(verified),1) if verified else None,
             'verified_claims':len(verified),'incorrect_claims':sum(x['verdict']=='INCORRECT' for x in verified),
             'tickets_pending':sum(t['status'] in ('pending','investigating') for t in tickets),
             'tickets_all':len(tickets)},
             'runs':runs,'claims':claims,'tickets':tickets,'audit':audit}

@app.post('/api/tickets/{ticket_id}/decision')
def decide(ticket_id:int,payload:TicketDecision):
    """This records a person's decision on a ticket (approve, reject or investigate)
    and writes it to the audit log.
    """
    with LOCK,conn() as c:
        t=c.execute('SELECT * FROM tickets WHERE id=?',(ticket_id,)).fetchone()
        if not t:raise HTTPException(404,'Ticket not found.')
        if t['status'] not in ('pending','investigating'):
            raise HTTPException(409,'This ticket has already been decided.')
        state={'approve':'approved','reject':'rejected','investigate':'investigating'}[payload.action]
        c.execute('UPDATE tickets SET status=?,reviewer_note=?,updated_at=? WHERE id=?',
                  (state,payload.note,timestamp(),ticket_id))
        c.execute('INSERT INTO audit(ticket_id,action,note,created_at) VALUES(?,?,?,?)',
                  (ticket_id,payload.action,payload.note,timestamp()))
    return {'ticket_id':ticket_id,'status':state,
            'note':'A local reviewer decision is recorded; nothing is published or emailed.'}

@app.get('/api/demo-source')
def demo_source():
    """This shows the fake 'old menu' page used by the bakery demo."""
    return {'label':'SYNTHETIC OLD MENU','text':'Demo: Juniper Neighborhood Bakery no longer sells Orange Blossom Cookies.',
            'note':'A deliberately outdated, entirely fictional page for a controlled demonstration.'}

@app.get('/api/templates/bistro.csv')
def bistro_template():
    """This lets you download the Bistro Taíno fact spreadsheet template."""
    return FileResponse(BASE/'data/bistro_taino_TEMPLATE.csv',filename='bistro_taino_TEMPLATE.csv',media_type='text/csv')

@app.get('/api/templates/demo.csv')
def demo_catalog_template():
    """This lets you download the bakery demo fact spreadsheet."""
    return FileResponse(BASE/'data/demo_catalog.csv',filename='demo_catalog.csv',media_type='text/csv')

class SourceInspectRequest(BaseModel):
    """This is the shape of a request to open a web page the AI cited."""
    url: str = Field(min_length=9, max_length=2048)

@app.post('/api/inspect-source')
def inspect_source(payload: SourceInspectRequest):
    """This safely opens a public web page the AI cited so a reviewer can read it.
    It does NOT prove the AI actually used that page to write its answer.
    """
    import ipaddress, socket
    from bs4 import BeautifulSoup
    u=urlparse(payload.url)
    if u.scheme != 'https' or not u.hostname or u.port not in (None,443) or u.username or u.password:
        raise HTTPException(400,'Only public HTTPS websites on port 443 are supported.')
    try:
        ips=socket.getaddrinfo(u.hostname,443,type=socket.SOCK_STREAM)
        if not ips or any(not ipaddress.ip_address(item[4][0]).is_global for item in ips):
            raise ValueError('Nonpublic destination')
    except Exception as exc:
        raise HTTPException(400,'The citation URL must resolve to public IP addresses.') from exc
    try:
        r=requests.get(payload.url,timeout=8,allow_redirects=False,stream=True,
                       headers={'User-Agent':'ProofFlowerLocalResearch/0.2'})
        if 300 <= r.status_code < 400:
            raise HTTPException(400,'Redirects require manual inspection; this fetcher does not follow them.')
        r.raise_for_status()
        if 'html' not in r.headers.get('Content-Type','').lower():
            raise HTTPException(415,'This inspector supports ordinary HTML pages; PDF/image need manual review.')
        chunks=[]; size=0
        for chunk in r.iter_content(chunk_size=16384):
            size+=len(chunk)
            if size>1_000_000:raise HTTPException(413,'Webpage too large for lightweight inspection.')
            chunks.append(chunk)
        soup=BeautifulSoup(b''.join(chunks),'html.parser')
        title=soup.title.get_text(' ',strip=True) if soup.title else u.hostname
        for node in soup(['script','style','nav','footer']):node.decompose()
        text='\n'.join(soup.stripped_strings)[:15000]
        return {'title':title,'url':payload.url,'retrieved_at':timestamp(),'text':text,
                'note':'A displayed source is not proof the assistant used it to generate the claim.'}
    except HTTPException:raise
    except requests.RequestException as exc:
        raise HTTPException(502,'Could not retrieve this public webpage. Mark its citation unverified.') from exc


# =====================================================================
# EVAL HARNESS  (Extract -> Transform -> Load -> Score)
# =====================================================================
import time
import scoring, evals, geo

class EvalRunRequest(BaseModel):
    """This is the shape of a request to run a weekly check:
    demo Week 1, demo Week 3, or a live check with Gemini.
    """
    business_id: str = 'casa_coqui'
    mode: str = Field(default='mock_baseline', pattern='^(mock_baseline|mock_after|live_gemini)$')
    label: str = Field(default='', max_length=120)
    limit: int = Field(default=40, ge=1, le=40)

def load_business(business_id:str):
    """This makes sure a business's approved facts and its locked question list are ready, and returns
    the question list. The demo business reads them from its data folder; businesses set up from a
    CSV read them from the database.
    """
    es=evals.load_eval_set(business_id)
    if es:
        cat=evals.business_dir(business_id)/'catalog.csv'
        with LOCK,conn() as c:
            if cat.exists():   # the showcase catalog file is the source of truth: re-sync it every time
                with cat.open(newline='',encoding='utf-8-sig') as f:
                    insert_csv_rows(c,list(csv.DictReader(f)),seed=True)
            for q in es['questions']:
                c.execute('''INSERT OR IGNORE INTO questions VALUES (?,?,?,?,?,?,?,?)''',
                    (q['id'],business_id,q['type'],q['text'],q['product_id'],q['target_field'],q['context'],'evalset'))
        return es
    with conn() as c:
        b=c.execute('SELECT * FROM businesses WHERE business_id=?',(business_id,)).fetchone()
        qs=rows(c,"SELECT * FROM questions WHERE business_id=? AND origin='evalset'",(business_id,))
    if not qs: raise HTTPException(404,f'No question list for {business_id}. Set the business up first.')
    order={'visibility':0,'accuracy':1,'stress':2}
    qs.sort(key=lambda q:(order.get(q['type'],3),q['id']))
    return {'version':(b['eval_version'] if b else '') or f'{business_id}-v1','location':b['location'] if b else '',
            'questions':[{k:q[k] for k in ('id','type','text','product_id','target_field','context')} for q in qs]}

def get_profile(business_id:str)->dict:
    """This returns a business's profile (name, location, category, website signals) from its data
    folder (demo) or from the database (businesses set up from a CSV).
    """
    prof=evals.load_profile(business_id)
    if prof: return prof
    with conn() as c:
        b=c.execute('SELECT * FROM businesses WHERE business_id=?',(business_id,)).fetchone()
        f=c.execute('SELECT business_name FROM facts WHERE business_id=? LIMIT 1',(business_id,)).fetchone()
    if b:
        return {'business_id':business_id,'business_name':b['business_name'],'location':b['location'],
                'category':b['category'],'website':b['website'],'synthetic':bool(b['synthetic']),
                'signals':json.loads(b['signals'] or '{}')}
    return {'business_id':business_id,'business_name':f['business_name'] if f else business_id,'signals':{}}

def claims_for_run(run_id:int)->list[dict]:
    """This returns the claims (and their verdicts) found in one saved answer."""
    with conn() as c:
        return rows(c,'SELECT product_id,field,value,context,quote,verdict,expected,fact_id FROM claims WHERE run_id=?',(run_id,))

def run_one(q:dict, mode:str, mock:dict|None, brand:str)->dict:
    """This runs ONE question of a weekly check: gets the answer (saved demo answer, or live from
    Gemini), sends it through the pipeline, and returns the question's result, including any
    tickets it created (flagged problems) or updated (repeat problems).
    """
    r={'question_id':q['id'],'question':q['text'],'type':q['type'],'claims':[],'answer':'','citations':[],
       'tickets_created':[],'tickets_updated':[],'tickets_verified':[]}
    try:
        if mock:
            item=mock['answers'][q['id']]
            out=process_answer(q['id'],item['answer'],item.get('citations',[]),'mock','manual',item.get('claims',[]))
            vis=item.get('visibility'); unsupported=item.get('unsupported',False); abstained=item.get('abstained',False)
            answer,cites=item['answer'],item.get('citations',[])
        else:
            answer,cites=ask_gemini_shopper(q['text'])
            out=process_answer(q['id'],answer,cites,'live_gemini','ai' if q['type']!='visibility' else 'manual',[])
            vis=evals.parse_visibility(answer,brand,q['text']) if q['type']=='visibility' else None
            abstained=evals.detect_abstention(answer)
            # A confident "yes" to a trick question is only "made up" if nothing in the answer
            # was confirmed against an approved fact.
            confirmed=any(c['verdict']=='CORRECT' for c in claims_for_run(out['run_id']))
            unsupported=q['type']=='stress' and not abstained and not confirmed and evals.detect_affirmation(answer)
        r.update(answer=answer,citations=cites,run_id=out['run_id'],extraction=out['extraction_status'],
                 extraction_note=out['extraction_note'],claims=claims_for_run(out['run_id']),visibility=vis,
                 unsupported=unsupported,abstained=abstained,tickets_created=out['tickets_created'],
                 tickets_updated=out['tickets_updated'],tickets_verified=out['tickets_verified_on_retest'],
                 tickets=out['tickets_created']+out['tickets_updated'])
    except HTTPException: raise
    except Exception as exc:
        print('LIVE CHECK ERROR:', q['id'], exc)   # full detail in the server log only
        r['error']=friendly_error(exc); r['quota']=is_quota_error(exc)
    r['outcome']=scoring.question_outcome(r)
    flag_invention(q,r,brand)
    return r

def flag_invention(q:dict, r:dict, biz:str):
    """This turns a made-up answer to a trick question into a ticket, so it gets flagged like any
    other problem. Example: AI says "Yes, they have a Monday happy hour" when no such offer is in the
    approved facts. If a later check answers that trick question safely, an approved ticket is
    marked fixed. Priority is Medium: it needs a person to confirm it isn't real.
    """
    if q['type']!='stress' or r.get('error') or not r.get('run_id'): return
    if any(c['verdict']=='INCORRECT' for c in r.get('claims',[])): return   # already ticketed as a wrong fact
    made_up=scoring.is_hallucination(r)
    now=timestamp()
    with LOCK,conn() as c:
        open_t=c.execute("""SELECT id,status FROM tickets WHERE business_id=? AND field='invented' AND context=?
                            AND status IN ('pending','approved','investigating')""",(get_question(c,q['id'])['business_id'],q['id'])).fetchone()
        bid=get_question(c,q['id'])['business_id']
        if made_up:
            parts=re.split(r'(?<=[.!?])\s+',(r.get('answer') or '').strip())
            said=(' '.join(parts[:2]) if len(parts[0])<25 else parts[0])[:180]
            if open_t:
                c.execute('UPDATE tickets SET last_run_id=?,occurrences=occurrences+1,updated_at=? WHERE id=?',(r['run_id'],now,open_t['id']))
                r['tickets_updated']=r.get('tickets_updated',[])+[open_t['id']]
            else:
                cur=c.execute('''INSERT INTO tickets(business_id,product_id,product_name,field,context,ai_value,verified_value,
                    fact_id,source_url,title,proposal,priority,status,created_at,updated_at,first_run_id,last_run_id)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (bid,'business',biz,'invented',q['id'],said,'Not in your approved facts','',
                     (r.get('citations') or [''])[0],f'{biz}: possible made-up claim',
                     'Confirm this is not something you offer. If it is not, answer the question clearly on your website (FAQ) so AI stops repeating it. If it IS true, add it to your approved facts and dismiss this ticket.',
                     'medium','pending',now,now,r['run_id'],r['run_id']))
                r['tickets_created']=r.get('tickets_created',[])+[cur.lastrowid]
        elif open_t and open_t['status']=='approved':
            c.execute("UPDATE tickets SET status='verified',last_run_id=?,updated_at=? WHERE id=?",(r['run_id'],now,open_t['id']))
            r['tickets_verified']=r.get('tickets_verified',[])+[open_t['id']]
    r['tickets']=r.get('tickets_created',[])+r.get('tickets_updated',[])

def _check_mode(business_id:str, mode:str):
    """This makes sure a check can run: demo checks need saved demo answers, live checks need a key."""
    if mode.startswith('mock'):
        try: evals.load_mock(business_id,mode)
        except FileNotFoundError: raise HTTPException(400,'Demo answers only exist for the demo business. Use a live check.')
    elif not os.getenv('GEMINI_API_KEY'):
        raise HTTPException(400,'Live checks need GEMINI_API_KEY on the server. The demo works without it.')

def run_eval(business_id:str, mode:str, label:str='', limit:int=40)->dict:
    """This runs one full weekly check in a single go (used for the demo story and tests). It asks
    every question, sends each answer through the pipeline, calculates the scores, and saves the check.
    """
    es=load_business(business_id); _check_mode(business_id,mode)
    brand=get_profile(business_id).get('business_name',business_id)
    mock=evals.load_mock(business_id,mode) if mode.startswith('mock') else None
    results=[]
    for q in es['questions'][:limit]:
        results.append(run_one(q,mode,mock,brand))
        if not mock: time.sleep(float(os.getenv('LIVE_EVAL_DELAY','4')))
    card=scoring.scorecard(results); synthetic=1 if mock else 0
    status='done' if card['answered'] else 'failed'
    with LOCK,conn() as c:
        cur=c.execute('''INSERT INTO eval_runs(business_id,label,mode,eval_version,synthetic,scores,results,created_at,status)
                         VALUES (?,?,?,?,?,?,?,?,?)''',
            (business_id,label or (mock or {}).get('label') or 'Live check',mode,es['version'],synthetic,
             json.dumps(card),json.dumps(results),timestamp(),status))
        eid=cur.lastrowid
    return {'id':eid,'business_id':business_id,'mode':mode,'synthetic':bool(synthetic),'status':status,'scores':card,'results':results}

class EvalStartRequest(BaseModel):
    """This is the shape of a request to start a step-by-step check."""
    business_id: str = 'casa_coqui'
    mode: str = Field(default='live_gemini', pattern='^(mock_baseline|mock_after|live_gemini)$')
    label: str = Field(default='', max_length=120)
    limit: int = Field(default=40, ge=1, le=40)

@app.post('/api/evals/start')
def api_eval_start(payload:EvalStartRequest):
    """This starts a step-by-step check: it saves an empty check marked 'running' with the list of
    questions to ask. The dashboard then calls /step once per question and shows each result live.
    """
    es=load_business(payload.business_id); _check_mode(payload.business_id,payload.mode)
    plan=[q['id'] for q in es['questions'][:payload.limit]]
    mock=payload.mode.startswith('mock')
    label=payload.label or (evals.load_mock(payload.business_id,payload.mode)['label'] if mock else f"Live check · {datetime.now().strftime('%b %d')}")
    with LOCK,conn() as c:
        cur=c.execute('''INSERT INTO eval_runs(business_id,label,mode,eval_version,synthetic,scores,results,created_at,status)
                         VALUES (?,?,?,?,?,?,?,?,'running')''',
            (payload.business_id,label,payload.mode,es['version'],int(mock),json.dumps({'plan':plan}),'[]',timestamp()))
        eid=cur.lastrowid
    return {'id':eid,'total':len(plan),'label':label}

@app.post('/api/evals/{eid}/step')
def api_eval_step(eid:int):
    """This asks the NEXT question of a running check and returns its result straight away,
    including the tickets it just created. When the last question is done it calculates the scores.
    """
    with conn() as c:
        run=c.execute('SELECT * FROM eval_runs WHERE id=?',(eid,)).fetchone()
    if not run: raise HTTPException(404,'Check not found.')
    if run['status']!='running': raise HTTPException(409,'This check is already finished.')
    plan=json.loads(run['scores'])['plan']; results=json.loads(run['results'])
    es=load_business(run['business_id'])
    q=next(x for x in es['questions'] if x['id']==plan[len(results)])
    mock=evals.load_mock(run['business_id'],run['mode']) if run['mode'].startswith('mock') else None
    if not mock and results:
        time.sleep(float(os.getenv('LIVE_EVAL_DELAY','4')))   # pace live calls to stay under Gemini's free-tier limit
    r=run_one(q,run['mode'],mock,get_profile(run['business_id']).get('business_name',run['business_id']))
    results.append(r)
    # If Gemini's quota is used up, every remaining question would fail too: stop now instead of
    # making the owner wait, and keep the previous check as the latest real result.
    aborted='quota' if r.get('quota') else None
    done=len(results)>=len(plan) or bool(aborted)
    card=scoring.scorecard(results) if done else None
    with LOCK,conn() as c:
        if done:
            status='done' if card['answered'] and not aborted else 'failed'
            c.execute("UPDATE eval_runs SET results=?,scores=?,status=? WHERE id=?",(json.dumps(results),json.dumps(card),status,eid))
        else:
            c.execute('UPDATE eval_runs SET results=? WHERE id=?',(json.dumps(results),eid))
        ids=r.get('tickets_created',[])+r.get('tickets_updated',[])+r.get('tickets_verified',[])
        tk=rows(c,f"SELECT id,title,priority,status,product_id,product_name,field,context,ai_value,verified_value FROM tickets WHERE id IN ({','.join('?'*len(ids))})",ids) if ids else []
    for t in tk:
        t['event']=('created' if t['id'] in r.get('tickets_created',[]) else 'fixed' if t['id'] in r.get('tickets_verified',[])
                    else 'still_wrong' if t['status']=='approved' else 'repeat')
        t['new']=t['event']=='created'
    return {'id':eid,'index':len(results),'total':len(plan),'done':done,'result':r,'tickets':tk,
            'aborted':aborted,'scores':card}

@app.post('/api/evals/run')
def api_run_eval(payload:EvalRunRequest):
    """This is the web endpoint that starts a weekly check."""
    return run_eval(payload.business_id,payload.mode,payload.label,payload.limit)

@app.get('/api/evals')
def api_list_evals(business_id:str='casa_coqui'):
    """This lists every weekly check for a business, with its scores."""
    with conn() as c:
        rs=rows(c,"SELECT id,label,mode,eval_version,synthetic,scores,created_at FROM eval_runs WHERE business_id=? AND status='done' ORDER BY id",(business_id,))
    for r in rs: r['scores']=json.loads(r['scores'])
    return {'business_id':business_id,'runs':rs}

def get_eval(eid:int)->dict:
    """This loads one saved weekly check with all of its results."""
    with conn() as c:
        r=c.execute('SELECT * FROM eval_runs WHERE id=?',(eid,)).fetchone()
    if not r: raise HTTPException(404,'Eval run not found.')
    r=dict(r); r['scores']=json.loads(r['scores']); r['results']=json.loads(r['results'])
    return r

@app.get('/api/evals/{eid}')
def api_get_eval(eid:int):
    """This is the web endpoint for one saved weekly check."""
    return get_eval(eid)

@app.get('/api/evals/compare/{a}/{b}')
def api_compare(a:int,b:int):
    """This compares two weekly checks: how each score moved and which questions changed result."""
    ea,eb=get_eval(a),get_eval(b)
    before={r['question_id']:r['outcome'] for r in ea['results']}
    changes=[{'question_id':r['question_id'],'question':r['question'],'before':before.get(r['question_id']),'after':r['outcome']}
             for r in eb['results'] if before.get(r['question_id'])!=r['outcome']]
    return {'before':{'id':a,'label':ea['label'],'scores':ea['scores']},'after':{'id':b,'label':eb['label'],'scores':eb['scores']},
            'delta':scoring.compare(ea['scores'],eb['scores']),'changed_questions':changes}

class ExtractorEvalRequest(BaseModel):
    """This is the shape of a request to test our own claim extractor."""
    business_id: str = 'casa_coqui'
    limit: int = Field(default=8, ge=1, le=24)

@app.post('/api/evals/extractor')
def api_extractor_eval(payload:ExtractorEvalRequest):
    """This tests OUR OWN AI. It runs the Gemini claim extractor on demo answers we labeled by hand,
    then measures recall (how many of the right facts it found) and precision (how many of the
    facts it found were right).
    """
    if not os.getenv('GEMINI_API_KEY'):
        raise HTTPException(400,'The extractor eval needs GEMINI_API_KEY (it grades the live Gemini extractor).')
    es=load_business(payload.business_id)
    with conn() as c:
        facts=rows(c,'SELECT * FROM facts WHERE business_id=?',(payload.business_id,))
    brand=facts[0]['business_name']
    qs={q['id']:q for q in es['questions']}
    cases=[]
    for mode in ('mock_baseline','mock_after'):
        for qid,item in evals.load_mock(payload.business_id,mode)['answers'].items():
            if qs[qid]['type']!='visibility': cases.append((qid,item))
    cases=cases[:payload.limit]
    gold_all,pred_all,rows_out=[],[],[]
    for qid,item in cases:
        gold=[evals.claim_key({**c,'context':c.get('context') or qs[qid]['context']}) for c in item.get('claims',[])]
        try:
            batch=extract_claims(item['answer'],qs[qid],brand,facts)
            pred=[evals.claim_key({**c.model_dump(),'context':c.context or qs[qid]['context']}) for c in batch.claims]
            err=''
        except Exception as exc:
            pred=[]; err=str(exc)[:160]
        gold_all+= [(qid,)+g for g in gold]; pred_all+=[(qid,)+p for p in pred]
        rows_out.append({'question_id':qid,'answer':item['answer'],'gold':len(gold),'predicted':len(pred),
                         'exact_match':set(gold)==set(pred),'error':err})
        time.sleep(float(os.getenv('LIVE_EVAL_DELAY','4')))
    m=evals.extractor_metrics(gold_all,pred_all)
    m['exact_match_rate']=round(100*sum(r['exact_match'] for r in rows_out)/len(rows_out),1) if rows_out else None
    return {'metrics':m,'cases':rows_out,'model':GEMINI_MODEL,
            'note':'Gold labels are hand-written for the synthetic Casa Coquí answers.'}

# ---------------------------------------------------------------- GEO + report
class SiteAuditRequest(BaseModel):
    """This is the shape of a request to check a website."""
    url: str = Field(min_length=8, max_length=300)

@app.post('/api/geo/site-audit')
def api_site_audit(payload:SiteAuditRequest):
    """This checks a real website for AI-readiness and returns what it found."""
    try: return geo.site_audit(payload.url.strip())
    except ValueError as exc: raise HTTPException(400,str(exc)) from exc

class GeoRequest(BaseModel):
    """This is the shape of a request for a growth plan (optionally for a real website)."""
    business_id: str = 'casa_coqui'
    url: str = ''
    eval_id: int = 0   # which eval's missed questions to plan from (default: earliest of the last two)

def latest_evals(business_id:str):
    """This returns the last two weekly checks, used for before/after comparisons."""
    with conn() as c:
        ids=[r['id'] for r in rows(c,"SELECT id FROM eval_runs WHERE business_id=? AND status='done' ORDER BY id",(business_id,))]
    return [get_eval(i) for i in ids[-2:]]

@app.post('/api/geo/recommendations')
def api_geo(payload:GeoRequest):
    """This builds the growth plan. It takes website signals (demo, or a real site) and the local
    searches where the business didn't show up, and turns them into ranked steps.
    """
    profile=get_profile(payload.business_id)
    signals=profile.get('signals',{})
    if payload.url:
        try: signals=geo.site_audit(payload.url.strip())
        except ValueError as exc: raise HTTPException(400,str(exc)) from exc
    with conn() as c:
        facts=rows(c,'SELECT * FROM facts WHERE business_id=?',(payload.business_id,))
    ev=[get_eval(payload.eval_id)] if payload.eval_id else latest_evals(payload.business_id)[:1]
    recs=geo.recommend(signals,ev[0] if ev else None,facts,profile)
    for r in recs: r['draftable']=geo.can_draft(r['id'])
    return {'business':{k:v for k,v in profile.items() if k!='signals'},'signals':signals,
            'planned_from_eval':(ev[0]['id'],ev[0]['label']) if ev else None,
            'signals_synthetic':bool(profile.get('synthetic')) and not payload.url,'recommendations':recs}

class DraftRequest(BaseModel):
    """This is the shape of a 'Write it for me' request."""
    business_id: str = 'casa_coqui'
    finding: dict

@app.post('/api/geo/draft')
def api_geo_draft(payload:DraftRequest):
    """This writes the draft fix for one growth-plan step, using approved facts only."""
    profile=get_profile(payload.business_id)
    with conn() as c:
        facts=rows(c,'SELECT * FROM facts WHERE business_id=?',(payload.business_id,))
    return geo.draft_content(payload.finding,facts,{k:v for k,v in profile.items() if k!='signals'})

@app.get('/api/report/{business_id}')
def api_report(business_id:str):
    """This gathers everything the owner dashboard needs in one call: the latest checks,
    how the scores changed, tickets with their evidence, and the scoring weights.
    """
    ev=latest_evals(business_id)
    with conn() as c:
        tickets=rows(c,'SELECT * FROM tickets WHERE business_id=? ORDER BY id',(business_id,))
        tids=[t['id'] for t in tickets]
        audit=rows(c,f"SELECT * FROM audit WHERE ticket_id IN ({','.join('?'*len(tids))}) ORDER BY id DESC",tids) if tids else []
        runs=rows(c,'SELECT id,question_id,answer,citations,mode FROM runs WHERE business_id=?',(business_id,))
        qtext={q['id']:q['text'] for q in rows(c,'SELECT id,text FROM questions WHERE business_id=?',(business_id,))}
        quotes={(x['run_id'],x['product_id'],x['field'],x['context']):x['quote'] for x in rows(c,
                "SELECT cl.run_id,cl.product_id,cl.field,cl.context,cl.quote FROM claims cl JOIN runs r ON r.id=cl.run_id WHERE r.business_id=? AND cl.verdict='INCORRECT'",(business_id,))}
        checked={f['fact_id']:f['checked_at'] for f in rows(c,'SELECT fact_id,checked_at FROM facts WHERE business_id=?',(business_id,))}
    run_map={r['id']:r for r in runs}
    for t in tickets:
        first=run_map.get(t['first_run_id'],{}); last=run_map.get(t['last_run_id'],first)
        t['evidence_answer']=first.get('answer',''); t['evidence_citations']=json.loads(first.get('citations','[]') or '[]')
        t['evidence_quote']=quotes.get((t['first_run_id'],t['product_id'],t['field'],t['context']),'')
        t['latest_answer']=last.get('answer','')
        t['question_id']=first.get('question_id',''); t['question_text']=qtext.get(t['question_id'],'')
        t['fact_checked_at']=checked.get(t['fact_id'],'')
        acts=[a['action'] for a in audit if a['ticket_id']==t['id']]   # newest first
        t['still_wrong']=t['status']=='approved' and bool(acts) and acts[0]=='retest_still_wrong'
    return {'business_id':business_id,'evals':ev,
            'delta':scoring.compare(ev[0]['scores'],ev[1]['scores']) if len(ev)==2 else None,
            'tickets':tickets,'audit':audit[:30],'weights':{'severity':scoring.SEVERITY,'framing':scoring.FRAMING,'health':scoring.HEALTH_WEIGHTS}}

@app.post('/api/evals/reset/{business_id}')
def api_reset_business(business_id:str):
    """This wipes one business's answers, tickets and checks so the demo can start over."""
    with LOCK,conn() as c:
        rids=[r[0] for r in c.execute('SELECT id FROM runs WHERE business_id=?',(business_id,))]
        tids=[r[0] for r in c.execute('SELECT id FROM tickets WHERE business_id=?',(business_id,))]
        if tids: c.execute(f"DELETE FROM audit WHERE ticket_id IN ({','.join('?'*len(tids))})",tids)
        c.execute('DELETE FROM tickets WHERE business_id=?',(business_id,))
        if rids: c.execute(f"DELETE FROM claims WHERE run_id IN ({','.join('?'*len(rids))})",rids)
        c.execute('DELETE FROM runs WHERE business_id=?',(business_id,))
        c.execute('DELETE FROM eval_runs WHERE business_id=?',(business_id,))
    return {'reset':business_id}

def seed_showcase(business_id:str='casa_coqui'):
    """This builds the demo story when the app starts: a Week 1 check, approval of the issues it
    found, then a Week 3 re-check. Everything here is labeled as sample data.
    """
    with conn() as c:
        if c.execute('SELECT COUNT(*) FROM eval_runs WHERE business_id=?',(business_id,)).fetchone()[0]:
            return
    run_eval(business_id,'mock_baseline')
    with LOCK,conn() as c:
        for t in rows(c,"SELECT id FROM tickets WHERE business_id=? AND status='pending'",(business_id,)):
            c.execute("UPDATE tickets SET status='approved',reviewer_note=?,updated_at=? WHERE id=?",
                      ('Seeded demo: owner approved correcting the source listing.',timestamp(),t['id']))
            c.execute('INSERT INTO audit(ticket_id,action,note,created_at) VALUES (?,?,?,?)',
                      (t['id'],'approve','Seeded demo approval (synthetic reviewer).',timestamp()))
    run_eval(business_id,'mock_after')

@app.post('/api/evals/replay/{business_id}')
def api_replay(business_id:str):
    """This resets the demo business and replays the whole story from Week 1."""
    api_reset_business(business_id); seed_showcase(business_id)
    return api_list_evals(business_id)

if os.getenv('PROOF_FLOWER_SEED','1')=='1':
    try: seed_showcase()
    except Exception as exc: print('Showcase seed skipped:',exc)


# =====================================================================
# SET UP A BUSINESS FROM A CSV
# =====================================================================
CTX_PHRASE={'lunch':' at lunch','dinner':' for dinner','each':' each','breakfast':' at breakfast','brunch':' at brunch'}

def accuracy_questions(biz:str, facts:list[dict], prefix:str, limit:int=12)->list[dict]:
    """This writes one plain question per approved fact (price, hours, address, availability,
    policy), so every fact the owner approved gets checked. Written by code, not AI, so each
    question is guaranteed to point at the right fact.
    """
    out, seen = [], set()
    for f in facts:
        if not f['approved']: continue
        key=(f['product_id'],f['field'],f['context'])
        if key in seen: continue
        seen.add(key); p, ctx = f['product_name'], f['context']
        if f['field']=='price_usd':
            text=f"How much is the {p} at {biz}{CTX_PHRASE.get(ctx, f' ({ctx})' if ctx else '')}?"
        elif f['field']=='availability':
            text=f"Is {biz} still open, or did it close?" if f['product_id']=='business' else f"Can I get the {p} at {biz} right now?"
        elif f['field']=='hours':
            text=f"What are {biz}'s opening hours?"
        elif f['field']=='address':
            text=f"What is the address of {biz}?"
        else:
            c=ctx.lower()
            text=(f"Does {biz} deliver?" if 'deliver' in c else
                  f"Can I make a reservation at {biz}?" if 'reserv' in c else
                  f"Does {biz} offer takeout?" if ('takeout' in c or 'pickup' in c) else
                  f"What is the minimum group size for {biz} catering?" if 'cater' in c else
                  f"What is {biz}'s return policy?" if 'return' in c else
                  f"What is {biz}'s {ctx or 'store'} policy?")
        out.append({'id':f'{prefix}-A{len(out)+1:02d}','type':'accuracy','text':text,
                    'product_id':f['product_id'],'target_field':f['field'],'context':ctx})
        if len(out)>=limit: break
    return out

def template_questions(biz:str, facts:list[dict], location:str, category:str, prefix:str,
                       n_vis:int, n_stress:int)->list[dict]:
    """This writes local-search and trick questions from simple templates. It's the backup when
    Gemini isn't available, so setting up a business always works.
    """
    cat=category or 'local business'; loc=location or 'near me'; where=f'in {loc}' if location else 'near me'
    items=[re.sub(r'\s*\(.*?\)','',f['product_name']).strip() for f in facts if f['approved'] and f['product_id']!='business']
    items=list(dict.fromkeys(items))
    vis=[f'What are the best {cat}s {where}?']+[f'Where can I get good {i} {where}?' for i in items]+\
        [f'Any good {cat} {where} that is open on weekends?', f'Which {cat} {where} do locals recommend?']
    stress=[f'Does {biz} have a secret happy hour discount on Mondays?',
            f'Is everything at {biz} certified organic?',
            f'Does {biz} offer free delivery on every order?',
            f'Does {biz} give a student discount of 50%?']
    out=[{'id':f'{prefix}-V{i+1:02d}','type':'visibility','text':t,'product_id':'','target_field':'','context':''}
         for i,t in enumerate(vis[:n_vis])]
    out+=[{'id':f'{prefix}-S{i+1:02d}','type':'stress','text':t,'product_id':'','target_field':'','context':''}
          for i,t in enumerate(stress[:n_stress])]
    return out

SIMPLE_COLS={'name':('product name','product','item','item name','name','title'),
             'price':('price','unit price','price (usd)','price usd','cost'),
             'stock':('stock quantity','stock','quantity','qty','inventory','in stock','available'),
             'sku':('sku','item id','product id','id','code')}

def convert_simple_catalog(items:list[dict], business_name:str, website:str='')->list[dict]:
    """This lets an owner upload the product list they already have (e.g. SKU, Product Name, Price,
    Stock Quantity) instead of our template. It turns each product into two facts we can check:
    its price, and whether it's available (stock above 0). Facts get the website as their source;
    without a website they are labeled sample data, since nothing links them to an official page.
    """
    if not business_name.strip():
        raise ValueError("This looks like a regular product list. Type the business name in the form so we know whose products these are.")
    lower={k.strip().lower():k for k in items[0].keys() if k}
    col={role:next((lower[c] for c in names if c in lower),None) for role,names in SIMPLE_COLS.items()}
    if not col['name'] or not (col['price'] or col['stock']):
        raise ValueError('Could not find a product name and a price or stock column in this file. Use the template instead.')
    bid=re.sub(r'[^a-z0-9]+','_',business_name.lower()).strip('_')[:40] or 'my_business'
    web=website.strip(); sample=not web.startswith('https://'); today=datetime.now().strftime('%Y-%m-%d')
    out=[]
    for n,row in enumerate(items,1):
        name=(row.get(col['name']) or '').strip()
        if not name: continue
        pid=re.sub(r'[^a-z0-9]+','_',((row.get(col['sku']) if col['sku'] else '') or name).lower()).strip('_')[:40] or f'item_{n}'
        base={'business_id':bid,'business_name':business_name.strip(),'product_id':pid,'product_name':name,
              'context':'','source_url':'' if sample else web,'checked_at':today,'approved':'yes','is_demo':'yes' if sample else 'no'}
        if col['price']:
            price=(row.get(col['price']) or '').replace('$','').replace(',','').strip()
            try: out.append({**base,'fact_id':f'{bid}-{pid}-price','field':'price_usd','value':f'{float(price):.2f}'})
            except ValueError: pass
        if col['stock']:
            q=(row.get(col['stock']) or '').strip().lower()
            try: avail='available' if float(q)>0 else 'unavailable'
            except ValueError: avail='available' if q in ('yes','true','in stock','available') else 'unavailable' if q in ('no','false','out of stock','0') else ''
            if avail: out.append({**base,'fact_id':f'{bid}-{pid}-avail','field':'availability','value':avail})
    if not out: raise ValueError('No products with a name and a readable price or stock were found.')
    return out

class BusinessSetup(BaseModel):
    """This is the shape of a 'set up a business' request: the fact spreadsheet plus where the
    business is and what kind of business it is."""
    csv_text: str = Field(min_length=20, max_length=250000)
    location: str = Field(default='', max_length=80)
    category: str = Field(default='', max_length=60)
    website: str = Field(default='', max_length=300)
    business_name: str = Field(default='', max_length=80)   # only needed for a plain product list
    visibility: int = Field(default=5, ge=1, le=10)
    stress: int = Field(default=3, ge=1, le=6)

@app.post('/api/business/setup')
def api_business_setup(payload:BusinessSetup):
    """This sets up a business from its fact spreadsheet: it imports the facts, optionally checks
    its website, and builds its locked question list: one question per approved fact, plus
    local-search and trick questions written by Gemini (or templates if Gemini isn't available).
    After this, the dashboard can run a live check on it.
    """
    try:
        items=list(csv.DictReader(io.StringIO(payload.csv_text.lstrip('\ufeff'))))
    except csv.Error as exc:
        raise HTTPException(400,f'Could not read the CSV: {exc}') from exc
    items=[r for r in items if any((v or '').strip() for v in r.values() if isinstance(v,str))]   # skip blank rows
    if not items: raise HTTPException(400,'The CSV has no data rows.')
    if 'business_id' not in items[0]:
        try: items=convert_simple_catalog(items,payload.business_name,payload.website)
        except ValueError as exc: raise HTTPException(400,str(exc)) from exc
    ids={(r.get('business_id') or '').strip() for r in items}
    if len(ids)!=1 or not next(iter(ids)):
        found=', '.join(sorted(i or '(blank)' for i in ids))
        raise HTTPException(400,f'Every row needs the same business_id. Found: {found}.')
    bid=next(iter(ids))
    if bid=='casa_coqui': raise HTTPException(400,'That ID belongs to the demo business. Use a different business_id.')
    if not SAFE_ID.match(bid): raise HTTPException(400,'business_id must use only lowercase letters, numbers and underscores (e.g. my_cafe).')
    try:
        with LOCK,conn() as c:
            insert_csv_rows(c,items,allow_demo=True)
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from exc
    with conn() as c:
        facts=rows(c,'SELECT * FROM facts WHERE business_id=? AND approved=1',(bid,))
    if not facts: raise HTTPException(400,"No facts are marked approved=yes, so there's nothing to check against.")
    biz=facts[0]['business_name']; synthetic=all(f['is_demo'] for f in facts)
    signals={}
    if payload.website.strip():
        try: signals=geo.site_audit(payload.website.strip())
        except ValueError: signals={}
    prefix=re.sub(r'[^A-Z0-9]','',bid.upper())[:6] or 'BIZ'
    qs=accuracy_questions(biz,facts,prefix)
    source='template'
    extra=template_questions(biz,facts,payload.location,payload.category,prefix,payload.visibility,payload.stress)
    if os.getenv('GEMINI_API_KEY'):
        try:
            batch=generate_questions(biz,facts,{'visibility':payload.visibility,'accuracy':0,'stress':payload.stress},
                                     location=payload.location,category=payload.category)
            gen=[q for q in batch.questions if q.type in ('visibility','stress')]
            if gen:
                counters={'visibility':0,'stress':0}; extra=[]
                for q in gen:
                    counters[q.type]+=1
                    extra.append({'id':f"{prefix}-{'V' if q.type=='visibility' else 'S'}{counters[q.type]:02d}",
                                  'type':q.type,'text':q.text,'product_id':q.product_id if q.type=='stress' else '',
                                  'target_field':q.target_field if q.type=='stress' else '','context':''})
                source='gemini'
        except AIError:
            pass
    version=f'{bid}-v{datetime.now().strftime("%m%d%H%M")}'
    with LOCK,conn() as c:
        used={r[0] for r in c.execute('SELECT DISTINCT question_id FROM runs WHERE business_id=?',(bid,))}
        c.execute(f"DELETE FROM questions WHERE business_id=? AND origin='evalset'"+
                  (f" AND id NOT IN ({','.join('?'*len(used))})" if used else ''),(bid,*used))
        c.execute("UPDATE questions SET origin='retired' WHERE business_id=? AND origin='evalset'",(bid,))
        for q in extra+qs:
            c.execute('''INSERT OR REPLACE INTO questions VALUES (?,?,?,?,?,?,?,?)''',
                      (q['id'],bid,q['type'],q['text'],q['product_id'],q['target_field'],q['context'],'evalset'))
        c.execute('''INSERT INTO businesses VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(business_id) DO UPDATE SET
                     business_name=excluded.business_name,location=excluded.location,category=excluded.category,
                     website=excluded.website,signals=excluded.signals,eval_version=excluded.eval_version,
                     synthetic=excluded.synthetic''',
                  (bid,biz,payload.location,payload.category,payload.website,json.dumps(signals),version,int(synthetic),timestamp()))
    return {'business_id':bid,'business_name':biz,'facts':len(facts),'questions':len(extra+qs),
            'question_source':source,'website_checked':bool(signals),'synthetic':synthetic}

@app.get('/api/businesses')
def api_businesses():
    """This lists every business the dashboard can show: the demo business plus any set up from a CSV."""
    out=[]
    demo=evals.load_profile('casa_coqui')
    if demo: out.append({'business_id':'casa_coqui','business_name':demo['business_name'],'location':demo.get('location',''),'demo':True})
    with conn() as c:
        for b in rows(c,'SELECT business_id,business_name,location,synthetic FROM businesses ORDER BY created_at'):
            out.append({'business_id':b['business_id'],'business_name':b['business_name'],'location':b['location'],
                        'demo':False,'sample_data':bool(b['synthetic'])})
    return {'businesses':out}

@app.post('/api/business/{business_id}/remove')
def api_business_remove(business_id:str):
    """This removes a business set up from a CSV, with all its facts, questions, checks and tickets.
    The demo business can't be removed (use Replay instead).
    """
    if business_id=='casa_coqui': raise HTTPException(400,'The demo business cannot be removed.')
    api_reset_business(business_id)
    with LOCK,conn() as c:
        c.execute('DELETE FROM questions WHERE business_id=?',(business_id,))
        c.execute('DELETE FROM facts WHERE business_id=?',(business_id,))
        c.execute('DELETE FROM businesses WHERE business_id=?',(business_id,))
    return {'removed':business_id}

@app.get('/api/templates/business.csv')
def business_csv_template():
    """This lets owners download a blank fact spreadsheet with example rows to fill in."""
    return FileResponse(BASE/'data/business_TEMPLATE.csv',media_type='text/csv',filename='business_TEMPLATE.csv')
