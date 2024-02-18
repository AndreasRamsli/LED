from microbit import *

# Initialize variables for price level, valid from timestamp, and total price
price_level = "Unknown"
valid_from = "00:00"
total_price = "0.0"

# Start listening for serial input
uart.init(baudrate=115200)

while True:
    # Check for incoming serial data
    if uart.any():
        data = uart.readline().decode('utf-8').rstrip()
        # Split the incoming data into price level, valid from, and total price
        price_level, valid_from, total_price = data.split(',')
        display.clear()  # Clear the display after receiving new data

    # Check if both buttons are pressed to display valid_from and total price
    if button_a.is_pressed() and button_b.is_pressed():
        display.scroll("Kl: " + valid_from + "Pris: " + total_price, delay=100)
    else:
        # Continuously display the price level when no buttons or only one button is pressed
        display.scroll(price_level, delay=100)
        sleep(1000)  # Update the display every second
