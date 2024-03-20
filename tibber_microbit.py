import asyncio
from datetime import datetime, timedelta, timezone
from tibber import Tibber, gql_queries
import serial
from dateutil import parser
import logging
import json

# Sensors: accelerometer, microphone, temperature, light
# Inputs: buttons, USB, 
# Outputs: LEDs, Speaker, 

logging.basicConfig(filename='tibber_microbit.log', level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

class MicroBitCommunicator:
    def __init__(self, port='/dev/cu.usbmodem11102', baudrate=115200): #/dev/ttyACM0
        self.port = port
        self.baudrate = baudrate
        self.serial_conn = None

    def connect(self):
        try:
            self.serial_conn = serial.Serial(self.port, self.baudrate)
            logging.info("Successfully connected to micro:bit")
        except Exception as e:
            logging.error(f"Connection failed: {e}")
            raise  # Raising exception to handle failure appropriately

    def send_to_microbit(self, message, startsAt, total):
        try:
            full_message = f"{message},{startsAt},{round(total,2)}\n"
            self.serial_conn.write(full_message.encode('utf-8'))
            logging.info(f"Message sent to micro:bit: {full_message}")
        except Exception as e:
            logging.error(f"Sending message failed: {e}")
            self.reconnect()  # Attempt to reconnect on send failure

    def disconnect(self):
        if self.serial_conn:
            self.serial_conn.close()
            logging.info("Micro:bit disconnected")

    def reconnect(self):
        logging.info("Attempting to reconnect to micro:bit...")
        self.disconnect()
        self.connect()


def send_update_to_microbit(cache, microbit_communicator):
    try:
        price_level, startsAt, total = cache.get_current_price_info()
        microbit_communicator.send_to_microbit(price_level, startsAt, total)
    except Exception as e:
        logging.error(f"Update send failed: {e}")
        microbit_communicator.reconnect()  # Reconnect in case of communication failure


class PriceCache:
    def __init__(self):
        self.cache = {'today': {}, 'tomorrow': {}}

    def update_cache(self, price_info):
        today_prices = price_info['viewer']['home']['currentSubscription']['priceInfo']['today']
        tomorrow_prices = price_info['viewer']['home']['currentSubscription']['priceInfo']['tomorrow']

        new_today_json = json.dumps(today_prices, sort_keys=True)
        new_tomorrow_json = json.dumps(tomorrow_prices, sort_keys=True)
        existing_today_json = json.dumps([self.cache['today'][hour] for hour in sorted(self.cache['today'])], sort_keys=True)
        existing_tomorrow_json = json.dumps([self.cache['tomorrow'][hour] for hour in sorted(self.cache['tomorrow'])], sort_keys=True)

        if new_today_json != existing_today_json:
            logging.info('Updating cache with new today prices.')
            for entry in today_prices:
                hour = parser.isoparse(entry['startsAt']).hour
                self.cache['today'][str(hour)] = entry

        if new_tomorrow_json != existing_tomorrow_json:
            logging.info('Updating cache with new tomorrow prices.')
            for entry in tomorrow_prices:
                hour = parser.isoparse(entry['startsAt']).hour
                self.cache['tomorrow'][str(hour)] = entry
        else:
            logging.info('No new price info for cache')

    def get_current_price_info(self):
        now = datetime.now(timezone.utc).astimezone()
        current_hour = str(now.hour)

        day = 'today'
        if any(datetime.strptime(entry['startsAt'], '%Y-%m-%dT%H:%M:%S.%f%z').date() > now.date() for entry in self.cache['today'].values()):
            day = 'tomorrow'

        if current_hour in self.cache[day]:
            entry = self.cache[day][current_hour]
            return entry['level'], parser.isoparse(entry['startsAt']).strftime('%H:%M'), entry['total']
        return 'Unknown', '00:00', 0.0




async def daily_updates(tibber_connection, cache, home_id, microbit_communicator):
    await fetch_prices_daily(tibber_connection, cache, home_id, microbit_communicator)
    await hourly_update(cache, microbit_communicator)


async def fetch_prices_daily(tibber_connection, cache, home_id, microbit_communicator):
    initial_fetch_done = False
    while True:
        now = datetime.now(timezone.utc).astimezone()

        if not initial_fetch_done:
            await fetch_prices(tibber_connection, cache, home_id)
            asyncio.create_task(hourly_update(cache, microbit_communicator))
            initial_fetch_done = True

        if '0' not in cache.cache['tomorrow']:
            await attempt_fetch_tomorrow_prices(tibber_connection, cache, home_id, now, microbit_communicator)
    
        await schedule_next_daily_fetch(now)



async def fetch_prices(tibber_connection, cache, home_id):
    query = gql_queries.PRICE_INFO % home_id
    data = await tibber_connection.execute(query)
    if data:
        cache.update_cache(data)
        logging.info("Data returned from API.")
        return True
    else:
        logging.info("No data returned from the API.")
        return False



async def hourly_update(cache, microbit_communicator):
    while True:
        send_update_to_microbit(cache, microbit_communicator)

        now = datetime.now(timezone.utc).astimezone()
        next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        wait_seconds = (next_hour - now).total_seconds()

        logging.info(f"Next hourly update in {str(timedelta(seconds=int(wait_seconds)))}, at {next_hour.strftime('%Y-%m-%d %H:%M:%S')}")
        await asyncio.sleep(wait_seconds)

            

async def attempt_fetch_tomorrow_prices(tibber_connection, cache, home_id, now, microbit_communicator):
    first_attempt_time = now.replace(hour=18, minute=0, second=0, microsecond=0) if now.hour < 18 else now
    
    wait_seconds_until_first_attempt = max((first_attempt_time - now).total_seconds(), 0)
    if wait_seconds_until_first_attempt > 0:
        logging.info(f"Waiting until 18:00 for the first attempt to fetch tomorrow's data in {str(timedelta(seconds=int(wait_seconds_until_first_attempt)))} (hh:mm:ss), at {first_attempt_time.strftime('%Y-%m-%d %H:%M:%S')}")
        await asyncio.sleep(wait_seconds_until_first_attempt)
    
    while '0' not in cache.cache['tomorrow']:
        data_fetched = await fetch_prices(tibber_connection, cache, home_id)
        if data_fetched:
            send_update_to_microbit(cache, microbit_communicator)
        await asyncio.sleep(3600)

    await schedule_next_daily_fetch(now)



async def schedule_next_daily_fetch(now):
    # Schedule next fetch for 18:00 the next day
    next_fetch_time = (now + timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0)
    wait_seconds = (next_fetch_time - now).total_seconds()
    logging.info(f"Waiting for next daily price update in {str(timedelta(seconds=int(wait_seconds)))} (hh:mm:ss), at {next_fetch_time.strftime('%Y-%m-%d %H:%M:%S')}")
    await asyncio.sleep(wait_seconds)



async def main():
    TOKEN = "U4L8yS_OHsfgKndAhNQZ8K-JYElbNUagYvToCF3ZPVE"
    USER_AGENT = "LED_client"
    HOME_ID = "975996b6-e7ca-4fbf-9f72-61e2df95bc0c"

    tibber_connection = Tibber(access_token=TOKEN, user_agent=USER_AGENT)
    await tibber_connection.update_info()
    
    cache = PriceCache()
    microbit_communicator = MicroBitCommunicator()
    microbit_communicator.connect()

    await daily_updates(tibber_connection, cache, HOME_ID, microbit_communicator)

    await tibber_connection.close_connection()
    microbit_communicator.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
