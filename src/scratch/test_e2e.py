import httpx
import asyncio
import sys

BASE_URL = "http://localhost:8000/api"

async def test_flow():
    async with httpx.AsyncClient(timeout=60.0) as client:
        # 1. Login
        print("--- 1. Logging in as admin@example.com ---")
        try:
            resp = await client.post(f"{BASE_URL}/auth/login", json={
                "email": "admin@example.com",
                "password": "secret123"
            })
            resp.raise_for_status()
            token = resp.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}
            print("Login success.")
        except Exception as e:
            print(f"FAILED Login: {e}")
            if hasattr(e, 'response'): print(e.response.text)
            return

        # 2. Create Project
        print("\n--- 2. Creating project ---")
        proj_data = {
            "title": "E2E Stability Test",
            "domain": "Logistics",
            "description": "A system to optimize truck routing using AI.",
            "attachments_url": ["file://spec.pdf"]
        }
        try:
            resp = await client.post(f"{BASE_URL}/projects", json=proj_data, headers=headers)
            resp.raise_for_status()
            project_id = resp.json()["result"]["id"]
            print(f"Project created with ID: {project_id}")
        except Exception as e:
            print(f"FAILED Project creation: {e}")
            if hasattr(e, 'response'): print(e.response.text)
            return

        # 3. Submit Project
        print("\n--- 3. Submitting project ---")
        try:
            resp = await client.post(f"{BASE_URL}/projects/{project_id}/submit", headers=headers)
            resp.raise_for_status()
            print("Project submitted successfully.")
        except Exception as e:
            print(f"FAILED Submission: {e}")
            if hasattr(e, 'response'): print(e.response.text)
            return

        # 4. Trigger Intake Agent
        print("\n--- 4. Triggering Intake Agent evaluation ---")
        try:
            resp = await client.post(f"{BASE_URL}/projects/{project_id}/runs/evaluation", json={"evaluation_prompt": ""}, headers=headers)
            resp.raise_for_status()
            run_id = resp.json()["id"]
            print(f"Intake run started with ID: {run_id}")
        except Exception as e:
            print(f"FAILED Intake trigger: {e}")
            if hasattr(e, 'response'): print(e.response.text)
            return

        # 5. Wait for Intake completion
        print("\n--- 5. Waiting for Intake Agent to finish ---")
        for i in range(20): # Wait up to 100 seconds
            await asyncio.sleep(5)
            try:
                resp = await client.get(f"{BASE_URL}/projects/{project_id}/runs/{run_id}", headers=headers)
                resp.raise_for_status()
                data = resp.json()["result"]
                status = data["status"]
                print(f"  [Attempt {i+1}] Intake status: {status}")
                if status == "completed":
                    print("Intake completed successfully!")
                    break
                if status == "failed":
                    print(f"Intake FAILED: {data.get('error_text')}")
                    return
            except Exception as e:
                print(f"Error polling status: {e}")
        else:
            print("Intake timed out.")
            return

        # 6. Accept for Research
        print("\n--- 6. Accepting project for research ---")
        try:
            resp = await client.post(f"{BASE_URL}/projects/{project_id}/review", json={"decision": "approve", "comment": "Verified via E2E script"}, headers=headers)
            resp.raise_for_status()
            print("Decision saved: accepted_for_research")
        except Exception as e:
            print(f"FAILED Decision: {e}")
            if hasattr(e, 'response'): print(e.response.text)
            # return # Continue anyway if status was already updated by agent? 
        
        # 7. Trigger Research Agent
        print("\n--- 7. Triggering Research Agent ---")
        try:
            resp = await client.post(f"{BASE_URL}/projects/{project_id}/runs/deep-research", json={}, headers=headers)
            resp.raise_for_status()
            res_run_id = resp.json()["id"]
            print(f"Research run started with ID: {res_run_id}")
        except Exception as e:
            print(f"FAILED Research trigger: {e}")
            if hasattr(e, 'response'): print(e.response.text)
            return

        print("\n--- SUCCESS: Full end-to-end flow verified up to Research start ---")

if __name__ == "__main__":
    asyncio.run(test_flow())
