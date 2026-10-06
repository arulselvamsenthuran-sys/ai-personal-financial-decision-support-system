import asyncio
import sys
sys.path.insert(0, 'backend')
from httpx import ASGITransport, AsyncClient
from app.main import app

async def main():
    print('starting')
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url='http://test') as ac:
        print('client ready')
        try:
            print('hitting register')
            resp = await ac.post('/api/auth/register', json={"email": "test@example.com", "password": "SecurePassword123!"})
            print(resp.status_code)
            print(resp.json())
        except Exception as e:
            print("Error:", e)

if __name__ == '__main__':
    asyncio.run(main())
