import asyncio
import json
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def main():
    engine = create_async_engine("postgresql+asyncpg://postgres:postgres@localhost:5432/hackathon")
    async with engine.connect() as conn:
        res1 = await conn.execute(text("SELECT id, intake_details FROM applications WHERE intake_details IS NOT NULL"))
        apps = res1.fetchall()
        print(f"Total applications with intake_details: {len(apps)}")
        for app in apps:
            app_id, details = app
            print(f"\n--- Application {app_id} (Intake) ---")
            if not isinstance(details, dict):
                print("Error: intake_details is not a dict")
            else:
                for agent, text_val in details.items():
                    err_markers = ["error", "ошибка", "failed", "не удалось", "none", "null"]
                    if not text_val:
                        print(f"Agent '{agent}' returned empty string")
                    elif any(m in str(text_val).lower() for m in err_markers):
                        print(f"Possible error in '{agent}': {str(text_val)[:200]}...")
                    elif len(str(text_val)) < 20:
                        print(f"Suspiciously short output in '{agent}': {text_val}")
                    else:
                        print(f"Agent '{agent}' output looks OK (len: {len(str(text_val))})")

        res2 = await conn.execute(text("SELECT id, content FROM documents WHERE doc_type = 'research_report'"))
        docs = res2.fetchall()
        print(f"\nTotal research documents: {len(docs)}")
        for doc in docs:
            doc_id, content = doc
            print(f"\n--- Document {doc_id} (Research) ---")
            if not isinstance(content, dict):
                try:
                    content = json.loads(content)
                except:
                    print("Could not parse content JSON")
                    continue
            
            outputs = content.get("agent_outputs", {})
            if not outputs:
                print("Warning: no agent_outputs found in research doc!")
            
            for agent, text_val in outputs.items():
                err_markers = ["error", "ошибка", "failed", "не удалось", "none", "null"]
                if not text_val:
                    print(f"Agent '{agent}' returned empty string")
                elif any(m in str(text_val).lower() for m in err_markers):
                    print(f"Possible error in '{agent}': {str(text_val)[:200]}...")
                elif len(str(text_val)) < 20:
                    print(f"Suspiciously short output in '{agent}': {text_val}")
                else:
                    print(f"Agent '{agent}' output looks OK (len: {len(str(text_val))})")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except ImportError:
        print("Install dependencies to run this")
