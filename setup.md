# < NEON SETUP GUIDE />
```
npx neon@latest
neon init -y --org-id org-lucky-darkness-43020680 --project-id cold-hall-89784657 --branch production --services postgres
neon deploy
```

# < backend guide />
```
python3 -m venv aura
source aura/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```
<table>
<tr><td>
🛈 if no requirements.txt available , create it and paste this
</td></tr></table>

```
fastapi>=0.115,<1
uvicorn[standard]>=0.30,<1
sqlalchemy>=2.0.30,<3
psycopg[binary]>=3.2,<4
pgvector>=0.3.2,<1
pydantic>=2.8,<3
pydantic-settings>=2.4,<3
PyJWT>=2.9,<3
httpx>=0.27,<1
pytest>=8.2,<9
```
```
uvicorn app.main:app --reload --port 8000
```
# < extension guide />
```
pnpm install
pnpm approve-builds
pnpm run build
```
# < dashboard guide />
```
pnpm install
pnpm approve-builds
pnpm run dev
```
<p align ="center"> Provided to you by CHURNCE® all rights reserved © 2026</p>