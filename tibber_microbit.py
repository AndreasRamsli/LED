import atexit
import signal
import asyncio
from datetime import datetime, timedelta, timezone
from tibber import Tibber, gql_queries
import serial
from dateutil import parser
import logging
import json
import backoff

#TODO:

#BUG:
#Find out why the cache is not updating properly even though the API was called

logging.basicConfig(filename='tibber_microbit.log', level=logging.INFO, format='%(asctime)s %(message)s')

class MicroBitCommunicator:
    def __init__(self, port='/dev/cu.usbmodem11102', baudrate=115200): #/dev/ttyACM0
        self.port = port
        self.baudrate = baudrate
        self.serial_conn = None
        atexit.register(self.disconnect)  # Register disconnect to be called at exit
        signal.signal(signal.SIGINT, self.handle_signal)  # Handle interrupt signal
        signal.signal(signal.SIGTERM, self.handle_signal)  # Handle termination signal

    def connect(self):
        try:
            self.serial_conn = serial.Serial(self.port, self.baudrate)
            logging.info(f"Successfully connected to micro:bit on {self.port}")
        except Exception as e:
            logging.error(f"Failed to connect to micro:bit on {self.port}: {e}", exc_info=True)
    
    def send_to_microbit(self, message, startsAt, total):
        full_message = f"{message},{startsAt},{round(total,2)}\n"
        try:
            if self.serial_conn:  
                self.serial_conn.write(full_message.encode('utf-8')) 
                logging.info(f"Sent to micro:bit: {full_message}")
        except Exception as e:
            logging.error(f"Failed to send to micro:bit: {e}", exc_info=True)

    def disconnect(self):
        termination_message = "TERMINATE\n"
        try:
            if self.serial_conn:
                self.serial_conn.write(termination_message.encode('utf-8'))
                logging.info("Sent termination signal to micro:bit.")
        except Exception as e:
            logging.error(f"Failed to send termination signal to micro:bit: {e}", exc_info=True)
        finally:
            if self.serial_conn:
                self.serial_conn.close()
                logging.info("Disconnected from micro:bit.")
                
    def handle_signal(self, signum, frame):
        logging.info(f"Received signal: {signal.Signals(signum).name}")
        self.disconnect()
        exit(0)


def send_update_to_microbit(cache, microbit_communicator):
    price_level, startsAt, total = cache.get_current_price_info()
    logging.info(f"Price Level: {price_level}, Starts At: {startsAt}, Total: {total}")
    microbit_communicator.send_to_microbit(price_level, startsAt, total)


class PriceCache:
    def __init__(self):
        self.cache = {'today': {}, 'tomorrow': {}}

    def update_cache(self, price_info):
        logging.debug(f"Received price info for updating cache: {price_info}")
        self.clear_old_prices()

        for period in ['today', 'tomorrow']:
            new_prices = price_info['viewer']['home']['currentSubscription']['priceInfo'][period]
            new_prices_json = json.dumps(new_prices, sort_keys=True)
            existing_prices_json = json.dumps([self.cache[period][hour] for hour in sorted(self.cache[period])], sort_keys=True)

            if new_prices_json != existing_prices_json:
                logging.info(f'Updating cache with new {period} prices.')
                self.cache[period] = {str(parser.isoparse(entry['startsAt']).hour): entry for entry in new_prices}
            else:
                logging.info(f'No new price info for {period}.')
        self.log_cache_contents()

    def get_current_price_info(self):
        now = datetime.now(timezone.utc).astimezone()
        current_hour = str(now.hour)
        day = self.determine_current_period()

        if current_hour in self.cache[day]:
            entry = self.cache[day][current_hour]
            return entry['level'], parser.isoparse(entry['startsAt']).strftime('%H:%M'), entry['total']
        
        return 'Unknown', '00:00', 0.0

    def determine_current_period(self):
        now = datetime.now(timezone.utc).astimezone().date()
        tomorrow_entries = list(self.cache['tomorrow'].values())
        
        if tomorrow_entries and now >= parser.isoparse(tomorrow_entries[0]['startsAt']).date():
            return 'tomorrow'
        return 'today'

    def clear_old_prices(self):
        """Adjusts the cache based on the current date, removing outdated entries."""
        now = datetime.now(timezone.utc).astimezone().date()
        today_entries = list(self.cache['today'].values())
        
        if today_entries and now > parser.isoparse(today_entries[0]['startsAt']).date():
            logging.info("Clearing outdated 'today' prices from the cache.")
            self.cache['today'] = self.cache['tomorrow']
            self.cache['tomorrow'] = {}

    def log_cache_contents(self):
        logging.info("Current Cache State:")
        for day, prices in self.cache.items():
            logging.info(f"{day}:")
            for hour, price_info in prices.items():
                logging.info(f"  Hour: {hour}, Price Info: {price_info}")


async def daily_updates(tibber_connection, cache, home_id, microbit_communicator):
    await fetch_prices_daily(tibber_connection, cache, home_id, microbit_communicator)
    await hourly_update(cache, microbit_communicator)


async def fetch_prices_daily(tibber_connection, cache, home_id, microbit_communicator):
    while True:
        now = datetime.now(timezone.utc).astimezone()
        
        data = await fetch_prices(tibber_connection, home_id)
        if data:
            cache.update_cache(data)
            asyncio.create_task(hourly_update(cache, microbit_communicator))
        else:
            logging.info("Waiting for the next scheduled fetch due to failed data retrieval.")
        
        # Check and fetch tomorrow's prices if not already fetched
        if '0' not in cache.cache['tomorrow']:
            await attempt_fetch_tomorrow_prices(tibber_connection, cache, home_id, now, microbit_communicator)
        
        # Schedule the next daily fetch for around 24 hours later
        await schedule_next_daily_fetch(now)


@backoff.on_exception(backoff.expo, Exception, max_tries=5)
async def fetch_prices(tibber_connection, home_id):
    query = gql_queries.PRICE_INFO % home_id
    try:
        data = await tibber_connection.execute(query)
        if data:
            logging.debug(f"Raw data returned from API: {data}")
            return data  # Return the full data for external validation
        else:
            logging.info("No data returned from the API.")
    except Exception as e:
        logging.error(f"Error fetching prices: {e}", exc_info=True)
    return None  # Return None if no data or an error occurred


async def hourly_update(cache, microbit_communicator):
    while True:
        send_update_to_microbit(cache, microbit_communicator)

        now = datetime.now(timezone.utc).astimezone()
        next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        wait_seconds = (next_hour - now).total_seconds()

        logging.info(f"Next hourly update in {str(timedelta(seconds=int(wait_seconds)))}, at {next_hour.strftime('%Y-%m-%d %H:%M:%S')}")
        await asyncio.sleep(wait_seconds)

            
async def attempt_fetch_tomorrow_prices(tibber_connection, cache, home_id):
    now = datetime.now(timezone.utc).astimezone()
    wait_time = ((18 - now.hour) * 3600 - now.minute * 60 - now.second) if now.hour < 18 else 0
    await asyncio.sleep(wait_time)

    retry_count = 0
    max_retries = 10
    retry_interval = 1800

    while retry_count < max_retries:
        data_fetched = await fetch_prices(tibber_connection, home_id)
        if data_fetched:
            tomorrow_data = data_fetched.get('viewer', {}).get('home', {}).get('currentSubscription', {}).get('priceInfo', {}).get('tomorrow', [])
            if all('total' in entry for entry in tomorrow_data):
                logging.info("Successfully fetched complete tomorrow's prices.")
                cache.update_cache(data_fetched)
                break
            else:
                logging.info("Incomplete data for tomorrow, retrying...")
        else:
            logging.info("Failed to fetch any data, retrying...")
        
        retry_count += 1
        await asyncio.sleep(retry_interval)

    if retry_count >= max_retries:
        logging.error("Failed to fetch complete data for tomorrow after maximum retries.")


async def schedule_next_daily_fetch(now):
    next_fetch_time = (now + timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0)
    wait_seconds = (next_fetch_time - now).total_seconds()
    logging.info(f"Waiting for next daily price update in {str(timedelta(seconds=int(wait_seconds)))} (hh:mm:ss), at {next_fetch_time.strftime('%Y-%m-%d %H:%M:%S')}")
    await asyncio.sleep(wait_seconds)


async def main():
    logging.info("Starting main application process")
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
