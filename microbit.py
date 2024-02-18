from microbit import *

# Define images for different price levels
level_images = {
    'NORMAL': Image.HAPPY,
    'CHEAP': Image.SQUARE_SMALL,
    'VERY_CHEAP': Image.SQUARE,
    'EXPENSIVE': Image.TRIANGLE,
    'VERY_EXPENSIVE': Image.NO
}

# Initialize variables for price level, valid from timestamp, and total price
price_level = "Unknown"
valid_from = "00:00"
total_price = "0.0"

# Start listening for serial input
uart.init(baudrate=115200)

while True:
    # Check for incoming serial data
    if uart.any():
        try:
            data = uart.readline().decode('utf-8').rstrip()
            # Attempt to split the incoming data into the expected three parts
            price_level, valid_from, total_price = data.split(',')
            display.clear()  # Clear the display after receiving new data
        except ValueError:
            # If there's an error, display a sad face for a brief moment
            display.show(Image.SAD)
            sleep(1000)  # Show the error image for 1 second
            display.clear()
            continue  # Skip the rest of the loop iteration and try again

    # Use the buttons to toggle between displaying the price level and details
    if button_a.is_pressed() and button_b.is_pressed():
        # Display detailed information about price and time
        display.scroll(valid_from + "   " + total_price, delay=100)
    elif button_a.is_pressed():
        # Display the price level as text
        display.scroll(price_level, delay=100)
    else:
        # Display an image representing the price level
        display.show(level_images.get(price_level, Image.CONFUSED))
        sleep(1000)  # Update the display every second
