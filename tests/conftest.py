import os
os.environ.setdefault('PROOF_FLOWER_SEED', '0')
# Tests never call the real Gemini API, even if a key is set on this machine or in .env.
# (An empty value also stops python-dotenv from loading a key from .env.)
os.environ['GEMINI_API_KEY'] = ''
os.environ['OPENAI_API_KEY'] = ''
os.environ['LIVE_EVAL_DELAY'] = '0'
