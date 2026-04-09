import asyncio
import json
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def main():
    engine = create_async_engine("postgresql+asyncpg://postgres:postgres@localhost:5432/hackathon")
    async with engine.connect() as conn:
        res = await conn.execute(text("SELECT id, content FROM documents WHERE doc_type = 'research_report'"))
        docs = res.fetchall()
        for doc in docs:
            doc_id, content = doc
            if not isinstance(content, dict):
                try: content = json.loads(content)
                except: continue
            
            outputs = content.get("agent_outputs", {})
            synth = outputs.get("synthesis_manager", "")
            if len(str(synth)) < 100:
                print(f"Doc {doc_id} Synthesis: {synth}")

if __name__ == '__main__':
    asyncio.run(main())
