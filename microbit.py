from microbit import *
import music

animation_sequences = {
    'NORMAL': [(Image.HEART, 500), (Image.HEART_SMALL, 500)],
    'CHEAP': [(Image.HAPPY, 500)],
    'VERY_CHEAP': [(Image.YES, 500)],
    'EXPENSIVE': [(Image.TRIANGLE, 500)],
    'VERY_EXPENSIVE': [(Image.NO, 500)]
}


def check_for_interrupt():
    return uart.any() or button_a.is_pressed() or button_b.is_pressed()

def animate_price_level(level):
    sequence = animation_sequences.get(level, [(Image.CONFUSED, 1000)])
    while not check_for_interrupt():
        for image, delay in sequence:
            display.show(image)
            sleep(delay)
            if check_for_interrupt():
                return

price_level = "Unknown"
valid_from = "00:00"
total_price = "0.0"

uart.init(baudrate=115200)

while True:
    if uart.any():
        try:
            data = uart.readline().decode('utf-8').rstrip()
            price_level, valid_from, total_price = data.split(',')
            display.clear()
            music.play(music.BA_DING)
        except ValueError:
            display.show(Image.SAD)
            sleep(1000)
            display.clear()
            continue

    if button_a.is_pressed() and button_b.is_pressed():
        display.scroll("Time: " + valid_from + " Price: " + total_price, delay=100)
    elif button_a.is_pressed():
        display.scroll(price_level, delay=100)
    elif button_b.is_pressed():
        display.scroll(total_price, delay=100)
    else:
        animate_price_level(price_level)