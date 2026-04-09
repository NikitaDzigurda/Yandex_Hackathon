import httpx
import asyncio
import sys

BASE_URL = "http://localhost:8000/api"

async def test_flow():
    async with httpx.AsyncClient(timeout=60.0) as client:
        # 1. Login
        print("--- 1. Logging in as admin@example.com ---")
        resp = await client.post(f"{BASE_URL}/auth/login", json={
            "email": "admin@example.com",
            "password": "secret123"
        })
        resp.raise_for_status()
        token = resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 2. Create Project
        print("\n--- 2. Creating project ---")
        proj_data = {
            "title": f"Idempotency Test {asyncio.get_event_loop().time()}",
            "domain": "AI",
            "description": "Unique description for hashing.",
            "attachments_url": []
        }
        resp = await client.post(f"{BASE_URL}/projects", json=proj_data, headers=headers)
        resp.raise_for_status()
        project_id = resp.json()["result"]["id"]
        print(f"Project created: {project_id}")

        # 3. Submit
        await client.post(f"{BASE_URL}/projects/{project_id}/submit", headers=headers)

        # 4. Trigger Intake Run 1
        print("\n--- 3. Triggering Intake Run 1 ---")
        resp = await client.post(f"{BASE_URL}/projects/{project_id}/runs/evaluation", json={"evaluation_prompt": ""}, headers=headers)
        run1_id = resp.json()["id"]
        print(f"Run 1 ID: {run1_id}")

        # 5. Wait for Run 1 completion (short-circuiting logic for test speed: just wait 5s and check)
        print("Waiting for Run 1 to start/finish...")
        await asyncio.sleep(10) # Give it some time to at least start

        # 6. Trigger Intake Run 2 (should be same content)
        # Note: Idempotency only returns COMPLETED runs. So we MUST wait for completion.
        print("\n--- 4. Waiting for Run 1 completion to test idempotency ---")
        for i in range(40):
            await asyncio.sleep(5)
            resp = await client.get(f"{BASE_URL}/projects/{project_id}/runs/{run1_id}", headers=headers)
            status = resp.json()["result"]["status"]
            print(f"   [Wait] Status: {status}")
            if status == "completed":
                break
        else:
            print("Run 1 did not complete in time.")
            return

        print("\n--- 5. Triggering Intake Run 2 (Same Content) ---")
        resp = await client.post(f"{BASE_URL}/projects/{project_id}/runs/evaluation", json={"evaluation_prompt": ""}, headers=headers)
        run2_id = resp.json()["id"]
        print(f"Run 2 ID: {run2_id}")

        if run1_id == run2_id:
            print("SUCCESS: Idempotency verified (Run 1 == Run 2)")
        else:
            print(f"FAILURE: Idempotency failed (Run 1 {run1_id} != Run 2 {run2_id})")

        # 7. Test Admin Bypass for Research
        print("\n--- 6. Testing Admin Bypass for Research (Project status is under_review) ---")
        resp = await client.get(f"{BASE_URL}/projects/{project_id}", headers=headers)
        print(f"Current project status: {resp.json()['result']['status']}")
        
        resp = await client.post(f"{BASE_URL}/projects/{project_id}/runs/deep-research", json={}, headers=headers)
        if resp.status_code == 200:
            print(f"SUCCESS: Research triggered successfully by admin! Run ID: {resp.json()['id']}")
        else:
            print(f"FAILURE: Research block still active. Status: {resp.status_code}, Detail: {resp.text}")

if __name__ == "__main__":
    asyncio.run(test_flow())
