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
#Wrong price and price_level displayed on the microbit after longrun.
#Debug the PriceCache class, find out why the total differs from the API-total. Maybe something wrong with the update_cache function.
#the timestamps might be modified or categorized wrong. 

logging.basicConfig(filename='tibber_microbit.log', level=logging.INFO, format='%(asctime)s %(message)s')

class MicroBitCommunicator:
    def __init__(self, port='/dev/ttyACM0', baudrate=115200):
        self.port = port
        self.baudrate = baudrate
        self.serial_conn = None
        atexit.register(self.disconnect)  # Register disconnect to be called at exit
        signal.signal(signal.SIGINT, self.handle_signal)  # Handle interrupt signal
        signal.signal(signal.SIGTERM, self.handle_signal)  # Handle termination signal

    def connect(self):
        try:
            self.serial_conn = serial.Serial(self.port, self.baudrate)
            logging.info("Connected to micro:bit")
        except Exception as e:
            logging.error(f"Failed to connect to micro:bit on {self.port}: {e}")

    def disconnect(self):
        termination_message = "TERMINATE\n"
        try:
            if self.serial_conn:
                self.serial_conn.write(termination_message.encode('utf-8'))
                logging.info("Sent termination signal to micro:bit.")
        except Exception as e:
            logging.error(f"Failed to send termination signal to micro:bit: {e}")
        finally:
            if self.serial_conn:
                self.serial_conn.close()
                logging.info("Disconnected from micro:bit.")
                
    def handle_signal(self, signum, frame):
        self.disconnect()
        print('EXIT')
        exit(0)  # Exit gracefully


def send_update_to_microbit(cache, microbit_communicator):
    price_level, startsAt, total = cache.get_current_price_info()
    logging.info(f"Price Level: {price_level}, Starts At: {startsAt}, Total: {total}")
    microbit_communicator.send_to_microbit(price_level, startsAt, total)


class PriceCache:
    def __init__(self):
        self.cache = {'today': {}, 'tomorrow': {}}

    def update_cache(self, price_info):
        self.clear_old_prices()  # Ensure the cache is current before updating

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



@backoff.on_exception(backoff.expo, Exception, max_tries=5)
async def fetch_prices(tibber_connection, cache, home_id):
    try:
        query = gql_queries.PRICE_INFO % home_id
        data = await tibber_connection.execute(query)
        if data:
            cache.update_cache(data)
            logging.info(data)
            logging.info("Data returned from API.")
            return True
        else:
            logging.info("No data returned from the API.")
            return False
    except Exception as e:
        logging.error(f"Error fetching prices: {e}")
        raise  # Reraising the exception to trigger the retry mechanism



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
