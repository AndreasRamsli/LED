import sys
#sys.path.append('/Users/andreas/fun/LED/pyTibber')
sys.path.append('/home/andram/fun/LED-env/lib/python3.11/site-packages/tibber')
from tibber import Tibber
import asyncio
import websockets
import json

# Global variable for Price Level
global_price_level = None

async def subscribe_to_live_measurement(uri, token, home_id):
    global global_price_level
    query = f'''
    subscription {{
      liveMeasurement(homeId: "{home_id}") {{
        timestamp
        # Add other fields if they provide price level info
      }}
    }}
    '''
    
    async with websockets.connect(uri) as websocket:
        # Authenticate and subscribe
        await websocket.send(json.dumps({"type": "connection_init", "payload": {"Authorization": f"Bearer {token}"}}))
        await websocket.recv()  # Acknowledgement
        await websocket.send(json.dumps({"id": "1", "type": "start", "payload": {"query": query}}))

        # Listen for messages
        while True:
            response = await websocket.recv()
            data = json.loads(response)
            print(data)
            # Process incoming data and update global_price_level
            # Example: global_price_level = data['...']

async def main():
    TOKEN = "U4L8yS_OHsfgKndAhNQZ8K-JYElbNUagYvToCF3ZPVE"
    WEBSOCKET_URL = "wss://api.tibber.com/v1-beta/gql/subscriptions"
    HOME_ID = "975996b6-e7ca-4fbf-9f72-61e2df95bc0c"  # Replace with actual home ID

    await subscribe_to_live_measurement(WEBSOCKET_URL, TOKEN, HOME_ID)

if __name__ == "__main__":
    asyncio.run(main())
    print(global_price_level)
